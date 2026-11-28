#!/usr/bin/env python3
"""Publish a VGA JPEG preview without consuming the Full HD stream over Wi-Fi."""

import time

import cv2
from cv_bridge import CvBridge, CvBridgeError
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image


class CameraPreview(Node):
    def __init__(self):
        super().__init__('mapping_camera_preview')
        self.bridge = CvBridge()
        self.quality = self.declare_parameter('jpeg_quality', 65).value
        max_fps = self.declare_parameter('max_fps', 0.0).value
        self.period = 1.0 / max_fps if max_fps > 0 else 0.0
        self.last_frame = float('-inf')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.preview = self.create_publisher(CompressedImage, '/camera/preview/image_raw/compressed', qos)
        # The D435 publisher is reliable. Use retransmission for the large
        # onboard frames while keeping the Wi-Fi JPEG publisher best effort.
        self.create_subscription(Image, '/camera/color/image_raw', self.frame,
                                 QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))

    def frame(self, message):
        now = time.monotonic()
        if now - self.last_frame < self.period or self.preview.get_subscription_count() == 0:
            return
        self.last_frame = now
        try:
            image = self.bridge.imgmsg_to_cv2(message, 'bgr8')
            scale = min(640 / message.width, 480 / message.height)
            width, height = round(message.width * scale), round(message.height * scale)
            resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            top, left = (480 - height) // 2, (640 - width) // 2
            preview = cv2.copyMakeBorder(resized, top, 480 - height - top,
                                         left, 640 - width - left, cv2.BORDER_CONSTANT)
            encoded, jpeg = cv2.imencode('.jpg', preview, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if encoded:
                self.preview.publish(CompressedImage(header=message.header,
                                                     format='bgr8; jpeg compressed bgr8',
                                                     data=jpeg.tobytes()))
        except (CvBridgeError, cv2.error) as error:
            self.get_logger().warning(str(error), throttle_duration_sec=5.0)


def main():
    rclpy.init()
    node = CameraPreview()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
