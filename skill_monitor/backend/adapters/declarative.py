"""The one adapter that reads its robot out of a JSON descriptor instead of being
written as a class per embodiment (skill_monitor/adapters/*.json, interpreted by
core/adapter_spec.py).

This module is the ONLY part of the adapter layer that needs ROS: message-type
lookup, subscription, and the four decoders below. Everything else -- which topics,
which fields, which sensor_eval keys, which thresholds -- is data.

    adapter = DeclarativeAdapter("real_g1")
    adapter.register_subscriptions(node)

Adding a robot is then a JSON file, not a Python class, which is what lets the
generator and the GUI work against a robot whose adapter module they never import.
"""

from __future__ import annotations

import importlib
import json

from skill_monitor.core import adapter_spec
from skill_monitor.backend.adapters.base import Freshness, SensorAdapter
from skill_monitor.backend.adapters.raw_echo import RawEcho


def _msg_class(type_str: str):
    """'nav_msgs/msg/Odometry' -> the class. Same spelling ROS uses on the wire, so a
    descriptor can be read off `ros2 topic info` without translation."""
    parts = type_str.split("/")
    if len(parts) != 3:
        raise ValueError(f"message type must be 'pkg/msg/Type', got {type_str!r}")
    return getattr(importlib.import_module(f"{parts[0]}.{parts[1]}"), parts[2])


def _qos(spec):
    if isinstance(spec, int):
        return spec
    if spec == "action_status":
        # Action status topics are TRANSIENT_LOCAL by convention; a bare depth here
        # silently misses statuses published before we subscribed.
        from rclpy.qos import qos_profile_action_status_default
        return qos_profile_action_status_default
    raise ValueError(f"unknown qos {spec!r} (use an int depth or 'action_status')")


def _decode(kind, msg):
    """Message -> the payload the descriptor's field paths and extractors see."""
    if kind is None:
        return msg
    if kind == "json":
        try:
            return json.loads(msg.data)
        except Exception:
            return None                     # a malformed status leaves state untouched
    if kind == "pointcloud_xyz":
        from sensor_msgs_py import point_cloud2
        return point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
    if kind == "laserscan_ranges":
        return msg.ranges
    if kind == "goal_status":
        return msg.status_list[-1].status if msg.status_list else None
    raise ValueError(f"unknown decode {kind!r}")


class DeclarativeAdapter(SensorAdapter):
    def __init__(self, descriptor="real_g1", stale_after: float = 2.0, clock=None):
        self.spec = adapter_spec.load(descriptor)
        self.SCHEMA = self.spec.docs()          # instance attr: schema is per descriptor
        self.state = adapter_spec.SensorState(self.spec)
        tracked = [s.id for s in self.spec.sources if s.tracked]
        self._fresh = Freshness(
            tracked, stale_after=stale_after,
            **({"clock": clock} if clock is not None else {}),
        )
        # Off until something asks. See raw_echo.py for what a summary looks like and
        # what bounds its size and rate; `tick_hz` is what the stride is derived from.
        self._echo = RawEcho({s.id: s.topic for s in self.spec.sources},
                             tick_hz=self.spec.tick_hz)

    # SensorAdapter's classmethods would read the class attribute, which is None here
    # -- the schema belongs to the loaded descriptor, not to the class.
    def schema(self) -> dict:
        return self.spec.docs()

    def schema_keys(self) -> frozenset:
        return self.spec.keys()

    def register_subscriptions(self, node) -> None:
        for src in self.spec.sources:
            node.create_subscription(
                _msg_class(src.type), src.topic,
                (lambda msg, _s=src: self._on_message(_s, msg)), _qos(src.qos))

    def _on_message(self, src, msg) -> None:
        payload = _decode(src.decode, msg)
        if payload is None and src.decode == "json":
            return
        contribution = self.state.update(src.id, payload)
        if src.tracked:
            self._fresh.stamp(src.id)
        # The one place a raw ROS message still exists: after this method returns it has
        # been folded to whatever the descriptor's steps extract, and the pixels -- or
        # the fields no step reads -- are gone. `offer` is a reference and a counter;
        # the encoding happens on the tick that publishes.
        if src.id == self._echo.selected:
            self._echo.offer(src.id, msg,
                             {k: contribution[k] for k in src.keys if k in contribution})

    # -- raw echo (api.RAW_ECHO_REQUEST -> api.RAW_ECHO, published by the evaluator) --

    def set_raw_echo(self, source_id: str | None) -> bool:
        return self._echo.select(source_id)

    def take_raw_echo(self) -> tuple[str, dict] | None:
        return self._echo.take()

    def get_sensor_eval(self) -> dict:
        return self.validate_sensor_eval(self.state.sensor_eval())

    def stale_sources(self) -> tuple:
        return self._fresh.stale_sources()

    def confidence(self) -> float:
        return self._fresh.confidence()

    def describe(self) -> dict:
        values = self.state.values
        out = {k: values.get(k, "N/A") for k in self.spec.describe_keys}
        stale = self.stale_sources()
        out["stale"] = ",".join(stale) if stale else "—"
        return out

    def manifest(self) -> dict:
        return self.spec.manifest()
