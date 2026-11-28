#!/usr/bin/env python3
"""Filter aligned RealSense depth before it enters the fused RTAB-Map graph."""

from __future__ import annotations

import cv2
from cv_bridge import CvBridge, CvBridgeError
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener

from surface import rotation


KERNEL = np.ones((3, 3), dtype=np.uint8)


def filter_depth(depth, height_per_meter, camera_height, max_height, preserve_foreground=False):
    valid = np.isfinite(depth) & (depth > 0) & (depth <= 2.5)
    heights = camera_height + depth * height_per_meter
    valid &= (heights >= -0.035) & (heights <= max_height)

    # Invalidate both sides of a depth discontinuity, including the uncertain
    # occlusion strip. Compare measured depths before applying the height mask.
    measured = np.isfinite(depth) & (depth > 0)
    if preserve_foreground:
        nearest = cv2.erode(np.where(measured, depth, np.float32(100.0)), KERNEL)
        median = cv2.medianBlur(np.where(measured, depth, np.float32(0.0)), 3)
        valid &= depth - nearest <= 0.05 + 0.02 * depth
        valid &= (median == 0) | (median - depth <= 0.12)
        return valid & (cv2.erode(measured.astype(np.uint8), KERNEL) != 0)
    edges = np.zeros(depth.shape, dtype=np.uint8)
    horizontal = (measured[:, 1:] & measured[:, :-1] &
                  (np.abs(depth[:, 1:] - depth[:, :-1]) >
                   0.05 + 0.02 * np.minimum(depth[:, 1:], depth[:, :-1])))
    vertical = (measured[1:, :] & measured[:-1, :] &
                (np.abs(depth[1:, :] - depth[:-1, :]) >
                 0.05 + 0.02 * np.minimum(depth[1:, :], depth[:-1, :])))
    edges[:, 1:] |= horizontal
    edges[:, :-1] |= horizontal
    edges[1:, :] |= vertical
    edges[:-1, :] |= vertical
    valid &= cv2.dilate(edges, KERNEL) == 0
    valid &= cv2.erode(measured.astype(np.uint8), KERNEL) != 0
    return valid


class MappingDepthFilter(Node):
    def __init__(self):
        from rtabmap_msgs.msg import RGBDImage

        super().__init__('mapping_depth_filter')
        self.max_height = self.declare_parameter('max_height', 0.40).value
        self.preserve_foreground = self.declare_parameter('preserve_foreground', False).value
        self.bridge = CvBridge()
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.geometry = None
        self.height_per_meter = None
        self.output = self.create_publisher(RGBDImage, 'rgbd_image', 2)
        self.create_subscription(RGBDImage, 'rgbd_unfiltered', self.frame, 2)

    def frame(self, msg: RGBDImage):
        info = msg.depth_camera_info
        image = msg.depth
        if (image.encoding not in ('16UC1', '32FC1') or
                (image.width, image.height) != (info.width, info.height) or min(info.k[0], info.k[4]) <= 0):
            self.get_logger().warning('Expected calibrated aligned depth', throttle_duration_sec=5.0)
            return
        try:
            tf = self.buffer.lookup_transform('base_footprint', info.header.frame_id, Time.from_msg(msg.header.stamp))
            up = rotation(tf.transform.rotation)[2]
            geometry = (image.width, image.height, *info.k, *up)
            if geometry != self.geometry:
                x = (np.arange(image.width, dtype=np.float32) - info.k[2]) / info.k[0]
                y = (np.arange(image.height, dtype=np.float32) - info.k[5]) / info.k[4]
                self.height_per_meter = up[0] * x[None, :] + up[1] * y[:, None] + up[2]
                self.geometry = geometry
            raw = self.bridge.imgmsg_to_cv2(image)
            depth = raw.astype(np.float32)
            if image.encoding == '16UC1':
                depth *= 0.001
            keep = filter_depth(depth, self.height_per_meter, tf.transform.translation.z, self.max_height,
                                self.preserve_foreground)
            msg.depth = self.bridge.cv2_to_imgmsg(np.where(keep, raw, 0), encoding=image.encoding,
                                                  header=image.header)
            self.output.publish(msg)
        except (TransformException, CvBridgeError, ValueError, cv2.error) as error:
            self.get_logger().warning(str(error), throttle_duration_sec=5.0)


def main():
    rclpy.init()
    node = MappingDepthFilter()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
