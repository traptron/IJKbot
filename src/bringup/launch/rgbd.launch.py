"""RealSense streams for fused mapping and independent spatial RGB-D odometry."""

import math
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue

RGBD_INPUTS = [
    ('rgb/image', '/camera/color/image_raw'),
    ('depth/image', '/camera/aligned_depth_to_color/image_raw'),
    ('rgb/camera_info', '/camera/color/camera_info'),
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
    visual_inputs = RGBD_INPUTS + [('odom', '/terrain/visual_odom'), ('/tf', '/terrain/tf')]

    def processing_nodes(max_height):
        return [
            Node(
                package='rtabmap_sync', executable='rgbd_sync', namespace='terrain/slam',
                output='screen', remappings=RGBD_INPUTS + [('rgbd_image', 'rgbd_unfiltered')],
                parameters=[{'use_sim_time': use_sim_time, 'qos': 1,
                             'approx_sync': False, 'decimation': 2}],
            ),
            Node(
                package='terrain', executable='mapping_depth_filter.py', namespace='terrain/slam',
                output='screen', parameters=[{'use_sim_time': use_sim_time, 'max_height': max_height,
                             'preserve_foreground': ParameterValue(
                                 LaunchConfiguration('depth_navigation'), value_type=bool)}],
            ),
        ]

    def launch_navigation_depth(context):
        height = float(LaunchConfiguration('max_scan_height').perform(context))
        if not math.isfinite(height) or height <= 0.025:
            raise ValueError('max_scan_height must exceed 0.025 m')
        return [Node(
            package='terrain', executable='navigation_depth.py', output='screen',
            parameters=[{'use_sim_time': use_sim_time, 'max_height': height}],
        )]

    def launch_mapper(context):
        fused = IfCondition(LaunchConfiguration('fused_mapping')).evaluate(context)
        parameters = {
            'subscribe_depth': True,
            'database_path': LaunchConfiguration('database_path'),
            'Grid/3D': 'true',
            'Grid/DepthDecimation': '2',
            'Grid/NormalsSegmentation': 'false',
            'Grid/MaxGroundHeight': '0.02',
            'Grid/RangeMax': '2.5',
            'Rtabmap/DetectionRate': '2',
        }
        nodes = []
        if fused:
            max_height = float(LaunchConfiguration('max_scan_height').perform(context))
            if not math.isfinite(max_height) or max_height <= 0.02:
                raise ValueError('max_scan_height must be finite and greater than 0.02 m')
            # The wheel TF supplies the initial planar pose. RTAB-Map uses camera
            # features and lidar ICP to constrain the same pose graph.
            parameters.update({
                'odom_frame_id': 'odom',
                'map_frame_id': 'map',
                'publish_tf': True,
                'subscribe_scan': True,
                'subscribe_depth': False,
                'subscribe_rgb': False,
                'subscribe_rgbd': True,
                'qos_image': 1,
                'approx_sync_max_interval': 0.15,
                'wait_for_transform': 0.3,
                'Reg/Strategy': '2',
                'Reg/Force3DoF': 'true',
                'RGBD/NeighborLinkRefining': 'true',
                'Grid/Sensor': '2',
                'Grid/CellSize': '0.05',
                'Grid/MaxObstacleHeight': str(max_height),
                'Grid/RangeMax': '8.0',
                'Grid/RayTracing': 'true',
            })
            remappings = [('scan', LaunchConfiguration('scan_topic')), ('map', '/map')]
            nodes += processing_nodes(max_height)
        else:
            parameters.update({
                'subscribe_odom': True,
                'map_frame_id': 'rgbd_map',
                'publish_tf': True,
                'Grid/CellSize': '0.005',
            })
            remappings = visual_inputs
        return nodes + [Node(
            package='rtabmap_slam', executable='rtabmap', namespace='terrain/slam',
            output='screen', remappings=remappings, parameters=[rgbd, parameters],
        )]

    align_color_depth = PythonExpression([
        "'false' if '", LaunchConfiguration('depth_navigation'), "' == 'true' else 'true'",
    ])
    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            FindPackageShare('realsense2_camera'), '/launch/rs_launch.py',
        ]),
        launch_arguments={
            'camera_name': 'camera',
            'camera_namespace': '',
            'rgb_camera.color_profile': LaunchConfiguration('color_profile'),
            'depth_module.depth_profile': LaunchConfiguration('depth_profile'),
            'enable_color': 'true',
            'enable_depth': 'true',
            'align_depth.enable': align_color_depth,
            'enable_sync': align_color_depth,
            'pointcloud.enable': 'false',
        }.items(),
        condition=UnlessCondition(LaunchConfiguration('replay')),
    )

    return LaunchDescription([
        DeclareLaunchArgument('replay', default_value='false'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('color_profile', default_value='1920x1080x15'),
        DeclareLaunchArgument('depth_profile', default_value='848x480x15'),
        DeclareLaunchArgument('mapping_3d', default_value='false'),
        DeclareLaunchArgument('depth_navigation', default_value='false'),
        DeclareLaunchArgument('fused_mapping', default_value='false'),
        DeclareLaunchArgument('max_scan_height', default_value='0.40'),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        DeclareLaunchArgument('database_path', default_value=os.path.expanduser('~/.ros/ijk-rgbd.db')),
        camera,
        Node(
            package='bringup', executable='mapping_camera_preview.py',
            condition=IfCondition(PythonExpression([
                "'", LaunchConfiguration('mapping_3d'), "' == 'true' or '",
                LaunchConfiguration('depth_navigation'), "' == 'true'"])),
            parameters=[
                [FindPackageShare('bringup'), '/config/mapping_camera.yaml'],
                {'max_fps': ParameterValue(PythonExpression([
                    '5.0 if "', LaunchConfiguration('depth_navigation'), '" == "true" else 0.0',
                ]), value_type=float)},
            ],
        ),
        Node(
            package='rtabmap_odom', executable='rgbd_odometry', namespace='terrain',
            output='screen', remappings=visual_inputs,
            condition=UnlessCondition(PythonExpression([
                "'", LaunchConfiguration('fused_mapping'), "' == 'true' or '",
                LaunchConfiguration('depth_navigation'), "' == 'true'"])),
            parameters=[rgbd, {
                'odom_frame_id': 'rgbd_odom',
                'publish_tf': ParameterValue(LaunchConfiguration('mapping_3d'), value_type=bool),
            }],
        ),
        OpaqueFunction(function=launch_navigation_depth, condition=IfCondition(LaunchConfiguration('depth_navigation'))),
        OpaqueFunction(function=launch_mapper, condition=IfCondition(LaunchConfiguration('mapping_3d'))),
    ])
