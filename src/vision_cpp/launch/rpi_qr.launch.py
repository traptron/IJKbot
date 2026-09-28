"""Native standalone CSI and QR pipeline; no motor nodes."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    arguments = [DeclareLaunchArgument(name, default_value=value) for name, value in (
        ('fps', '10'), ('jpeg_quality', '85'), ('mock_hardware', 'false'),
        ('backend', 'v4l2_raw'), ('camera_name', ''), ('enable_reader', 'true'),
        ('confirm_frames', '3'))]
    return LaunchDescription(arguments + [
        Node(package='vision_cpp', executable='rpi_camera_node', output='screen',
             parameters=[{name: ParameterValue(LaunchConfiguration(name), value_type=kind)
                          for name, kind in (('fps', int), ('jpeg_quality', int),
                                             ('mock_hardware', bool), ('backend', str),
                                             ('camera_name', str))}]),
        Node(package='vision_cpp', executable='qr_reader_node', output='screen',
             condition=IfCondition(LaunchConfiguration('enable_reader')),
             parameters=[{'state_filter_enabled': False, 'snapshot_mode': False,
                          'save_snapshot': False, 'confirm_frames': ParameterValue(
                              LaunchConfiguration('confirm_frames'), value_type=int)}]),
    ])
