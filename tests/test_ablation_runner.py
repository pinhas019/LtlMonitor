"""The episode runner, driven against a scripted world through `tests/ros_stub.py`.

What it must get right, and used not to:
  * a reset that is rejected or never answered is recorded as such, not driven blind
    (it used to continue after its 20 s timeout as if the reset had happened);
  * Nav2's status list still holds the previous episode's finished goal, and that
    stale `succeeded` must not end the next episode before the robot moves;
  * a halting verdict still in flight from the previous episode must not either;
  * every episode ends as a valid `core/episode_record` line.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ros_stub

pytestmark = pytest.mark.skipif(
    ros_stub.real_ros_present(),
    reason="a real rclpy is installed; these tests drive a stub and must not shadow it",
)

ros_stub.install()

from skill_monitor.backend import ablation_runner as runner            # noqa: E402
from skill_monitor.core import api, episode_record                     # noqa: E402
from skill_monitor.core.episode_outcome import GoalStatusTracker        # noqa: E402

SCENARIO = {"name": "clear", "seed": 0, "goals": [[3.0, 0.0]], "duration_s": 5.0,
            "faults": [{"type": "push", "onset_s": 4.0, "params": {"force_n": 300}}]}
HALTING = {"seq": 41, "step": 12, "intervention": {"action": "HALT", "category": "SAFETY"},
           "failure_modes": [{"name": "fell_over", "fault_category": "SAFETY",
                              "status": "VIOLATED"}]}


class Msg:
    """A message whose nested fields spring into existence, as ROS messages' do."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = Msg()
        setattr(self, name, value)
        return value

    @property
    def data(self):
        return self


def statuses(*entries):
    """A GoalStatusArray: (goal id byte, status code) pairs."""
    return SimpleNamespace(status_list=[
        SimpleNamespace(goal_info=SimpleNamespace(goal_id=SimpleNamespace(uuid=[gid] * 16)),
                        status=code)
        for gid, code in entries])


class World:
    """Stands in for the simulator, Nav2 and the monitor. `spin_once` advances it."""

    def __init__(self, node, *, reset_reply=True, script=()):
        self.node = node
        self.reset_reply = reset_reply
        self.script = list(script)          # callables run one per spin after the goal
        self.resets_seen = 0

    def deliver(self, topic, message):
        for callback in self.node.subscriptions[topic]:
            callback(message)

    def spin_once(self, *_a, **_k):
        resets = self.node.publishers[runner.RESET_TOPIC].sent
        if len(resets) > self.resets_seen:
            self.resets_seen = len(resets)
            if self.reset_reply is not None:
                self.deliver(runner.RESET_DONE_TOPIC, SimpleNamespace(data=self.reset_reply))
            return
        if self.node.publishers[runner.GOAL_TOPIC].sent and self.script:
            self.script.pop(0)(self)


@pytest.fixture
def node():
    made = runner.G1EpisodeDriver(reset_timeout_s=0.3, verdict_grace_s=0.0)
    yield made
    made.destroy_node()


@pytest.fixture(autouse=True)
def rich_pose(monkeypatch):
    monkeypatch.setattr(runner, "PoseStamped", Msg)


def drive(monkeypatch, node, world, scenario=SCENARIO, episode_id="full-clear-s0-0000"):
    monkeypatch.setattr(runner.rclpy, "spin_once", world.spin_once)
    return node.run_episode(dict(scenario), arm="full", episode_id=episode_id)


def nav(*entries):
    return lambda w: w.deliver(runner.NAV_STATUS_TOPIC, statuses(*entries))


def verdict(payload):
    return lambda w: w.deliver(api.VERDICT, SimpleNamespace(data=json.dumps(payload)))


# =============================================================================
# The goal tracker (pure)
# =============================================================================

def test_a_finished_goal_from_before_begin_is_ignored():
    tracker = GoalStatusTracker()
    tracker.observe([("old", 4)])
    tracker.begin()
    tracker.observe([("old", 4)])
    assert tracker.status == ""
    tracker.observe([("old", 4), ("new", 2)])
    assert tracker.status == "executing"
    tracker.observe([("old", 4), ("new", 4)])
    assert tracker.status == "succeeded"


def test_the_previous_episodes_goal_is_ignored_even_if_no_status_arrived_between():
    tracker = GoalStatusTracker()
    tracker.begin()
    tracker.observe([("first", 4)])
    assert tracker.status == "succeeded"
    tracker.begin()                         # next episode, immediately
    tracker.observe([("first", 4)])
    assert tracker.status == ""


# =============================================================================
# One episode
# =============================================================================

