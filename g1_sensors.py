"""Pure sensor math for the G1 humanoid actor — no ROS/Isaac imports, so it is unit-testable.

Used by every sensor adapter (adapter_real_g1.py, adapter_nav2_common.py) to derive base
orientation/height AP fields from odom, and to derive obstacle range from a point cloud.
formulas_g1.json's rule APs reference the fields these produce (``base_roll``,
``base_pitch``, ``base_height``, ``min_range``).
"""

from __future__ import annotations

import math

NAV_STATUS_MAP = {
    1: "accepted",
    2: "executing",
    3: "canceling",
    4: "succeeded",
    5: "canceled",
    6: "aborted",
}


def quat_to_euler(x: float, y: float, z: float, w: float) -> tuple[float, float, float]:
    """Quaternion (x, y, z, w) -> (roll, pitch, yaw) in radians (ZYX / aerospace convention)."""
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


def base_upright(
    roll: float,
    pitch: float,
    height: float,
    tilt_max: float = 0.5,
    height_min: float = 0.5,
) -> bool:
    """True when the base is level enough and tall enough not to count as 'fallen'.

    ``tilt_max`` rad and ``height_min`` m are sim/robot-specific — calibrate on the G1.
    """
    return abs(roll) < tilt_max and abs(pitch) < tilt_max and height > height_min


def min_range_from_points(
    points, z_lo: float = 0.1, z_hi: float = 1.5, default: float = 10.0
) -> float:
    """Min planar (xy) distance to any point within a height band — PointCloud2 -> obstacle range.

    ``points``: iterable of (x, y, z) in the SENSOR frame (distance from origin = distance to
    the robot). Points outside [z_lo, z_hi] (ground, ceiling) are ignored. Returns ``default``
    when no point qualifies (matches the evaluator's empty-scan fallback).
    """
    best = math.inf
    for x, y, z in points:
        if z_lo <= z <= z_hi:
            d = math.hypot(x, y)
            if d < best:
                best = d
    return best if best != math.inf else default
