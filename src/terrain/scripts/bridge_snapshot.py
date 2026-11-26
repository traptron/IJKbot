#!/usr/bin/env python3
"""Capture the optimized RTAB-Map cloud and freeze a reviewed bridge reference."""

import argparse
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from surface import RESOLUTION, digest, read_reference, yaw_matrix


def alignment(anchors, tolerance):
    visual = np.asarray([pair['rgbd_map'] for pair in anchors], dtype=float)
    arena = np.asarray([pair['map'] for pair in anchors], dtype=float)
    if (visual.shape != arena.shape or len(visual) < 3 or visual.shape[1:] != (3,)
            or not np.isfinite(visual).all() or not np.isfinite(arena).all()
            or np.linalg.matrix_rank(arena[:, :2] - arena[:, :2].mean(axis=0)) != 2):
        raise ValueError('Use three or more non-collinear floor anchors in both maps')
    source = visual - visual.mean(axis=0)
    target = arena - arena.mean(axis=0)
    yaw = np.arctan2(np.sum(source[:, 0]*target[:, 1] - source[:, 1]*target[:, 0]),
                     np.sum(source[:, :2]*target[:, :2]))
    rotation = yaw_matrix(float(yaw))
    offset = arena.mean(axis=0) - rotation @ visual.mean(axis=0)
    if np.max(np.linalg.norm(visual @ rotation.T + offset - arena, axis=1)) > tolerance:
        raise ValueError('Alignment error exceeds calibration. Recheck floor anchors or the SLAM loop')
    return rotation, offset


