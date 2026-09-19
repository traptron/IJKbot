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

    enable_camera = LaunchConfiguration('enable_camera')
    enable_motors = LaunchConfiguration('enable_motors')

    # 1. Сенсорный пайплайн (RealSense D435 + LaserScan)
    realsense_laserscan_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'realsense_laserscan.launch.py')
        ),
        condition=IfCondition(enable_camera)
    )

    # 2. Драйвер приводов STS3215 (C++ нода из пакета sts3215_driver)
    motor_driver_node = Node(
        package='sts3215_driver',
        executable='node',
        name='sts3215_driver_node',
        output='screen',
        condition=IfCondition(enable_motors)
    )

    return LaunchDescription([
        declare_enable_camera,
        declare_enable_motors,
        realsense_laserscan_launch,
        motor_driver_node,
    ])

