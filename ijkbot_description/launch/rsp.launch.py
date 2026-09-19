#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_description = get_package_share_directory('ijkbot_description')
    xacro_file = os.path.join(pkg_description, 'urdf', 'ijkbot.urdf.xacro')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Использовать симуляционное время (/clock)'
    )

    use_sim_time = LaunchConfiguration('use_sim_time')

    # Преобразование Xacro в URDF XML через команду xacro
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

