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

from demo_common import HEADER, WHY, TickView, result_line  # noqa: E402,F401


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
    import ros_stub
    if ros_stub.real_ros_present():
        # With ROS 2 installed the in-process stand-in cannot be used; the same run goes
        # over DDS, the evaluator and the monitor as their own processes.
        if not args.no_view:
            print("ROS 2 is installed here, so this runs over ROS 2 in the terminal; for "
                  "the live view use `python sim/stack.py` (a web page).")
        import stack
        return stack.main(["--text", "--fault", args.fault, "--spec", args.spec,
                           "--policy", args.policy, "--seed", str(args.seed)])
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
    print(HEADER)

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

    tv = TickView(task, args.spec)

    def on_tick(seq, verdict, name, ex, s, link):
        for line in tv.fault_events(ex, s):
            print(f"      ** {line}")
        sensors = getattr(getattr(link, "monitor", None), "sensors", {}) or {}
        f = tv.tick(seq, verdict, name, ex, s, sensors.get("holding"))
        print(f["line"])
        view["status"] = (
            "spec\nscenario\nt\nmonitor phase\nheld (inferred)\nverdict\nlast alarm",
            f"{args.spec}\n{task['name']}\n{seq} s\n{f['phase']}\n{f['held']}\n"
            f"{f['verdict']}\n{f['alarm'] or 'none'}")
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
    print("\n" + result_line(rec, args.spec))
    if view["viewer"] is not None:
        print("Close the window to exit.")
        while view["viewer"].is_running():
            time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
