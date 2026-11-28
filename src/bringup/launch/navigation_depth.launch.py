"""Navigate a saved RGB-D map projection with live small-obstacle voxel layers."""

from pathlib import Path
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
import yaml


def navigation_params(params):
    """Use live 3D observations in both costmaps while retaining lidar and inflation."""
    for name in ('local_costmap', 'global_costmap'):
        costmap = params[name][name]['ros__parameters']
        # Keep the footprint clearance and inflation radius. A steeper gradient
        # makes the surrounding traversable cells less expensive in narrow lanes.
        costmap['inflation_layer']['cost_scaling_factor'] = 10.0
        costmap['plugins'].insert(-1, 'depth_voxels')
        costmap['depth_voxels'] = {
            'plugin': 'terrain::FloorVoxelLayer',
            'enabled': True,
            'origin_z': 0.0, 'z_resolution': 0.025, 'z_voxels': 16,
            'max_obstacle_height': 0.4,
            'mark_threshold': 0, 'unknown_threshold': 15,
            'observation_sources': 'depth depth_clear',
            'depth': {
                'topic': '/navigation/depth_points', 'data_type': 'PointCloud2',
                'min_obstacle_height': 0.025, 'max_obstacle_height': 0.4,
                'marking': True, 'clearing': False,
                'observation_persistence': 0.0, 'expected_update_rate': 0.5,
                'obstacle_min_range': 0.15, 'obstacle_max_range': 2.5,
                'raytrace_min_range': 0.0, 'raytrace_max_range': 2.5,
            },
        }
        # Clearing uses floor returns too. The marking source's height filter
        # would otherwise discard those rays and leave removed objects occupied.
        costmap['depth_voxels']['depth_clear'] = {
            **costmap['depth_voxels']['depth'],
            'min_obstacle_height': -0.035, 'marking': False, 'clearing': True,
        }
    local = params['local_costmap']['local_costmap']['ros__parameters']
    local.update(resolution=0.02, width=3, height=3)
    controller = params['controller_server']['ros__parameters']['FollowPath']
    controller.update(desired_linear_vel=0.10, cost_scaling_dist=0.16,
                      inflation_cost_scaling_factor=10.0)
    params['planner_server']['ros__parameters']['GridBased']['allow_unknown'] = False
    return params


def setup(context, temporary):
    def arg(name):
        return LaunchConfiguration(name).perform(context)

    bringup = Path(get_package_share_directory('bringup'))
    nav2 = Path(get_package_share_directory('nav2'))
    map_path = Path(arg('map')).expanduser().resolve(strict=True)
    params = navigation_params(yaml.safe_load((nav2 / 'config/nav2_params.yaml').read_text()))
    params_path = Path(temporary.name) / 'nav2.yaml'
    params_path.write_text(yaml.safe_dump(params))

    def include(path, **arguments):
        return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(path)),
                                        launch_arguments=arguments.items())
    return [
        include(bringup / 'launch/robot.launch.py',
                enable_camera='false', enable_lidar=arg('enable_lidar'),
                mock_hardware=arg('mock_hardware'), max_linear_velocity='0.10',
                lidar_serial_port=arg('lidar_serial_port'), lidar_serial_baudrate=arg('lidar_serial_baudrate'),
                motors_serial_port=arg('motors_serial_port'),
                wheel_diameter=arg('wheel_diameter'), wheel_separation=arg('wheel_separation'),
                robot_model='locking_deck', sensor_mounts_file=arg('sensor_mounts_file'),
                motor_cmd_vel_topic='/cmd_vel_depth_safe', monitor_cmd_vel_topic='/cmd_vel_depth_input',
                use_sim_time=arg('use_sim_time')),
        include(bringup / 'launch/rgbd.launch.py',
                depth_navigation='true', replay=arg('replay'),
                color_profile=arg('color_profile'), use_sim_time=arg('use_sim_time')),
        include(nav2 / 'launch/navigation.launch.py',
                map=str(map_path), use_amcl=arg('use_amcl'), use_twist_mux='false',
                params_file=str(params_path), use_sim_time=arg('use_sim_time')),
    ]


def generate_launch_description():
    temporary = tempfile.TemporaryDirectory(prefix='ijk-depth-nav-')
    defaults = {
        'map': '', 'use_amcl': 'true', 'mock_hardware': 'false',
        'enable_lidar': 'true', 'replay': 'false', 'use_sim_time': 'false',
        'sensor_mounts_file': '', 'color_profile': '1920x1080x15',
        'lidar_serial_port': '/dev/ttyUSB0', 'lidar_serial_baudrate': '115200',
        'motors_serial_port': '/dev/ttySTS', 'wheel_diameter': '0.075', 'wheel_separation': '0.225',
    }
    return LaunchDescription([
        *(DeclareLaunchArgument(name, default_value=value) for name, value in defaults.items()),
        OpaqueFunction(function=setup, args=[temporary]),
    ])
