"""Exercise the mission trigger with real ROS message classes, without a camera."""

from types import SimpleNamespace

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('zxingcpp')

from sensor_msgs.msg import Image  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402
from vision import zxing_qr_node  # noqa: E402


def test_continuous_reader_republishes_after_mission_photo_reset(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'reset_topic:=/vision/take_photo'])
    node = None
    try:
        node = zxing_qr_node.ZxingQrReader()
        assert any(sub.topic_name == '/vision/take_photo' for sub in node.subscriptions)
        now = 10.0
        monkeypatch.setattr(zxing_qr_node, 'monotonic', lambda: now)
        monkeypatch.setattr(node._decoder, 'decode_image', lambda *_args: 'Состояние')
        messages = []
        node._status = SimpleNamespace(publish=messages.append)

        for stamp in range(1, 7):
            if stamp == 5:
                assert len(messages) == 1
                node._on_reset(Bool(data=True))
            now += 0.2
            image = Image(width=1, height=1, encoding='mono8', step=1, data=[255])
            image.header.stamp.sec = stamp
            node._on_image(image)

        assert [msg.data for msg in messages] == ['Состояние', 'Состояние']
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


def test_trigger_requires_fresh_distinct_frames_and_rearms_same_qr(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'require_trigger:=true'])
    node = None
    try:
        node = zxing_qr_node.ZxingQrReader()
        now = 10.0
        monkeypatch.setattr(zxing_qr_node, 'monotonic', lambda: now)
        monkeypatch.setattr(
            node._decoder, 'decode_image', lambda *_args: 'Состояние: стабильное')
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
            now += 0.2
            node._on_trigger(Bool(data=True))
            start = node._trigger_stamp
            frame(start - 200_000_000)
            frame(0)
            frame(start + 1)
            assert node._latest is None
            frame(start + 1)
            node._process_latest()
            assert len(messages) == attempt - 1
            # A second fresh frame arriving at the next camera interval can confirm immediately.
            now += 0.07
            frame(start + 2)
            frame(start + 3)
            assert [message.data for message in messages] == ['Состояние: стабильное'] * attempt

        now += 0.2
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        frame(start + 1)
        now += 1.41
        frame(start + 2)
        assert len(messages) == 2
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


def test_trigger_logs_stage_timings_and_timeout_reason(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'require_trigger:=true'])
    node = None
    try:
        node = zxing_qr_node.ZxingQrReader()
        now = 20.0
        infos, warnings = [], []
        monkeypatch.setattr(zxing_qr_node, 'monotonic', lambda: now)
        monkeypatch.setattr(node, 'get_logger', lambda: SimpleNamespace(
            info=infos.append, warning=warnings.append))
        node._status = SimpleNamespace(publish=lambda _msg: None)

        def send(stamp, text):
            monkeypatch.setattr(node._decoder, 'decode_image', lambda *_args: text)
            image = Image(width=1, height=1, encoding='mono8', step=1, data=[255])
            image.header.stamp.sec, image.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
            node._on_image(image)
            node._process_latest()

        # 1) Confirmed path logs trigger -> 1st fresh -> decode -> 2nd fresh -> published,
        #    and captures stale_frames + delta in ms when a pre-trigger frame is outside tolerance.
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        send(start - 150_000_000, 'QR-OLD')
        now += 0.04
        send(start + 1, 'QR-1')
        now += 0.07
        send(start + 2, 'QR-1')
        joined = '\n'.join(infos)
        assert 'QR trigger #1: start' in joined
        assert 'process_hz=30' in joined
        assert '1st fresh frame at +40.0 ms' in joined
        assert 'stale_frames=1, last_stale_dt=-150.0 ms' in joined
        assert 'frame #1 (1×1): hit=True' in joined
        assert '2nd fresh frame at +110.0 ms' in joined
        assert 'confirmed & published at +110.0 ms' in joined
        assert warnings == []

        # 2) Timeout with only 1 fresh frame logs explicit reason.
        now += 0.2
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        now += 0.05
        send(start + 1, 'QR-1')
        now += 1.40
        node._process_latest()
        assert len(warnings) == 1
        assert 'only 1 fresh frame arrived' in warnings[0]
        assert 'fresh=1, decoded=1, hits=1' in warnings[0]

        # 3) Timeout with 0 fresh frames and stale drops logs explicit reason and delta.
        now += 0.2
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        send(start - 120_000_000, 'QR-1')
        now += 1.41
        node._process_latest()
        assert len(warnings) == 2
        assert 'no fresh frames (only stale/pre-trigger frames arrived)' in warnings[1]
        assert 'stale_frames=1, last_stale_dt=-120.0 ms' in warnings[1]
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


def test_trigger_stamp_tolerance_and_miss_resilient_confirmation(monkeypatch):
    rclpy.init(args=['--ros-args', '-p', 'require_trigger:=true', '-p', 'trigger_stamp_tolerance_sec:=0.1'])
    node = None
    try:
        node = zxing_qr_node.ZxingQrReader()
        now = 30.0
        monkeypatch.setattr(zxing_qr_node, 'monotonic', lambda: now)
        published = []
        node._status = SimpleNamespace(publish=lambda msg: published.append(msg.data))

        def send(stamp, text):
            monkeypatch.setattr(node._decoder, 'decode_image', lambda *_args: text)
            image = Image(width=1, height=1, encoding='mono8', step=1, data=[255])
            image.header.stamp.sec, image.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
            node._on_image(image)
            node._process_latest()

        # Frame older than tolerance is rejected; frame within tolerance is accepted,
        # and [QR_A, None, QR_A] still confirms inside the active trigger window.
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        send(start - 100_000_001, 'QR_OLD')
        assert node._stale_frames == 1
        assert node._fresh_arrivals == 0
        now += 0.04
        send(start - 50_000_000, 'QR_A')
        now += 0.04
        send(start + 10_000_000, None)
        now += 0.04
        send(start + 50_000_000, 'QR_A')
        assert published == ['QR_A']

        # Different non-empty QR text resets streak: [QR_A, QR_B] does not confirm,
        # and a subsequent QR_B confirms QR_B.
        now += 0.2
        node._on_trigger(Bool(data=True))
        start = node._trigger_stamp
        now += 0.04
        send(start + 1, 'QR_A')
        now += 0.04
        send(start + 2, 'QR_B')
        assert published == ['QR_A']
        now += 0.04
        send(start + 3, 'QR_B')
        assert published == ['QR_A', 'QR_B']
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


def test_image_reliability_parameter_switches_qos():
    qos_profiles = []
    rclpy.init(args=['--ros-args', '-p', 'image_reliability:=reliable'])
    node = None
    try:
        orig_create_sub = zxing_qr_node.ZxingQrReader.create_subscription

        def capture_sub(self, msg_type, topic, callback, qos):
            if topic == '/camera/color/image_raw':
                qos_profiles.append(qos)
            return orig_create_sub(self, msg_type, topic, callback, qos)

        zxing_qr_node.ZxingQrReader.create_subscription = capture_sub
        try:
            node = zxing_qr_node.ZxingQrReader()
        finally:
            zxing_qr_node.ZxingQrReader.create_subscription = orig_create_sub
        assert len(qos_profiles) == 1
        assert qos_profiles[0].reliability == zxing_qr_node.ReliabilityPolicy.RELIABLE
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
