#!/usr/bin/env python3

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.conditions import IfCondition, UnlessCondition
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    pkg_bringup = get_package_share_directory('bringup')
    pkg_slam = get_package_share_directory('slam_toolbox')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Использовать симуляционное время (/clock)'
    )
    declare_lidar_serial_port = DeclareLaunchArgument(
        'lidar_serial_port', default_value='/dev/ttyUSB0',
        description='Последовательный порт RPLIDAR A2M8; приводы используют /dev/ttySTS'
    )
    declare_lidar_serial_baudrate = DeclareLaunchArgument(
        'lidar_serial_baudrate', default_value='115200',
        description='Скорость последовательного порта RPLIDAR A2M8'
    )
    declare_mock_hardware = DeclareLaunchArgument(
        'mock_hardware', default_value='false',
        description='Режим имитации моторов без реального UART'
    )
    declare_scan_topic = DeclareLaunchArgument(
        'scan_topic', default_value='/scan',
        description='Топик сканов лидара (/scan или /scan_raw)'
    )
    declare_slam_params_file = DeclareLaunchArgument(
        'slam_params_file',
        default_value=os.path.join(pkg_slam, 'config', 'mapper_params_online_async.yaml'),
        description='Профиль параметров slam_toolbox'
    )
    declare_max_linear_velocity = DeclareLaunchArgument(
        'max_linear_velocity', default_value='0.20',
        description='Аппаратный потолок линейной скорости при картографировании (м/с)'
    )

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'robot.launch.py')
        ),
        launch_arguments={
            'enable_camera': LaunchConfiguration('mapping_camera'),
            'color_profile': LaunchConfiguration('color_profile'),
            'enable_motors': LaunchConfiguration('enable_motors'),
            'enable_lidar': LaunchConfiguration('enable_lidar'),
            'robot_model': LaunchConfiguration('robot_model'),
            'lidar_serial_port': LaunchConfiguration('lidar_serial_port'),
            'lidar_serial_baudrate': LaunchConfiguration('lidar_serial_baudrate'),
            'mock_hardware': LaunchConfiguration('mock_hardware'),
            'motors_serial_port': LaunchConfiguration('motors_serial_port'),
            'max_linear_velocity': LaunchConfiguration('max_linear_velocity'),
            'wheel_diameter': LaunchConfiguration('wheel_diameter'),
            'wheel_separation': LaunchConfiguration('wheel_separation'),
            'sensor_mounts_file': LaunchConfiguration('sensor_mounts_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items()
    )

    def start_rgbd(context):
        directory = LaunchConfiguration('terrain_session').perform(context)
        if not directory:
            raise ValueError('Set terrain_session to a new session directory')
        session = Path(directory).expanduser().resolve()
        session.mkdir(parents=True, exist_ok=False)
        fused = IfCondition(LaunchConfiguration('fused_mapping')).evaluate(context)
        actions = [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(os.path.join(pkg_bringup, 'launch', 'rgbd.launch.py')),
                launch_arguments={
                    'mapping_3d': 'true', 'database_path': str(session / 'rtabmap.db'),
                    'fused_mapping': LaunchConfiguration('fused_mapping'),
                    'max_scan_height': LaunchConfiguration('max_scan_height'),
                    'scan_topic': LaunchConfiguration('scan_topic'),
                    'color_profile': LaunchConfiguration('color_profile'),
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'replay': LaunchConfiguration('replay'),
                }.items(),
            ),
        ]
        if fused:
            return actions + [Node(
                package='terrain', executable='cloud_preview.py', output='screen',
                parameters=[{'max_height': ParameterValue(
                    LaunchConfiguration('max_scan_height'), value_type=float)}],
            )]
        return actions + [
            Node(package='terrain', executable='bridge_snapshot.py', output='screen',
                 arguments=['capture', str(session / 'cloud.npz')]),
            Node(package='tf2_ros', executable='static_transform_publisher',
                 arguments=['--x', '.4', '--y', '.4', '--frame-id', 'map',
                            '--child-frame-id', 'slam_map']),
        ]

    slam_node = LifecycleNode(
        package='slam_toolbox',
        condition=UnlessCondition(LaunchConfiguration('fused_mapping')),
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        namespace='',
        parameters=[
            LaunchConfiguration('slam_params_file'),
            {
                'use_sim_time': LaunchConfiguration('use_sim_time'),
                'scan_topic': LaunchConfiguration('scan_topic'),
                'base_frame': 'base_footprint',
                'odom_frame': 'odom',
                'map_frame': LaunchConfiguration('mapping_frame'),
                'min_laser_range': 0.18,
                'max_laser_range': 12.0,
            },
        ],
        remappings=[('map', LaunchConfiguration('mapping_topic'))],
    )

    configure_event = EmitEvent(
        condition=UnlessCondition(LaunchConfiguration('fused_mapping')),
        event=ChangeState(
            lifecycle_node_matcher=matches_action(slam_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_event = RegisterEventHandler(
        condition=UnlessCondition(LaunchConfiguration('fused_mapping')),
        event_handler=OnStateTransition(
            target_lifecycle_node=slam_node,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(slam_node),
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        )
    )

    return LaunchDescription([
        DeclareLaunchArgument('color_profile', default_value='640x480x15'),
        DeclareLaunchArgument('mapping_camera', default_value='false'),
        DeclareLaunchArgument('robot_model', default_value='locking_deck'),
        DeclareLaunchArgument('enable_3d', default_value='false'),
        DeclareLaunchArgument('fused_mapping', default_value='false'),
        DeclareLaunchArgument('max_scan_height', default_value='0.40',
                              description='Максимальная высота точек 3D-карты над полом, в метрах'),
        DeclareLaunchArgument('enable_motors', default_value='true'),
        DeclareLaunchArgument('enable_lidar', default_value='true'),
        DeclareLaunchArgument('wheel_diameter', default_value='0.075'),
        DeclareLaunchArgument('wheel_separation', default_value='0.225'),
        DeclareLaunchArgument('motors_serial_port', default_value='/dev/ttySTS'),
        DeclareLaunchArgument('replay', default_value='false'),
        DeclareLaunchArgument('terrain_session', default_value=''),
        DeclareLaunchArgument('sensor_mounts_file', default_value=''),
        DeclareLaunchArgument('mapping_frame', default_value='map'),
        DeclareLaunchArgument('mapping_topic', default_value='/map'),
        declare_use_sim_time,
        declare_lidar_serial_port,
        declare_lidar_serial_baudrate,
        declare_mock_hardware,
        declare_scan_topic,
        declare_slam_params_file,
        declare_max_linear_velocity,
        robot_launch,
        slam_node,
        configure_event,
        activate_event,
        OpaqueFunction(function=start_rgbd, condition=IfCondition(LaunchConfiguration('enable_3d'))),
    ])
