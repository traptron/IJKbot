"""Start the local ZXing reader, either triggered by the mission or free running."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import AndSubstitution, EqualsSubstitution, IfElseSubstitution, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    params_file = Path(get_package_share_directory('vision')) / 'config' / 'zxing_qr.yaml'
    require_trigger = LaunchConfiguration('require_trigger')
    requested_reset_topic = LaunchConfiguration('reset_topic')
    # In triggered mode the photo topic already resets confirmation through the trigger callback.
    reset_topic = IfElseSubstitution(
        AndSubstitution(require_trigger, EqualsSubstitution(requested_reset_topic, '/vision/take_photo')),
        if_value='',
        else_value=requested_reset_topic,
    )
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=str(params_file)),
        DeclareLaunchArgument('require_trigger', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('reset_topic', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('image_reliability', default_value='best_effort',
                              choices=['best_effort', 'reliable']),
        Node(
            package='vision', executable='zxing_qr_reader_node', name='zxing_qr_reader', output='screen',
            parameters=[LaunchConfiguration('params_file'), {
                'require_trigger': ParameterValue(require_trigger, value_type=bool),
                'reset_topic': ParameterValue(reset_topic, value_type=str),
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                'image_reliability': LaunchConfiguration('image_reliability'),
            }],
        ),
    ])
