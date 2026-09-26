#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('bringup')
    pkg_slam = get_package_share_directory('slam_toolbox')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Использовать симуляционное время (/clock)'
    )
    declare_lidar_serial_port = DeclareLaunchArgument(
        'lidar_serial_port', default_value='/dev/ttyUSB1',
        description='Последовательный порт RPLIDAR A2M8'
    )
    declare_lidar_serial_baudrate = DeclareLaunchArgument(
        'lidar_serial_baudrate', default_value='115200',
        description='Скорость последовательного порта RPLIDAR A2M8'
    )
    declare_slam_params_file = DeclareLaunchArgument(
        'slam_params_file',
        default_value=os.path.join(pkg_slam, 'config', 'mapper_params_online_async.yaml'),
        description='Профиль параметров slam_toolbox'
    )

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'robot.launch.py')
        ),
        launch_arguments={
            'enable_camera': 'false',
            'enable_motors': 'true',
            'enable_lidar': 'true',
            'lidar_serial_port': LaunchConfiguration('lidar_serial_port'),
            'lidar_serial_baudrate': LaunchConfiguration('lidar_serial_baudrate'),
        }.items()
    )

    slam_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[
            LaunchConfiguration('slam_params_file'),
            {
                'use_sim_time': LaunchConfiguration('use_sim_time'),
                'scan_topic': '/scan',
                'base_frame': 'base_footprint',
                'odom_frame': 'odom',
                'map_frame': 'map',
            },
        ],
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_lidar_serial_port,
        declare_lidar_serial_baudrate,
        declare_slam_params_file,
        robot_launch,
        slam_node,
    ])
