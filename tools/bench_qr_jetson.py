#!/usr/bin/env python3
"""Compare QR decoding configurations on a short sequence of camera frames."""

import argparse
from itertools import product
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'vision'))
from vision.core.qr import QrDecoder, image_to_gray  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames', type=Path, help='Directory with JPEG or PNG frames from one scene')
    parser.add_argument('--max-frames', type=int, default=60, help='Evenly sample up to this many frames')
    parser.add_argument('--crop-ratio', type=float, default=0.7)
    args = parser.parse_args()
    if args.max_frames < 1:
        parser.error('--max-frames must be positive')
    paths = sorted(path for path in args.frames.glob('*') if path.suffix.lower() in ('.jpg', '.jpeg', '.png'))
    if not paths:
        parser.error(f'No frames in {args.frames}')
    indexes = np.linspace(0, len(paths) - 1, min(len(paths), args.max_frames), dtype=int)
    parameters = list(product((False, True), repeat=2))
    decoders = [QrDecoder(try_harder=harder, use_center_crop=crop, center_crop_ratio=args.crop_ratio)
                for harder, crop in parameters]
    timings: list[list[float]] = [[] for _ in decoders]
    grayscale_ms: list[float] = []
    hits = [0 for _ in decoders]
    resolutions = set()

    for frame_index, index in enumerate(indexes):
        with Image.open(paths[index]) as source:
            rgb = np.asarray(source.convert('RGB'))
        height, width = rgb.shape[:2]
        resolutions.add(f'{width}x{height}')
        start = perf_counter()
        gray = image_to_gray(rgb, width, height, rgb.strides[0], 'rgb8')
        grayscale_ms.append((perf_counter() - start) * 1000)
        for i, decoder in enumerate(decoders):
            if frame_index == 0:
                decoder.decode(gray)
            start = perf_counter()
            result = decoder.decode(gray)
            timings[i].append((perf_counter() - start) * 1000)
            hits[i] += result is not None

    print(f'{len(indexes)} frames; resolution: {", ".join(sorted(resolutions))}')
    print(f'Grayscale median={np.median(grayscale_ms):.2f} ms p95={np.percentile(grayscale_ms, 95):.2f} ms')
    for (harder, crop), times, count in zip(parameters, timings, hits):
        total = np.asarray(times) + grayscale_ms
        print(f'try_harder={str(harder):<5} center_crop={str(crop):<5} reads={count}/{len(times)}  '
              f'decode median={np.median(times):.2f} ms p95={np.percentile(times, 95):.2f} ms  '
              f'with grayscale p95={np.percentile(total, 95):.2f} ms')


if __name__ == '__main__':
    main()
