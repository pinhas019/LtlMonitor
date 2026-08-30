"""`session`'s wiring: the bundle it writes, the bag it launches, and how it closes.

`core/session.py` is the manifest and the completeness rule and is tested without any of
this. What is left in `backend/replay_node.py` is the part that has to be right on the
one day it runs beside a robot: subscribe, wait for the latched adapter frame, read the
bag's topic list off it, spawn `ros2 bag record`, and — the one nobody thinks about —
close that child so the bag is readable afterwards.

`tests/ros_stub.py` supplies the graph and `spin_once` is made to deliver frames, which
is what a real executor does. `ros2` is a fake on PATH that records its argv and exits
only on SIGINT, so "the bag was closed properly" is checkable rather than assumed.

**What this cannot cover**, stated so a green run here is not mistaken for a green run
on a robot: no DDS, so nothing here proves a TRANSIENT_LOCAL subscription actually
receives a frame published before it existed, and no rosbag2, so nothing here proves the
real recorder accepts the argv or writes a bag `ros2 bag play` will open. Those need a
machine with ROS 2 on it.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ros_stub                                                      # noqa: E402

pytestmark = pytest.mark.skipif(
    ros_stub.real_ros_present(),
    reason="a real rclpy is present; this drives the stub and would test a fiction")

ros_stub.install()

from skill_monitor.backend import replay_node                        # noqa: E402
from skill_monitor.core import api, session                          # noqa: E402


ADAPTER = {"adapter": "mujoco", "tick_hz": 1.0,
           "sources": [{"topic": "/odom"}, {"topic": "/scan"}],
           "scene": ["/tf", "/map"]}
MANIFEST = {"skill_name": "G1Nav", "phases": ["approach"], "source": "formulas_g1.json"}


def a_verdict(seq, verdict="SATISFIED", terminal=None):
    return {"seq": seq, "verdict": verdict, "terminal": terminal}


def an_episode(ticks=3):
    """The frames a live graph would deliver, in the order it would deliver them: the
    two latched documents on subscription, then the per-tick stream."""
    frames = [(api.ADAPTER, ADAPTER), (api.MANIFEST, MANIFEST)]
    for seq in range(1, ticks + 1):
        frames += [(api.TICK, {"seq": seq, "t": float(seq)}),
                   (api.OBSERVATION, {"seq": seq}),
                   (api.VERDICT, a_verdict(seq))]
    return frames


# ---------------------------------------------------------------- the harness

def fake_ros2(tmp_path: pathlib.Path) -> pathlib.Path:
    """A `ros2` that records its argv and exits ONLY on SIGINT.

    The exit path is the point. rosbag2 closes its database on interrupt and leaves a
    bag that cannot be opened if it is killed instead, so `metadata.yaml` existing is
    this test's proxy for "the child was asked to stop, not shot".
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "ros2"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, signal, sys, time\n"
        "pathlib.Path(os.environ['FAKE_ROS2_ARGV']).write_text(json.dumps(sys.argv[1:]))\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "def bye(*_):\n"
        "    (out / 'metadata.yaml').write_text('closed on SIGINT\\n')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGINT, bye)\n"
        "while True: time.sleep(0.02)\n",
        encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


class Args:
    def __init__(self, path, **over):
        self.path = str(path)
        self.note = ""
        self.no_bag = False
        self.adapter_timeout = 5.0
        self.append = False
        self.__dict__.update(over)


