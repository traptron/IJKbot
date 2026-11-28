#!/usr/bin/env python3
"""Capture 1920x1080@15 FPS RGB frames from D435 via pyrealsense2 or OpenCV for dataset labeling."""

import argparse
from pathlib import Path
import sys
from time import monotonic
from typing import Iterator

import cv2
import numpy as np


def _opencv_api_pref() -> int:
    return cv2.CAP_AVFOUNDATION if sys.platform == 'darwin' else cv2.CAP_ANY


def _list_opencv_cameras(max_index: int = 8) -> int:
    api = _opencv_api_pref()
    found = 0
    print(f'Probing OpenCV cameras (0..{max_index - 1}, api={api}):')
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, api)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        shape_info = f'{frame.shape[1]}x{frame.shape[0]}' if ok and frame is not None else 'no-frame'
        print(f'  [{idx}] opened (reported {w}x{h} @ {fps:.2f} FPS, frame={shape_info})')
        cap.release()
        found += 1
    if found == 0:
        print('  No OpenCV cameras detected.')
    return 0


def _iter_realsense_frames() -> tuple[str, Iterator[np.ndarray]]:
    import pyrealsense2 as rs

    if len(rs.context().query_devices()) == 0:
        raise RuntimeError('No Intel RealSense D435 device detected over USB.')

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 1920, 1080, rs.format.bgr8, 15)
    profile = pipeline.start(config)
    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
    intr = color_stream.get_intrinsics()
    stream_info = f'realsense actual={intr.width}x{intr.height} @ {color_stream.fps()} FPS'

    def _gen() -> Iterator[np.ndarray]:
        try:
            while True:
                frames = pipeline.wait_for_frames(timeout_ms=5000)
                color_frame = frames.get_color_frame()
                if color_frame:
                    yield np.asanyarray(color_frame.get_data())
        finally:
            pipeline.stop()

    return stream_info, _gen()


def _iter_opencv_frames(camera_index: int) -> tuple[str, Iterator[np.ndarray]]:
    api = _opencv_api_pref()
    cap = cv2.VideoCapture(camera_index, api)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f'Failed to open OpenCV camera index {camera_index} (api={api}).')

    # Set FPS first so AVFoundation picks 15 FPS instead of falling back to 6 FPS.
    cap.set(cv2.CAP_PROP_FPS, 15)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    ok, first_frame = cap.read()
    if not ok or first_frame is None:
        cap.release()
        raise RuntimeError(f'Camera index {camera_index} opened, but failed to read initial frame.')

    actual_h, actual_w = first_frame.shape[:2]
    actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
    stream_info = f'opencv[{camera_index}] actual={actual_w}x{actual_h} @ {actual_fps:.2f} FPS'
    if (actual_w, actual_h) != (1920, 1080):
        print(f'[WARN] Requested 1920x1080, got {actual_w}x{actual_h}. Check --camera-index.',
              file=sys.stderr)

    def _gen() -> Iterator[np.ndarray]:
        try:
            yield first_frame
            while True:
                ok_next, frame = cap.read()
                if not ok_next or frame is None:
                    break
                yield frame
        finally:
            cap.release()

    return stream_info, _gen()


def _open_stream(backend: str, camera_index: int) -> tuple[str, Iterator[np.ndarray]]:
    if backend == 'realsense':
        try:
            return _iter_realsense_frames()
        except ImportError as exc:
            raise RuntimeError(f'pyrealsense2 is required for --backend realsense: {exc}') from exc
    if backend == 'opencv':
        return _iter_opencv_frames(camera_index)

    # backend == 'auto'
    try:
        import pyrealsense2 as _rs  # noqa: F401
    except ImportError:
        print('pyrealsense2 unavailable; falling back to OpenCV capture.')
        return _iter_opencv_frames(camera_index)
    return _iter_realsense_frames()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=False,
                        help='Output directory (e.g. datasets/polygon/pos)')
    parser.add_argument('--backend', choices=['auto', 'realsense', 'opencv'], default='auto',
                        help='Capture backend (default: auto)')
    parser.add_argument('--camera-index', type=int, default=0,
                        help='Camera index for OpenCV backend (default: 0)')
    parser.add_argument('--list-cameras', action='store_true',
                        help='List available OpenCV camera indices and exit')
    parser.add_argument('--save-hz', type=float, default=2.5,
                        help='Target save rate in frames/sec (default: 2.5)')
    parser.add_argument('--min-blur', type=float, default=25.0,
                        help='Minimum Laplacian variance to save a frame (0 disables filtering; default: 25.0)')
    parser.add_argument('--jpeg-quality', type=int, default=95, help='JPEG quality (1-100)')
    parser.add_argument('--prefix', default='d435', help='Saved filename prefix')
    parser.add_argument('--max-frames', type=int, default=0, help='Optional limit on saved frames (0 = unlimited)')
    parser.add_argument('--no-preview', action='store_true', help='Run headless without OpenCV preview window')
    args = parser.parse_args()

    if args.list_cameras:
        return _list_opencv_cameras()

    if args.out is None:
        parser.error('--out is required unless --list-cameras is specified')
    if args.save_hz <= 0:
        parser.error('--save-hz must be positive')

    try:
        stream_info, frame_iter = _open_stream(args.backend, args.camera_index)
    except Exception as exc:
        print(f'Failed to open camera stream: {exc}', file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    save_period = 1.0 / args.save_hz
    next_save_at = monotonic()
    paused = False
    saved = 0
    skipped_blur = 0
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]

    print(f'Capturing ({stream_info}) -> {args.out} (save_hz={args.save_hz}, min_blur={args.min_blur})')
    if not args.no_preview:
        print('Controls: [Space] pause/resume, [q] quit')

    try:
        for frame in frame_iter:
            now = monotonic()
            lap_var = None
            if not paused and now >= next_save_at:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if args.min_blur > 0 and lap_var < args.min_blur:
                    skipped_blur += 1
                else:
                    out_path = args.out / f'{args.prefix}_{saved:06d}.jpg'
                    cv2.imwrite(str(out_path), frame, encode_params)
                    saved += 1
                    next_save_at = now + save_period
                    if args.max_frames > 0 and saved >= args.max_frames:
                        break

            if not args.no_preview:
                vis = cv2.resize(frame, (960, 540))
                state_txt = 'PAUSED' if paused else 'REC'
                blur_txt = f' | lap={lap_var:.1f}' if lap_var is not None else ''
                cv2.putText(
                    vis,
                    f'{state_txt} | saved={saved} | blur_skip={skipped_blur}{blur_txt}',
                    (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 200, 255) if paused else (0, 255, 0), 2,
                )
                cv2.imshow('D435 Dataset Capture (Space: pause, q: quit)', vis)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    break
                if key == ord(' '):
                    paused = not paused
    except KeyboardInterrupt:
        pass
    finally:
        if not args.no_preview:
            cv2.destroyAllWindows()

    print(f'Done: saved={saved}, skipped_blur={skipped_blur} -> {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
