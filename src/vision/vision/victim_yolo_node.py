#!/usr/bin/env python3
"""ROS 2 YOLO victim detector with unaligned D435 3D localization and /vision/observations output."""

from __future__ import annotations

from collections import deque
from math import isfinite
from time import monotonic
from typing import Any

import numpy as np
import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from std_msgs.msg import String

from .core.depth_3d import CameraIntrinsics, Extrinsics, Victim3DFilter
from .core.victim_yolo import (
    CLASS_NAMES,
    VictimObservationPipeline,
    YoloDetector,
    depth_to_array,
    image_to_bgr,
    transform_point,
)

try:
    from tf2_ros import Buffer, TransformException, TransformListener
except ImportError:
    Buffer = None
    TransformListener = None
    TransformException = Exception

try:
    from realsense2_camera_msgs.msg import Extrinsics as RsExtrinsics
except ImportError:
    RsExtrinsics = None


def _stamp_to_sec(stamp: Any) -> float:
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def _intrinsics_from_camera_info(msg: CameraInfo) -> CameraIntrinsics:
    return CameraIntrinsics.from_k(msg.width, msg.height, msg.k, tuple(msg.d))


def select_matching_depth(
    depth_buffer: deque[tuple[Image, float]],
    color_stamp_sec: float,
    max_dt_sec: float,
) -> Image | None:
    """Select the buffered depth frame closest to color_stamp_sec within max_dt_sec."""
    if not depth_buffer or color_stamp_sec <= 0.0:
        return None
    best_msg: Image | None = None
    best_dt = float('inf')
    for msg, stamp_sec in depth_buffer:
        if stamp_sec <= 0.0:
            continue
        dt = abs(stamp_sec - color_stamp_sec)
        if dt <= max_dt_sec and dt < best_dt:
            best_dt = dt
            best_msg = msg
    return best_msg


