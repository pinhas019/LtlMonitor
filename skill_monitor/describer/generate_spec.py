"""Natural-language skill description -> a monitor spec the monitor will accept, with a
record of how it was made.

    python -m skill_monitor.describer.generate_spec \\
        --adapter mujoco \\
        --description skill_monitor/specs/descriptions/g1_navigation.md \\
        --out skill_monitor/specs/formulas_g1_sim.json

The LLM sees the description and the adapter's sensor vocabulary, never a hand-written
spec. Each reply is checked by the same gates the monitor applies when a spec is loaded,
and the problems are handed back for repair (`generate_formulas.generate`):

    spec_contract.validate             every AP rule reads fields this robot provides
    manifest.fault_category_problems   every fault category is one the monitor grades
    offline_gate (here)                every phase and terminal condition parses

The spec is written only if all three pass; otherwise the exit code is 1 and the
problems are printed. Either way `<out>.provenance.json` records the model, endpoint,
attempts, what each attempt got wrong and hashes of the description and the result --
a generation that needed repairs, or failed, is evidence about the description step,
not something to hide.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

from skill_monitor.core import adapter_spec, manifest
from skill_monitor.describer import generate_formulas

_PHASE_CONDITIONS = ("enter_condition", "precondition", "invariant",
                     "progress_condition", "exit_condition")


def condition_problems(spec: dict) -> list[str]:
    """Phase and terminal conditions that do not parse as Python boolean expressions."""
    found = []

    def check(raw, label):
        if raw in (None, ""):
            return
        if not isinstance(raw, str):
            found.append(f"{label} must be a string, got {type(raw).__name__}")
            return
        try:
            ast.parse(raw, mode="eval")
        except SyntaxError as exc:
            found.append(f"{label} is not a Python boolean expression: {raw!r} ({exc.msg})")

    for i, phase in enumerate(spec.get("execution_phases") or []):
        name = phase.get("phase", f"#{i}") if isinstance(phase, dict) else f"#{i}"
        for key in _PHASE_CONDITIONS:
            check((phase or {}).get(key), f"phase {name}: {key}")
    for key in ("terminal_success", "terminal_failure"):
        check((spec.get(key) or {}).get("condition"), f"{key}.condition")
    if not spec.get("execution_phases"):
        found.append("spec declares no execution_phases")
    return found


def offline_gate(spec: dict) -> list[str]:
    """Everything the monitor would refuse at load that the schema check does not see."""
    return manifest.fault_category_problems(spec) + condition_problems(spec)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def provenance_path(out: Path) -> Path:
    return out.with_name(out.stem + ".provenance.json")


def run(*, adapter: str, description_path: Path, out: Path, api_url: str, model: str,
        attempts: int = 3, llm=None, now=None) -> tuple[dict, list[str]]:
    """Generate, gate, write. Returns (spec, surviving problems); writes the spec only
    when there are none, and the provenance always."""
    description = description_path.read_text(encoding="utf-8").strip()
    schema = adapter_spec.load(adapter).docs()
    calls = []

    def counted(api_url_, model_, prompt):
        calls.append(len(prompt))
        return (llm or generate_formulas.query_llm)(api_url_, model_, prompt)

    history: list[dict] = []
    spec, problems = generate_formulas.generate(
        description, schema, api_url=api_url, model=model, llm=counted,
        attempts=attempts, checks=offline_gate, history=history)

    accepted = not problems
    text = json.dumps(spec, indent=2) + "\n"
    if accepted:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).isoformat(timespec="seconds")
    provenance = {
        "generated_at": stamp,
        "accepted": accepted,
        "adapter": adapter,
        "model": model,
        "api_url": api_url,
        "attempts_allowed": attempts,
        "llm_calls": len(calls),
        "history": history,
        "surviving_problems": problems,
        "description_file": str(description_path),
        "description_sha256": _sha256(description),
        "spec_sha256": _sha256(text) if accepted else None,
    }
    provenance_path(out).parent.mkdir(parents=True, exist_ok=True)
    provenance_path(out).write_text(json.dumps(provenance, indent=2) + "\n",
                                    encoding="utf-8")
    return spec, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--adapter", required=True,
                        help="descriptor whose sensor vocabulary the spec is written over")
    parser.add_argument("--description", required=True, type=Path,
                        help="the skill in natural language (a .md or .txt file)")
    parser.add_argument("--out", required=True, type=Path, help="where the spec goes")
    parser.add_argument("--api-url", default=generate_formulas.DEFAULT_API_URL)
    parser.add_argument("--model", default=generate_formulas.DEFAULT_MODEL)
    parser.add_argument("--attempts", type=int, default=3,
                        help="model replies allowed, the first included")
    args = parser.parse_args(argv)

    spec, problems = run(adapter=args.adapter, description_path=args.description,
                         out=args.out, api_url=args.api_url, model=args.model,
                         attempts=args.attempts)
    where = provenance_path(args.out)
    if problems:
        print(f"Rejected after {args.attempts} attempt(s); provenance in {where}:",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({spec.get('skill_name', '?')}, "
          f"{len(spec.get('execution_phases') or [])} phases); provenance in {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
