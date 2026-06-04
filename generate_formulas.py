#!/usr/bin/env python3
import ast
import json
import keyword
import re
import urllib.request
import argparse
import sys

# ---------------------------------------------------------------------------
# Sensor schema — ground truth for what the evaluator (llm_client.py) can read.
# AP descriptions MUST reference these exact field names and thresholds.
# ---------------------------------------------------------------------------

SENSOR_SCHEMA = """
Available sensor fields (provided to the evaluator at each step):
  Odometry (/odom):
    position.x, position.y          — robot position in metres
    linear_vel                       — forward speed in m/s  (moving if > 0.05)
    angular_vel                      — rotation speed in rad/s
    distance_to_target               — Euclidean distance to current goal in metres

  Laser scan (/scan):
    min_range                        — closest obstacle distance in metres
    mean_range                       — average obstacle distance in metres
    close_objects                    — number of laser rays < 1.0 m

  Nav2 action status (/navigate_to_pose/_action/status):
    nav_status                       — one of: "accepted", "executing", "canceling",
                                       "succeeded", "canceled", "aborted"

Evaluation rule examples (the evaluator applies these literally):
  "True when linear_vel > 0.05"
  "True when distance_to_target < 0.5"
  "True when min_range < 0.25"
  "True when nav_status == 'succeeded'"
  "True when nav_status in ['aborted', 'canceled']"
  "True when nav_status in ['accepted', 'executing']"
"""

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _build_request(api_url: str, model: str, prompt: str, json_mode: bool) -> urllib.request.Request:
    is_openai = "/v1" in api_url or "openai" in api_url
    if is_openai:
        endpoint = api_url if api_url.endswith("/chat/completions") else f"{api_url.rstrip('/')}/chat/completions"
        data: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        if json_mode:
            data["response_format"] = {"type": "json_object"}
    else:
        endpoint = f"{api_url.rstrip('/')}/api/generate"
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        if json_mode:
            data["format"] = "json"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    req.add_header("Authorization", "Bearer dummy-key")
    return req, is_openai


