"""Offline RAW10/JPEG parity and throughput regression against the Python path.

Run after colcon build, with the vision Python package on PYTHONPATH.
No ROS nodes or real camera are required.
"""
import argparse
import json
import subprocess
import time

import cv2
import numpy as np

from vision.csi_capture import MjpegFramer, raw10_to_jpeg
from vision.qr_decoder import decode_jpeg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable')
    args = parser.parse_args()
    cv2.setNumThreads(1)
    frames: list[bytes] = []
    labels: list[str] = []
    for side in (80, 150, 350):
        for white in (80, 255):
            text = 'IJKbot patient'
            qr = cv2.QRCodeEncoder_create().encode(text)
            qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
            qr = cv2.resize(qr, (side, side), interpolation=cv2.INTER_NEAREST)
            image = np.full((480, 640), white, dtype=np.uint8)
            image[40:40 + side, 40:40 + side] = np.rint(qr * ((white - 10) / 255.0) + 10).astype(np.uint8)
            # Achromatic Bayer samples exercise exactly the production RAW10 route.
            packed = np.zeros((480, 160, 5), dtype=np.uint8)
            packed[:, :, :4] = image.reshape(480, 160, 4)
            frames.append(packed.tobytes())
            labels.append(text)
    # Coloured/noisy scene catches LUT rounding and measures entropy savings.
    random = np.random.default_rng(42).integers(0, 256, (480, 160, 5), dtype=np.uint8)
    frames.append(random.tobytes())
    start = time.perf_counter()
    old = [raw10_to_jpeg(raw, 85) for raw in frames]
    python_seconds = time.perf_counter() - start
    start = time.perf_counter()
    result = subprocess.run([args.executable, '--raw-stdin'], input=b''.join(frames),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    native_seconds = time.perf_counter() - start
    framer = MjpegFramer()
    new = framer.feed(result.stdout)
    assert len(new) == len(old)
    max_error = 0
    decoded_count = 0
    for index, (before, after) in enumerate(zip(old, new)):
        a = cv2.imdecode(np.frombuffer(before, np.uint8), cv2.IMREAD_COLOR)
        b = cv2.imdecode(np.frombuffer(after, np.uint8), cv2.IMREAD_COLOR)
        error = int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max())
        max_error = max(max_error, error)
        assert error == 0, f'Frame {index}: decoded pixel difference {error}'
        if index < len(labels):
            before_qr, after_qr = decode_jpeg(before), decode_jpeg(after)
            assert bool(before_qr) == bool(after_qr), f'QR regression on frame {index}'
            if before_qr:
                assert before_qr.text == after_qr.text == labels[index]
                decoded_count += 1
    bad = subprocess.run([args.executable, '--raw-stdin'], input=frames[0][:-1],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert bad.returncode != 0
    assert decoded_count >= 4
    print(json.dumps({'frames': len(frames), 'qr_cases_without_regression': len(labels),
                      'qr_decoded_by_both': decoded_count,
                      'max_pixel_difference': max_error, 'python_seconds': python_seconds,
                      'native_seconds_including_startup': native_seconds,
                      'legacy_jpeg_bytes': sum(map(len, old)),
                      'native_jpeg_bytes': sum(map(len, new))}, indent=2))


if __name__ == '__main__':
    main()
