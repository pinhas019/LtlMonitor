"""E1b, headless: the fetch-and-deliver skill (sim/e1/carry) under the real evaluator and
monitor, exactly as run_e1.py runs navigation.

    python sim/e1/run_e1b.py --seeds 0-19 --out e1b.jsonl

Differences from E1:
  * the skill is task.CarryExecutor (walk to the object, grasp, carry, place) on top of the
    navigator, open-loop as a plain behaviour tree is;
  * the evaluator uses sim/e1/carry/mujoco_carry.json: the navigation sources plus the
    task (/task) and perception of the object (/object/pose: task.perceive_object, the
    object's position with noise and missed detections). Nothing comes from the gripper
    or the executor; the evaluator infers "held" from where the object is;
  * success is ground truth: the executor finished AND the object rests within 0.5 m of the
    drop-off AND it is not held AND the robot never fell. An executor that reports success
    with the object elsewhere is a `false_arrival`;
  * `recover` re-perceives and re-plans the task (CarryExecutor.replan) and re-arms the
    monitor;
  * the completion check: when the executor reports the task done, the monitor must
    confirm it within COMPLETION_GRACE ticks -- its specification SATISFIED, or its
    terminal-success condition reached -- or the runner
    counts an intervention `completion_unverified`. The same for every arm -- it is the one
    check a flat spec can make, and leaving it out would deny the control it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "carry"))

import run_e1                                                   # noqa: E402
from run_e1 import ROOT, Bus, _odom, deliver                    # noqa: E402

DESCRIPTOR = HERE / "carry" / "mujoco_carry.json"
ARMS = {
    "full": "formulas_g1_carry.json",
    "flat": "formulas_g1_carry_flat.json",
    "flat_strict": "formulas_g1_carry_flat_strict.json",
}
POLICIES = ("off", "detect", "recover")
COMPLETION_GRACE = 2            # ticks for the monitor to see a reported completion


def run_episode(item: dict) -> dict:
    from g1sim import from_dict
    from g1sim.navigator import Navigator, scan_points
    from skill_monitor.backend import monitor_node
    from skill_monitor.backend.adapters.declarative import DeclarativeAdapter
    from skill_monitor.backend.evaluator_node import GenericClientNode
    from skill_monitor.core import api, episode_record
    from skill_monitor.core.automata import MultiMonitor
    from skill_monitor.core.episode_outcome import decide_step, intervention_from_verdict
    from task import PERCEPTION_MISS, PERCEPTION_NOISE_M, CarryExecutor, perceive_object

    ros_stub = run_e1._W["ros_stub"]
    sim = run_e1._W["sim"]
    task, arm, policy = item["task"], item["arm"], item["policy"]
    max_recoveries = item.get("max_recoveries", 2)
    noise_m = item.get("noise_m", PERCEPTION_NOISE_M)
    miss = item.get("miss", PERCEPTION_MISS)
    perception_rng = random.Random(f"perception:{task['name']}:{arm}:{policy}")
    scenario = from_dict(task["scenario"])
    wall0 = time.monotonic()

    sim.reset(scenario)
    nav = Navigator(scenario)
    spec = monitor_node.load_formulas_from_file(ROOT / "skill_monitor" / "specs" / ARMS[arm])

    with contextlib.redirect_stdout(io.StringIO()):
        multi = MultiMonitor(spec.all_formulas, names=spec.all_names,
                             failure_modes=spec.build_failure_mode_infos())
        monitor = monitor_node.LtlMonitorNode(spec, multi, run_e1._Args())
        evaluator = GenericClientNode(
            DeclarativeAdapter(descriptor=str(DESCRIPTOR), clock=lambda: sim.time),
            api_url="http://127.0.0.1:0/unused", model="none")
        bus = Bus([evaluator, monitor], ros_stub.Message)
        bus.flush(evaluator)

        ex = CarryExecutor(sim, nav, task)
        task_msg = ros_stub.Message(data=json.dumps(
            {"dropoff_x": task["dropoff"][0], "dropoff_y": task["dropoff"][1]}))
        deliver(evaluator, "/task", task_msg)

        def command(name):
            payload = json.dumps(api.build_command(command=name))
            for node in (evaluator, monitor):
                deliver(node, api.COMMAND, ros_stub.Message(data=payload))
            bus.flush(evaluator)

        faults = [episode_record.build_fault(type=f["type"], onset_s=f["onset_s"],
                                             params=f.get("params"))
                  for f in task["scenario"].get("faults", [])]
        faults += [episode_record.build_fault(
            type=f["type"], onset_s=f.get("onset_s", 0.0),
            params={k: v for k, v in f.items() if k not in ("type", "onset_s")})
            for f in task.get("task_faults", [])]

        def stamp(kind, t, seq, params=None):
            for f in faults:
                if f["injected_t"] is None and f["type"] == kind:
                    f["injected_t"], f["injected_tick"] = round(t, 3), seq
                    if params:
                        f["params"] = dict(params)
                    return

        seq, verdict, detected, recoveries = 0, {}, None, 0
        done_seq = None
        intervention_log, fired_seen = [], 0
        steps_per_tick = round(1.0 / sim.config.control_dt)
        timeout = float(task.get("duration_s", 150.0))
        step, decision = 0, None
        while True:
            step += 1
            if step % run_e1.CONTROL_PER_SENSOR == 0:
                ex.update(sim.time)
                for event in ex.fired[fired_seen:]:
                    stamp(event["type"], event["t"], seq)
                fired_seen = len(ex.fired)
                if ex.goal_changed:
                    gx, gy = ex.target
                    deliver(evaluator, "/goal_pose", NS(pose=NS(position=NS(x=gx, y=gy, z=0.0))))
                    ex.goal_changed = False
                deliver(evaluator, "/odom", _odom(sim))
                seen = perceive_object(sim, perception_rng, noise_m=noise_m, miss=miss)
                if seen is not None:
                    ox, oy, oz = seen
                    deliver(evaluator, "/object/pose", NS(point=NS(x=ox, y=oy, z=oz)))
                x, y, _, yaw = sim.reported_pose()
                pts = None
                if sim.scan_available():
                    ranges = sim.ranges()
                    deliver(evaluator, "/scan", NS(ranges=list(ranges)))
                    pts = scan_points(ranges, (x, y, yaw))
                vx, wz = nav.update(sim.time, (x, y, yaw), pts)
                if ex.command():
                    vx, wz = 0.0, 0.0
                sim.set_command(vx, 0.0, wz)
            sim.step(control_steps=1)
            for event in sim.pop_fault_events():
                stamp(event["type"], event["t"], seq, event["params"])
            if step % steps_per_tick:
                continue

            seq += 1
            tick = json.dumps(api.build_tick(seq=seq, t=round(sim.time, 3), tick_hz=1.0,
                                             t0=1.0, mode="replay"))
            for node in (evaluator, monitor):
                deliver(node, api.TICK, ros_stub.Message(data=tick))
            bus.flush(evaluator)
            new = monitor.publishers[api.VERDICT].sent
            if new:
                last = json.loads(new[-1])
                if last.get("seq") == seq:
                    verdict = last
            name = intervention_from_verdict(verdict) if verdict.get("seq") == seq else None
            nav_status = {"succeeded": "succeeded", "aborted": "aborted"}.get(ex.status, "")
            if ex.status == "succeeded":
                done_seq = seq if done_seq is None else done_seq
                confirmed = verdict.get("terminal") == "SUCCESS" or \
                    verdict.get("verdict") == "SATISFIED"
                if not confirmed:
                    if seq - done_seq < COMPLETION_GRACE:
                        nav_status = ""                 # give the monitor its grace
                    elif not name:
                        name = "completion_unverified"
            else:
                done_seq = None
            if name:
                intervention_log.append((seq, name))
                if detected is None:
                    detected = seq

            dx, dy = task["dropoff"]
            ox, oy, _ = sim.object_position()
            delivered = math.hypot(ox - dx, oy - dy) if not sim.holding else math.inf
            decision = decide_step(
                policy=policy, nav_status=nav_status, intervention=name,
                fell=sim.fell, dist_to_goal=delivered,
                timed_out=sim.time >= timeout, recoveries=recoveries,
                max_recoveries=max_recoveries)
            if decision.action == "recover":
                recoveries += 1
                verdict = {}
                command("arm")
                deliver(evaluator, "/task", task_msg)
                ex.replan(sim.time)
            elif decision.action == "end":
                break

        ox, oy, _ = sim.object_position()
        record = episode_record.build_record(
            episode_id=f"{arm}-{policy}-{task['name']}",
            arm=arm, policy=policy, seed=task["seed"], scenario=task["name"],
            scenario_params=task, faults=faults, terminal=True,
            success=decision.outcome.success, cause=decision.outcome.cause,
            elapsed_s=round(sim.time, 2), steps=verdict.get("step"),
            detected_tick=detected, recoveries=recoveries,
            timing={"wall_s": round(time.monotonic() - wall0, 2), "ticks": seq,
                    "interventions": intervention_log[:20], "executor": ex.status,
                    "executor_state": ex.state, "holding": bool(sim.holding),
                    "object_to_dropoff_m": round(math.hypot(ox - task["dropoff"][0],
                                                            oy - task["dropoff"][1]), 3),
                    "fell": bool(sim.fell)})
        evaluator.destroy_node()
        monitor.destroy_node()
    problems = episode_record.validate_record(record)
    if problems:
        raise ValueError(problems)
    return record


def main(argv=None) -> int:
    from task import FAMILIES, generate
    from g1sim.generator import parse_seeds

    parser = argparse.ArgumentParser(description="Run E1b (fetch and deliver) headless.")
    parser.add_argument("--families", nargs="+", default=list(FAMILIES), choices=FAMILIES)
    parser.add_argument("--seeds", default="0-19")
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    parser.add_argument("--policies", nargs="+", default=list(POLICIES), choices=POLICIES)
    parser.add_argument("--workers", type=int, default=max(1, mp.cpu_count()))
    parser.add_argument("--perfect-perception", action="store_true",
                        help="no perception noise or missed detections (parity checks)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    perception = {"noise_m": 0.0, "miss": 0.0} if args.perfect_perception else {}

    out = Path(args.out)
    done = set()
    if out.exists():
        done = {json.loads(line)["episode_id"]
                for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    items = []
    for family in args.families:
        for seed in parse_seeds(args.seeds):
            task = generate(family, seed)
            for arm in args.arms:
                for policy in args.policies:
                    if f"{arm}-{policy}-{task['name']}" not in done:
                        items.append({"task": task, "arm": arm, "policy": policy,
                                      **perception})
    print(f"{len(items)} episodes to run ({len(done)} already in {out})", flush=True)
    t0 = time.monotonic()
    with mp.get_context("fork").Pool(args.workers, initializer=run_e1._init_worker,
                                     maxtasksperchild=20) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for i, rec in enumerate(pool.imap_unordered(run_episode, items), 1):
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(items):
                rate = (time.monotonic() - t0) / i
                print(f"  {i}/{len(items)}  {rate:.1f} s/episode  "
                      f"eta {rate * (len(items) - i) / 60:.0f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
