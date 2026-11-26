#!/usr/bin/env python3

import os
import shutil
import subprocess
from xml.etree import ElementTree

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration, Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def add_locking_deck_visuals(urdf, cad_file):
    """Overlay CAD visuals while retaining the robot's operational joints."""
    robot = ElementTree.fromstring(urdf)
    cad = ElementTree.parse(cad_file).getroot()
    links = {link.attrib['name']: link for link in robot.findall('link')}
    robot.extend(cad.findall('material'))
    for part in cad.findall('link'):
        name = part.attrib['name']
        visuals = part.findall('visual')
        if name in links and visuals:
            for old_visual in links[name].findall('visual'):
                links[name].remove(old_visual)
        if name == 'base_link':
            links[name].extend(visuals)
        elif visuals:
            # The CAD part may be attached at a different pose from the sensor TF.
            # Keep the CAD pose in a separate frame used only for visualization.
            visual_link = ElementTree.SubElement(robot, 'link', name=f'cad_{name}')
            visual_link.extend(visuals)
    for joint in cad.findall('joint'):
        child = joint.find('child')
        name = child.attrib['link']
        if robot.find(f"link[@name='cad_{name}']") is not None:
            joint.set('name', f"cad_{joint.attrib['name']}")
            child.set('link', f'cad_{name}')
            robot.append(joint)
    return ElementTree.tostring(robot, encoding='unicode')


def launch_state_publisher(context):
    pkg_description = get_package_share_directory('description')
    xacro_file = os.path.join(pkg_description, 'urdf', 'ijkbot.urdf.xacro')
    urdf_fallback = os.path.join(pkg_description, 'urdf', 'ijkbot.urdf')

    use_sim_time = LaunchConfiguration('use_sim_time')
    model = LaunchConfiguration('robot_model').perform(context)

    # Определение команды xacro или fallback на статический URDF
    xacro_cmd = shutil.which('xacro') or (
        os.path.expanduser('~/.local/bin/xacro')
        if os.path.exists(os.path.expanduser('~/.local/bin/xacro'))
        else None
    )

    if model == 'locking_deck':
        if not xacro_cmd or not os.path.isfile(xacro_file):
            raise RuntimeError('Для модели locking_deck нужен ijkbot.urdf.xacro и Xacro')
        result = subprocess.run([xacro_cmd, xacro_file], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'Ошибка генерации URDF: {result.stderr.strip()}')
        cad_file = os.path.join(pkg_description, 'urdf', 'ijkbot_locking_deck.urdf')
        robot_description = ParameterValue(
            add_locking_deck_visuals(result.stdout, cad_file), value_type=str
        )
    elif xacro_cmd and os.path.exists(xacro_file):
        robot_description = ParameterValue(
            Command([xacro_cmd, ' ', xacro_file]),
            value_type=str
        )
    elif os.path.exists(urdf_fallback):
        with open(urdf_fallback, 'r', encoding='utf-8') as f:
            robot_description = f.read()
    else:
        robot_description = ParameterValue(
            Command(['xacro ', xacro_file]),
            value_type=str
        )

    # Нода публикации состояния робота (публикует дерево TF статических и подвижных звеньев)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'use_sim_time': use_sim_time
        }]
    )

    return [LogInfo(msg=f'Модель IJKbot: {model}'), robot_state_publisher_node]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time', default_value='false',
            description='Использовать симуляционное время (/clock)',
        ),
        DeclareLaunchArgument('robot_model', default_value='legacy', choices=['legacy', 'locking_deck']),
        OpaqueFunction(function=launch_state_publisher),
    ])

