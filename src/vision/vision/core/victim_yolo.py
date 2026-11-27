"""YOLO RGB inference core, JPEG evidence encoding, and /vision/observations builder."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from io import BytesIO
import logging
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Sequence

_LOGGER = logging.getLogger(__name__)

import numpy as np

from .depth_3d import (
    CameraIntrinsics,
    DepthPointResult,
    Extrinsics,
    Victim3DFilter,
    estimate_bbox_3d,
)

CLASS_NAMES: dict[int, str] = {
    0: 'victim',
    1: 'qr_code',
}
VICTIM_CLASS_ID = 0
QR_CLASS_ID = 1
MAX_OBSERVATION_JPEG_BYTES = 2_000_000
MIN_OBSERVATION_CONFIDENCE = 0.6
DEFAULT_SNAPSHOT_MAX_WIDTH = 640


@dataclass(frozen=True)
class YoloDetection:
    """Single 2D YOLO detection in source color image pixel coordinates."""

    class_id: int
    label: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class FrameProcessResult:
    """Output of a single RGB-D detection and map-frame 3D confirmation step."""

    stamp_sec: float
    victim_detections: tuple[YoloDetection, ...] = ()
    qr_detections: tuple[YoloDetection, ...] = ()
    best_victim: YoloDetection | None = None
    point_optical: DepthPointResult | None = None
    point_map: tuple[float, float, float] | None = None
    confirmed_map_xyz: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class ObservationOutputs:
    """Prepared /vision/observations JSON and /vision/victim/image/compressed JPEG."""

    jpeg_bytes: bytes
    observation_payload: dict[str, Any] | None
    observation_json: str | None


def image_to_bgr(data: Any, width: int, height: int, step: int, encoding: str) -> np.ndarray:
    """Convert raw ROS Image buffer (rgb8/bgr8/mono8) into contiguous BGR uint8 array."""
    if encoding not in ('rgb8', 'bgr8', 'mono8'):
        raise ValueError(f'Unsupported image encoding: {encoding}')
    channels = 1 if encoding == 'mono8' else 3
    row_bytes = width * channels
    if width <= 0 or height <= 0 or step < row_bytes:
        raise ValueError('Invalid image dimensions or stride')
    buf = np.frombuffer(data, dtype=np.uint8)
    if buf.size != height * step:
        raise ValueError('Image buffer size does not match height * step')
    rows = buf.reshape(height, step)[:, :row_bytes]
    if encoding == 'mono8':
        gray = rows.reshape(height, width)
        return np.repeat(gray[..., None], 3, axis=2)
    pixels = rows.reshape(height, width, 3)
    if encoding == 'rgb8':
        return np.ascontiguousarray(pixels[..., ::-1])
    return np.ascontiguousarray(pixels)


def depth_to_array(
    data: Any,
    width: int,
    height: int,
    step: int,
    encoding: str,
    is_bigendian: int = 0,
) -> np.ndarray:
    """Convert raw ROS depth Image buffer (16UC1/32FC1) to a 2D numpy array."""
    if encoding not in ('16UC1', '32FC1'):
        raise ValueError(f'Unsupported depth encoding: {encoding}')
    dtype = np.dtype(('>' if is_bigendian else '<') + ('u2' if encoding == '16UC1' else 'f4'))
    row_bytes = width * dtype.itemsize
    if width <= 0 or height <= 0 or step < row_bytes:
        raise ValueError('Invalid depth dimensions or stride')
    buf = np.frombuffer(data, dtype=np.uint8)
    if buf.size != height * step:
        raise ValueError('Depth buffer size does not match height * step')
    return np.ndarray((height, width), dtype=dtype, buffer=buf, strides=(step, dtype.itemsize))


def transform_point(
    point_xyz: Sequence[float],
    translation_xyz: Sequence[float],
    rotation_xyzw: Sequence[float],
) -> tuple[float, float, float]:
    """Apply rigid transform (translation + XYZW quaternion) to a 3D point."""
    if len(point_xyz) != 3 or len(translation_xyz) != 3 or len(rotation_xyzw) != 4:
        raise ValueError('Expected 3D point, 3D translation, and 4D xyzw quaternion')
    p = np.asarray(point_xyz, dtype=np.float64)
    t = np.asarray(translation_xyz, dtype=np.float64)
    qx, qy, qz, qw = (float(v) for v in rotation_xyzw)
    norm = float(np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw))
    if not (isfinite(norm) and norm > 1e-9):
        raise ValueError('Invalid quaternion norm')
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    rot = np.array(
        [
            [1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy - qz * qw), 2.0 * (qx * qz + qy * qw)],
            [2.0 * (qx * qy + qz * qw), 1.0 - 2.0 * (qx * qx + qz * qz), 2.0 * (qy * qz - qx * qw)],
            [2.0 * (qx * qz - qy * qw), 2.0 * (qy * qz + qx * qw), 1.0 - 2.0 * (qx * qx + qy * qy)],
        ],
        dtype=np.float64,
    )
    out = rot @ p + t
    if not np.all(np.isfinite(out)):
        raise ValueError('Transformed point is non-finite')
    return (float(out[0]), float(out[1]), float(out[2]))


def encode_observation_jpeg(
    bgr_image: np.ndarray,
    *,
    snapshot_max_width: int = DEFAULT_SNAPSHOT_MAX_WIDTH,
    max_height: int | None = None,
    quality: int = 80,
    max_bytes: int = MAX_OBSERVATION_JPEG_BYTES,
) -> bytes:
    """Proportionally downscale if wider than snapshot_max_width and encode as bounded JPEG."""
    if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
        raise ValueError(f'Expected (H, W, 3) BGR image, got {bgr_image.shape}')
    if snapshot_max_width <= 0 or (max_height is not None and max_height <= 0):
        raise ValueError('Invalid JPEG resize bounds')
    if not 1 <= quality <= 100 or max_bytes <= 0:
        raise ValueError('Invalid JPEG encoding parameters')

    h, w = bgr_image.shape[:2]
    scale = min(1.0, snapshot_max_width / float(w))
    if max_height is not None:
        scale = min(scale, max_height / float(h))
    target_w = max(1, int(round(w * scale)))
    target_h = max(1, int(round(h * scale)))

    quality_ladder = [int(quality)]
    for fallback_q in (60, 40, 25):
        if fallback_q < quality_ladder[-1]:
            quality_ladder.append(fallback_q)

    try:
        import cv2  # Lazy optional import

        img = (
            cv2.resize(bgr_image, (target_w, target_h), interpolation=cv2.INTER_AREA)
            if (target_w, target_h) != (w, h)
            else bgr_image
        )
        for q in quality_ladder:
            ok, encoded = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if ok:
                data = encoded.tobytes()
                if len(data) <= max_bytes:
                    return data
    except ImportError:
        from PIL import Image as PilImage

        rgb = np.ascontiguousarray(bgr_image[..., ::-1])
        pil = PilImage.fromarray(rgb)
        if (target_w, target_h) != (w, h):
            pil = pil.resize((target_w, target_h), PilImage.Resampling.BILINEAR)
        for q in quality_ladder:
            with BytesIO() as out:
                pil.save(out, format='JPEG', quality=q)
                data = out.getvalue()
                if len(data) <= max_bytes:
                    return data

    raise ValueError(f'Unable to encode JPEG within {max_bytes} bytes')


def build_observation_payload(
    *,
    attempt_id: str,
    label: str,
    stamp: float,
    position_map: Sequence[float],
    confidence: float,
    jpeg_bytes: bytes,
    frame_id: str = 'map',
) -> dict[str, Any]:
    """Build and validate a JSON-serializable /vision/observations dictionary."""
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError('attempt_id must be a non-empty string')
    if frame_id != 'map':
        raise ValueError(f"Observation frame_id must be 'map', got {frame_id!r}")
    if not label:
        raise ValueError('label must be non-empty')
    if not (isfinite(stamp) and stamp >= 0.0):
        raise ValueError('stamp must be a finite non-negative ROS timestamp')
    if len(position_map) != 3 or not all(isfinite(float(v)) for v in position_map):
        raise ValueError('position_map must contain 3 finite coordinates')
    conf = float(confidence)
    if not (MIN_OBSERVATION_CONFIDENCE <= conf <= 1.0):
        raise ValueError(
            f'confidence must be in [{MIN_OBSERVATION_CONFIDENCE}, 1.0], got {conf}'
        )
    if not jpeg_bytes.startswith(b'\xff\xd8') or len(jpeg_bytes) > MAX_OBSERVATION_JPEG_BYTES:
        raise ValueError('Invalid or oversized JPEG snapshot')

    return {
        'attempt_id': attempt_id.strip(),
        'label': label,
        'stamp': float(stamp),
        'frame_id': 'map',
        'position': [float(position_map[0]), float(position_map[1]), float(position_map[2])],
        'image_jpeg_b64': base64.b64encode(jpeg_bytes).decode('ascii'),
        'confidence': conf,
    }


def _nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Pure-NumPy greedy NMS on [x1, y1, x2, y2] boxes."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0.0, inter / union, 0.0)
        order = rest[iou <= iou_threshold]
    return keep


def _letterbox_rgb(
    bgr_image: np.ndarray,
    input_size: int,
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize with aspect ratio + 114 padding, returning NCHW float32 RGB in [0, 1]."""
    import cv2

    h, w = bgr_image.shape[:2]
    scale = min(input_size / float(w), input_size / float(h))
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    pad_w = (input_size - new_w) / 2.0
    pad_h = (input_size - new_h) / 2.0
    resized = cv2.resize(bgr_image, (new_w, new_h), interpolation=cv2.INTER_LINEAR) if (new_w, new_h) != (w, h) else bgr_image
    top, bottom = int(round(pad_h - 0.1)), int(round(pad_h + 0.1))
    left, right = int(round(pad_w - 0.1)), int(round(pad_w + 0.1))
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
    return tensor[None, ...], scale, (float(left), float(top))


