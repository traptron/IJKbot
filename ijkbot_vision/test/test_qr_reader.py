"""Exercise ROS callbacks without opening DDS sockets or camera devices."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from sensor_msgs.msg import CompressedImage

from ijkbot_vision.qr_decoder import QrConfirmation, QrDetection
from ijkbot_vision.qr_reader_node import QrReaderNode


def harness():
    return SimpleNamespace(
        _confirmation=QrConfirmation(3), _last_frame=0.0,
        _last_publication=0.0, _last_stamp=None, _last_logged_text=None,
        _status_publisher=Mock(), _detected_publisher=Mock(), get_logger=Mock(),
    )


def frame(node, stamp, now, result):
    message = CompressedImage()
    message.header.stamp.sec = stamp
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=now), \
            patch('ijkbot_vision.qr_reader_node.decode_jpeg', return_value=result):
        QrReaderNode._image_callback(node, message)


def test_republishes_for_late_subscriber_and_duplicate_frames_do_not_count():
    node = harness()
    result = QrDetection('text')
    frame(node, 1, 10.0, result)
    frame(node, 1, 10.1, result)
    frame(node, 2, 10.2, result)
    assert node._status_publisher.publish.call_count == 0
    frame(node, 3, 10.3, result)
    assert node._status_publisher.publish.call_count == 1
    for i in range(4, 18):
        frame(node, i, 10.0 + i * 0.1, result)
    assert node._status_publisher.publish.call_count == 2


def test_corrupt_frame_breaks_confirmation_and_silence_clears_detection():
    node = harness()
    result = QrDetection('text')
    frame(node, 1, 10.0, result)
    frame(node, 2, 10.1, result)
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=10.2), \
            patch('ijkbot_vision.qr_reader_node.decode_jpeg', side_effect=ValueError('bad')):
        QrReaderNode._image_callback(node, CompressedImage())
    frame(node, 4, 10.3, result)
    assert node._status_publisher.publish.call_count == 0
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=12):
        QrReaderNode._check_stream(node)
    assert node._detected_publisher.publish.call_args.args[0].data is False
    frame(node, 5, 12.1, result)
    assert node._status_publisher.publish.call_count == 0
