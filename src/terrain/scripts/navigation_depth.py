#!/usr/bin/env python3
"""Supply live RGB-D obstacles to Nav2 and stop when sensor data is stale."""

import time

from cv_bridge import CvBridge, CvBridgeError
import numpy as np
import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image, LaserScan, PointCloud2
from sensor_msgs_py.point_cloud2 import create_cloud_xyz32
from tf2_ros import Buffer, TransformException, TransformListener

from mapping_depth_filter import filter_depth
from surface import rotation


class NavigationDepth(Node):
    def __init__(self):
        super().__init__('navigation_depth')
        self.bridge = CvBridge()
        self.max_height = self.declare_parameter('max_height', 0.40).value
        self.camera_info = None
        self.pending_depth = None
        self.geometry = None
        self.rays = None
        self.height_per_meter = None
        self.floor_samples = None
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.last_depth = self.last_scan = self.last_command = float('-inf')
        self.command = Twist()
        self.blocked = None
        self.cloud = self.create_publisher(PointCloud2, '/navigation/depth_points', 2)
        self.velocity = self.create_publisher(Twist, '/cmd_vel_depth_safe', 10)
        self.create_subscription(CameraInfo, '/camera/depth/camera_info', self.calibration, 1)
        self.create_subscription(Image, '/camera/depth/image_rect_raw', self.receive_depth, 1)
        self.create_subscription(LaserScan, '/scan', self.scan, qos_profile_sensor_data)
        self.create_subscription(Twist, '/cmd_vel_depth_input', self.receive_command, 10)
        self.create_timer(0.05, self.update)

    def calibration(self, msg):
        self.camera_info = msg

    def receive_depth(self, msg):
        self.pending_depth = msg

    def age(self, stamp):
        return (self.get_clock().now() - stamp).nanoseconds * 1e-9

    def scan(self, msg):
        age = self.age(Time.from_msg(msg.header.stamp))
        if -0.05 <= age <= 0.5 and any(
            msg.range_min <= value <= msg.range_max for value in msg.ranges
        ):
            self.last_scan = time.monotonic() - max(age, 0.0)

    def process_depth(self):
        image, info = self.pending_depth, self.camera_info
        if image is None or info is None:
            return
        stamp = Time.from_msg(image.header.stamp)
        age = self.age(stamp)
        if not -0.05 <= age <= 0.5:
            self.pending_depth = None
            return
        if (image.encoding not in ('16UC1', '32FC1') or
                (image.width, image.height, image.header.frame_id) !=
                (info.width, info.height, info.header.frame_id) or
                not np.isfinite(info.k).all() or min(info.k[0], info.k[4]) <= 0):
            self.pending_depth = None
            self.get_logger().warning('Expected calibrated depth', throttle_duration_sec=5.0)
            return

        # An image can arrive just ahead of the wheel TF. Let the next tick retry
        # the latest image while it is fresh instead of discarding that frame.
        if not self.buffer.can_transform('odom', image.header.frame_id, stamp):
            return
        try:
            tf = self.buffer.lookup_transform('base_footprint', image.header.frame_id, stamp).transform
            self.pending_depth = None
            up = rotation(tf.rotation)[2]
            geometry = (image.width, image.height, *info.k, *up)
            if geometry != self.geometry:
                x = (np.arange(image.width, dtype=np.float32) - info.k[2]) / info.k[0]
                y = (np.arange(image.height, dtype=np.float32) - info.k[5]) / info.k[4]
                x, y = np.meshgrid(x, y)
                self.rays = np.stack((x, y, np.ones_like(x)), axis=-1)
                self.height_per_meter = up[0] * x + up[1] * y + up[2]
                self.floor_samples = np.zeros(self.rays[::2, ::2].shape[:2], dtype=bool)
                self.floor_samples[::3, ::3] = True
                self.geometry = geometry

            depth = self.bridge.imgmsg_to_cv2(image).astype(np.float32)
            if image.encoding == '16UC1':
                depth *= 0.001
            # Filter the native image before subsampling to preserve small edges.
            keep = filter_depth(depth, self.height_per_meter, tf.translation.z,
                                self.max_height, preserve_foreground=True)[::2, ::2]
            sampled = depth[::2, ::2]
            if np.count_nonzero(keep) < 50:
                return
            heights = tf.translation.z + self.height_per_meter[::2, ::2] * sampled
            # Keep dense obstacle returns and a sparser set of clearing rays to the floor.
            keep &= (heights >= 0.025) | self.floor_samples
            points = self.rays[::2, ::2][keep] * sampled[keep, None]
            age = self.age(stamp)
            if age <= 0.5:
                self.cloud.publish(create_cloud_xyz32(image.header, points))
                self.last_depth = time.monotonic() - max(age, 0.0)
        except (TransformException, CvBridgeError, ValueError) as error:
            self.get_logger().warning(str(error), throttle_duration_sec=5.0)

    def update(self):
        self.process_depth()
        self.forward()

    def receive_command(self, msg):
        self.command = msg
        self.last_command = time.monotonic()

    def forward(self):
        now = time.monotonic()
        blocked = now - self.last_depth > 0.5 or now - self.last_scan > 0.5
        if blocked != self.blocked:
            self.get_logger().info('Движение заблокировано: ожидаем свежие D435 и лидар'
                                   if blocked else 'D435 и лидар поступают, контроль глубины активен')
            self.blocked = blocked
        self.velocity.publish(Twist() if blocked or now - self.last_command > 0.2 else self.command)


def main():
    rclpy.init()
    node = NavigationDepth()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.velocity.publish(Twist())
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
