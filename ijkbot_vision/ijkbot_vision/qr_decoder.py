"""ROS-independent QR decoding and multi-frame confirmation helpers."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class QrDetection:
    """Text and pixel bounds returned by a QR decoder."""

    text: str
    corners: Optional[Tuple[Tuple[int, int], ...]] = None


class QrConfirmation:
    """Publishes only text seen unchanged in consecutive frames."""

    def __init__(self, required_frames: int = 3) -> None:
        if required_frames < 1:
            raise ValueError('required_frames must be at least 1')
        self.required_frames = required_frames
        self._candidate: Optional[str] = None
        self._count = 0
        self._published: Optional[str] = None

    def observe(self, text: Optional[str]) -> Optional[str]:
        """Return newly confirmed text once; return None otherwise."""
        normalized = text if text else ''
        if not normalized:
            self._candidate = None
            self._count = 0
            self._published = None
            return None

        if normalized == self._candidate:
            self._count += 1
        else:
            self._candidate = normalized
            self._count = 1

        if self._count >= self.required_frames and normalized != self._published:
            self._published = normalized
            return normalized
        return None

    def reset(self) -> None:
        """Forget confirmation after a stream gap or a publication interval."""
        self.observe(None)


def decode_jpeg(jpeg: bytes) -> Optional[QrDetection]:
    """Decode one QR code from JPEG bytes using OpenCV.

    Importing OpenCV here keeps pure confirmation tests runnable without it.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError('OpenCV and NumPy are required for QR decoding') from error

    if not jpeg:
        return None
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None

    detector = cv2.QRCodeDetector()
    text, points, _ = detector.detectAndDecode(image)
    scale = 1
    if not text and max(image.shape[:2]) < 640:
        # Small QR codes often survive JPEG transport but are below OpenCV's
        # detector sampling threshold. A nearest-neighbour retry preserves cells.
        scale = 4
        enlarged = cv2.resize(
            image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST
        )
        text, points, _ = detector.detectAndDecode(enlarged)

    if not text:
        return None

    corners = None
    if points is not None:
        corners = tuple(
            (int(x / scale), int(y / scale)) for x, y in points.reshape(-1, 2)
        )
    return QrDetection(text=text, corners=corners)
