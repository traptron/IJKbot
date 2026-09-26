"""Exercise real ROS topics using mock hardware; no physical UART is opened."""

import math
import os
import signal
import subprocess
import tempfile
import time
import uuid

import pytest
import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage


@pytest.fixture
def driver(monkeypatch, request):
    namespace = "test_" + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="ijkbot_ros_") as logs:
        monkeypatch.setenv("ROS_LOG_DIR", logs)
        environment = dict(os.environ, ROS_LOG_DIR=logs)
        missing_uart = getattr(request, "param", False)
        arguments = [os.environ["DRIVER_EXECUTABLE"], "--ros-args", "-r", f"__ns:=/{namespace}"]
        if missing_uart:
            arguments.extend(["-p", "mock_hardware:=false", "-p", f"serial_port:={logs}/absent_uart"])
        with open(f"{logs}/driver.log", "w+") as output:
            process = subprocess.Popen(
                arguments,
                env=environment, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                rclpy.init()
                node = rclpy.create_node("test_observer", namespace=namespace)
            except Exception:
                process.terminate()
                process.wait(timeout=3)
                raise
            odometry = []
            diagnostics = []
            transforms = []
            node.create_subscription(Odometry, "odom", lambda msg: odometry.append((time.monotonic(), msg)), 100)
            node.create_subscription(DiagnosticArray, "diagnostics", diagnostics.append, 10)
            node.create_subscription(TFMessage, "/tf", transforms.append, 100)
            publisher = node.create_publisher(Twist, "cmd_vel", 1)

            def spin(seconds, command=None):
                until = time.monotonic() + seconds
                next_publish = 0.0
                while time.monotonic() < until:
                    assert process.poll() is None, "Driver exited unexpectedly"
                    if command is not None and time.monotonic() >= next_publish:
                        publisher.publish(command)
                        next_publish = time.monotonic() + 0.04
                    rclpy.spin_once(node, timeout_sec=0.01)

            try:
                spin(1.5)
                if not missing_uart:
                    assert len(odometry) > 10
                assert publisher.get_subscription_count() == 1
                yield spin, odometry, diagnostics, transforms
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                node.destroy_node()
                rclpy.shutdown()
                output.seek(0)
                print(output.read())


def test_mock_motion_watchdog_tf_and_invalid_command(driver):
    spin, odometry, diagnostics, transforms = driver
    assert abs(odometry[-1][1].pose.pose.position.x) < 1e-9
    assert diagnostics[-1].status[0].hardware_id == "mock"
    command = Twist()
    command.linear.x = 0.1
    spin(1.0, command)
    assert odometry[-1][1].pose.pose.position.x > 0.05
    assert abs(odometry[-1][1].twist.twist.linear.x - 0.1) < 1e-6
    stopped_publishing = time.monotonic()
    spin(0.7)
    braking = [(stamp, msg) for stamp, msg in odometry
               if stamp > stopped_publishing and msg.twist.twist.linear.x < 0.099]
    assert braking and braking[0][0] - stopped_publishing < 0.30
    assert abs(odometry[-1][1].twist.twist.linear.x) < 1e-9
    stopped_x = odometry[-1][1].pose.pose.position.x
    command.linear.x = 0.0
    command.angular.z = 1.0
    spin(1.0, command)
    spin(0.7)
    latest = odometry[-1][1]
    assert abs(latest.pose.pose.position.x - stopped_x) < 0.001
    assert latest.pose.pose.orientation.z > 0.3
    assert abs(latest.twist.twist.angular.z) < 1e-9
    assert latest.header.frame_id == "odom"
    assert latest.child_frame_id == "base_footprint"
    assert transforms
    tf_by_stamp = {
        (tf.header.stamp.sec, tf.header.stamp.nanosec): tf
        for message in transforms for tf in message.transforms
    }
    matching = [msg for _, msg in odometry
                if (msg.header.stamp.sec, msg.header.stamp.nanosec) in tf_by_stamp]
    assert matching
    message = matching[-1]
    tf = tf_by_stamp[(message.header.stamp.sec, message.header.stamp.nanosec)]
    assert tf.header.frame_id == message.header.frame_id
    assert tf.child_frame_id == message.child_frame_id
    assert tf.transform.translation.x == message.pose.pose.position.x
    assert tf.transform.rotation == message.pose.pose.orientation
    command.angular.z = math.nan
    spin(0.2, command)
    count_after_fault = len(odometry)
    command.angular.z = 0.0
    command.linear.x = 0.1
    spin(1.2, command)
    assert len(odometry) == count_after_fault
    assert diagnostics[-1].status[0].level == DiagnosticStatus.ERROR
    assert "Non-finite" in diagnostics[-1].status[0].message


@pytest.mark.parametrize("driver", [True], indirect=True)
def test_missing_uart_keeps_node_alive_and_motion_locked(driver):
    spin, odometry, diagnostics, _ = driver
    command = Twist()
    command.linear.x = 0.1
    spin(1.2, command)
    assert not odometry
    assert diagnostics[-1].status[0].level == DiagnosticStatus.ERROR
    assert "Cannot open serial port" in diagnostics[-1].status[0].message


@pytest.mark.parametrize("parameter", [
    "max_linear_velocity:=0.3", "wheel_separation:=0.0",
    "left_wheel_id:=2", "cmd_vel_timeout:=0.3",
    "serial_timeout_ms:=0", "serial_timeout_ms:=101",
])
def test_unsafe_parameters_are_rejected(parameter):
    with tempfile.TemporaryDirectory(prefix="ijkbot_ros_") as logs:
        result = subprocess.run(
            [os.environ["DRIVER_EXECUTABLE"], "--ros-args", "-p", parameter],
            env=dict(os.environ, ROS_LOG_DIR=logs), capture_output=True, text=True, timeout=5,
        )
        assert result.returncode != 0
        assert "Driver startup failed" in result.stderr
