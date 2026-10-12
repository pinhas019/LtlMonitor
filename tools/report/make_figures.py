"""Figures for the progress report, from the real simulator and the real monitor folding.

    pip install mujoco "numpy<2" pyyaml matplotlib
    sim/fetch_assets.sh /tmp/unitree
    sudo apt-get install -y libosmesa6        # offscreen rendering, for the frames only
    MUJOCO_GL=osmesa G1SIM_ASSETS=/tmp/unitree PYTHONPATH=.:sim \
        python tools/report/make_figures.py docs/report/figures

Writes, into OUT:
  fig_faults.*   pelvis height and distance walked, one episode per fault type
  fig_stall.*    commanded vs measured speed through a stall, and the monitor's
                 closing_speed / no_progress from the shipped `mujoco` descriptor,
                 folded at 1 Hz through SensorState exactly as the evaluator does
  fig_scan.*     the lidar before and after a block_route fault
  frame_*.png    offscreen renders of a push fall and of the spawned wall
  facts.json     every number the captions quote, from this run

Each figure is one simulated episode -- an illustration of the mechanism, not a result.
"""
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mujoco
import numpy as np

from g1sim import G1Sim, from_dict
from skill_monitor.core import adapter_spec

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SURFACE = "#fcfcfb"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "lines.linewidth": 2.0, "axes.titleweight": "bold", "axes.titlesize": 12,
    "axes.titlecolor": INK,
})
facts = {}
sim = G1Sim()
DT = sim.config.control_dt


def scenario(faults=(), obstacles=(), start=(-3.0, 0.0), goal=(6.0, 0.0), size=24.0):
    return from_dict({"name": "deck", "map_size": [size, size],
                      "start": {"x": start[0], "y": start[1], "yaw": 0.0},
                      "goals": [list(goal)], "obstacles": list(obstacles),
                      "faults": list(faults), "duration_s": 120})


def walk(faults, seconds, vx=0.5, every=None):
    sim.reset(scenario(faults))
    x0 = sim.base_pose()[0]
    rows = []
    sim.set_command(vx, 0.0, 0.0)
    for _ in range(int(round(seconds / DT))):
        sim.step(control_steps=1)
        x, y, z, _ = sim.base_pose()
        rows.append((sim.time, x - x0, z, sim.command[0], sim.linear_velocity_body()[0]))
        if every:
            every(sim)
    return np.array(rows), sim.fell, sim.pop_fault_events()


# ----------------------------------------------------------------- Fig A
ONSET = 3.0
cases = [
    ("No fault", []),
    ("Push (300 N, sideways)", [{"type": "push", "onset_s": ONSET}]),
    ("Slip (friction μ 0.1)", [{"type": "slip", "onset_s": ONSET}]),
    ("Weaken (torque × 0.5)", [{"type": "weaken", "onset_s": ONSET}]),
    ("Stall (legs stop, command stays)", [{"type": "stall", "onset_s": ONSET}]),
    ("Odometry drift (0.1 m/s)", [{"type": "odom_drift", "onset_s": ONSET,
                                   "params": {"rate_m_s": 0.1, "angle": 1.5708}}]),
]
fig, axes = plt.subplots(2, 3, figsize=(13, 6.4), sharex=True, sharey=True)
facts["faults"] = {}
for ax, (title, faults) in zip(axes.flat, cases):
    rows, fell, events = walk(faults, 9.0)
    dx = float(rows[-1, 1])
    outcome = "fell" if fell else ("stood still" if dx < 1.5 else "kept walking")
    facts["faults"][title] = {"fell": bool(fell), "dx_m": round(dx, 2),
                              "fired_at": [e["t"] for e in events]}
    ax.plot(rows[:, 0], rows[:, 2], color=BLUE, label="pelvis height (m)")
    ax.plot(rows[:, 0], rows[:, 1], color=ORANGE, label="distance walked (m)")
    if faults:
        ax.axvline(events[0]["t"], color=MUTED, linestyle=(0, (3, 3)), linewidth=1.2)
        ax.text(events[0]["t"] + 0.15, 4.25, "fault", color=INK2, fontsize=9)
    ax.set_title(title, loc="left")
    ax.text(0.98, 0.04, outcome, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=11, fontweight="bold", color=INK)
    ax.set_ylim(-0.1, 4.6)
