#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_bringup = get_package_share_directory('ijkbot_bringup')
    pkg_realsense = get_package_share_directory('realsense2_camera')

    # Аргументы запуска
    declare_color_profile = DeclareLaunchArgument(
        'color_profile',
        default_value='640x480x15',
        description='Профиль цветной камеры: разрешение и FPS (640x480x15)'
    )

    declare_depth_profile = DeclareLaunchArgument(
        'depth_profile',
        default_value='640x480x15',
        description='Профиль модуля глубины: разрешение и FPS (напр. 640x480x15)'
    )

    declare_scan_config = DeclareLaunchArgument(
        'scan_config_file',
        default_value=os.path.join(pkg_bringup, 'config', 'realsense_laserscan.yaml'),
        description='Путь к конфигурационному файлу для depthimage_to_laserscan'
    )

    color_profile = LaunchConfiguration('color_profile')
    depth_profile = LaunchConfiguration('depth_profile')
    scan_config_file = LaunchConfiguration('scan_config_file')

    # 1. Запуск драйвера Intel RealSense D435 через официальный rs_launch.py
    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_realsense, 'launch', 'rs_launch.py')
        ),
        launch_arguments={
            'camera_name': 'camera',
            'camera_namespace': '',
            'rgb_camera.color_profile': color_profile,
            'depth_module.depth_profile': depth_profile,
            'enable_color': 'true',
            'enable_depth': 'true',
            'align_depth.enable': 'false',   # Отключено: экономия CPU Pi 4B
            'pointcloud.enable': 'false',    # Отключено для экономии ресурсов
            'enable_sync': 'false',          # Отключено: без align_depth
        }.items()
    )

    # 2. Нода преобразования среза карты глубины в 2D LaserScan (/scan)
    depthimage_to_laserscan_node = Node(
        package='depthimage_to_laserscan',
        executable='depthimage_to_laserscan_node',
        name='depthimage_to_laserscan',
        parameters=[scan_config_file],
        remappings=[
            ('depth', '/camera/depth/image_rect_raw'),
            ('depth_camera_info', '/camera/depth/camera_info'),
            ('scan', '/scan'),
        ],
        output='screen'
    )

    return LaunchDescription([
        declare_color_profile,
        declare_depth_profile,
        declare_scan_config,
        realsense_launch,
        depthimage_to_laserscan_node,
    ])
