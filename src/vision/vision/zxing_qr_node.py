"""Read QR codes from the newest locally received RealSense frame."""

from io import BytesIO
from math import isfinite
from time import monotonic, perf_counter

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import Bool, String

from .core.qr import QrConfirmation, QrDecoder, image_to_gray


class ZxingQrReader(Node):
    def __init__(self) -> None:
        super().__init__('zxing_qr_reader')
        declared = self.declare_parameters('', [
            ('image_topic', '/camera/color/image_raw'),
            ('status_topic', '/victim_status'),
            ('confirm_frames', 2),
            ('reset_timeout_sec', 1.2),
            ('max_process_hz', 8.0),
            ('try_harder', False),
            ('use_center_crop', False),
            ('center_crop_ratio', 0.7),
            ('publish_confirm_snapshot', False),
            ('snapshot_topic', '/vision/qr/image/compressed'),
            ('require_trigger', False),
            ('trigger_topic', '/vision/take_photo'),
            ('reset_topic', ''),
            ('capture_window_sec', 0.9),
            ('metrics_interval_sec', 5.0),
        ])
        params = {parameter.name: parameter.value for parameter in declared}
        for name in ('max_process_hz', 'capture_window_sec', 'metrics_interval_sec'):
            if not isfinite(params[name]) or params[name] <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if params['require_trigger'] and (not params['trigger_topic'] or
                                           params['trigger_topic'] == params['reset_topic']):
            raise ValueError('Set a trigger topic distinct from the optional reset topic')

        self._decoder = QrDecoder(try_harder=params['try_harder'],
                                  use_center_crop=params['use_center_crop'],
                                  center_crop_ratio=params['center_crop_ratio'])
        self._confirmation = QrConfirmation(params['confirm_frames'], params['reset_timeout_sec'])
        self._latest: tuple[Image, float] | None = None
        self._last_stamp: int | None = None
        self._require_trigger = params['require_trigger']
        self._capture_window = params['capture_window_sec']
        self._deadline: float | None = None
        self._trigger_stamp = 0
        self._metrics_interval = params['metrics_interval_sec']
        self._next_log = 0.0

        self._status = self.create_publisher(String, params['status_topic'], 10)
        self._snapshot = None
        if params['publish_confirm_snapshot']:
            from PIL import Image as PilImage

            self._pil_image = PilImage
            self._snapshot = self.create_publisher(CompressedImage, params['snapshot_topic'], 10)

        sensor_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                                reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, params['image_topic'], self._on_image, sensor_qos)
        if self._require_trigger:
            self.create_subscription(Bool, params['trigger_topic'], self._on_trigger, 10)
        if params['reset_topic']:
            self.create_subscription(Bool, params['reset_topic'], self._on_reset, 10)
        self.create_timer(1.0 / params['max_process_hz'], self._process_latest)
        self.get_logger().info(
            f"ZXing QR: {params['image_topic']} → {params['status_topic']}; "
            f"{params['confirm_frames']} frames, max {params['max_process_hz']:g} Hz, "
            f"triggered={self._require_trigger}")

    def _reset(self) -> None:
        self._confirmation.reset()
        self._latest = None
        self._last_stamp = None
        self._deadline = None
        self._trigger_stamp = 0

    def _on_reset(self, message: Bool) -> None:
        if message.data:
            self._reset()

    def _on_trigger(self, message: Bool) -> None:
        if message.data:
            self._reset()
            self._deadline = monotonic() + self._capture_window
            self._trigger_stamp = self.get_clock().now().nanoseconds

    @staticmethod
    def _stamp(image: Image) -> int:
        return image.header.stamp.sec * 1_000_000_000 + image.header.stamp.nanosec

    def _on_image(self, image: Image) -> None:
        now = monotonic()
        if self._require_trigger:
            stamp = self._stamp(image)
            if self._deadline is None or now >= self._deadline or not stamp or stamp < self._trigger_stamp:
                return
        self._latest = image, now

    def _process_latest(self) -> None:
        now = monotonic()
        if self._require_trigger and self._deadline is None:
            return
        if self._deadline is not None and now >= self._deadline:
            self._reset()
            return
        self._confirmation.expire(now)
        pending, self._latest = self._latest, None
        if pending is None:
            return
        image, received_at = pending
        if now - received_at >= self._confirmation.reset_timeout_sec:
            return
        stamp = self._stamp(image)
        if stamp and stamp == self._last_stamp:
            return
        self._last_stamp = stamp or None

        started = perf_counter()
        try:
            gray = image_to_gray(image.data, image.width, image.height, image.step, image.encoding)
            decode_started = perf_counter()
            text = self._decoder.decode(gray)
        except (TypeError, ValueError, RuntimeError) as error:
            self._confirmation.observe(None, now)
            self.get_logger().warning(f'QR frame skipped: {error}', throttle_duration_sec=5.0)
            return
        finished = perf_counter()
        now = monotonic()
        if self._deadline is not None and now >= self._deadline:
            self._reset()
            return
        confirmed = self._confirmation.observe(text, now)
        if confirmed or now >= self._next_log:
            self.get_logger().info(
                f'QR {image.width}×{image.height}: decode {(finished - decode_started) * 1000:.1f} ms, '
                f'with grayscale {(finished - started) * 1000:.1f} ms, confirmed={confirmed is not None}')
            self._next_log = now + self._metrics_interval
        if confirmed is None:
            return

        self._status.publish(String(data=confirmed))
        if self._require_trigger:
            self._reset()
        if self._snapshot is not None:
            try:
                # Keep even the optional network evidence within the dashboard preview size.
                preview = self._pil_image.fromarray(gray)
                preview.thumbnail((640, 480))
                with BytesIO() as output:
                    preview.save(output, format='JPEG', quality=85)
                    snapshot = CompressedImage(header=image.header, format='jpeg')
                    snapshot.data.frombytes(output.getvalue())
                    self._snapshot.publish(snapshot)
            except (OSError, ValueError) as error:
                self.get_logger().warning(f'QR confirmed, snapshot failed: {error}')


def main(args=None) -> None:
    rclpy.init(args=args)
    try:
        node = ZxingQrReader()
        try:
            rclpy.spin(node)
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            node.destroy_node()
    finally:
        rclpy.try_shutdown()