def drive(monkeypatch, frames, ready=None, at_spin=None):
    """Deliver `frames` through the node's own subscriptions, as an executor would.

    `spin_once` hands over one frame; `spin` drains the rest and then raises
    KeyboardInterrupt, which is exactly what Ctrl-C does to a real session and is the
    only way `run_session` ever reaches its cleanup.

    `ready` is a path to wait for before the interrupt -- the child recorder's first
    write. Without it the session would end microseconds after spawning `ros2`, before
    the child has installed its own SIGINT handler, and the test would be measuring a
    race rather than the behaviour. A real session outlives the bag's startup by the
    length of an episode.

    **Both replacements check which node they were handed and delegate anything that is
    not ours.** `rclpy` is one module object shared by the whole pytest process, and
    other suites leave executor threads spinning on it (`test_gateway.py`'s gateway is
    one). Patching `spin_once` unconditionally hands our frames to whichever node that
    thread happens to be driving -- the session then never sees its adapter, waits out
    its timeout, and records no bag. That failure appears only in a full-suite run and
    not when this file runs alone, which is the worst shape a test failure can have.
    """
    import rclpy
    pending = list(frames)
    box = {}

    real_create = rclpy.create_node

    def create_node(name):
        box["node"] = node = real_create(name)
        return node

    def deliver_one():
        if not pending:
            return False
        topic, payload = pending.pop(0)
        for callback in box["node"].subscriptions.get(topic, []):
            callback(ros_stub.Message(json.dumps(payload)))
        return True

    prior_spin_once, prior_spin = rclpy.spin_once, rclpy.spin

    def ours(node) -> bool:
        return node is not None and node is box.get("node")

    def spin_once(node=None, *a, **k):
        if not ours(node):
            return prior_spin_once(node, *a, **k)
        deliver_one()

    def spin(node=None, *a, **k):
        if not ours(node):
            return prior_spin(node, *a, **k)
        return _drain()

    def _drain():
        while deliver_one():
            pass
        if ready is not None:
            deadline = time.monotonic() + 10.0
            while not pathlib.Path(ready).exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        if at_spin is not None:
            at_spin()
        raise KeyboardInterrupt

    monkeypatch.setattr(rclpy, "create_node", create_node)
    monkeypatch.setattr(rclpy, "spin_once", spin_once)
    monkeypatch.setattr(rclpy, "spin", spin)
    return box


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{fake_ros2(tmp_path)}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_ROS2_ARGV", str(tmp_path / "argv.json"))
    return tmp_path / "g1_run1"


def argv_of(bundle) -> list:
    return json.loads((bundle.parent / "argv.json").read_text(encoding="utf-8"))


def manifest_of(bundle) -> dict:
    return json.loads((bundle / session.MANIFEST).read_text(encoding="utf-8"))


# =============================================================================
# One command, one directory
# =============================================================================

def test_a_session_writes_the_whole_bundle(bundle, monkeypatch):
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    code = replay_node.run_session(Args(bundle, note="dead end on purpose"))

    assert code == 0, "a complete session exits 0"
    assert (bundle / session.MANIFEST).exists()
    assert (bundle / session.STREAM).exists()
    assert (bundle / session.BAG).is_dir()


def test_the_stream_holds_the_inputs_and_the_outputs(bundle, monkeypatch):
    """Both halves, which is what makes the bundle a comparison rather than a replay:
    the inputs are what gets replayed, the outputs are what it is checked against."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))
    counts = manifest_of(bundle)["frames"]

    assert counts[api.OBSERVATION] == 3 and counts[api.VERDICT] == 3
    assert counts[api.ADAPTER] == 1 and counts[api.MANIFEST] == 1


def test_the_manifest_indexes_the_run_from_its_own_latched_frames(bundle, monkeypatch):
    """Which robot and which skill, copied onto session.json so a directory answers
    "what is this?" before anything inside it is opened."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle, note="dead end on purpose"))
    doc = manifest_of(bundle)

    assert (doc["adapter"], doc["skill"], doc["tick_hz"]) == ("mujoco", "G1Nav", 1.0)
    assert doc["note"] == "dead end on purpose"
    assert doc["verdict"] == {"verdict": "SATISFIED", "terminal": None, "seq": 3}
    assert doc["ended"] is not None and session.duration_s(doc) is not None


# =============================================================================
# The bag it launches
# =============================================================================

def test_the_bag_line_is_read_off_the_adapter_and_carries_the_scene(bundle, monkeypatch):
    """Not hardcoded, and not sources-only. Sources alone record a run that can be
    checked and never re-executed."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))

    assert argv_of(bundle) == ["bag", "record", "-o", str(bundle / session.BAG),
                               "/odom", "/scan", "/tf", "/map"]
    assert manifest_of(bundle)["bag"]["scene"] == ["/tf", "/map"]


def test_the_bag_is_closed_on_sigint_and_not_killed(bundle, monkeypatch):
    """rosbag2 writes its metadata on interrupt. Killed instead, it leaves a directory
    `ros2 bag play` refuses to open -- an episode recorded and then unreadable, which
    is the worst of the failures available here."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))

    assert (bundle / session.BAG / "metadata.yaml").exists()


