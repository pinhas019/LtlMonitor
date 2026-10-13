"""Live demo of E1b: the G1 fetches an object and delivers it, a fault is injected, and the
real monitor (evaluator + LTL monitor + phase machine, as in the experiments) reports what
it sees, tick by tick, in a 3-D MuJoCo window.

    python sim/demo_e1b.py                          # drop, full spec: caught ~1 s after it
    python sim/demo_e1b.py --spec flat              # same drop: noticed only at the end
    python sim/demo_e1b.py --fault grasp_fail --policy recover   # caught, re-planned, delivered
    python sim/demo_e1b.py --no-view                # text only (no display needed)

macOS: run with `mjpython` instead of `python` (MuJoCo's viewer needs it there).
Needs Spot (conda-forge) for the monitor, MuJoCo, and the Unitree assets
(sim/fetch_assets.sh; set G1SIM_ASSETS).

The monitor sees only messages: odometry, the scan, the commanded goal and task, and the
object as a noisy detector reports it. "held" is its inference. The printout's last column
is the simulator's ground truth, which the monitor never sees.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE / "e1", HERE / "e1" / "carry", HERE, HERE.parent, HERE.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

WHY = {
    "phase:Carry:invariant": "Carry phase broken: the object must be held while carrying",
    "TIMEOUT": "phase took longer than its time budget",
    "completion_unverified": "executor claims success; the monitor does not confirm it",
    "terminal_failure": "no progress for 10 s: the task has failed",
    "fell_over": "the robot fell",
    "collision_imminent": "an obstacle is dangerously close",
}


def main(argv=None) -> int:
    from task import FAMILIES, generate
    import run_e1b

    parser = argparse.ArgumentParser(description="Live E1b demo: fetch and deliver.")
    parser.add_argument("--fault", default="drop", choices=FAMILIES,
                        help="scenario family (clear = no fault)")
    parser.add_argument("--spec", default="full", choices=list(run_e1b.ARMS),
                        help="full = the generated spec; flat = phases merged; "
                             "ltl_only = no phase machine; closed_loop = hand-coded checks")
    parser.add_argument("--policy", default="off", choices=("off", "detect", "recover"),
                        help="what an alarm does: nothing, stop, or re-plan")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-view", action="store_true", help="text only")
    parser.add_argument("--speed", type=float, default=2.0,
                        help="playback speed in the window (simulated s per wall s)")
    args = parser.parse_args(argv)

    try:
        import spot  # noqa: F401
    except ImportError:
        print("The monitor needs Spot: conda install -c conda-forge spot  "
              "(or micromamba; see docs/pitch.md, 'Try it yourself').")
        return 2
    import run_e1
    run_e1._init_worker()               # the real Spot, then the stand-in ROS layer
    sim = run_e1._W["sim"]

    task = generate(args.fault, args.seed)
    if args.spec == "closed_loop":
        args.policy = "off"
    item = {"task": task, "arm": args.spec, "policy": args.policy}
    print(f"\n{task['name']}: {args.spec} spec, policy {args.policy}. Object at "
          f"({task['object'][0]:.1f}, {task['object'][1]:.1f}), drop-off at "
          f"({task['dropoff'][0]:.1f}, {task['dropoff'][1]:.1f}).")
    faults = task["scenario"].get("faults", []) + task.get("task_faults", [])
    print("Injected: " + (", ".join(f["type"] for f in faults) or "nothing") + "\n")
    print(f"{'t':>4}  {'monitor phase':<14} {'held?':<6} {'monitor says':<60} truth (sim)")

    view = {"viewer": None, "wall0": None, "status": ("", "")}

    def on_step(s):
        if args.no_view:
            return
        if view["viewer"] is None:
            import mujoco.viewer
            v = mujoco.viewer.launch_passive(s.model, s.data, show_left_ui=False,
                                             show_right_ui=False)
            v.opt.geomgroup[3] = 1      # the object and the drop-off pad
            v.cam.distance, v.cam.elevation = 6.0, -35.0
            view["viewer"], view["wall0"] = v, time.monotonic()
        v = view["viewer"]
        if not v.is_running():
            raise KeyboardInterrupt
        x, y, z, _ = s.base_pose()
        v.cam.lookat[:] = (x, y, 0.5)
        if view.pop("dirty", False):
            try:
                import mujoco
                left, right = view["status"]
                v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150,
                             mujoco.mjtGridPos.mjGRID_TOPLEFT, left, right))
            except Exception:                               # noqa: BLE001  older MuJoCo
                pass
        v.sync()
        ahead = s.time / args.speed - (time.monotonic() - view["wall0"])
        if ahead > 0:
            time.sleep(ahead)

    fired_seen = {"n": 0, "sim": set(), "alarm": False}

    def on_tick(seq, verdict, name, ex, s, link):
        for ev in ex.fired[fired_seen["n"]:]:
            print(f"      ** fault injected: {ev['type']} at {ev['t']:.1f} s")
        fired_seen["n"] = len(ex.fired)
        for f in task["scenario"].get("faults", []):
            if f["type"] not in fired_seen["sim"] and s.time >= f["onset_s"]:
                fired_seen["sim"].add(f["type"])
                print(f"      ** fault injected: {f['type']} at {f['onset_s']:.1f} s")
        sensors = getattr(getattr(link, "monitor", None), "sensors", {}) or {}
        held = sensors.get("holding")
        fired_seen["alarm"] = fired_seen["alarm"] or bool(name)
        phase = (verdict or {}).get("phase") or ("(stopped)" if fired_seen["alarm"] else "(idle)")
        says = f"!! {WHY.get(name, name)}" if name else (verdict or {}).get("verdict", "")
        truth = ("fell" if s.fell else "holding" if s.holding else "not holding") + \
            f", {ex.status}"
        print(f"{seq:>3}s  {phase:<14} {('yes' if held else 'no') if held is not None else '?':<6}"
              f" {says:<60} {truth}")
        if name:
            view["alarm"] = f"{seq} s: {WHY.get(name, name)}"
        view["status"] = (
            "spec\nscenario\nt\nmonitor phase\nheld (inferred)\nverdict\nlast alarm",
            f"{args.spec}\n{task['name']}\n{seq} s\n{phase}\n"
            f"{('yes' if held else 'no') if held is not None else '?'}\n"
            f"{(verdict or {}).get('verdict', '-')}\n{view.get('alarm', 'none')}")
        view["dirty"] = True

    made = []

    def make():
        made.append(run_e1b.InProcess(args.spec, sim))
        return made[0]
    try:
        rec = run_e1b.play_episode(item, sim, make, on_step=on_step, on_tick=on_tick)
    except KeyboardInterrupt:
        print("\nwindow closed")
        return 0
    finally:
        for link in made:
            link.end()
    print(f"\nGround truth: {'DELIVERED' if rec['success'] else 'FAILED'} ({rec['cause']}) at "
          f"{rec['elapsed_s']:.0f} s. Monitor's own conclusion: "
          f"{rec['timing']['monitor_outcome']}")
    if view["viewer"] is not None:
        print("Close the window to exit.")
        while view["viewer"].is_running():
            time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
