"""The flattened control for E1: the same skill with its progress structure removed.

    python -m skill_monitor.core.spec_ablation formulas_g1_sim.json --out formulas_g1_sim_flat.json

E1 asks whether progress states earn their keep. The control must therefore differ from
the full spec in the structure and nothing else -- same atomic propositions, same failure
modes, same terminals -- so that any difference in detection or recovery is the
structure's. `flatten` keeps every proposition and safety formula and removes the two
places order lives:

- **phases -> one.** Its enter condition is the first phase's; its invariant is the
  conjunction of every phase's invariant, graded at the most severe of their categories;
  its progress condition is `True` (there is no "next" to make progress towards); it exits
  on the terminal-success condition; its one time budget is the sum of the phases'.
- **ordered LTL chains -> eventual completion.** `F(a && F(b && F(c)))` says *in this
  order*; the control says only `F(success)`.

`keep_terminal_failure` decides what happens to `terminal_failure`. A stall reaches the
monitor through it on the first stalled tick, not through the phase machine -- so if the
generated spec puts `no_progress` there, a flattened spec with it kept still catches
stalls. That is a finding about *where* the structure matters, not a flaw in the control,
and both readings are worth running: `True` (the default) is the fair control,
`False` removes the last piece of skill-level knowledge about failing.

Pure: no ROS, no Spot. The result is checked by the same gate the monitor applies at load
(`spec_contract.validate_structure`, `manifest.fault_category_problems`).
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from skill_monitor.core import api, manifest, spec_contract

FLAT_PHASE = "Execution"

_SEVERITY = {category: rank for rank, category in enumerate(api.FAULT_CATEGORIES)}
_PY_TO_LTL = {"and": "&&", "or": "||", "not": "!", "True": "true", "False": "false"}
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def to_ltl(condition: str) -> str:
    """A Python-syntax phase/terminal condition as an LTL state formula."""
    return _WORD.sub(lambda m: _PY_TO_LTL.get(m.group(0), m.group(0)), condition).strip()


def _conjunction(conditions) -> str:
    parts, seen = [], set()
    for condition in conditions:
        condition = (condition or "").strip()
        if condition and condition != "True" and condition not in seen:
            seen.add(condition)
            parts.append(condition)
    if not parts:
        return "True"
    return parts[0] if len(parts) == 1 else " and ".join(f"({p})" for p in parts)


def _most_severe(categories) -> str:
    known = [c for c in categories if c in _SEVERITY]
    return min(known, key=_SEVERITY.__getitem__) if known else "NONE"


def flatten(spec: dict, *, keep_terminal_failure: bool = True) -> dict:
    """The flattened control of `spec`. The input is not modified."""
    phases = spec.get("execution_phases") or []
    if not phases:
        raise ValueError("spec has no execution_phases to flatten")
    out = copy.deepcopy(spec)
    first, last = phases[0], phases[-1]
    success = ((spec.get("terminal_success") or {}).get("condition")
               or last.get("exit_condition") or "False")

    invariants = [p.get("invariant") for p in phases]
    with_invariant = [p for p in phases if (p.get("invariant") or "True").strip() != "True"]
    phase = {
        "phase": FLAT_PHASE,
        "description": "Flattened control: every phase merged into one, so the monitor "
                       "keeps the skill's propositions and safety conditions but not "
                       "its order.",
        "enter_condition": first.get("enter_condition", "True"),
        "precondition": first.get("precondition", "True"),
        "precondition_fault_category": first.get("precondition_fault_category", "NONE"),
        "invariant": _conjunction(invariants),
        "invariant_fault_category": _most_severe(
            p.get("invariant_fault_category") for p in with_invariant),
        "progress_condition": "True",
        "exit_condition": success,
        "progress_violation_limit": max(
            int(p.get("progress_violation_limit", 1)) for p in phases),
    }
    budgets = [(p.get("timing_bounds") or {}).get("max_steps") for p in phases]
    phase["timing_bounds"] = ({"max_steps": sum(budgets)}
                              if all(isinstance(b, int) for b in budgets) else {})
    out["execution_phases"] = [phase]

    out["ltl_formulas"] = [{"name": "eventual_completion",
                            "formula": f"F({to_ltl(success)})"}]
    if not keep_terminal_failure:
        out.pop("terminal_failure", None)
    out["description"] = (f"[flattened control of {spec.get('skill_name', 'the skill')}"
                          f"{'' if keep_terminal_failure else ', no terminal failure'}] "
                          + (spec.get("description") or ""))
    return out


def problems(spec: dict) -> list[str]:
    """What the monitor would refuse or misgrade at load, schema aside."""
    return spec_contract.validate_structure(spec) + manifest.fault_category_problems(spec)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write the flattened control of a spec.")
    parser.add_argument("spec", help="the full spec (JSON)")
    parser.add_argument("--out", required=True, help="where to write the flattened spec")
    parser.add_argument("--drop-terminal-failure", action="store_true",
                        help="also remove terminal_failure (the stricter reading)")
    args = parser.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    flat = flatten(spec, keep_terminal_failure=not args.drop_terminal_failure)
    found = problems(flat)
    if found:
        for problem in found:
            print(f"  - {problem}")
        return 1
    Path(args.out).write_text(json.dumps(flat, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(spec['execution_phases'])} phases -> 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
