"""Exercise ROS callbacks without opening DDS sockets or camera devices."""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, String

from ijkbot_vision.qr_decoder import QrConfirmation, QrDetection
from ijkbot_vision.qr_reader_node import QrReaderNode


def harness(confirm_frames=3, state_filter_enabled=False, snapshot_mode=False, log_dir='log'):
    node = SimpleNamespace(
        _confirmation=QrConfirmation(confirm_frames),
        _last_frame=0.0,
        _last_publication=0.0,
        _last_stamp=None,
        _last_logged_text=None,
        _status_publisher=Mock(),
        _detected_publisher=Mock(),
        _qr_image_publisher=Mock(),
        get_logger=Mock(),
        _latest_image_msg=None,
        _snapshot_mode=snapshot_mode,
        _state_filter_enabled=state_filter_enabled,
        _current_mission_state=None,
        _allowed_states=('SEARCHING_VICTIM', 'READING_QR'),
        _save_snapshot=False,
        _log_dir=log_dir,
    )
    node._process_image = QrReaderNode._process_image.__get__(node)
    node._save_qr_snapshot = QrReaderNode._save_qr_snapshot.__get__(node)
    return node


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


def test_confirm_frames_one_confirms_immediately_d08():
    """Defect D08: confirm_frames=1 publishes immediately on first frame."""
    node = harness(confirm_frames=1)
    result = QrDetection('immediate_victim', corners=((0, 0), (10, 0), (10, 10), (0, 10)))
    frame(node, 1, 10.0, result)
    assert node._status_publisher.publish.call_count == 1
    assert node._status_publisher.publish.call_args.args[0].data == 'immediate_victim'
    assert node._qr_image_publisher.publish.call_count == 1


def test_stream_filtering_by_mission_state():
    """Frames processed only when state is SEARCHING_VICTIM or READING_QR."""
    node = harness(confirm_frames=1, state_filter_enabled=True)
    result = QrDetection('filtered_victim')

    # Initial state is None -> skipped
    frame(node, 1, 10.0, result)
    assert node._status_publisher.publish.call_count == 0

    # Non-target states -> skipped
    for non_target in ('PREPARATION', 'LLM_PARSING', 'NAVIGATING_TO_LANDMARK', 'RETURNING_HOME'):
        QrReaderNode._mission_state_callback(node, String(data=non_target))
        frame(node, 2, 10.1, result)
        assert node._status_publisher.publish.call_count == 0

    # SEARCHING_VICTIM -> processed
    QrReaderNode._mission_state_callback(node, String(data='SEARCHING_VICTIM'))
    frame(node, 3, 10.2, result)
    assert node._status_publisher.publish.call_count == 1
    assert node._status_publisher.publish.call_args.args[0].data == 'filtered_victim'

    # READING_QR -> processed
    result2 = QrDetection('reading_victim')
    QrReaderNode._mission_state_callback(node, String(data='READING_QR'))
    frame(node, 4, 11.5, result2)
    assert node._status_publisher.publish.call_count == 2
    assert node._status_publisher.publish.call_args.args[0].data == 'reading_victim'


def test_photo_trigger_bypasses_state_filter():
    """Trigger topic forces processing of the latest frame regardless of mission state."""
    node = harness(confirm_frames=1, state_filter_enabled=True)
    QrReaderNode._mission_state_callback(node, String(data='PREPARATION'))
    result = QrDetection('triggered_victim')

    message = CompressedImage()
    message.header.stamp.sec = 1
    QrReaderNode._image_callback(node, message)
    # Filtered out during image callback
    assert node._status_publisher.publish.call_count == 0
    assert node._latest_image_msg is not None

    # Trigger fired
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=10.0), \
            patch('ijkbot_vision.qr_reader_node.decode_jpeg', return_value=result):
        QrReaderNode._trigger_callback(node, Bool(data=True))

    assert node._status_publisher.publish.call_count == 1
    assert node._status_publisher.publish.call_args.args[0].data == 'triggered_victim'


