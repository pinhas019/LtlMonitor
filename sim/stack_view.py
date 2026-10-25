"""What the monitor is doing, in a form the demo page can draw.

Built only from what the monitor and the evaluator publish over ROS 2: the latched
manifest (the spec, its phases and every automaton the monitor built), each tick's
verdict (the phase, and which state each automaton is in) and the evaluator's
observation (the proposition values the monitor stepped on). Nothing here re-evaluates
the spec; it reads what the monitor said and puts words to it.

No ROS import, so sim/tests/test_stack_view.py runs it anywhere.
"""

from __future__ import annotations

import re

#: What each state of the generated task automaton means. The state numbers are the ones
#: Spot gives the ordered formula in skill_monitor/specs/formulas_g1_carry.json; the
#: table in docs/pitch.md is the same. Any other automaton is described from its own
#: graph ("stays while ...").
MEANINGS = {
    "fetch_and_deliver_in_order": {
        0: "not started",
        1: "started, walking to the object",
        2: "at the object",
        3: "holding it, carrying",
        4: "at the drop-off",
        5: "delivered",
    },
    "eventual_completion": {
        0: "not delivered yet",
        1: "delivered",
    },
}
SAFETY = {"fell_over": "the robot stays upright", "collision_imminent": "no obstacle too close"}


def _budget(phase: dict, tick_hz: float = 1.0):
    steps = (phase.get("timing_bounds") or {}).get("max_steps")
    return None if steps is None else round(steps / tick_hz)


def _aps_in(expr: str, aps) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr or "")
    return [w for w in dict.fromkeys(words) if w in aps]


def _culprits(expr: str, aps, values: dict) -> list[str]:
    """The propositions whose value makes a conjunction like `a and not b` false: `a`
    false, or `b` true. All of them when none can be singled out."""
    names = [n for n in _aps_in(expr, aps) if n in values]
    bad = [n for n in names
           if values[n] is (re.search(rf"(not|!)\s*\(?\s*{n}\b", expr) is not None)]
    return bad or names


def _graph_view(graph: dict, state, prev, status) -> dict:
    meanings = MEANINGS.get(graph["name"], {})
    loops = {e["from"]: e["label"] for e in graph["edges"] if e["from"] == e["to"]}
    return {
        "name": graph["name"],
        "formula": graph.get("formula"),
        "initial": graph.get("initial", 0),
        "states": [
            {
                "id": s["id"],
                "accepting": bool(s.get("accepting")),
                "sink": bool(s.get("sink")),
                "meaning": meanings.get(s["id"]),
                "stay": loops.get(s["id"]),
            }
            for s in graph["states"]
        ],
        "edges": [e for e in graph["edges"] if e["from"] != e["to"]],
        "current": state,
        "prev": prev,
        "status": status,
    }


def automata_view(manifest: dict | None, verdict: dict | None, observation: dict | None,
                  prev_states: dict | None = None, stopped: bool = False) -> dict | None:
    """The page's "what the monitor is doing" card for one tick.

    `verdict` is the last verdict the monitor published (it stops publishing after a
    terminal, so the caller keeps the last one); `prev_states` maps automaton name to
    the state it was in on the previous verdict, so the page can light the edge taken.
    """
    if not manifest:
        return None
    verdict = verdict or {}
    aps = manifest.get("atomic_propositions") or {}
    graphs = {g["name"]: g for g in manifest.get("automata") or ()}
    prev_states = prev_states or {}

    phases = [{"name": "Idle", "budget": None, "invariant": None, "exit": "task_started",
               "progress": None, "description": "Waiting for the task to be commanded."}]
    for p in manifest.get("execution_phases") or ():
        phases.append({
            "name": p["phase"],
            "budget": _budget(p),
            "invariant": p.get("invariant"),
            "exit": p.get("exit_condition"),
            "progress": p.get("progress_condition"),
            "description": p.get("description"),
        })
    phases.append({"name": "Done", "budget": None, "invariant": None, "exit": None,
                   "progress": None,
                   "description": (manifest.get("terminal_success") or {}).get("description")})

    terminal = verdict.get("terminal")
    phase = verdict.get("phase")
    # A passive monitor reaches Done with every automaton satisfied and no terminal.
    success = terminal == "SUCCESS" or phase == "Done" or verdict.get("verdict") == "SATISFIED"
    if success:
        phase = "Done"
    elif not phase:
        phase = "Idle"

    automata = []
    for row in verdict.get("formulas") or ():
        if row["name"] in graphs:
            automata.append(dict(_graph_view(graphs[row["name"]], row.get("state"),
                                             prev_states.get(row["name"]), row.get("status")),
                                 kind="task"))
    if not automata:                              # before the first verdict: draw the graphs
        for name, g in graphs.items():
            if name not in SAFETY:
                automata.append(dict(_graph_view(g, g.get("initial", 0), None, None),
                                     kind="task"))
    safety, fault = [], None
    for row in verdict.get("failure_modes") or ():
        if row.get("state") is not None and row["name"] in graphs:
            safety.append({"name": row["name"], "status": row.get("status"),
                           "state": row.get("state"), "means": SAFETY.get(row["name"], ""),
                           "formula": graphs[row["name"]].get("formula")})
        elif row.get("status") == "VIOLATED":
            fault = {"name": row["name"], "category": row.get("fault_category")}
    for row in safety:
        if row["status"] == "VIOLATED" and fault is None:
            fault = {"name": row["name"], "category": "SAFETY"}

    values = (observation or {}).get("ap_values") or {}
    props = [{"name": n, "value": values.get(n), "meaning": str(text).split(". ", 1)[-1]}
             for n, text in aps.items()]
    guards = (verdict.get("phase_guards") or {}).get("guards") or []

    view = {
        "spec": manifest.get("skill_name"),
        "phases": phases,
        "phase": phase,
        "terminal": terminal,
        "success": success and terminal != "FAILURE",
        "fault": fault,
        "t": verdict.get("t"),
        "seconds_left": (verdict.get("risk") or {}).get("seconds_to_timeout"),
        "guards": guards,
        "automata": automata,
        "safety": safety,
        "props": props,
        "stopped": stopped,
    }
    view["now"] = now_sentence(view, values, aps)
    return view


