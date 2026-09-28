"""Read-only, on-robot measurement of the independent QR and preview streams."""
import argparse
import json
import time

import cv2
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=10)
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error('seconds must be in (0, 60]')
    rclpy.init(args=[])
    node = rclpy.create_node('qr_stream_measurement')
    samples = {}

    def received(topic, message):
        sample = samples.setdefault(topic, {'times': [], 'bytes': 0, 'dimensions': None})
        sample['times'].append(time.monotonic())
        sample['bytes'] += len(message.data)
        if sample['dimensions'] is None:
            image = cv2.imdecode(np.frombuffer(bytes(message.data), np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                sample['dimensions'] = [image.shape[1], image.shape[0]]

    subscriptions = [node.create_subscription(
        CompressedImage, topic, lambda msg, topic=topic: received(topic, msg), qos_profile_sensor_data)
        for topic in ('/camera/qr/image/compressed', '/camera/color/image_raw/compressed')]
    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        report = {}
        for topic, sample in samples.items():
            times = sample['times']
            intervals = [b - a for a, b in zip(times, times[1:])]
            report[topic] = {
                'frames': len(times), 'dimensions': sample['dimensions'],
                'fps': round(len(intervals) / sum(intervals), 2) if intervals else 0,
                'max_gap_sec': round(max(intervals), 3) if intervals else None,
                'mean_jpeg_bytes': sample['bytes'] // len(times),
            }
        print(json.dumps(report, indent=2))
    finally:
        del subscriptions
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
