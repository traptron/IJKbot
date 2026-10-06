#!/usr/bin/env python3
"""Preview the Pi CSI camera and forward confirmed QR evidence to the ROS dashboard.

The SSH connection carries JPEG frames only. Start after sourcing ROS 2 and the
vision workspace; a passwordless SSH control socket or SSH key is required.
"""

import argparse
import os
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from vision.csi_capture import MjpegFramer
from vision.qr_decoder import annotate_qr_jpeg, decode_jpeg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_host = f"{os.environ.get('PI_USER', 'otmorozki')}@{os.environ.get('PI_HOST', os.environ.get('ROBOT_IP', '192.168.0.191'))}"
    parser.add_argument('--host', default=default_host)
    parser.add_argument('--socket', default='/tmp/ijkbot-camera-new.sock')
    parser.add_argument('--remote-script',
                        default='/home/otmorozki/IJKbot/scripts/csi_jpeg_stream.py')
    parser.add_argument('--no-window', action='store_true')
    args = parser.parse_args()

    rclpy.init()
    node = Node('qr_ssh_preview')
    image_pub = node.create_publisher(
        CompressedImage, '/camera/color/image_raw/compressed',
        QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
    evidence_pub = node.create_publisher(CompressedImage, '/vision/qr/image/compressed', 10)
    status_pub = node.create_publisher(String, '/victim_status', 10)
    process = subprocess.Popen([
        'ssh', '-S', args.socket, '-o', 'BatchMode=yes', args.host,
        'sudo', '-n', 'python3', args.remote_script,
    ], stdout=subprocess.PIPE)
    display = None
    if not args.no_window:
        display = subprocess.Popen([
            'gst-launch-1.0', '-q', 'fdsrc', '!', 'jpegparse', '!',
            'jpegdec', '!', 'videoconvert', '!', 'ximagesink', 'sync=false',
        ], stdin=subprocess.PIPE)

    lock = threading.Lock()
    stopped = threading.Event()
    latest = None
    last_text = None
    last_publication = 0.0

    def receive() -> None:
        nonlocal latest
        framer = MjpegFramer()
        try:
            while not stopped.is_set():
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                for jpeg in framer.feed(chunk):
                    message = CompressedImage()
                    message.header.stamp = node.get_clock().now().to_msg()
                    message.header.frame_id = 'camera_link'
                    message.format = 'jpeg'
                    message.data = jpeg
                    if not rclpy.ok():
                        return
                    image_pub.publish(message)
                    with lock:
                        latest = jpeg
                    if display is not None:
                        display.stdin.write(jpeg)
                        display.stdin.flush()
        except (BrokenPipeError, OSError, ValueError, RuntimeError) as error:
            if not stopped.is_set():
                node.get_logger().error(f'Camera stream stopped: {error}')
        finally:
            stopped.set()

    def recognize() -> None:
        nonlocal last_text, last_publication
        while not stopped.is_set():
            with lock:
                jpeg = latest
            if jpeg:
                try:
                    result = decode_jpeg(jpeg)
                    if result and (result.text != last_text
                                   or time.monotonic() - last_publication >= 2.0):
                        last_text = result.text
                        last_publication = time.monotonic()
                        status_pub.publish(String(data=result.text))
                        evidence = CompressedImage()
                        evidence.header.stamp = node.get_clock().now().to_msg()
                        evidence.header.frame_id = 'camera_link'
                        evidence.format = 'jpeg'
                        evidence.data = annotate_qr_jpeg(jpeg, result.corners)
                        evidence_pub.publish(evidence)
                        node.get_logger().info(f'QR подтверждён: {result.text}')
                except Exception as error:
                    node.get_logger().warning(f'QR decoder: {error}')
            stopped.wait(0.5)

    receive_thread = threading.Thread(target=receive, daemon=True)
    recognize_thread = threading.Thread(target=recognize, daemon=True)
    receive_thread.start()
    recognize_thread.start()
    try:
        while not stopped.is_set():
            if display is not None and display.poll() is not None:
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if display is not None:
            display.terminate()
            display.wait()
        receive_thread.join(timeout=2)
        recognize_thread.join(timeout=2)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
