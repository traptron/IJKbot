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
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    pkg_bringup = get_package_share_directory('ijkbot_bringup')
    pkg_nav2 = get_package_share_directory('ijkbot_nav2')

    # Аргументы запуска
    declare_mock_hardware = DeclareLaunchArgument(
        'mock_hardware',
        default_value='false',
        description='Использовать симуляцию моторов без реального UART (false для реального робота)'
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

    # 1. Запуск базовых систем робота (Robot State Publisher, RealSense /scan, STS3215 Driver)
    robot_bringup_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'robot.launch.py')
        ),
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

    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        declare_mock_hardware,
        declare_enable_camera,
        declare_enable_motors,
        declare_use_amcl,
        declare_initial_x,
        declare_initial_y,
        declare_initial_yaw,
        declare_map,
        declare_use_sim_time,
        declare_autostart,

        # Включение подсистем
        robot_bringup_launch,
        navigation_launch,
    ])
