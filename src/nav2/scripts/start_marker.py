#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from visualization_msgs.msg import Marker


class StartMarker(Node):
    def __init__(self) -> None:
        super().__init__('start_marker')
        qos = rclpy.qos.QoSProfile(depth=1)
        qos.durability = rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL
        self.publisher = self.create_publisher(Marker, 'start_marker', qos)
        self.publish_marker()

    def publish_marker(self) -> None:
        marker = Marker()
        marker.header.frame_id = 'map'
        marker.ns = 'polygon'
        marker.id = 0
        marker.type = Marker.CUBE
        marker.action = Marker.ADD
        marker.pose.position.x = 0.4
        marker.pose.position.y = 0.4
        marker.pose.position.z = 0.015
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.72
        marker.scale.y = 0.72
        marker.scale.z = 0.03
        marker.color.r = 0.21
        marker.color.g = 0.72
        marker.color.b = 0.42
        marker.color.a = 0.75
        marker.lifetime.sec = 0
        self.publisher.publish(marker)


def main() -> None:
    rclpy.init()
    node = StartMarker()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()