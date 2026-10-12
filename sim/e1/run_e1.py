"""E1, headless: every episode runs the real evaluator and the real monitor (Spot automata,
phase machine, intervention grading) in-process against the MuJoCo G1, with no ROS daemon,
no Docker and no wall clock.

    python sim/e1/run_e1.py --families clear stall push --seeds 0-19 \
        --arms full flat flat_strict --policies off detect recover --out e1.jsonl

What is real and what stands in:
  real       G1Sim (MuJoCo, Unitree policy, fault library); GenericClientNode with the
             shipped `mujoco` descriptor; LtlMonitorNode with MultiMonitor (Spot); the
             episode decision (core/episode_outcome.decide_step) and the record format.
  stand-in   ROS transport: tests/ros_stub.py nodes, with a bus that delivers each
             published message to every node subscribed to that topic -- the job DDS
             does. Nav2: g1sim/navigator.py, configured from sim/nav2_params.yaml and
             identical for every arm.
  clock      simulated time: the tick is 1 Hz of simulated time, odometry and the scan
             10 Hz, control 50 Hz.

One episode = one scenario x one arm (spec) x one policy, written as one
core/episode_record line. Outcomes come from the simulator (a latched fall, the true
distance to the goal), never from the verdict.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "sim", ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

ARMS = {
    "full": "formulas_g1_sim.json",
    "flat": "formulas_g1_sim_flat.json",
    "flat_strict": "formulas_g1_sim_flat_strict.json",
}
POLICIES = ("off", "detect", "recover")
TICK_HZ = 1.0
CONTROL_PER_SENSOR = 5            # 50 Hz control, 10 Hz odometry and scan

_W = {}                            # per-worker state


def _init_worker():
    import spot  # noqa: F401  -- the real one, before the stub would install a blank
    import ros_stub
    ros_stub.install()
    from g1sim import G1Sim
    _W["sim"] = G1Sim()
    _W["ros_stub"] = ros_stub


class _Args:
    changes_only = True
    stop_on_violation = False
    passive = True                 # a fault sends the monitor idle; the episode goes on
    formulas_file = None
    output_dir = None


class Bus:
    """Delivers what each node published to every other node subscribed to the topic."""

    def __init__(self, nodes, message):
        self.nodes, self.message = nodes, message
        self.read = {}

    def flush(self, evaluator):
        for _ in range(20):
            evaluator.query_queue.join()
            moved = False
            for src in self.nodes:
                for topic, pub in src.publishers.items():
                    start = self.read.get((id(src), topic), 0)
                    new = pub.sent[start:]
                    if not new:
                        continue
                    self.read[(id(src), topic)] = len(pub.sent)
                    for dst in self.nodes:
                        if dst is src:
                            continue
                        for callback in dst.subscriptions.get(topic, ()):
                            for text in new:
                                callback(self.message(data=text))
                                moved = True
            if not moved:
                return


def deliver(node, topic, msg):
    for callback in node.subscriptions.get(topic, ()):
        callback(msg)


def _odom(sim):
    x, y, z, _ = sim.reported_pose()
    qw, qx, qy, qz = sim.base_quat()
    v, w = sim.linear_velocity_body(), sim.angular_velocity_body()
    return NS(pose=NS(pose=NS(position=NS(x=x, y=y, z=z),
                              orientation=NS(x=qx, y=qy, z=qz, w=qw))),
              twist=NS(twist=NS(linear=NS(x=v[0], y=v[1], z=v[2]),
                                angular=NS(x=w[0], y=w[1], z=w[2]))))


def run_episode(task: dict) -> dict:
    import math
    from g1sim import from_dict
    from g1sim.navigator import Navigator, scan_points
    from skill_monitor import spec_path
    from skill_monitor.backend import monitor_node
    from skill_monitor.backend.adapters.declarative import DeclarativeAdapter
    from skill_monitor.backend.evaluator_node import GenericClientNode
    from skill_monitor.core import api, episode_record
    from skill_monitor.core.automata import MultiMonitor
    from skill_monitor.core.episode_outcome import decide_step, intervention_from_verdict

    ros_stub = _W["ros_stub"]
    sim = _W["sim"]
    raw, arm, policy = task["scenario"], task["arm"], task["policy"]
    max_recoveries = task.get("max_recoveries", 2)
    scenario = from_dict(raw)
    wall0 = time.monotonic()

    sim.reset(scenario)
    nav = Navigator(scenario)
    goal = scenario.goals[0]
    spec = monitor_node.load_formulas_from_file(
        ROOT / "skill_monitor" / "specs" / ARMS[arm])

    with contextlib.redirect_stdout(io.StringIO()):
        multi = MultiMonitor(spec.all_formulas, names=spec.all_names,
                             failure_modes=spec.build_failure_mode_infos())
        monitor = monitor_node.LtlMonitorNode(spec, multi, _Args())
        evaluator = GenericClientNode(
            DeclarativeAdapter(descriptor="mujoco", clock=lambda: sim.time),
            api_url="http://127.0.0.1:0/unused", model="none")
        bus = Bus([evaluator, monitor], ros_stub.Message)
        bus.flush(evaluator)

        def send_goal():
            msg = NS(pose=NS(position=NS(x=goal[0], y=goal[1], z=0.0)))
            deliver(evaluator, "/goal_pose", msg)
            nav.set_goal(goal[0], goal[1], sim.time) if nav.goal is None \
                else nav.restart(sim.time)

        def command(name):
            payload = json.dumps(api.build_command(command=name))
            for node in (evaluator, monitor):
                deliver(node, api.COMMAND, ros_stub.Message(data=payload))
            bus.flush(evaluator)

        faults = [episode_record.build_fault(type=f["type"], onset_s=f["onset_s"],
                                             params=f.get("params"))
                  for f in raw.get("faults", [])]
        seq, verdict, detected, recoveries = 0, {}, None, 0
        intervention_log = []
        send_goal()
        steps_per_tick = round(1.0 / (sim.config.control_dt * TICK_HZ))
        timeout = float(raw.get("duration_s", 60.0))
        step, decision = 0, None
        while True:
            step += 1
            if step % CONTROL_PER_SENSOR == 0:
                deliver(evaluator, "/odom", _odom(sim))
                x, y, _, yaw = sim.reported_pose()
                pts = None
                if sim.scan_available():
                    ranges = sim.ranges()
                    deliver(evaluator, "/scan", NS(ranges=list(ranges)))
                    pts = scan_points(ranges, (x, y, yaw))
                vx, wz = nav.update(sim.time, (x, y, yaw), pts)
                sim.set_command(vx, 0.0, wz)
            sim.step(control_steps=1)
            for event in sim.pop_fault_events():
                for f in faults:
                    if f["injected_t"] is None and f["type"] == event["type"] \
                            and f["onset_s"] == event["onset_s"]:
                        f["injected_t"], f["injected_tick"] = event["t"], seq
                        f["params"] = dict(event["params"])
                        break
            if step % steps_per_tick:
                continue

            seq += 1
            tick = json.dumps(api.build_tick(seq=seq, t=round(sim.time, 3), tick_hz=TICK_HZ,
                                             t0=1.0, mode="replay"))
            for node in (evaluator, monitor):
                deliver(node, api.TICK, ros_stub.Message(data=tick))
            bus.flush(evaluator)
            new = monitor.publishers[api.VERDICT].sent
            if new:
                last = json.loads(new[-1])
                if last.get("seq") == seq:
                    verdict = last
            name = intervention_from_verdict(verdict)
            if name and verdict.get("seq") == seq:
                intervention_log.append((seq, name))
                if detected is None:
                    detected = seq
            decision = decide_step(
                policy=policy, nav_status=nav.status if nav.status != "executing" else "",
                intervention=name if verdict.get("seq") == seq else None,
                fell=sim.fell, dist_to_goal=sim.dist_to_goal(),
                timed_out=sim.time >= timeout, recoveries=recoveries,
                max_recoveries=max_recoveries)
            if decision.action == "recover":
                recoveries += 1
                verdict = {}
                command("arm")
                send_goal()
            elif decision.action == "end":
                break

        record = episode_record.build_record(
            episode_id=f"{arm}-{policy}-{scenario.name}",
            arm=arm, policy=policy, seed=scenario.seed, scenario=scenario.name,
            scenario_params=raw, faults=faults, terminal=True,
            success=decision.outcome.success, cause=decision.outcome.cause,
            elapsed_s=round(sim.time, 2), steps=verdict.get("step"),
            detected_tick=detected, recoveries=recoveries,
            timing={"wall_s": round(time.monotonic() - wall0, 2), "ticks": seq,
                    "interventions": intervention_log[:20], "nav_status": nav.status,
                    "true_dist_m": round(sim.dist_to_goal(), 3),
                    "fell": bool(sim.fell)})
        evaluator.destroy_node()
        monitor.destroy_node()
    problems = episode_record.validate_record(record)
    if problems:
        raise ValueError(problems)
    return record


def main(argv=None) -> int:
    from g1sim.generator import FAMILIES, generate, parse_seeds

    parser = argparse.ArgumentParser(description="Run E1 headless.")
    parser.add_argument("--families", nargs="+", default=list(FAMILIES), choices=FAMILIES)
    parser.add_argument("--seeds", default="0-19")
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    parser.add_argument("--policies", nargs="+", default=list(POLICIES), choices=POLICIES)
    parser.add_argument("--workers", type=int, default=max(1, mp.cpu_count()))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    done = set()
    if out.exists():
        done = {json.loads(line)["episode_id"] for line in out.read_text().splitlines()
                if line.strip()}
    tasks = []
    for family in args.families:
        for seed in parse_seeds(args.seeds):
            raw = generate(family, seed).to_dict()
            for arm in args.arms:
                for policy in args.policies:
                    if f"{arm}-{policy}-{raw['name']}" not in done:
                        tasks.append({"scenario": raw, "arm": arm, "policy": policy})
    print(f"{len(tasks)} episodes to run ({len(done)} already in {out})", flush=True)
    t0 = time.monotonic()
    with mp.get_context("fork").Pool(args.workers, initializer=_init_worker,
                                     maxtasksperchild=20) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for i, rec in enumerate(pool.imap_unordered(run_episode, tasks), 1):
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(tasks):
                rate = (time.monotonic() - t0) / i
                print(f"  {i}/{len(tasks)}  {rate:.1f} s/episode  "
                      f"eta {rate * (len(tasks) - i) / 60:.0f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