def test_snapshot_saved_to_disk_on_confirmation():
    """Saving annotated snapshot to disk in log/qr_snapshot_<timestamp>.jpg."""
    with tempfile.TemporaryDirectory() as tmpdir:
        node = harness(confirm_frames=1, log_dir=tmpdir)
        node._save_snapshot = True
        fake_jpeg = b'\xff\xd8\xff\xe0fakejpegimagecontent'
        result = QrDetection('disk_victim', corners=((0, 0), (10, 0), (10, 10), (0, 10)), annotated_jpeg=fake_jpeg)

        frame(node, 1, 10.0, result)

        files = os.listdir(tmpdir)
        assert len(files) == 1
        assert files[0].startswith('qr_snapshot_') and files[0].endswith('.jpg')
        with open(os.path.join(tmpdir, files[0]), 'rb') as f:
            assert f.read() == fake_jpeg


def test_trigger_forces_processing_on_identical_stamp():
    """Trigger forces processing of the latest frame even if its stamp matches _last_stamp."""
    node = harness(confirm_frames=1, state_filter_enabled=False)
    fake_jpeg = b'\xff\xd8\xff\xe0frame'
    result = QrDetection('forced_victim')

    message = CompressedImage()
    message.header.stamp.sec = 100
    message.header.stamp.nanosec = 0
    message.data = fake_jpeg

    # First normal frame arrived and processed with None
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=1.0), \
         patch('ijkbot_vision.qr_reader_node.decode_jpeg', return_value=None):
        QrReaderNode._image_callback(node, message)

    assert node._status_publisher.publish.call_count == 0
    assert node._last_stamp == (100, 0)

    # Now take_photo trigger fires on the same frame
    with patch('ijkbot_vision.qr_reader_node.time.monotonic', return_value=1.5), \
         patch('ijkbot_vision.qr_reader_node.decode_jpeg', return_value=result):
        QrReaderNode._trigger_callback(node, Bool(data=True))

    assert node._status_publisher.publish.call_count == 1
    assert node._status_publisher.publish.call_args.args[0].data == 'forced_victim'


def test_snapshot_disk_deduplication_on_continuous_frames():
    """Continuous frames of the same QR do not create multiple duplicate snapshot files on disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        node = harness(confirm_frames=1, log_dir=tmpdir)
        node._save_snapshot = True
        fake_jpeg = b'\xff\xd8\xff\xe0fakejpeg'
        result = QrDetection('victim_dedup', corners=((0, 0), (10, 0), (10, 10), (0, 10)), annotated_jpeg=fake_jpeg)

        # Frame 1 at t=10.0
        frame(node, 1, 10.0, result)
        assert len(os.listdir(tmpdir)) == 1

        # Frame 2 at t=11.1 (1.1s later, repeat_due triggers re-publication)
        frame(node, 2, 11.1, result)
        # Should still be only 1 snapshot on disk for this victim
        assert len(os.listdir(tmpdir)) == 1

        # Different victim scanned later -> saves new snapshot
        result2 = QrDetection('victim_2', corners=((0, 0), (10, 0), (10, 10), (0, 10)), annotated_jpeg=fake_jpeg)
        frame(node, 3, 12.2, result2)
        assert len(os.listdir(tmpdir)) == 2


def test_custom_relative_log_dir_respected():
    """Custom relative log directory is respected and not hijacked to repo root log/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a relative path within tmpdir
        rel_sub = os.path.join(tmpdir, 'my_custom_logs')
        node = harness(confirm_frames=1, log_dir=rel_sub)
        node._save_snapshot = True
        fake_jpeg = b'\xff\xd8\xff\xe0fake'
        result = QrDetection('rel_victim', corners=((0, 0), (10, 0), (10, 10), (0, 10)), annotated_jpeg=fake_jpeg)

        frame(node, 1, 10.0, result)

        assert os.path.isdir(rel_sub)
        files = os.listdir(rel_sub)
        assert len(files) == 1
        assert files[0].startswith('qr_snapshot_')


def test_state_transition_out_of_search_clears_candidate():
    """Transitioning from SEARCHING_VICTIM to RETURNING_HOME resets candidate state."""
    node = harness(confirm_frames=2, state_filter_enabled=True)
    QrReaderNode._mission_state_callback(node, String(data='SEARCHING_VICTIM'))
    result = QrDetection('partial_candidate')

    # Frame 1 sets candidate
    frame(node, 1, 10.0, result)
    assert node._confirmation._candidate == 'partial_candidate'

    # State changes to RETURNING_HOME
    QrReaderNode._mission_state_callback(node, String(data='RETURNING_HOME'))
    assert node._confirmation._candidate is None
    assert node._last_stamp is None
