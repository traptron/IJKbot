#!/usr/bin/env python3

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


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
        description='Запускать ли map_server и AMCL (false при использовании slam_toolbox)'
    )

    use_sim_time = LaunchConfiguration('use_sim_time')
    params_file = LaunchConfiguration('params_file')
    map_yaml_file = LaunchConfiguration('map')
    autostart = LaunchConfiguration('autostart')
    use_localization = LaunchConfiguration('use_localization')

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

    # 1. Ноды локализации и карты (map_server + amcl)
    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[configured_params],
        condition=IfCondition(use_localization)
    )

    amcl_node = Node(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[configured_params],
        condition=IfCondition(use_localization)
    )

    loc_lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_localization',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': autostart,
            'autostart': True,
            'node_names': ['map_server', 'amcl']
        }],
        condition=IfCondition(use_localization)
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
        parameters=[configured_params]
    )

    nav_lifecycle_manager = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': autostart,
            'autostart': True,
            'node_names': [
                'controller_server',
                'velocity_smoother',
                'planner_server',
                'behavior_server',
                'bt_navigator'
            ]
        }]
    )

    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        declare_use_sim_time,
        declare_params_file,
        declare_map,
        declare_autostart,
        declare_use_localization,

        # Локализация
        map_server_node,
        amcl_node,
        loc_lifecycle_manager,

        # Навигация
        controller_node,
        smoother_node,
        planner_node,
        behavior_server_node,
        bt_navigator_node,
        nav_lifecycle_manager
    ])

