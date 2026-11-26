#!/usr/bin/env python3
"""Turn timestamped D435 terrain evidence into Nav2 costs and a velocity interlock."""

from collections import deque
import json
import math
from pathlib import Path
import time

from geometry_msgs.msg import Point, PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image, LaserScan
from std_msgs.msg import ColorRGBA, String
from tf2_ros import Buffer, TransformException, TransformListener
from visualization_msgs.msg import Marker

from surface import BLOCKED, CLEAR, RESOLUTION, UNKNOWN, Surface, project_depth, read_reference, rotation, yaw_matrix

RGB = '/camera/color'
DEPTH = '/camera/aligned_depth_to_color/image_raw'


def xyz(point):
    return np.array([point.x, point.y, point.z])


def surface_marker(surface, states, header):
    mark = Marker(header=header, ns='bridge_surface', id=0, type=Marker.CUBE_LIST)
    mark.pose.orientation.w = 1.
    mark.scale.x = mark.scale.y = RESOLUTION
    mark.scale.z = .005
    mark.color.a = 1.
    colors = {
        CLEAR: ColorRGBA(r=.12, g=.85, b=.2, a=.75),
        BLOCKED: ColorRGBA(r=1., g=.1, b=.08, a=.95),
        UNKNOWN: ColorRGBA(r=1., g=.65, b=.0, a=.7),
    }
    ys, xs = np.nonzero(surface.mask | surface.keepout)
    for y, x in zip(ys, xs):
        z = float(surface.heights[y, x]) if surface.mask[y, x] else 0.
        mark.points.append(Point(x=(x+.5)*RESOLUTION, y=(y+.5)*RESOLUTION, z=z+.005))
        mark.colors.append(colors[int(states[y, x])])
    return mark


