"""Preserve smooth surfaces while rejecting stereo occlusion boundaries."""

from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mapping_depth_filter import filter_depth


def test_occlusion_rejects_both_sides_preserving_surfaces():
    depth = np.ones((25, 40), dtype=np.float32)
    depth[:, 20:] = 2.0
    keep = filter_depth(depth, np.zeros_like(depth), 0.15, 0.4)
    assert not keep[:, 18:22].any()
    assert keep[:, 10:18].all()
    assert keep[:, 22:30].all()


def test_holes_and_isolated_returns_do_not_create_edges():
    depth = np.ones((25, 40), dtype=np.float32)
    depth[12, 12] = 0.6
    depth[12, 27] = 0.0
    keep = filter_depth(depth, np.zeros_like(depth), 0.15, 0.4)
    assert not keep[11:14, 11:14].any()
    assert not keep[11:14, 26:29].any()
    assert keep[4:8, 4:8].all()


def test_smooth_depth_gradient_survives():
    depth = np.tile(np.linspace(0.5, 2, 40, dtype=np.float32), (25, 1))
    assert filter_depth(depth, np.zeros_like(depth), 0.15, 0.4).all()


def test_navigation_preserves_three_pixel_obstacle_top():
    depth = np.full((25, 40), 1.5, dtype=np.float32)
    depth[12:15, 10:30] = 1.0
    keep = filter_depth(depth, np.zeros_like(depth), 0.15, 0.4, preserve_foreground=True)
    assert keep[13, 12:28].all()
    assert not keep[11, 10:30].any()
