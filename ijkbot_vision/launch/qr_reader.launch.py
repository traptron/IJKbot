#!/usr/bin/env python3
"""Launch QR reading on the laptop."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory('ijkbot_vision')
    default_params = os.path.join(package_share, 'config', 'qr_reader.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_params),
        Node(
            package='ijkbot_vision',
            executable='qr_reader_node',
            name='qr_reader_node',
            output='screen',
            parameters=[LaunchConfiguration('params_file')],
        ),
    ])
