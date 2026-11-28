"""Bridge reference raster, depth classification and swept wheelbase checks."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np

RESOLUTION = .02
OUTSIDE, CLEAR, UNKNOWN, BLOCKED = -1, 0, 50, 100


def read_reference(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    shape = tuple(data['shape'])
    if (data['frame_id'] != 'map' or data['resolution'] != RESOLUTION
            or shape != (200, 200)):
        raise ValueError('Expected a 4 m square map in the arena frame')
    heights = np.asarray([np.nan if z is None else z for z in data['heights']],
                         dtype=np.float32).reshape(shape)
    if np.isinf(heights).any() or not np.isfinite(heights).any():
        raise ValueError('A measured bridge surface is required')
    forbidden = np.asarray(data['keepout'], dtype=int)
    if (forbidden.ndim != 1 or not len(forbidden)
            or not ((0 <= forbidden) & (forbidden < heights.size)).all()
            or np.isfinite(heights.flat[forbidden]).any()):
        raise ValueError('Mark bridge shoulders without overlapping its lane')
    keepout = np.zeros(heights.size, dtype=bool)
    keepout[forbidden] = True
    data['keepout'] = keepout.reshape(shape)
    calibration = data['calibration']
    limits = {
        'residual_m': (.005, .03), 'max_pose_error_m': (.005, .06),
        'braking_decel_m_s2': (.05, .5), 'angular_decel_rad_s2': (.05, 2.),
        'reaction_sec': (.6, 2.), 'max_speed_m_s': (.03, .15),
        'clear_ttl_sec': (.5, 10.), 'footprint_margin_m': (.05, .20),
    }
    for key, (lo, hi) in limits.items():
        value = float(calibration[key])
        if not lo <= value <= hi:
            raise ValueError(f'{key} must be between {lo} and {hi}')
        calibration[key] = value
    data['heights'] = heights
    if len(data['start_pose']) != 3 or not all(math.isfinite(p) for p in data['start_pose']):
        raise ValueError('A surveyed start pose is required')
    return data


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rotation(q) -> np.ndarray:
    x, y, z, w = q.x, q.y, q.z, q.w
    norm = math.hypot(x, y, z, w)
    if not .99 <= norm <= 1.01:
        raise ValueError('Invalid orientation quaternion')
    x, y, z, w = (component / norm for component in (x, y, z, w))
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])


def yaw_matrix(yaw: float) -> np.ndarray:
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def project_depth(data, height, width, step, encoding, bigendian, k) -> np.ndarray:
    if step * height > len(data) or width <= 0 or height <= 0:
        raise ValueError('Invalid depth image dimensions')
    if encoding not in ('16UC1', '32FC1') or min(k[0], k[4]) <= 0:
        raise ValueError('Expected calibrated D435 depth')
    dtype = np.dtype(('>' if bigendian else '<') + ('u2' if encoding == '16UC1' else 'f4'))
    if step < width * dtype.itemsize:
        raise ValueError('Invalid depth row stride')
    raw = np.ndarray((height, width), dtype, buffer=bytes(data), strides=(step, dtype.itemsize))
    # Keep full resolution: small cars and the far wheel track can occupy very few pixels.
    row, col = np.nonzero(np.isfinite(raw) & (raw > 0))
    z = raw[row, col].astype(np.float32)
    if encoding == '16UC1':
        z *= .001
    valid = (z >= .20) & (z <= 2.5)
    row, col, z = row[valid], col[valid], z[valid]
    return np.stack(((col-k[2])*z/k[0], (row-k[5])*z/k[4], z), axis=1)


class Surface:
    def __init__(self, reference: dict):
        self.heights = reference['heights']
        self.calibration = reference['calibration']
        self.mask = np.isfinite(self.heights)
        self.keepout = reference['keepout']
        self.last_clear = np.full(self.heights.shape, -np.inf)
        self.hazards = np.zeros(self.heights.shape, dtype=bool)
        self.confirmations = np.zeros(self.heights.shape, dtype=np.uint8)

    def reset(self):
        self.invalidate_clear()
        self.hazards.fill(False)

    def invalidate_clear(self):
        self.last_clear.fill(-np.inf)
        self.confirmations.fill(0)

    def observe(self, points: np.ndarray, now: float):
        size = self.heights.size
        points = points[np.isfinite(points).all(axis=1)]
        xy = np.floor(points[:, :2] / RESOLUTION).astype(int)
        inside = ((xy >= 0) & (xy < self.heights.shape[0])).all(axis=1)
        x, y = xy[inside].T
        z = points[inside, 2]
        delta = z - self.heights[y, x]
        cell = y * self.heights.shape[1] + x
        tolerance = self.calibration['residual_m']
        outliers = np.bincount(cell[np.abs(delta) > tolerance], minlength=size).reshape(self.heights.shape)
        support = np.bincount(cell[np.abs(delta) <= tolerance], minlength=size).reshape(self.heights.shape)
        # A gap or protrusion overrides support in the same cell.
        hit = outliers >= 2
        self.hazards |= hit
        self.last_clear[outliers > 0] = -np.inf
        match = (support >= 3) & (outliers == 0) & self.mask
        self.confirmations[~match] = 0
        self.confirmations[match] = np.minimum(self.confirmations[match] + 1, 3)
        clear = self.confirmations >= 3
        self.last_clear[clear] = now
        self.hazards[clear] = False

    def grid(self, now: float, fresh: bool) -> np.ndarray:
        grid = np.full(self.heights.shape, OUTSIDE, dtype=np.int8)
        grid[self.mask] = UNKNOWN
        if fresh:
            grid[self.mask & (now - self.last_clear <= self.calibration['clear_ttl_sec'])] = CLEAR
        grid[self.hazards | self.keepout] = BLOCKED
        return grid

    def permits(self, grid, pose, linear, angular) -> bool:
        """Check the footprint swept through delay and braking, including turns."""
        cfg = self.calibration
        margin = cfg['footprint_margin_m'] + cfg['max_pose_error_m']
        rear, front, half_width = .17 + margin, .11 + margin, .125 + margin
        x, y, yaw = pose
        delay = cfg['reaction_sec']
        linear_decel, angular_decel = cfg['braking_decel_m_s2'], cfg['angular_decel_rad_s2']
        duration = delay + max(abs(linear)/linear_decel, abs(angular)/angular_decel)
        max_tip_speed = abs(linear) + math.hypot(rear, half_width)*abs(angular)
        step = min(.04, RESOLUTION / (4 * max(max_tip_speed, .01)))
        radius = math.hypot(rear, half_width) + 2 * RESOLUTION
        reach = radius + abs(linear) * duration
        low_x, low_y = np.floor((np.array([x, y])-reach)/RESOLUTION).astype(int)
        high_x, high_y = np.ceil((np.array([x, y])+reach)/RESOLUTION).astype(int)
        if not np.any(grid[max(0, low_y):high_y+1, max(0, low_x):high_x+1] >= UNKNOWN):
            return True
        count = math.ceil(radius/RESOLUTION)
        offsets = np.arange(-count, count+1)
        for index in range(math.ceil(duration / step) + 1):
            ix = math.floor(x / RESOLUTION) + offsets
            iy = math.floor(y / RESOLUTION) + offsets
            ix, iy = ix[(ix >= 0) & (ix < grid.shape[1])], iy[(iy >= 0) & (iy < grid.shape[0])]
            wy, wx = np.meshgrid((iy + .5) * RESOLUTION - y, (ix + .5) * RESOLUTION - x,
                                 indexing='ij')
            c, s = math.cos(yaw), math.sin(yaw)
            along, across = c*wx + s*wy, -s*wx + c*wy
            pad = RESOLUTION
            hit = ((along >= -rear-pad) & (along <= front+pad) & (np.abs(across) <= half_width+pad))
            if np.any(grid[np.ix_(iy, ix)][hit] >= UNKNOWN):
                return False
            after_delay = max(0, index*step - delay)
            v = math.copysign(max(0, abs(linear) - linear_decel*after_delay), linear)
            w = math.copysign(max(0, abs(angular) - angular_decel*after_delay), angular)
            x += step*v*math.cos(yaw + w*step/2)
            y += step*v*math.sin(yaw + w*step/2)
            yaw += step*w
        return True
