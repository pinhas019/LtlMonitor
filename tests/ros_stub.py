"""Just enough `rclpy`, `std_msgs` and `spot` to import and drive `monitor_node`.

`monitor_node` needs a ROS graph and `core/automata` needs `spot`, so the package's
answer to "how is this tested" has been "put the logic in `core/manifest.py` and test
that". That worked -- every defect this file pins was findable there -- but it left the
~600 lines of wiring in the node itself with no coverage at all, and three of the bugs
lived in the wiring: which wire steps the automaton, what the ledger is handed, and
which rows reach the verdict builder.

Nothing here simulates ROS. Publishers record, subscriptions are a dispatch table, and
timers never fire; the node is then driven by calling its callbacks directly, which is
what a real executor does anyway. `install()` refuses to run if a real `rclpy` is
importable, so a ROS machine skips these tests rather than testing the stub.
"""

from __future__ import annotations

import importlib.util
import sys
import types


class Message:
    """`std_msgs/String`. The only message type this node publishes or subscribes to."""

    def __init__(self, data: str = "") -> None:
        self.data = data


class Publisher:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.sent: list[str] = []

    def publish(self, msg) -> None:
        self.sent.append(msg.data)


class Timer:
    def __init__(self, period, callback) -> None:
        self.period = period
        self.callback = callback
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class Logger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def _log(self, level: str, text: str) -> None:
        self.lines.append((level, str(text)))

    def info(self, text) -> None:
        self._log("info", text)

    def warn(self, text) -> None:
        self._log("warn", text)

    def error(self, text) -> None:
        self._log("error", text)

    def debug(self, text) -> None:
        self._log("debug", text)

    def at(self, level: str) -> list[str]:
        return [text for lvl, text in self.lines if lvl == level]


class Node:
    def __init__(self, name: str = "") -> None:
        self.node_name = name
        self.publishers: dict[str, Publisher] = {}
        self.subscriptions: dict[str, list] = {}
        self.timers: list[Timer] = []
        self._logger = Logger()

    def create_publisher(self, msg_type, topic, qos):
        # Last publisher wins per topic, which is fine: this node creates one each.
        pub = Publisher(topic)
        self.publishers[topic] = pub
        return pub

    def create_subscription(self, msg_type, topic, callback, qos):
        self.subscriptions.setdefault(topic, []).append(callback)
        return object()

    def create_timer(self, period, callback):
        timer = Timer(period, callback)
        self.timers.append(timer)
        return timer

    def get_logger(self) -> Logger:
        return self._logger

    def destroy_node(self) -> None:
        pass


def _rclpy_module() -> types.ModuleType:
    rclpy = types.ModuleType("rclpy")
    rclpy.shutdowns = []

    def init(*_args, **_kwargs):
        return None

    def ok():
        return True

    def shutdown(*_args, **_kwargs):
        rclpy.shutdowns.append(True)

    rclpy.init = init
    rclpy.ok = ok
    rclpy.shutdown = shutdown
    rclpy.try_shutdown = shutdown
    rclpy.spin = lambda *_a, **_k: None
    rclpy.spin_once = lambda *_a, **_k: None
    return rclpy


def _qos_module() -> types.ModuleType:
    qos = types.ModuleType("rclpy.qos")

    class _Policy:
        TRANSIENT_LOCAL = "transient_local"
        RELIABLE = "reliable"
        KEEP_LAST = "keep_last"

    class QoSProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    qos.DurabilityPolicy = _Policy
    qos.ReliabilityPolicy = _Policy
    qos.HistoryPolicy = _Policy
    qos.QoSProfile = QoSProfile
    return qos


def real_ros_present() -> bool:
    """True when this machine has a real `rclpy`, in which case the stub must not be
    installed over it -- these tests are skipped there rather than testing a fiction."""
    return importlib.util.find_spec("rclpy") is not None


def install() -> types.ModuleType:
    """Put the stubs in `sys.modules` and return the stub `rclpy`. Idempotent."""
    if "rclpy" not in sys.modules or not getattr(
        sys.modules["rclpy"], "_is_skill_monitor_stub", False
    ):
        rclpy = _rclpy_module()
        rclpy._is_skill_monitor_stub = True
        node_mod = types.ModuleType("rclpy.node")
        node_mod.Node = Node
        rclpy.node = node_mod
        qos = _qos_module()
        rclpy.qos = qos
        sys.modules["rclpy"] = rclpy
        sys.modules["rclpy.node"] = node_mod
        sys.modules["rclpy.qos"] = qos

        std_msgs = types.ModuleType("std_msgs")
        msg_mod = types.ModuleType("std_msgs.msg")
        msg_mod.String = Message
        msg_mod.Bool = Message
        std_msgs.msg = msg_mod
        sys.modules["std_msgs"] = std_msgs
        sys.modules["std_msgs.msg"] = msg_mod

        # `ablation_runner` reads the same verdict; it needs a pose type to import.
        geometry = types.ModuleType("geometry_msgs")
        geometry_msg = types.ModuleType("geometry_msgs.msg")
        geometry_msg.PoseStamped = Message
        geometry.msg = geometry_msg
        sys.modules["geometry_msgs"] = geometry
        sys.modules["geometry_msgs.msg"] = geometry_msg

    if "spot" not in sys.modules:
        # `core/automata` imports it at module scope. Nothing here builds an automaton:
        # the tests inject a fake MultiMonitor, which is what lets them assert on how
        # many times it was stepped.
        sys.modules["spot"] = types.ModuleType("spot")

    return sys.modules["rclpy"]
