"""Render what the monitor actually runs for a spec: one automaton per LTL formula, built by
`core.automata.LTLMonitor` exactly as at runtime (Spot: deterministic, complete,
state-based Büchi), and the phase machine from the spec's `execution_phases`.

    python tools/report/render_automata.py skill_monitor/specs/formulas_g1_carry.json \
        --out docs/figures/automata

Writes, per formula, `<name>.dot` / `<name>.svg` and `phases.dot` / `phases.svg` (the SVGs
need Graphviz's `dot` on PATH), and prints a Markdown transition table per automaton.
Needs Spot.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def formulas(spec: dict) -> list[tuple[str, str, str]]:
    """(name, formula, role) for every formula the monitor builds an automaton for."""
    out = [(f["name"], f["formula"], "ordered task") for f in spec.get("ltl_formulas", [])]
    out += [(f["name"], f["formula"], f"failure mode ({f.get('fault_category', '?')})")
            for f in spec.get("named_failure_modes", [])]
    return out


def automaton_dot(monitor) -> str:
    """Graphviz for one automaton: states labelled with their role, edges with guards."""
    import spot
    aut, bdict = monitor.aut, monitor.aut.get_dict()
    init = aut.get_init_state_number()
    lines = ["digraph automaton {", '  rankdir=LR; node [fontname="Helvetica" fontsize=11];',
             '  edge [fontname="Helvetica" fontsize=10];', '  start [shape=point];',
             f"  start -> s{init};"]
    for s in range(aut.num_states()):
        if aut.state_is_accepting(s):
            shape, extra = "doublecircle", ' style=filled fillcolor="#DCEBDD"'
        elif s in monitor._sink_states:
            shape, extra = "circle", ' style=filled fillcolor="#F6D5CF"'
        else:
            shape, extra = "circle", ""
        lines.append(f'  s{s} [label="{s}" shape={shape}{extra}];')
    for s in range(aut.num_states()):
        for e in aut.out(s):
            cond = spot.bdd_format_formula(bdict, e.cond).replace('"', '\\"')
            lines.append(f'  s{s} -> s{e.dst} [label="{cond}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def transition_table(monitor) -> str:
    import spot
    aut, bdict = monitor.aut, monitor.aut.get_dict()
    rows = ["| state | role | on | to |", "|---|---|---|---|"]
    for s in range(aut.num_states()):
        role = ("initial, " if s == aut.get_init_state_number() else "") + (
            "accepting" if aut.state_is_accepting(s)
            else "sink (violated)" if s in monitor._sink_states else "waiting")
        for k, e in enumerate(aut.out(s)):
            cond = spot.bdd_format_formula(bdict, e.cond).replace("|", "∨").replace("&", "∧")
            rows.append(f"| {s if k == 0 else ''} | {role if k == 0 else ''} | `{cond}` | {e.dst} |")
    return "\n".join(rows)


def phases_dot(spec: dict) -> str:
    """The phase machine: enter/exit conditions, time budgets, and how each phase faults."""
    phases = spec["execution_phases"]

    def esc(text):
        return str(text).replace('"', '\\"')

    lines = ["digraph phases {", '  rankdir=LR; node [fontname="Helvetica" fontsize=11];',
             '  edge [fontname="Helvetica" fontsize=10];',
             '  Idle [shape=box style=rounded];',
             '  Done [shape=box style="rounded,filled" fillcolor="#DCEBDD"];',
             '  Fault [label="FAULT\\n(intervention)" shape=box style="rounded,filled" '
             'fillcolor="#F6D5CF"];']
    for p in phases:
        budget = (p.get("timing_bounds") or {}).get("max_steps")
        label = [p["phase"], f"≤ {budget} s" if budget else ""]
        if (p.get("progress_condition") or "True") != "True":
            label.append(f"progress: {p['progress_condition']}")
        label.append(f"invariant: {p.get('invariant', 'True')}")
        lines.append(f'  {p["phase"]} [shape=box label="{esc(chr(10).join(x for x in label if x))}"];')
    lines.append(f'  Idle -> {phases[0]["phase"]} [label="{esc(phases[0]["enter_condition"])}"];')
    for a, b in zip(phases, phases[1:]):
        lines.append(f'  {a["phase"]} -> {b["phase"]} [label="{esc(a["exit_condition"])}"];')
    lines.append(f'  {phases[-1]["phase"]} -> Done [label="{esc(phases[-1]["exit_condition"])}"];')
    for p in phases:
        why = ["invariant broken", "time budget exceeded"]
        if (p.get("progress_condition") or "True") != "True":
            why.append("progress lost")
        lines.append(f'  {p["phase"]} -> Fault [style=dashed color="#B5503C" '
                     f'label="{esc(" / ".join(why))}" fontcolor="#B5503C"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _svg(dot_path: Path) -> None:
    if shutil.which("dot"):
        subprocess.run(["dot", "-Tsvg", str(dot_path), "-o", str(dot_path.with_suffix(".svg"))],
                       check=True)
    else:
        print(f"  (no Graphviz `dot` on PATH: wrote {dot_path.name} only)")


def main(argv=None) -> int:
    from skill_monitor.core.automata import LTLMonitor

    parser = argparse.ArgumentParser(description="Render a spec's automata and phase machine.")
    parser.add_argument("spec")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for name, formula, role in formulas(spec):
        monitor = LTLMonitor(formula, name)
        path = out / f"{name}.dot"
        path.write_text(automaton_dot(monitor), encoding="utf-8")
        _svg(path)
        print(f"### {name} ({role}): `{formula}`, {monitor.aut.num_states()} states\n")
        print(transition_table(monitor) + "\n")
    path = out / "phases.dot"
    path.write_text(phases_dot(spec), encoding="utf-8")
    _svg(path)
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
