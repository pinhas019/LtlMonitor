"""The flattened control (E1): the same skill with its order removed and nothing else."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from skill_monitor.core import spec_ablation
from skill_monitor.core.spec_ablation import FLAT_PHASE, flatten, to_ltl

SPECS = Path(__file__).resolve().parents[1] / "skill_monitor/specs"


def g1_spec():
    return json.loads((SPECS / "formulas_g1.json").read_text(encoding="utf-8"))


def three_phases():
    phase = {"precondition": "True", "precondition_fault_category": "NONE",
             "progress_violation_limit": 3}
    return {
        "skill_name": "Fetch", "description": "fetch it",
        "atomic_propositions": {k: f"True when {k} == True." for k in
                                ("a", "b", "c", "safe", "dry", "stuck", "done")},
        "ltl_formulas": [{"name": "order", "formula": "F(a && F(b && F(c)))"}],
        "named_failure_modes": [{"name": "unsafe", "formula": "G(safe)",
                                 "fault_category": "SAFETY", "description": "x"}],
        "execution_phases": [
            {**phase, "phase": "A", "enter_condition": "a", "invariant": "safe",
             "invariant_fault_category": "SAFETY", "progress_condition": "not stuck",
             "exit_condition": "b", "timing_bounds": {"max_steps": 10}},
            {**phase, "phase": "B", "enter_condition": "b", "invariant": "dry",
             "invariant_fault_category": "PROGRESS", "progress_condition": "a or b",
             "exit_condition": "c", "timing_bounds": {"max_steps": 20},
             "progress_violation_limit": 7},
            {**phase, "phase": "C", "enter_condition": "c", "invariant": "safe",
             "invariant_fault_category": "INVARIANT", "progress_condition": "True",
             "exit_condition": "done", "timing_bounds": {"max_steps": 5}},
        ],
        "terminal_success": {"condition": "done and not stuck", "description": "ok"},
        "terminal_failure": {"condition": "stuck", "description": "stuck"},
    }


def test_the_phases_collapse_into_one():
    (phase,) = flatten(three_phases())["execution_phases"]
    assert phase["phase"] == FLAT_PHASE
    assert phase["enter_condition"] == "a"
    assert phase["progress_condition"] == "True"
    assert phase["exit_condition"] == "done and not stuck"
    assert phase["timing_bounds"] == {"max_steps": 35}
    assert phase["progress_violation_limit"] == 7


def test_the_invariant_is_every_phases_conjoined_once_at_the_worst_category():
    (phase,) = flatten(three_phases())["execution_phases"]
    assert phase["invariant"] == "(safe) and (dry)"
    assert phase["invariant_fault_category"] == "SAFETY"


def test_the_ordered_chain_becomes_eventual_completion():
    assert flatten(three_phases())["ltl_formulas"] == [
        {"name": "eventual_completion", "formula": "F(done && ! stuck)"}]


def test_everything_but_the_structure_is_kept():
    spec, flat = three_phases(), flatten(three_phases())
    for key in ("skill_name", "atomic_propositions", "named_failure_modes",
                "terminal_success", "terminal_failure"):
        assert flat[key] == spec[key], key


def test_the_input_is_not_modified():
    spec = three_phases()
    before = copy.deepcopy(spec)
    flatten(spec, keep_terminal_failure=False)
    assert spec == before


def test_the_stricter_reading_drops_the_terminal_failure():
    flat = flatten(three_phases(), keep_terminal_failure=False)
    assert "terminal_failure" not in flat
    assert "no terminal failure" in flat["description"]


def test_a_missing_budget_leaves_the_flat_phase_unbounded_rather_than_guessing():
    spec = three_phases()
    del spec["execution_phases"][1]["timing_bounds"]
    assert flatten(spec)["execution_phases"][0]["timing_bounds"] == {}


def test_without_a_terminal_success_the_last_exit_ends_it():
    spec = three_phases()
    del spec["terminal_success"]
    assert flatten(spec)["execution_phases"][0]["exit_condition"] == "done"


def test_a_spec_without_phases_cannot_be_flattened():
    with pytest.raises(ValueError):
        flatten({"ltl_formulas": []})


@pytest.mark.parametrize("condition,ltl", [
    ("a and not b", "a && ! b"), ("a or (b and c)", "a || (b && c)"),
    ("True", "true"), ("anderson and nothing", "anderson && nothing"),
])
def test_conditions_translate_to_ltl_by_whole_words(condition, ltl):
    assert to_ltl(condition) == ltl


def test_the_flattened_g1_spec_passes_the_monitors_load_gate():
    flat = flatten(g1_spec())
    assert spec_ablation.problems(flat) == []
    import ros_stub
    if ros_stub.real_ros_present():
        pytest.skip("a real rclpy is installed; this test drives the stub")
    ros_stub.install()
    from skill_monitor.backend import monitor_node
    parsed = monitor_node.spec_from_dict(flat)
    assert [p["phase"] for p in parsed.execution_phases] == [FLAT_PHASE]
    assert parsed.formulas == ["F(at_goal && visually_at_goal)"]


def test_the_cli_writes_a_valid_spec_and_refuses_a_broken_one(tmp_path, capsys):
    src, out = tmp_path / "full.json", tmp_path / "flat.json"
    src.write_text(json.dumps(three_phases()), encoding="utf-8")
    assert spec_ablation.main([str(src), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["execution_phases"][0]["phase"] \
        == FLAT_PHASE

    broken = three_phases()
    broken["execution_phases"][0]["invariant"] = "safe and ghost"
    src.write_text(json.dumps(broken), encoding="utf-8")
    out.unlink()
    assert spec_ablation.main([str(src), "--out", str(out)]) == 1
    assert "ghost" in capsys.readouterr().out and not out.exists()
