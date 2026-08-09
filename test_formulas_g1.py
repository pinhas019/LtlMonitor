"""Structural validation of the G1 nav specs (sim + real) — no ROS/spot needed.

Catches the common authoring bug: a formula/phase/terminal referencing an atomic
proposition that was never declared. Parametrized over both formulas_g1.json
(Isaac Lab sim + Nav2) and formulas_g1_real.json (real robot, no Nav2/lidar) rather
than duplicating this file per spec.
Run: python3 -m pytest test_formulas_g1.py
"""

import json
import re
from pathlib import Path

import pytest

_SPEC_FILES = ["formulas_g1.json", "formulas_g1_real.json"]
_SPECS = {
    name: json.loads((Path(__file__).parent / name).read_text()) for name in _SPEC_FILES
}

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


def _referenced_aps(spec: dict) -> set[str]:
    refs: set[str] = set()
    for f in spec["ltl_formulas"]:
        refs |= _aps_in(f["formula"])
    for fm in spec.get("named_failure_modes", []):
        refs |= _aps_in(fm["formula"])
    for ph in spec.get("execution_phases", []):
        for key in (
            "enter_condition",
            "precondition",
            "invariant",
            "progress_condition",
            "exit_condition",
        ):
            refs |= _aps_in(ph.get(key, ""))
    for key in ("terminal_success", "terminal_failure"):
        refs |= _aps_in(spec.get(key, {}).get("condition", ""))
    return refs


@pytest.mark.parametrize("spec_name", _SPEC_FILES)
def test_all_referenced_aps_are_declared(spec_name):
    spec = _SPECS[spec_name]
    declared = set(spec["atomic_propositions"])
    missing = _referenced_aps(spec) - declared
    assert not missing, f"{spec_name}: formulas reference undeclared APs: {sorted(missing)}"


@pytest.mark.parametrize("spec_name", _SPEC_FILES)
def test_humanoid_properties_present(spec_name):
    spec = _SPECS[spec_name]
    assert "upright" in spec["atomic_propositions"]
    names = {fm["name"] for fm in spec["named_failure_modes"]}
    assert "fell_over" in names and "collision_imminent" in names
    # fall + collision are SAFETY faults (drive the intervention supervisor)
    for fm in spec["named_failure_modes"]:
        if fm["name"] in ("fell_over", "collision_imminent"):
            assert fm["fault_category"] == "SAFETY"


@pytest.mark.parametrize("spec_name", _SPEC_FILES)
def test_rule_aps_are_plain_comparisons(spec_name):
    # every AP must be a rule AP ("True when …") so no LLM is needed for G1 nav
    spec = _SPECS[spec_name]
    for name, desc in spec["atomic_propositions"].items():
        assert re.search(r"[Tt]rue when", desc), f"{spec_name}: AP {name} is not rule-based"
