"""Classify the printed road signs used by the City arena from a colour frame.

The detector deliberately returns no result for weak or ambiguous matches. A
wrong turn sign is more dangerous than an unrecognised one. Templates encode
the five direction signs and the two pickup/drop-off signs in the regulation;
all matching runs locally and needs no network or model download.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


SIGN_NAMES = (
    'straight', 'left', 'right', 'no_left', 'no_right',
    'bus_stop', 'parking',
)


@dataclass(frozen=True)
class SignDetection:
    """One image-space road sign candidate with a conservative score."""

    name: str
    confidence: float
    bbox: Tuple[int, int, int, int]


def _arrow(direction: str, size: int = 64) -> np.ndarray:
    """Canonical white/black pictogram, excluding its coloured border."""
    canvas = np.zeros((size, size), dtype=np.uint8)
    if direction == 'straight':
        cv2.arrowedLine(canvas, (32, 54), (32, 11), 255, 9, cv2.LINE_AA, 0, 0.40)
    else:
        end_x = 12 if direction == 'left' else 52
        cv2.line(canvas, (32, 54), (32, 29), 255, 9, cv2.LINE_AA)
        cv2.arrowedLine(canvas, (32, 29), (end_x, 29), 255, 9,
                        cv2.LINE_AA, 0, 0.55)
    return canvas > 127


def _parking(size: int = 64) -> np.ndarray:
    canvas = np.zeros((size, size), dtype=np.uint8)
    cv2.putText(canvas, 'P', (14, 51), cv2.FONT_HERSHEY_SIMPLEX, 1.7,
                255, 8, cv2.LINE_AA)
    return canvas > 127


def _bus(size: int = 64) -> np.ndarray:
    canvas = np.zeros((size, size), dtype=np.uint8)
    cv2.rectangle(canvas, (11, 20), (53, 43), 255, -1)
    cv2.rectangle(canvas, (16, 24), (28, 34), 0, -1)
    cv2.rectangle(canvas, (33, 24), (48, 34), 0, -1)
    cv2.circle(canvas, (19, 46), 5, 255, -1)
    cv2.circle(canvas, (45, 46), 5, 255, -1)
    return canvas > 127


_ARROWS = {name: _arrow(name) for name in ('straight', 'left', 'right')}
_SQUARES = {'parking': _parking(), 'bus_stop': _bus()}


def _similarity(observed: np.ndarray, template: np.ndarray) -> float:
    """Tolerate a few pixels of print/pose error without rewarding solid blobs."""
    observed = observed.astype(np.uint8)
    template = template.astype(np.uint8)
    if cv2.countNonZero(observed) < 35:
        return 0.0
    kernel = np.ones((5, 5), dtype=np.uint8)
    near_template = cv2.dilate(template, kernel)
    near_observed = cv2.dilate(observed, kernel)
    precision = np.count_nonzero(observed & near_template) / np.count_nonzero(observed)
    recall = np.count_nonzero(template & near_observed) / np.count_nonzero(template)
    return float(2 * precision * recall / (precision + recall + 1e-9))


def _classify_symbol(
    crop: np.ndarray, colour: str, round_sign: bool,
    minimum_score: float, ambiguity_margin: float,
) -> Optional[Tuple[str, float]]:
    symbol = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(symbol, cv2.COLOR_BGR2HSV)
    if colour == 'blue':
        observed = (hsv[:, :, 1] < 95) & (hsv[:, :, 2] > 135)
        templates = _ARROWS if round_sign else _SQUARES
    else:
        # Red no-turn signs have a dark arrow on white, crossed by a red bar.
        observed = (hsv[:, :, 1] < 100) & (hsv[:, :, 2] < 125)
        templates = {name: _ARROWS[name] for name in ('left', 'right')}
    observed[:7, :] = False
    observed[-7:, :] = False
    observed[:, :7] = False
    observed[:, -7:] = False
    scores = sorted(
        ((_similarity(observed, mask), name) for name, mask in templates.items()),
        reverse=True,
    )
    if not scores or scores[0][0] < minimum_score:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < ambiguity_margin:
        return None
    name = scores[0][1]
    if colour == 'red':
        name = 'no_' + name
    return name, scores[0][0]


def detect_signs(
    image: np.ndarray, minimum_score: float = 0.68,
    ambiguity_margin: float = 0.08,
) -> List[SignDetection]:
    """Find road signs in a BGR frame; reject uncertain shapes and pictograms."""
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Expected a BGR image with three channels')
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = {
        'blue': cv2.inRange(hsv, (90, 75, 45), (135, 255, 255)),
        'red': cv2.bitwise_or(
            cv2.inRange(hsv, (0, 85, 55), (12, 255, 255)),
            cv2.inRange(hsv, (168, 85, 55), (179, 255, 255)),
        ),
    }
    detections: List[SignDetection] = []
    height, width = image.shape[:2]
    for colour, mask in masks.items():
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                np.ones((3, 3), dtype=np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if min(w, h) < 22 or max(w, h) > min(width, height) * 0.65:
                continue
            if not 0.72 <= w / h <= 1.28:
                continue
            area = cv2.contourArea(contour)
            if area < 180 or area / (w * h) < 0.28:
                continue
            radius = cv2.minEnclosingCircle(contour)[1]
            round_sign = radius > 0 and area / (np.pi * radius * radius) > 0.72
            if colour == 'red' and not round_sign:
                continue
            pad = int(round(max(w, h) * 0.03))
            left, top = max(0, x - pad), max(0, y - pad)
            right, bottom = min(width, x + w + pad), min(height, y + h + pad)
            result = _classify_symbol(
                image[top:bottom, left:right], colour, round_sign,
                minimum_score, ambiguity_margin,
            )
            if result is not None:
                name, confidence = result
                detections.append(SignDetection(name, confidence,
                                                (left, top, right, bottom)))
    return sorted(detections, key=lambda item: item.confidence, reverse=True)


def annotate(image: np.ndarray, detections: List[SignDetection]) -> np.ndarray:
    """Make a compact judge-facing image without changing the source frame."""
    annotated = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated, f'{detection.name} {detection.confidence:.2f}',
                    (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0), 1, cv2.LINE_AA)
    return annotated
