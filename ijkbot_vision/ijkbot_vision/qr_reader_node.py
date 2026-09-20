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
    """Decode QR codes on demand (snapshot mode) or from stream, publishing confirmed source text."""

    def __init__(self) -> None:
        super().__init__('qr_reader_node')
        self.declare_parameter('image_topic', '/camera/color/image_raw/compressed')
        self.declare_parameter('status_topic', '/victim_status')
        self.declare_parameter('detected_topic', '/vision/qr/detected')
        self.declare_parameter('confirm_frames', 1)
        self.declare_parameter('snapshot_mode', True)
        self.declare_parameter('trigger_topic', '/vision/take_photo')

        image_topic = self.get_parameter('image_topic').value
        status_topic = self.get_parameter('status_topic').value
        detected_topic = self.get_parameter('detected_topic').value
        confirm_frames = int(self.get_parameter('confirm_frames').value)
        self._snapshot_mode = bool(self.get_parameter('snapshot_mode').value)
        trigger_topic = self.get_parameter('trigger_topic').value

        self._confirmation = QrConfirmation(confirm_frames)
        self._last_frame = 0.0
        self._last_publication = 0.0
        self._last_stamp = None
        self._last_logged_text = None
        self._latest_image_msg: Optional[CompressedImage] = None

        self._status_publisher = self.create_publisher(String, status_topic, 10)
        self._detected_publisher = self.create_publisher(Bool, detected_topic, 10)

        self.create_subscription(
            CompressedImage, image_topic, self._image_callback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        )

        # Подписка на триггер фотосъемки (в snapshot режиме обработка запускается только по триггеру)
        self.create_subscription(
            Bool, trigger_topic, self._trigger_callback, 10
        )

        self.create_timer(0.5, self._check_stream)
        self.get_logger().info(
            f'QR reader started: {image_topic} -> {status_topic}; '
            f'snapshot_mode: {self._snapshot_mode}; trigger: {trigger_topic}; '
            f'confirmation frames: {confirm_frames}'
        )

    def _check_stream(self) -> None:
        if self._last_frame and time.monotonic() - self._last_frame > 1.0:
            self._confirmation.reset()
            self._last_stamp = None
            self._detected_publisher.publish(Bool(data=False))

    def _trigger_callback(self, message: Bool) -> None:
        if not message.data:
            return
        if self._latest_image_msg is None:
            self.get_logger().warning('Триггер фото получен, но кадры от камеры еще не поступали!')
            return
        self.get_logger().info('Получен триггер фото: обработка единичного кадра для поиска QR...')
        self._process_image(self._latest_image_msg)

    def _image_callback(self, message: CompressedImage) -> None:
        self._latest_image_msg = message
        # В режиме снимков (snapshot_mode) не декодируем непрерывный видеопоток для экономии CPU!
        if getattr(self, '_snapshot_mode', False):
            return
        self._process_image(message)

    def _process_image(self, message: CompressedImage) -> None:
        now = time.monotonic()
        stream_gap = now - self._last_frame > 1.0
        repeat_due = self._last_publication and now - self._last_publication >= 1.0
        if stream_gap or repeat_due:
            self._confirmation.reset()
            self._last_publication = 0.0
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        if stamp != (0, 0) and stamp == self._last_stamp and not getattr(self, '_snapshot_mode', False):
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
