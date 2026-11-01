"""Worker script for odometry calibration executed inside ROS 2 environment."""

import argparse
import math
import sys
import time
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
except ImportError:
    print("[ERROR] ROS 2 python libraries (rclpy) not found. Run via pixi or source ROS 2.")
    sys.exit(1)


def euler_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """Extract yaw angle (radians) from quaternion."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


class OdomCalibWorker(Node):
    def __init__(self, mode: str, target: float, speed: float):
        super().__init__("odom_calib_worker")
        self.mode = mode
        self.target = target
        self.speed = speed

        self.current_x = 0.0
        self.current_y = 0.0
        self.current_yaw = 0.0
        self.odom_received = False

        self.start_x: Optional[float] = None
        self.start_y: Optional[float] = None
        self.start_yaw: Optional[float] = None
        self.last_yaw: Optional[float] = None
        self.total_yaw_accumulated = 0.0

        self.sub_odom = self.create_subscription(Odometry, "/odom", self._on_odom, 10)
        self.pub_cmd = self.create_publisher(Twist, "/cmd_vel", 10)
        self.timer = self.create_timer(0.05, self._on_timer)  # 20 Hz
        self.done = False

    def _on_odom(self, msg: Odometry):
        self.current_x = msg.pose.pose.position.x
        self.current_y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        self.current_yaw = euler_from_quaternion(q.x, q.y, q.z, q.w)

        if not self.odom_received:
            self.start_x = self.current_x
            self.start_y = self.current_y
            self.start_yaw = self.current_yaw
            self.last_yaw = self.current_yaw
            self.odom_received = True
            return

        # Track angle wrap-around for rotation
        if self.last_yaw is not None:
            dyaw = self.current_yaw - self.last_yaw
            if dyaw > math.pi:
                dyaw -= 2.0 * math.pi
            elif dyaw < -math.pi:
                dyaw += 2.0 * math.pi
            self.total_yaw_accumulated += dyaw
        self.last_yaw = self.current_yaw

    def _on_timer(self):
        if not self.odom_received:
            return

        twist = Twist()
        if self.mode == "linear":
            dx = self.current_x - self.start_x
            dy = self.current_y - self.start_y
            distance_travelled = math.sqrt(dx * dx + dy * dy)

            remaining = self.target - distance_travelled
            if remaining <= 0.005:
                # Target reached
                twist.linear.x = 0.0
                self.pub_cmd.publish(twist)
                self.done = True
                print(f"RESULT_ODOM_DIST={distance_travelled:.6f}", flush=True)
                return

            current_speed = min(self.speed, max(0.04, remaining * 1.5))
            twist.linear.x = current_speed
            self.pub_cmd.publish(twist)
            print(f"PROGRESS={distance_travelled:.3f}/{self.target:.3f}", flush=True)

        elif self.mode == "angular":
            angle_travelled = abs(self.total_yaw_accumulated)
            remaining = self.target - angle_travelled
            if remaining <= 0.02:
                # Target reached
                twist.angular.z = 0.0
                self.pub_cmd.publish(twist)
                self.done = True
                print(f"RESULT_ODOM_ANGLE_RAD={angle_travelled:.6f}", flush=True)
                print(f"RESULT_ODOM_ANGLE_DEG={math.degrees(angle_travelled):.3f}", flush=True)
                return

            current_turn = math.copysign(min(self.speed, max(0.15, remaining * 1.2)), self.speed)
            twist.angular.z = current_turn
            self.pub_cmd.publish(twist)
            print(f"PROGRESS={math.degrees(angle_travelled):.1f}/{math.degrees(self.target):.1f} deg", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["linear", "angular"], required=True)
    parser.add_argument("--target", type=float, required=True, help="Distance in m or angle in rad")
    parser.add_argument("--speed", type=float, default=0.12, help="Speed in m/s or rad/s")
    args = parser.parse_args()

    rclpy.init()
    node = OdomCalibWorker(args.mode, args.target, args.speed)
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        # Emergency stop
        stop_twist = Twist()
        node.pub_cmd.publish(stop_twist)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

