"""Bounded MJPEG framing and libcamera capture command (no ROS dependency)."""


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
                    mock_hardware: bool = False) -> list[str]:
    """Use libcamera for CSI; mock mode uses a GStreamer test pattern."""
    if not 1 <= fps <= 15 or not 1 <= quality <= 100:
        raise ValueError('fps must be 1..15 and jpeg_quality must be 1..100')
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
