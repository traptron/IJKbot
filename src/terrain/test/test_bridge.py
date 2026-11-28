"""Regression scenes for bridge traversal with centimetre-scale depth evidence."""

from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bridge_snapshot import bake
from surface import BLOCKED, CLEAR, UNKNOWN, Surface, project_depth

CALIBRATION = {
    'residual_m': .012, 'max_pose_error_m': .02, 'braking_decel_m_s2': .2,
    'angular_decel_rad_s2': .8, 'reaction_sec': .6, 'max_speed_m_s': .10,
    'clear_ttl_sec': 2., 'footprint_margin_m': .05,
}


@pytest.fixture
def ramp():
    axis = (np.arange(200) + .5) * .02
    x, y = np.meshgrid(axis, axis)
    z = np.clip((x - 1.) * .275, 0, .055)
    lane = (x >= .88) & (x < 1.6) & (y >= 1.7) & (y < 2.3)
    heights = np.where(lane, z, np.nan)
    reference = {'heights': heights, 'calibration': CALIBRATION,
                 'keepout': ((x >= 1.) & (x < 1.6) & (y >= 2.3) & (y < 2.4))}
    points = np.column_stack([x[lane], y[lane], z[lane]])
    return reference, np.repeat(points, 3, axis=0)


def test_empty_ramp_becomes_passable_and_expires(ramp):
    ref, points = ramp
    surface = Surface(ref)
    pose = (.8, 2., 0.)
    assert not surface.permits(surface.grid(0., False), pose, .1, 0.)
    for now in (.1, .2, .3):
        surface.observe(points, now)
    assert surface.permits(surface.grid(.3, True), pose, .1, 0.)
    assert not surface.permits(surface.grid(.6, False), pose, .1, 0.)
    assert not surface.permits(surface.grid(2.4, True), pose, .1, 0.)


@pytest.mark.parametrize('obstacle_x', [1.01, 1.35])
def test_fallen_car_overrides_ramp_and_deck(ramp, obstacle_x):
    ref, points = ramp
    surface = Surface(ref)
    pose = (obstacle_x - .2, 2., 0.)
    for now in (.1, .2, .3):
        surface.observe(points, now)
    grid = surface.grid(.3, True)
    assert surface.permits(grid, pose, .1, 0.)
    mask = np.isclose(points[:, 0], obstacle_x) & np.isclose(points[:, 1], 2.01)
    obstructed = points.copy()
    obstructed[mask, 2] += .035
    surface.observe(obstructed, .4)
    assert surface.grid(.4, True)[100, int(obstacle_x/.02)] == BLOCKED
    assert not surface.permits(surface.grid(.4, True), pose, .1, 0.)
    for now in (.5, .6):
        surface.observe(points, now)
        assert not surface.permits(surface.grid(now, True), pose, .1, 0.)
    surface.observe(points, .7)
    assert surface.permits(surface.grid(.7, True), pose, .1, 0.)
    surface.reset()
    assert surface.grid(.8, True)[100, int(obstacle_x/.02)] == UNKNOWN


def test_occlusion_does_not_prove_support(ramp):
    ref, points = ramp
    surface = Surface(ref)
    scene = points[points[:, 1] > 2.]
    for now in (.1, .2, .3):
        surface.observe(scene, now)
    assert surface.grid(.3, True)[101, 50] == CLEAR
    assert not surface.permits(surface.grid(.3, True), (.8, 2., 0.), .1, 0.)


def test_reference_in_map_frame(ramp):
    ref, points = ramp
    offset = np.array([.2, .5, .03])
    anchors = [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]
    review = {
        'calibration': CALIBRATION,
        'floor_anchors': [{'rgbd_map': (anchor-offset).tolist(), 'map': anchor} for anchor in anchors],
        'lane_polygons': [[[.88, 1.7], [1.6, 1.7], [1.6, 2.3], [.88, 2.3]]],
        'keepout_polygons': [[[1., 2.3], [1.6, 2.3], [1.6, 2.4], [1., 2.4]]],
        'deck_checks': [[[1.3, 1.9], [1.5, 1.9], [1.5, 2.1], [1.3, 2.1]]],
    }
    heights, keepout = bake(points-offset, review)
    assert np.allclose(heights, ref['heights'], equal_nan=True)
    assert np.array_equal(keepout, np.flatnonzero(ref['keepout']))
    with pytest.raises(ValueError, match='Unobserved'):
        bake(points[points[:, 1] > 2.]-offset, review)


def test_depth_projection_handles_invalid_pixels_and_row_stride():
    depths = np.array([[1000, 0, 1234], [500, 1500, 1234]], dtype='<u2')
    points = project_depth(depths.tobytes(), 2, 2, 6, '16UC1', False,
                           [100, 0, 0, 0, 100, 0, 0, 0, 1])
    expected = [[0, 0, 1], [0, .005, .5], [.015, .015, 1.5]]
    assert np.allclose(points, expected)
