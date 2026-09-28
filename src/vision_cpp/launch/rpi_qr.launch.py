"""Native standalone CSI and QR pipeline; no motor nodes."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    arguments = [DeclareLaunchArgument(name, default_value=value) for name, value in (
        ('fps', '6'), ('jpeg_quality', '95'), ('mock_hardware', 'false'),
        ('monochrome', 'true'),
        ('width', '1296'), ('height', '972'), ('preview_fps', '4'), ('preview_quality', '85'),
        ('qr_image_topic', '/camera/qr/image/compressed'), ('max_decode_fps', '3.0'),
        ('decode_duty_cycle', '0.7'),
        ('confirmation_timeout_sec', '15.0'),
        ('backend', 'v4l2_raw'), ('camera_name', ''), ('enable_reader', 'true'),
        ('confirm_frames', '3'), ('one_shot', 'true'))]
    return LaunchDescription(arguments + [
        Node(package='vision_cpp', executable='rpi_camera_node', output='screen',
             parameters=[{name: ParameterValue(LaunchConfiguration(name), value_type=kind)
                          for name, kind in (('fps', int), ('jpeg_quality', int),
                                             ('width', int), ('height', int),
                                             ('preview_fps', int), ('preview_quality', int),
                                             ('qr_image_topic', str),
                                             ('mock_hardware', bool), ('monochrome', bool),
                                             ('backend', str),
                                             ('camera_name', str))},
                         {'stop_on_qr': ParameterValue(LaunchConfiguration('one_shot'), value_type=bool)}]),
        Node(package='vision_cpp', executable='qr_reader_node', output='screen',
             condition=IfCondition(LaunchConfiguration('enable_reader')),
             parameters=[{'state_filter_enabled': False, 'snapshot_mode': False,
                          'save_snapshot': False,
                          'image_topic': ParameterValue(LaunchConfiguration('qr_image_topic'), value_type=str),
                          'max_decode_fps': ParameterValue(LaunchConfiguration('max_decode_fps'), value_type=float),
                          'decode_duty_cycle': ParameterValue(LaunchConfiguration('decode_duty_cycle'), value_type=float),
                          'confirmation_timeout_sec': ParameterValue(
                              LaunchConfiguration('confirmation_timeout_sec'), value_type=float),
                          'one_shot': ParameterValue(LaunchConfiguration('one_shot'), value_type=bool),
                          'confirm_frames': ParameterValue(
                              LaunchConfiguration('confirm_frames'), value_type=int)}]),
    ])
