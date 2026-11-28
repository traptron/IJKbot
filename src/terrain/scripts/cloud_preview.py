#!/usr/bin/env python3
"""Publish a bandwidth-limited view of the ray-traced occupied OctoMap cells."""

import numpy as np
import rclpy
from geometry_msgs.msg import Point
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py.point_cloud2 import read_points
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker


def voxel_marker(cloud: PointCloud2, max_height: float) -> Marker:
    marker = Marker(header=cloud.header, ns='rtabmap', id=0, type=Marker.CUBE_LIST)
    marker.pose.orientation.w = 1.0
    marker.color = ColorRGBA(r=0.35, g=0.72, b=0.95, a=1.0)
    points = read_points(cloud).reshape(-1)
    # Bound processing time even when the full-resolution map has millions of points.
    sample = points[::max(1, (points.size + 119999) // 120000)]
    xyz = np.column_stack((sample['x'], sample['y'], sample['z']))
    valid = np.isfinite(xyz).all(axis=1)
    if max_height > 0:
        valid &= xyz[:, 2] <= max_height
    xyz = xyz[valid]
    if not len(xyz):
        marker.action = Marker.DELETE
        return marker

    side = 0.035
    while True:
        cells = np.floor(xyz / side).astype(np.int64)
        occupied, first = np.unique(cells, axis=0, return_index=True)
        if len(occupied) <= 8000:
            break
        side *= 1.5
    marker.scale.x = marker.scale.y = marker.scale.z = side
    centers = (occupied + 0.5) * side
    if max_height > 0:
        inside = (centers[:, 2] + side / 2) <= max_height + 1e-9
        centers = centers[inside]
        first = first[inside]
        if not len(centers):
            marker.action = Marker.DELETE
    marker.points = [Point(x=x, y=y, z=z) for x, y, z in centers.tolist()]
    color_field = next((key for key in ('rgb', 'rgba') if key in sample.dtype.names), None)
    if color_field:
        packed = sample[color_field][valid][first].view(np.uint32)
        marker.colors = [
            ColorRGBA(r=((p >> 16) & 255) / 255, g=((p >> 8) & 255) / 255,
                      b=(p & 255) / 255, a=1.0) for p in packed.tolist()
        ]
    return marker


class CloudPreview(Node):
    def __init__(self):
        super().__init__('terrain_cloud_preview')
        self.max_height = self.declare_parameter('max_height', 0.0).value
        self.cloud_topic = self.declare_parameter(
            'cloud_topic', '/terrain/slam/octomap_occupied_space').value
        self.latest = None
        self.cloud_sub = None
        self.qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.preview = self.create_publisher(Marker, '/terrain/rviz_map', self.qos)
        self.create_timer(2.0, self.update_view)

    def receive(self, cloud: PointCloud2):
        self.latest = cloud

    def update_view(self):
        if self.preview.get_subscription_count() == 0:
            if self.cloud_sub is not None:
                self.destroy_subscription(self.cloud_sub)
                self.cloud_sub = None
                self.latest = None
            return
        if self.cloud_sub is None:
            self.cloud_sub = self.create_subscription(
                PointCloud2, self.cloud_topic, self.receive, self.qos)
        if self.latest is not None:
            self.preview.publish(voxel_marker(self.latest, self.max_height))
            self.latest = None


def main():
    rclpy.init()
    node = CloudPreview()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
