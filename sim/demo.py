"""Two-minute demo, no ROS or Docker: the G1 walks in MuJoCo, a fault is injected, and the
monitor's sensor folding (the shipped `mujoco` descriptor, at 1 Hz) reports what it sees.

    pip install mujoco "numpy<2" pyyaml
    sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree
    python sim/demo.py                 # stall: the legs stop, the command does not
    python sim/demo.py --fault push    # a 300 N shove: the robot falls

Prints one line per monitor tick: time, distance to goal, closing speed, no_progress,
upright -- and when the injected fault took effect.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

from g1sim import G1Sim, from_dict                       # noqa: E402
from skill_monitor.core import adapter_spec              # noqa: E402


def odom_msg(sim):
    x, y, z, _ = sim.reported_pose()
    qw, qx, qy, qz = sim.base_quat()
    v, w = sim.linear_velocity_body(), sim.angular_velocity_body()
    return NS(pose=NS(pose=NS(position=NS(x=x, y=y, z=z),
                              orientation=NS(x=qx, y=qy, z=qz, w=qw))),
              twist=NS(twist=NS(linear=NS(x=v[0], y=v[1], z=v[2]),
                                angular=NS(x=w[0], y=w[1], z=w[2]))))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fault", default="stall",
                        choices=["none", "stall", "push", "slip", "weaken", "odom_drift"])
    parser.add_argument("--onset", type=float, default=5.0, help="seconds")
    parser.add_argument("--seconds", type=float, default=25.0)
    args = parser.parse_args(argv)

    goal = (8.0, 0.0)
    faults = [] if args.fault == "none" else [{"type": args.fault, "onset_s": args.onset}]
    sim = G1Sim()
    sim.reset(from_dict({"name": "demo", "map_size": [24, 24], "goals": [list(goal)],
                         "start": {"x": -3.0, "y": 0.0, "yaw": 0.0}, "faults": faults}))
    monitor = adapter_spec.SensorState(adapter_spec.load("mujoco"))
    monitor.update("goal", NS(pose=NS(position=NS(x=goal[0], y=goal[1], z=0.0))))

    print(f"G1 walking to {goal} at 0.5 m/s; fault: {args.fault} at t={args.onset:.0f} s\n")
    print("  t (s)   dist (m)   closing (m/s)   no_progress   upright")
    sim.set_command(0.5, 0.0, 0.0)
    steps_per_tick = round(1.0 / sim.config.control_dt)
    for step in range(1, round(args.seconds / sim.config.control_dt) + 1):
        sim.step(control_steps=1)
        for event in sim.pop_fault_events():
            print(f"  -- fault '{event['type']}' took effect at t={event['t']:.2f} s --")
        if step % 5 == 0:                                   # odometry at 10 Hz
            monitor.update("odom", odom_msg(sim))
        if step % steps_per_tick == 0:                      # the monitor's 1 Hz tick
            v = monitor.tick()
            flag = "TRUE " if v["no_progress"] else "false"
            up = "yes" if v["upright_flag"] > 0.5 else "NO (fallen)"
            print(f"  {sim.time:5.0f}   {v['dist_to_goal']:8.2f}   {v['closing_speed']:13.2f}"
                  f"   {flag:>11}   {up}")
    print(f"\nground truth: fell={sim.fell}, true distance to goal "
          f"{sim.dist_to_goal():.2f} m (commanded speed stayed {sim.command[0]:.1f} m/s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
