"""Exercise native ROS contracts, state gating, frame confirmation and snapshots."""
import os
import select
import signal
import subprocess
import time

import cv2
import numpy as np
import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String


def test_relay_preserves_jpeg_and_waits_for_ack():
    """A slow receiver must get the newest JPEG, not a backlog of old frames."""
    rclpy.init()
    node = rclpy.create_node('relay_test')
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    publisher = node.create_publisher(CompressedImage, '/test/relay', qos)
    process = subprocess.Popen([
        os.environ['RELAY_EXECUTABLE'], '--topic', '/test/relay', '--fps', '15',
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def spin(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.01)

    def read_jpeg():
        data = bytearray()
        until = time.monotonic() + 4
        while time.monotonic() < until:
            if select.select([process.stdout], [], [], 0.05)[0]:
                chunk = os.read(process.stdout.fileno(), 65536)
                assert chunk, 'Relay closed before JPEG arrived'
                data.extend(chunk)
                if data.endswith(b'\xff\xd9'):
                    return bytes(data)
        raise AssertionError('Relay JPEG timed out')

    try:
        until = time.monotonic() + 5
        while publisher.get_subscription_count() == 0 and time.monotonic() < until:
            spin(0.05)
        assert publisher.get_subscription_count() == 1
        spin(0.3)  # Discovery can precede readiness of the best-effort data path.
        payloads = []
        for value in (25, 125, 225):
            ok, jpeg = cv2.imencode('.jpg', np.full((48, 64, 3), value, np.uint8))
            assert ok
            payloads.append(jpeg.tobytes())
        for _ in range(3):
            publisher.publish(CompressedImage(format='jpeg', data=payloads[0]))
            spin(0.05)
        assert read_jpeg() == payloads[0]
        for payload in payloads[1:]:
            publisher.publish(CompressedImage(format='jpeg', data=payload))
            spin(0.15)
        assert not select.select([process.stdout], [], [], 0.2)[0], 'Unacknowledged backlog'
        process.stdin.write(b'A')
        process.stdin.flush()
        assert read_jpeg() == payloads[-1]
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
        node.destroy_node()
        rclpy.shutdown()


def test_native_reader_and_mock_camera():
    rclpy.init()
    node = rclpy.create_node('native_vision_test')
    processes = []
    texts, evidence, images, detected = [], [], [], []
    node.create_subscription(String, '/test/status', lambda msg: texts.append(msg.data), 10)
    node.create_subscription(CompressedImage, '/test/evidence', evidence.append, 10)
    node.create_subscription(Bool, '/test/detected', lambda msg: detected.append(msg.data), 10)
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    node.create_subscription(CompressedImage, '/test/mock', images.append, qos)
    image_pub = node.create_publisher(CompressedImage, '/test/input', qos)
    state_pub = node.create_publisher(String, '/test/state', 10)
    trigger_pub = node.create_publisher(Bool, '/test/trigger', 10)

    def spin(seconds=0.2):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.02)

    def wait_for(condition, seconds=5):
        until = time.monotonic() + seconds
        while not condition() and time.monotonic() < until:
            spin(0.05)
        assert condition()

    def start_reader(snapshot=False):
        process = subprocess.Popen([
            os.environ['READER_EXECUTABLE'], '--ros-args',
            '-p', 'image_topic:=/test/input', '-p', 'status_topic:=/test/status',
            '-p', 'qr_image_topic:=/test/evidence', '-p', 'detected_topic:=/test/detected',
            '-p', 'mission_state_topic:=/test/state', '-p', 'trigger_topic:=/test/trigger',
            '-p', 'confirm_frames:=3', '-p', 'save_snapshot:=false',
            '-p', f'snapshot_mode:={str(snapshot).lower()}',
        ])
        processes.append(process)
        wait_for(lambda: image_pub.get_subscription_count() > 0)
        return process

    try:
        qr = cv2.QRCodeEncoder_create().encode('IJKbot native integration')
        qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        qr = cv2.resize(qr, (400, 400), interpolation=cv2.INTER_NEAREST)
        ok, jpeg = cv2.imencode('.jpg', qr)
        assert ok
        frame = CompressedImage(format='jpeg', data=jpeg.tobytes())
        reader = start_reader()
        frame.header.stamp.sec = 1
        for _ in range(4):
            image_pub.publish(frame)
            spin()
        assert not texts  # Unknown mission state is gated.
        state_pub.publish(String(data='READING_QR'))
        spin()
        image_pub.publish(frame)
        spin()
        for _ in range(3):  # Repeated timestamp must not confirm a single photo.
            image_pub.publish(frame)
            spin(0.1)
        assert not texts
        for stamp in (2, 3):
            frame.header.stamp.sec = stamp
            image_pub.publish(frame)
            spin()
        wait_for(lambda: texts and evidence)
        assert texts == ['IJKbot native integration']
        assert detected[-1]
        decoded = cv2.imdecode(np.frombuffer(bytes(evidence[0].data), np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == (400, 400, 3)
        reader.send_signal(signal.SIGINT)
        reader.wait(timeout=5)
        wait_for(lambda: image_pub.get_subscription_count() == 0)
        texts.clear()
        start_reader(snapshot=True)
        frame.header.stamp.sec = 4
        for _ in range(4):
            image_pub.publish(frame)
            spin(0.2)
        assert not texts
        trigger_pub.publish(Bool(data=True))
        wait_for(lambda: bool(texts))
        assert texts == ['IJKbot native integration']
        camera = subprocess.Popen([
            os.environ['CAMERA_EXECUTABLE'], '--ros-args',
            '-p', 'mock_hardware:=true', '-p', 'image_topic:=/test/mock', '-p', 'fps:=10',
        ])
        processes.append(camera)
        wait_for(lambda: len(images) >= 3)
        sample = cv2.imdecode(np.frombuffer(bytes(images[-1].data), np.uint8), cv2.IMREAD_COLOR)
        assert sample.shape == (480, 640, 3)
        assert images[-1].header.frame_id == 'camera_optical_frame'
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        node.destroy_node()
        rclpy.shutdown()


def test_one_shot_result_is_retained_and_camera_stops():
    rclpy.init()
    node = rclpy.create_node('one_shot_test')
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                          reliability=ReliabilityPolicy.RELIABLE)
    publisher = node.create_publisher(CompressedImage, '/test/once/input', qos)
    results, completed, frames, late_results, full_frames = [], [], [], [], []
    node.create_subscription(String, '/test/once/status', results.append, retained)
    node.create_subscription(Bool, '/test/once/complete', completed.append, retained)
    node.create_subscription(CompressedImage, '/test/once/camera', frames.append, qos)
    node.create_subscription(CompressedImage, '/test/once/full', full_frames.append, qos)
    processes = []

    def spin(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.02)

    try:
        camera = subprocess.Popen([
            os.environ['CAMERA_EXECUTABLE'], '--ros-args',
            '-p', 'mock_hardware:=true', '-p', 'image_topic:=/test/once/camera',
            '-p', 'stop_on_qr:=true', '-p', 'complete_topic:=/test/once/complete',
            '-p', 'width:=1296', '-p', 'height:=972',
            '-p', 'qr_image_topic:=/test/once/full', '-p', 'preview_fps:=4',
        ])
        processes.append(camera)
        reader = subprocess.Popen([
            os.environ['READER_EXECUTABLE'], '--ros-args',
            '-p', 'image_topic:=/test/once/input', '-p', 'status_topic:=/test/once/status',
            '-p', 'complete_topic:=/test/once/complete', '-p', 'one_shot:=true',
            '-p', 'state_filter_enabled:=false', '-p', 'save_snapshot:=false',
            '-p', 'confirm_frames:=3',
        ])
        processes.append(reader)
        until = time.monotonic() + 5
        while (publisher.get_subscription_count() == 0 or len(frames) < 3) and time.monotonic() < until:
            spin(0.05)
        assert publisher.get_subscription_count() == 1 and len(frames) >= 3
        assert full_frames
        full = cv2.imdecode(np.frombuffer(bytes(full_frames[-1].data), np.uint8), cv2.IMREAD_COLOR)
        preview = cv2.imdecode(np.frombuffer(bytes(frames[-1].data), np.uint8), cv2.IMREAD_COLOR)
        assert full.shape == (972, 1296, 3)
        assert preview.shape == (480, 640, 3)
        qr = cv2.QRCodeEncoder_create().encode('single session result')
        qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        qr = cv2.resize(qr, (400, 400), interpolation=cv2.INTER_NEAREST)
        ok, jpeg = cv2.imencode('.jpg', qr)
        assert ok
        message = CompressedImage(format='jpeg', data=jpeg.tobytes())
        for stamp in range(1, 9):
            message.header.stamp.sec = stamp
            publisher.publish(message)
            # Dense-code processing may span >1 s. Live distinct observations
            # must still confirm; the former one-second timer erased progress.
            spin(1.2 if stamp < 3 else 0.2)
        assert [item.data for item in results] == ['single session result']
        assert len(completed) == 1 and completed[0].data
        spin(0.5)  # Allow capture and already queued frames to drain.
        stopped_count = len(frames)
        stopped_full_count = len(full_frames)
        spin(0.5)
        assert len(frames) == stopped_count
        assert len(full_frames) == stopped_full_count
        # A laptop that reconnects after capture ended must still receive the result.
        node.create_subscription(String, '/test/once/status', late_results.append, retained)
        spin(0.5)
        assert [item.data for item in late_results] == ['single session result']
        assert reader.poll() is None and camera.poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        node.destroy_node()
        rclpy.shutdown()
