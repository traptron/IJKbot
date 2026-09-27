#!/usr/bin/env python3
"""Stream JPEG frames from the Pi's OV5647 RAW10 V4L2 camera to stdout."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'vision'))

from vision.csi_capture import RAW_FRAME_BYTES, raw10_to_jpeg


def main() -> None:
    capture = subprocess.Popen([
        'v4l2-ctl', '-d', '/dev/video0', '--stream-mmap=4',
        '--stream-to=/dev/stdout',
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            raw = capture.stdout.read(RAW_FRAME_BYTES)
            if len(raw) != RAW_FRAME_BYTES:
                break
            sys.stdout.buffer.write(raw10_to_jpeg(raw, 85))
            sys.stdout.buffer.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        capture.terminate()
        try:
            capture.wait(timeout=2)
        except subprocess.TimeoutExpired:
            capture.kill()
            capture.wait()


if __name__ == '__main__':
    main()
