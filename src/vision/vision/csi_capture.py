"""Bounded MJPEG framing and libcamera capture command (no ROS dependency)."""

RAW_FRAME_BYTES = 640 * 480 * 10 // 8


def raw10_to_jpeg(raw: bytes, quality: int) -> bytes:
    """Demosaic OV5647 packed GBRG10 and encode one bounded JPEG frame."""
    if len(raw) != RAW_FRAME_BYTES:
        raise ValueError('Incomplete 640x480 packed Bayer frame')
    import cv2
    import numpy as np

    groups = np.frombuffer(raw, dtype=np.uint8).reshape(480, 160, 5)
    # The first four bytes of each MIPI RAW10 group contain the high eight bits.
    bayer = groups[:, :, :4].reshape(480, 640)
    bgr = cv2.cvtColor(bayer, cv2.COLOR_BayerGBRG2BGR)
    ok, encoded = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError('Camera JPEG encoding failed')
    return encoded.tobytes()


class MjpegFramer:
    """Split camera JPEG frames even when markers cross pipe read boundaries."""

    def __init__(self, max_bytes: int = 2_000_000) -> None:
        self.buffer = bytearray()
        self.max_bytes = max_bytes

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        frames = []
        while self.buffer:
            start = self.buffer.find(b'\xff\xd8')
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == b'\xff' else b''
                break
            del self.buffer[:start]
            end = self.buffer.find(b'\xff\xd9', 2)
            if end < 0:
                if len(self.buffer) > self.max_bytes:
                    self.buffer.clear()
                    raise ValueError('Camera JPEG exceeds bounded capture buffer')
                break
            if end + 2 > self.max_bytes:
                self.buffer.clear()
                raise ValueError('Camera JPEG exceeds bounded capture buffer')
            frames.append(bytes(self.buffer[:end + 2]))
            del self.buffer[:end + 2]
        return frames


def capture_command(fps: int, quality: int, camera_name: str = '',
                    mock_hardware: bool = False,
                    backend: str = 'libcamera') -> list[str]:
    """Use libcamera for CSI; mock mode uses a GStreamer test pattern."""
    if not 1 <= fps <= 15 or not 1 <= quality <= 100:
        raise ValueError('fps must be 1..15 and jpeg_quality must be 1..100')
    if backend not in ('libcamera', 'v4l2_raw'):
        raise ValueError('backend must be libcamera or v4l2_raw')
    if backend == 'v4l2_raw' and not mock_hardware:
        return ['v4l2-ctl', '-d', '/dev/video0', '--stream-mmap=4',
                '--stream-to=/dev/stdout']
    source = ['videotestsrc', 'is-live=true'] if mock_hardware else ['libcamerasrc']
    if camera_name and not mock_hardware:
        if any(char in camera_name for char in '\n\r\0'):
            raise ValueError('Invalid camera_name')
        source.append('camera-name=' + camera_name)
    return [
        'gst-launch-1.0', '-q', *source, '!',
        f'video/x-raw,width=640,height=480,framerate={fps}/1', '!',
        'videoconvert', '!', 'video/x-raw,format=I420', '!',
        'jpegenc', f'quality={quality}', '!', 'fdsink', 'fd=1',
    ]
