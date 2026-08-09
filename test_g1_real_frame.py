"""Unit tests for the optical->body frame remap. Run: python3 -m pytest test_g1_real_frame.py"""

import math

import g1_sensors
from g1_real_frame import remap_optical_to_body


def test_point_directly_ahead_in_optical_frame_becomes_forward_range():
    # 0.2m straight down the camera's optical Z axis (dead ahead) should read as
    # 0.2m directly in front of the robot after remap, at zero height.
    points = [(0.0, 0.0, 0.2)]
    remapped = list(remap_optical_to_body(points))
    assert remapped == [(0.2, 0.0, 0.0)]


def test_min_range_from_points_after_remap_matches_expected_distance():
    # A point 0.2m ahead (optical Z) should yield min_range ~0.2, not something
    # derived from the wrong axis (e.g. treating depth as height and discarding it).
    points = [(0.0, 0.0, 0.2)]
    remapped = remap_optical_to_body(points)
    min_range = g1_sensors.min_range_from_points(remapped, z_lo=-0.5, z_hi=0.5)
    assert math.isclose(min_range, 0.2, abs_tol=1e-6)


def test_point_above_camera_optical_y_becomes_body_height_and_is_filtered():
    # optical Y is down, so a point with optical y = -2.0 (well above the camera) remaps
    # to body z = +2.0 (up) -- outside the default [0.1, 1.5] ground-height band, so it
    # must NOT be counted as a ground-plane obstacle.
    points = [(0.0, -2.0, 3.0)]
    remapped = remap_optical_to_body(points)
    min_range = g1_sensors.min_range_from_points(remapped, z_lo=0.1, z_hi=1.5, default=10.0)
    assert min_range == 10.0  # filtered out -> falls back to default, not 3.0


def test_left_right_orientation_matches_body_left_convention():
    # optical X is right, so a point to the camera's right (positive optical x)
    # should remap to a negative body-left (y) coordinate.
    points = [(1.0, 0.0, 0.0)]
    remapped = list(remap_optical_to_body(points))
    assert remapped[0][1] == -1.0
