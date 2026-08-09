"""SensorAdapter: the seam that makes generic_client.py agnostic to which environment
(real G1, MuJoCo sim, Isaac Lab sim, ...) it's evaluating against.

Each adapter maps ONE environment's native ROS topics to the SAME sensor_eval dict
schema (see formulas_g1.json's atomic_propositions for the canonical key set: min_range,
base_roll, base_pitch, base_height, upright_flag, linear_vel, angular_vel, nav_mode,
nav_state, num_waypoints, current_target_idx, mission_finished, nav_stuck,
image_similarity_to_goal). generic_client.py owns everything else (the /ltl/* protocol,
rule/LLM AP evaluation, print formatting) unchanged regardless of which adapter is
loaded -- swapping environments is choosing an adapter, not writing new evaluator code
or ROS-topic translation shims.

Any environment whose native "path status" isn't already in the mode/state/finished
vocabulary (e.g. Nav2's accepted/executing/succeeded/aborted/canceled) translates it
in-process inside get_sensor_eval() -- see nav2_status_map.py, reused by
adapter_mujoco.py and adapter_isaac_lab.py. No wire-level shim nodes are needed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from rclpy.node import Node


class SensorAdapter(ABC):
    @abstractmethod
    def register_subscriptions(self, node: Node) -> None:
        """Create whatever subscriptions this environment needs on `node`."""

    @abstractmethod
    def get_sensor_eval(self) -> dict:
        """Return the current sensor_eval dict. Must return sane defaults (e.g. an
        obstacle-free min_range, a non-upright-penalizing pose) before any messages
        have arrived, same contract every adapter honors -- see
        test_adapter_sensor_eval_contract.py.
        """

    def describe(self) -> dict:
        """Optional debug snapshot for the evaluator's console print block. Default
        empty; adapters may override to surface adapter-specific fields (e.g. nav_mode/
        nav_state) without generic_client.py needing to know their names.
        """
        return {}
