import numpy as np
import pytest

from vision.core.depth_3d import (
    CameraIntrinsics,
    DepthPointResult,
    Extrinsics,
    Victim3DFilter,
    estimate_bbox_3d,
    project_points_to_color,
)


COLOR_INTRINSICS = CameraIntrinsics(width=1920, height=1080, fx=1380.0, fy=1380.0, cx=960.0, cy=540.0)
DEPTH_INTRINSICS = CameraIntrinsics(width=640, height=480, fx=385.0, fy=385.0, cx=320.0, cy=240.0)


def _render_synthetic_scene(
    target_center_color: tuple[float, float, float],
    target_size_xy: tuple[float, float],
    background_z_m: float,
    extrinsics: Extrinsics,
    *,
    color_intrinsics: CameraIntrinsics = COLOR_INTRINSICS,
    dtype=np.uint16,
    split_half_wall: bool = False,
) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Render a 640x480 depth image of a target plate in front of a background plane.

    When `split_half_wall=True`, the target only covers the left half of the bbox while
    the right half of the bbox exposes `background_z_m` (50% target / 50% wall).
    """
    tx, ty, tz = target_center_color
    half_w, half_h = target_size_xy[0] / 2.0, target_size_xy[1] / 2.0

    u_d, v_d = np.meshgrid(
        np.arange(DEPTH_INTRINSICS.width, dtype=np.float64),
        np.arange(DEPTH_INTRINSICS.height, dtype=np.float64),
    )
    ray_d = np.stack((
        (u_d - DEPTH_INTRINSICS.cx) / DEPTH_INTRINSICS.fx,
        (v_d - DEPTH_INTRINSICS.cy) / DEPTH_INTRINSICS.fy,
        np.ones_like(u_d),
    ), axis=-1)

    r2 = extrinsics.rotation[2]
    denom_t = ray_d @ r2
    z_d_target = (tz - extrinsics.translation[2]) / denom_t
    p_d_target = ray_d * z_d_target[..., None]
    p_c_target = p_d_target @ extrinsics.rotation.T + extrinsics.translation

    x_max = tx if split_half_wall else tx + half_w
    on_target = (
        (z_d_target > 0.05)
        & (p_c_target[..., 0] >= tx - half_w)
        & (p_c_target[..., 0] <= x_max)
        & (np.abs(p_c_target[..., 1] - ty) <= half_h)
    )

    z_d_bg = (background_z_m - extrinsics.translation[2]) / denom_t
    depth_m = np.where(on_target, z_d_target, z_d_bg)

    if dtype == np.uint16:
        depth_img = np.rint(depth_m * 1000.0).astype(np.uint16)
    else:
        depth_img = depth_m.astype(dtype)

    corners = np.array([
        [tx - half_w, ty - half_h, tz],
        [tx + half_w, ty - half_h, tz],
        [tx - half_w, ty + half_h, tz],
        [tx + half_w, ty + half_h, tz],
    ], dtype=np.float64)
    u_c, v_c = project_points_to_color(corners, color_intrinsics)
    bbox = (float(np.min(u_c)), float(np.min(v_c)), float(np.max(u_c)), float(np.max(v_c)))
    return depth_img, bbox


def test_estimate_bbox_3d_accurate_with_15mm_baseline_and_rotation():
    yaw, pitch = np.deg2rad(0.8), np.deg2rad(-0.5)
    rot = np.array([
        [np.cos(yaw), 0.0, np.sin(yaw)],
        [0.0, 1.0, 0.0],
        [-np.sin(yaw), 0.0, np.cos(yaw)],
    ]) @ np.array([
        [1.0, 0.0, 0.0],
        [0.0, np.cos(pitch), -np.sin(pitch)],
        [0.0, np.sin(pitch), np.cos(pitch)],
    ])
    extrinsics = Extrinsics(rotation=rot, translation=np.array([-0.015, 0.001, 0.002]))
    true_xyz = (0.14, 0.04, 0.85)
    depth_mm, bbox = _render_synthetic_scene(true_xyz, (0.12, 0.14), background_z_m=2.40, extrinsics=extrinsics)

    result = estimate_bbox_3d(bbox, depth_mm, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics)

    assert result is not None
    assert result.valid_points >= 50
    assert abs(result.x - true_xyz[0]) < 0.003
    assert abs(result.y - true_xyz[1]) < 0.003
    assert abs(result.z - true_xyz[2]) < 0.003


def test_estimate_bbox_3d_50_percent_figurine_and_50_percent_wall():
    extrinsics = Extrinsics(rotation=np.eye(3), translation=np.array([-0.015, 0.0, 0.0]))
    # Bbox spans [-0.08, +0.08] in X; figurine occupies [-0.08, 0.0], wall at Z=1.8m occupies [0.0, +0.08].
    depth_mm, bbox = _render_synthetic_scene(
        (0.0, 0.0, 1.00), (0.16, 0.16), background_z_m=1.80,
        extrinsics=extrinsics, split_half_wall=True,
    )

    result = estimate_bbox_3d(bbox, depth_mm, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics)

    assert result is not None
    assert result.valid_points >= 10
    assert abs(result.z - 1.00) < 0.01
    # Must fall cleanly inside the figurine [-0.08, 0.0], not pulled into the wall.
    assert -0.08 <= result.x <= 0.0
    assert abs(result.y - 0.0) < 0.01


def test_estimate_bbox_3d_handles_distortion_near_frame_edge():
    distorted_color = CameraIntrinsics(
        width=1920, height=1080, fx=1380.0, fy=1380.0, cx=960.0, cy=540.0,
        distortion=(-0.28, 0.09, 0.002, -0.002, -0.01),
    )
    extrinsics = Extrinsics(rotation=np.eye(3), translation=np.array([-0.015, 0.002, 0.0]))
    # Place target near the right/bottom edge where radial & tangential distortion shift pixels significantly.
    true_xyz = (0.48, 0.24, 1.05)
    depth_mm, bbox = _render_synthetic_scene(
        true_xyz, (0.14, 0.14), background_z_m=2.50,
        extrinsics=extrinsics, color_intrinsics=distorted_color,
    )

    result = estimate_bbox_3d(bbox, depth_mm, distorted_color, DEPTH_INTRINSICS, extrinsics)

    assert result is not None
    assert result.valid_points >= 10
    assert abs(result.x - true_xyz[0]) < 0.005
    assert abs(result.y - true_xyz[1]) < 0.005
    assert abs(result.z - true_xyz[2]) < 0.005


def test_estimate_bbox_3d_returns_none_on_empty_or_too_few_points():
    extrinsics = Extrinsics.identity()
    zeros = np.zeros((480, 640), dtype=np.uint16)
    assert estimate_bbox_3d((800, 400, 1000, 600), zeros, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics) is None

    nans = np.full((480, 640), np.nan, dtype=np.float32)
    assert estimate_bbox_3d((800, 400, 1000, 600), nans, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics) is None

    # Out-of-range depth (> 3.0 m)
    too_far = np.full((480, 640), 3500, dtype=np.uint16)
    assert estimate_bbox_3d((800, 400, 1000, 600), too_far, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics) is None

    # Fewer than 10 valid points
    sparse = np.zeros((480, 640), dtype=np.uint16)
    sparse[240, 320:324] = 1000
    assert estimate_bbox_3d((920, 500, 1020, 580), sparse, COLOR_INTRINSICS, DEPTH_INTRINSICS, extrinsics) is None


def test_victim_3d_filter_confirms_three_close_points_and_resets_on_outlier_or_age():
    filt = Victim3DFilter(confirm_count=3, max_spread_m=0.15, max_age_sec=1.0)

    assert filt.observe((0.10, 0.05, 1.00), 1.0) is None
    assert filt.observe((0.12, 0.04, 1.02), 1.2) is None
    confirmed = filt.observe(DepthPointResult(0.11, 0.06, 1.01, valid_points=30, depth_roi=(0, 0, 10, 10)), 1.4)
    assert confirmed is not None
    assert abs(confirmed[0] - 0.11) < 1e-6
    assert abs(confirmed[1] - 0.05) < 1e-6
    assert abs(confirmed[2] - 1.01) < 1e-6

    # Sudden jump > max_spread_m resets the streak
    assert filt.observe((0.80, 0.05, 1.80), 1.5) is None
    assert filt.observe((0.81, 0.04, 1.81), 1.6) is None
    assert filt.observe((0.79, 0.06, 1.79), 1.7) == pytest.approx((0.80, 0.05, 1.80))

    # Empty observation or age > max_age_sec resets the streak
    assert filt.observe(None, 1.8) is None
    assert filt.observe((0.10, 0.05, 1.00), 2.0) is None
    assert filt.observe((0.10, 0.05, 1.00), 2.2) is None
    assert filt.observe((0.10, 0.05, 1.00), 3.5) is None  # old samples aged out (>1.0s)
