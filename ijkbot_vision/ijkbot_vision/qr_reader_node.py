#!/usr/bin/env python3
"""Read confirmed QR text from a compressed RealSense colour stream."""

from typing import Optional
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String

from .qr_decoder import QrConfirmation, decode_jpeg


class QrReaderNode(Node):
    """Decode QR codes on the laptop and publish the confirmed source text."""

    def __init__(self) -> None:
        super().__init__('qr_reader_node')
        self.declare_parameter('image_topic', '/camera/color/image_raw/compressed')
        self.declare_parameter('status_topic', '/victim_status')
        self.declare_parameter('detected_topic', '/vision/qr/detected')
        self.declare_parameter('confirm_frames', 3)

        image_topic = self.get_parameter('image_topic').value
        status_topic = self.get_parameter('status_topic').value
        detected_topic = self.get_parameter('detected_topic').value
        confirm_frames = int(self.get_parameter('confirm_frames').value)

        self._confirmation = QrConfirmation(confirm_frames)
        self._last_frame = 0.0
        self._last_publication = 0.0
        self._last_stamp = None
        self._last_logged_text = None
        self._status_publisher = self.create_publisher(String, status_topic, 10)
        self._detected_publisher = self.create_publisher(Bool, detected_topic, 10)
        self.create_subscription(
            CompressedImage, image_topic, self._image_callback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        )
        self.create_timer(0.5, self._check_stream)
        self.get_logger().info(
            f'QR reader started: {image_topic} -> {status_topic}; '
            f'confirmation frames: {confirm_frames}'
        )

    def _check_stream(self) -> None:
        if self._last_frame and time.monotonic() - self._last_frame > 1.0:
            self._confirmation.reset()
            self._last_stamp = None
            self._detected_publisher.publish(Bool(data=False))

    def _image_callback(self, message: CompressedImage) -> None:
        now = time.monotonic()
        stream_gap = now - self._last_frame > 1.0
        repeat_due = self._last_publication and now - self._last_publication >= 1.0
        if stream_gap or repeat_due:
            self._confirmation.reset()
            self._last_publication = 0.0
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        if stamp != (0, 0) and stamp == self._last_stamp:
            return
        self._last_stamp = stamp
        self._last_frame = now
        try:
            detection = decode_jpeg(bytes(message.data))
        except RuntimeError as error:
            self.get_logger().error(str(error))
            detection = None
        except Exception as error:
            self.get_logger().warning(f'QR frame decoding failed: {error}', throttle_duration_sec=5)
            detection = None

        detected = Bool()
        detected.data = detection is not None
        self._detected_publisher.publish(detected)

        confirmed_text: Optional[str] = self._confirmation.observe(
            detection.text if detection else None
        )
        if confirmed_text is None:
            return

        status = String()
        status.data = confirmed_text
        self._status_publisher.publish(status)
        self._last_publication = now
        if confirmed_text != self._last_logged_text:
            self.get_logger().info('QR text confirmed and published:\n' + repr(confirmed_text))
            self._last_logged_text = confirmed_text


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = QrReaderNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
