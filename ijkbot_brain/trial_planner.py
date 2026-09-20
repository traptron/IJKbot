"""Coordinate trial: navigate, remain stationary for five seconds, return home."""

import copy
import math
import time

import rclpy
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Bool, String


class TrialPlanner(Node):
    """One mission at a time; Nav2 results, not odom coordinates, prove arrival."""

    def __init__(self):
        super().__init__('trial_planner')
        for name, value in [('home_x', 0.4), ('home_y', 0.4),
                            ('home_yaw', 0.0), ('mission_timeout', 300.0)]:
            self.declare_parameter(name, value)
        self.home = PoseStamped()
        self.home.header.frame_id = 'map'
        self.home.pose.position.x = float(self.get_parameter('home_x').value)
        self.home.pose.position.y = float(self.get_parameter('home_y').value)
        yaw = float(self.get_parameter('home_yaw').value)
        self.home.pose.orientation.z = math.sin(yaw / 2)
        self.home.pose.orientation.w = math.cos(yaw / 2)
        self.timeout = float(self.get_parameter('mission_timeout').value)
        if not all(math.isfinite(v) for v in (
                self.home.pose.position.x, self.home.pose.position.y, yaw, self.timeout)):
            raise ValueError('Parameters must be finite')
        if self.timeout <= 0:
            raise ValueError('mission_timeout must be positive')
        self.state = 'IDLE'
        self.handle = None
        self.pending = False
        self.estopped = False
        self.started = 0.0
        self.stationary_since = None
        self.last_odom = None
        self.stationary = False
        self.active_goals = set()
        self.owned_goal_id = None
        self.legacy_active = False
        self.client = ActionClient(self, NavigateToPose, '/navigate_to_pose')
        self.state_pub = self.create_publisher(String, '/trial/state', 10)
        self.create_subscription(PoseStamped, '/trial/goal_pose', self.on_goal, 10)
        self.create_subscription(PoseStamped, '/goal_pose', self.on_external_goal, 10)
        self.create_subscription(String, '/mission/state', self.on_mission_state, 10)
        self.create_subscription(
            GoalStatusArray, '/navigate_to_pose/_action/status', self.on_nav_status,
            qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(Bool, '/emergency_stop', self.on_stop, 10)
        self.create_timer(0.05, self.tick)
        self.transition('IDLE')

    def transition(self, state: str) -> None:
        self.state = state
        self.get_logger().info(f'Trial: {state}')
        self.state_pub.publish(String(data=state))

    def on_goal(self, pose: PoseStamped) -> None:
        if self.estopped or self.pending or self.handle is not None or self.state not in (
                'IDLE', 'COMPLETE', 'FAILED', 'STOPPED'):
            self.get_logger().warning('Цель отклонена: миссия занята или E-STOP активен')
            return
        if self.active_goals or self.legacy_active:
            self.get_logger().warning('Испытание не запущено: система уже выполняет миссию')
            return
        p, q = pose.pose.position, pose.pose.orientation
        values = (p.x, p.y, p.z, q.x, q.y, q.z, q.w)
        norm = math.sqrt(sum(v*v for v in (q.x, q.y, q.z, q.w)))
        if (pose.header.frame_id != 'map' or not all(math.isfinite(v) for v in values)
                or abs(norm - 1.0) > 0.01 or abs(p.z) > 0.001):
            self.get_logger().error('Нужна конечная PoseStamped в map с единичным quaternion')
            return
        if not self.client.server_is_ready():
            self.get_logger().error('Nav2 /navigate_to_pose пока недоступен; повторите цель')
            return
        if self.last_odom is None or time.monotonic() - self.last_odom > 0.5:
            self.get_logger().error('Цель отклонена: нет свежей колёсной одометрии')
            return
        self.started = time.monotonic()
        self.stationary_since = None
        self.send(pose, 'OUTBOUND')

    def send(self, pose: PoseStamped, state: str) -> None:
        self.transition(state)
        goal = NavigateToPose.Goal()
        goal.pose = copy.deepcopy(pose)
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        self.pending = True
        try:
            self.client.send_goal_async(goal).add_done_callback(self.accepted)
        except Exception as exc:
            self.pending = False
            self.fail(str(exc))

    def accepted(self, future) -> None:
        self.pending = False
        try:
            handle = future.result()
            if not handle.accepted:
                self.fail('Nav2 отклонил цель')
                return
            self.handle = handle
            self.owned_goal_id = bytes(handle.goal_id.uuid)
            handle.get_result_async().add_done_callback(self.finished)
            if self.state not in ('OUTBOUND', 'RETURNING'):
                self.cancel()
        except Exception as exc:
            self.fail(str(exc))

    def finished(self, future) -> None:
        try:
            result = future.result()
            self.handle = None
            if self.state not in ('OUTBOUND', 'RETURNING'):
                return
            if (result.status != GoalStatus.STATUS_SUCCEEDED
                    or getattr(result.result, 'error_code', 0) != 0):
                self.fail(f'Nav2 завершился без успеха: status={result.status}')
            elif self.state == 'OUTBOUND':
                self.stationary_since = None
                self.transition('HOLDING')
            else:
                self.transition('COMPLETE')
        except Exception as exc:
            self.fail(str(exc))

    def on_external_goal(self, msg: PoseStamped) -> None:
        """Yield to the existing system rather than competing with its goals."""
        if self.state in ('OUTBOUND', 'HOLDING', 'RETURNING'):
            self.fail('Внешняя цель /goal_pose: испытание отменено, управление у системы')

    def on_mission_state(self, msg: String) -> None:
        self.legacy_active = msg.data in {
            'NAVIGATING_TO_LANDMARK', 'SEARCHING_VICTIM', 'APPROACHING_VICTIM',
            'WAIT_5_SECONDS', 'READING_QR', 'RETURNING_HOME', 'PAUSED', 'EMERGENCY_STOP',
        }
        if self.legacy_active and self.state in ('OUTBOUND', 'HOLDING', 'RETURNING'):
            self.fail('Старый автомат миссии активен; испытание отменено')

    def on_nav_status(self, msg: GoalStatusArray) -> None:
        self.active_goals = {
            bytes(item.goal_info.goal_id.uuid) for item in msg.status_list
            if item.status in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING,
                               GoalStatus.STATUS_CANCELING)
        }
        if self.state not in ('OUTBOUND', 'HOLDING', 'RETURNING') or self.pending:
            return
        own = {self.owned_goal_id} if self.owned_goal_id is not None else set()
        if self.active_goals - own:
            self.fail('Другая action-цель Nav2: испытание отменено')

    def on_odom(self, msg: Odometry) -> None:
        now = time.monotonic()
        twist = msg.twist.twist
        values = (twist.linear.x, twist.linear.y, twist.angular.z)
        self.stationary = (all(math.isfinite(v) for v in values)
                           and math.hypot(*values[:2]) < 0.01
                           and abs(values[2]) < 0.02)
        if (not self.stationary or self.last_odom is None
                or now - self.last_odom > 0.5):
            self.stationary_since = None
        self.last_odom = now

    def tick(self) -> None:
        now = time.monotonic()
        if self.state in ('OUTBOUND', 'HOLDING', 'RETURNING'):
            if now - self.started >= self.timeout:
                self.fail('Истекло время миссии')
        if self.state in ('OUTBOUND', 'RETURNING'):
            if self.last_odom is None or now - self.last_odom > 0.5:
                self.fail('Потеря колёсной одометрии')
        if self.state == 'HOLDING':
            if not self.stationary or self.last_odom is None or now - self.last_odom > 0.5:
                self.stationary_since = None
            elif self.stationary_since is None:
                self.stationary_since = now
            elif now - self.stationary_since >= 5.0:
                self.send(self.home, 'RETURNING')
        self.state_pub.publish(String(data=self.state))

    def cancel(self) -> None:
        if self.handle is not None:
            try:
                self.handle.cancel_goal_async().add_done_callback(self.canceled)
            except Exception as exc:
                self.get_logger().error(f'Ошибка отмены Nav2: {exc}')

    def canceled(self, future) -> None:
        try:
            if not future.result().goals_canceling:
                self.get_logger().error('Nav2 не подтвердил отмену цели')
        except Exception as exc:
            self.get_logger().error(f'Ошибка отмены Nav2: {exc}')

    def on_stop(self, msg: Bool) -> None:
        self.estopped = msg.data
        if msg.data:
            self.transition('STOPPED')
            self.cancel()

    def fail(self, reason: str) -> None:
        self.get_logger().error(reason)
        self.transition('FAILED')
        self.cancel()

def main(args=None):
    rclpy.init(args=args)
    node = TrialPlanner()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.on_stop(Bool(data=True))
            deadline = time.monotonic() + 2.0
            while (node.pending or node.handle is not None) and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
