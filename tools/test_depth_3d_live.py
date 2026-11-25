#!/usr/bin/env python3
"""Interactive live verification of unaligned D435 3D bbox localization without ROS 2."""

import argparse
from pathlib import Path
import sys
from time import monotonic

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'vision'))
from vision.core.depth_3d import (  # noqa: E402
    CameraIntrinsics,
    Extrinsics,
    Victim3DFilter,
    estimate_bbox_3d,
)

PREVIEW_W = 960
PREVIEW_H = 540
WIN_NAME = 'D435 Live 3D Check (r: ROI, c: clear, q: quit)'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-count', type=int, default=3)
    parser.add_argument('--max-spread', type=float, default=0.15)
    parser.add_argument('--max-age', type=float, default=1.0)
    parser.add_argument('--inner-margin', type=float, default=0.20)
    parser.add_argument('--z-percentile', type=float, default=20.0)
    parser.add_argument('--z-band', type=float, default=0.05)
    parser.add_argument('--min-points', type=int, default=10)
    parser.add_argument('--stride', type=int, default=1)
    args = parser.parse_args()

    try:
        import pyrealsense2 as rs
    except ImportError as exc:
        print(f'pyrealsense2 is required for live D435 check: {exc}', file=sys.stderr)
        return 1

    if len(rs.context().query_devices()) == 0:
        print('No Intel RealSense D435 device detected over USB.', file=sys.stderr)
        return 1

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 1920, 1080, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)

    try:
        profile = pipeline.start(config)
    except Exception as exc:
        print(f'Failed to start D435 streams: {exc}', file=sys.stderr)
        return 1

    depth_sensor = profile.get_device().first_depth_sensor()
    depth_scale = float(depth_sensor.get_depth_scale())

    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
    depth_stream = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    ci = color_stream.get_intrinsics()
    di = depth_stream.get_intrinsics()

    color_intr = CameraIntrinsics(
        width=ci.width,
        height=ci.height,
        fx=ci.fx,
        fy=ci.fy,
        cx=ci.ppx,
        cy=ci.ppy,
        distortion=tuple(ci.coeffs),
    )
    depth_intr = CameraIntrinsics(
        width=di.width,
        height=di.height,
        fx=di.fx,
        fy=di.fy,
        cx=di.ppx,
        cy=di.ppy,
    )

    ext = depth_stream.get_extrinsics_to(color_stream)
    rot = np.array(ext.rotation, dtype=np.float64).reshape((3, 3), order='F')
    extrinsics = Extrinsics(
        rotation=rot,
        translation=np.array(ext.translation, dtype=np.float64),
    )

    sx = color_intr.width / PREVIEW_W
    sy = color_intr.height / PREVIEW_H
    bbox_full: tuple[float, float, float, float] | None = None
    filt = Victim3DFilter(
        confirm_count=args.confirm_count,
        max_spread_m=args.max_spread,
        max_age_sec=args.max_age,
    )

    print(f'Started unaligned D435: color={ci.width}x{ci.height}, depth={di.width}x{di.height}, '
          f'depth_scale={depth_scale:.6f}, t={extrinsics.translation.round(4).tolist()}')
    print('Controls: [r] select ROI | [c] clear ROI & filter | [q] quit')

    try:
        while True:
            frames = pipeline.wait_for_frames(timeout_ms=5000)
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if not color_frame or not depth_frame:
                continue

            color_bgr = np.asanyarray(color_frame.get_data())
            depth_raw = np.asanyarray(depth_frame.get_data())
            vis = cv2.resize(color_bgr, (PREVIEW_W, PREVIEW_H))

            if bbox_full is not None:
                x1, y1, x2, y2 = bbox_full
                mx = (x2 - x1) * args.inner_margin
                my = (y2 - y1) * args.inner_margin
                cv2.rectangle(
                    vis,
                    (round(x1 / sx), round(y1 / sy)),
                    (round(x2 / sx), round(y2 / sy)),
                    (255, 200, 0),
                    2,
                )
                cv2.rectangle(
                    vis,
                    (round((x1 + mx) / sx), round((y1 + my) / sy)),
                    (round((x2 - mx) / sx), round((y2 - my) / sy)),
                    (0, 220, 255),
                    1,
                )

                res = estimate_bbox_3d(
                    bbox_full,
                    depth_raw,
                    color_intr,
                    depth_intr,
                    extrinsics,
                    depth_scale=depth_scale,
                    inner_margin_ratio=args.inner_margin,
                    z_percentile=args.z_percentile,
                    z_band_m=args.z_band,
                    min_valid_points=args.min_points,
                    sample_stride=args.stride,
                )
                confirmed = filt.observe(res, monotonic())
                if confirmed is not None and res is not None:
                    cx, cy, cz = confirmed
                    txt = (f'CONFIRMED | X={cx:+.3f} Y={cy:+.3f} Z={cz:.3f} m '
                           f'| pts={res.valid_points}')
                    color = (0, 255, 0)
                elif res is not None:
                    txt = (f'PENDING   | X={res.x:+.3f} Y={res.y:+.3f} Z={res.z:.3f} m '
                           f'| pts={res.valid_points}')
                    color = (0, 215, 255)
                else:
                    txt = 'PENDING   | no valid 3D points'
                    color = (0, 0, 255)
            else:
                txt = 'Press [r] select ROI | [c] clear | [q] quit'
                color = (220, 220, 220)

            cv2.putText(vis, txt, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 4)
            cv2.putText(vis, txt, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
            cv2.imshow(WIN_NAME, vis)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            if key == ord('c'):
                bbox_full = None
                filt.reset()
            elif key == ord('r'):
                rx, ry, rw, rh = cv2.selectROI(WIN_NAME, vis, fromCenter=False, showCrosshair=True)
                if rw > 0 and rh > 0:
                    bbox_full = (rx * sx, ry * sy, (rx + rw) * sx, (ry + rh) * sy)
                    filt.reset()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