def test_a_successful_episode_is_a_valid_record(monkeypatch, node):
    world = World(node, script=[nav((1, 2)), nav((1, 4))])
    rec = drive(monkeypatch, node, world)
    assert episode_record.validate_record(rec) == []
    assert rec["success"] is True and rec["cause"] == "reached_goal"
    assert rec["arm"] == "full" and rec["scenario"] == "clear"


def test_the_episode_is_bracketed_reset_then_arm_then_goal(monkeypatch, node):
    world = World(node, script=[nav((1, 4))])
    drive(monkeypatch, node, world)
    (reset,) = node.publishers[runner.RESET_TOPIC].sent
    assert json.loads(reset)["name"] == "clear"
    (command,) = node.publishers[api.COMMAND].sent
    assert api.validate_command(json.loads(command)) == []
    assert json.loads(command)["command"] == "arm"
    (goal,) = node.publishers[runner.GOAL_TOPIC].sent
    assert (goal.pose.position.x, goal.pose.position.y) == (3.0, 0.0)
    assert goal.header.frame_id == "map"


def test_a_stale_succeeded_from_the_last_episode_does_not_end_this_one(monkeypatch, node):
    """The bug: the last entry of Nav2's status list was read, and it was the previous
    goal's `succeeded`, so the next episode ended at t = 0 as a success."""
    node.nav.observe([(bytes([7] * 16).hex(), 4)])      # left over from before
    world = World(node, script=[nav((7, 4)), nav((7, 4), (8, 2)), nav((7, 4), (8, 6))])
    rec = drive(monkeypatch, node, world)
    assert rec["success"] is False and rec["cause"] == "nav_failed"


def test_a_halting_verdict_ends_the_episode_and_records_its_tick(monkeypatch, node):
    world = World(node, script=[nav((1, 2)), verdict(HALTING)])
    rec = drive(monkeypatch, node, world)
    assert rec["success"] is False and rec["cause"] == "fell_over"
    assert rec["detected_tick"] == 41 and rec["steps"] == 12


def test_a_verdict_from_the_previous_episode_is_ignored_during_the_grace(monkeypatch):
    node = runner.G1EpisodeDriver(reset_timeout_s=0.3, verdict_grace_s=60.0)
    world = World(node, script=[verdict(HALTING), nav((1, 4))])
    rec = drive(monkeypatch, node, world)
    assert rec["cause"] == "reached_goal" and rec["detected_tick"] is None


def test_a_rejected_reset_is_recorded_and_the_robot_is_not_driven(monkeypatch, node):
    rec = drive(monkeypatch, node, World(node, reset_reply=False))
    assert rec["cause"] == "reset_rejected" and rec["success"] is False
    assert node.publishers[runner.GOAL_TOPIC].sent == []
    assert episode_record.validate_record(rec) == []


def test_an_unanswered_reset_times_out_instead_of_continuing_blind(monkeypatch, node):
    rec = drive(monkeypatch, node, World(node, reset_reply=None))
    assert rec["cause"] == "reset_timeout"
    assert node.publishers[runner.GOAL_TOPIC].sent == []


def test_an_episode_that_never_finishes_times_out_at_the_scenario_duration(monkeypatch, node):
    rec = drive(monkeypatch, node, World(node, script=[nav((1, 2))]),
                scenario={**SCENARIO, "duration_s": 0.2})
    assert rec["cause"] == "timeout" and rec["success"] is False


def test_scheduled_faults_are_recorded_as_not_yet_injected(monkeypatch, node):
    rec = drive(monkeypatch, node, World(node, script=[nav((1, 4))]))
    (fault,) = rec["faults"]
    assert fault["type"] == "push" and fault["onset_s"] == 4.0
    assert fault["injected_tick"] is None, "only the injector may set this"


# =============================================================================
# A run of several
# =============================================================================

def test_a_run_writes_one_record_per_episode_with_consecutive_seeds(monkeypatch, node,
                                                                  tmp_path):
    out = tmp_path / "episodes.jsonl"

    class Repeating(World):
        def spin_once(self, *a, **k):
            if not self.script:
                self.script = [nav((len(self.node.publishers[runner.GOAL_TOPIC].sent), 4))]
            super().spin_once(*a, **k)

    monkeypatch.setattr(runner.rclpy, "spin_once", Repeating(node).spin_once)
    records = runner.run(node, SCENARIO, episodes=3, seed_start=10, arm="flattened", out=out)
    assert [r["seed"] for r in records] == [10, 11, 12]
    assert all(r["success"] for r in records)
    written = list(episode_record.read_records(out))
    assert written == records
    assert [json.loads(s)["seed"] for s in node.publishers[runner.RESET_TOPIC].sent] \
        == [10, 11, 12]


def test_a_scenario_without_a_goal_is_refused_before_anything_runs(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "x", "goals": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        runner.load_scenario(path)
