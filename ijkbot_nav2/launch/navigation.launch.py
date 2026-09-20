#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, SetEnvironmentVariable
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace
from launch.substitution import Substitution
from launch_ros.descriptions import ParameterFile

try:
    from nav2_common.launch import RewrittenYaml
except ImportError:
    class RewrittenYaml(Substitution):
        def __init__(self, source_file, param_rewrites=None, value_rewrites=None, convert_types=True):
            super().__init__()
            self.source_file = source_file
        def perform(self, context):
            if hasattr(self.source_file, 'perform'):
                return self.source_file.perform(context)
            return str(self.source_file)


def generate_launch_description():
    pkg_nav2 = get_package_share_directory('ijkbot_nav2')

    # Аргументы запуска
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Использовать ли симуляционное время (/clock)'
    )

    declare_params_file = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(pkg_nav2, 'config', 'nav2_params.yaml'),
        description='Полный путь к конфигурационному файлу nav2_params.yaml'
    )

    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg_nav2, 'maps', 'polygon_empty_4x4.yaml'),
        description='Полный путь к файлу статической карты полигона (.yaml)'
    )

    declare_autostart = DeclareLaunchArgument(
        'autostart',
        default_value='true',
        description='Автоматический переход lifecycle нод в состояние Active'
    )

    declare_use_localization = DeclareLaunchArgument(
        'use_localization',
        default_value='true',
        description='Запускать ли карту и локализацию (false при использовании slam_toolbox)'
    )

    declare_use_amcl = DeclareLaunchArgument(
        'use_amcl',
        default_value='false',
        description='Использовать ли AMCL для вероятностной локализации (false: навигация чисто по одометрии + static TF map->odom)'
    )

    declare_initial_x = DeclareLaunchArgument(
        'initial_x',
        default_value='0.4',
        description='Начальная координата X робота на карте полигона (м)'
    )

    declare_initial_y = DeclareLaunchArgument(
        'initial_y',
        default_value='0.4',
        description='Начальная координата Y робота на карте полигона (м)'
    )

    declare_initial_yaw = DeclareLaunchArgument(
        'initial_yaw',
        default_value='0.0',
        description='Начальный угол рыскания Yaw робота на карте (рад)'
    )

    use_sim_time = LaunchConfiguration('use_sim_time')
    params_file = LaunchConfiguration('params_file')
    map_yaml_file = LaunchConfiguration('map')
    autostart = LaunchConfiguration('autostart')
    use_localization = LaunchConfiguration('use_localization')
    use_amcl = LaunchConfiguration('use_amcl')
    initial_x = LaunchConfiguration('initial_x')
    initial_y = LaunchConfiguration('initial_y')
    initial_yaw = LaunchConfiguration('initial_yaw')

    # Переопределение параметра yaml_filename в map_server на переданный аргумент map
    param_substitutions = {
        'use_sim_time': use_sim_time,
        'yaml_filename': map_yaml_file
    }

    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            param_rewrites=param_substitutions,
            convert_types=True
        ),
        allow_substs=True
    )

    # 1. Ноды локализации и карты (map_server + статический TF или AMCL)
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[configured_params]
    )

    # Режим А (по умолчанию): навигация чисто по идеальной колесной одометрии
    # Статический TF map -> odom жестко фиксирует начало отсчета одометрии на карте
    static_tf_map_to_odom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_map_to_odom',
        output='screen',
        arguments=[
            '--x', initial_x,
            '--y', initial_y,
            '--z', '0.0',
            '--yaw', initial_yaw,
            '--pitch', '0.0',
            '--roll', '0.0',
            '--frame-id', 'map',
            '--child-frame-id', 'odom'
        ],
        condition=UnlessCondition(use_amcl)
    )

    loc_lifecycle_manager_odom = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_localization',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': autostart,
            'node_names': ['map_server'],
            'bond_timeout': 0.0
        }],
        condition=UnlessCondition(use_amcl)
    )

    # Режим Б: AMCL (если явно указано use_amcl:=true)
    amcl_node = Node(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[configured_params],
        condition=IfCondition(use_amcl)
    )

    loc_lifecycle_manager_amcl = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_localization',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': autostart,
            'node_names': ['map_server', 'amcl'],
            'bond_timeout': 0.0
        }],
        condition=IfCondition(use_amcl)
    )

    localization_group = GroupAction(
        condition=IfCondition(use_localization),
        actions=[
            map_server_node,
            static_tf_map_to_odom,
            loc_lifecycle_manager_odom,
            amcl_node,
            loc_lifecycle_manager_amcl
        ]
    )

    # 2. Ноды навигации (Controller, Smoother, Planner, Behaviors, BT Navigator)
    controller_node = Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        output='screen',
        parameters=[configured_params],
        remappings=[('cmd_vel', 'cmd_vel_nav')]
    )

    smoother_node = Node(
        package='nav2_velocity_smoother',
        executable='velocity_smoother',
        name='velocity_smoother',
        output='screen',
        parameters=[configured_params],
        remappings=[
            ('cmd_vel', 'cmd_vel_nav'),
            ('cmd_vel_smoothed', 'cmd_vel')
        ]
    )

    planner_node = Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        output='screen',
        parameters=[configured_params]
    )

    behavior_server_node = Node(
        package='nav2_behaviors',
        executable='behavior_server',
        name='behavior_server',
        output='screen',
        parameters=[configured_params]
    )

    bt_navigator_node = Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        output='screen',
        parameters=[configured_params],
        remappings=[('goal_pose', LaunchConfiguration('goal_pose_topic'))]
    )

    nav_lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': autostart,
            'node_names': [
                'controller_server',
                'velocity_smoother',
                'planner_server',
                'behavior_server',
                'bt_navigator'
            ],
            'bond_timeout': 0.0
        }]
    )

    return LaunchDescription([
        DeclareLaunchArgument('goal_pose_topic', default_value='/goal_pose'),
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        declare_use_sim_time,
        declare_params_file,
        declare_map,
        declare_autostart,
        declare_use_localization,
        declare_use_amcl,
        declare_initial_x,
        declare_initial_y,
        declare_initial_yaw,

        # Локализация (чисто одометрия + static TF по умолчанию, либо AMCL)
        localization_group,

        # Навигация
        controller_node,
        smoother_node,
        planner_node,
        behavior_server_node,
        bt_navigator_node,
        nav_lifecycle_manager
    ])

