#!/usr/bin/env python3
"""
system.launch.py — Единый мастер-лаунч мобильного робота IJKbot.

Запускает все подсистемы робота в одном процессе:
1. Бортовые системы (robot.launch.py):
   - Robot State Publisher и TF-дерево (rsp.launch.py)
   - Сенсорный пайплайн Intel RealSense D435 + LaserScan (/scan)
   - Низкоуровневый драйвер приводов Feetech STS3215 (diff_drive_node, одометрия 50 Гц)
2. Автономная навигация Nav2 (navigation.launch.py):
   - Статический TF map -> odom (навигация чисто по одометрии)
   - Map Server (карта полигона 4х4 м)
   - Controller Server (Regulated Pure Pursuit)
   - Velocity Smoother
   - Planner Server (Navfn A*)
   - Behavior Server
   - BT Navigator (принимает /goal_pose от Web Dashboard / LLM)
   - Lifecycle Managers (автоматический переход всех нод в Active)
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('bringup')
    pkg_nav2 = get_package_share_directory('nav2')
    pkg_vision = get_package_share_directory('vision')

    # Аргументы запуска
    declare_mock_hardware = DeclareLaunchArgument(
        'mock_hardware',
        default_value='false',
        description='Использовать симуляцию моторов без реального UART (false для реального робота)'
    )

    declare_enable_qr = DeclareLaunchArgument(
        'enable_qr',
        default_value='true',
        description='Запускать ли распознавание QR-кодов (qr_reader_node)'
    )

    declare_enable_camera = DeclareLaunchArgument(
        'enable_camera',
        default_value='true',
        description='Запускать ли RealSense D435 и генерацию /scan'
    )

    declare_enable_motors = DeclareLaunchArgument(
        'enable_motors',
        default_value='true',
        description='Запускать ли драйвер сервоприводов STS3215'
    )

    declare_use_amcl = DeclareLaunchArgument(
        'use_amcl',
        default_value='false',
        description='Использовать ли AMCL (false: навигация чисто по одометрии + static TF map->odom)'
    )

    declare_initial_x = DeclareLaunchArgument(
        'initial_x',
        default_value='0.4',
        description='Начальная координата X робота на карте полигона (м)'
    )

    declare_initial_y = DeclareLaunchArgument(
        'initial_y',
        default_value='0.4',
        description='Начальная координата Y робота на карте полигона (м)'
    )

    declare_initial_yaw = DeclareLaunchArgument(
        'initial_yaw',
        default_value='0.0',
        description='Начальный угол рыскания Yaw робота на карте (рад)'
    )

    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_nav2, 'maps', 'polygon_empty_4x4.yaml'),
        description='Полный путь к файлу статической карты полигона (.yaml)'
    )

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Использовать ли симуляционное время (/clock)'
    )

    declare_autostart = DeclareLaunchArgument(
        'autostart',
        default_value='true',
        description='Автоматический перевод lifecycle нод в состояние Active'
    )

    declare_llm_host = DeclareLaunchArgument(
        'llm_host',
        default_value='http://localhost:11434',
        description='Адрес сервера Ollama LLM (например, http://192.168.1.20:11434)'
    )

    declare_enable_brain = DeclareLaunchArgument(
        'enable_brain',
        default_value='true',
        description='Запускать ли Mission State Machine и Web Dashboard (ijkbot_brain)'
    )

    declare_enable_nav = DeclareLaunchArgument(
        'enable_nav',
        default_value='false',
        description='Запускать ли стек навигации Nav2 локально (по умолчанию false, т.к. Nav2 работает на роботе)'
    )

    declare_enable_robot = DeclareLaunchArgument(
        'enable_robot',
        default_value='false',
        description='Запускать ли базовые системы робота локально (по умолчанию false для ноутбука)'
    )

    # 1. Запуск базовых систем робота (Robot State Publisher, RealSense /scan, STS3215 Driver)
    robot_bringup_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'robot.launch.py')
        ),
        condition=IfCondition(LaunchConfiguration('enable_robot')),
        launch_arguments={
            'enable_camera': LaunchConfiguration('enable_camera'),
            'enable_motors': LaunchConfiguration('enable_motors'),
            'mock_hardware': LaunchConfiguration('mock_hardware'),
        }.items()
    )

    # 2. Запуск стека навигации Nav2
    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_nav2, 'launch', 'navigation.launch.py')
        ),
        condition=IfCondition(LaunchConfiguration('enable_nav')),
        launch_arguments={
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'autostart': LaunchConfiguration('autostart'),
            'map': LaunchConfiguration('map'),
            'use_localization': 'true',
            'use_amcl': LaunchConfiguration('use_amcl'),
            'initial_x': LaunchConfiguration('initial_x'),
            'initial_y': LaunchConfiguration('initial_y'),
            'initial_yaw': LaunchConfiguration('initial_yaw'),
        }.items()
    )

    # 3. Бортовой модуль управления миссией и веб-панель (опционально)
    brain_node = Node(
        package='brain',
        executable='dashboard_app',
        name='mission_state_machine',
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_brain')),
        arguments=['--host', '0.0.0.0', '--port', '8080', '--llm-host', LaunchConfiguration('llm_host')],
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }]
    )

    # 4. Запуск распознавания QR-кодов (ноутбук)
    qr_reader_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_vision, 'launch', 'qr_reader.launch.py')
        ),
        condition=IfCondition(LaunchConfiguration('enable_qr'))
    )

    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        declare_mock_hardware,
        declare_enable_qr,
        declare_enable_camera,
        declare_enable_motors,
        declare_use_amcl,
        declare_initial_x,
        declare_initial_y,
        declare_initial_yaw,
        declare_map,
        declare_use_sim_time,
        declare_autostart,
        declare_llm_host,
        declare_enable_brain,
        declare_enable_nav,
        declare_enable_robot,

        # Включение подсистем
        robot_bringup_launch,
        navigation_launch,
        brain_node,
        qr_reader_launch,
    ])

