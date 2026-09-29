"""CSI capture and standalone QR reading; does not start robot motors."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    native = PythonExpression(["'", LaunchConfiguration('implementation'), "' == 'vision_cpp'"])
    return LaunchDescription([
        DeclareLaunchArgument('camera_name', default_value=''),
        DeclareLaunchArgument('mock_hardware', default_value='false'),
        DeclareLaunchArgument('backend', default_value='v4l2_raw'),
        DeclareLaunchArgument('enable_reader', default_value='true'),
        DeclareLaunchArgument('confirm_frames', default_value='3'),
        DeclareLaunchArgument('one_shot', default_value='true'),
        DeclareLaunchArgument('implementation', default_value='vision_cpp'),
        DeclareLaunchArgument('fps', default_value='6'),
        DeclareLaunchArgument('jpeg_quality', default_value='95'),
        DeclareLaunchArgument('width', default_value='1920'),
        DeclareLaunchArgument('height', default_value='1080'),
        # Route the native implementation through its split full-resolution/preview pipeline.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('vision_cpp'), 'launch', 'rpi_qr.launch.py')),
            condition=IfCondition(native),
            launch_arguments={name: LaunchConfiguration(name) for name in (
                'camera_name', 'mock_hardware', 'backend', 'enable_reader',
                'confirm_frames', 'one_shot', 'fps', 'jpeg_quality', 'width', 'height')}.items(),
        ),
        Node(
            package=LaunchConfiguration('implementation'), executable='rpi_camera_node', output='screen',
            condition=UnlessCondition(native),
            parameters=[{
                'fps': ParameterValue(LaunchConfiguration('fps'), value_type=int),
                'jpeg_quality': ParameterValue(LaunchConfiguration('jpeg_quality'), value_type=int),
                'camera_name': ParameterValue(LaunchConfiguration('camera_name'), value_type=str),
                'backend': ParameterValue(LaunchConfiguration('backend'), value_type=str),
                'mock_hardware': ParameterValue(
                    LaunchConfiguration('mock_hardware'), value_type=bool),
                'stop_on_qr': ParameterValue(LaunchConfiguration('one_shot'), value_type=bool),
            }],
        ),
        Node(
            package=LaunchConfiguration('implementation'), executable='qr_reader_node', output='screen',
            condition=IfCondition(PythonExpression([
                "'", LaunchConfiguration('implementation'), "' != 'vision_cpp' and '",
                LaunchConfiguration('enable_reader'), "'.lower() == 'true'"])),
            parameters=[{
                'image_topic': '/camera/color/image_raw/compressed',
                'state_filter_enabled': False,
                'snapshot_mode': False,
                'save_snapshot': False,
                'one_shot': ParameterValue(LaunchConfiguration('one_shot'), value_type=bool),
                'confirm_frames': ParameterValue(
                    LaunchConfiguration('confirm_frames'), value_type=int),
            }],
        ),
    ])
