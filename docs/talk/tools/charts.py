"""The talk's two simple charts. Values from docs/e1b_ros/results.md (summarize_e1.py)."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "figures")
BLUE, GREY, DARK = "#1F5FAE", "#B8BEC7", "#3A3F47"
plt.rcParams.update({"font.size": 15, "font.family": "DejaVu Sans",
                     "axes.spines.top": False, "axes.spines.right": False})

# Seconds from the fault to the alarm (median, 20 runs each), carry_drop / carry_grasp_fail.
fig, ax = plt.subplots(figsize=(7.2, 3.6))
rows = [("Dropped box", 1, 14), ("Failed grasp", 4, 19)]
y = [1.1, 0]
for yy, (name, staged, flat) in zip(y, rows):
    ax.barh(yy + 0.2, staged, 0.36, color=BLUE)
    ax.barh(yy - 0.2, flat, 0.36, color=GREY)
    ax.text(staged + 0.3, yy + 0.2, f"{staged} s", va="center", color=BLUE, fontweight="bold")
    ax.text(flat + 0.3, yy - 0.2, f"{flat} s", va="center", color=DARK)
ax.set_yticks(y, [r[0] for r in rows])
ax.set_xlabel("seconds until the monitor raises the alarm")
ax.set_xlim(0, 24)
from matplotlib.patches import Patch  # noqa: E402
ax.legend(handles=[Patch(color=BLUE, label="with stages"), Patch(color=GREY, label="without stages")],
          loc="upper right", frameon=False)
fig.tight_layout()
fig.savefig(OUT / "chart_latency.png", dpi=200)

# Delivered within 1.5x the normal time (160 runs each, all fault types).
fig, ax = plt.subplots(figsize=(7.2, 3.9))
rows = [("No monitor", 34, GREY), ("Monitor,\nno stages", 36, GREY),
        ("Monitor,\nLTL only", 36, GREY), ("Monitor,\nwith stages", 64, BLUE),
        ("Hand-written\nchecks", 81, DARK)]
for i, (name, v, c) in enumerate(rows):
    ax.bar(i, v, 0.62, color=c)
    ax.text(i, v + 2, f"{v}%", ha="center", fontweight="bold", color=c if c != GREY else DARK)
ax.set_xticks(range(len(rows)), [r[0] for r in rows], fontsize=12.5)
ax.set_ylim(0, 95)
ax.set_yticks([])
ax.spines["left"].set_visible(False)
ax.set_title("delivered on time (deadline = 1.5 × normal time)", fontsize=14, color=DARK)
fig.tight_layout()
fig.savefig(OUT / "chart_deadline.png", dpi=200)
