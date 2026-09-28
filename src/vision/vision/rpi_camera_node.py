#!/usr/bin/env python3
"""Publish CSI camera JPEGs without blocking the ROS executor."""

import os
import selectors
import shutil
import subprocess
import threading
import time
from typing import Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage

from .csi_capture import RAW_FRAME_BYTES, MjpegFramer, capture_command, raw10_to_jpeg


class RpiCameraNode(Node):
    """Keep only the latest JPEG; restart failed or stalled capture processes."""

    def __init__(self) -> None:
        super().__init__('rpi_camera_node')
        self.declare_parameter('image_topic', '/camera/color/image_raw/compressed')
        self.declare_parameter('frame_id', 'camera_optical_frame')
        self.declare_parameter('camera_name', '')
        self.declare_parameter('fps', 10)
        self.declare_parameter('jpeg_quality', 85)
        self.declare_parameter('mock_hardware', False)
        self.declare_parameter('backend', 'v4l2_raw')
        self.declare_parameter('exposure', 2500)
        self.declare_parameter('analogue_gain', 320)
        fps = int(self.get_parameter('fps').value)
        self._quality = int(self.get_parameter('jpeg_quality').value)
        self._v4l2_backend = (
            str(self.get_parameter('backend').value) == 'v4l2_raw'
            and not bool(self.get_parameter('mock_hardware').value))
        self._command = capture_command(
            fps, self._quality,
            str(self.get_parameter('camera_name').value),
            bool(self.get_parameter('mock_hardware').value),
            str(self.get_parameter('backend').value))
        if not shutil.which(self._command[0]):
            raise RuntimeError(f'Camera capture program missing: {self._command[0]}')
        self._frame_id = str(self.get_parameter('frame_id').value)
        topic = str(self.get_parameter('image_topic').value)
        self._publisher = self.create_publisher(CompressedImage, topic, qos_profile_sensor_data)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[CompressedImage] = None
        self._timer = self.create_timer(1.0 / fps, self._publish_latest)
        self._worker = threading.Thread(target=self._capture, name='csi-capture', daemon=True)
        self._worker.start()
        self.get_logger().info(f'CSI camera: JPEG 640x480 at {fps} fps -> {topic}')

    def _publish_latest(self) -> None:
        with self._lock:
            message, self._latest = self._latest, None
        if message is not None:
            self._publisher.publish(message)

    def _capture(self) -> None:
        while not self._stop.is_set():
            process = None
            try:
                if self._v4l2_backend:
                    exposure = int(self.get_parameter('exposure').value)
                    gain = int(self.get_parameter('analogue_gain').value)
                    if not 4 <= exposure <= 3145 or not 16 <= gain <= 1023:
                        raise ValueError('OV5647 exposure or analogue_gain out of range')
                    subprocess.run([
                        'v4l2-ctl', '-d', '/dev/v4l-subdev0',
                        f'--set-ctrl=exposure={exposure},analogue_gain={gain}',
                    ], check=True, capture_output=True)
                # argv list, no shell; camera errors remain visible in the launch log.
                process = subprocess.Popen(
                    self._command, stdout=subprocess.PIPE, bufsize=0,
                    stderr=subprocess.DEVNULL if self._v4l2_backend else None)
                parser = MjpegFramer() if not self._v4l2_backend else None
                frame_buffer = bytearray()
                last_frame = time.monotonic()
                first_frame = True
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while not self._stop.is_set():
                        if time.monotonic() - last_frame > 5.0:
                            raise RuntimeError('No camera frames for 5 seconds')
                        if not selector.select(timeout=0.2):
                            continue
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError('Camera capture closed its output')
                        if self._v4l2_backend:
                            frame_buffer.extend(chunk)
                            frames = []
                            while len(frame_buffer) >= RAW_FRAME_BYTES:
                                frames.append(raw10_to_jpeg(
                                    bytes(frame_buffer[:RAW_FRAME_BYTES]), self._quality))
                                del frame_buffer[:RAW_FRAME_BYTES]
                        else:
                            frames = parser.feed(chunk)
                        if not frames:
                            continue
                        last_frame = time.monotonic()
                        message = CompressedImage()
                        message.header.stamp = self.get_clock().now().to_msg()
                        message.header.frame_id = self._frame_id
                        message.format = 'jpeg'
                        message.data = frames[-1]
                        with self._lock:
                            self._latest = message
                        if first_frame:
                            self.get_logger().info('Camera stream active: first JPEG received')
                            first_frame = False
            except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
                if not self._stop.is_set():
                    self.get_logger().error(f'CSI capture failed: {error}; retry in 2 seconds')
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    process.wait()
                    if process.stdout is not None:
                        process.stdout.close()
                with self._lock:
                    self._latest = None
            self._stop.wait(2.0)

    def destroy_node(self):
        self._timer.cancel()
        self._stop.set()
        self._worker.join()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = RpiCameraNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
