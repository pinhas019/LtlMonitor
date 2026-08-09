"""Pure Nav2-GoalStatus -> path_manager-state mapping, no ROS import, unit-testable.

Used only by nav2_status_to_path_manager_status.py (a sim-only shim -- the real robot
has no Nav2 and publishes /path_manager/status natively). Sim missions are single-goal
(send_goal.py sends one /goal_pose), so this collapses Nav2's five-way status into the
handful of path_manager states formulas_g1_real.json's APs actually distinguish.
"""

from __future__ import annotations

# action_msgs/GoalStatus values, from llm_client.py's nav_status_callback status_map.
_STATUS_TO_STATE = {
    1: "following",       # accepted
    2: "following",       # executing
    3: "no_path_found",   # canceling
    4: "finished",        # succeeded
    5: "no_path_found",   # canceled
    6: "no_path_found",   # aborted
}


def nav2_status_to_state(status: int) -> str:
    return _STATUS_TO_STATE.get(status, "waiting_inputs")
