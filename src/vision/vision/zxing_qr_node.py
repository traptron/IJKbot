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
            ('image_reliability', 'best_effort'),
            ('status_topic', '/victim_status'),
            ('confirm_frames', 2),
            ('reset_timeout_sec', 1.2),
            ('max_process_hz', 8.0),
            ('trigger_process_hz', 30.0),
            ('try_harder', False),
            ('use_center_crop', False),
            ('center_crop_ratio', 0.7),
            ('publish_confirm_snapshot', False),
            ('snapshot_topic', '/vision/qr/image/compressed'),
            ('require_trigger', False),
            ('trigger_topic', '/vision/take_photo'),
            ('reset_topic', ''),
            ('capture_window_sec', 1.4),
            ('trigger_stamp_tolerance_sec', 0.1),
            ('metrics_interval_sec', 5.0),
        ])
        params = {parameter.name: parameter.value for parameter in declared}
        for name in ('max_process_hz', 'trigger_process_hz', 'capture_window_sec', 'metrics_interval_sec'):
            if not isfinite(params[name]) or params[name] <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not isfinite(params['trigger_stamp_tolerance_sec']) or params['trigger_stamp_tolerance_sec'] < 0:
            raise ValueError('trigger_stamp_tolerance_sec must be finite and non-negative')
        if params['require_trigger'] and (not params['trigger_topic'] or
                                           params['trigger_topic'] == params['reset_topic']):
            raise ValueError('Set a trigger topic distinct from the optional reset topic')
        reliability_name = str(params['image_reliability']).strip().lower()
        reliability_map = {
            'best_effort': ReliabilityPolicy.BEST_EFFORT,
            'reliable': ReliabilityPolicy.RELIABLE,
        }
        if reliability_name not in reliability_map:
            raise ValueError(f"image_reliability must be 'best_effort' or 'reliable', got {params['image_reliability']!r}")

        self._decoder = QrDecoder(try_harder=params['try_harder'],
                                  use_center_crop=params['use_center_crop'],
                                  center_crop_ratio=params['center_crop_ratio'])
        self._confirmation = QrConfirmation(
            params['confirm_frames'],
            params['reset_timeout_sec'],
            reset_on_miss=not params['require_trigger'],
        )
        self._latest: tuple[Image, float] | None = None
        self._last_stamp: int | None = None
        self._require_trigger = params['require_trigger']
        self._capture_window = params['capture_window_sec']
        self._trigger_stamp_tolerance_ns = round(params['trigger_stamp_tolerance_sec'] * 1_000_000_000)
        self._deadline: float | None = None
        self._trigger_stamp = 0
        self._trigger_seq = 0
        self._trigger_at: float | None = None
        self._fresh_arrivals = 0
        self._stale_frames = 0
        self._last_stale_dt_ms: float | None = None
        self._decoded_frames = 0
        self._decode_hits = 0
        self._decode_misses = 0
        self._cooldown_waits = 0
        self._prev_fresh_at: float | None = None
        self._metrics_interval = params['metrics_interval_sec']
        self._next_log = 0.0
        process_hz = params['trigger_process_hz'] if self._require_trigger else params['max_process_hz']
        self._process_hz = process_hz
        self._process_period = 1.0 / process_hz
        self._next_process_at = 0.0

        self._status = self.create_publisher(String, params['status_topic'], 10)
        self._snapshot = None
        if params['publish_confirm_snapshot']:
            from PIL import Image as PilImage

            self._pil_image = PilImage
            self._snapshot = self.create_publisher(CompressedImage, params['snapshot_topic'], 10)

        sensor_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                                reliability=reliability_map[reliability_name])
        self.create_subscription(Image, params['image_topic'], self._on_image, sensor_qos)
        if self._require_trigger:
            self.create_subscription(Bool, params['trigger_topic'], self._on_trigger, 10)
        if params['reset_topic']:
            self.create_subscription(Bool, params['reset_topic'], self._on_reset, 10)
        self.create_timer(self._process_period, self._process_latest)
        self.get_logger().info(
            f"ZXing QR: {params['image_topic']} ({reliability_name}) → {params['status_topic']}; "
            f"{params['confirm_frames']} frames, max {process_hz:g} Hz, "
            f"triggered={self._require_trigger}")

    def _reset(self) -> None:
        self._confirmation.reset()
        self._latest = None
        self._last_stamp = None
        self._deadline = None
        self._trigger_stamp = 0
        self._trigger_at = None
        self._fresh_arrivals = 0
        self._stale_frames = 0
        self._last_stale_dt_ms = None
        self._decoded_frames = 0
        self._decode_hits = 0
        self._decode_misses = 0
        self._cooldown_waits = 0
        self._prev_fresh_at = None

    def _stale_summary(self) -> str:
        if self._stale_frames == 0:
            return 'stale_frames=0'
        if self._last_stale_dt_ms is not None:
            return f'stale_frames={self._stale_frames}, last_stale_dt={self._last_stale_dt_ms:+.1f} ms'
        return f'stale_frames={self._stale_frames}, last_stale_dt=unstamped'

    def _timeout_reason(self) -> str:
        if self._fresh_arrivals == 0:
            if self._stale_frames > 0:
                return 'no fresh frames (only stale/pre-trigger frames arrived)'
            return 'no fresh frames arrived'
        if self._fresh_arrivals == 1:
            if self._decoded_frames == 0:
                return 'only 1 fresh frame arrived (not decoded before window expired)'
            return 'only 1 fresh frame arrived'
        if self._decoded_frames < 2:
            return 'fewer than 2 frames decoded before window expired'
        if self._decode_hits == 0:
            return 'no QR decoded in fresh frames'
        if self._decode_hits == 1:
            return 'only 1 readable QR frame (need 2 consecutive)'
        return 'no 2 identical QR reads before window expired'

    def _expire_window(self, now: float) -> None:
        elapsed_ms = (now - self._trigger_at) * 1000.0 if self._trigger_at is not None else 0.0
        self.get_logger().warning(
            f'QR trigger #{self._trigger_seq} timeout after {elapsed_ms:.1f} ms: '
            f'{self._timeout_reason()} '
            f'(fresh={self._fresh_arrivals}, decoded={self._decoded_frames}, '
            f'hits={self._decode_hits}, misses={self._decode_misses}, '
            f'{self._stale_summary()}, cooldown_waits={self._cooldown_waits})'
        )
        self._reset()

    def _on_reset(self, message: Bool) -> None:
        if message.data:
            self._reset()

    def _on_trigger(self, message: Bool) -> None:
        if not message.data:
            return
        now = monotonic()
        if self._deadline is not None:
            elapsed_ms = (now - self._trigger_at) * 1000.0 if self._trigger_at is not None else 0.0
            self.get_logger().warning(
                f'QR trigger #{self._trigger_seq} superseded after {elapsed_ms:.1f} ms '
                f'(fresh={self._fresh_arrivals}, decoded={self._decoded_frames}, '
                f'hits={self._decode_hits}, {self._stale_summary()})'
            )
        self._reset()
        self._trigger_seq += 1
        self._trigger_at = now
        self._deadline = now + self._capture_window
        self._trigger_stamp = self.get_clock().now().nanoseconds
        self.get_logger().info(
            f'QR trigger #{self._trigger_seq}: start '
            f'(window={self._capture_window:.2f}s, process_hz={self._process_hz:g}, '
            f'tolerance={self._trigger_stamp_tolerance_ns / 1_000_000:.0f}ms, '
            f'stamp={self._trigger_stamp})'
        )

    @staticmethod
    def _stamp(image: Image) -> int:
        return image.header.stamp.sec * 1_000_000_000 + image.header.stamp.nanosec

    def _on_image(self, image: Image) -> None:
        now = monotonic()
        if self._require_trigger:
            if self._deadline is None:
                return
            if now >= self._deadline:
                self._expire_window(now)
                return
            stamp = self._stamp(image)
            min_stamp = self._trigger_stamp - self._trigger_stamp_tolerance_ns
            if not stamp or stamp < min_stamp:
                self._stale_frames += 1
                self._last_stale_dt_ms = (
                    (stamp - self._trigger_stamp) / 1_000_000.0 if stamp else None
                )
                return
            self._fresh_arrivals += 1
            dt_trig_ms = (now - self._trigger_at) * 1000.0 if self._trigger_at is not None else 0.0
            stamp_ms = (stamp - self._trigger_stamp) / 1_000_000.0
            if self._fresh_arrivals == 1:
                self.get_logger().info(
                    f'QR trigger #{self._trigger_seq}: 1st fresh frame at +{dt_trig_ms:.1f} ms '
                    f'(stamp {stamp_ms:+.1f} ms, {self._stale_summary()}, '
                    f'{image.width}×{image.height})'
                )
            elif self._fresh_arrivals == 2:
                dt_prev_ms = (now - self._prev_fresh_at) * 1000.0 if self._prev_fresh_at is not None else 0.0
                self.get_logger().info(
                    f'QR trigger #{self._trigger_seq}: 2nd fresh frame at +{dt_trig_ms:.1f} ms '
                    f'(+{dt_prev_ms:.1f} ms from 1st, stamp {stamp_ms:+.1f} ms)'
                )
            self._prev_fresh_at = now
            if now < self._next_process_at:
                self._cooldown_waits += 1
        self._latest = image, now
        # Use the first fresh frame immediately when the rate limit allows it.
        # The timer still handles a pending frame if arrivals stop during cooldown.
        if now >= self._next_process_at:
            self._process_latest()

    def _process_latest(self) -> None:
        now = monotonic()
        if self._require_trigger and self._deadline is None:
            return
        if self._deadline is not None and now >= self._deadline:
            self._expire_window(now)
            return
        self._confirmation.expire(now)
        if now < self._next_process_at:
            return
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
        self._next_process_at = now + self._process_period

        started = perf_counter()
        try:
            text = self._decoder.decode_image(
                image.data, image.width, image.height, image.step, image.encoding)
        except (TypeError, ValueError, RuntimeError) as error:
            self._confirmation.observe(None, now)
            if self._trigger_at is not None:
                self._decoded_frames += 1
                self._decode_misses += 1
            self.get_logger().warning(f'QR frame skipped: {error}', throttle_duration_sec=5.0)
            return
        finished = perf_counter()
        now = monotonic()
        decode_ms = (finished - started) * 1000.0
        has_hit = text is not None and bool(text.strip())
        if self._trigger_at is not None:
            self._decoded_frames += 1
            if has_hit:
                self._decode_hits += 1
            else:
                self._decode_misses += 1
            if self._decoded_frames <= 2 or has_hit:
                at_ms = (now - self._trigger_at) * 1000.0
                self.get_logger().info(
                    f'QR trigger #{self._trigger_seq} frame #{self._decoded_frames} '
                    f'({image.width}×{image.height}): hit={has_hit} at +{at_ms:.1f} ms '
                    f'(decode {decode_ms:.1f} ms)'
                )
        if self._deadline is not None and now >= self._deadline:
            self._expire_window(now)
            return
        confirmed = self._confirmation.observe(text, now)
        if not self._require_trigger and (confirmed or now >= self._next_log):
            self.get_logger().info(
                f'QR {image.width}×{image.height}: decode {decode_ms:.1f} ms, '
                f'confirmed={confirmed is not None}')
            self._next_log = now + self._metrics_interval
        if confirmed is None:
            return

        self._status.publish(String(data=confirmed))
        if self._trigger_at is not None:
            pub_ms = (now - self._trigger_at) * 1000.0
            self.get_logger().info(
                f'QR trigger #{self._trigger_seq}: confirmed & published at +{pub_ms:.1f} ms '
                f'(fresh={self._fresh_arrivals}, decoded={self._decoded_frames}, '
                f'len={len(confirmed)}, snapshot={self._snapshot is not None}, '
                f'{self._stale_summary()})'
            )
        if self._require_trigger:
            self._reset()
        if self._snapshot is not None:
            try:
                # Keep even the optional network evidence within the dashboard preview size.
                gray = image_to_gray(
                    image.data, image.width, image.height, image.step, image.encoding)
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
