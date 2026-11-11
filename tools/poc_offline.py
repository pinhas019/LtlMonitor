"""Offline proof of concept: per-frame CSV -> propositions -> phase ladder vs flat spec.

Iteration 0 of the paper plan. Pure Python: no ROS, no Spot. It answers one question
end to end -- on the same recorded frames, what does a phase ladder report that a flat
goal formula does not, and what does it cost in false alarms?

    python3 tools/poc_offline.py                 # synthetic pick-and-place episodes
    python3 tools/poc_offline.py --csv-dir DIR   # one CSV per episode, same columns

CSV columns: frame, hand_x, hand_z, gripper, label, onset
  hand_x   forward reach of the hand (m);  hand_z  hand height (m)
  gripper  0 open .. 1 closed
  label    success | failed | near_miss   (constant per file)
  onset    frame at which the failure began, or -1

The ladder here is a minimal mirror of `MonitorNode._update_phase_state`
(skill_monitor/backend/monitor_node.py): invariant, then deadline, then progress budget,
then exit. It is a stand-in until the real monitor is driven through a descriptor.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

# ----------------------------------------------------------------------------- task

OBJECT_X, TARGET_X, LIFT_Z, TABLE_Z = 0.40, 0.10, 0.25, 0.05
NEAR, MOVING_EPS = 0.03, 0.002          # metres, metres per frame


def propositions(prev: dict | None, row: dict) -> dict[str, bool]:
    """Ground the atomic propositions for one frame. `prev` is the previous row."""
    x, z, g = row["hand_x"], row["hand_z"], row["gripper"]
    speed = 0.0 if prev is None else math.hypot(x - prev["hand_x"], z - prev["hand_z"])
    grip_change = 0.0 if prev is None else abs(g - prev["gripper"])
    return {
        "at_object": abs(x - OBJECT_X) < NEAR and z < TABLE_Z + NEAR,
        "gripper_closed": g > 0.8,
        "gripper_open": g < 0.2,
        "lifted": z > LIFT_Z,
        "at_target": abs(x - TARGET_X) < NEAR,
        "lowered": z < TABLE_Z + NEAR,
        "active": speed > MOVING_EPS or grip_change > 0.01,
    }


# (name, progress AP, exit expression as a tuple of APs that must all hold)
PHASES = [
    ("reach", "active", ("at_object",)),
    ("grasp", "active", ("gripper_closed",)),
    ("lift", "active", ("lifted",)),
    ("transport", "active", ("at_target",)),
    ("place", "active", ("lowered", "gripper_open")),
]


# --------------------------------------------------------------------------- monitors

@dataclass
class Verdict:
    fault: str | None = None        # e.g. "phase:transport:progress"; None if no fault
    fault_frame: int | None = None
    completed: bool = False
    warnings: int = 0               # progress violations that later cleared
    phase_durations: dict = field(default_factory=dict)


def run_ladder(aps: list[dict], deadlines: dict[str, int], budget: int) -> Verdict:
    """Phase ladder: per-phase deadline and progress budget, checked in that order."""
    v = Verdict()
    idx, steps, violations = 0, 0, 0
    for frame, ap in enumerate(aps):
        name, progress_ap, exit_aps = PHASES[idx]
        if steps >= deadlines[name]:
            v.fault, v.fault_frame = f"phase:{name}:timeout", frame
            return v
        if not ap[progress_ap]:
            violations += 1
            if violations >= budget:
                v.fault, v.fault_frame = f"phase:{name}:progress", frame
                return v
        else:
            if violations:
                v.warnings += 1
            violations = 0
        if all(ap[a] for a in exit_aps):
            v.phase_durations[name] = steps + 1
            idx, steps, violations = idx + 1, 0, 0
            if idx == len(PHASES):
                v.completed = True
                return v
            continue
        steps += 1
    return v


def run_flat(aps: list[dict], global_deadline: int | None = None) -> Verdict:
    """Flat goal: F(e1 & F(e2 & ... )). Never refuted unless a global deadline is given."""
    v = Verdict()
    idx = 0
    for frame, ap in enumerate(aps):
        if global_deadline is not None and frame >= global_deadline:
            v.fault, v.fault_frame = "mission:timeout", frame
            return v
        if all(ap[a] for a in PHASES[idx][2]):
            idx += 1
            if idx == len(PHASES):
                v.completed = True
                return v
    return v


# ------------------------------------------------------------------------ calibration

def conformal_quantile(values: list[int], alpha: float) -> int:
    """Split-conformal upper bound: the ceil((n+1)(1-alpha))-th smallest value."""
    s = sorted(values)
    k = min(len(s), math.ceil((len(s) + 1) * (1 - alpha)))
    return s[k - 1]


def calibrate(nominal: list[list[dict]], alpha: float, budget: int) -> dict[str, int]:
    """Per-phase deadline from the durations seen in successful episodes."""
    loose = {name: 10**9 for name, _, _ in PHASES}
    durations: dict[str, list[int]] = {name: [] for name, _, _ in PHASES}
    for aps in nominal:
        v = run_ladder(aps, loose, budget=10**9)
        for name, d in v.phase_durations.items():
            durations[name].append(d)
    # alpha is split across phases so the episode-level false-alarm level is ~alpha
    per_phase = alpha / len(PHASES)
    return {name: conformal_quantile(d, per_phase) for name, d in durations.items()}


# ------------------------------------------------------------------------- synthetic

def _segment(rows, x0, z0, g0, x1, z1, g1, n):
    for i in range(1, n + 1):
        f = i / n
        rows.append({"hand_x": x0 + f * (x1 - x0), "hand_z": z0 + f * (z1 - z0),
                     "gripper": g0 + f * (g1 - g0)})


def synth_episode(rng: random.Random, label: str) -> tuple[list[dict], int]:
    """One pick-and-place episode. Returns (rows, onset frame or -1)."""
    n = lambda base: max(4, int(rng.gauss(base, base * 0.15)))  # noqa: E731
    rows = [{"hand_x": 0.0, "hand_z": 0.20, "gripper": 0.0}]
    onset = -1
    plan = [  # (x, z, gripper, nominal frames)
        (OBJECT_X, TABLE_Z, 0.0, 30), (OBJECT_X, TABLE_Z, 1.0, 10),
        (OBJECT_X, LIFT_Z + 0.05, 1.0, 15), (TARGET_X, LIFT_Z + 0.05, 1.0, 30),
        (TARGET_X, TABLE_Z, 1.0, 15), (TARGET_X, TABLE_Z, 0.0, 10),
    ]
    stall_at = rng.choice([0, 2, 3]) if label != "success" else None
    for i, (x, z, g, base) in enumerate(plan):
        last = rows[-1]
        frames = n(base)
        if i == stall_at:
            half = frames // 2
            _segment(rows, last["hand_x"], last["hand_z"], last["gripper"],
                     (last["hand_x"] + x) / 2, (last["hand_z"] + z) / 2, g, half)
            hold = rows[-1]
            if label == "failed":            # stuck for good
                onset = len(rows)
                rows.extend(dict(hold) for _ in range(200))
                break
            rows.extend(dict(hold) for _ in range(rng.randint(3, 6)))  # hesitation
            last, frames = rows[-1], frames - half
        _segment(rows, last["hand_x"], last["hand_z"], last["gripper"], x, z, g, frames)
    for r in rows:                            # sensor noise
        r["hand_x"] += rng.gauss(0, 0.0004)
        r["hand_z"] += rng.gauss(0, 0.0004)
    return rows, onset


def synth_dataset(seed: int, n_success=60, n_failed=30, n_near=30):
    rng = random.Random(seed)
    out = []
    for label, count in (("success", n_success), ("failed", n_failed), ("near_miss", n_near)):
        for _ in range(count):
            rows, onset = synth_episode(rng, label)
            out.append({"label": label, "onset": onset, "rows": rows})
    return out


def load_csv_dir(path: Path):
    out = []
    for f in sorted(path.glob("*.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            raw = list(csv.DictReader(fh))
        rows = [{k: float(r[k]) for k in ("hand_x", "hand_z", "gripper")} for r in raw]
        out.append({"label": raw[0]["label"], "onset": int(raw[0]["onset"]), "rows": rows})
    return out


# --------------------------------------------------------------------------- evaluate

def to_aps(rows: list[dict]) -> list[dict]:
    return [propositions(rows[i - 1] if i else None, r) for i, r in enumerate(rows)]


def evaluate(episodes, alpha: float = 0.05, budget: int = 8, seed: int = 0) -> dict:
    rng = random.Random(seed)
    for e in episodes:
        e["aps"] = to_aps(e["rows"])
    success = [e for e in episodes if e["label"] == "success"]
    rng.shuffle(success)
    half = len(success) // 2
    calib, held_out = success[:half], success[half:]
    deadlines = calibrate([e["aps"] for e in calib], alpha, budget)
    mission_deadline = sum(deadlines.values())

    arms = {
        "B1 flat": lambda a: run_flat(a),
        "B2 flat + mission deadline": lambda a: run_flat(a, mission_deadline),
        "C  phase ladder": lambda a: run_ladder(a, deadlines, budget),
    }
    failed = [e for e in episodes if e["label"] == "failed"]
    near = [e for e in episodes if e["label"] == "near_miss"]
    results = {}
    for arm, run in arms.items():
        false_alarms = sum(run(e["aps"]).fault is not None for e in held_out)
        near_alarms = sum(run(e["aps"]).fault is not None for e in near)
        delays, names = [], {}
        for e in failed:
            v = run(e["aps"])
            if v.fault is not None:
                delays.append(v.fault_frame - e["onset"])
                names[v.fault] = names.get(v.fault, 0) + 1
        delays.sort()
        results[arm] = {
            "false_alarm_rate": false_alarms / max(1, len(held_out)),
            "near_miss_alarm_rate": near_alarms / max(1, len(near)),
            "detection_rate": len(delays) / max(1, len(failed)),
            "median_delay": delays[len(delays) // 2] if delays else None,
            "worst_delay": delays[-1] if delays else None,
            "faults": names,
        }
    return {"deadlines": deadlines, "budget": budget, "alpha": alpha,
            "n": {"calibration": len(calib), "held_out": len(held_out),
                  "failed": len(failed), "near_miss": len(near)},
            "arms": results}


def report(res: dict) -> str:
    n = res["n"]
    lines = [
        f"calibrated on {n['calibration']} successes (alpha={res['alpha']}), "
        f"tested on {n['held_out']} held-out successes, {n['failed']} failed, "
        f"{n['near_miss']} near-miss",
        f"deadlines (frames): {res['deadlines']}   progress budget: {res['budget']}",
        "",
        f"{'arm':28} {'false-alarm':>11} {'near-miss':>10} {'detected':>9} "
        f"{'median delay':>13} {'worst':>6}",
    ]
    for arm, r in res["arms"].items():
        md = "-" if r["median_delay"] is None else str(r["median_delay"])
        wd = "-" if r["worst_delay"] is None else str(r["worst_delay"])
        lines.append(f"{arm:28} {r['false_alarm_rate']:>11.2f} "
                     f"{r['near_miss_alarm_rate']:>10.2f} {r['detection_rate']:>9.2f} "
                     f"{md:>13} {wd:>6}")
    lines.append("")
    for arm, r in res["arms"].items():
        if r["faults"]:
            lines.append(f"{arm.strip()} fault names: {r['faults']}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--csv-dir", type=Path, help="directory of per-episode CSV files")
    p.add_argument("--alpha", type=float, default=0.05, help="target false-alarm level")
    p.add_argument("--budget", type=int, default=8, help="progress budget in frames")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    episodes = load_csv_dir(args.csv_dir) if args.csv_dir else synth_dataset(args.seed)
    print(report(evaluate(episodes, args.alpha, args.budget, args.seed)))


if __name__ == "__main__":
    main()
