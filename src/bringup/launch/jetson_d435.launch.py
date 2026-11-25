"""Run the Jetson D435 and optional QR reader on a local ROS graph."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    SetEnvironmentVariable,
    UnsetEnvironmentVariable,
)
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


BENCH_DOMAIN = '88'
LOOPBACK_DDS = (
    '<CycloneDDS><Domain><General><Interfaces>'
    '<NetworkInterface name="lo"/></Interfaces>'
    '<AllowMulticast>false</AllowMulticast></General>'
    '<Discovery><ParticipantIndex>auto</ParticipantIndex>'
    '<Peers><Peer address="127.0.0.1"/></Peers></Discovery>'
    '</Domain></CycloneDDS>'
)


def generate_launch_description() -> LaunchDescription:
    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            str(Path(__file__).with_name('realsense_laserscan.launch.py'))
        ),
        launch_arguments={
            'color_profile': LaunchConfiguration('color_profile'),
            'depth_profile': LaunchConfiguration('depth_profile'),
            'enable_depth_scan': 'false',
        }.items(),
    )
    qr = Node(
        package='vision_cpp',
        executable='qr_reader_node',
        name='jetson_bench_qr',
        condition=LaunchConfigurationEquals('qr_backend', 'opencv'),
        parameters=[{
            'image_topic': '/camera/color/image_raw/compressed',
            'trigger_topic': '~/take_photo',
            'state_filter_enabled': False,
            'snapshot_mode': False,
            'confirm_frames': 3,
            'save_snapshot': False,
        }],
        output='screen',
    )
    zxing_qr = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare('vision'), 'launch', 'zxing_qr.launch.py',
        ])),
        condition=LaunchConfigurationEquals('qr_backend', 'zxing'),
        launch_arguments={'require_trigger': LaunchConfiguration('require_trigger')}.items(),
    )
    return LaunchDescription([
        DeclareLaunchArgument('enable_qr', default_value='false',
                              description='Decode QR locally from D435'),
        DeclareLaunchArgument('qr_backend', default_value='opencv', choices=['opencv', 'zxing']),
        DeclareLaunchArgument('require_trigger', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('color_profile', default_value='640x480x15'),
        DeclareLaunchArgument('depth_profile', default_value='640x480x15'),
        GroupAction([
            # Replace CLI peer settings and bind DDS traffic to loopback.
            SetEnvironmentVariable('RMW_IMPLEMENTATION', 'rmw_cyclonedds_cpp'),
            SetEnvironmentVariable('ROS_DOMAIN_ID', BENCH_DOMAIN),
            SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'SYSTEM_DEFAULT'),
            SetEnvironmentVariable('CYCLONEDDS_URI', LOOPBACK_DDS),
            UnsetEnvironmentVariable('ROS_STATIC_PEERS'),
            UnsetEnvironmentVariable('ROS_LOCALHOST_ONLY'),
            LogInfo(msg=f'D435 bench: CycloneDDS loopback, domain {BENCH_DOMAIN}'),
            camera,
            GroupAction([qr, zxing_qr], condition=IfCondition(LaunchConfiguration('enable_qr'))),
        ]),
    ])
