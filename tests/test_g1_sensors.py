"""Unit tests for g1_sensors — pure math, no ROS/Isaac. Run: python3 -m pytest test_g1_sensors.py"""

import math

from skill_monitor.core.g1_sensors import base_upright, min_range_from_points, quat_to_euler


def test_identity_quat_is_level():
    roll, pitch, yaw = quat_to_euler(0.0, 0.0, 0.0, 1.0)
    assert abs(roll) < 1e-9 and abs(pitch) < 1e-9 and abs(yaw) < 1e-9


def test_yaw_90_degrees():
    h = math.sqrt(0.5)  # 90° about z
    roll, pitch, yaw = quat_to_euler(0.0, 0.0, h, h)
    assert abs(yaw - math.pi / 2) < 1e-6
    assert abs(roll) < 1e-6 and abs(pitch) < 1e-6


def test_roll_90_degrees():
    h = math.sqrt(0.5)  # 90° about x -> a fallen-sideways base
    roll, pitch, yaw = quat_to_euler(h, 0.0, 0.0, h)
    assert abs(roll - math.pi / 2) < 1e-6


def test_base_upright_thresholds():
    assert base_upright(0.0, 0.0, 0.8) is True
    assert base_upright(1.2, 0.0, 0.8) is False  # tilted past tilt_max -> fallen
    assert base_upright(0.0, 1.2, 0.8) is False
    assert base_upright(0.0, 0.0, 0.2) is False  # pelvis too low -> fallen


def test_min_range_height_band_and_default():
    pts = [
        (2.0, 0.0, 0.5),  # in band, far
        (0.3, 0.0, 0.5),  # in band, closest
        (0.1, 0.0, 5.0),  # above band -> ignored (ceiling)
        (0.05, 0.0, -0.2),  # below band -> ignored (ground)
    ]
    assert abs(min_range_from_points(pts) - 0.3) < 1e-9
    assert min_range_from_points([]) == 10.0  # empty -> default