class VictimYoloNode(Node):
    """Run YOLO + unaligned 3D depth estimation and publish Evacuation observations."""

    def __init__(self, *, detector: YoloDetector | None = None) -> None:
        super().__init__('victim_yolo_node')
        declared = self.declare_parameters('', [
            ('model_path', ''),
            ('backend', 'auto'),
            # An empty YAML sequence does not carry a string-array type in ROS.
            ('class_names', list(CLASS_NAMES.values()), ParameterDescriptor(dynamic_typing=True, read_only=True)),
            ('conf_threshold', 0.6),
            ('min_observation_confidence', 0.6),
            ('iou_threshold', 0.45),
            ('input_size', 640),
            ('max_process_hz', 6.0),
            ('max_depth_sync_dt_sec', 0.08),
            ('depth_scale', 0.001),
            ('confirm_count', 3),
            ('max_spread_m', 0.15),
            ('max_age_sec', 1.0),
            ('jpeg_quality', 80),
            ('snapshot_max_width', 640),
            ('publish_cooldown_sec', 1.0),
            ('tf_timeout_sec', 0.05),
            ('image_reliability', 'best_effort'),
            ('color_topic', '/camera/color/image_raw'),
            ('depth_topic', '/camera/depth/image_rect_raw'),
            ('color_info_topic', '/camera/color/camera_info'),
            ('depth_info_topic', '/camera/depth/camera_info'),
            ('extrinsics_topic', '/camera/extrinsics/depth_to_color'),
            ('attempt_id_topic', '/mission/attempt_id'),
            ('observations_topic', '/vision/observations'),
            ('victim_snapshot_topic', '/vision/victim/image/compressed'),
        ])
        params = {p.name: p.value for p in declared}

        max_hz = float(params['max_process_hz'])
        max_dt = float(params['max_depth_sync_dt_sec'])
        if not isfinite(max_hz) or max_hz <= 0.0:
            raise ValueError('max_process_hz must be finite and positive')
        if not isfinite(max_dt) or max_dt < 0.0:
            raise ValueError('max_depth_sync_dt_sec must be finite and non-negative')

        reliability_name = str(params['image_reliability']).strip().lower()
        reliability_map = {
            'best_effort': ReliabilityPolicy.BEST_EFFORT,
            'reliable': ReliabilityPolicy.RELIABLE,
        }
        if reliability_name not in reliability_map:
            raise ValueError(f"image_reliability must be 'best_effort' or 'reliable', got {params['image_reliability']!r}")

        self._process_period = 1.0 / max_hz
        self._max_depth_sync_dt = max_dt
        self._publish_cooldown = max(0.0, float(params['publish_cooldown_sec']))
        self._tf_timeout = max(0.0, float(params['tf_timeout_sec']))

        min_obs_conf = float(params['min_observation_confidence'])
        detector_conf = float(params['conf_threshold'])
        if detector is None:
            backend = str(params['backend'])
            model_path = str(params['model_path'])
            if backend == 'auto' and not model_path:
                backend = 'mock'
            detector = YoloDetector(
                model_path=model_path,
                backend=backend,
                conf_threshold=detector_conf,
                iou_threshold=float(params['iou_threshold']),
                input_size=int(params['input_size']),
                class_names=params['class_names'],
            )

        victim_filter = Victim3DFilter(
            confirm_count=int(params['confirm_count']),
            max_spread_m=float(params['max_spread_m']),
            max_age_sec=float(params['max_age_sec']),
        )
        self._pipeline = VictimObservationPipeline(
            detector=detector,
            victim_filter=victim_filter,
            min_observation_confidence=min_obs_conf,
            depth_scale=float(params['depth_scale']),
            jpeg_quality=int(params['jpeg_quality']),
            snapshot_max_width=int(params['snapshot_max_width']),
        )

        self._latest_color: Image | None = None
        self._last_color_stamp: float | None = None
        self._depth_buffer: deque[tuple[Image, float]] = deque(maxlen=10)
        self._color_info: CameraIntrinsics | None = None
        self._depth_info: CameraIntrinsics | None = None
        self._extrinsics: Extrinsics | None = None
        self._attempt_id: str = ''
        self._next_process_at: float = 0.0
        self._last_publish_at: float = -1e9
        self._last_publish_attempt: str = ''

        self._tf_buffer = Buffer(node=self) if Buffer is not None else None
        self._tf_listener = (
            # Receive TF while the inference callback waits for the image-time transform.
            TransformListener(self._tf_buffer, None, spin_thread=True)
            if (self._tf_buffer is not None and TransformListener is not None)
            else None
        )

        self._obs_pub = self.create_publisher(String, str(params['observations_topic']), 10)
        self._snap_pub = self.create_publisher(CompressedImage, str(params['victim_snapshot_topic']), 10)

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=reliability_map[reliability_name],
        )
        self.create_subscription(Image, str(params['color_topic']), self._on_color, sensor_qos)
        self.create_subscription(Image, str(params['depth_topic']), self._on_depth, sensor_qos)
        self.create_subscription(CameraInfo, str(params['color_info_topic']), self._on_color_info, sensor_qos)
        self.create_subscription(CameraInfo, str(params['depth_info_topic']), self._on_depth_info, sensor_qos)
        self.create_subscription(String, str(params['attempt_id_topic']), self._on_attempt_id, 10)
        if RsExtrinsics is not None and str(params['extrinsics_topic']).strip():
            ext_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.create_subscription(
                RsExtrinsics, str(params['extrinsics_topic']), self._on_extrinsics, ext_qos
            )

        self.create_timer(self._process_period, self._process_latest)
        self.get_logger().info(
            f"Victim YOLO ({detector.backend}) ready: {params['color_topic']} + {params['depth_topic']} "
            f"-> {params['observations_topic']} & {params['victim_snapshot_topic']} (max {max_hz:g} Hz)"
        )

    def _on_attempt_id(self, msg: String) -> None:
        new_id = msg.data.strip()
        if new_id != self._attempt_id:
            self._attempt_id = new_id
            self._pipeline.victim_filter.reset()
            self._last_publish_at = -1e9

    def _on_color_info(self, msg: CameraInfo) -> None:
        try:
            self._color_info = _intrinsics_from_camera_info(msg)
        except ValueError as exc:
            self.get_logger().warning(f'Invalid color CameraInfo skipped: {exc}', throttle_duration_sec=5.0)

    def _on_depth_info(self, msg: CameraInfo) -> None:
        try:
            self._depth_info = _intrinsics_from_camera_info(msg)
        except ValueError as exc:
            self.get_logger().warning(f'Invalid depth CameraInfo skipped: {exc}', throttle_duration_sec=5.0)

    def _on_extrinsics(self, msg: Any) -> None:
        try:
            self._extrinsics = Extrinsics.from_realsense(msg.rotation, msg.translation)
        except ValueError as exc:
            self.get_logger().warning(f'Invalid D435 extrinsics skipped: {exc}', throttle_duration_sec=5.0)

    def _on_depth(self, msg: Image) -> None:
        self._depth_buffer.append((msg, _stamp_to_sec(msg.header.stamp)))

    def _on_color(self, msg: Image) -> None:
        self._latest_color = msg
        if monotonic() >= self._next_process_at:
            self._process_latest()

    def _resolve_extrinsics(self, color_frame: str, depth_frame: str, stamp: Any) -> Extrinsics | None:
        if not color_frame or not depth_frame:
            return None
        if color_frame == depth_frame:
            return Extrinsics.identity()
        if self._extrinsics is not None:
            return self._extrinsics
        if self._tf_buffer is None:
            return None
        try:
            stamped_tf = self._tf_buffer.lookup_transform(
                color_frame,
                depth_frame,
                Time.from_msg(stamp),
                timeout=Duration(seconds=self._tf_timeout),
            )
            if stamped_tf is None:
                return None
            tf = stamped_tf.transform
            q = tf.rotation
            # Build R from XYZW quaternion by transforming basis vectors
            r_cols = [
                transform_point(axis, (0.0, 0.0, 0.0), (q.x, q.y, q.z, q.w))
                for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            ]
            rot = np.column_stack(r_cols)
            trans = np.array([tf.translation.x, tf.translation.y, tf.translation.z], dtype=np.float64)
            return Extrinsics(rotation=rot, translation=trans)
        except (TransformException, ValueError) as exc:
            self.get_logger().warning(f'Depth-to-color TF unavailable: {exc}', throttle_duration_sec=2.0)
            return None

    def _lookup_map_position(
        self,
        optical_xyz: tuple[float, float, float],
        color_frame: str,
        stamp: Any,
    ) -> tuple[float, float, float] | None:
        if self._tf_buffer is None:
            self.get_logger().warning('TF2 buffer unavailable; cannot transform victim pose to map', throttle_duration_sec=5.0)
            return None
        if not color_frame:
            self.get_logger().warning('Color image header.frame_id is empty; skipping TF transform', throttle_duration_sec=5.0)
            return None
        try:
            stamped_tf = self._tf_buffer.lookup_transform(
                'map',
                color_frame,
                Time.from_msg(stamp),
                timeout=Duration(seconds=self._tf_timeout),
            )
            if stamped_tf is None:
                return None
            tf = stamped_tf.transform
            t = tf.translation
            q = tf.rotation
            return transform_point(optical_xyz, (t.x, t.y, t.z), (q.x, q.y, q.z, q.w))
        except (TransformException, ValueError) as exc:
            self.get_logger().warning(
                f"TF lookup 'map' <- '{color_frame}' unavailable: {exc}",
                throttle_duration_sec=2.0,
            )
            return None

    def _process_latest(self) -> None:
        now = monotonic()
        if now < self._next_process_at or self._latest_color is None:
            return

        color_msg = self._latest_color
        self._latest_color = None
        stamp_sec = _stamp_to_sec(color_msg.header.stamp)
        if stamp_sec > 0.0 and self._last_color_stamp is not None and stamp_sec == self._last_color_stamp:
            return
        self._last_color_stamp = stamp_sec
        self._next_process_at = now + self._process_period

        if self._color_info is None:
            self.get_logger().warning('Waiting for color CameraInfo...', throttle_duration_sec=5.0)
            return

        try:
            bgr = image_to_bgr(
                color_msg.data, color_msg.width, color_msg.height, color_msg.step, color_msg.encoding
            )
        except ValueError as exc:
            self.get_logger().warning(f'Color frame skipped: {exc}', throttle_duration_sec=5.0)
            return

        depth_msg = select_matching_depth(self._depth_buffer, stamp_sec, self._max_depth_sync_dt)
        depth_arr: np.ndarray | None = None
        extrinsics: Extrinsics | None = None
        if depth_msg is not None and self._depth_info is not None:
            extrinsics = self._resolve_extrinsics(
                color_msg.header.frame_id, depth_msg.header.frame_id, color_msg.header.stamp
            )
            if extrinsics is None:
                return
            try:
                depth_arr = depth_to_array(
                    depth_msg.data,
                    depth_msg.width,
                    depth_msg.height,
                    depth_msg.step,
                    depth_msg.encoding,
                    depth_msg.is_bigendian,
                )
            except ValueError as exc:
                self.get_logger().warning(f'Depth frame skipped: {exc}', throttle_duration_sec=5.0)

        if depth_msg is None or depth_arr is None or self._depth_info is None or extrinsics is None:
            self.get_logger().debug('No synchronized depth/intrinsics/extrinsics for current color frame')

        result = self._pipeline.process_frame(
            bgr,
            depth_arr,
            self._color_info,
            self._depth_info,
            extrinsics,
            stamp_sec=stamp_sec,
            monotonic_sec=now,
            point_transformer=lambda xyz: self._lookup_map_position(
                xyz, color_msg.header.frame_id, color_msg.header.stamp
            ),
        )

        map_xyz = result.confirmed_map_xyz
        if map_xyz is None or result.best_victim is None:
            return

        if (
            self._attempt_id == self._last_publish_attempt
            and (now - self._last_publish_at) < self._publish_cooldown
        ):
            return

        try:
            outputs = self._pipeline.build_outputs(bgr, result, attempt_id=self._attempt_id)
        except ValueError as exc:
            self.get_logger().warning(f'Victim evidence skipped: {exc}', throttle_duration_sec=5.0)
            return

        snapshot = CompressedImage()
        snapshot.header = color_msg.header
        snapshot.format = 'jpeg'
        snapshot.data.frombytes(outputs.jpeg_bytes)
        self._snap_pub.publish(snapshot)

        if outputs.observation_json is not None:
            self._obs_pub.publish(String(data=outputs.observation_json))
            self.get_logger().info(
                f'CONFIRMED victim map=({map_xyz[0]:.2f}, {map_xyz[1]:.2f}, {map_xyz[2]:.2f}) '
                f'conf={result.best_victim.confidence:.2f} attempt={self._attempt_id}'
            )
        else:
            self.get_logger().warning(
                'CONFIRMED victim in map, but /mission/attempt_id is empty: skipped /vision/observations',
                throttle_duration_sec=5.0,
            )

        self._last_publish_at = now
        self._last_publish_attempt = self._attempt_id


def main(args: Any = None) -> None:
    rclpy.init(args=args)
    try:
        node = VictimYoloNode()
        try:
            rclpy.spin(node)
        except (KeyboardInterrupt, ExternalShutdownException):
            pass
        finally:
            node.destroy_node()
    finally:
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
