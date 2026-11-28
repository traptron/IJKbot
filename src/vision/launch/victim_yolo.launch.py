"""Launch the YOLO RGB-D victim detector node."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    params_file = Path(get_package_share_directory('vision')) / 'config' / 'victim_yolo.yaml'
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=str(params_file)),
        DeclareLaunchArgument('model_path', default_value='', description='Path to a single-class victim model'),
        DeclareLaunchArgument('use_sim_time', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('backend', default_value='auto', choices=['auto', 'tensorrt', 'onnx', 'ultralytics', 'mock']),
        DeclareLaunchArgument('image_reliability', default_value='best_effort', choices=['best_effort', 'reliable']),
        Node(
            package='vision',
            executable='victim_yolo_node',
            name='victim_yolo_node',
            output='screen',
            parameters=[
                LaunchConfiguration('params_file'),
                {
                    'model_path': ParameterValue(LaunchConfiguration('model_path'), value_type=str),
                    'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                    'backend': LaunchConfiguration('backend'),
                    'image_reliability': LaunchConfiguration('image_reliability'),
                },
            ],
        ),
    ])
