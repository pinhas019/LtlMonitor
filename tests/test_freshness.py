"""Freshness / staleness contract.

    python3 -m pytest test_freshness.py

Covers the defect this exists for: a dead sensor topic must be distinguishable
from a sensor reporting benign values. No ROS, no sleeping -- the clock is
injected.
"""

from skill_monitor.backend.adapters.base import Freshness, SensorAdapter


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _fresh(stale_after=2.0):
    clock = _FakeClock()
    return Freshness(("odom", "points", "status"), stale_after=stale_after, clock=clock), clock


def test_never_stamped_counts_as_stale():
    # "no data yet" is as unsafe as "data stopped" -- both must not read as fresh.
    f, _ = _fresh()
    assert f.stale_sources() == ("odom", "points", "status")
    assert f.confidence() == 0.0


def test_all_stamped_is_fully_fresh():
    f, _ = _fresh()
    for s in ("odom", "points", "status"):
        f.stamp(s)
    assert f.stale_sources() == ()
    assert f.confidence() == 1.0


def test_one_source_going_silent_is_detected():
    f, clock = _fresh(stale_after=2.0)
    for s in ("odom", "points", "status"):
        f.stamp(s)
    # points dies; the other two keep publishing
    clock.advance(3.0)
    f.stamp("odom")
    f.stamp("status")
    assert f.stale_sources() == ("points",)
    assert abs(f.confidence() - 2 / 3) < 1e-9


def test_boundary_is_strictly_greater_than():
    f, clock = _fresh(stale_after=2.0)
    f.stamp("odom")
    clock.advance(2.0)
    assert "odom" not in f.stale_sources()   # exactly at the limit is still fresh
    clock.advance(0.001)
    assert "odom" in f.stale_sources()


def test_restamping_recovers():
    f, clock = _fresh(stale_after=2.0)
    f.stamp("points")
    clock.advance(5.0)
    assert "points" in f.stale_sources()
    f.stamp("points")
    assert "points" not in f.stale_sources()


def test_unknown_source_is_rejected():
    f, _ = _fresh()
    try:
        f.stamp("lidar")
    except KeyError:
        return
    raise AssertionError("stamping an undeclared source should raise")


def test_adapter_default_is_backwards_compatible():
    # Adapters that do not track freshness must behave exactly as before.
    class _Bare(SensorAdapter):
        def register_subscriptions(self, node):
            pass

        def get_sensor_eval(self):
            return {}

    bare = _Bare()
    assert bare.stale_sources() == ()
    assert bare.confidence() == 1.0
