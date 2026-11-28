"""Estimate 3D object coordinates from an unaligned D435 depth map and a 2D color bbox."""

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    """Pinhole + Brown-Conrady (plumb_bob) intrinsics for an optical frame (+X right, +Y down, +Z forward)."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError('Image dimensions must be positive')
        if not (isfinite(self.fx) and self.fx > 0 and isfinite(self.fy) and self.fy > 0):
            raise ValueError('Focal lengths fx and fy must be finite and positive')
        if not (isfinite(self.cx) and isfinite(self.cy)):
            raise ValueError('Principal point cx and cy must be finite')
        coeffs = tuple(float(c) for c in self.distortion)
        if any(not isfinite(c) for c in coeffs):
            raise ValueError('Distortion coefficients must be finite')
        object.__setattr__(self, 'distortion', coeffs)

    @property
    def has_distortion(self) -> bool:
        return any(abs(c) > 0.0 for c in self.distortion)

    def plumb_bob_coeffs(self) -> tuple[float, float, float, float, float]:
        padded = list(self.distortion[:5]) + [0.0] * max(0, 5 - len(self.distortion))
        return tuple(padded)  # type: ignore[return-value]

    @classmethod
    def from_k(
        cls,
        width: int,
        height: int,
        k: Sequence[float],
        distortion: Sequence[float] = (),
    ) -> 'CameraIntrinsics':
        """Build intrinsics from a 9-element row-major CameraInfo.k matrix and optional D."""
        if len(k) != 9:
            raise ValueError(f'Expected 9 elements in K matrix, got {len(k)}')
        return cls(
            width=int(width),
            height=int(height),
            fx=float(k[0]),
            fy=float(k[4]),
            cx=float(k[2]),
            cy=float(k[5]),
            distortion=tuple(float(c) for c in distortion),
        )


@dataclass(frozen=True)
class Extrinsics:
    """Rigid transform from depth optical frame to color optical frame: P_color = R @ P_depth + t."""

    rotation: np.ndarray
    translation: np.ndarray

    def __post_init__(self) -> None:
        rot = np.asarray(self.rotation, dtype=np.float64)
        trans = np.asarray(self.translation, dtype=np.float64).reshape(3)
        if rot.shape != (3, 3):
            raise ValueError(f'Expected (3, 3) rotation matrix, got {rot.shape}')
        if not (np.all(np.isfinite(rot)) and np.all(np.isfinite(trans))):
            raise ValueError('Extrinsics must be finite')
        object.__setattr__(self, 'rotation', rot)
        object.__setattr__(self, 'translation', trans)

    @classmethod
    def identity(cls) -> 'Extrinsics':
        return cls(rotation=np.eye(3, dtype=np.float64), translation=np.zeros(3, dtype=np.float64))

    @classmethod
    def from_realsense(cls, rotation: Sequence[float], translation: Sequence[float]) -> 'Extrinsics':
        """Build the transform from the column-major RealSense Extrinsics message."""
        matrix = np.asarray(rotation, dtype=np.float64).reshape((3, 3), order='F')
        return cls(rotation=matrix, translation=np.asarray(translation, dtype=np.float64))


@dataclass(frozen=True)
class DepthPointResult:
    """Estimated 3D point in the color optical frame (meters)."""

    x: float
    y: float
    z: float
    valid_points: int
    depth_roi: tuple[int, int, int, int]


def project_points_to_color(
    pts_color: np.ndarray,
    color: CameraIntrinsics,
) -> tuple[np.ndarray, np.ndarray]:
    """Project 3D points (N, 3) with Z > 0 to color pixels using K and optional plumb_bob D."""
    x_n = pts_color[:, 0] / pts_color[:, 2]
    y_n = pts_color[:, 1] / pts_color[:, 2]
    if color.has_distortion:
        k1, k2, p1, p2, k3 = color.plumb_bob_coeffs()
        r2 = x_n * x_n + y_n * y_n
        r4 = r2 * r2
        radial = 1.0 + k1 * r2 + k2 * r4 + k3 * (r4 * r2)
        xy = x_n * y_n
        x_d = x_n * radial + 2.0 * p1 * xy + p2 * (r2 + 2.0 * x_n * x_n)
        y_d = y_n * radial + p1 * (r2 + 2.0 * y_n * y_n) + 2.0 * p2 * xy
    else:
        x_d, y_d = x_n, y_n
    return color.fx * x_d + color.cx, color.fy * y_d + color.cy


def _undistort_normalized(x_d: float, y_d: float, color: CameraIntrinsics) -> tuple[float, float]:
    """Iteratively invert plumb_bob distortion for bounding depth ROI search."""
    if not color.has_distortion:
        return x_d, y_d
    k1, k2, p1, p2, k3 = color.plumb_bob_coeffs()
    x, y = x_d, y_d
    for _ in range(5):
        r2 = x * x + y * y
        r4 = r2 * r2
        radial = 1.0 + k1 * r2 + k2 * r4 + k3 * (r4 * r2)
        if abs(radial) < 1e-6:
            break
        dx = 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
        dy = p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
        x = (x_d - dx) / radial
        y = (y_d - dy) / radial
    return x, y


def _compute_depth_roi(
    box_color: tuple[float, float, float, float],
    color: CameraIntrinsics,
    depth: CameraIntrinsics,
    extrinsics: Extrinsics,
    min_depth_m: float,
    max_depth_m: float,
    pad_px: int = 6,
) -> tuple[int, int, int, int] | None:
    """Project the color bbox frustum slab back into depth pixels to bound deprojection work."""
    x1, y1, x2, y2 = box_color
    z_near = max(min_depth_m, 0.1)
    z_far = max(max_depth_m, z_near + 0.1)
    rays = [
        _undistort_normalized((u - color.cx) / color.fx, (v - color.cy) / color.fy, color)
        for u in (x1, x2)
        for v in (y1, y2)
    ]
    corners_color = [(rx * z, ry * z, z) for z in (z_near, z_far) for rx, ry in rays]
    pts_color = np.asarray(corners_color, dtype=np.float64)
    # Inverse rigid transform: P_depth = R^T @ (P_color - t)
    pts_depth = (pts_color - extrinsics.translation) @ extrinsics.rotation
    positive = pts_depth[:, 2] > 1e-4
    if not np.any(positive):
        return None
    pts_depth = pts_depth[positive]
    u_d = depth.fx * (pts_depth[:, 0] / pts_depth[:, 2]) + depth.cx
    v_d = depth.fy * (pts_depth[:, 1] / pts_depth[:, 2]) + depth.cy

    effective_pad = pad_px + (8 if color.has_distortion else 0)
    dx1 = max(0, int(np.floor(np.min(u_d))) - effective_pad)
    dy1 = max(0, int(np.floor(np.min(v_d))) - effective_pad)
    dx2 = min(depth.width, int(np.ceil(np.max(u_d))) + effective_pad)
    dy2 = min(depth.height, int(np.ceil(np.max(v_d))) + effective_pad)
    if dx2 <= dx1 or dy2 <= dy1:
        return None
    return (dx1, dy1, dx2, dy2)


def _depth_roi_to_meters(roi: np.ndarray, depth_scale: float) -> np.ndarray:
    """Convert raw uint16 (mm) or float (m) depth values to float64 meters."""
    if np.issubdtype(roi.dtype, np.integer):
        return roi.astype(np.float64) * depth_scale
    if np.issubdtype(roi.dtype, np.floating):
        return roi.astype(np.float64)
    raise ValueError(f'Unsupported depth dtype: {roi.dtype}')


def estimate_bbox_3d(
    bbox_xyxy: Sequence[float],
    depth_image: np.ndarray,
    color_intrinsics: CameraIntrinsics,
    depth_intrinsics: CameraIntrinsics,
    extrinsics: Extrinsics,
    *,
    depth_scale: float = 0.001,
    inner_margin_ratio: float = 0.20,
    z_percentile: float = 20.0,
    z_band_m: float = 0.05,
    min_depth_m: float = 0.25,
    max_depth_m: float = 3.0,
    min_valid_points: int = 10,
    sample_stride: int = 1,
) -> DepthPointResult | None:
    """Estimate a stable 3D target point in color optical frame from unaligned depth.

    Uses the central 60% of `bbox_xyxy` by default (`inner_margin_ratio=0.20`),
    isolates the near-surface cluster `|Z - z_front| <= z_band_m` around the
    20th percentile depth, and returns the median (X, Y, Z) over that cluster.
    """
    if depth_image.ndim != 2 or depth_image.shape != (depth_intrinsics.height, depth_intrinsics.width):
        raise ValueError(
            f'Expected depth shape {(depth_intrinsics.height, depth_intrinsics.width)}, '
            f'got {depth_image.shape}'
        )
    if len(bbox_xyxy) != 4:
        raise ValueError(f'Expected 4 bbox coordinates (x1, y1, x2, y2), got {len(bbox_xyxy)}')
    if not 0.0 <= inner_margin_ratio < 0.49:
        raise ValueError('inner_margin_ratio must be in [0.0, 0.49)')
    if not 0.0 <= z_percentile <= 100.0:
        raise ValueError('z_percentile must be in [0, 100]')
    if z_band_m <= 0:
        raise ValueError('z_band_m must be positive')
    if sample_stride < 1:
        raise ValueError('sample_stride must be >= 1')
    if min_depth_m <= 0 or max_depth_m <= min_depth_m:
        raise ValueError('Invalid depth range')

    x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
    x1 = max(0.0, min(x1, float(color_intrinsics.width)))
    x2 = max(0.0, min(x2, float(color_intrinsics.width)))
    y1 = max(0.0, min(y1, float(color_intrinsics.height)))
    y2 = max(0.0, min(y2, float(color_intrinsics.height)))
    if x2 <= x1 or y2 <= y1:
        return None

    margin_x = (x2 - x1) * inner_margin_ratio
    margin_y = (y2 - y1) * inner_margin_ratio
    ix1, ix2 = x1 + margin_x, x2 - margin_x
    iy1, iy2 = y1 + margin_y, y2 - margin_y

    depth_roi = _compute_depth_roi(
        (ix1, iy1, ix2, iy2),
        color_intrinsics,
        depth_intrinsics,
        extrinsics,
        min_depth_m,
        max_depth_m,
    )
    if depth_roi is None:
        return None

    dx1, dy1, dx2, dy2 = depth_roi
    roi_raw = depth_image[dy1:dy2:sample_stride, dx1:dx2:sample_stride]
    roi_m = _depth_roi_to_meters(roi_raw, depth_scale)

    valid_mask = np.isfinite(roi_m) & (roi_m >= min_depth_m) & (roi_m <= max_depth_m)
    if not np.any(valid_mask):
        return None

    rows, cols = np.nonzero(valid_mask)
    z_d = roi_m[rows, cols]
    u_d = (dx1 + cols * sample_stride).astype(np.float64)
    v_d = (dy1 + rows * sample_stride).astype(np.float64)

    x_d = (u_d - depth_intrinsics.cx) * z_d / depth_intrinsics.fx
    y_d = (v_d - depth_intrinsics.cy) * z_d / depth_intrinsics.fy
    pts_depth = np.column_stack((x_d, y_d, z_d))

    pts_color = pts_depth @ extrinsics.rotation.T + extrinsics.translation
    z_c = pts_color[:, 2]
    in_range = (z_c >= min_depth_m) & (z_c <= max_depth_m)
    if not np.any(in_range):
        return None
    pts_color = pts_color[in_range]

    u_c, v_c = project_points_to_color(pts_color, color_intrinsics)
    in_bbox = (u_c >= ix1) & (u_c <= ix2) & (v_c >= iy1) & (v_c <= iy2)
    matched = pts_color[in_bbox]
    if matched.shape[0] < min_valid_points:
        return None

    z_vals = matched[:, 2]
    z_front = float(np.percentile(z_vals, z_percentile))
    cluster = matched[np.abs(z_vals - z_front) <= z_band_m]
    cluster_count = int(cluster.shape[0])
    if cluster_count < min_valid_points:
        return None

    return DepthPointResult(
        x=float(np.median(cluster[:, 0])),
        y=float(np.median(cluster[:, 1])),
        z=float(np.median(cluster[:, 2])),
        valid_points=cluster_count,
        depth_roi=depth_roi,
    )


class Victim3DFilter:
    """Confirm a 3D victim location only after N consecutive spatially consistent detections."""

    def __init__(
        self,
        confirm_count: int = 3,
        max_spread_m: float = 0.15,
        max_age_sec: float = 1.0,
    ) -> None:
        if confirm_count < 1:
            raise ValueError('confirm_count must be >= 1')
        if not (isfinite(max_spread_m) and max_spread_m > 0):
            raise ValueError('max_spread_m must be finite and positive')
        if not (isfinite(max_age_sec) and max_age_sec > 0):
            raise ValueError('max_age_sec must be finite and positive')
        self.confirm_count = confirm_count
        self.max_spread_m = max_spread_m
        self.max_age_sec = max_age_sec
        self._samples: list[tuple[np.ndarray, float]] = []

    def reset(self) -> None:
        self._samples.clear()

    @staticmethod
    def _extract_xyz(point: DepthPointResult | Sequence[float]) -> np.ndarray | None:
        if isinstance(point, DepthPointResult):
            arr = np.array([point.x, point.y, point.z], dtype=np.float64)
        else:
            if len(point) != 3:
                raise ValueError(f'Expected 3 coordinates (x, y, z), got {len(point)}')
            arr = np.asarray(point, dtype=np.float64)
        if not np.all(np.isfinite(arr)):
            return None
        return arr

    def observe(
        self,
        point: DepthPointResult | Sequence[float] | None,
        timestamp: float,
    ) -> tuple[float, float, float] | None:
        if not isfinite(timestamp):
            raise ValueError('timestamp must be finite')
        if self._samples and timestamp < self._samples[-1][1]:
            self.reset()
        self._samples = [(p, t) for p, t in self._samples if timestamp - t <= self.max_age_sec]
        if point is None:
            self.reset()
            return None
        xyz = self._extract_xyz(point)
        if xyz is None:
            self.reset()
            return None
        if self._samples and any(float(np.linalg.norm(xyz - prev)) > self.max_spread_m for prev, _ in self._samples):
            self._samples = [(xyz, timestamp)]
            return None
        self._samples.append((xyz, timestamp))
        if len(self._samples) > self.confirm_count:
            self._samples = self._samples[-self.confirm_count:]
        if len(self._samples) < self.confirm_count:
            return None
        stacked = np.stack([p for p, _ in self._samples], axis=0)
        return (
            float(np.median(stacked[:, 0])),
            float(np.median(stacked[:, 1])),
            float(np.median(stacked[:, 2])),
        )
