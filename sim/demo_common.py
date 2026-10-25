"""What the demos say each tick: one wording for the terminal (demo_e1b.py), the MuJoCo
window (demo_e1b.py) and the browser (stack.py)."""

from __future__ import annotations

#: The monitor's intervention names in words.
WHY = {
    "phase:Carry:invariant": "Carry phase broken: the object must be held while carrying",
    "TIMEOUT": "phase took longer than its time budget",
    "completion_unverified": "executor claims success; the monitor does not confirm it",
    "terminal_failure": "no progress for 10 s: the task has failed",
    "fell_over": "the robot fell",
    "collision_imminent": "an obstacle is dangerously close",
}

#: The arm with no monitor acting: only the executor's own checks are shown for it.
NO_MONITOR = ("closed_loop",)

HEADER = f"{'t':>4}  {'monitor phase':<14} {'held?':<6} {'monitor says':<60} truth (sim)"


class TickView:
    """Turns one tick of an episode into what a demo shows. Keeps the little state the
    wording needs: which faults were already announced, the last alarm."""

    def __init__(self, task: dict, spec: str):
        self.task, self.spec = task, spec
        self._fired = 0
        self._sim_faults: set[str] = set()
        self._rechecks = 0
        self.alarmed = False
        self.alarm = None              # "22 s: Carry phase broken: ..."

    def fault_events(self, ex, sim) -> list[str]:
        """Faults that took effect since the last tick, as lines to show."""
        out = [f"fault injected: {ev['type']} at {ev['t']:.1f} s"
               for ev in ex.fired[self._fired:]]
        self._fired = len(ex.fired)
        for f in self.task["scenario"].get("faults", []):
            if f["type"] not in self._sim_faults and sim.time >= f["onset_s"]:
                self._sim_faults.add(f["type"])
                out.append(f"fault injected: {f['type']} at {f['onset_s']:.1f} s")
        return out

    def tick(self, seq: int, verdict: dict | None, name: str | None, ex, sim,
             held: bool | None) -> dict:
        """The fields for this tick (`line` is the terminal line)."""
        if self.spec in NO_MONITOR:                    # no monitor in this deployment:
            verdict, held, name = None, None, None     # show only the executor's checks
            for c in ex.rechecks[self._rechecks:]:
                name = f"executor check: {c['reason']}"
            self._rechecks = len(ex.rechecks)
        self.alarmed = self.alarmed or bool(name)
        phase = (verdict or {}).get("phase") or ("(stopped)" if self.alarmed else "(idle)")
        if self.spec in NO_MONITOR:
            phase = "(no monitor)"
        words = WHY.get(name, name) if name else None
        if words:
            self.alarm = f"{seq} s: {words}"
        says = f"!! {words}" if words else (verdict or {}).get("verdict", "")
        held_s = ("yes" if held else "no") if held is not None else "?"
        truth = ("fell" if sim.fell else "holding" if sim.holding else "not holding") + \
            f", executor {ex.status}"
        return {"t": seq, "phase": phase, "held": held_s,
                "verdict": (verdict or {}).get("verdict", "-"), "says": says,
                "alarm": self.alarm, "new_alarm": words, "truth": truth,
                "line": f"{seq:>3}s  {phase:<14} {held_s:<6} {says:<60} {truth}"}


def result_line(rec: dict, spec: str) -> str:
    said = ("executor reported " + rec["timing"]["executor"] if spec in NO_MONITOR
            else f"monitor's own conclusion: {rec['timing']['monitor_outcome']}")
    return (f"Ground truth: {'DELIVERED' if rec['success'] else 'FAILED'} ({rec['cause']}) at "
            f"{rec['elapsed_s']:.0f} s; {said}.")
