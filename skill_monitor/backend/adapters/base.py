"""SensorAdapter: the seam that makes generic_client.py agnostic to which environment
(real G1, MuJoCo sim, Isaac Lab sim, ...) it's evaluating against.

Each adapter maps ONE environment's native ROS topics to the sensor_eval dict its
schema declares. Most embodiments now do that declaratively -- a JSON descriptor in
skill_monitor/adapters/ interpreted by core/adapter_spec.py and declarative.py -- and
the hand-written subclasses here remain for embodiments whose plumbing needs code.

The evaluator owns everything else (the /ltl/* protocol, rule/LLM AP evaluation, print
formatting) unchanged regardless of which adapter is loaded -- swapping environments is
choosing an adapter, not writing new evaluator code or ROS-topic translation shims.

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
from pathlib import Path
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
# units and meaning. It is the ONE artifact shared by four consumers:
#   1. validate_sensor_eval()               -- runtime: adapter returns exactly these keys
#   2. test_adapter_sensor_eval_contract    -- static: rules reference only these keys
#   3. generate_formulas.py                 -- synthesis: what the LLM may write rules over
#   4. the Skill Center, over /ltl/adapter  -- what an operator sees
# (3) is why the values are prose and not just types: the generator has to know what
# `nav_state == 'following'` means to produce a correct rule from a free-language
# skill description.
#
# The schemas themselves live in skill_monitor/adapters/*_schema.json, not in this
# module: (3) and (4) do not import the ROS layer at all, so a schema they must read
# cannot live behind a Python import of it. What follows is the in-process view.

def load_schema(name: str = "nav") -> dict:
    """key -> prose, read from skill_monitor/adapters/<name>_schema.json."""
    import json
    path = _ADAPTERS_DIR / f"{name}_schema.json"
    return {k: v.get("doc", "") for k, v in json.loads(path.read_text(encoding="utf-8"))["keys"].items()}


_ADAPTERS_DIR = Path(__file__).resolve().parents[2] / "adapters"

NAV_SCHEMA = load_schema("nav")

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

    # -- raw echo ------------------------------------------------------------
    # The evaluator publishes the raw echo out of these two calls and knows nothing else
    # about them. Defaulted here rather than probed with `hasattr` at the call site, so
    # an adapter that cannot echo REFUSES a selection instead of accepting one and then
    # never producing a frame -- which an operator would read as "the camera is dead".

    def set_raw_echo(self, source_id: str | None) -> bool:
        """Echo `source_id` and no other source; None stops. False when this adapter
        cannot echo that source. Default: it cannot echo anything, so only "off" is
        honoured."""
        return source_id is None

    def take_raw_echo(self) -> tuple[str, dict] | None:
        """`(source_id, summary)` for the tick just closed, or None when there is
        nothing to echo. See `adapters/raw_echo.py` for the summary convention."""
        return None

    def manifest(self) -> dict:
        """What this adapter announces on /ltl/adapter. A declarative adapter
        overrides this with its descriptor's topic list; a hand-written one has no
        machine-readable topic map, so it publishes just the schema."""
        return {
            "adapter": type(self).__name__,
            "doc": (type(self).__doc__ or "").strip().split("\n")[0],
            "schema": {k: {"doc": v} for k, v in self.schema().items()},
            "sources": [],
        }