for ax in axes[1]:
    ax.set_xlabel("simulated time (s)")
handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="upper right", ncol=2, frameon=False, fontsize=10)
fig.suptitle("Fault library on the walking G1 (MuJoCo, Unitree policy) — one episode each, "
             "commanded 0.5 m/s", x=0.01, ha="left", fontsize=13, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT / "fig_faults.svg")
fig.savefig(OUT / "fig_faults.png", dpi=160)
plt.close(fig)

# ----------------------------------------------------------------- Fig B
spec = adapter_spec.load("mujoco")
state = adapter_spec.SensorState(spec)
STALL = 6.0
GOAL = (8.0, 0.0)
mon = []


def to_odom(s):
    x, y, z, _ = s.reported_pose()
    qw, qx, qy, qz = s.base_quat()
    v = s.linear_velocity_body()
    w = s.angular_velocity_body()
    return NS(pose=NS(pose=NS(position=NS(x=x, y=y, z=z), orientation=NS(x=qx, y=qy, z=qz, w=qw))),
              twist=NS(twist=NS(linear=NS(x=v[0], y=v[1], z=v[2]), angular=NS(x=w[0], y=w[1], z=w[2]))))


tick_every = int(round(1.0 / DT))
counter = {"n": 0}


def every(s):
    counter["n"] += 1
    if counter["n"] % 5 == 0:                     # odometry at 10 Hz
        state.update("odom", to_odom(s))
    if counter["n"] == 1:
        state.update("goal", NS(pose=NS(position=NS(x=GOAL[0], y=GOAL[1], z=0.0))))
    if counter["n"] % tick_every == 0:            # the monitor's 1 Hz clock
        v = state.tick()
        mon.append((s.time, v["dist_to_goal"], v["closing_speed"], v["no_progress"]))


sim.reset(scenario([{"type": "stall", "onset_s": STALL}], start=(-3.0, 0.0), goal=GOAL))
state.reset()
counter["n"] = 0
rows = []
sim.set_command(0.5, 0.0, 0.0)
for _ in range(int(round(30.0 / DT))):
    sim.step(control_steps=1)
    rows.append((sim.time, sim.command[0], sim.linear_velocity_body()[0]))
    every(sim)
rows = np.array(rows)
mon = np.array(mon, dtype=float)
first = next(t for t, _, _, n in mon if n)
facts["stall"] = {"stall_at_s": STALL, "no_progress_first_true_s": round(float(first), 2),
                  "latency_s": round(float(first) - STALL, 2),
                  "commanded_mps_after_stall": float(rows[-1, 1]),
                  "measured_mps_last5s": round(float(np.mean(np.abs(rows[-250:, 2]))), 3)}

fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1]})
a1.plot(rows[:, 0], rows[:, 1], color=BLUE, label="commanded by the planner")
k = 25
smooth = np.convolve(rows[:, 2], np.ones(k) / k, mode="same")
a1.plot(rows[:, 0], smooth, color=ORANGE, label="measured by odometry")
a1.set_ylabel("forward speed (m/s)")
a1.set_ylim(-0.15, 0.75)
a1.legend(loc="upper right", frameon=False, ncol=2)
a1.set_title("The planner keeps commanding — the robot has stopped", loc="left")
a2.step(mon[:, 0], mon[:, 2], where="post", color=AQUA, label="closing_speed (m/s), 1 Hz")
a2.fill_between(mon[:, 0], -0.2, 0.75, where=mon[:, 3] > 0.5, step="post",
                color="#e34948", alpha=0.12, linewidth=0, label="no_progress = true")
a2.axhline(0.05, color=MUTED, linestyle=(0, (3, 3)), linewidth=1.2)
a2.text(0.3, 0.075, "ε = 0.05 m/s", color=INK2, fontsize=9)
a2.set_ylim(-0.2, 0.75)
a2.set_ylabel("monitor's view")
a2.set_xlabel("simulated time (s)")
a2.legend(loc="upper right", frameon=False, ncol=2)
a2.set_title(f"Progress from odometry: no_progress fires {first - STALL:.0f} s after the stall "
             "(10 s debounce)", loc="left")
