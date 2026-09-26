#!/usr/bin/env python3
"""Read confirmed QR text from a compressed RealSense colour stream."""

import os
import time
from datetime import datetime
from typing import Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String

from .qr_decoder import QrConfirmation, annotate_qr_jpeg, decode_jpeg


class QrReaderNode(Node):
    """Decode QR codes on demand (snapshot mode) or from stream, publishing confirmed source text."""

    def __init__(self) -> None:
        super().__init__('qr_reader_node')
        self.declare_parameter('image_topic', '/camera/color/image_raw/compressed')
        self.declare_parameter('status_topic', '/victim_status')
        self.declare_parameter('detected_topic', '/vision/qr/detected')
        self.declare_parameter('qr_image_topic', '/vision/qr/image/compressed')
        self.declare_parameter('mission_state_topic', '/mission/state')
        self.declare_parameter('confirm_frames', 1)
        self.declare_parameter('snapshot_mode', False)
        self.declare_parameter('state_filter_enabled', True)
        self.declare_parameter('trigger_topic', '/vision/take_photo')
        self.declare_parameter('save_snapshot', True)
        self.declare_parameter('log_dir', 'log')

        image_topic = self.get_parameter('image_topic').value
        status_topic = self.get_parameter('status_topic').value
        detected_topic = self.get_parameter('detected_topic').value
        qr_image_topic = self.get_parameter('qr_image_topic').value
        mission_state_topic = self.get_parameter('mission_state_topic').value
        confirm_frames = int(self.get_parameter('confirm_frames').value)
        self._snapshot_mode = bool(self.get_parameter('snapshot_mode').value)
        self._state_filter_enabled = bool(self.get_parameter('state_filter_enabled').value)
        trigger_topic = self.get_parameter('trigger_topic').value
        self._save_snapshot = bool(self.get_parameter('save_snapshot').value)
        self._log_dir = str(self.get_parameter('log_dir').value)

        self._confirmation = QrConfirmation(confirm_frames)
        self._last_frame = 0.0
        self._last_publication = 0.0
        self._last_stamp = None
        self._last_logged_text = None
        self._last_saved_text: Optional[str] = None
        self._latest_image_msg: Optional[CompressedImage] = None
        self._current_mission_state: Optional[str] = None
        self._allowed_states = ('SEARCHING_VICTIM', 'READING_QR')

        self._status_publisher = self.create_publisher(String, status_topic, 10)
        self._detected_publisher = self.create_publisher(Bool, detected_topic, 10)
        self._qr_image_publisher = self.create_publisher(CompressedImage, qr_image_topic, 10)

        self.create_subscription(
            CompressedImage, image_topic, self._image_callback,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        )

        self.create_subscription(
            Bool, trigger_topic, self._trigger_callback, 10
        )

        self.create_subscription(
            String, mission_state_topic, self._mission_state_callback, 10
        )

        self.create_timer(0.5, self._check_stream)
        self.get_logger().info(
            f'QR reader started: {image_topic} -> {status_topic}; '
            f'snapshot_mode: {self._snapshot_mode}; state_filter: {self._state_filter_enabled}; '
            f'trigger: {trigger_topic}; confirmation frames: {confirm_frames}'
        )

    def _mission_state_callback(self, message: String) -> None:
        new_state = message.data.strip()
        if new_state != self._current_mission_state:
            allowed = getattr(self, '_allowed_states', ('SEARCHING_VICTIM', 'READING_QR'))
            if self._current_mission_state in allowed and new_state not in allowed:
                self._confirmation.reset()
                self._last_stamp = None
            self._current_mission_state = new_state

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
        self._process_image(self._latest_image_msg, force=True)

    def _image_callback(self, message: CompressedImage) -> None:
        self._latest_image_msg = message
        # В режиме снимков (snapshot_mode) не декодируем непрерывный видеопоток
        if getattr(self, '_snapshot_mode', False):
            return
        # Фильтрация потока по состоянию миссии
        if getattr(self, '_state_filter_enabled', True):
            allowed = getattr(self, '_allowed_states', ('SEARCHING_VICTIM', 'READING_QR'))
            current = getattr(self, '_current_mission_state', None)
            if current not in allowed:
                return
        self._process_image(message)

    def _save_qr_snapshot(self, jpeg_bytes: bytes) -> Optional[str]:
        try:
            raw_log_dir = getattr(self, '_log_dir', 'log')
            if raw_log_dir == 'log':
                log_dir = os.environ.get('IJKBOT_LOG_DIR')
                if not log_dir:
                    repo_log = '/home/lev/IJKbot/log'
                    if os.path.isdir(repo_log):
                        log_dir = repo_log
                    else:
                        log_dir = os.path.abspath('log')
            else:
                log_dir = os.path.abspath(raw_log_dir) if not os.path.isabs(raw_log_dir) else raw_log_dir

            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'qr_snapshot_{timestamp}.jpg'
            filepath = os.path.join(log_dir, filename)
            counter = 1
            while os.path.exists(filepath):
                timestamp_ms = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:19]
                filename = f'qr_snapshot_{timestamp_ms}_{counter}.jpg'
                filepath = os.path.join(log_dir, filename)
                counter += 1
            with open(filepath, 'wb') as f:
                f.write(jpeg_bytes)
            self.get_logger().info(f'Судейский снимок QR сохранен: {filepath}')
            return filepath
        except Exception as error:
            self.get_logger().error(f'Не удалось сохранить снимок QR на диск: {error}')
            return None

    def _process_image(self, message: CompressedImage, force: bool = False) -> None:
        now = time.monotonic()
        stream_gap = now - self._last_frame > 1.0
        repeat_due = self._last_publication and now - self._last_publication >= 1.0
        if stream_gap or repeat_due:
            self._confirmation.reset()
            self._last_publication = 0.0
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        if not force and stamp != (0, 0) and stamp == self._last_stamp and not getattr(self, '_snapshot_mode', False):
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
        if confirmed_text is None and force and detection is not None and detection.text:
            confirmed_text = detection.text

        if confirmed_text is None:
            return

        status = String()
        status.data = confirmed_text
        self._status_publisher.publish(status)
        self._last_publication = now

        # Подготовка аннотированного снимка с зеленой рамкой
        annotated_bytes = None
        if detection is not None:
            annotated_bytes = getattr(detection, 'annotated_jpeg', None)
            if annotated_bytes is None and detection.corners:
                annotated_bytes = annotate_qr_jpeg(bytes(message.data), detection.corners)
        if annotated_bytes is None:
            annotated_bytes = bytes(message.data)

        # Публикация аннотированного сжатого кадра
        if getattr(self, '_qr_image_publisher', None) is not None:
            qr_img_msg = CompressedImage()
            qr_img_msg.header = message.header
            if qr_img_msg.header.stamp.sec == 0 and qr_img_msg.header.stamp.nanosec == 0:
                if hasattr(self, 'get_clock'):
                    qr_img_msg.header.stamp = self.get_clock().now().to_msg()
            qr_img_msg.format = 'jpeg'
            qr_img_msg.data = annotated_bytes
            self._qr_image_publisher.publish(qr_img_msg)

        # Автоматическое сохранение на диск (дедуплицировано, чтобы не забивать диск при републикациях)
        if getattr(self, '_save_snapshot', True):
            if force or confirmed_text != getattr(self, '_last_saved_text', None):
                self._save_qr_snapshot(annotated_bytes)
                self._last_saved_text = confirmed_text

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
