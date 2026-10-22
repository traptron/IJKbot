"""Image-level checks for the standalone City sign reader."""

import cv2
import numpy as np
import pytest

from vision.city_signs import _arrow, _bus, _parking, detect_signs


def make_sign(name: str) -> np.ndarray:
    frame = np.full((240, 320, 3), 175, dtype=np.uint8)
    cx, cy, radius = 160, 120, 48
    if name in ('parking', 'bus_stop'):
        cv2.rectangle(frame, (cx - radius, cy - radius),
                      (cx + radius, cy + radius), (220, 70, 5), -1)
        pictogram = _parking() if name == 'parking' else _bus()
        colour = (255, 255, 255)
    elif name.startswith('no_'):
        cv2.circle(frame, (cx, cy), radius, (255, 255, 255), -1)
        cv2.circle(frame, (cx, cy), radius, (20, 20, 225), 9)
        pictogram = _arrow(name[3:])
        colour = (15, 15, 15)
    else:
        cv2.circle(frame, (cx, cy), radius, (220, 70, 5), -1)
        pictogram = _arrow(name)
        colour = (255, 255, 255)
    symbol = cv2.resize(pictogram.astype(np.uint8), (96, 96),
                        interpolation=cv2.INTER_NEAREST).astype(bool)
    roi = frame[cy - radius:cy + radius, cx - radius:cx + radius]
    roi[symbol] = colour
    if name.startswith('no_'):
        cv2.line(frame, (cx - 33, cy + 33), (cx + 33, cy - 33),
                 (20, 20, 225), 7, cv2.LINE_AA)
    return frame


@pytest.mark.parametrize('name', [
    'straight', 'left', 'right', 'no_left', 'no_right', 'parking', 'bus_stop',
])
def test_detect_printed_style_sign(name):
    result = detect_signs(make_sign(name))
    assert result and result[0].name == name
    assert result[0].confidence >= 0.68


def test_ignores_plain_coloured_shapes():
    frame = np.full((240, 320, 3), 175, dtype=np.uint8)
    cv2.circle(frame, (90, 120), 48, (220, 70, 5), -1)
    cv2.rectangle(frame, (200, 72), (296, 168), (220, 70, 5), -1)
    assert detect_signs(frame) == []


def test_rejects_non_bgr_frame():
    with pytest.raises(ValueError):
        detect_signs(np.zeros((20, 20), dtype=np.uint8))
