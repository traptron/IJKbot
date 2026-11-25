"""Grayscale input, ZXing QR decoding and confirmation without ROS dependencies."""

from math import isfinite
from typing import Any

import numpy as np


def image_to_gray(data: Any, width: int, height: int, step: int, encoding: str) -> np.ndarray:
    if encoding not in ('mono8', 'rgb8', 'bgr8'):
        raise ValueError(f'Unsupported image encoding: {encoding}')
    channels = 1 if encoding == 'mono8' else 3
    row_bytes = width * channels
    if width <= 0 or height <= 0 or step < row_bytes:
        raise ValueError('Invalid image dimensions or stride')
    buffer = np.frombuffer(data, dtype=np.uint8)
    if buffer.size != height * step:
        raise ValueError('Image buffer size does not match height × step')
    rows = buffer.reshape(height, step)[:, :row_bytes]
    if channels == 1:
        return rows

    pixels = rows.reshape(height, width, channels)
    red, blue = (0, 2) if encoding == 'rgb8' else (2, 0)
    luminance = np.multiply(pixels[..., red], 77, dtype=np.uint16)
    luminance += np.multiply(pixels[..., 1], 150, dtype=np.uint16)
    luminance += np.multiply(pixels[..., blue], 29, dtype=np.uint16)
    luminance += 128
    np.right_shift(luminance, 8, out=luminance)
    return luminance.astype(np.uint8)


class QrDecoder:
    def __init__(self, *, try_harder: bool = False, use_center_crop: bool = False,
                 center_crop_ratio: float = 0.7):
        if not 0 < center_crop_ratio <= 1:
            raise ValueError('center_crop_ratio must be in (0, 1]')
        # Keep confirmation and image conversion usable even without the optional decoder.
        import zxingcpp

        self._zxing = zxingcpp
        self.try_harder = try_harder
        self.use_center_crop = use_center_crop
        self.center_crop_ratio = center_crop_ratio

    @staticmethod
    def _area(barcode: Any) -> int:
        pos = barcode.position
        points = (pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left)
        return abs(sum(a.x * b.y - a.y * b.x for a, b in zip(points, points[1:] + points[:1])))

    def _read(self, image: Any) -> str | None:
        zxing = self._zxing
        settings = dict(formats=zxing.BarcodeFormat.QRCode, binarizer=zxing.Binarizer.LocalAverage,
                        try_rotate=True, try_downscale=True, text_mode=zxing.TextMode.Plain)
        codes = zxing.read_barcodes(image, **settings)
        if not codes and self.try_harder:
            # The Python binding keeps native tryHarder at its default (true).
            # The configurable extra pass enables ZXing's own denoising.
            codes = zxing.read_barcodes(image, **settings, try_denoise=True)
        best = max((code for code in codes if code.text.strip()), key=self._area, default=None)
        return best.text if best is not None else None

    def decode_image(self, data: Any, width: int, height: int, step: int, encoding: str) -> str | None:
        """Decode directly from a raw ROS image buffer without intermediate gray allocation."""
        zxing = self._zxing
        format_map = {
            'mono8': (1, zxing.ImageFormat.Lum),
            'rgb8': (3, zxing.ImageFormat.RGB),
            'bgr8': (3, zxing.ImageFormat.BGR),
        }
        if encoding not in format_map:
            raise ValueError(f'Unsupported image encoding: {encoding}')
        channels, image_format = format_map[encoding]
        row_bytes = width * channels
        if width <= 0 or height <= 0 or step < row_bytes:
            raise ValueError('Invalid image dimensions or stride')
        view = memoryview(data)
        if view.nbytes != height * step:
            raise ValueError('Image buffer size does not match height × step')
        if self.use_center_crop and self.center_crop_ratio < 1:
            crop_height = max(1, round(height * self.center_crop_ratio))
            crop_width = max(1, round(width * self.center_crop_ratio))
            y, x = (height - crop_height) // 2, (width - crop_width) // 2
            if (crop_height, crop_width) != (height, width):
                offset = y * step + x * channels
                crop_view = zxing.ImageView(view[offset:], crop_width, crop_height, image_format, step)
                text = self._read(crop_view)
                if text is not None:
                    return text
        return self._read(zxing.ImageView(view, width, height, image_format, step))

    def decode(self, gray: np.ndarray) -> str | None:
        if gray.ndim != 2 or gray.dtype != np.uint8 or not gray.size:
            raise ValueError('Expected a nonempty two-dimensional uint8 grayscale image')
        if self.use_center_crop and self.center_crop_ratio < 1:
            height, width = gray.shape
            crop_height = max(1, round(height * self.center_crop_ratio))
            crop_width = max(1, round(width * self.center_crop_ratio))
            y, x = (height - crop_height) // 2, (width - crop_width) // 2
            if (crop_height, crop_width) != gray.shape:
                text = self._read(gray[y:y + crop_height, x:x + crop_width])
                if text is not None:
                    return text
        return self._read(gray)


class QrConfirmation:
    def __init__(self, confirm_frames: int, reset_timeout_sec: float, *, reset_on_miss: bool = True):
        if confirm_frames < 1 or not isfinite(reset_timeout_sec) or reset_timeout_sec <= 0:
            raise ValueError('Expected positive confirm_frames and reset_timeout_sec')
        self.confirm_frames = confirm_frames
        self.reset_timeout_sec = reset_timeout_sec
        self.reset_on_miss = reset_on_miss
        self.reset()

    def reset(self) -> None:
        self._candidate: str | None = None
        self._count = 0
        self._published: str | None = None
        self._last_seen: float | None = None

    def expire(self, now: float) -> None:
        if self._last_seen is not None and now - self._last_seen >= self.reset_timeout_sec:
            self.reset()

    def observe(self, text: str | None, now: float) -> str | None:
        self.expire(now)
        if text is None or not text.strip():
            if self.reset_on_miss:
                self._candidate, self._count = None, 0
            return None
        self._last_seen = now
        if text != self._candidate:
            self._candidate, self._count = text, 0
        self._count += 1
        if self._count >= self.confirm_frames and text != self._published:
            self._published = text
            return text
        return None
