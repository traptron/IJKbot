"""Exercise native ROS contracts, state gating, frame confirmation and snapshots."""
import os
import signal
import subprocess
import time

import cv2
import numpy as np
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String


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
