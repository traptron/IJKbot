#!/usr/bin/env python3
"""Measure received JPEG FPS, payload bandwidth and resolution without saving frames."""
import argparse
import json
import time

import cv2
import numpy as np
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--topic', default='/camera/color/image_raw/compressed')
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    rclpy.init()
    node = rclpy.create_node('video_measurement')
    count, total, first, last, latest = 0, 0, None, None, None

    def receive(message: CompressedImage) -> None:
        nonlocal count, total, first, last, latest
        last = time.monotonic()
        if first is None:
            first = last
        count += 1
        total += len(message.data)
        latest = message

    node.create_subscription(CompressedImage, args.topic, receive,
                             QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    deadline = time.monotonic() + 20 + args.seconds
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if first is not None and time.monotonic() - first >= args.seconds:
                break
        if count < 2:
            raise RuntimeError('Fewer than two JPEG frames received')
        elapsed = last - first
        image = cv2.imdecode(np.frombuffer(bytes(latest.data), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError('Received JPEG is corrupt')
        print(json.dumps({'frames': count, 'fps': (count - 1) / elapsed,
                          'mean_jpeg_bytes': total / count,
                          'jpeg_payload_mbps': (total / count) * (count - 1) / elapsed * 8 / 1e6,
                          'width': image.shape[1], 'height': image.shape[0]}, indent=2))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
