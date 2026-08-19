"""Unit tests for stuck_detector.py. Run: python3 -m pytest tests/test_stuck_detector.py

`StuckStreak` counts whatever it is `update()`d with. Whether that is one message or
one tick is the CALLER's choice, and getting it wrong is what made a declared 10 s
debounce mean 2 s on a 5 Hz topic -- see tests/test_adapter_spec.py, which pins the
adapter to advancing it once per tick. `threshold_from_seconds` is the other half of
that fix: the descriptor declares a duration, and the tick count is derived from it
exactly once, at load.
"""

import pytest

from skill_monitor.core.stuck_detector import (
    is_blocked_state, StuckStreak, threshold_from_seconds,
)


def test_is_blocked_state_matches_exact_vocabulary():
    assert is_blocked_state("no_traversable")
    assert is_blocked_state("unreachable")
    assert is_blocked_state("no_path_found")
    assert not is_blocked_state("following")
    assert not is_blocked_state("finished")
    assert not is_blocked_state("waiting_inputs")


def test_streak_does_not_fire_below_threshold():
    s = StuckStreak(threshold=3)
    s.update("no_path_found")
    s.update("no_path_found")
    assert not s.is_stuck
    assert s.count == 2


def test_streak_fires_at_threshold():
    s = StuckStreak(threshold=3)
    for _ in range(3):
        s.update("unreachable")
    assert s.is_stuck


def test_single_bad_tick_does_not_fire_and_recovers():
    s = StuckStreak(threshold=3)
    s.update("no_traversable")
    s.update("no_traversable")
    s.update("following")  # recovered -> resets
    assert not s.is_stuck
    assert s.count == 0


def test_reset_forgets_the_streak():
    """An episode boundary is not a recovery. Without reset() the previous episode's
    blocked ticks count toward the next episode's nav_stuck, firing it on the first
    blocked observation of a fresh run -- the false positive the debounce exists to
    prevent. See AdapterSpec.reset(): the streak lives in the extractor's closure on
    the SPEC, so constructing a new SensorState does not clear it."""
    s = StuckStreak(threshold=3)
    s.update("no_path_found")
    s.update("no_path_found")
    assert s.count == 2

    s.reset()
    assert s.count == 0 and not s.is_stuck

    for _ in range(3):
        s.update("no_path_found")
    assert s.is_stuck, "reset() broke the counter rather than clearing it"


def test_streak_stays_stuck_while_state_remains_blocked():
    s = StuckStreak(threshold=2)
    s.update("no_path_found")
    s.update("no_path_found")
    s.update("no_path_found")
    assert s.is_stuck
    assert s.count == 3


# ------------------------------------------ seconds -> ticks, resolved at load

def test_threshold_is_the_tick_count_the_duration_implies():
    assert threshold_from_seconds(10.0, 1.0) == 10
    assert threshold_from_seconds(10.0, 5.0) == 50
    assert threshold_from_seconds(4.0, 0.5) == 2


def test_threshold_rounds_up_so_a_debounce_never_fires_early():
    assert threshold_from_seconds(2.5, 1.0) == 3
    assert threshold_from_seconds(1.01, 1.0) == 2


def test_threshold_floors_at_one_tick():
    """A debounce shorter than the tick period is still one observation, not zero --
    a zero threshold would make `is_stuck` true before any sample arrived."""
    assert threshold_from_seconds(0.1, 1.0) == 1
    assert threshold_from_seconds(1e-9, 1.0) == 1
    assert StuckStreak(threshold=threshold_from_seconds(0.1, 1.0)).is_stuck is False


def test_threshold_is_not_defeated_by_binary_floating_point():
    """1.1 * 10 is 11.000000000000002; a bare ceil() would silently make it 12."""
    assert threshold_from_seconds(1.1, 10.0) == 11
    assert threshold_from_seconds(0.3, 10.0) == 3
    assert threshold_from_seconds(0.7, 10.0) == 7


@pytest.mark.parametrize("debounce_s", [0.0, -1.0])
def test_non_positive_debounce_is_rejected(debounce_s):
    with pytest.raises(ValueError, match="debounce_s"):
        threshold_from_seconds(debounce_s, 1.0)


@pytest.mark.parametrize("tick_hz", [0.0, -5.0])
def test_non_positive_tick_hz_is_rejected(tick_hz):
    with pytest.raises(ValueError, match="tick_hz"):
        threshold_from_seconds(1.0, tick_hz)


# --------------------------------- every rejection is a ValueError, deliberately
#
# A descriptor is loaded by code that treats a bad descriptor as a ValueError. A
# rejection that arrives as a TypeError or an OverflowError escapes that handling and
# crashes the loader, from a file that raises cleanly on a misspelt key.

@pytest.mark.parametrize("bad", ["10", None, [], {}, object()])
def test_a_non_numeric_debounce_is_a_value_error_not_a_type_error(bad):
    with pytest.raises(ValueError, match="debounce_s"):
        threshold_from_seconds(bad, 1.0)
    with pytest.raises(ValueError, match="tick_hz"):
        threshold_from_seconds(1.0, bad)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_debounce_is_a_value_error_not_an_overflow_error(bad):
    with pytest.raises(ValueError, match="debounce_s"):
        threshold_from_seconds(bad, 1.0)
    with pytest.raises(ValueError, match="tick_hz"):
        threshold_from_seconds(1.0, bad)


def test_a_product_that_overflows_is_a_value_error():
    """Both factors finite, the product not. math.ceil(inf) is an OverflowError."""
    with pytest.raises(ValueError, match="overflow"):
        threshold_from_seconds(1e308, 10.0)


@pytest.mark.parametrize("bad", [True, False])
def test_a_bool_is_not_a_duration(bad):
    """bool is a subclass of int, so a JSON `true` used to resolve to a one-tick
    debounce -- a debounce that is satisfied by the first blocked observation."""
    with pytest.raises(ValueError, match="debounce_s"):
        threshold_from_seconds(bad, 1.0)
    with pytest.raises(ValueError, match="tick_hz"):
        threshold_from_seconds(1.0, bad)
