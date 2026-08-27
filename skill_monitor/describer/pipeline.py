#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import os
from pathlib import Path

BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"


def run_command(cmd: list, check: bool = True, env: dict = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=check, env=env)
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(e.returncode or 1)


def _nested_f_depth(formula: str) -> int:
    """Count nested F(...) operators — proxy for expected automaton state count."""
    return len(re.findall(r'F\s*\(', formula))


def _validate_and_summarize(formulas_path: Path) -> int:
    """
    Parse formulas.json, print a structured summary, and return the number of warnings.
    Checks that the spec makes full use of the new constraint system:
      - Nested F formulas (rich automaton)
      - named_failure_modes with fault categories
      - Per-phase preconditions, invariants, and timing bounds
    """
    try:
        data = json.loads(formulas_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  {RED}✘  Could not parse formulas.json: {e}{RESET}", file=sys.stderr)
        return 1

    if isinstance(data, list):
        print(f"  {DIM}Simple formula list ({len(data)} formula(s)) — no rich spec fields to check.{RESET}")
        return 0

    skill      = data.get("skill_name", "(unnamed)")
    formulas   = data.get("ltl_formulas", [])
    phases     = data.get("execution_phases", [])
    named_fms  = data.get("named_failure_modes", [])
    aps        = data.get("atomic_propositions", {})
    warnings   = 0

    print(f"\n  {BOLD}{CYAN}Skill:{RESET}  {skill}")
    if data.get("description"):
        desc = data["description"]
        print(f"  {DIM}{desc[:120]}{'…' if len(desc) > 120 else ''}{RESET}")

    # ── LTL formulas ─────────────────────────────────────────────
    print(f"\n  {BOLD}LTL Formulas  ({len(formulas)}):{RESET}")
    for f in formulas:
        formula_str = f.get("formula", "")
        depth = _nested_f_depth(formula_str)
        est   = depth + 1 if depth else 2
        if depth < 2:
            print(f"    {YELLOW}⚠  {f.get('name', formula_str)}{RESET}")
            print(f"       {DIM}{formula_str}{RESET}")
            print(f"       {YELLOW}~{est} automaton states — nest F() deeper for phase-tracking automaton{RESET}")
            warnings += 1
        else:
            print(f"    {GREEN}✔  {f.get('name', formula_str)}{RESET}")
            print(f"       {DIM}{formula_str}{RESET}")
            print(f"       {DIM}~{est} automaton states{RESET}")

    # ── Named failure modes ───────────────────────────────────────
    if named_fms:
        print(f"\n  {BOLD}Named Failure Modes  ({len(named_fms)}):{RESET}")
        for fm in named_fms:
            cat = fm.get("fault_category", "UNKNOWN")
            print(f"    {RED}✘  [{cat}]{RESET}  {fm['name']}  →  {DIM}{fm['formula']}{RESET}")
            if fm.get("description"):
                print(f"       {DIM}{fm['description']}{RESET}")
    else:
        print(f"\n  {YELLOW}⚠  No named_failure_modes — faults will surface as generic automaton violations{RESET}")
        warnings += 1

    # ── Execution phases ──────────────────────────────────────────
    if phases:
        print(f"\n  {BOLD}Execution Phases  ({len(phases)}):{RESET}")
        for p in phases:
            tags = []
            if p.get("precondition"):
                cat = p.get("precondition_fault_category", "PRECONDITION")
                tags.append(f"{GREEN}precondition [{cat}]{RESET}")
            if p.get("invariant"):
                cat = p.get("invariant_fault_category", "INVARIANT")
                tags.append(f"{RED}invariant [{cat}]{RESET}")
            if p.get("timing_bounds"):
                t = p["timing_bounds"]
                parts = []
                if "min_steps" in t: parts.append(f"min={t['min_steps']}")
                if "max_steps" in t: parts.append(f"max={t['max_steps']}")
                tags.append(f"{CYAN}timing({', '.join(parts)}){RESET}")

            if tags:
                print(f"    {p['phase']}")
                for tag in tags:
                    print(f"      + {tag}")
            else:
                print(f"    {YELLOW}⚠  {p['phase']}  [no precondition / invariant / timing]{RESET}")
                warnings += 1
    else:
        print(f"\n  {YELLOW}⚠  No execution_phases defined{RESET}")
        warnings += 1

    # ── AP breakdown ──────────────────────────────────────────────
    rule_count = sum(1 for d in aps.values() if re.search(r'[Tt]rue when', d))
    llm_count  = len(aps) - rule_count
    print(f"\n  {BOLD}Atomic Propositions:{RESET}  {len(aps)} total  "
          f"({GREEN}⚡ {rule_count} rule-based{RESET}, "
          f"{CYAN}🤖 {llm_count} LLM-evaluated{RESET})")

    # ── Terminal conditions ───────────────────────────────────────
    ts = data.get("terminal_success", {}).get("condition", "")
    tf = data.get("terminal_failure", {}).get("condition", "")
    print(f"\n  {BOLD}Terminal:{RESET}  "
          f"{GREEN}success:{RESET} {ts or '(none)'}   "
          f"{RED}failure:{RESET} {tf or '(none)'}")

    print()
    if warnings:
        print(f"  {YELLOW}⚠  {warnings} warning(s) above.{RESET}")
        print(f"  {DIM}  Re-run without --no-generate to produce a richer spec,{RESET}")
        print(f"  {DIM}  or edit formulas.json manually and use --no-generate.{RESET}\n")
    else:
        print(f"  {GREEN}✔  Spec is complete — all constraint layers present.{RESET}\n")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Run the entire LTL Monitor and simulation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from natural language description
  python3 run_pipeline.py -d "Navigate to a target while avoiding obstacles"

  # Use existing formulas.json without regenerating
  python3 run_pipeline.py --no-generate

  # Just validate and preview the current formulas.json
  python3 run_pipeline.py --validate-only

  # Rebuild Docker images and start (first run or after code changes)
  python3 run_pipeline.py -d "..." --no-build=False
""",
    )
    parser.add_argument("--description", "-d", type=str,
                        help="Natural language description of the robot skill.")
    parser.add_argument("--api-url", "--ollama-url", dest="api_url",
                        default="http://192.168.140.101/developer-api/v1",
                        help="LLM API base URL.")
    parser.add_argument("--model", default="Gemma4",
                        help="LLM model name (default: Gemma4).")
    parser.add_argument("--no-build",     action="store_true",
                        help="Skip rebuilding Docker containers.")
    parser.add_argument("--no-generate",  action="store_true",
                        help="Skip formula generation; use existing formulas.json.")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate and print formulas.json summary, then exit.")
    args = parser.parse_args()

    script_dir    = Path(os.path.dirname(os.path.abspath(__file__)))
    formulas_path = script_dir / "formulas.json"
    compose_file  = script_dir / "sim" / "docker-compose.sim.yml"

    env = os.environ.copy()
    env["LLM_MODEL"]   = args.model
    env["LLM_API_URL"] = args.api_url

    # ── Step 1: Generate formulas ─────────────────────────────────
    if not args.no_generate and not args.validate_only:
        skill_desc = args.description
        if not skill_desc:
            if sys.stdin.isatty():
                print("Enter the natural language robot skill description:")
                try:
                    skill_desc = input("> ").strip()
                except KeyboardInterrupt:
                    print("\nExiting.")
                    sys.exit(0)
            else:
                print("Error: No description provided and input is not interactive.",
                      file=sys.stderr)
                sys.exit(1)

        if not skill_desc:
            print("Error: Skill description cannot be empty.", file=sys.stderr)
            sys.exit(1)

        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}Step 1: Generating LTL formulas via LLM...{RESET}")
        print(f"{BOLD}{'='*60}{RESET}")

        run_command([
            sys.executable, str(script_dir / "generate_formulas.py"),
            "-d", skill_desc,
            "--api-url", args.api_url,
            "--model",   args.model,
        ])

    elif not args.validate_only:
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}Step 1: Skipped (--no-generate) — using existing formulas.json{RESET}")
        print(f"{BOLD}{'='*60}{RESET}")

    # ── Validate + summarize ──────────────────────────────────────
    label = "Validating" if args.validate_only else "Step 1b: Reviewing"
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}{label} formulas.json{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    if not formulas_path.exists():
        print(f"{RED}✘  formulas.json not found at {formulas_path}{RESET}", file=sys.stderr)
        sys.exit(1)

    _validate_and_summarize(formulas_path)

    if args.validate_only:
        sys.exit(0)

    # ── Step 2: Stop any running stack ───────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Step 2: Starting Docker simulation stack...{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    print("Stopping active containers...")
    run_command(["docker", "compose", "-f", str(compose_file), "down"],
                check=False, env=env)

    # ── Step 3: Run stack in foreground (logs stream directly) ───
    up_cmd = ["docker", "compose", "-f", str(compose_file), "up"]
    if not args.no_build:
        up_cmd.append("--build")

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Step 3: Running stack  (Ctrl+C to stop){RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    try:
        subprocess.run(up_cmd, env=env)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        if sys.stdin.isatty():
            try:
                ans = input("Shut down the simulation stack? [y/N]: ").strip().lower()
                if ans == "y":
                    print("\nShutting down containers...")
                    subprocess.run(
                        ["docker", "compose", "-f", str(compose_file), "down"],
                        env=env,
                    )
                else:
                    print("\nStack left running in the background.")
            except KeyboardInterrupt:
                print("\nLeaving stack running.")
        else:
            print("Leaving stack running in the background.")


if __name__ == "__main__":
    main()
