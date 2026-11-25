"""Exercise the mission trigger with real ROS message classes, without a camera."""

from types import SimpleNamespace

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('zxingcpp')

from sensor_msgs.msg import Image  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402
from vision import zxing_qr_node  # noqa: E402


def test_trigger_requires_fresh_distinct_frames_and_rearms_same_qr(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'require_trigger:=true'])
    node = None
    try:
        node = zxing_qr_node.ZxingQrReader()
        now = 10.0
        monkeypatch.setattr(zxing_qr_node, 'monotonic', lambda: now)
        monkeypatch.setattr(node._decoder, 'decode', lambda _: 'Состояние: стабильное')
        messages = []
        node._status = SimpleNamespace(publish=messages.append)

        def frame(stamp):
            image = Image(width=1, height=1, encoding='mono8', step=1, data=[255])
            image.header.stamp.sec, image.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
            node._on_image(image)
            node._process_latest()

        frame(node.get_clock().now().nanoseconds)
        assert messages == []

        for attempt in (1, 2):
            node._on_trigger(Bool(data=True))
            start = node._trigger_stamp
            frame(start - 1)
            frame(0)
            frame(start + 1)
            frame(start + 1)
            assert len(messages) == attempt - 1
            frame(start + 2)
            frame(start + 3)
            assert [message.data for message in messages] == ['Состояние: стабильное'] * attempt

        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        frame(start + 1)
        now += 1.0
        frame(start + 2)
        assert len(messages) == 2
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