def now_sentence(view: dict, values: dict, aps) -> str:
    """One plain sentence for the top of the card."""
    def show(names):  # noqa: E306
        return ", ".join(f"{n} = {str(values.get(n)).lower()}" for n in names
                         if n in values)
    task = next(iter(view["automata"]), None)
    state_words = ""
    if task and task["current"] is not None:
        st = next((s for s in task["states"] if s["id"] == task["current"]), None)
        if st:
            what = st["meaning"] or (f"stays while {st['stay']}" if st["stay"] else "")
            state_words = f" Task automaton in state {st['id']}" + (f": {what}." if what
                                                                     else ".")
    if view["terminal"] == "FAILURE":
        fault = view["fault"] or {}
        name = fault.get("name") or ""
        m = re.match(r"phase:([^:]+):(\w+)", name)
        at = f" at {view['t']:.0f} s" if view.get("t") is not None else ""
        if m:
            ph, kind = m.groups()
            p = next((p for p in view["phases"] if p["name"] == ph), {})
            expr = p.get("invariant") if kind == "invariant" else p.get("progress")
            if kind == "invariant" and expr:
                why = (f"the {ph} phase's invariant `{expr}` became false "
                       f"({show(_culprits(expr, aps, values))})")
            elif kind in ("timeout", "timing", "budget"):
                why = f"the {ph} phase ran over its {p.get('budget')} s budget"
            elif expr:
                why = f"the {ph} phase stopped making progress (`{expr}` failed)"
            else:
                why = f"the {ph} phase failed ({kind})"
        else:
            why = f"{name} was violated"
        if m and task and task["current"] is not None and not any(
                s["accepting"] and s["id"] == task["current"] for s in task["states"]):
            st = next((s for s in task["states"] if s["id"] == task["current"]), {})
            state_words = (f" The LTL task automaton alone has not noticed: it is still in "
                           f"state {task['current']}"
                           + (f" ({st['meaning']})" if st.get("meaning") else "")
                           + ", because \"eventually\" can still come true.")
        return f"FAULT{at}: {why}. The monitor stops and reports failure.{state_words}"
    if view["success"]:
        return "Done: the object rests at the drop-off and the robot let go. Success." + state_words
    phase = next((p for p in view["phases"] if p["name"] == view["phase"]), None)
    if not phase or phase["name"] == "Idle":
        return "Idle: waiting for the task to start." + state_words
    parts = [f"Phase {phase['name']}"]
    if phase["budget"] is not None:
        left = view.get("seconds_left")
        parts[0] += f" (≤{phase['budget']} s" + (f", {left:.0f} s left)" if left is not None
                                                 else ")")
    words = parts[0] + ":"
    if phase["invariant"]:
        words += f" must keep `{phase['invariant']}`"
    if phase["exit"]:
        words += f"; moves on when `{phase['exit']}`"
    return words + "." + state_words
