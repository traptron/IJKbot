#!/usr/bin/env python3
"""Laptop-side City sign recognition and optional live judge preview."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('image_topic',
                              default_value='/camera/color/image_raw/compressed'),
        DeclareLaunchArgument('show_video', default_value='true'),
        DeclareLaunchArgument('minimum_score', default_value='0.68'),
        DeclareLaunchArgument('confirm_frames', default_value='3'),
        Node(
            package='vision', executable='city_sign_node', name='city_sign_node',
            output='screen', parameters=[{
                'image_topic': LaunchConfiguration('image_topic'),
                'minimum_score': LaunchConfiguration('minimum_score'),
                'confirm_frames': LaunchConfiguration('confirm_frames'),
            }],
        ),
        Node(
            package='vision_cpp', executable='video_viewer',
            name='city_sign_preview', output='screen',
            parameters=[{
                'image_topic': '/vision/traffic_sign/image/compressed',
                'window_title': 'IJKbot City - road signs',
                'complete_topic': '/city/vision/complete',
            }],
            condition=IfCondition(LaunchConfiguration('show_video')),
        ),
    ])
