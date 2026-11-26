"""Synchronized RealSense streams and independent spatial RGB-D odometry."""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue

RGBD_INPUTS = [
    ('rgb/image', '/camera/color/image_raw'),
    ('depth/image', '/camera/aligned_depth_to_color/image_raw'),
    ('rgb/camera_info', '/camera/color/camera_info'),
    ('odom', '/terrain/visual_odom'),
    ('/tf', '/terrain/tf'),
]


def generate_launch_description():
    use_sim_time = ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool)
    rgbd = {
        'use_sim_time': use_sim_time,
        'frame_id': 'base_footprint',
        'approx_sync': True,
        'approx_sync_max_interval': .04,
        'qos': 2,
        'Reg/Force3DoF': 'false',
    }
    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare('realsense2_camera'), '/launch/rs_launch.py',
        ]),
        launch_arguments={
            'camera_name': 'camera',
            'camera_namespace': '',
            'rgb_camera.color_profile': '640x480x15',
            'depth_module.depth_profile': '640x480x15',
            'enable_color': 'true',
            'enable_depth': 'true',
            'align_depth.enable': 'true',
            'enable_sync': 'true',
            'pointcloud.enable': 'false',
        }.items(),
        condition=UnlessCondition(LaunchConfiguration('replay')),
    )

    return LaunchDescription([
        DeclareLaunchArgument('replay', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('mapping_3d', default_value='false'),
        DeclareLaunchArgument('database_path', default_value=os.path.expanduser('~/.ros/ijk-rgbd.db')),
        camera,
        Node(
            package='rtabmap_odom', executable='rgbd_odometry', namespace='terrain',
            output='screen', remappings=RGBD_INPUTS,
            parameters=[rgbd, {
                'odom_frame_id': 'rgbd_odom',
                'publish_tf': ParameterValue(LaunchConfiguration('mapping_3d'), value_type=bool),
            }],
        ),
        Node(
            package='rtabmap_slam', executable='rtabmap', namespace='terrain/slam',
            output='screen', remappings=RGBD_INPUTS,
            condition=IfCondition(LaunchConfiguration('mapping_3d')),
            parameters=[rgbd, {
                'subscribe_depth': True,
                'subscribe_odom': True,
                'publish_tf': False,
                'map_frame_id': 'rgbd_map',
                'database_path': LaunchConfiguration('database_path'),
                'Grid/3D': 'true',
                'Grid/CellSize': '0.005',
                'Grid/DepthDecimation': '2',
                'Grid/NormalsSegmentation': 'false',
                'Grid/MaxGroundHeight': '0.02',
                'Grid/RangeMax': '2.5',
                'Rtabmap/DetectionRate': '2',
            }],
        ),
    ])