def _decode_yolo_output(
    output: np.ndarray,
    *,
    scale: float,
    pad_wh: tuple[float, float],
    img_wh: tuple[int, int],
    conf_threshold: float,
    iou_threshold: float,
    class_names: dict[int, str],
) -> list[YoloDetection]:
    """Decode raw Ultralytics/ONNX/TRT head output ((1,4+C,N), (1,N,4+C), or end2end (1,N,6))."""
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2 or arr.shape[0] == 0:
        return []

    pad_w, pad_h = pad_wh
    img_w, img_h = img_wh

    # End-to-end exported YOLO26/YOLOv8/v10 with built-in NMS: (N, 6) [x1, y1, x2, y2, conf, cls]
    if arr.shape[1] == 6 and np.all(np.isin(arr[:, 5], tuple(class_names))):
        detections: list[YoloDetection] = []
        for row in arr:
            conf = float(row[4])
            if not conf_threshold <= conf <= 1.0 or not np.all(np.isfinite(row[:4])):
                continue
            cls_id = int(row[5])
            x1 = max(0.0, min(float(img_w), (float(row[0]) - pad_w) / scale))
            y1 = max(0.0, min(float(img_h), (float(row[1]) - pad_h) / scale))
            x2 = max(0.0, min(float(img_w), (float(row[2]) - pad_w) / scale))
            y2 = max(0.0, min(float(img_h), (float(row[3]) - pad_h) / scale))
            if x2 > x1 and y2 > y1:
                detections.append(YoloDetection(cls_id, class_names[cls_id], conf, (x1, y1, x2, y2)))
        return detections

    # Standard dense head: (4+C, N) -> transpose to (N, 4+C)
    channels = 4 + len(class_names)
    if arr.shape[0] == channels:
        arr = arr.T
    if arr.shape[1] != channels:
        return []

    cx, cy, bw, bh = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    scores_all = arr[:, 4:]
    cls_ids = np.argmax(scores_all, axis=1)
    confs = scores_all[np.arange(arr.shape[0]), cls_ids]
    mask = (confs >= conf_threshold) & (confs <= 1.0) & np.isfinite(arr[:, :4]).all(axis=1)
    if not np.any(mask):
        return []

    cx, cy, bw, bh = cx[mask], cy[mask], bw[mask], bh[mask]
    cls_ids, confs = cls_ids[mask], confs[mask]

    x1 = np.clip((cx - bw / 2.0 - pad_w) / scale, 0.0, float(img_w))
    y1 = np.clip((cy - bh / 2.0 - pad_h) / scale, 0.0, float(img_h))
    x2 = np.clip((cx + bw / 2.0 - pad_w) / scale, 0.0, float(img_w))
    y2 = np.clip((cy + bh / 2.0 - pad_h) / scale, 0.0, float(img_h))
    boxes = np.column_stack((x1, y1, x2, y2))

    detections = []
    for cls_id in np.unique(cls_ids):
        cid = int(cls_id)
        if cid not in class_names:
            continue
        cls_mask = cls_ids == cls_id
        cls_boxes = boxes[cls_mask]
        cls_scores = confs[cls_mask]
        for idx in _nms_xyxy(cls_boxes, cls_scores, iou_threshold):
            bx1, by1, bx2, by2 = (float(v) for v in cls_boxes[idx])
            if bx2 > bx1 and by2 > by1:
                detections.append(
                    YoloDetection(cid, class_names[cid], float(cls_scores[idx]), (bx1, by1, bx2, by2))
                )
    return detections


