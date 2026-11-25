#!/usr/bin/env python3
"""Offline Orin benchmark: export local YOLO .pt weights to FP16 TensorRT and measure latency."""

import argparse
from pathlib import Path
import sys
from time import perf_counter

import numpy as np


def _benchmark_model(
    yolo_cls,
    weights_path: Path,
    imgsz: int,
    device: str,
    warmup: int,
    iters: int,
    out_dir: Path,
) -> None:
    print(f'\n=== {weights_path} (imgsz={imgsz}, FP16 TensorRT) ===')
    if not weights_path.is_file():
        print(f'[FAIL] Local weights file not found (offline mode, skipping download): {weights_path}',
              file=sys.stderr)
        return
    try:
        model = yolo_cls(str(weights_path))
        t_exp0 = perf_counter()
        exported_path = model.export(
            format='engine',
            imgsz=imgsz,
            half=True,
            device=device,
            project=str(out_dir),
        )
        export_sec = perf_counter() - t_exp0
        print(f'Exported: {exported_path} in {export_sec:.1f}s')

        engine_model = yolo_cls(str(exported_path), task='detect')
    except Exception as exc:
        print(f'[FAIL] {weights_path}: {exc}', file=sys.stderr)
        return

    dummy = np.random.randint(0, 255, (imgsz, imgsz, 3), dtype=np.uint8)
    for _ in range(warmup):
        engine_model.predict(dummy, imgsz=imgsz, verbose=False)

    lat_ms = []
    for _ in range(iters):
        t0 = perf_counter()
        engine_model.predict(dummy, imgsz=imgsz, verbose=False)
        lat_ms.append((perf_counter() - t0) * 1000.0)

    arr = np.asarray(lat_ms, dtype=np.float64)
    med = float(np.median(arr))
    p95 = float(np.percentile(arr, 95))
    mean = float(np.mean(arr))
    print(f'Latency ({iters} iters): median={med:.2f} ms, p95={p95:.2f} ms, '
          f'mean={mean:.2f} ms (~{1000.0 / med:.1f} FPS)')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, default=None,
                        help='Single local .pt weights file to export and benchmark offline (e.g. models/yolo11n.pt)')
    parser.add_argument('--models', nargs='+', default=['yolo11n.pt', 'yolo26n.pt'],
                        help='List of local .pt paths when --weights is not specified')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--device', default='0', help='CUDA device index (default: 0)')
    parser.add_argument('--warmup', type=int, default=20)
    parser.add_argument('--iters', type=int, default=100)
    parser.add_argument('--out-dir', type=Path, default=Path('/tmp/ijk_yolo_trt_bench'))
    args = parser.parse_args()

    try:
        import tensorrt as trt
    except ImportError as exc:
        print(
            f'TensorRT Python bindings not found ({exc}).\n'
            'Hint: on Jetson Orin check system Python (/usr/bin/python3) or recreate your venv with '
            '--system-site-packages so system tensorrt is visible.',
            file=sys.stderr,
        )
        return 1

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        print(f'Missing dependency for benchmark: {exc}', file=sys.stderr)
        return 1

    print(f'tensorrt={getattr(trt, "__version__", "unknown")}, torch={torch.__version__}, '
          f'cuda_available={torch.cuda.is_available()}')
    if not torch.cuda.is_available():
        print('CUDA is unavailable on this host; run this script on Jetson Orin.', file=sys.stderr)
        return 2

    targets = [args.weights] if args.weights is not None else [Path(m) for m in args.models]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for weights_path in targets:
        _benchmark_model(YOLO, weights_path, args.imgsz, args.device, args.warmup, args.iters, args.out_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
