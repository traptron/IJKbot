"""Check pipe boundaries, bounded buffering and QR compatibility."""

import pytest

from vision.csi_capture import RAW_FRAME_BYTES, MjpegFramer, capture_command, raw10_to_jpeg
from vision.qr_decoder import decode_jpeg


def test_split_markers_and_multiple_frames():
    framer = MjpegFramer()
    assert framer.feed(b'noise\xff') == []
    assert framer.feed(b'\xd8one\xff') == []
    assert framer.feed(b'\xd9\xff\xd8two\xff\xd9') == [
        b'\xff\xd8one\xff\xd9', b'\xff\xd8two\xff\xd9']


def test_bounded_corrupt_frame_and_recovery():
    framer = MjpegFramer(max_bytes=20)
    with pytest.raises(ValueError):
        framer.feed(b'\xff\xd8' + b'x' * 30)
    assert framer.feed(b'\xff\xd8ok\xff\xd9') == [b'\xff\xd8ok\xff\xd9']
    framer.feed(b'noise' * 100)
    assert len(framer.buffer) <= 1


def test_invalid_capture_parameters():
    for fps, quality in [(0, 85), (16, 85), (10, 0), (10, 101)]:
        with pytest.raises(ValueError):
            capture_command(fps, quality)


def test_mock_does_not_open_camera():
    command = capture_command(10, 85, mock_hardware=True)
    assert 'videotestsrc' in command
    assert 'libcamerasrc' not in command


def test_raw_ov5647_frame_to_jpeg():
    cv2 = pytest.importorskip('cv2')
    raw = bytes([100, 110, 120, 130, 0]) * (RAW_FRAME_BYTES // 5)
    jpeg = raw10_to_jpeg(raw, 85)
    assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
    assert 'v4l2-ctl' == capture_command(10, 85, backend='v4l2_raw')[0]
    with pytest.raises(ValueError):
        raw10_to_jpeg(raw[:-1], 85)


def test_camera_name_is_one_argument():
    name = '/base/sensor name'
    assert 'camera-name=' + name in capture_command(10, 85, name)


def test_fragmented_camera_jpeg_reaches_qr_decoder():
    cv2 = pytest.importorskip('cv2')
    if not hasattr(cv2, 'QRCodeEncoder_create'):
        pytest.skip('OpenCV QR encoder unavailable')
    image = cv2.QRCodeEncoder_create().encode('IJKbot CSI QR')
    image = cv2.copyMakeBorder(image, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    image = cv2.resize(image, (464, 464), interpolation=cv2.INTER_NEAREST)
    ok, jpeg = cv2.imencode('.jpg', image)
    assert ok
    framer = MjpegFramer()
    frames = []
    data = jpeg.tobytes()
    for i in range(0, len(data), 37):
        frames.extend(framer.feed(data[i:i + 37]))
    assert len(frames) == 1
    result = decode_jpeg(frames[0])
    assert result is not None and result.text == 'IJKbot CSI QR'
