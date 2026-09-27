"""CSI capture and standalone QR reading; does not start robot motors."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('camera_name', default_value=''),
        DeclareLaunchArgument('mock_hardware', default_value='false'),
        DeclareLaunchArgument('enable_reader', default_value='true'),
        DeclareLaunchArgument('confirm_frames', default_value='3'),
        Node(
            package='vision', executable='rpi_camera_node', output='screen',
            parameters=[{
                'camera_name': ParameterValue(LaunchConfiguration('camera_name'), value_type=str),
                'mock_hardware': ParameterValue(
                    LaunchConfiguration('mock_hardware'), value_type=bool),
            }],
        ),
        Node(
            package='vision', executable='qr_reader_node', output='screen',
            condition=IfCondition(LaunchConfiguration('enable_reader')),
            parameters=[{
                'image_topic': '/camera/color/image_raw/compressed',
                'state_filter_enabled': False,
                'snapshot_mode': False,
                'save_snapshot': False,
                'confirm_frames': ParameterValue(
                    LaunchConfiguration('confirm_frames'), value_type=int),
            }],
        ),
    ])
