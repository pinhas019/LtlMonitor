"""Structural validation of formulas_g1.json — no ROS/spot needed.

Catches the common authoring bug: a formula/phase/terminal referencing an atomic
proposition that was never declared. Run: python3 -m pytest test_formulas_g1.py
"""

import json
import re
from pathlib import Path

SPEC = json.loads((Path(__file__).parent / "formulas_g1.json").read_text())

# LTL temporal operators + python logical tokens that are NOT atomic propositions.
_NON_APS = {
    "F",
    "G",
    "X",
    "U",
    "W",
    "R",
    "and",
    "or",
    "not",
    "True",
    "False",
    "in",
    "None",
}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _aps_in(expr) -> set[str]:
    if not expr:
        return set()
    return {t for t in _IDENT.findall(expr) if t not in _NON_APS}


def _referenced_aps() -> set[str]:
    refs: set[str] = set()
    for f in SPEC["ltl_formulas"]:
        refs |= _aps_in(f["formula"])
    for fm in SPEC.get("named_failure_modes", []):
        refs |= _aps_in(fm["formula"])
    for ph in SPEC.get("execution_phases", []):
        for key in (
            "enter_condition",
            "precondition",
            "invariant",
            "progress_condition",
            "exit_condition",
        ):
            refs |= _aps_in(ph.get(key, ""))
    for key in ("terminal_success", "terminal_failure"):
        refs |= _aps_in(SPEC.get(key, {}).get("condition", ""))
    return refs


def test_all_referenced_aps_are_declared():
    declared = set(SPEC["atomic_propositions"])
    missing = _referenced_aps() - declared
    assert not missing, f"formulas reference undeclared APs: {sorted(missing)}"


def test_humanoid_properties_present():
    assert "upright" in SPEC["atomic_propositions"]
    names = {fm["name"] for fm in SPEC["named_failure_modes"]}
    assert "fell_over" in names and "collision_imminent" in names
    # fall + collision are SAFETY faults (drive the intervention supervisor)
    for fm in SPEC["named_failure_modes"]:
        if fm["name"] in ("fell_over", "collision_imminent"):
            assert fm["fault_category"] == "SAFETY"


def test_rule_aps_are_plain_comparisons():
    # every AP must be a rule AP ("True when …") so no LLM is needed for G1 nav
    for name, desc in SPEC["atomic_propositions"].items():
        assert re.search(r"[Tt]rue when", desc), f"AP {name} is not rule-based"