class YoloDetector:
    """Lazy multi-backend YOLO detector supporting TensorRT (.engine), ONNX (.onnx), Ultralytics (.pt), or mock."""

    def __init__(
        self,
        model_path: str | Path = '',
        *,
        backend: str = 'auto',
        conf_threshold: float = MIN_OBSERVATION_CONFIDENCE,
        iou_threshold: float = 0.45,
        input_size: int = 640,
        class_names: dict[int, str] | None = None,
        detector_fn: Callable[[np.ndarray, float], Sequence[YoloDetection]] | None = None,
    ) -> None:
        if not 0.0 < conf_threshold <= 1.0:
            raise ValueError('conf_threshold must be in (0, 1]')
        if not 0.0 < iou_threshold <= 1.0:
            raise ValueError('iou_threshold must be in (0, 1]')
        if input_size < 32:
            raise ValueError('input_size must be >= 32')

        self.model_path = Path(model_path) if model_path else None
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self.input_size = int(input_size)
        self.class_names = dict(class_names or CLASS_NAMES)
        self._detector_fn = detector_fn
        self.backend = self._resolve_backend(backend, self.model_path, detector_fn)
        self._runtime: Any = None

    @staticmethod
    def _resolve_backend(
        backend: str,
        model_path: Path | None,
        detector_fn: Callable[..., Any] | None,
    ) -> str:
        if detector_fn is not None or backend == 'mock':
            return 'mock'
        mode = backend.strip().lower()
        if mode == 'auto':
            if model_path is None:
                raise ValueError("model_path is required when backend is 'auto'")
            suffix = model_path.suffix.lower()
            mapping = {'.engine': 'tensorrt', '.onnx': 'onnx', '.pt': 'ultralytics'}
            if suffix not in mapping:
                raise ValueError(f'Cannot infer YOLO backend from model extension: {suffix!r}')
            return mapping[suffix]
        if mode not in ('tensorrt', 'onnx', 'ultralytics'):
            raise ValueError(f'Unsupported YOLO backend: {backend!r}')
        return mode

    def _ensure_loaded(self) -> None:
        if self.backend == 'mock' or self._runtime is not None:
            return
        if self.model_path is None or not self.model_path.is_file():
            raise FileNotFoundError(f'YOLO model file not found: {self.model_path}')

        if self.backend == 'ultralytics':
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError('ultralytics package is required for .pt inference') from exc
            self._runtime = YOLO(str(self.model_path))
            return

        if self.backend == 'onnx':
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise RuntimeError('onnxruntime package is required for .onnx inference') from exc
            providers = [p for p in ('CUDAExecutionProvider', 'CPUExecutionProvider') if p in ort.get_available_providers()]
            session = ort.InferenceSession(str(self.model_path), providers=providers or None)
            self._runtime = (session, session.get_inputs()[0].name)
            return

        if self.backend == 'tensorrt':
            self._runtime = self._load_tensorrt(self.model_path)

    @staticmethod
    def _load_tensorrt(engine_path: Path) -> Any:
        try:
            import tensorrt as trt
        except ImportError as exc:
            raise RuntimeError('tensorrt package is required for .engine inference') from exc
        try:
            import pycuda.driver as cuda  # noqa: F401
            import pycuda.autoinit  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('pycuda is required for raw TensorRT .engine execution') from exc

        logger = trt.Logger(trt.Logger.WARNING)
        runtime = trt.Runtime(logger)
        engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if engine is None:
            raise RuntimeError(f'Failed to deserialize TensorRT engine: {engine_path}')
        return (engine, engine.create_execution_context(), cuda)

    def detect(self, bgr_image: np.ndarray) -> list[YoloDetection]:
        """Run inference on a (H, W, 3) BGR uint8 image."""
        if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            raise ValueError(f'Expected (H, W, 3) BGR image, got {bgr_image.shape}')

        if self._detector_fn is not None:
            raw = self._detector_fn(bgr_image, self.conf_threshold)
            return [d for d in raw if d.confidence >= self.conf_threshold and d.class_id in self.class_names]

        if self.backend == 'mock':
            return []

        self._ensure_loaded()
        if self.backend == 'ultralytics':
            results = self._runtime.predict(
                bgr_image,
                imgsz=self.input_size,
                conf=self.conf_threshold,
                iou=self.iou_threshold,
                verbose=False,
            )
            detections: list[YoloDetection] = []
            for res in results:
                boxes = getattr(res, 'boxes', None)
                if boxes is None:
                    continue
                for box in boxes:
                    cls_id = int(box.cls[0])
                    if cls_id not in self.class_names:
                        continue
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                    detections.append(YoloDetection(cls_id, self.class_names[cls_id], conf, (x1, y1, x2, y2)))
            return detections

        h, w = bgr_image.shape[:2]
        tensor, scale, pad_wh = _letterbox_rgb(bgr_image, self.input_size)
        if self.backend == 'onnx':
            session, input_name = self._runtime
            output = session.run(None, {input_name: tensor})[0]
            return _decode_yolo_output(
                output,
                scale=scale,
                pad_wh=pad_wh,
                img_wh=(w, h),
                conf_threshold=self.conf_threshold,
                iou_threshold=self.iou_threshold,
                class_names=self.class_names,
            )

        # TensorRT execution path
        engine, context, cuda = self._runtime
        in_name = engine.get_tensor_name(0)
        out_name = engine.get_tensor_name(1)
        out_shape = tuple(context.get_tensor_shape(out_name))
        out_host = np.empty(out_shape, dtype=np.float32)
        d_in = cuda.mem_alloc(tensor.nbytes)
        d_out = cuda.mem_alloc(out_host.nbytes)
        stream = cuda.Stream()
        cuda.memcpy_htod_async(d_in, tensor, stream)
        context.set_tensor_address(in_name, int(d_in))
        context.set_tensor_address(out_name, int(d_out))
        context.execute_async_v3(stream_handle=stream.handle)
        cuda.memcpy_dtoh_async(out_host, d_out, stream)
        stream.synchronize()
        return _decode_yolo_output(
            out_host,
            scale=scale,
            pad_wh=pad_wh,
            img_wh=(w, h),
            conf_threshold=self.conf_threshold,
            iou_threshold=self.iou_threshold,
            class_names=self.class_names,
        )