def polygon_mask(vertices, x, y):
    vertices = np.asarray(vertices, dtype=float)
    if (len(vertices) < 3 or vertices.shape[1:] != (2,) or not np.isfinite(vertices).all()
            or not ((vertices >= 0) & (vertices <= 4)).all()):
        raise ValueError('Provide bridge lane polygons inside the arena')
    inside = np.zeros(x.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(vertices, np.roll(vertices, -1, axis=0)):
        if y2 != y1:
            inside ^= ((y1 > y) != (y2 > y)) & (x < (x2-x1)*(y-y1)/(y2-y1)+x1)
    return inside


def bake(points, review):
    calibration = review['calibration']
    rotation, offset = alignment(review['floor_anchors'], calibration['max_pose_error_m'])
    points = points @ rotation.T + offset
    cells = np.arange(200)
    x, y = np.meshgrid((cells+.5)*RESOLUTION, (cells+.5)*RESOLUTION)
    mask = np.zeros(x.shape, dtype=bool)
    for polygon in review['lane_polygons']:
        mask |= polygon_mask(polygon, x, y)
    deck = np.zeros(x.shape, dtype=bool)
    for polygon in review['deck_checks']:
        deck |= polygon_mask(polygon, x, y)
    if not mask.any() or not deck.any() or np.any(deck & ~mask):
        raise ValueError('Mark the full lane including both approaches, and a deck region inside it')
    keepout = np.zeros(x.shape, dtype=bool)
    for polygon in review['keepout_polygons']:
        keepout |= polygon_mask(polygon, x, y)
    if not keepout.any() or np.any(keepout & mask):
        raise ValueError('Mark the areas beside the bridge without covering the lane')
    valid = np.isfinite(points).all(axis=1)
    points = points[valid & ((points[:, :2] >= 0) & (points[:, :2] < 4)).all(axis=1)]
    ix, iy = np.floor(points[:, :2]/RESOLUTION).astype(int).T
    bins = {}
    for col, row, height in zip(ix, iy, points[:, 2]):
        if mask[row, col]:
            bins.setdefault((row, col), []).append(height)
    heights = np.full(mask.shape, np.nan)
    for row, col in zip(*np.nonzero(mask)):
        samples = bins.get((row, col), ())
        if len(samples) >= 3:
            heights[row, col] = np.median(samples)
    if np.isnan(heights[mask]).any():
        raise ValueError('Unobserved cells in the reviewed lane. Capture the bridge again from both sides')
    tolerance = calibration['residual_m']
    if np.any(np.abs(heights[deck]-.055) > tolerance):
        raise ValueError('Deck check differs from 55 mm. Verify the reference and camera mount')
    if np.any((heights[mask] < -tolerance) | (heights[mask] > .055+tolerance)):
        raise ValueError('Unexpected elevations in lane. Review the empty capture and the rail boundaries')
    return heights, np.flatnonzero(keepout)


def build(args):
    arena = json.loads(args.arena.read_text())
    review = json.loads(args.review.read_text())
    if arena.get('training_state') != 'MAP_READY' or not arena.get('version'):
        raise ValueError('Use a frozen semantic map')
    start_pose = arena['objects']['start']['goals'][0]
    with np.load(args.cloud, allow_pickle=False) as cloud:
        heights, keepout = bake(cloud['points'], review)
    if not args.database.is_file() or args.database.stat().st_size == 0:
        raise ValueError('Use the saved RTAB-Map database from the same session')
    data = {
        'frame_id': 'map', 'resolution': RESOLUTION, 'shape': list(heights.shape),
        'heights': [round(float(z), 5) if np.isfinite(z) else None for z in heights.flat],
        'keepout': keepout.tolist(),
        'arena_version': arena['version'], 'occupancy_sha256': arena['occupancy_sha256'],
        'database_sha256': digest(args.database), 'cloud_sha256': digest(args.cloud),
        'calibration': review['calibration'], 'start_pose': start_pose,
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=args.output.parent) as temporary:
        json.dump(data, temporary, allow_nan=False, separators=(',', ':'))
        temporary.flush()
        read_reference(Path(temporary.name))
        os.link(temporary.name, args.output)
    print(f'Bridge reference saved: {args.output}')


def capture(args):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from nav_msgs.msg import OccupancyGrid
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py.point_cloud2 import read_points_numpy
    from std_srvs.srv import Trigger

    class Capture(Node):
        def __init__(self):
            super().__init__('bridge_capture')
            self.cloud = None
            qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(PointCloud2, '/terrain/slam/cloud_map', self.cloud_callback, qos)
            self.create_service(Trigger, '/terrain/capture', self.save)
            self.map_pub = self.create_publisher(OccupancyGrid, '/map', qos)
            self.create_subscription(OccupancyGrid, '/terrain/slam_grid', self.rebase_grid, qos)

        def rebase_grid(self, grid):
            if grid.header.frame_id == 'slam_map':
                # Match the static map->slam_map transform in the training launch.
                grid.info.origin.position.x += .4
                grid.info.origin.position.y += .4
                grid.header.frame_id = 'map'
                self.map_pub.publish(grid)

        def cloud_callback(self, cloud):
            if cloud.header.frame_id == 'rgbd_map' and cloud.width:
                self.cloud = cloud

        def save(self, _request, response):
            if self.cloud is None:
                response.message = 'Wait for the optimized RGB-D cloud'
                return response
            try:
                points = read_points_numpy(self.cloud, field_names=('x', 'y', 'z'), skip_nans=True)
                with args.output.open('xb') as stream:
                    np.savez_compressed(stream, points=points)
                response.success = True
                response.message = str(args.output)
            except (OSError, ValueError, AssertionError) as exc:
                response.message = str(exc)
            return response

    rclpy.init()
    node = Capture()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def preview(args):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import Header
    from visualization_msgs.msg import Marker
    from bridge_guard import surface_marker
    from surface import CLEAR, Surface

    surface = Surface(read_reference(args.reference))
    states = surface.grid(0., False)
    states[surface.mask] = CLEAR
    rclpy.init()
    node = Node('bridge_reference_preview')
    markers = node.create_publisher(Marker, '/terrain/markers',
                                    QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    header = Header(frame_id='map')
    markers.publish(surface_marker(surface, states, header))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    from rclpy.utilities import remove_ros_args

    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(required=True)
    record = actions.add_parser('capture')
    record.add_argument('output', type=Path)
    record.set_defaults(run=capture)
    freeze = actions.add_parser('build')
    for file in ('arena', 'review', 'cloud', 'database', 'output'):
        freeze.add_argument(f'--{file}', type=Path, required=True)
    freeze.set_defaults(run=build)
    view = actions.add_parser('preview')
    view.add_argument('reference', type=Path)
    view.set_defaults(run=preview)
    args = parser.parse_args(remove_ros_args()[1:])
    args.run(args)


if __name__ == '__main__':
    main()
