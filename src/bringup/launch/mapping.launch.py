#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    RegisterEventHandler,
)
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
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

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, 'launch', 'robot.launch.py')
        ),
        launch_arguments={
            'enable_camera': 'false',
            'enable_motors': 'true',
            'enable_lidar': 'true',
            'lidar_serial_port': LaunchConfiguration('lidar_serial_port'),
            'lidar_serial_baudrate': LaunchConfiguration('lidar_serial_baudrate'),
            'mock_hardware': LaunchConfiguration('mock_hardware'),
        }.items()
    )

    slam_node = LifecycleNode(
        package='slam_toolbox',
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
                'map_frame': 'map',
                'min_laser_range': 0.18,
            },
        ],
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(slam_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_event = RegisterEventHandler(
        OnStateTransition(
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
        declare_use_sim_time,
        declare_lidar_serial_port,
        declare_lidar_serial_baudrate,
        declare_mock_hardware,
        declare_scan_topic,
        declare_slam_params_file,
        robot_launch,
        slam_node,
        configure_event,
        activate_event,
    ])
