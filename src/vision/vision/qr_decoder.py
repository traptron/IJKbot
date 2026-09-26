"""ROS-independent QR decoding and multi-frame confirmation helpers."""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

_WECHAT_DETECTOR = None
_QR_DETECTOR = None


@dataclass(frozen=True)
class QrDetection:
    """Text and pixel bounds returned by a QR decoder."""

    text: str
    corners: Optional[Tuple[Tuple[int, int], ...]] = None
    annotated_jpeg: Optional[bytes] = None


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


def _get_cv2_and_np():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError as error:
        raise RuntimeError('OpenCV and NumPy are required for QR decoding') from error


def get_wechat_detector():
    """Lazily load WeChatQRCode detector if supported by OpenCV."""
    global _WECHAT_DETECTOR
    if _WECHAT_DETECTOR is None:
        cv2, _ = _get_cv2_and_np()
        if hasattr(cv2, 'wechat_qrcode_WeChatQRCode'):
            try:
                _WECHAT_DETECTOR = cv2.wechat_qrcode_WeChatQRCode()
            except Exception:
                _WECHAT_DETECTOR = None
    return _WECHAT_DETECTOR


def get_fallback_detector():
    """Lazily load standard OpenCV QRCodeDetector as fallback."""
    global _QR_DETECTOR
    if _QR_DETECTOR is None:
        cv2, _ = _get_cv2_and_np()
        if hasattr(cv2, 'QRCodeDetector'):
            try:
                _QR_DETECTOR = cv2.QRCodeDetector()
            except Exception:
                _QR_DETECTOR = None
    return _QR_DETECTOR


def annotate_qr_image(
    image,
    corners: Optional[Sequence[Tuple[int, int]]],
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 3,
):
    """Draw a green bounding box around QR corners on a BGR image."""
    cv2, np = _get_cv2_and_np()
    if image is None:
        return None
    annotated = image.copy()
    if annotated.ndim == 2 or (annotated.ndim == 3 and annotated.shape[2] == 1):
        annotated = cv2.cvtColor(annotated, cv2.COLOR_GRAY2BGR)
    if corners and len(corners) >= 3:
        try:
            pts = np.array(corners, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=thickness)
        except Exception:
            pass
    return annotated


draw_qr_border = annotate_qr_image


def annotate_qr_jpeg(
    jpeg: bytes,
    corners: Optional[Sequence[Tuple[int, int]]],
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 3,
) -> Optional[bytes]:
    """Decode JPEG, draw green border along corners, re-encode as JPEG bytes."""
    if not jpeg:
        return None
    cv2, np = _get_cv2_and_np()
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    annotated = annotate_qr_image(image, corners, color=color, thickness=thickness)
    ok, encoded = cv2.imencode('.jpg', annotated)
    if not ok:
        return None
    return bytes(encoded)


def decode_jpeg(jpeg: bytes) -> Optional[QrDetection]:
    """Decode one QR code from JPEG bytes using WeChatQRCode with QRCodeDetector fallback.

    Importing OpenCV lazily keeps pure confirmation tests runnable without it.
    """
    if not jpeg:
        return None
    cv2, np = _get_cv2_and_np()

    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None

    text = ''
    points = None
    scale = 1

    # 1. Попытка детекции через WeChatQRCode (Дефект D07: устойчив к наклонам >5°, бликам и смазам)
    wechat = get_wechat_detector()
    if wechat is not None:
        try:
            texts, pts_list = wechat.detectAndDecode(image)
            if texts and pts_list:
                for t, pts in zip(texts, pts_list):
                    if t:
                        text = t
                        points = pts
                        break
        except Exception:
            text = ''
            points = None

        # Дефект D12: исправление масштабирования мелких кодов на дистанции
        if not text and (image.shape[0] <= 640 or image.shape[1] <= 640):
            for s in (2, 4):
                try:
                    enlarged = cv2.resize(
                        image, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST
                    )
                    texts, pts_list = wechat.detectAndDecode(enlarged)
                    if texts and pts_list:
                        for t, pts in zip(texts, pts_list):
                            if t:
                                text = t
                                points = pts
                                scale = s
                                break
                        if text:
                            break
                except Exception:
                    pass

    # 2. Fallback на cv2.QRCodeDetector, если WeChat недоступен или не декодировал
    if not text:
        fallback = get_fallback_detector()
        if fallback is not None:
            try:
                t, pts, _ = fallback.detectAndDecode(image)
                if t:
                    text = t
                    points = pts
                    scale = 1
            except Exception:
                pass

            # Дефект D12 для fallback детектора
            if not text and (image.shape[0] <= 640 or image.shape[1] <= 640):
                for s in (2, 4):
                    try:
                        enlarged = cv2.resize(
                            image, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST
                        )
                        t, pts, _ = fallback.detectAndDecode(enlarged)
                        if t:
                            text = t
                            points = pts
                            scale = s
                            break
                    except Exception:
                        pass

    if not text:
        return None

    corners = None
    if points is not None:
        try:
            corners = tuple(
                (int(round(float(x) / scale)), int(round(float(y) / scale)))
                for x, y in points.reshape(-1, 2)
            )
        except Exception:
            corners = None

    annotated_jpeg = None
    if corners is not None:
        try:
            annotated_img = annotate_qr_image(image, corners)
            ok, enc = cv2.imencode('.jpg', annotated_img)
            if ok:
                annotated_jpeg = bytes(enc)
        except Exception:
            annotated_jpeg = None

    return QrDetection(text=text, corners=corners, annotated_jpeg=annotated_jpeg)