class BridgeGuard(Node):
    def __init__(self):
        super().__init__('bridge_guard')
        self.reference = read_reference(Path(self.declare_parameter('reference', '').value))
        self.surface = Surface(self.reference)
        self.config = self.reference['calibration']
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.info = None
        self.depth = deque(maxlen=6)
        self.last_depth = None
        self.visual = deque(maxlen=15)
        self.previous_visual = None
        self.odom = None
        self.amcl = None
        self.scan_stamp = None
        self.zero_height = None
        self.visual_floor = None
        self.depth_ok = float('-inf')
        self.attempt = ''
        self.mission_state = ''
        self.last_reason = ''
        self.grid = self.surface.grid(time.monotonic(), False)
        self.qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.grid_pub = self.create_publisher(OccupancyGrid, '/terrain/grid', self.qos)
        self.markers = self.create_publisher(Marker, '/terrain/markers', self.qos)
        self.status = self.create_publisher(String, '/terrain/status', self.qos)
        self.velocity = self.create_publisher(Twist, '/cmd_vel_terrain_safe', 1)
        self.create_subscription(CameraInfo, RGB+'/camera_info', self.on_info, qos_profile_sensor_data)
        self.create_subscription(Image, DEPTH, self.on_depth, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/terrain/visual_odom', self.on_visual, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.on_amcl, 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(String, '/mission/attempt_id', self.on_attempt, 10)
        self.create_subscription(String, '/mission/state', self.on_mission_state, 10)
        self.create_subscription(Twist, '/cmd_vel_terrain_input', self.command, 1)
        self.create_timer(.05, self.tick)
        self.create_timer(.25, self.publish_grid)

    def age(self, stamp):
        return (self.get_clock().now() - Time.from_msg(stamp)).nanoseconds * 1e-9

    def recent(self, stamp, limit=.3):
        return stamp is not None and 0 <= self.age(stamp) <= limit

    def on_info(self, msg):
        self.info = msg

    def on_depth(self, msg):
        self.depth.append(msg)

    def on_visual(self, msg):
        self.visual.append(msg)

    def on_odom(self, msg):
        self.odom = msg

    def on_amcl(self, msg):
        self.amcl = msg

    def on_scan(self, msg):
        if any(math.isfinite(value) and msg.range_min <= value <= msg.range_max for value in msg.ranges):
            self.scan_stamp = msg.header.stamp

    def discard_evidence(self):
        self.surface.reset()
        self.depth.clear()
        self.visual.clear()
        self.depth_ok = float('-inf')

    def on_attempt(self, msg):
        if msg.data != self.attempt:
            self.attempt = msg.data
            self.discard_evidence()

    def on_mission_state(self, msg):
        if msg.data == 'READY_TO_START' and msg.data != self.mission_state:
            self.discard_evidence()
        self.mission_state = msg.data

    def localized(self):
        if self.amcl is None or self.odom is None or self.amcl.header.frame_id != 'map':
            return False
        covariance = self.amcl.pose.covariance
        std = self.config['max_pose_error_m']
        return bool(self.recent(self.scan_stamp) and self.recent(self.odom.header.stamp)
                    and self.recent(self.amcl.header.stamp, .6)
                    and 0 <= covariance[0] <= std**2 and 0 <= covariance[7] <= std**2
                    and 0 <= covariance[35] <= .2**2)

    def planar_pose(self, stamp):
        tf = self.buffer.lookup_transform('map', 'base_footprint', stamp).transform
        matrix = rotation(tf.rotation)
        translation = xyz(tf.translation)
        if not np.isfinite(translation).all():
            raise ValueError('Non-finite map pose')
        return (*translation[:2], math.atan2(matrix[1, 0], matrix[0, 0]))

    def process_depth(self):
        if not self.localized() or not self.depth or self.info is None or not self.visual:
            return
        for msg in reversed(self.depth):
            stamp = Time.from_msg(msg.header.stamp)
            if ((self.last_depth is not None and self.last_depth >= stamp)
                    or not self.recent(msg.header.stamp)
                    or self.info.header.frame_id != msg.header.frame_id
                    or (self.info.width, self.info.height) != (msg.width, msg.height)):
                continue
            visual = min(self.visual, key=lambda odom: abs((Time.from_msg(odom.header.stamp)-stamp).nanoseconds))
            if abs((Time.from_msg(visual.header.stamp)-stamp).nanoseconds) <= 35_000_000:
                break
        else:
            return
        cov = visual.pose.covariance
        if (visual.child_frame_id != 'base_footprint' or visual.header.frame_id != 'rgbd_odom'
                or not all(0 <= cov[i] < .1 for i in (0, 7, 14, 21, 28, 35))):
            return
        vo = visual.pose.pose
        vo_rotation = rotation(vo.orientation)
        x, y, yaw = self.planar_pose(stamp)
        if self.zero_height is None:
            start = self.reference['start_pose']
            motion = self.odom.twist.twist
            if (math.hypot(x-start[0], y-start[1]) > .15 or abs(motion.linear.x) >= .01
                    or abs(motion.angular.z) >= .02 or vo_rotation[2, 2] < .995):
                return
            self.zero_height = vo.position.z
        if self.previous_visual is not None:
            prev_xy, prev_z = self.previous_visual
            if abs(vo.position.z - prev_z) > .035 + .5 * math.dist((x, y), prev_xy):
                self.zero_height = None
                self.previous_visual = None
                self.discard_evidence()
                return
        self.previous_visual = ((x, y), vo.position.z)
        height = vo.position.z - self.zero_height
        if not math.isfinite(height) or not -.08 <= height <= .20:
            return
        tf = self.buffer.lookup_transform('base_footprint', msg.header.frame_id, stamp).transform
        points = project_depth(msg.data, msg.height, msg.width, msg.step, msg.encoding,
                               msg.is_bigendian, self.info.k)
        if not len(points):
            return
        vo_yaw = math.atan2(vo_rotation[1, 0], vo_rotation[0, 0])
        orientation = yaw_matrix(yaw - vo_yaw) @ vo_rotation
        # Unfold the optical projection using pitch/roll from RGB-D odometry.
        points = np.einsum('ij,kj->ik', points, orientation @ rotation(tf.rotation))
        points += orientation @ xyz(tf.translation) + [x, y, height]
        now = time.monotonic()
        self.surface.observe(points, now)
        self.depth_ok = now
        self.last_depth = stamp

    def depth_fresh(self, now):
        return (self.localized() and now - self.depth_ok <= .30 and self.last_depth is not None
                and 0 <= (self.get_clock().now() - self.last_depth).nanoseconds <= 350_000_000)

    def current_grid(self):
        now = time.monotonic()
        return self.surface.grid(now, self.depth_fresh(now))

    def tick(self):
        if not self.depth_fresh(time.monotonic()):
            self.surface.invalidate_clear()
        try:
            self.process_depth()
        except (TransformException, ValueError, OverflowError) as exc:
            self.get_logger().debug(str(exc))
        if not self.localized():
            self.velocity.publish(Twist())

    def report(self, reason):
        if reason != self.last_reason:
            self.get_logger().info(reason)
            self.last_reason = reason

    def command(self, msg):
        if not math.isfinite(msg.linear.x) or not math.isfinite(msg.angular.z):
            self.velocity.publish(Twist())
            return
        if msg.linear.x == 0 and msg.angular.z == 0:
            self.velocity.publish(Twist())
            return
        if not self.localized():
            self.report('Локализация по лидару недоступна')
            self.velocity.publish(Twist())
            return
        if self.zero_height is None:
            self.report('Ожидание привязки D435 на ровном старте')
            self.velocity.publish(Twist())
            return
        v = float(np.clip(msg.linear.x, -self.config['max_speed_m_s'], self.config['max_speed_m_s']))
        w = float(np.clip(msg.angular.z, -.45, .45))
        actual = self.odom.twist.twist
        try:
            pose = self.planar_pose(Time.from_msg(self.odom.header.stamp))
            grid = self.current_grid()
            permitted = all(
                math.isfinite(linear) and math.isfinite(angular)
                and self.surface.permits(grid, pose, linear, angular)
                for linear, angular in ((v, w), (actual.linear.x, actual.angular.z),
                                        (actual.linear.x, w), (v, actual.angular.z))
            )
        except (TransformException, ValueError, OverflowError):
            permitted = False
        if not permitted:
            self.report('Проезд перекрыт или поверхность не подтверждена')
            self.velocity.publish(Twist())
            return
        command = Twist()
        command.linear.x, command.angular.z = v, w
        self.report('Траектория разрешена')
        self.velocity.publish(command)

    def publish_grid(self):
        self.grid = self.current_grid()
        grid = OccupancyGrid()
        grid.header.frame_id = 'map'
        grid.header.stamp = self.get_clock().now().to_msg()
        grid.info.resolution = RESOLUTION
        grid.info.height, grid.info.width = self.grid.shape
        grid.info.origin.orientation.w = 1.
        grid.data = self.grid.ravel().tolist()
        self.grid_pub.publish(grid)
        self.status.publish(String(data=json.dumps({
            'reason': self.last_reason, 'localized': self.localized(),
            'depth_fresh': self.depth_fresh(time.monotonic()),
            'blocked_cells': int(np.count_nonzero(self.surface.hazards)),
            'clear_cells': int(np.count_nonzero(self.grid == CLEAR)),
        }, ensure_ascii=False)))
        if self.markers.get_subscription_count():
            self.markers.publish(surface_marker(self.surface, self.grid, grid.header))


def main():
    rclpy.init()
    node = BridgeGuard()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
