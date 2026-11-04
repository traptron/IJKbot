#!/usr/bin/env python3
"""ROS 2 road-sign reader for the City hackathon camera stream."""

import json
import signal
import time
from typing import Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .city_signs import annotate, detect_signs


class CitySignNode(Node):
    """Publish conservative sign detections and compressed annotated previews."""

    def __init__(self) -> None:
        super().__init__('city_sign_node')
        self.declare_parameter('image_topic', '/camera/color/image_raw/compressed')
        self.declare_parameter('detections_topic', '/vision/traffic_sign/detections')
        self.declare_parameter('confirmed_topic', '/vision/traffic_sign/confirmed')
        self.declare_parameter('preview_topic', '/vision/traffic_sign/image/compressed')
        self.declare_parameter('minimum_score', 0.68)
        self.declare_parameter('confirm_frames', 3)
        self.declare_parameter('max_fps', 5.0)

        image_topic = str(self.get_parameter('image_topic').value)
        minimum_score = float(self.get_parameter('minimum_score').value)
        confirm_frames = int(self.get_parameter('confirm_frames').value)
        max_fps = float(self.get_parameter('max_fps').value)
        if not 0.0 < minimum_score <= 1.0 or confirm_frames < 1 or max_fps <= 0:
            raise ValueError('Invalid City sign detector settings')
        self._minimum_score = minimum_score
        self._confirm_frames = confirm_frames
        self._period = 1.0 / max_fps
        self._last_processed = 0.0
        self._started = time.monotonic()
        self._last_frame: Optional[float] = None
        self._candidate: Optional[str] = None
        self._candidate_count = 0
        self._confirmed: Optional[str] = None
        self._stream_warning = False

        self._detections_pub = self.create_publisher(
            String, str(self.get_parameter('detections_topic').value), 10)
        self._confirmed_pub = self.create_publisher(
            String, str(self.get_parameter('confirmed_topic').value), 10)
        self._preview_pub = self.create_publisher(
            CompressedImage, str(self.get_parameter('preview_topic').value), 2)
        self.create_subscription(CompressedImage, image_topic, self._on_image,
                                 qos_profile_sensor_data)
        self.create_timer(1.0, self._check_stream)
        self.get_logger().info(
            f'Город: распознавание знаков запущено; камера: {image_topic}; '
            f'подтверждение: {confirm_frames} кадра(ов), до {max_fps:g} FPS')

    def _publish_confirmed(self, name: Optional[str], confidence: float = 0.0) -> None:
        payload = {'name': name, 'confidence': round(confidence, 3)}
        self._confirmed_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        if name is None:
            self.get_logger().info('Город: подтвержденный знак сброшен')
        else:
            self.get_logger().info(
                f'Город: подтвержден знак {name}, достоверность {confidence:.2f}')

    def _check_stream(self) -> None:
        last_seen = self._last_frame if self._last_frame is not None else self._started
        if time.monotonic() - last_seen > 2.0:
            if not self._stream_warning:
                self.get_logger().warning('Город: нет сжатых кадров камеры более 2 с')
                self._stream_warning = True
            self._candidate = None
            self._candidate_count = 0
            if self._confirmed is not None:
                self._confirmed = None
                self._publish_confirmed(None)

    def _on_image(self, message: CompressedImage) -> None:
        now = time.monotonic()
        self._last_frame = now
        self._stream_warning = False
        if now - self._last_processed < self._period:
            return
        self._last_processed = now
        try:
            image = cv2.imdecode(np.frombuffer(message.data, dtype=np.uint8),
                                 cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError('JPEG не декодирован')
            height, width = image.shape[:2]
            if width > 640 or height > 480:
                scale = min(640 / width, 480 / height)
                image = cv2.resize(image, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA)
            detections = detect_signs(image, self._minimum_score)
            preview = annotate(image, detections)
            encoded, jpeg = cv2.imencode('.jpg', preview,
                                         [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not encoded:
                raise ValueError('JPEG не закодирован')
        except (cv2.error, ValueError) as error:
            self.get_logger().warning(f'Город: кадр пропущен: {error}')
            return

        self._preview_pub.publish(CompressedImage(
            header=message.header, format='jpeg', data=jpeg.tobytes()))
        payload = [
            {'name': item.name, 'confidence': round(item.confidence, 3),
             'bbox': list(item.bbox)} for item in detections
        ]
        self._detections_pub.publish(
            String(data=json.dumps(payload, ensure_ascii=False)))

        # One unambiguous sign must persist for several *processed* frames.
        candidate = detections[0].name if len(detections) == 1 else None
        if candidate != self._candidate:
            self._candidate = candidate
            self._candidate_count = 1 if candidate else 0
        elif candidate:
            self._candidate_count += 1
        if self._candidate_count >= self._confirm_frames and candidate != self._confirmed:
            self._confirmed = candidate
            self._publish_confirmed(candidate, detections[0].confidence)
        elif candidate is None and self._confirmed is not None:
            self._confirmed = None
            self._publish_confirmed(None)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CitySignNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # ros2 launch may forward a second SIGINT while teardown is in progress.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
