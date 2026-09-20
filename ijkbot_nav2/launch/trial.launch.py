"""Start Nav2 and the coordinate trial without duplicate goal subscribers."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    navigation = os.path.join(
        get_package_share_directory('ijkbot_nav2'), 'launch', 'navigation.launch.py')
    return LaunchDescription([
        DeclareLaunchArgument('initial_x', default_value='0.4'),
        DeclareLaunchArgument('initial_y', default_value='0.4'),
        DeclareLaunchArgument('initial_yaw', default_value='0.0'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(navigation),
            launch_arguments={
                'goal_pose_topic': '/nav2/manual_goal_pose',
                'nav_cmd_vel_topic': '/trial/cmd_vel',
            }.items()),
        Node(package='ijkbot_brain', executable='trial_planner', output='screen',
             parameters=[{
                 'home_x': ParameterValue(LaunchConfiguration('initial_x'), value_type=float),
                 'home_y': ParameterValue(LaunchConfiguration('initial_y'), value_type=float),
                 'home_yaw': ParameterValue(LaunchConfiguration('initial_yaw'), value_type=float),
                 'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
             }]),
    ])
