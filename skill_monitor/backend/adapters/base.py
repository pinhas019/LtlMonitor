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

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rclpy.node import Node


class Freshness:
    """Per-source last-message clock, so a DEAD topic is distinguishable from a
    topic that is reporting benign values.

    This exists because every adapter's get_sensor_eval() must return a full key
    set before any message has arrived, so the defaults are necessarily benign --
    e.g. min_range=10.0 ("nothing nearby"). If the publisher then dies, that
    default silently reads as "clear corridor" and no atomic proposition can tell
    the difference. Freshness answers the question the sensor_eval dict cannot:
    is this number actually being refreshed?

    A source that has NEVER produced a message counts as stale: "no data yet" and
    "data stopped" are equally unsafe to treat as an observation.

    `clock` is injected so tests can drive time directly instead of sleeping.
    """

    def __init__(self, sources, stale_after: float = 2.0, clock=time.monotonic):
        self._stale_after = float(stale_after)
        self._clock = clock
        self._last: dict[str, float | None] = {s: None for s in sources}

    def stamp(self, source: str) -> None:
        if source not in self._last:
            raise KeyError(f"unknown freshness source {source!r}; declared: {sorted(self._last)}")
        self._last[source] = self._clock()

    def stale_sources(self) -> tuple[str, ...]:
        now = self._clock()
        return tuple(
            s for s, t in sorted(self._last.items())
            if t is None or (now - t) > self._stale_after
        )

    def confidence(self) -> float:
        """Fraction of declared sources currently reporting. 1.0 = all fresh.

        ponytail: one scalar over all sources, not per-AP. Per-AP confidence needs
        an AP->source dependency map; add that only once a guard actually needs to
        distinguish "my inputs are stale" from "some other sensor is stale".
        """
        if not self._last:
            return 1.0
        return 1.0 - len(self.stale_sources()) / len(self._last)

# A SCHEMA maps each sensor_eval key to a human-readable description of its type,
# units and meaning. It is the ONE artifact shared by three consumers:
#   1. validate_sensor_eval()               -- runtime: adapter returns exactly these keys
#   2. test_adapter_sensor_eval_contract    -- static: rules reference only these keys
#   3. generate_formulas.py                 -- synthesis: what the LLM may write rules over
# (3) is why the values are prose and not just types: the generator has to know what
# `nav_state == 'following'` means to produce a correct rule from a free-language
# skill description.
#
# Schemas live here, in this rclpy-free module, rather than on the adapter classes:
# the generator runs on a host with no ROS, so it must be able to read a schema
# without importing the adapter module that implements it.

NAV_SCHEMA = {
    "min_range": "float, metres. Distance to the nearest obstacle ahead within the "
                 "0.1-1.5 m height band. 10.0 means nothing was detected.",
    "base_roll": "float, radians. Roll of the robot base. 0.0 is level.",
    "base_pitch": "float, radians. Pitch of the robot base. 0.0 is level.",
    "base_height": "float, metres. Height of the robot base above the odometry origin "
                   "plane. Drops sharply if the robot falls or collapses.",
    "upright_flag": "float, 1.0 if the base is within tilt and height limits, else 0.0.",
    "linear_vel": "float, m/s. Forward velocity of the base.",
    "angular_vel": "float, rad/s. Yaw rate of the base.",
    "nav_mode": "string, one of 'MANUAL' or 'AUTOMATIC'. AUTOMATIC means the planner, "
                "not a human operator, is driving.",
    "nav_state": "string, the planner's current state: 'manual', 'waiting_inputs', "
                 "'following', 'positioning', 'unblocking', 'no_traversable', "
                 "'unreachable', 'no_path_found', 'finished'.",
    "num_waypoints": "int, how many waypoints the current mission has. 0 means no goal "
                     "has been set.",
    "current_target_idx": "int, index of the waypoint currently being driven to. "
                          "Increases as waypoints are passed.",
    "mission_finished": "bool, True once every waypoint has been reached.",
    "nav_stuck": "bool, True when the planner has reported a blocked state continuously "
                 "for a debounce window (not a single bad tick).",
    "image_similarity_to_goal": "float, 0.0-1.0. Visual similarity between the current "
                                "camera view and a reference photo of the goal.",
}

# Back-compat alias. Prefer adapter.schema() / adapter.schema_keys().
CANONICAL_SENSOR_EVAL_KEYS = frozenset(NAV_SCHEMA)

SCHEMAS = {
    "nav": NAV_SCHEMA,
}


class SensorAdapter(ABC):
    #: What THIS embodiment can observe. Subclasses MUST set it to a schema dict (see
    #: NAV_SCHEMA). A manipulation adapter declares gripper/object keys instead --
    #: that per-adapter declaration is what keeps the engine skill-agnostic, rather
    #: than one global key set that quietly assumes navigation. Deliberately not
    #: defaulted to NAV_SCHEMA: a manipulation adapter that forgot to declare one
    #: would then silently inherit navigation fields and fail far downstream.
    SCHEMA: dict | None = None

    @classmethod
    def schema(cls) -> dict:
        if not cls.SCHEMA:
            raise NotImplementedError(
                f"{cls.__name__} must declare SCHEMA (a sensor_eval key -> description "
                f"dict, e.g. sensor_adapter.NAV_SCHEMA)"
            )
        return cls.SCHEMA

    @classmethod
    def schema_keys(cls) -> frozenset:
        return frozenset(cls.schema())

    @abstractmethod
    def register_subscriptions(self, node: "Node") -> None:
        """Create whatever subscriptions this environment needs on `node`."""

    @abstractmethod
    def get_sensor_eval(self) -> dict:
        """Return the current sensor_eval dict (via validate_sensor_eval, below).
        Must return sane defaults (e.g. an obstacle-free min_range, a
        non-upright-penalizing pose) before any messages have arrived.
        """

    def validate_sensor_eval(self, sensor_eval: dict) -> dict:
        """Implementations should `return self.validate_sensor_eval({...})` rather than
        the raw dict -- catches a missing/extra key immediately at runtime (any
        environment) instead of silently leaving some atomic proposition always-false.

        Validates against THIS adapter's declared SCHEMA, not a global key set.
        """
        expected = self.schema_keys()
        actual = set(sensor_eval)
        if actual != expected:
            raise ValueError(
                f"{type(self).__name__} sensor_eval contract violation: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        return sensor_eval

    def describe(self) -> dict:
        """Optional debug snapshot for the evaluator's console print block. Default
        empty; adapters may override to surface adapter-specific fields (e.g. nav_mode/
        nav_state) without generic_client.py needing to know their names.
        """
        return {}

    # -- freshness -----------------------------------------------------------
    # Deliberately NOT part of sensor_eval: adding keys there would change the
    # CANONICAL_SENSOR_EVAL_KEYS contract and every formulas_*.json rule that is
    # checked against it. Freshness travels beside the observation instead, as
    # the reserved __confidence__ key on /ltl/evaluations.

    def stale_sources(self) -> tuple[str, ...]:
        """Names of subscribed sources with no recent message. Default: assume
        fresh, so adapters that do not track freshness behave exactly as before."""
        return ()

    def confidence(self) -> float:
        """Confidence in this tick's sensor_eval, 0.0-1.0. Default 1.0."""
        return 1.0
