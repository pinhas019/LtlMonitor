#!/usr/bin/env python3
"""G1 nav episode runner: runs a scenario N times, back to back, and writes one episode
record per run (`core/episode_record.py`).

    python -m skill_monitor.backend.ablation_runner \\
        --scenario sim/scenarios/clear.json --episodes 20 --arm full --out episodes.jsonl

Per episode:
  1. publish the scenario (with this run's seed) on /g1/reset and wait for /g1/reset_done
     -- the MuJoCo bridge implements it (sim/mujoco_ros_bridge.py). A rejected or
     timed-out reset is recorded as such and the run moves on; it is never driven blind.
  2. arm the monitor (api.COMMAND) so it starts the skill from its first phase;
  3. send the scenario's first goal on /goal_pose;
  4. spin until `classify_outcome` says terminal: Nav2 status for *this* goal (stale
     statuses from earlier episodes are ignored, `GoalStatusTracker`), a halting
     monitor verdict, or the scenario's `duration_s`.

`--arm` is a label for the analysis, e.g. `full`, `flattened`, `off`; configuring the
monitor for that arm is the caller's job. The scenario file is passed through to the
simulator unvalidated beyond what this runner needs -- the bridge validates it fully and
answers `reset_done: false` if it cannot run it.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import Bool, String

from skill_monitor.core import api, episode_record, manifest
from skill_monitor.core.episode_outcome import GoalStatusTracker, classify_outcome

RESET_TOPIC = "/g1/reset"
RESET_DONE_TOPIC = "/g1/reset_done"
GOAL_TOPIC = "/goal_pose"
NAV_STATUS_TOPIC = "/navigate_to_pose/_action/status"


def safety_fault_from_verdict(verdict: dict) -> str | None:
    """The name of the fault that stopped the robot, or None.

    Read straight off the verdict's intervention token rather than re-graded here. The
    monitor decides the rung; an episode driver that re-derived it from the raw failure
    modes would be a third opinion on the same tick, and the one most likely to drift.

    Which mode gets *named* comes from `manifest.breached_mode`, i.e. from the same
    precedence the token itself was graded with. Taking the first VIOLATED entry
    instead used to be indistinguishable, and stopped being so the moment the verdict
    started carrying the phase machine's fault alongside the spec's named modes: an
    episode halted for a collision could be recorded under a phase name that was
    breached on the same tick.
    """
    intervention = (verdict or {}).get("intervention") or {}
    if not manifest.token_halts(intervention.get("action", "CONTINUE")):
        return None
    breached = manifest.breached_mode((verdict or {}).get("failure_modes") or [])
    return (breached or {}).get("name") or intervention.get("category") or "fault"


def _goal_id(entry) -> str:
    return bytes(entry.goal_info.goal_id.uuid).hex()


class G1EpisodeDriver(Node):
    def __init__(self, *, reset_timeout_s: float = 30.0, verdict_grace_s: float = 2.0):
        super().__init__("g1_episode_driver")
        self.reset_timeout_s = reset_timeout_s
        #: Verdicts arriving this soon after `arm` may still be the previous episode's
        #: last tick in flight; a halting one would end the new episode at t = 0.
        self.verdict_grace_s = verdict_grace_s
        self.nav = GoalStatusTracker()
        self.verdict: dict = {}
        self.detected_seq: int | None = None
        self.reset_result: bool | None = None
        self._accept_verdicts_after = float("inf")

        self.reset_pub = self.create_publisher(String, RESET_TOPIC, 10)
        self.goal_pub = self.create_publisher(PoseStamped, GOAL_TOPIC, 10)
        self.command_pub = self.create_publisher(String, api.COMMAND, 10)
        self.create_subscription(String, api.VERDICT, self._on_verdict, 10)
        self.create_subscription(Bool, RESET_DONE_TOPIC, self._on_reset_done, 10)
        # Imported here so this module parses without action_msgs installed.
        from action_msgs.msg import GoalStatusArray
        self.create_subscription(GoalStatusArray, NAV_STATUS_TOPIC, self._on_nav_status, 10)

    # ---- callbacks ----

    def _on_verdict(self, msg: String) -> None:
        if time.monotonic() < self._accept_verdicts_after:
            return
        try:
            verdict = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        self.verdict = verdict
        if self.detected_seq is None and safety_fault_from_verdict(verdict):
            seq = verdict.get("seq")
            self.detected_seq = seq if isinstance(seq, int) else None

    def _on_reset_done(self, msg: Bool) -> None:
        self.reset_result = bool(msg.data)

    def _on_nav_status(self, msg) -> None:
        self.nav.observe((_goal_id(e), e.status) for e in msg.status_list)

    # ---- one episode ----

    def run_episode(self, scenario: dict, *, arm: str, episode_id: str) -> dict:
        """Reset to `scenario`, drive to its first goal, return a validated record."""
        name = scenario.get("name", "")
        seed = scenario.get("seed", 0)
        timeout_s = float(scenario.get("duration_s", 120.0))
        self.verdict, self.detected_seq, self.reset_result = {}, None, None
        self._accept_verdicts_after = float("inf")
        started = time.monotonic()

        # Scheduled, not yet injected: the injection tick is the injector's to set (SIM.4),
        # never this runner's and never the monitor's.
        faults = [episode_record.build_fault(type=f["type"], onset_s=f["onset_s"],
                                             params=f.get("params"))
                  for f in scenario.get("faults", [])]

        def record(*, terminal, success, cause, elapsed):
            return episode_record.build_record(
                episode_id=episode_id, arm=arm, seed=seed, scenario=name,
                scenario_params=scenario, faults=faults,
                terminal=terminal, success=success, cause=cause,
                elapsed_s=round(elapsed, 2), steps=self.verdict.get("step"),
                detected_tick=self.detected_seq,
                timing={"wall_s": round(time.monotonic() - started, 2)},
            )

        self.reset_pub.publish(String(data=json.dumps(scenario)))
        self._spin_until(lambda: self.reset_result is not None, self.reset_timeout_s)
        if self.reset_result is not True:
            cause = "reset_rejected" if self.reset_result is False else "reset_timeout"
            self.get_logger().error(f"{episode_id}: {cause}; episode not run")
            return record(terminal=True, success=False, cause=cause, elapsed=0.0)

        self.command_pub.publish(String(data=json.dumps(api.build_command(command="arm"))))
        self._accept_verdicts_after = time.monotonic() + self.verdict_grace_s
        self.nav.begin()
        self.goal_pub.publish(self._goal(scenario["goals"][0]))

        start = time.monotonic()
        outcome = classify_outcome("", None, False)
        while rclpy.ok() and not outcome.terminal:
            rclpy.spin_once(self, timeout_sec=0.1)
            timed_out = (time.monotonic() - start) > timeout_s
            outcome = classify_outcome(self.nav.status,
                                       safety_fault_from_verdict(self.verdict), timed_out)
        return record(terminal=outcome.terminal, success=outcome.success,
                      cause=outcome.cause or "interrupted",
                      elapsed=time.monotonic() - start)

    def _goal(self, goal_xy) -> PoseStamped:
        goal = PoseStamped()
        goal.header.frame_id = "map"
        goal.header.stamp = self.get_clock().now().to_msg()
        goal.pose.position.x, goal.pose.position.y = float(goal_xy[0]), float(goal_xy[1])
        goal.pose.orientation.w = 1.0
        return goal

    def _spin_until(self, pred, timeout_s: float) -> None:
        start = time.monotonic()
        while rclpy.ok() and not pred() and (time.monotonic() - start) < timeout_s:
            rclpy.spin_once(self, timeout_sec=0.1)


def load_scenario(path: str | Path) -> dict:
    """The scenario as the simulator will receive it. Only what this runner reads is
    checked here; the bridge validates the rest and refuses what it cannot run."""
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(scenario, dict) or not scenario.get("name") \
            or not isinstance(scenario.get("goals"), list) or not scenario["goals"]:
        raise SystemExit(f"{path}: a scenario needs a name and at least one goal")
    return scenario


def run(node: G1EpisodeDriver, scenario: dict, *, episodes: int, seed_start: int,
        arm: str, out: Path) -> list[dict]:
    records = []
    for i in range(episodes):
        seed = seed_start + i
        episode = {**scenario, "seed": seed}
        episode_id = f"{arm}-{scenario['name']}-s{seed}-{i:04d}"
        rec = node.run_episode(episode, arm=arm, episode_id=episode_id)
        episode_record.write_record(out, rec)
        node.get_logger().info(
            f"{episode_id}: {'success' if rec['success'] else 'failure'} ({rec['cause']}, "
            f"{rec['elapsed_s']} s)")
        records.append(rec)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a scenario N times and record each.")
    parser.add_argument("--scenario", required=True, help="sim/scenarios/<name>.json")
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--arm", default="full", help="label for the analysis")
    parser.add_argument("--out", default="episodes.jsonl")
    parser.add_argument("--reset-timeout", type=float, default=30.0)
    args, ros_args = parser.parse_known_args(argv)

    scenario = load_scenario(args.scenario)
    rclpy.init(args=ros_args)
    node = G1EpisodeDriver(reset_timeout_s=args.reset_timeout)
    try:
        run(node, scenario, episodes=args.episodes, seed_start=args.seed_start,
            arm=args.arm, out=Path(args.out))
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
