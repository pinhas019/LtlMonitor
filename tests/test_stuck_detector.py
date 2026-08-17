"""Unit tests for stuck_detector.py. Run: python3 -m pytest test_stuck_detector.py"""

from skill_monitor.core.stuck_detector import is_blocked_state, StuckStreak


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


def test_streak_stays_stuck_while_state_remains_blocked():
    s = StuckStreak(threshold=2)
    s.update("no_path_found")
    s.update("no_path_found")
    s.update("no_path_found")
    assert s.is_stuck
    assert s.count == 3
