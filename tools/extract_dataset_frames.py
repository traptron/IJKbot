#!/usr/bin/env python3
"""Extract sampled sharp frames from a video (.mp4/.mov) or RealSense .bag for dataset labeling."""

import argparse
from pathlib import Path
import sys
from typing import Iterator

import cv2
import numpy as np


def _iter_video_frames(path: Path) -> tuple[float, Iterator[np.ndarray]]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f'Failed to open video: {path}')
    fps = float(cap.get(cv2.CAP_PROP_FPS))

    def _gen() -> Iterator[np.ndarray]:
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
        finally:
            cap.release()

    return (fps if fps > 0 else 15.0), _gen()


def _iter_bag_frames(path: Path) -> tuple[float, Iterator[np.ndarray]]:
    try:
        import pyrealsense2 as rs
    except ImportError as exc:
        raise RuntimeError(f'pyrealsense2 is required to read .bag files: {exc}') from exc

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device_from_file(str(path), repeat_playback=False)
    config.enable_stream(rs.stream.color)
    profile = pipeline.start(config)
    playback = profile.get_device().as_playback()
    playback.set_real_time(False)
    stream_fps = float(profile.get_stream(rs.stream.color).fps())

    def _gen() -> Iterator[np.ndarray]:
        try:
            while True:
                try:
                    frames = pipeline.wait_for_frames(timeout_ms=2000)
                except RuntimeError:
                    break
                color_frame = frames.get_color_frame()
                if not color_frame:
                    continue
                arr = np.asanyarray(color_frame.get_data())
                if color_frame.get_profile().format() == rs.format.rgb8:
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                yield arr
        finally:
            pipeline.stop()

    return (stream_fps if stream_fps > 0 else 15.0), _gen()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path, help='Input .mp4/.mov video or RealSense .bag recording')
    parser.add_argument('--out', type=Path, required=True, help='Output directory for extracted frames')
    parser.add_argument('--step-sec', type=float, default=0.5,
                        help='Time interval between sampled frames in seconds (default: 0.5)')
    parser.add_argument('--step-frames', type=int, default=None,
                        help='Override --step-sec with a fixed integer frame step')
    parser.add_argument('--blur-threshold', type=float, default=25.0,
                        help='Minimum Laplacian variance to keep a frame (0 disables filtering; default: 25.0)')
    parser.add_argument('--ext', choices=['jpg', 'png'], default='jpg', help='Output image format')
    parser.add_argument('--jpeg-quality', type=int, default=95, help='JPEG quality (1-100)')
    parser.add_argument('--max-frames', type=int, default=0, help='Optional limit on saved frames (0 = unlimited)')
    args = parser.parse_args()

    if not args.video.is_file():
        print(f'Input file not found: {args.video}', file=sys.stderr)
        return 1
    if args.step_frames is not None and args.step_frames < 1:
        parser.error('--step-frames must be >= 1')
    if args.step_sec <= 0:
        parser.error('--step-sec must be positive')

    try:
        if args.video.suffix.lower() == '.bag':
            fps, frame_iter = _iter_bag_frames(args.video)
        else:
            fps, frame_iter = _iter_video_frames(args.video)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    stride = args.step_frames if args.step_frames is not None else max(1, round(args.step_sec * fps))
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.video.stem
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality] if args.ext == 'jpg' else []

    frame_idx = 0
    sampled = 0
    rejected_blur = 0
    saved = 0
    lap_vars = []

    for frame in frame_iter:
        if frame_idx % stride == 0:
            sampled += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            lap_vars.append(lap_var)
            if args.blur_threshold > 0 and lap_var < args.blur_threshold:
                rejected_blur += 1
            else:
                out_path = args.out / f'{stem}_f{frame_idx:06d}.{args.ext}'
                cv2.imwrite(str(out_path), frame, encode_params)
                saved += 1
                if args.max_frames > 0 and saved >= args.max_frames:
                    frame_idx += 1
                    break
        frame_idx += 1

    lap_info = ''
    if lap_vars:
        lap_vars.sort()
        med = lap_vars[len(lap_vars) // 2]
        lap_info = f', lap_var min={lap_vars[0]:.1f} med={med:.1f} max={lap_vars[-1]:.1f}'
    print(f'{args.video.name}: read={frame_idx}, stride={stride} (fps={fps:.2f}), '
          f'sampled={sampled}, rejected_blur={rejected_blur}, saved={saved} -> {args.out}{lap_info}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
