"""Start the differential drive; hardware access must be selected explicitly."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    package = get_package_share_directory("driver")
    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=f"{package}/config/params.yaml"),
        DeclareLaunchArgument("mock_hardware", default_value="true"),
        DeclareLaunchArgument("serial_port", default_value="/dev/ttySTS"),
        Node(
            package="driver",
            executable="diff_drive_node",
            name="diff_drive_node",
            output="screen",
            parameters=[
                LaunchConfiguration("params_file"),
                {
                    "mock_hardware": ParameterValue(
                        LaunchConfiguration("mock_hardware"), value_type=bool),
                    "serial_port": LaunchConfiguration("serial_port"),
                },
            ],
        ),
    ])
