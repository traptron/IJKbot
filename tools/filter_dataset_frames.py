#!/usr/bin/env python3
"""Filter and deduplicate stationary-camera dataset frames using pixel-change thresholds."""

import argparse
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}


def _prep_gray(path: Path, target_width: int = 320) -> np.ndarray | None:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None or gray.size == 0:
        return None
    h, w = gray.shape[:2]
    if w != target_width and w > 0:
        target_height = max(1, round(h * target_width / w))
        gray = cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(gray, (5, 5), 0)


def _change_pct(a: np.ndarray, b: np.ndarray, pixel_diff: int) -> float:
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(a, b)
    return 100.0 * float(np.count_nonzero(diff >= pixel_diff)) / float(diff.size)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Input directory with .jpg/.png frames')
    parser.add_argument('--output', type=Path, required=True, help='Output directory for filtered frames')
    parser.add_argument('--min-change-pct', type=float, default=0.3,
                        help='Minimum changed pixel percentage vs last kept frame (default: 0.3)')
    parser.add_argument('--pixel-diff', type=int, default=18,
                        help='Absolute grayscale intensity difference threshold 0..255 (default: 18)')
    parser.add_argument('--max-motion-pct', type=float, default=12.0,
                        help='Maximum changed pixel percentage vs previous frame; 0 disables (default: 12.0)')
    parser.add_argument('--max-frames', type=int, default=0,
                        help='Optional maximum output frames via uniform subsampling (0 = unlimited)')
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f'Input directory not found: {args.input}', file=sys.stderr)
        return 1
    if not 0 <= args.pixel_diff <= 255:
        parser.error('--pixel-diff must be in 0..255')
    if args.min_change_pct < 0 or args.max_motion_pct < 0 or args.max_frames < 0:
        parser.error('Thresholds and --max-frames must be non-negative')

    paths = sorted(
        p for p in args.input.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not paths:
        print(f'No .jpg/.png images found in {args.input}', file=sys.stderr)
        return 1

    kept: list[Path] = []
    prev_seq_gray: np.ndarray | None = None
    last_kept_gray: np.ndarray | None = None
    rejected_dup = 0
    rejected_motion = 0
    unreadable = 0

    for path in paths:
        gray = _prep_gray(path)
        if gray is None:
            unreadable += 1
            continue

        if prev_seq_gray is not None and args.max_motion_pct > 0:
            motion_pct = _change_pct(gray, prev_seq_gray, args.pixel_diff)
            if motion_pct > args.max_motion_pct:
                rejected_motion += 1
                prev_seq_gray = gray
                continue

        if last_kept_gray is not None:
            change_pct = _change_pct(gray, last_kept_gray, args.pixel_diff)
            if change_pct < args.min_change_pct:
                rejected_dup += 1
                prev_seq_gray = gray
                continue

        kept.append(path)
        last_kept_gray = gray
        prev_seq_gray = gray

    selected = kept
    if args.max_frames > 0 and len(kept) > args.max_frames:
        indices = np.linspace(0, len(kept) - 1, args.max_frames, dtype=int)
        selected = [kept[int(i)] for i in indices]

    args.output.mkdir(parents=True, exist_ok=True)
    for src in selected:
        shutil.copy2(src, args.output / src.name)

    extra = f', unreadable={unreadable}' if unreadable else ''
    sub_info = f' (subsampled from {len(kept)})' if len(selected) != len(kept) else ''
    print(
        f'{args.input} -> {args.output}: total={len(paths)}, '
        f'rejected_dup={rejected_dup}, rejected_motion={rejected_motion}{extra}, '
        f'saved={len(selected)}{sub_info}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
