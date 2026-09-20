"""Existing LLM dashboard and QR reader; camera runs on the robot separately."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('image_topic', default_value='/camera/color/image_raw/compressed'),
        DeclareLaunchArgument('port', default_value='8080'),
        Node(package='ijkbot_vision', executable='qr_reader_node', output='screen',
             parameters=[{'image_topic': LaunchConfiguration('image_topic')}]),
        Node(package='ijkbot_brain', executable='dashboard_app', output='screen',
             arguments=['--no-mock', '--port', LaunchConfiguration('port')]),
    ])
