#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('ijkbot_bringup')
    pkg_description = get_package_share_directory('ijkbot_description')
    pkg_driver = get_package_share_directory('sts3215_driver')

    # Аргументы запуска
    declare_enable_camera = DeclareLaunchArgument(
        'enable_camera',
        default_value='true',
        description='Запускать ли сенсорную связку (RealSense D435 + /scan)'
    )

    declare_enable_motors = DeclareLaunchArgument(
        'enable_motors',
        default_value='true',
        description='Запускать ли ноду драйвера сервоприводов STS3215'
    )

    declare_mock_hardware = DeclareLaunchArgument(
        'mock_hardware',
        default_value='false',
        description='Симуляция моторов без UART (false на реальном роботе)'
    )

    declare_color_profile = DeclareLaunchArgument(
        'color_profile',
        default_value='640x480x15',
        description='Профиль цветной камеры RealSense: разрешение и FPS'
    )

    declare_depth_profile = DeclareLaunchArgument(
        'depth_profile',
        default_value='640x480x15',
        description='Профиль модуля глубины RealSense: разрешение и FPS'
    )

    declare_scan_config_file = DeclareLaunchArgument(
        'scan_config_file',
        default_value=os.path.join(pkg_bringup, 'config', 'realsense_laserscan.yaml'),
        description='Путь к конфигурационному файлу для depthimage_to_laserscan'
    )

    declare_driver_params_file = DeclareLaunchArgument(
        'driver_params_file',
        default_value=os.path.join(pkg_driver, 'config', 'params.yaml'),
        description='Путь к конфигурационному файлу драйвера STS3215'
    )

    enable_camera = LaunchConfiguration('enable_camera')
    enable_motors = LaunchConfiguration('enable_motors')
    mock_hardware = LaunchConfiguration('mock_hardware')
    color_profile = LaunchConfiguration('color_profile')
    depth_profile = LaunchConfiguration('depth_profile')
    scan_config_file = LaunchConfiguration('scan_config_file')
    driver_params_file = LaunchConfiguration('driver_params_file')

    # 1. Описание робота и публикация TF-дерева (Robot State Publisher)
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_description, 'launch', 'rsp.launch.py')
        )
    )

    # 2. Сенсорный пайплайн (RealSense D435 + LaserScan)
    realsense_laserscan_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'realsense_laserscan.launch.py')
        ),
        condition=IfCondition(enable_camera),
        launch_arguments={
            'color_profile': color_profile,
            'depth_profile': depth_profile,
            'scan_config_file': scan_config_file,
        }.items()
    )

    # 3. Драйвер приводов STS3215 (C++ нода из пакета sts3215_driver)
    motor_driver_node = Node(
        package='sts3215_driver',
        executable='diff_drive_node',
        name='diff_drive_node',
        output='screen',
        parameters=[
            driver_params_file,
            {'mock_hardware': mock_hardware}
        ],
        condition=IfCondition(enable_motors)
    )

    return LaunchDescription([
        declare_enable_camera,
        declare_enable_motors,
        declare_mock_hardware,
        declare_color_profile,
        declare_depth_profile,
        declare_scan_config_file,
        declare_driver_params_file,
        rsp_launch,
        realsense_laserscan_launch,
        motor_driver_node,
    ])
