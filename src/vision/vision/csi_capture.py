"""Bounded MJPEG framing and libcamera capture command (no ROS dependency)."""

RAW_FRAME_BYTES = 640 * 480 * 10 // 8


def correct_color(image, saturation_gain: float = 2.5):
    """Reduce channel cast and lift underexposed shadows without unbounded gain."""
    import cv2
    import numpy as np

    channel_means = image.mean(axis=(0, 1))
    reference = float(channel_means.mean())
    gains = np.clip(reference / np.maximum(channel_means, 1.0), 0.75, 1.35)
    balanced = np.clip(image.astype(np.float32) * gains, 0, 255).astype(np.uint8)

    luminance = cv2.cvtColor(balanced, cv2.COLOR_BGR2GRAY)
    mean_luminance = float(luminance.mean())
    if mean_luminance < 110.0:
        normalized_mean = max(mean_luminance / 255.0, 1.0 / 255.0)
        gamma = float(np.clip(np.log(0.5) / np.log(normalized_mean), 0.42, 0.88))
        lookup = np.array([
            round(((value / 255.0) ** gamma) * 255.0) for value in range(256)
        ], dtype=np.uint8)
        balanced = cv2.LUT(balanced, lookup)

    hsv = cv2.cvtColor(balanced, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = np.clip(
        hsv[:, :, 1].astype(np.float32) * saturation_gain, 0, 255
    ).astype(np.uint8)
    balanced = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return balanced


def raw10_to_jpeg(raw: bytes, quality: int) -> bytes:
    """Demosaic OV5647 packed GBRG10 and encode one bounded JPEG frame."""
    if len(raw) != RAW_FRAME_BYTES:
        raise ValueError('Incomplete 640x480 packed Bayer frame')
    import cv2
    import numpy as np

    groups = np.frombuffer(raw, dtype=np.uint8).reshape(480, 160, 5)
    bayer = groups[:, :, :4].reshape(480, 640)
    bgr = cv2.cvtColor(bayer, cv2.COLOR_BayerGBRG2BGR)
    bgr = correct_color(bgr)
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
        return ['v4l2-ctl', '-d', '/dev/video0',
            '--set-fmt-video=width=640,height=480,pixelformat=pGAA',
                '--stream-mmap=4',
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
