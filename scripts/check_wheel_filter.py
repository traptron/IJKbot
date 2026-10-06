#!/usr/bin/env python3
"""Read-only check of paired lidar scans; never publishes motion or test scans."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--config', default=str(
        Path(__file__).resolve().parents[1] / 'src/bringup/config/lidar_self_filter.yaml'))
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error('seconds must be in (0, 60]')
    config = yaml.safe_load(Path(args.config).read_text())['scan_to_scan_filter_chain']['ros__parameters']
    boxes = [item['params'] for name, item in config.items()
             if name.startswith('filter') and isinstance(item.get('params'), dict) and 'min_x' in item['params']]
    rclpy.init(args=[])
    node = rclpy.create_node('wheel_filter_check')
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    pending = [{}, {}]
    totals = Counter({name: 0 for name in (
        'paired_scans', 'wheel_raw', 'wheel_removed', 'wheel_remaining',
        'outside_raw', 'outside_removed', 'tf_unavailable')})
    clusters = Counter()

    def received(which, scan):
        key = (scan.header.stamp.sec, scan.header.stamp.nanosec)
        pending[which][key] = scan
        while len(pending[which]) > 30:
            del pending[which][next(iter(pending[which]))]
        if key not in pending[1 - which]:
            return
        raw, filtered = pending[0].pop(key), pending[1].pop(key)
        try:
            transform = buffer.lookup_transform('base_footprint', raw.header.frame_id,
                                                rclpy.time.Time()).transform
        except Exception:
            totals['tf_unavailable'] += 1
            return
        q, t = transform.rotation, transform.translation
        totals['paired_scans'] += 1
        for index, (before, after) in enumerate(zip(raw.ranges, filtered.ranges)):
            if not math.isfinite(before) or not raw.range_min <= before <= raw.range_max:
                continue
            angle = raw.angle_min + index * raw.angle_increment
            px, py = before * math.cos(angle), before * math.sin(angle)
            # Quaternion rotation of a planar endpoint, followed by translation.
            x = t.x + (1 - 2 * (q.y*q.y + q.z*q.z))*px + 2*(q.x*q.y - q.z*q.w)*py
            y = t.y + 2*(q.x*q.y + q.z*q.w)*px + (1 - 2*(q.x*q.x + q.z*q.z))*py
            z = t.z + 2*(q.x*q.z - q.y*q.w)*px + 2*(q.y*q.z + q.x*q.w)*py
            inside = any(b['min_x'] < x < b['max_x'] and b['min_y'] < y < b['max_y']
                         and b['min_z'] < z < b['max_z'] for b in boxes) or (before < 0.18)
            removed = not math.isfinite(after)
            totals['wheel_raw' if inside else 'outside_raw'] += 1
            if inside and not removed:
                totals['wheel_remaining'] += 1
            if removed:
                totals['wheel_removed' if inside else 'outside_removed'] += 1
            if not removed and -0.25 < x < 0.15 and abs(y) < 0.18:
                clusters[(round(x, 2), round(y, 2), round(z, 2))] += 1

    subscriptions = [node.create_subscription(LaserScan, topic,
                     lambda scan, i=i: received(i, scan), qos_profile_sensor_data)
                     for i, topic in enumerate(('/scan_raw', '/scan'))]
    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        print(json.dumps({'counts': dict(totals), 'near_robot_remaining': [
            {'xyz': point, 'count': count} for point, count in clusters.most_common(12)]}, indent=2))
    finally:
        del subscriptions, listener
        node.destroy_node()
        rclpy.shutdown()
    return 0 if (totals['paired_scans'] and not totals['wheel_remaining']
                 and not totals['outside_removed']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
