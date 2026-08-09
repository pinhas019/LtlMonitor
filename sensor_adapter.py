"""SensorAdapter: the seam that makes generic_client.py agnostic to which environment
(real G1, MuJoCo sim, Isaac Lab sim, ...) it's evaluating against.

Each adapter maps ONE environment's native ROS topics to the SAME sensor_eval dict
schema (CANONICAL_SENSOR_EVAL_KEYS below). generic_client.py owns everything else (the
/ltl/* protocol, rule/LLM AP evaluation, print formatting) unchanged regardless of
which adapter is loaded -- swapping environments is choosing an adapter, not writing
new evaluator code or ROS-topic translation shims.

Any environment whose native "path status" isn't already in the mode/state/finished
vocabulary (e.g. Nav2's accepted/executing/succeeded/aborted/canceled) translates it
in-process inside get_sensor_eval() -- see nav2_status_map.py, reused by
adapter_mujoco.py and adapter_isaac_lab.py. No wire-level shim nodes are needed.

No rclpy import here (only used for a type hint, deferred under TYPE_CHECKING) so this
module -- and CANONICAL_SENSOR_EVAL_KEYS -- stays importable without ROS installed,
which is what lets test_adapter_sensor_eval_contract.py check formulas_g1.json's rule
APs against the contract without needing a ROS environment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rclpy.node import Node

# Single source of truth for what every adapter's get_sensor_eval() must return.
# formulas_g1.json's rule-AP expressions may only reference these identifiers (checked
# statically by test_adapter_sensor_eval_contract.py); every concrete adapter's
# get_sensor_eval() should return exactly this key set (checked at runtime by
# validate_sensor_eval below, so a drifted adapter fails loudly instead of silently
# leaving some AP always-false).
CANONICAL_SENSOR_EVAL_KEYS = frozenset({
    "min_range",
    "base_roll",
    "base_pitch",
    "base_height",
    "upright_flag",
    "linear_vel",
    "angular_vel",
    "nav_mode",
    "nav_state",
    "num_waypoints",
    "current_target_idx",
    "mission_finished",
    "nav_stuck",
    "image_similarity_to_goal",
})


class SensorAdapter(ABC):
    @abstractmethod
    def register_subscriptions(self, node: "Node") -> None:
        """Create whatever subscriptions this environment needs on `node`."""

    @abstractmethod
    def get_sensor_eval(self) -> dict:
        """Return the current sensor_eval dict (via validate_sensor_eval, below).
        Must return sane defaults (e.g. an obstacle-free min_range, a
        non-upright-penalizing pose) before any messages have arrived.
        """

    @staticmethod
    def validate_sensor_eval(sensor_eval: dict) -> dict:
        """Implementations should `return self.validate_sensor_eval({...})` rather than
        the raw dict -- catches a missing/extra key immediately at runtime (any
        environment) instead of silently leaving some atomic proposition always-false.
        """
        actual = set(sensor_eval)
        if actual != CANONICAL_SENSOR_EVAL_KEYS:
            missing = CANONICAL_SENSOR_EVAL_KEYS - actual
            extra = actual - CANONICAL_SENSOR_EVAL_KEYS
            raise ValueError(
                f"sensor_eval contract violation: missing={sorted(missing)} extra={sorted(extra)}"
            )
        return sensor_eval

    def describe(self) -> dict:
        """Optional debug snapshot for the evaluator's console print block. Default
        empty; adapters may override to surface adapter-specific fields (e.g. nav_mode/
        nav_state) without generic_client.py needing to know their names.
        """
        return {}
