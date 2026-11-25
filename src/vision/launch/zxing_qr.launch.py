"""Start the local ZXing reader, either triggered by the mission or free running."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    params_file = Path(get_package_share_directory('vision')) / 'config' / 'zxing_qr.yaml'
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=str(params_file)),
        DeclareLaunchArgument('require_trigger', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('image_reliability', default_value='best_effort',
                              choices=['best_effort', 'reliable']),
        Node(
            package='vision', executable='zxing_qr_reader_node', name='zxing_qr_reader', output='screen',
            parameters=[LaunchConfiguration('params_file'), {
                'require_trigger': ParameterValue(LaunchConfiguration('require_trigger'), value_type=bool),
                'image_reliability': LaunchConfiguration('image_reliability'),
            }],
        ),
    ])
