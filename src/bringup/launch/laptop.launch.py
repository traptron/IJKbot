#!/usr/bin/env python3
"""
laptop.launch.py — Верхнеуровневый запуск компонентов рабочей станции (ноутбука).

Хакатон «Эвакуация» (Кубок РТК Высшая Лига).
Запускает на ноутбуке (192.168.1.20):
1. Mission Orchestrator & Web Dashboard (ijkbot_brain):
   - Подключение к локальной или внешней LLM Ollama (Qwen 3.5 9B) по адресу llm_host
   - Интерактивный судейский дашборд NiceGUI на порту 8080
   - Прием и отправка топиков в реальном времени (/cmd_vel, /odom, /goal_pose, /victim_status)
2. Распознавание QR-кодов и детекция пострадавшего (ijkbot_vision)
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
    pkg_vision = get_package_share_directory('vision')

    pkg_nav2 = get_package_share_directory('nav2')

    declare_llm_host = DeclareLaunchArgument(
        'llm_host',
        default_value='http://localhost:11434',
        description='Адрес сервера Ollama LLM (например, http://localhost:11434 или http://192.168.1.20:11434)'
    )

    declare_port = DeclareLaunchArgument(
        'port',
        default_value='8080',
        description='Порт веб-интерфейса NiceGUI'
    )

    declare_host = DeclareLaunchArgument(
        'host',
        default_value='0.0.0.0',
        description='Хост для биндинга веб-сервера'
    )

    declare_mock = DeclareLaunchArgument(
        'mock',
        default_value='false',
        description='Режим работы (false — физический робот по Wi-Fi, true — автономная симуляция)'
    )

    declare_enable_vision = DeclareLaunchArgument(
        'enable_vision',
        default_value='true',
        description='Запускать ли детекцию QR-кодов (ijkbot_vision)'
    )

    declare_enable_twist_mux = DeclareLaunchArgument(
        'enable_twist_mux',
        default_value='false',
        description='Запускать ли twist_mux в laptop.launch.py (по умолчанию false, если запущен в navigation.launch.py)'
    )

    declare_twist_mux_config = DeclareLaunchArgument(
        'twist_mux_config',
        default_value=os.path.join(pkg_nav2, 'config', 'twist_mux.yaml'),
        description='Полный путь к конфигурационному файлу twist_mux.yaml'
    )

    # 1. Нода управления миссией и Web Dashboard
    dashboard_node = Node(
        package='brain',
        executable='dashboard_app',
        name='mission_state_machine',
        output='screen',
        arguments=[
            '--host', LaunchConfiguration('host'),
            '--port', LaunchConfiguration('port'),
            '--llm-host', LaunchConfiguration('llm_host'),
            '--mock', LaunchConfiguration('mock'),
        ],
    )

    # 2. Нода считывания QR-кодов (ijkbot_vision)
    qr_reader_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_vision, 'launch', 'qr_reader.launch.py')
        ),
        condition=IfCondition(LaunchConfiguration('enable_vision'))
    )

    # 3. Нода арбитража скоростей twist_mux (опционально)
    twist_mux_node = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        output='screen',
        parameters=[LaunchConfiguration('twist_mux_config')],
        remappings=[('cmd_vel_out', '/cmd_vel')],
        condition=IfCondition(LaunchConfiguration('enable_twist_mux'))
    )

    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        declare_llm_host,
        declare_port,
        declare_host,
        declare_mock,
        declare_enable_vision,
        declare_enable_twist_mux,
        declare_twist_mux_config,

        dashboard_node,
        qr_reader_launch,
        twist_mux_node,
    ])
