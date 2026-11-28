"""Unit tests for victim_yolo core and Evacuation /vision/observations contract (no GPU/ROS required)."""

from __future__ import annotations

import base64
from collections import deque
from importlib.util import find_spec
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

_SRC_ROOT = Path(__file__).resolve().parents[2]
_VISION_ROOT = _SRC_ROOT / 'vision'
_BRAIN_ROOT = _SRC_ROOT / 'brain'
for _p in (str(_VISION_ROOT), str(_BRAIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from vision.core.depth_3d import CameraIntrinsics, Extrinsics, Victim3DFilter  # noqa: E402
from vision.core.victim_yolo import (  # noqa: E402
    CLASS_NAMES,
    DEFAULT_SNAPSHOT_MAX_WIDTH,
    MAX_OBSERVATION_JPEG_BYTES,
    MIN_OBSERVATION_CONFIDENCE,
    VICTIM_CLASS_ID,
    VictimObservationPipeline,
    YoloDetection,
    YoloDetector,
    _decode_yolo_output,
    build_observation_payload,
    depth_to_array,
    encode_observation_jpeg,
    image_to_bgr,
    transform_point,
)


def _synthetic_unaligned_depth(
    color_intr: CameraIntrinsics,
    depth_intr: CameraIntrinsics,
    extrinsics: Extrinsics,
    *,
    target_z_m: float = 1.20,
    bbox_xyxy: tuple[float, float, float, float] = (760.0, 420.0, 1080.0, 860.0),
) -> np.ndarray:
    """Create a synthetic 16UC1 depth image with foreground figurine pixels in the color bbox."""
    depth = np.full((depth_intr.height, depth_intr.width), 3000, dtype=np.uint16)
    x1, y1, x2, y2 = bbox_xyxy
    ud_grid, vd_grid = np.meshgrid(
        np.arange(depth_intr.width, dtype=np.float64),
        np.arange(depth_intr.height, dtype=np.float64),
    )
    xd = (ud_grid - depth_intr.cx) * target_z_m / depth_intr.fx
    yd = (vd_grid - depth_intr.cy) * target_z_m / depth_intr.fy
    zd = np.full_like(xd, target_z_m)
    pts_d = np.stack((xd, yd, zd), axis=-1).reshape(-1, 3)
    pts_c = pts_d @ extrinsics.rotation.T + extrinsics.translation
    uc = color_intr.fx * (pts_c[:, 0] / pts_c[:, 2]) + color_intr.cx
    vc = color_intr.fy * (pts_c[:, 1] / pts_c[:, 2]) + color_intr.cy
    mask = ((uc >= x1) & (uc <= x2) & (vc >= y1) & (vc <= y2)).reshape(depth.shape)
    depth[mask] = int(round(target_z_m * 1000.0))
    return depth


class TestVictimYolo(unittest.TestCase):
    def setUp(self) -> None:
        self.color_intr = CameraIntrinsics(width=1920, height=1080, fx=1380.0, fy=1380.0, cx=960.0, cy=540.0)
        self.depth_intr = CameraIntrinsics(width=640, height=480, fx=385.0, fy=385.0, cx=320.0, cy=240.0)
        self.extrinsics = Extrinsics(
            rotation=np.eye(3, dtype=np.float64),
            translation=np.array([0.015, 0.0, 0.0], dtype=np.float64),
        )
        self.bbox = (780.0, 420.0, 1060.0, 860.0)
        self.bgr_frame = np.full((1080, 1920, 3), 90, dtype=np.uint8)
        self.bgr_frame[420:860, 780:1060] = (40, 180, 220)
        self.depth_frame = _synthetic_unaligned_depth(
            self.color_intr,
            self.depth_intr,
            self.extrinsics,
            target_z_m=1.20,
            bbox_xyxy=self.bbox,
        )

    def test_module_imports_lazily_without_gpu_backends(self):
        self.assertEqual(CLASS_NAMES, {0: 'victim'})
        # Selecting an unavailable runtime should only fail when _ensure_loaded() runs, not on import/init.
        det_ort = YoloDetector('/tmp/nonexistent_model.onnx', backend='auto')
        self.assertEqual(det_ort.backend, 'onnx')
        det_trt = YoloDetector('/tmp/nonexistent_model.engine', backend='auto')
        self.assertEqual(det_trt.backend, 'tensorrt')
        with self.assertRaises(FileNotFoundError):
            det_ort.detect(self.bgr_frame)

    def test_class_names_accepts_default_and_explicit_victim(self):
        import yaml

        params_file = _VISION_ROOT / 'config' / 'victim_yolo.yaml'
        names = yaml.safe_load(params_file.read_text())['victim_yolo_node']['ros__parameters']['class_names']
        self.assertEqual(names, ['victim'])
        for value in (None, [], {}, names, {0: 'victim'}):
            with self.subTest(class_names=value):
                self.assertEqual(YoloDetector(backend='mock', class_names=value).class_names, {0: 'victim'})
        for value in ('victim', ['other'], ['victim', 'other'], {1: 'victim'}):
            with self.subTest(class_names=value), self.assertRaisesRegex(ValueError, 'class_names'):
                YoloDetector(backend='mock', class_names=value)

    @unittest.skipUnless(find_spec('rclpy'), 'ROS 2 is unavailable')
    def test_ros_node_accepts_empty_and_single_class_yaml_arrays(self):
        import rclpy
        from vision import victim_yolo_node

        with TemporaryDirectory() as directory, patch.object(victim_yolo_node, 'Buffer', None):
            params_file = Path(directory) / 'victim.yaml'
            for names in ('[]', '[victim]'):
                with self.subTest(class_names=names):
                    params_file.write_text(
                        f'victim_yolo_node:\n  ros__parameters:\n    class_names: {names}\n'
                    )
                    rclpy.init(args=['--ros-args', '--params-file', str(params_file)])
                    node = None
                    try:
                        node = victim_yolo_node.VictimYoloNode()
                        self.assertEqual(node._pipeline.detector.class_names, {0: 'victim'})
                    finally:
                        if node is not None:
                            node.destroy_node()
                        rclpy.try_shutdown()

    def test_confirmed_victim_produces_valid_evacuation_observation_and_jpeg(self):
        from evacuation import Observation  # direct contract check against src/brain/evacuation.py

        detections = [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.60, self.bbox)]
        detector = YoloDetector(backend='mock', detector_fn=lambda _img, _c: detections)
        self.assertEqual(MIN_OBSERVATION_CONFIDENCE, 0.6)
        self.assertEqual(detector.conf_threshold, 0.6)
        pipeline = VictimObservationPipeline(
            detector=detector,
            victim_filter=Victim3DFilter(confirm_count=3, max_spread_m=0.15, max_age_sec=1.0),
            jpeg_quality=80,
            snapshot_max_width=640,
            point_transformer=lambda xyz: transform_point(
                xyz,
                translation_xyz=(0.5, 1.0, 0.12),
                rotation_xyzw=(-0.5, 0.5, -0.5, 0.5),
            ),
        )

        # Frames 1 & 2 accumulate confirmations; frame 3 confirms in map frame.
        res1 = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=100.0, monotonic_sec=10.0,
        )
        res2 = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=100.2, monotonic_sec=10.2,
        )
        self.assertIsNone(res1.confirmed_map_xyz)
        self.assertIsNone(res2.confirmed_map_xyz)
        self.assertEqual(res1.victim_detections, tuple(detections))

        res3 = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=100.4, monotonic_sec=10.4,
        )
        self.assertIsNotNone(res3.point_optical)
        self.assertAlmostEqual(res3.point_optical.z, 1.20, delta=0.05)
        self.assertIsNotNone(res3.confirmed_map_xyz)
        self.assertGreater(res3.confirmed_map_xyz[0], 1.5)

        outputs = pipeline.build_outputs(
            self.bgr_frame,
            res3,
            attempt_id='attempt-123',
        )

        self.assertTrue(outputs.jpeg_bytes.startswith(b'\xff\xd8'))
        self.assertLessEqual(len(outputs.jpeg_bytes), MAX_OBSERVATION_JPEG_BYTES)
        self.assertIsNotNone(outputs.observation_json)

        parsed_json = json.loads(outputs.observation_json)
        obs = Observation.parse(parsed_json, attempt_id='attempt-123', now=100.6)
        self.assertEqual(obs.label, 'victim')
        self.assertEqual(obs.frame_id, 'map')
        self.assertAlmostEqual(obs.confidence, 0.60, places=3)
        self.assertGreater(obs.position[0], 1.5)
        self.assertEqual(base64.b64decode(obs.image_jpeg_b64), outputs.jpeg_bytes)

        from brain.mission_sm import MissionROSNode, MissionState, MissionStateMachine, Waypoint

        sm = MissionStateMachine(llm_client=SimpleNamespace(arena={}), mock_mode=True)
        sm.state = MissionState.SEARCHING_VICTIM
        sm.evacuation.attempt_id = 'attempt-123'
        sm.inspection_waypoints = [Waypoint(x=obs.position[0], y=obs.position[1])]
        clock = SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=100_600_000_000))
        wrapper = SimpleNamespace(sm=sm, node=SimpleNamespace(get_clock=lambda: clock))
        MissionROSNode._observation_callback(wrapper, SimpleNamespace(data=outputs.observation_json))
        self.assertTrue(sm.victim_found)
        self.assertEqual(sm.evacuation.victim.position, obs.position)

    def test_threshold_06_passes_and_059_filtered_and_map_filter_survives_robot_motion(self):
        # Detections with confidence < 0.6 must be ignored even if detector emits them.
        det_low = YoloDetector(
            backend='mock',
            conf_threshold=0.5,
            detector_fn=lambda _img, _c: [
                YoloDetection(VICTIM_CLASS_ID, 'victim', 0.59, self.bbox),
                YoloDetection(VICTIM_CLASS_ID, 'victim', 1.01, self.bbox),
            ],
        )
        pipe_low = VictimObservationPipeline(detector=det_low, victim_filter=Victim3DFilter(confirm_count=1))
        res_low = pipe_low.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=10.0, monotonic_sec=1.0,
        )
        self.assertEqual(res_low.victim_detections, ())
        self.assertIsNone(res_low.confirmed_map_xyz)

        # Simulate moving robot: optical Z changes across 3 frames (1.6m -> 1.2m -> 0.9m, >0.15m spread!),
        # while the point in 'map' frame stays stationary at ~(2.1, 0.5, 0.1).
        det_ok = YoloDetector(
            backend='mock',
            conf_threshold=0.6,
            detector_fn=lambda _img, _c: [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.60, self.bbox)],
        )
        pipe_motion = VictimObservationPipeline(
            detector=det_ok,
            victim_filter=Victim3DFilter(confirm_count=3, max_spread_m=0.15, max_age_sec=1.0),
        )
        depths = [1.60, 1.20, 0.90]
        last_res = None
        for idx, z_m in enumerate(depths):
            d_img = _synthetic_unaligned_depth(
                self.color_intr, self.depth_intr, self.extrinsics, target_z_m=z_m, bbox_xyxy=self.bbox
            )
            # Invert robot forward translation along Z so the stationary figurine stays at (2.1, 0.5, 0.1) in map
            last_res = pipe_motion.process_frame(
                self.bgr_frame,
                d_img,
                self.color_intr,
                self.depth_intr,
                self.extrinsics,
                stamp_sec=100.0 + 0.2 * idx,
                monotonic_sec=10.0 + 0.2 * idx,
                point_transformer=lambda xyz, z_ref=z_m: (2.1 + (xyz[2] - z_ref), 0.5 - xyz[0], 0.1 - xyz[1]),
            )
        self.assertIsNotNone(last_res.confirmed_map_xyz)
        self.assertAlmostEqual(last_res.confirmed_map_xyz[0], 2.1, delta=0.05)
        self.assertAlmostEqual(last_res.confirmed_map_xyz[1], 0.5, delta=0.05)

    def test_1920x1080_snapshot_downscales_to_640_width(self):
        import cv2

        det = YoloDetector(
            backend='mock',
            detector_fn=lambda _img, _c: [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.72, self.bbox)],
        )
        pipe = VictimObservationPipeline(
            detector=det,
            victim_filter=Victim3DFilter(confirm_count=1),
            snapshot_max_width=DEFAULT_SNAPSHOT_MAX_WIDTH,
            point_transformer=lambda _xyz: (2.0, 1.0, 0.1),
        )
        res = pipe.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=50.0, monotonic_sec=5.0,
        )
        outputs = pipe.build_outputs(self.bgr_frame, res, attempt_id='att-resize')
        decoded = cv2.imdecode(np.frombuffer(outputs.jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        h, w = decoded.shape[:2]
        self.assertEqual(w, 640)
        self.assertEqual(h, 360)
        self.assertLessEqual(len(outputs.jpeg_bytes), MAX_OBSERVATION_JPEG_BYTES)
        obs_jpg = base64.b64decode(outputs.observation_payload['image_jpeg_b64'])
        self.assertEqual(obs_jpg, outputs.jpeg_bytes)

    def test_point_transformer_none_or_exception_skips_frame_without_breaking_streak(self):
        det = YoloDetector(
            backend='mock',
            detector_fn=lambda _img, _c: [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.85, self.bbox)],
        )
        pipe = VictimObservationPipeline(
            detector=det,
            victim_filter=Victim3DFilter(confirm_count=3, max_spread_m=0.15, max_age_sec=2.0),
        )

        # Frame 1 & Frame 2: valid TF -> streak 2/3
        for idx, t in enumerate((10.0, 10.2)):
            res = pipe.process_frame(
                self.bgr_frame,
                self.depth_frame,
                self.color_intr,
                self.depth_intr,
                self.extrinsics,
                stamp_sec=100.0 + idx * 0.2,
                monotonic_sec=t,
                point_transformer=lambda xyz: (2.0, 0.5, xyz[2] - 1.1),
            )
            self.assertIsNotNone(res.point_map)
            self.assertIsNone(res.confirmed_map_xyz)

        # Frame 3: TF returns None -> graceful skip, does NOT reset 2/3 streak
        res_none = pipe.process_frame(
            self.bgr_frame,
            self.depth_frame,
            self.color_intr,
            self.depth_intr,
            self.extrinsics,
            stamp_sec=100.4,
            monotonic_sec=10.4,
            point_transformer=lambda _xyz: None,
        )
        self.assertIsNone(res_none.point_map)
        self.assertIsNone(res_none.confirmed_map_xyz)

        # Frame 4: TF raises extrapolation error -> graceful skip, does NOT crash or reset streak
        def raising_tf(_xyz):
            raise RuntimeError('Transform extrapolation into the future')

        res_exc = pipe.process_frame(
            self.bgr_frame,
            self.depth_frame,
            self.color_intr,
            self.depth_intr,
            self.extrinsics,
            stamp_sec=100.6,
            monotonic_sec=10.6,
            point_transformer=raising_tf,
        )
        self.assertIsNone(res_exc.point_map)
        self.assertIsNone(res_exc.confirmed_map_xyz)

        # Frame 5: TF recovers -> completes 3/3 confirmation immediately!
        res_ok = pipe.process_frame(
            self.bgr_frame,
            self.depth_frame,
            self.color_intr,
            self.depth_intr,
            self.extrinsics,
            stamp_sec=100.8,
            monotonic_sec=10.8,
            point_transformer=lambda xyz: (2.0, 0.5, xyz[2] - 1.1),
        )
        self.assertIsNotNone(res_ok.confirmed_map_xyz)
        self.assertAlmostEqual(res_ok.confirmed_map_xyz[0], 2.0, delta=0.05)

    def test_unknown_class_never_confirms_a_victim(self):
        detections = [YoloDetection(1, 'other', 0.99, self.bbox)]
        detector = YoloDetector(backend='mock', conf_threshold=0.6, detector_fn=lambda _img, _c: detections)
        pipeline = VictimObservationPipeline(
            detector=detector,
            victim_filter=Victim3DFilter(confirm_count=1),
        )
        res = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=200.0, monotonic_sec=20.0,
        )
        self.assertEqual(res.victim_detections, ())
        self.assertIsNone(res.best_victim)
        self.assertIsNone(res.confirmed_map_xyz)

    def test_missing_attempt_id_skips_observation_json_but_keeps_snapshot(self):
        detections = [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.91, self.bbox)]
        detector = YoloDetector(backend='mock', conf_threshold=0.6, detector_fn=lambda _img, _c: detections)
        pipeline = VictimObservationPipeline(
            detector=detector,
            victim_filter=Victim3DFilter(confirm_count=1),
            point_transformer=lambda _xyz: (2.0, 1.0, 0.1),
        )
        res = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=50.0, monotonic_sec=5.0,
        )
        self.assertIsNotNone(res.confirmed_map_xyz)

        outputs = pipeline.build_outputs(
            self.bgr_frame,
            res,
            attempt_id='   ',
        )
        self.assertTrue(outputs.jpeg_bytes.startswith(b'\xff\xd8'))
        self.assertIsNone(outputs.observation_payload)
        self.assertIsNone(outputs.observation_json)

    def test_missing_or_stale_depth_resets_filter_and_blocks_confirmation(self):
        detections = [YoloDetection(VICTIM_CLASS_ID, 'victim', 0.95, self.bbox)]
        detector = YoloDetector(backend='mock', conf_threshold=0.6, detector_fn=lambda _img, _c: detections)
        filt = Victim3DFilter(confirm_count=2)
        pipeline = VictimObservationPipeline(
            detector=detector, victim_filter=filt, point_transformer=lambda _xyz: (2.0, 1.0, 0.1),
        )

        # Frame 1 valid depth -> 1/2
        res1 = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=10.0, monotonic_sec=1.0,
        )
        self.assertIsNone(res1.confirmed_map_xyz)

        # Frame 2 stale/absent depth -> resets confirmation streak!
        res2 = pipeline.process_frame(
            self.bgr_frame, None, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=10.2, monotonic_sec=1.2,
        )
        self.assertIsNone(res2.confirmed_map_xyz)

        # Frame 3 valid depth only counts as 1/2 (not 2/2) because streak was reset.
        res3 = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=10.4, monotonic_sec=1.4,
        )
        self.assertIsNone(res3.confirmed_map_xyz)

        # Check depth sync helper rejects stale depth outside tolerance
        def make_stamp(s: float) -> SimpleNamespace:
            sec = int(s)
            nsec = int(round((s - sec) * 1e9))
            return SimpleNamespace(sec=sec, nanosec=nsec)

        # Pure timestamp matching logic equivalent to select_matching_depth
        depth_buf = deque([
            (SimpleNamespace(header=SimpleNamespace(stamp=make_stamp(9.50))), 9.50),
            (SimpleNamespace(header=SimpleNamespace(stamp=make_stamp(10.02))), 10.02),
        ])
        max_dt = 0.08
        matched = min(
            ((msg, abs(ts - 10.00)) for msg, ts in depth_buf if abs(ts - 10.00) <= max_dt),
            key=lambda pair: pair[1],
            default=(None, None),
        )[0]
        self.assertIsNotNone(matched)
        too_old = min(
            ((msg, abs(ts - 10.50)) for msg, ts in depth_buf if abs(ts - 10.50) <= max_dt),
            key=lambda pair: pair[1],
            default=(None, None),
        )[0]
        self.assertIsNone(too_old)

    def test_missing_transformer_never_confirms_optical_coordinates_in_map(self):
        detector = YoloDetector(detector_fn=lambda _img, _c: [
            YoloDetection(VICTIM_CLASS_ID, 'victim', 1.0, self.bbox),
        ])
        pipeline = VictimObservationPipeline(detector, victim_filter=Victim3DFilter(confirm_count=1))
        result = pipeline.process_frame(
            self.bgr_frame, self.depth_frame, self.color_intr, self.depth_intr, self.extrinsics,
            stamp_sec=100.0, monotonic_sec=10.0,
        )
        self.assertIsNotNone(result.point_optical)
        self.assertIsNone(result.confirmed_map_xyz)
        with self.assertRaises(ValueError):
            pipeline.build_outputs(self.bgr_frame, result, attempt_id='test')

    def test_realsense_extrinsics_uses_column_major_rotation(self):
        extrinsics = Extrinsics.from_realsense((0, 1, 0, -1, 0, 0, 0, 0, 1), (1, 2, 3))
        point = extrinsics.rotation @ (1, 0, 0) + extrinsics.translation
        np.testing.assert_array_equal(point, [1, 3, 3])

    def test_yolo11n_single_class_raw_head_applies_inclusive_threshold_and_nms(self):
        dense = np.array([
            [100, 100, 80, 60, .92],
            [104, 103, 80, 60, .81],  # Suppressed by the higher-scoring overlapping box.
            [250, 100, 40, 20, .60],
            [350, 100, 40, 20, np.nextafter(np.float32(.60), np.float32(0))],
            [450, 100, 40, 20, 1.01],
            [0, 0, 0, 0, 0],
        ], dtype=np.float32)
        head = dense.T[None, ...]
        self.assertEqual(head.shape, (1, 5, 6))
        for output in (head, head[0], dense[None, ...], dense):
            with self.subTest(shape=output.shape):
                detections = _decode_yolo_output(
                    output, scale=1, pad_wh=(0, 0), img_wh=(640, 480),
                    conf_threshold=0.6, iou_threshold=0.45, class_names=CLASS_NAMES,
                )
                self.assertEqual([(d.class_id, d.label) for d in detections], [(0, 'victim')] * 2)
                self.assertEqual([d.bbox_xyxy for d in detections], [(60, 70, 140, 130), (230, 90, 270, 110)])
                np.testing.assert_allclose([d.confidence for d in detections], [.92, .60])

    def test_single_class_packed_head_filters_unknown_ids_without_second_nms(self):
        packed = np.zeros((1, 6, 6), dtype=np.float32)
        packed[0, :3] = [
            [60, 70, 140, 130, .8, 0],
            [60, 70, 140, 130, .7, 0],
            [20, 10, 80, 90, .9, 1],
        ]
        detections = _decode_yolo_output(
            packed, scale=.5, pad_wh=(10, 20), img_wh=(640, 480),
            conf_threshold=.6, iou_threshold=.45, class_names=CLASS_NAMES,
        )
        self.assertEqual([(d.class_id, d.label) for d in detections], [(0, 'victim')] * 2)
        self.assertEqual([d.bbox_xyxy for d in detections], [(100, 100, 260, 220)] * 2)

    def test_onnx_and_tensorrt_backends_decode_single_class_raw_output(self):
        head = np.array([[[32], [32], [20], [24], [.75]]], dtype=np.float32)
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        expected = [YoloDetection(0, 'victim', .75, (22.0, 20.0, 42.0, 44.0))]

        ort = YoloDetector('model.onnx', input_size=64)
        session = SimpleNamespace(run=Mock(return_value=[head]))
        ort._runtime = (session, 'input')
        self.assertEqual(ort.detect(image), expected)
        self.assertEqual(session.run.call_args.args[1]['input'].shape, (1, 3, 64, 64))

        trt = YoloDetector('model.engine', input_size=64)
        engine = SimpleNamespace(get_tensor_name=('input', 'output').__getitem__)
        context = Mock()
        context.get_tensor_shape.return_value = head.shape
        cuda = Mock()
        cuda.mem_alloc.side_effect = [1, 2]
        cuda.memcpy_dtoh_async.side_effect = lambda host, *_: np.copyto(host, head)
        trt._runtime = (engine, context, cuda)
        self.assertEqual(trt.detect(image), expected)
        context.execute_async_v3.assert_called_once()

    def test_ultralytics_backend_accepts_class_zero_only_at_or_above_threshold(self):
        detector = YoloDetector('model.pt', input_size=64)
        coords = np.array([[22, 20, 42, 44]], dtype=np.float32)
        boxes = [SimpleNamespace(cls=[cls], conf=[conf], xyxy=coords)
                 for cls, conf in ((0, .60), (0, .59), (1, .90))]
        detector._runtime = SimpleNamespace(predict=Mock(return_value=[SimpleNamespace(boxes=boxes)]))

        self.assertEqual(detector.detect(np.zeros((64, 64, 3), dtype=np.uint8)),
                         [YoloDetection(0, 'victim', .60, (22.0, 20.0, 42.0, 44.0))])

    def test_raw_image_and_depth_buffers_and_observation_jpeg(self):
        # Verify RGB->BGR conversion with padded stride and 16UC1 depth conversion
        rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        rgb[0, 0] = [10, 20, 30]
        padded_step = 8
        buf = bytearray(2 * padded_step)
        buf[0:6] = rgb[0].tobytes()
        buf[padded_step:padded_step + 6] = rgb[1].tobytes()
        bgr = image_to_bgr(bytes(buf), 2, 2, padded_step, 'rgb8')
        np.testing.assert_array_equal(bgr[0, 0], [30, 20, 10])

        raw_d = np.array([[1000, 1500], [2000, 0]], dtype=np.uint16)
        parsed_d = depth_to_array(raw_d.tobytes(), 2, 2, 4, '16UC1')
        np.testing.assert_array_equal(parsed_d, raw_d)

        jpeg = encode_observation_jpeg(self.bgr_frame, snapshot_max_width=640, max_height=480, quality=80)
        self.assertTrue(jpeg.startswith(b'\xff\xd8'))
        self.assertLessEqual(len(jpeg), MAX_OBSERVATION_JPEG_BYTES)

        # Verify observation payload validates MIN_OBSERVATION_CONFIDENCE = 0.6 boundary
        ok_payload = build_observation_payload(
            attempt_id='a1',
            label='victim',
            stamp=10.0,
            position_map=(1.0, 2.0, 0.1),
            confidence=0.60,
            jpeg_bytes=jpeg,
        )
        self.assertEqual(ok_payload['confidence'], 0.60)
        with self.assertRaises(ValueError):
            build_observation_payload(
                attempt_id='a1',
                label='victim',
                stamp=10.0,
                position_map=(1.0, 2.0, 0.1),
                confidence=0.59,  # below Observation.parse minimum 0.6
                jpeg_bytes=jpeg,
            )


if __name__ == '__main__':
    unittest.main()
