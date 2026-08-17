"""Pure frame-convention math for adapter_real_g1.py — no ROS imports, unit-testable.

Isolated because it's the highest-risk piece of the real-robot evaluator (a silent
axis mismatch here makes min_range report plausible-looking garbage instead of
failing loudly), and g1_sensors.py deliberately stays untouched/sim-and-real-agnostic.
"""

from __future__ import annotations

from typing import Iterable, Tuple


def remap_optical_to_body(points: Iterable[Tuple[float, float, float]]):
    """camera_color_optical_frame (X-right, Y-down, Z-forward/depth — REP-103 optical
    convention) -> body-ish (X-forward, Y-left, Z-up), the convention
    g1_sensors.min_range_from_points expects (Z-up height band, XY ground-plane range).
    """
    return ((p[2], -p[0], -p[1]) for p in points)