@dataclass
class VictimObservationPipeline:
    """Coordinate YOLO detection, unaligned 3D depth lookup, map-frame filtering, and payload creation."""

    detector: YoloDetector
    victim_filter: Victim3DFilter = field(default_factory=Victim3DFilter)
    min_observation_confidence: float = MIN_OBSERVATION_CONFIDENCE
    depth_scale: float = 0.001
    jpeg_quality: int = 80
    snapshot_max_width: int = DEFAULT_SNAPSHOT_MAX_WIDTH
    jpeg_max_height: int | None = None
    point_transformer: Callable[[tuple[float, float, float]], tuple[float, float, float] | None] | None = None
    estimate_kwargs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not MIN_OBSERVATION_CONFIDENCE <= self.min_observation_confidence <= 1.0:
            raise ValueError(
                f'min_observation_confidence must be in [{MIN_OBSERVATION_CONFIDENCE}, 1.0]'
            )
        if not 1 <= self.snapshot_max_width <= DEFAULT_SNAPSHOT_MAX_WIDTH:
            raise ValueError(f'snapshot_max_width must be in [1, {DEFAULT_SNAPSHOT_MAX_WIDTH}]')

    def process_frame(
        self,
        bgr_image: np.ndarray,
        depth_image: np.ndarray | None,
        color_intrinsics: CameraIntrinsics,
        depth_intrinsics: CameraIntrinsics | None,
        extrinsics: Extrinsics | None,
        *,
        stamp_sec: float,
        monotonic_sec: float,
        point_transformer: Callable[[tuple[float, float, float]], tuple[float, float, float] | None] | None = None,
    ) -> FrameProcessResult:
        """Detect victim & qr_code, estimate 3D pose, transform to map, and update Victim3DFilter."""
        detections = self.detector.detect(bgr_image)
        victims = tuple(
            d for d in detections
            if d.class_id == VICTIM_CLASS_ID and self.min_observation_confidence <= d.confidence <= 1.0
        )
        qrs = tuple(d for d in detections if d.class_id == QR_CLASS_ID)

        if not victims or depth_image is None or depth_intrinsics is None or extrinsics is None:
            self.victim_filter.observe(None, monotonic_sec)
            return FrameProcessResult(
                stamp_sec=stamp_sec,
                victim_detections=victims,
                qr_detections=qrs,
            )

        best = max(victims, key=lambda d: d.confidence)
        point_3d = estimate_bbox_3d(
            best.bbox_xyxy,
            depth_image,
            color_intrinsics,
            depth_intrinsics,
            extrinsics,
            depth_scale=self.depth_scale,
            **self.estimate_kwargs,
        )
        if point_3d is None:
            self.victim_filter.observe(None, monotonic_sec)
            return FrameProcessResult(
                stamp_sec=stamp_sec,
                victim_detections=victims,
                qr_detections=qrs,
                best_victim=best,
            )

        transformer = point_transformer if point_transformer is not None else self.point_transformer
        optical_xyz = (point_3d.x, point_3d.y, point_3d.z)
        transformed = None
        if transformer is not None:
            try:
                transformed = transformer(optical_xyz)
            except Exception as exc:
                _LOGGER.warning('point_transformer failed; skipping frame without resetting filter: %s', exc)

        if transformed is None or len(transformed) != 3 or not all(isfinite(v) for v in transformed):
            # Skip this frame without losing recent map-frame samples.
            return FrameProcessResult(
                stamp_sec=stamp_sec,
                victim_detections=victims,
                qr_detections=qrs,
                best_victim=best,
                point_optical=point_3d,
            )
        point_map = (float(transformed[0]), float(transformed[1]), float(transformed[2]))

        confirmed_map = self.victim_filter.observe(point_map, monotonic_sec)
        return FrameProcessResult(
            stamp_sec=stamp_sec,
            victim_detections=victims,
            qr_detections=qrs,
            best_victim=best,
            point_optical=point_3d,
            point_map=point_map,
            confirmed_map_xyz=confirmed_map,
        )

    def build_outputs(
        self,
        bgr_image: np.ndarray,
        result: FrameProcessResult,
        *,
        attempt_id: str,
    ) -> ObservationOutputs:
        """Encode downscaled JPEG snapshot and (when attempt_id is non-empty) build /vision/observations JSON."""
        import json

        if result.best_victim is None or result.confirmed_map_xyz is None:
            raise ValueError('Cannot build outputs without confirmed map victim detection')

        jpeg_bytes = encode_observation_jpeg(
            bgr_image,
            snapshot_max_width=self.snapshot_max_width,
            max_height=self.jpeg_max_height,
            quality=self.jpeg_quality,
        )
        if not attempt_id or not attempt_id.strip():
            return ObservationOutputs(
                jpeg_bytes=jpeg_bytes,
                observation_payload=None,
                observation_json=None,
            )

        payload = build_observation_payload(
            attempt_id=attempt_id,
            label='victim',
            stamp=result.stamp_sec,
            position_map=result.confirmed_map_xyz,
            confidence=result.best_victim.confidence,
            jpeg_bytes=jpeg_bytes,
            frame_id='map',
        )
        return ObservationOutputs(
            jpeg_bytes=jpeg_bytes,
            observation_payload=payload,
            observation_json=json.dumps(payload, ensure_ascii=False),
        )
