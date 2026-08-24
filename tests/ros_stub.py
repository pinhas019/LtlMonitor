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
importable -- it asks `real_ros_present()`, not whether `rclpy` happens to have been
imported yet, because an installed-but-unimported ROS is exactly the case where
replacing `rclpy`, `std_msgs` and `geometry_msgs` for the whole pytest process does
damage. The `pytestmark` skipif in the test modules does not cover this: skipif
suppresses *tests*, and `install()` runs at module scope, before any of them.

**What this stub is not.** Everything below is a fidelity gap, and a test that would
only pass because of one of them is testing this file rather than the package:

* **Timers never fire.** `create_timer` records the callback and stops. Anything the
  node schedules -- `heartbeat`, `_do_shutdown` -- has zero coverage unless a test
  calls it directly, which is why `test_monitor_node.py` does exactly that.
* **The three QoS policy enums are one aliased class.** `DurabilityPolicy`,
  `ReliabilityPolicy` and `HistoryPolicy` are all `_Policy`, so a nonsense pairing
  like `DurabilityPolicy.RELIABLE` resolves here and would fail against real rclpy.
* **`QoSProfile` accepts arbitrary keyword arguments** and never validates them.
* **No transport.** No message loss, no QoS depth or history, no ordering between
  topics, no delivery latency: a callback runs synchronously inside the call that
  publishes to it. Nothing here can pin behaviour that depends on any of those.
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
    def __init__(self, topic: str, qos=None) -> None:
        self.topic = topic
        #: The profile object handed to `create_publisher`, kept verbatim and never
        #: interpreted -- see the docstring above on what this stub does not simulate.
        #: It is enough to say *which* profile a topic was created with, which is the
        #: difference between a latched topic and one a late subscriber never hears.
        self.qos = qos
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
        pub = Publisher(topic, qos)
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

    def get_topic_names_and_types(self):
        # ponytail: only the topics this node itself made. A real graph also lists
        # every other node's — give the stub a settable list when a test needs one.
        return [(topic, []) for topic in sorted({*self.publishers, *self.subscriptions})]

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


#: Set on the stub `rclpy` so it can be told from a real one in `sys.modules`.
_STUB_FLAG = "_is_skill_monitor_stub"


def real_ros_present() -> bool:
    """True when this machine has a real `rclpy`, in which case the stub must not be
    installed over it -- these tests are skipped there rather than testing a fiction.

    Answers the same way before and after `install()`. `importlib.util.find_spec` reads
    `sys.modules` first and raises `ValueError: rclpy.__spec__ is None` for a module
    built with `types.ModuleType`, which is every module in this file -- so an
    already-installed stub is recognised by its flag rather than handed to `find_spec`.
    """
    existing = sys.modules.get("rclpy")
    if existing is not None:
        return not getattr(existing, _STUB_FLAG, False)
    try:
        return importlib.util.find_spec("rclpy") is not None
    except (ImportError, ValueError):
        # An `rclpy` whose own import machinery is broken is not one to shadow either.
        return False


def install() -> types.ModuleType | None:
    """Put the stubs in `sys.modules` and return the stub `rclpy`. Idempotent.

    Returns None, having changed nothing, when a real ROS is installed on this machine:
    the modules replaced here are process-wide, and `sys.modules` is not the question --
    a real `rclpy` that simply has not been imported yet is still the one that must win.
    """
    if real_ros_present():
        return None
    if "rclpy" not in sys.modules or not getattr(
        sys.modules["rclpy"], _STUB_FLAG, False
    ):
        rclpy = _rclpy_module()
        setattr(rclpy, _STUB_FLAG, True)
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
