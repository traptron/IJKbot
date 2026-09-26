#!/usr/bin/env python3

import os
import shutil
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_description = get_package_share_directory('description')
    xacro_file = os.path.join(pkg_description, 'urdf', 'ijkbot.urdf.xacro')
    urdf_fallback = os.path.join(pkg_description, 'urdf', 'ijkbot.urdf')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Использовать симуляционное время (/clock)'
    )

    use_sim_time = LaunchConfiguration('use_sim_time')

    # Определение команды xacro или fallback на статический URDF
    xacro_cmd = shutil.which('xacro') or (
        os.path.expanduser('~/.local/bin/xacro')
        if os.path.exists(os.path.expanduser('~/.local/bin/xacro'))
        else None
    )

    if xacro_cmd and os.path.exists(xacro_file):
        robot_description = ParameterValue(
            Command([xacro_cmd, ' ', xacro_file]),
            value_type=str
        )
    elif os.path.exists(urdf_fallback):
        with open(urdf_fallback, 'r', encoding='utf-8') as f:
            robot_description = f.read()
    else:
        robot_description = ParameterValue(
            Command(['xacro ', xacro_file]),
            value_type=str
        )

    # Нода публикации состояния робота (публикует дерево TF статических и подвижных звеньев)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'use_sim_time': use_sim_time
        }]
    )

    return LaunchDescription([
        declare_use_sim_time,
        robot_state_publisher_node
    ])

