#!/usr/bin/env python3
"""G1 nav episode runner: runs scenarios back to back and writes one episode record per
run (`core/episode_record.py`).

    python -m skill_monitor.backend.ablation_runner \\
        --scenario-dir sim/scenarios/generated --arm full --policy recover \\
        --out episodes.jsonl
    python -m skill_monitor.backend.ablation_runner \\
        --scenario sim/scenarios/clear.json --episodes 20 --arm full --out episodes.jsonl

Per episode:
  1. publish the scenario on /g1/reset and wait for /g1/reset_done -- the MuJoCo bridge
     implements it (sim/mujoco_ros_bridge.py). A rejected or timed-out reset is recorded
     as such and the run moves on; it is never driven blind.
  2. arm the monitor (api.COMMAND) so it starts the skill from its first phase;
  3. send the scenario's first goal on /goal_pose;
  4. spin until `decide_step` ends it, under `--policy`:
       off      the monitor's interventions are recorded, not acted on;
       detect   the first intervention (REPLAN or worse, or terminal FAILURE) ends the
                episode as a stop;
       recover  an intervention re-plans: a fresh goal-status window, the goal re-sent
                (Nav2 preempts and plans again), the monitor re-armed so its phase
                machine starts over -- up to `--max-recoveries`, then a stop.
     The outcome itself is ground truth from the simulator (/g1/ground_truth): a fall
     ends the episode under every policy, and Nav2's `succeeded` counts only if the
     robot is truly within `ARRIVAL_RADIUS_M` of the goal. Nav2 statuses from earlier
     goals are ignored (`GoalStatusTracker`).

Ground truth for detection comes from the injector: each /g1/fault_injected event is
stamped with the clock tick (`api.TICK`) current when it arrives, as `injected_tick` --
the same clock the monitor's `detected_tick` is counted on.

`--arm` is a label for the analysis, e.g. `full`, `flattened`; configuring the monitor for
that arm is the caller's job. A scenario is passed through to the simulator unvalidated
beyond what this runner needs -- the bridge validates it fully and answers
`reset_done: false` if it cannot run it.
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
from skill_monitor.core.episode_outcome import (
    POLICIES, GoalStatusTracker, Outcome, decide_step, intervention_from_verdict,
)

RESET_TOPIC = "/g1/reset"
RESET_DONE_TOPIC = "/g1/reset_done"
FAULT_TOPIC = "/g1/fault_injected"
TRUTH_TOPIC = "/g1/ground_truth"
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
        self.truth: dict | None = None
        self.faults: list[dict] = []
        self.tick_seq: int | None = None
        self._accept_verdicts_after = float("inf")
        # The simulator's reset count, as its /g1 messages carry it. Anything stamped at
        # or below the count seen when this episode's reset was sent is still in flight
        # from an earlier episode -- a `fell: true` from the last one most of all.
        self._last_reset_seen: int | None = None
        self._reset_floor: int | None = None

        self.reset_pub = self.create_publisher(String, RESET_TOPIC, 10)
        self.goal_pub = self.create_publisher(PoseStamped, GOAL_TOPIC, 10)
        self.command_pub = self.create_publisher(String, api.COMMAND, 10)
        self.create_subscription(String, api.VERDICT, self._on_verdict, 10)
        self.create_subscription(Bool, RESET_DONE_TOPIC, self._on_reset_done, 10)
        self.create_subscription(String, api.TICK, self._on_tick, 10)
        self.create_subscription(String, FAULT_TOPIC, self._on_fault, 10)
        self.create_subscription(String, TRUTH_TOPIC, self._on_truth, 10)
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
        if not isinstance(verdict, dict):
            return
        self.verdict = verdict
        # Recorded under every policy, `off` included: whether the monitor saw the fault
        # is measured whether or not anything acted on it.
        if self.detected_seq is None and intervention_from_verdict(verdict):
            seq = verdict.get("seq")
            self.detected_seq = seq if isinstance(seq, int) and seq >= 0 else None

    def _on_reset_done(self, msg: Bool) -> None:
        self.reset_result = bool(msg.data)

    def _on_tick(self, msg: String) -> None:
        try:
            tick = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if api.validate_tick(tick) == []:
            self.tick_seq = tick["seq"]

    def _current(self, payload) -> bool:
        """Whether a /g1 message belongs to this episode; notes the reset count."""
        reset = payload.get("reset") if isinstance(payload, dict) else None
        if not isinstance(reset, int):
            return False
        if self._last_reset_seen is None or reset > self._last_reset_seen:
            self._last_reset_seen = reset
        return self._reset_floor is None or reset > self._reset_floor

    def _on_truth(self, msg: String) -> None:
        try:
            truth = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if self._current(truth):
            self.truth = truth

    def _on_fault(self, msg: String) -> None:
        """Stamp the scheduled fault this event reports with the tick it took effect on."""
        try:
            event = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if not self._current(event):
            return
        for fault in self.faults:
            if fault["injected_t"] is None and fault["type"] == event.get("type") \
                    and fault["onset_s"] == event.get("onset_s"):
                fault["injected_t"] = event.get("t")
                fault["injected_tick"] = self.tick_seq
                fault["params"] = dict(event.get("params") or fault["params"])
                return

    def _on_nav_status(self, msg) -> None:
        self.nav.observe((_goal_id(e), e.status) for e in msg.status_list)

    # ---- one episode ----

    def run_episode(self, scenario: dict, *, arm: str, episode_id: str,
                    policy: str = "detect", max_recoveries: int = 2) -> dict:
        """Reset to `scenario`, drive to its first goal, return a validated record."""
        if policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
        name = scenario.get("name", "")
        seed = scenario.get("seed", 0)
        timeout_s = float(scenario.get("duration_s", 120.0))
        self.verdict, self.detected_seq, self.reset_result = {}, None, None
        self.truth = None
        self._accept_verdicts_after = float("inf")
        self._reset_floor = self._last_reset_seen
        recoveries = 0
        started = time.monotonic()

        # Scheduled, not yet injected: `injected_*` are filled from the injector's own
        # events (`_on_fault`), never by this runner's guess and never from the monitor.
        self.faults = [episode_record.build_fault(type=f["type"], onset_s=f["onset_s"],
                                                  params=f.get("params"))
                       for f in scenario.get("faults", [])]

        def record(outcome: Outcome, elapsed: float) -> dict:
            return episode_record.build_record(
                episode_id=episode_id, arm=arm, policy=policy, seed=seed, scenario=name,
                scenario_params=scenario, faults=self.faults,
                terminal=outcome.terminal, success=outcome.success,
                cause=outcome.cause or "interrupted",
                elapsed_s=round(elapsed, 2), steps=self.verdict.get("step"),
                detected_tick=self.detected_seq, recoveries=recoveries,
                timing={"wall_s": round(time.monotonic() - started, 2)},
            )

        self.reset_pub.publish(String(data=json.dumps(scenario)))
        self._spin_until(lambda: self.reset_result is not None, self.reset_timeout_s)
        if self.reset_result is not True:
            cause = "reset_rejected" if self.reset_result is False else "reset_timeout"
            self.get_logger().error(f"{episode_id}: {cause}; episode not run")
            return record(Outcome(True, False, cause), 0.0)

        goal = scenario["goals"][0]
        self._attempt(goal)
        start = time.monotonic()
        outcome = Outcome(False)
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)
            truth = self.truth or {}
            decision = decide_step(
                policy=policy, nav_status=self.nav.status,
                intervention=intervention_from_verdict(self.verdict),
                fell=truth.get("fell") is True, dist_to_goal=truth.get("dist_to_goal"),
                timed_out=(time.monotonic() - start) > timeout_s,
                recoveries=recoveries, max_recoveries=max_recoveries)
            if decision.action == "recover":
                recoveries += 1
                self.get_logger().info(
                    f"{episode_id}: recovery {recoveries}/{max_recoveries} on "
                    f"{intervention_from_verdict(self.verdict)}")
                self._attempt(goal)
            elif decision.action == "end":
                outcome = decision.outcome
                break
        return record(outcome, time.monotonic() - start)

    def _attempt(self, goal_xy) -> None:
        """Start (or restart) driving to the goal, with the monitor on its first phase.

        The order matters: the goal-status window opens before the goal is sent, so the
        goal this one preempts -- which Nav2 reports `aborted` or `canceled` -- is
        already an earlier goal; and verdicts are dropped for the grace period, because
        the ones in flight still describe the attempt being abandoned.
        """
        self.verdict = {}
        self.command_pub.publish(String(data=json.dumps(api.build_command(command="arm"))))
        self._accept_verdicts_after = time.monotonic() + self.verdict_grace_s
        self.nav.begin()
        self.goal_pub.publish(self._goal(goal_xy))

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


def load_scenario_dir(path: str | Path) -> list[dict]:
    """Every `*.json` scenario in a directory, in name order (sim/generate_scenarios.py)."""
    files = sorted(Path(path).glob("*.json"))
    if not files:
        raise SystemExit(f"{path}: no scenario files (*.json)")
    return [load_scenario(f) for f in files]


def run(node: G1EpisodeDriver, scenarios, *, episodes: int = 1,
        seed_start: int | None = None, arm: str, policy: str = "detect",
        max_recoveries: int = 2, out: Path) -> list[dict]:
    """Each scenario `episodes` times. With `seed_start`, the repeats are relabelled with
    consecutive seeds; without it, each keeps its own -- a generated scenario's seed is
    what generated its world, so relabelling it would misreport where it came from."""
    if isinstance(scenarios, dict):
        scenarios = [scenarios]
    records = []
    for scenario in scenarios:
        for i in range(episodes):
            seed = scenario.get("seed", 0) if seed_start is None else seed_start + i
            episode = {**scenario, "seed": seed}
            episode_id = f"{arm}-{policy}-{scenario['name']}-s{seed}-{i:04d}"
            rec = node.run_episode(episode, arm=arm, episode_id=episode_id, policy=policy,
                                   max_recoveries=max_recoveries)
            episode_record.write_record(out, rec)
            node.get_logger().info(
                f"{episode_id}: {'success' if rec['success'] else 'failure'} "
                f"({rec['cause']}, {rec['elapsed_s']} s, {rec['recoveries']} recoveries)")
            records.append(rec)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run scenarios and record each episode.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", help="one scenario, e.g. sim/scenarios/clear.json")
    source.add_argument("--scenario-dir", help="every *.json in a directory, in name order")
    parser.add_argument("--episodes", type=int, default=1, help="repeats per scenario")
    parser.add_argument("--seed-start", type=int, default=None,
                        help="relabel repeats with consecutive seeds (default for "
                             "--scenario: 0; --scenario-dir keeps each file's seed)")
    parser.add_argument("--arm", default="full", help="label for the analysis")
    parser.add_argument("--policy", choices=POLICIES, default="detect",
                        help="what the monitor's interventions do (see module doc)")
    parser.add_argument("--max-recoveries", type=int, default=2)
    parser.add_argument("--out", default="episodes.jsonl")
    parser.add_argument("--reset-timeout", type=float, default=30.0)
    args, ros_args = parser.parse_known_args(argv)

    if args.scenario:
        scenarios = [load_scenario(args.scenario)]
        seed_start = 0 if args.seed_start is None else args.seed_start
    else:
        scenarios = load_scenario_dir(args.scenario_dir)
        seed_start = args.seed_start
    rclpy.init(args=ros_args)
    node = G1EpisodeDriver(reset_timeout_s=args.reset_timeout)
    try:
        run(node, scenarios, episodes=args.episodes, seed_start=seed_start, arm=args.arm,
            policy=args.policy, max_recoveries=args.max_recoveries, out=Path(args.out))
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