for ax in (a1, a2):
    ax.axvline(STALL, color=MUTED, linestyle=(0, (3, 3)), linewidth=1.2)
a1.text(STALL + 0.2, 0.62, "stall injected", color=INK2, fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig_stall.svg")
fig.savefig(OUT / "fig_stall.png", dpi=160)
plt.close(fig)

# ----------------------------------------------------------------- Fig C
wall = {"type": "block_route", "onset_s": 1.0, "params": {"pos": [0.0, 0.0]}}
sim.reset(scenario([wall], start=(-2.0, 0.0), goal=(3.0, 0.0), size=10.0))
sim.step(0.5)
before = sim.ranges(); pose_b = sim.base_pose()
sim.step(1.0)
after = sim.ranges(); pose_a = sim.base_pose()
ang = -math.pi + 2 * math.pi * np.arange(len(before)) / len(before)


def pts(r, pose):
    x, y, _, yaw = pose
    ok = np.isfinite(r)
    return x + r[ok] * np.cos(yaw + ang[ok]), y + r[ok] * np.sin(yaw + ang[ok])


fig, axs = plt.subplots(1, 2, figsize=(11, 5.2), sharey=True)
for ax, r, pose, title in ((axs[0], before, pose_b, "Before the fault"),
                           (axs[1], after, pose_a, "1 s after block_route")):
    px, py = pts(r, pose)
    ax.scatter(px, py, s=6, color=BLUE, linewidths=0, label="lidar returns")
    ax.plot(pose[0], pose[1], marker="o", markersize=9, color=ORANGE, linestyle="none",
            label="robot")
    ax.plot(3.0, 0.0, marker="*", markersize=14, color=AQUA, linestyle="none", label="goal")
    ax.set_aspect("equal"); ax.set_xlim(-5.2, 5.2); ax.set_ylim(-5.2, 5.2)
    ax.set_title(title, loc="left")
    ax.set_xlabel("x (m)")
axs[0].set_ylabel("y (m)")
handles, labels = axs[1].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, fontsize=10)
facts["block_route_min_range_m"] = {"before": round(float(np.nanmin(before)), 2),
                                    "after": round(float(np.nanmin(after)), 2)}
fig.tight_layout(rect=(0, 0.07, 1, 1))
fig.savefig(OUT / "fig_scan.svg")
fig.savefig(OUT / "fig_scan.png", dpi=160)
plt.close(fig)

# ----------------------------------------------------------------- Fig D: frames
sim.model.vis.global_.offwidth = 960
sim.model.vis.global_.offheight = 540
sim.model.vis.headlight.ambient[:] = (0.45, 0.45, 0.45)
sim.model.vis.headlight.diffuse[:] = (0.7, 0.7, 0.7)
renderer = mujoco.Renderer(sim.model, 540, 960)
cam = mujoco.MjvCamera()
cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
cam.trackbodyid = sim.model.body("pelvis").id
cam.distance, cam.elevation, cam.azimuth = 2.6, -14.0, 135.0


def frame(name):
    renderer.update_scene(sim.data, camera=cam)
    plt.imsave(OUT / f"{name}.png", renderer.render())


sim.reset(scenario([{"type": "push", "onset_s": 2.0, "params": {"force_n": 350.0}}]))
sim.set_command(0.5, 0.0, 0.0)
shots = {1.9: "frame_push_1_walking", 2.3: "frame_push_2_pushed", 4.0: "frame_push_3_down"}
for _ in range(int(round(4.05 / DT))):
    sim.step(control_steps=1)
    for t, name in list(shots.items()):
        if sim.time >= t:
            frame(name); shots.pop(t)
facts["push_frames_fell"] = bool(sim.fell)

sim.reset(scenario([dict(wall, onset_s=0.5)], start=(-2.0, 0.0), goal=(3.0, 0.0), size=10.0))
sim.set_command(0.4, 0.0, 0.0)
sim.step(3.0)
cam.azimuth, cam.distance, cam.elevation = 160.0, 4.5, -18.0
frame("frame_block_route")

(OUT / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
print(json.dumps(facts, indent=2))
