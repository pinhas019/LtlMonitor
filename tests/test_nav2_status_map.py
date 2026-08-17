"""Unit tests for nav2_status_map.py. Run: python3 -m pytest test_nav2_status_map.py"""

from skill_monitor.core.nav2_status_map import nav2_status_to_state


def test_accepted_and_executing_both_map_to_following():
    assert nav2_status_to_state(1) == "following"
    assert nav2_status_to_state(2) == "following"


def test_succeeded_maps_to_finished():
    assert nav2_status_to_state(4) == "finished"


def test_canceling_canceled_aborted_map_to_no_path_found():
    assert nav2_status_to_state(3) == "no_path_found"
    assert nav2_status_to_state(5) == "no_path_found"
    assert nav2_status_to_state(6) == "no_path_found"


def test_unknown_status_falls_back_to_waiting_inputs():
    assert nav2_status_to_state(99) == "waiting_inputs"
