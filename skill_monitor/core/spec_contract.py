"""Does a formulas_*.json spec only talk about things the robot can actually observe?

This is the validation oracle for skill-agnostic synthesis. A spec is generated from
a free-language skill description by an LLM, which has no way to know which sensor
fields exist -- so the generated rules must be mechanically checked against the
adapter's declared schema before the spec is allowed anywhere near the engine.

Used by BOTH:
  - test_adapter_sensor_eval_contract.py  (static check of the hand-authored spec)
  - generate_formulas.py                  (generate -> validate -> repair loop)

so the two can never drift apart. rclpy-free on purpose: the generator runs on a host
with no ROS.

A rule AP is an atomic proposition whose description carries an executable rule, in
the form "True when <python expression>. <prose>". Anything else is an LLM-evaluated
AP and has no schema obligation.
"""

from __future__ import annotations

import re

# The terminator is a sentence-ending period -- one followed by whitespace or the end
# of the string -- NOT any period. Matching any period truncates the rule at the first
# DECIMAL POINT, so "True when min_range < 0.25." evaluated as "min_range < 0", which
# is never true for a distance. See test_decimal_literals_survive_extraction.
TRUE_WHEN_RE = re.compile(r"[Tt]rue when\s+(.+?)(?:\.\s|\.$|$)", re.IGNORECASE)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Python keywords/literals that may appear in a rule but are not sensor fields.
NON_SENSOR_TOKENS = frozenset({
    "and", "or", "not", "in", "is", "if", "else", "True", "False", "None",
    "abs", "min", "max", "len",   # tolerated in rules; eval() has no builtins, so a
                                  # rule using them fails safely rather than silently
})


def rule_of(description: str) -> str | None:
    """The executable part of a rule AP description, or None if it is not a rule AP."""
    m = TRUE_WHEN_RE.search(description)
    return m.group(1).strip().rstrip(".") if m else None


def sensor_keys_in_rule(description: str) -> set[str]:
    """Identifiers a rule references, excluding keywords and string-literal contents."""
    rule = rule_of(description)
    if rule is None:
        return set()
    # Strip string literals first, else 'AUTOMATIC' inside a comparison is mistaken
    # for a bare identifier.
    rule = _QUOTED.sub("", rule)
    return {t for t in _IDENT.findall(rule) if t not in NON_SENSOR_TOKENS}


def unknown_keys(spec: dict, schema_keys) -> dict[str, set[str]]:
    """AP name -> the sensor keys it references that the schema does not provide.

    Empty dict means the spec is executable against this adapter.
    """
    schema_keys = frozenset(schema_keys)
    out: dict[str, set[str]] = {}
    for ap, desc in (spec.get("atomic_propositions") or {}).items():
        missing = sensor_keys_in_rule(desc) - schema_keys
        if missing:
            out[ap] = missing
    return out


def undeclared_aps(spec: dict) -> set[str]:
    """APs used in formulas/phases/terminals but never declared. A generated spec that
    references an AP it forgot to define is silently always-false at runtime."""
    declared = set(spec.get("atomic_propositions") or {})
    used: set[str] = set()

    def scan(text):
        if isinstance(text, str):
            used.update(
                t for t in _IDENT.findall(_QUOTED.sub("", text))
                if t not in NON_SENSOR_TOKENS
            )

    for f in spec.get("ltl_formulas") or []:
        scan(f.get("formula"))
    for f in spec.get("named_failure_modes") or []:
        scan(f.get("formula"))
    for ph in spec.get("execution_phases") or []:
        for k in ("enter_condition", "condition", "precondition", "invariant",
                  "progress_condition", "exit_condition"):
            scan(ph.get(k))
    for k in ("terminal_success", "terminal_failure"):
        scan((spec.get(k) or {}).get("condition"))

    # LTL temporal operators are single uppercase letters, not APs.
    return {u for u in used - declared if u not in {"G", "F", "X", "U", "R", "W", "M"}}


def validate_structure(spec: dict) -> list[str]:
    """Problems that need no schema: a spec is internally incoherent regardless of
    which robot runs it. Split out because a monitor may have to judge a pushed spec
    before any adapter has announced its schema."""
    problems: list[str] = []

    for ap in sorted(undeclared_aps(spec)):
        problems.append(
            f"'{ap}' is used in a formula/phase/terminal condition but is not declared "
            f"in atomic_propositions"
        )

    if not (spec.get("atomic_propositions") or {}):
        problems.append("spec declares no atomic propositions")

    return problems


def validate(spec: dict, schema_keys) -> list[str]:
    """Human-readable problems, empty if the spec is executable. This list is what the
    repair loop feeds back to the LLM, so each message names the offending AP and the
    legal alternatives."""
    problems: list[str] = []

    for ap, missing in sorted(unknown_keys(spec, schema_keys).items()):
        problems.append(
            f"atomic proposition '{ap}' references sensor field(s) "
            f"{sorted(missing)} which this robot does not provide; "
            f"available fields are: {sorted(schema_keys)}"
        )

    return problems + validate_structure(spec)
