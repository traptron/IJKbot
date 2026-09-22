"""Launch only the trial planner alongside an existing robot/Nav2 system."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('home_x', default_value='0.4'),
        DeclareLaunchArgument('home_y', default_value='0.4'),
        DeclareLaunchArgument('home_yaw', default_value='0.0'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        Node(package='ijkbot_brain', executable='trial_planner', output='screen',
             parameters=[{
                 'home_x': ParameterValue(LaunchConfiguration('home_x'), value_type=float),
                 'home_y': ParameterValue(LaunchConfiguration('home_y'), value_type=float),
                 'home_yaw': ParameterValue(LaunchConfiguration('home_yaw'), value_type=float),
                 'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
             }]),
    ])