def query_llm(api_url: str, model: str, prompt: str) -> dict:
    """Query the LLM and return parsed JSON."""
    req, is_openai = _build_request(api_url, model, prompt, json_mode=True)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            if is_openai:
                content = result["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    first_nl = content.find("\n")
                    if first_nl != -1:
                        content = content[first_nl:].strip()
                    if content.endswith("```"):
                        content = content[:-3].strip()
                return json.loads(content)
            else:
                return json.loads(result["response"])
    except Exception as e:
        print(f"Error: LLM query failed: {e}", file=sys.stderr)
        if hasattr(e, "read"):
            try:
                print(f"Response body: {e.read().decode('utf-8')}", file=sys.stderr)
            except Exception:
                pass
        sys.exit(1)


def query_llm_text(api_url: str, model: str, prompt: str) -> str:
    """Query the LLM and return plain text (no JSON formatting enforced)."""
    req, is_openai = _build_request(api_url, model, prompt, json_mode=False)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            if is_openai:
                return result["choices"][0]["message"]["content"].strip()
            else:
                return result["response"].strip()
    except Exception as e:
        print(f"Warning: skill description generation failed: {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Post-processing: sanitize & validate
# ---------------------------------------------------------------------------

_LTL_OPS = re.compile(r"\b(G|F|X)\s*\(")


def _sanitize_bool_expr(expr: str) -> str:
    """Convert LTL/C-style operators to Python boolean syntax."""
    prev = None
    while prev != expr:
        prev = expr
        expr = _LTL_OPS.sub("(", expr)
    expr = expr.replace("&&", " and ")
    expr = expr.replace("||", " or ")
    expr = re.sub(r"!(?!=)", "not ", expr)
    return expr.strip()


def _validate_and_fix(spec: dict) -> tuple[dict, list[str]]:
    """Sanitize all Python boolean conditions and report problems."""
    warnings = []
    ap_names = set(spec.get("atomic_propositions", {}).keys())

    def _check_condition(raw: str, label: str) -> str:
        fixed = _sanitize_bool_expr(raw)
        if fixed != raw:
            warnings.append(f"[{label}] Sanitized: '{raw}' → '{fixed}'")
        if fixed and fixed not in ("True", "False", "true", "false"):
            try:
                tree = ast.parse(fixed, mode="eval")
                used = {
                    n.id for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and not keyword.iskeyword(n.id)
                }
                missing = used - ap_names
                if missing:
                    warnings.append(f"[{label}] References undefined APs: {missing}")
            except SyntaxError as e:
                warnings.append(f"[{label}] Syntax error after sanitization: {e}")
        return fixed

    # Terminal conditions
    for key in ("terminal_success", "terminal_failure"):
        entry = spec.get(key, {})
        if entry:
            spec[key]["condition"] = _check_condition(
                entry.get("condition", ""), key
            )

    # Phase conditions — all five boolean fields + legacy "condition"
    for phase in spec.get("execution_phases", []):
        name = phase.get("phase", "?")
        for field in ("condition", "enter_condition", "precondition",
                      "invariant", "progress_condition", "exit_condition"):
            if phase.get(field):
                phase[field] = _check_condition(phase[field], f"phase.{name}.{field}")

    return spec, warnings


# ---------------------------------------------------------------------------
# Structured skill description formatter (deterministic — no LLM call)
# ---------------------------------------------------------------------------

def _collect_phase_aps(phase: dict, all_aps: dict) -> dict:
    """Return {ap_name: description} for every AP referenced in any phase condition."""
    used: set[str] = set()
    for field in ("enter_condition", "condition", "precondition",
                  "invariant", "progress_condition", "exit_condition"):
        raw = phase.get(field, "")
        if not raw:
            continue
        try:
            sanitized = re.sub(r'\b(G|F|X)\s*\(', '(', raw)
            sanitized = sanitized.replace('&&', ' and ').replace('||', ' or ')
            sanitized = re.sub(r'!(?!=)', 'not ', sanitized)
            tree = ast.parse(sanitized, mode='eval')
            used |= {
                n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and not keyword.iskeyword(n.id)
            }
        except Exception:
            pass
    return {n: all_aps[n] for n in sorted(used) if n in all_aps}


def _nested_f_chain(formula: str) -> list[str]:
    """
    Extract the AP at each nesting level of a formula like
    F(p1 && F(p2 && F(p3 && F(p4)))).
    Returns ['p1', 'p2', 'p3', 'p4'].
    """
    return re.findall(r'F\s*\(\s*(\w+)', formula)


def generate_skill_description(_api_url: str, _model: str, spec: dict) -> str:
    """
    Build a Markdown per-phase reference document from the spec dict.
    Deterministic — no LLM call. Every field is taken directly from formulas.json.
    """
    lines: list[str] = []

    skill_name = spec.get("skill_name", "UnknownSkill")
    all_aps    = spec.get("atomic_propositions", {})
    formulas   = spec.get("ltl_formulas", [])
    named_fms  = spec.get("named_failure_modes", [])
    phases     = spec.get("execution_phases", [])
    ts         = spec.get("terminal_success", {})
    tf         = spec.get("terminal_failure", {})

    def _ap_method(desc: str) -> str:
        return "⚡ Rule" if re.search(r'[Tt]rue when', desc) else "🤖 LLM"

    # ── Title ─────────────────────────────────────────────────────
    lines += [f"# Skill Monitor Documentation: {skill_name}", ""]
    if spec.get("description"):
        lines += [f"> {spec['description']}", ""]
    lines.append("---")

    # ── LTL formulas ──────────────────────────────────────────────
    lines += ["", "## LTL Formulas (Mission Specification)", ""]
    if formulas:
        lines.append("| Name | Formula | Automaton milestone chain |")
        lines.append("|---|---|---|")
        for f in formulas:
            chain = _nested_f_chain(f.get("formula", ""))
            chain_str = " → ".join(f"`{ap}`" for ap in chain) if chain else "—"
            lines.append(f"| `{f.get('name', '')}` | `{f['formula']}` | {chain_str} |")
    else:
        lines.append("*(no formulas defined)*")

    # ── Named failure modes ───────────────────────────────────────
    lines += ["", "---", "", "## Named Failure Modes", "",
              "> LTL formulas whose **VIOLATED** status triggers an immediate named halt.", ""]
    if named_fms:
        lines.append("| Fault Category | Name | Formula | Description |")
        lines.append("|---|---|---|---|")
        for fm in named_fms:
            cat  = fm.get("fault_category", "?")
            desc = fm.get("description", "")
            lines.append(f"| `{cat}` | `{fm['name']}` | `{fm['formula']}` | {desc} |")
    else:
        lines.append("*(no named failure modes defined)*")

    # ── Terminal conditions ───────────────────────────────────────
    lines += ["", "---", "", "## Terminal Conditions", ""]
    if ts:
        lines += [
            f"**✅ SUCCESS** — `{ts.get('condition', '(none)')}`",
            f"> {ts.get('description', '')}",
            "",
        ]
    if tf:
        lines += [
            f"**❌ FAILURE** — `{tf.get('condition', '(none)')}`",
            f"> {tf.get('description', '')}",
            "",
        ]

    # ── All atomic propositions ───────────────────────────────────
    lines += ["---", "", "## Atomic Propositions", ""]
    if all_aps:
        lines.append("| Name | Eval | Rule / Description |")
        lines.append("|---|---|---|")
        for name, desc in all_aps.items():
            lines.append(f"| `{name}` | {_ap_method(desc)} | {desc} |")
    else:
        lines.append("*(none)*")

    # ── Per-phase sections ────────────────────────────────────────
    for i, p in enumerate(phases):
        prev_phase = phases[i - 1]["phase"] if i > 0 else "Idle"
        next_phase = phases[i + 1]["phase"] if i + 1 < len(phases) else "Done"
        phase_aps  = _collect_phase_aps(p, all_aps)

        lines += [
            "", "---", "",
            f"## Phase {i+1}/{len(phases)} — {p['phase']}", "",
        ]
        if p.get("description"):
            lines += [f"> {p['description']}", ""]

        # ── Entry ──────────────────────────────────────────────────
        lines += ["### Entry", ""]
        lines.append(f"- **From:** {prev_phase}")
        enter = p.get("enter_condition") or p.get("condition") or "—"
        lines.append(f"- **Condition:** `{enter}`")

        precond = p.get("precondition", "")
        if precond and precond.strip().lower() not in ("true", ""):
            cat = p.get("precondition_fault_category", "PRECONDITION")
            lines += [
                "",
                f"**Precondition** *(checked once on entry)*",
                "",
                f"```",
                precond,
                f"```",
                f"> `[{cat}]` halt if not satisfied",
            ]
        lines.append("")

        # ── In Progress ────────────────────────────────────────────
        lines += ["### In Progress", ""]

        invariant = p.get("invariant", "")
        if invariant:
            cat = p.get("invariant_fault_category", "INVARIANT")
            lines += [
                "#### Invariant *(every step — immediate halt if violated)*",
                "",
                "```",
                invariant,
                "```",
                f"> **`[{cat}]`** halt on violation",
                "",
            ]

        progress = p.get("progress_condition", "")
        if progress:
            limit = p.get("progress_violation_limit", 3)
            lines += [
                "#### Progress *(counted soft violations)*",
                "",
                "```",
                progress,
                "```",
                f"> **`[PROGRESS]`** enter IDLE after **{limit}** consecutive violations",
                "",
            ]

        timing = p.get("timing_bounds", {})
        if timing:
            min_s = timing.get("min_steps")
            max_s = timing.get("max_steps")
            lines += ["#### Timing", ""]
            if min_s is not None:
                lines.append(f"- **`min_steps`: {min_s}** — exit blocked until this many steps have elapsed")
            if max_s is not None:
                lines.append(f"- **`max_steps`: {max_s}** — `[TIMEOUT]` halt if exceeded")
            lines.append("")

        # ── Exit ───────────────────────────────────────────────────
        lines += ["### Exit", ""]
        lines.append(f"- **To:** {next_phase}")
        lines.append(f"- **Condition:** `{p.get('exit_condition', '—')}`")
        lines.append("")

        # ── APs used in this phase ─────────────────────────────────
        if phase_aps:
            lines += ["### Atomic Propositions Used in This Phase", ""]
            lines.append("| Name | Eval | Rule / Description |")
            lines.append("|---|---|---|")
            for ap_name, ap_desc in phase_aps.items():
                lines.append(f"| `{ap_name}` | {_ap_method(ap_desc)} | {ap_desc} |")
            lines.append("")

        # ── Related formulas ───────────────────────────────────────
        lines += ["### Related Formulas", ""]

        for f in formulas:
            formula_str = f.get("formula", "")
            chain = _nested_f_chain(formula_str)
            lines += [
                f"**LTL:** `{f.get('name', '')}`",
                "",
                "```",
                formula_str,
                "```",
                "",
            ]
            if i < len(chain):
                lines.append(
                    f"> Automaton **state {i}**: waiting for `{chain[i]}` to advance to state {i+1}"
                )
            elif chain:
                lines.append("> Automaton **accepting state** — all milestones satisfied")
            lines.append("")

        if named_fms:
            lines += ["**Named failure modes active in this phase:**", ""]
            lines.append("| Fault Category | Name | Formula |")
            lines.append("|---|---|---|")
            for fm in named_fms:
                cat = fm.get("fault_category", "?")
                lines.append(f"| `{cat}` | `{fm['name']}` | `{fm['formula']}` |")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate LTL formulas and skill description from natural language."
    )
    parser.add_argument("--description", "-d", type=str,
                        help="Natural language description of the robot skill.")
    parser.add_argument("--output", "-o", default="formulas.json",
                        help="Output path for formulas JSON (default: formulas.json).")
    parser.add_argument("--desc-output", "-t", default="skill_description.md",
                        help="Output path for skill description (default: skill_description.md).")
    parser.add_argument("--api-url", "--ollama-url", dest="api_url",
                        default="http://192.168.140.111/developer-api/v1",
                        help="LLM API base URL.")
    parser.add_argument("--model", default="Gemma4",
                        help="LLM model name (default: Gemma4).")
    args = parser.parse_args()

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
            print("Error: No description provided and input is not interactive.", file=sys.stderr)
            sys.exit(1)

    if not skill_desc:
        print("Error: Skill description cannot be empty.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Connecting to {args.api_url} using model {args.model}...")
    print("[*] Step 1/2 — Generating formal skill specification (formulas.json)...")

    formulas_prompt = f"""You are an expert in robotics, Linear Temporal Logic (LTL), formal verification, and runtime monitoring.

Your task: convert the robot skill description below into a formal monitoring specification.

Skill Description:
"{skill_desc}"

{SENSOR_SCHEMA}

CRITICAL RULES:
1. Every atomic proposition description MUST include a concrete, sensor-measurable evaluation rule
   using the exact field names and thresholds listed above.
   GOOD: "True when nav_status == 'succeeded'. The navigation goal was reached."
   BAD:  "The robot has reached the target." (no sensor rule — evaluator cannot apply this)

2. terminal_success.condition and terminal_failure.condition MUST be plain Python boolean
   expressions using only: and, or, not, ==, !=, <, >, <=, >=, parentheses, and AP names.
   DO NOT use LTL operators (G, F, X, U) or C-style operators (&&, ||, !) in these fields.

3. All execution_phases conditions (enter_condition, precondition, invariant, progress_condition,
   exit_condition) must use plain Python boolean syntax (and/or/not).

4. ltl_formulas[].formula MUST use LTL syntax (G, F, X, U, ->, &&, ||, !) valid for the Spot library.
   For skills with sequential phases, use nested F operators to produce a richer automaton:
   GOOD: "F(phase1_ap && F(phase2_ap && F(phase3_ap)))"  — one state per milestone
   BAD:  "F(final_ap)"  — generates only a 2-state automaton, loses phase tracking

5. Only reference AP names that are defined in atomic_propositions.

6. description must be 2-3 sentences covering the skill's purpose, what it monitors, and
   its termination criteria.

7. Each execution phase MUST have:
   - enter_condition: APs that must be True to transition into this phase
   - precondition: Python bool checked ONCE on phase entry; "" if none
   - precondition_fault_category: fault category string if precondition fails (e.g. "PRECONDITION", "NAVIGATION")
   - invariant: Python bool checked EVERY step; immediate halt if False; "" if none
   - invariant_fault_category: fault category string if invariant violated (e.g. "SAFETY", "NAVIGATION")
   - progress_condition: must remain True while in phase; counted violations
   - exit_condition: APs that must be True to leave this phase
   - progress_violation_limit: int (typically 3–5)
   - timing_bounds: object with "max_steps" (required) and optionally "min_steps"

8. named_failure_modes: one entry per global failure mode that should trigger a named halt
   anywhere during execution (not just within a phase). Use G(!) formulas for safety properties.
   Each entry: name, formula (LTL), fault_category (e.g. "SAFETY", "NAVIGATION"), description.

Respond with a single valid JSON object:
{{
  "skill_name": "CamelCaseSkillName",
  "description": "2-3 sentence description.",
  "atomic_propositions": {{
    "ap_name": "True when <sensor rule>. <plain-English meaning>."
  }},
  "ltl_formulas": [
    {{
      "name": "formula_name",
      "formula": "F(ap1 && F(ap2 && F(ap3)))"
    }}
  ],
  "named_failure_modes": [
    {{
      "name": "collision_risk",
      "formula": "G(!obstacle_detected)",
      "fault_category": "SAFETY",
      "description": "Robot must never come within collision range of an obstacle."
    }}
  ],
  "execution_phases": [
    {{
      "phase": "PhaseName",
      "description": "What the robot is doing in this phase.",
      "enter_condition": "ap1 and ap2",
      "precondition": "ap3",
      "precondition_fault_category": "PRECONDITION",
      "invariant": "not ap4",
      "invariant_fault_category": "SAFETY",
      "progress_condition": "ap3 and not ap4",
      "exit_condition": "ap5",
      "progress_violation_limit": 3,
      "timing_bounds": {{"max_steps": 60}}
    }}
  ],
  "terminal_success": {{
    "condition": "ap1 and ap2",
    "description": "What constitutes successful completion."
  }},
  "terminal_failure": {{
    "condition": "ap3 or ap4",
    "description": "What constitutes task failure."
  }}
}}

Respond ONLY with the JSON object. No markdown, no code fences, no explanation.
"""

    formulas_json = query_llm(args.api_url, args.model, formulas_prompt)

    # Sanitize and validate
    formulas_json, warnings = _validate_and_fix(formulas_json)
    if warnings:
        print("\n[!] Post-processing warnings:")
        for w in warnings:
            print(f"    {w}")

    # Save formulas.json
    try:
        with open(args.output, "w") as f:
            json.dump(formulas_json, f, indent=2)
        print(f"\n[+] Saved formal specification to: {args.output}")
    except Exception as e:
        print(f"Error: Failed to write formulas file: {e}", file=sys.stderr)

    # Step 2/2: build structured per-phase reference document (deterministic)
    print(f"[*] Step 2/2 — Building structured skill description ({args.desc_output})...")
    narrative = generate_skill_description(args.api_url, args.model, formulas_json)

    try:
        with open(args.desc_output, "w") as f:
            f.write(narrative)
        print(f"[+] Saved skill description to: {args.desc_output}")
    except Exception as e:
        print(f"Error: Failed to write skill description: {e}", file=sys.stderr)

    print("\n" + "=" * 60)
    print(narrative)


if __name__ == "__main__":
    main()
