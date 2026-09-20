"""Start Nav2 and the coordinate trial without duplicate goal subscribers."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    navigation = os.path.join(
        get_package_share_directory('ijkbot_nav2'), 'launch', 'navigation.launch.py')
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(navigation),
            launch_arguments={'goal_pose_topic': '/nav2/manual_goal_pose'}.items()),
        Node(package='ijkbot_brain', executable='trial_planner', output='screen'),
    ])
