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
    """Sanitize terminal/phase conditions and report problems."""
    warnings = []
    ap_names = set(spec.get("atomic_propositions", {}).keys())

    for key in ("terminal_success", "terminal_failure"):
        entry = spec.get(key, {})
        if not entry:
            continue
        raw = entry.get("condition", "")
        fixed = _sanitize_bool_expr(raw)
        if fixed != raw:
            warnings.append(f"[{key}] Sanitized: '{raw}' → '{fixed}'")
        spec[key]["condition"] = fixed

        try:
            tree = ast.parse(fixed, mode="eval")
            used = {
                n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and not keyword.iskeyword(n.id)
            }
            missing = used - ap_names
            if missing:
                warnings.append(
                    f"[{key}] Condition references undefined APs: {missing}"
                )
        except SyntaxError as e:
            warnings.append(f"[{key}] Syntax error after sanitization: {e}")

    for phase in spec.get("execution_phases", []):
        phase["condition"] = _sanitize_bool_expr(phase.get("condition", ""))

    return spec, warnings


# ---------------------------------------------------------------------------
# Narrative description generator (second LLM call)
# ---------------------------------------------------------------------------

def generate_skill_description(api_url: str, model: str, spec: dict) -> str:
    """Generate a structured per-phase skill description document."""
    phases = spec.get("execution_phases", [])

    # Build a detailed per-phase context block for the LLM
    phase_details = []
    for i, p in enumerate(phases):
        enter    = p.get("enter_condition") or p.get("condition", "—")
        progress = p.get("progress_condition", "True")
        exit_c   = p.get("exit_condition", "False")
        limit    = p.get("progress_violation_limit", 3)
        from_p   = phases[i - 1]["phase"] if i > 0 else "Idle"
        to_p     = phases[i + 1]["phase"] if i + 1 < len(phases) else "Done"
        phase_details.append(
            f"Phase {i+1}: {p['phase']}\n"
            f"  Description : {p.get('description', '')}\n"
            f"  Entered from: {from_p}\n"
            f"  Enter when  : {enter}\n"
            f"  Progress    : {progress}  (fail after {limit} consecutive violations)\n"
            f"  Exit when   : {exit_c}\n"
            f"  Exits to    : {to_p}"
        )

    ap_block = "\n".join(
        f"  {name}: {desc}"
        for name, desc in spec.get("atomic_propositions", {}).items()
    )
    formula_block = "\n".join(
        f"  {f['name']}: {f['formula']}"
        for f in spec.get("ltl_formulas", [])
    )
    ts = spec.get("terminal_success", {})
    tf = spec.get("terminal_failure", {})

    prompt = f"""You are writing operator documentation for a robot skill runtime monitor.

The document must follow this EXACT structure and use these EXACT section headings.
Each section and sub-section must appear even if content is minimal.

Skill: {spec.get("skill_name", "")}
Description: {spec.get("description", "")}

---
FORMAL SPEC (do NOT copy verbatim — translate into clear technical prose):

LTL formulas:
{formula_block}

Execution phases:
{chr(10).join(phase_details)}

Terminal success: {ts.get("condition", "")} — {ts.get("description", "")}
Terminal failure: {tf.get("condition", "")} — {tf.get("description", "")}

Atomic propositions:
{ap_block}

---
REQUIRED OUTPUT FORMAT (reproduce these exact headings):

# Skill Monitor Documentation: {spec.get("skill_name", "")}

## Overview
(3-4 sentences: what the skill does, its goal, what failure looks like)

## Monitored LTL Properties
(For each formula: name, what safety/liveness property it enforces, why it matters)

## Execution Phases

(Repeat this block for EVERY phase in order:)

### Phase: <PhaseName>
**Description**
(1-2 sentences on what the robot is doing in this phase)

**Enter Conditions**
Entered from: <previous phase or Idle>
When: <plain-English explanation of enter_condition>

**Progress Conditions**
(Plain-English explanation of progress_condition — what must remain True)
If violated for <N> consecutive steps, the skill is declared failed.

**Exit Conditions**
Exits to: <next phase or Done>
When: <plain-English explanation of exit_condition>

**Possible Transitions**
- Advance → <next phase>: when <exit condition plain English>
- Failure: when progress conditions are violated <N> consecutive times

---

## Terminal Conditions

### Success
Condition: <plain English>
(Description of what this means operationally)

### Failure
Condition: <plain English>
(Description of what this means operationally)

## Atomic Propositions
(Table or list: AP name | evaluation rule | plain-English meaning)

---
Write only the document. No preamble, no JSON, no code fences.
"""

    print("[*] Generating structured skill description...")
    return query_llm_text(api_url, model, prompt)


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
    parser.add_argument("--desc-output", "-t", default="skill_description.txt",
                        help="Output path for skill description text (default: skill_description.txt).")
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
   GOOD: "nav_status_success and near_target"
   BAD:  "G(nav_status_success) && near_target"

3. execution_phases[].enter_condition, progress_condition, exit_condition must all use plain Python boolean syntax (and/or/not).

4. ltl_formulas[].formula MUST use LTL syntax (G, F, X, U, ->, &&, ||, !) valid for the Spot library.

5. Only reference AP names that are defined in atomic_propositions.

6. description must be 2-3 sentences covering the skill's purpose, what it monitors, and its termination criteria.

7. Each execution phase MUST have three conditions:
   - enter_condition: APs that must be True to enter this phase (checked on transition from previous phase or Idle)
   - progress_condition: APs that must remain True WHILE in this phase; if violated for progress_violation_limit consecutive steps the skill fails
   - exit_condition: APs that must be True to leave this phase and advance to the next

Respond with a single valid JSON object:
{{
  "skill_name": "CamelCaseSkillName",
  "description": "2-3 sentence description of purpose, monitored properties, and termination criteria.",
  "atomic_propositions": {{
    "ap_name": "True when <sensor rule>. <plain-English meaning>."
  }},
  "ltl_formulas": [
    {{
      "name": "formula_name",
      "formula": "LTL formula using Spot syntax"
    }}
  ],
  "execution_phases": [
    {{
      "phase": "PhaseName",
      "description": "What the robot is doing in this phase.",
      "enter_condition": "ap1 and ap2",
      "progress_condition": "ap3 and not ap4",
      "exit_condition": "ap5",
      "progress_violation_limit": 3
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

    # Second call: generate narrative skill description
    print(f"[*] Step 2/2 — Generating narrative skill description ({args.desc_output})...")
    narrative = generate_skill_description(args.api_url, args.model, formulas_json)

    if not narrative:
        # Fallback: structured text assembled from JSON fields
        skill_name = formulas_json.get("skill_name", "UnknownSkill")
        description = formulas_json.get("description", "")
        phases = formulas_json.get("execution_phases", [])
        ts = formulas_json.get("terminal_success", {})
        tf = formulas_json.get("terminal_failure", {})
        lines = [
            f"Skill: {skill_name}", f"Description: {description}",
            "=" * 60, "Execution Phases:", "=" * 60,
        ]
        for entry in phases:
            lines += [f"\n[{entry.get('phase', '?')}]",
                      f"  Condition  : {entry.get('condition', '')}",
                      f"  Description: {entry.get('description', '')}"]
        lines += ["", "=" * 60, "Terminal Conditions:",
                  f"  SUCCESS : {ts.get('condition', '')}",
                  f"            {ts.get('description', '')}",
                  f"  FAILURE : {tf.get('condition', '')}",
                  f"            {tf.get('description', '')}"]
        narrative = "\n".join(lines)

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
