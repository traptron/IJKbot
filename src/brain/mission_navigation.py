"""Asynchronous Nav2 path checks against a fresh global costmap."""

import math
import time

from nav_msgs.msg import OccupancyGrid
from nav2_msgs.action import ComputePathToPose
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data


class MissionNavigation:
    def __init__(self, wrapper):
        self.wrapper = wrapper
        self.node = wrapper.node
        self.client = ActionClient(self.node, ComputePathToPose, '/compute_path_to_pose')
        self.grid = None
        self.grid_time = 0.0
        self.generation = 0
        self.home_pending = False
        self.cells_pending = False
        self.node.create_subscription(OccupancyGrid, '/global_costmap/costmap', self.on_grid, qos_profile_sensor_data)
        self.node.declare_parameter('approach_clearance_radius', 0.28)
        self.radius = float(self.node.get_parameter('approach_clearance_radius').value)
        if not math.isfinite(self.radius) or self.radius < .25:
            raise ValueError('Approach radius must cover chassis and safety clearance')

    def on_grid(self, msg):
        with self.wrapper.sm.lock:
            self.grid, self.grid_time = msg, time.monotonic()

    def free(self, x, y):
        grid = self.grid
        if grid is None or time.monotonic()-self.grid_time > 2 or grid.header.frame_id != 'map':
            return False
        info = grid.info
        if info.resolution <= 0 or len(grid.data) != info.width*info.height:
            return False
        q = info.origin.orientation
        if abs(q.x)+abs(q.y)+abs(q.z) > 1e-6:
            return False
        cx = math.floor((x-info.origin.position.x)/info.resolution)
        cy = math.floor((y-info.origin.position.y)/info.resolution)
        count = math.ceil(self.radius/info.resolution)
        for ix in range(cx-count, cx+count+1):
            for iy in range(cy-count, cy+count+1):
                if not 0 <= ix < info.width or not 0 <= iy < info.height:
                    return False
                if grid.data[iy*info.width+ix] < 0 or grid.data[iy*info.width+ix] >= 50:
                    return False
        return True

    def path(self, x, y, callback):
        if not self.client.server_is_ready():
            callback(None)
            return
        goal = ComputePathToPose.Goal()
        goal.goal = PoseStamped()
        goal.goal.header.frame_id = 'map'
        goal.goal.header.stamp = self.node.get_clock().now().to_msg()
        goal.goal.pose.position.x, goal.goal.pose.position.y = float(x), float(y)
        goal.goal.pose.orientation.w = 1.0
        goal.use_start = False

        finished = False
        handle = None

        def done(length):
            nonlocal finished
            if finished:
                return
            finished = True
            self.node.destroy_timer(timer)
            callback(length)

        def expired():
            if handle is not None:
                handle.cancel_goal_async()
            done(None)

        timer = self.node.create_timer(2., expired)

        def accepted(future):
            nonlocal handle
            try:
                handle = future.result()
                if not handle.accepted:
                    done(None)
                    return
                if finished:
                    handle.cancel_goal_async()
                    return
                handle.get_result_async().add_done_callback(completed)
            except Exception:
                done(None)

        def completed(future):
            try:
                result = future.result()
                poses = result.result.path.poses
                length = sum(math.hypot(b.pose.position.x-a.pose.position.x,
                                        b.pose.position.y-a.pose.position.y)
                             for a, b in zip(poses, poses[1:]))
                victim = self.wrapper.sm.evacuation.victim
                safe = True
                if victim:
                    vx, vy = victim.position[:2]
                    for a, b in zip(poses, poses[1:]):
                        ax, ay = a.pose.position.x, a.pose.position.y
                        dx, dy = b.pose.position.x-ax, b.pose.position.y-ay
                        square_length = dx*dx+dy*dy
                        fraction = max(0., min(1., ((vx-ax)*dx+(vy-ay)*dy)/square_length)) if square_length else 0.
                        if math.hypot(ax+fraction*dx-vx, ay+fraction*dy-vy) < .32:
                            safe = False
                done(length if result.status == 4 and poses and math.isfinite(length) and safe else None)
            except Exception:
                done(None)
        try:
            self.client.send_goal_async(goal).add_done_callback(accepted)
        except Exception:
            done(None)

    def plan_cells(self, attempt_id):
        if self.cells_pending and self.wrapper.sm.evacuation.attempt_id == self.cells_attempt:
            return
        self.cells_pending = True
        self.cells_attempt = attempt_id
        self.generation += 1
        generation = self.generation
        sm = self.wrapper.sm
        cells = [(x, y) for x in range(5) for y in range(5)
                 if [x, y] not in sm.evacuation.map.get('blocked_cells', [])
                 and self.free(.4+.8*x, .4+.8*y)]
        paths = {}

        def next_cell(index=0):
            with sm.lock:
                if sm.evacuation.attempt_id != attempt_id or generation != self.generation or sm.state.value != 'SEARCHING_VICTIM':
                    if generation == self.generation:
                        self.cells_pending = False
                    return
                if index == len(cells):
                    self.cells_pending = False
                    sm.evacuation.paths = paths
                    sm.evacuation.paths_at = time.monotonic()
                    return
                x, y = cells[index]
                def ready(length):
                    with sm.lock:
                        if length is not None and self.free(.4+.8*x, .4+.8*y):
                            paths[x, y] = length
                        next_cell(index+1)
                self.path(.4+.8*x, .4+.8*y, ready)
        next_cell()

    def plan_home(self, attempt_id):
        if self.home_pending:
            return
        self.home_pending = True
        home = self.wrapper.sm.evacuation.home
        def ready(length):
            with self.wrapper.sm.lock:
                self.home_pending = False
                runtime = self.wrapper.sm.evacuation
                if runtime.attempt_id == attempt_id:
                    runtime.home_length = length
                    runtime.paths_at = time.monotonic()
        self.path(home.x, home.y, ready)
