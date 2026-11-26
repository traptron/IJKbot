"""Onboard competition with a measured bridge reference and AMCL."""

import json
from pathlib import Path
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
import yaml


def setup(context, temporary):
    def arg(name):
        return LaunchConfiguration(name).perform(context)

    bringup = Path(get_package_share_directory('bringup'))
    nav2 = Path(get_package_share_directory('nav2'))
    reference = Path(arg('bridge_reference')).expanduser().resolve(strict=True)
    data = json.loads(reference.read_text())
    x, y, yaw = map(float, data['start_pose'])
    speed = float(data['calibration']['max_speed_m_s'])
    if not 0.03 <= speed <= .15:
        raise ValueError('Calibrate the bridge speed on the bench first')

    params = yaml.safe_load((nav2 / 'config/nav2_params.yaml').read_text())
    for name in ('local_costmap', 'global_costmap'):
        costmap = params[name][name]['ros__parameters']
        costmap['global_frame'] = 'map'
        costmap['update_frequency'] = 5.
        costmap['plugins'].insert(-1, 'bridge_layer')
        costmap['bridge_layer'] = {
            'plugin': 'terrain::BridgeLayer',
            'block_unobserved': name == 'local_costmap',
        }
    amcl = params['amcl']['ros__parameters']
    # Keep the estimate stamped on every scan, including while waiting at a ramp.
    amcl.update(update_min_a=-1., update_min_d=-1., transform_tolerance=.15)
    params['planner_server']['ros__parameters']['GridBased']['allow_unknown'] = False
    params['controller_server']['ros__parameters']['FollowPath']['desired_linear_vel'] = speed
    params_file = Path(temporary.name) / 'nav2.yaml'
    params_file.write_text(yaml.safe_dump(params))

    def include(path, **arguments):
        return IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(path)), launch_arguments=arguments.items())

    sim = arg('use_sim_time')
    use_sim_time = ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool)
    return [
        include(bringup / 'launch/robot.launch.py',
                enable_camera='false', enable_lidar=arg('enable_lidar'),
                enable_motors=arg('enable_motors'),
                mock_hardware=arg('mock_hardware'), max_linear_velocity=str(speed),
                wheel_diameter=arg('wheel_diameter'), wheel_separation=arg('wheel_separation'),
                lidar_serial_port=arg('lidar_serial_port'), lidar_serial_baudrate=arg('lidar_serial_baudrate'),
                motors_serial_port=arg('motors_serial_port'),
                motor_cmd_vel_topic='/cmd_vel_terrain_safe',
                monitor_cmd_vel_topic='/cmd_vel_terrain_input',
                sensor_mounts_file=arg('sensor_mounts_file'), use_sim_time=sim),
        include(bringup / 'launch/rgbd.launch.py', replay=arg('replay'), use_sim_time=sim),
        include(nav2 / 'launch/navigation.launch.py', use_amcl='true', use_twist_mux='false',
                params_file=str(params_file), map=arg('map'), use_sim_time=sim,
                initial_x=str(x), initial_y=str(y), initial_yaw=str(yaw)),
        Node(package='terrain', executable='bridge_guard.py', output='screen', parameters=[{
            'reference': str(reference), 'use_sim_time': use_sim_time,
        }]),
        Node(
            package='vision_cpp', executable='qr_reader_node', output='screen',
            condition=IfCondition(LaunchConfiguration('enable_qr')),
            parameters=[{'use_sim_time': use_sim_time}],
        ),
    ]


def generate_launch_description():
    temporary = tempfile.TemporaryDirectory(prefix='ijk-terrain-')
    defaults = {
        'map': '', 'bridge_reference': '', 'mock_hardware': 'true', 'enable_lidar': 'true', 'enable_motors': 'true',
        'replay': 'false', 'use_sim_time': 'false', 'sensor_mounts_file': '',
        'enable_qr': 'true', 'lidar_serial_port': '/dev/ttyUSB0',
        'lidar_serial_baudrate': '115200', 'motors_serial_port': '/dev/ttySTS',
        'wheel_diameter': '.075', 'wheel_separation': '.225',
    }
    return LaunchDescription([
        *(DeclareLaunchArgument(name, default_value=value) for name, value in defaults.items()),
        OpaqueFunction(function=setup, args=[temporary]),
    ])