def test_no_bag_is_asked_for_when_the_adapter_never_arrives(bundle, monkeypatch):
    """The evaluator is not running. Guessing a topic list from this machine's copy of
    the descriptor would record a bag against a robot that was never confirmed."""
    drive(monkeypatch, [(api.TICK, {"seq": 1}), (api.OBSERVATION, {"seq": 1})])
    code = replay_node.run_session(Args(bundle, adapter_timeout=0.2))

    assert not (bundle.parent / "argv.json").exists(), "ros2 was never invoked"
    assert code == 1
    assert any("no sensor bag" in p for p in session.problems(manifest_of(bundle)))


def test_no_bag_is_a_choice_the_operator_can_make(bundle, monkeypatch):
    drive(monkeypatch, an_episode())
    code = replay_node.run_session(Args(bundle, no_bag=True))

    assert not (bundle.parent / "argv.json").exists()
    assert code == 1, "a stream-only session is incomplete, and says so"


# =============================================================================
# What it refuses, and what it leaves behind when it dies
# =============================================================================

def test_a_second_session_will_not_overwrite_the_first(bundle, monkeypatch):
    """Two runs in one bundle is a bundle whose verdicts belong to two episodes, and
    the `--diff` that later compares them has no way to know."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))
    first = (bundle / session.STREAM).read_text(encoding="utf-8")

    drive(monkeypatch, an_episode())
    assert replay_node.run_session(Args(bundle)) == 2
    assert (bundle / session.STREAM).read_text(encoding="utf-8") == first


def test_the_manifest_exists_before_the_first_frame_does(bundle, monkeypatch):
    """A flat battery mid-run must still leave a directory that says what it was. The
    manifest is written at the start, so a session killed halfway leaves `ended: null`
    as the finding rather than an empty directory as the whole story."""
    seen = {}
    drive(monkeypatch, an_episode(), at_spin=lambda: seen.update(mid=manifest_of(bundle)))
    replay_node.run_session(Args(bundle, no_bag=True))

    assert seen["mid"]["session"] == "g1_run1"
    assert seen["mid"]["ended"] is None, "not yet finished, and it says so"
    assert manifest_of(bundle)["ended"] is not None, "and it is closed at the end"


def test_a_bag_that_wrote_nothing_is_not_claimed_as_one(bundle, monkeypatch):
    """The manifest records the topic list when the recorder is LAUNCHED, which is a
    claim about intent. `ros2` missing from PATH, an unwritable /data or an absent
    storage plugin all leave a bundle whose session.json says "4 topics bagged" and
    whose directory holds nothing -- and `verify` passing that is the one thing it
    exists to prevent."""
    monkeypatch.setenv("PATH", "/nonexistent")
    drive(monkeypatch, an_episode())
    code = replay_node.run_session(Args(bundle))
    doc = manifest_of(bundle)

    assert code == 1
    assert doc["bag"]["topics"] == [], "no claim survives a recorder that wrote nothing"
    assert "could not start" in doc["bag"]["failed"]
    assert any("could not start" in p for p in session.problems(doc))
    assert (bundle / session.STREAM).exists(), "losing the bag must not lose the session"
    assert manifest_of(bundle)["frames"][api.VERDICT] == 3


# =============================================================================
# verify, on what session just wrote
# =============================================================================

def test_verify_passes_the_bundle_session_just_wrote(bundle, monkeypatch, capsys):
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))
    capsys.readouterr()

    assert replay_node.run_verify(Args(bundle)) == 0
    assert "Complete" in capsys.readouterr().out


def test_verify_refuses_a_directory_that_is_not_a_bundle(tmp_path, capsys):
    assert replay_node.run_verify(Args(tmp_path)) == 2
    assert "not a session bundle" in capsys.readouterr().err


def test_every_subcommand_takes_the_bundle_directory(bundle, monkeypatch, capsys):
    """The bundle is the unit. Asking someone to remember which file inside it holds
    the frames would put the pile back."""
    drive(monkeypatch, an_episode(), ready=os.environ['FAKE_ROS2_ARGV'])
    replay_node.run_session(Args(bundle))
    capsys.readouterr()

    assert replay_node.run_info(Args(bundle)) == 0
    assert "mujoco" in capsys.readouterr().out

    class TopicArgs(Args):
        scene = True

    assert replay_node.run_topics(TopicArgs(bundle)) == 0
    assert capsys.readouterr().out.split() == ["/odom", "/scan", "/tf", "/map"]
