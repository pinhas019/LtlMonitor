"""The wire contract: what a client can rely on finding in a manifest, and that a
pushed spec is judged before it is run."""

import json

import skill_monitor
from skill_monitor.core import manifest, spec_contract


def _spec():
    return json.loads(skill_monitor.spec_path("g1").read_text())


def test_manifest_passes_the_spec_through_unchanged():
    raw = _spec()
    m = manifest.skill_manifest(raw, source="/tmp/formulas_g1.json")
    for k, v in raw.items():
        assert m[k] == v, f"manifest dropped or altered {k}"
    assert m["source"] == "/tmp/formulas_g1.json"
    assert json.loads(json.dumps(m)) == m       # must survive the wire


def test_manifest_names_the_phases_in_order():
    m = manifest.skill_manifest(_spec())
    expected = [p["phase"] for p in _spec()["execution_phases"]]
    assert m["phases"] == expected


def test_phase_names_tolerate_an_unnamed_phase():
    assert manifest.phase_names([{"phase": "A"}, {}]) == ["A", "phase1"]
    assert manifest.phase_names(None) == []


def test_ap_rows_distinguish_false_from_not_evaluated():
    m = {"atomic_propositions": {"a": "desc a", "b": "desc b"}}
    rows = manifest.ap_rows(m, {"ap_values": {"a": False}})
    assert rows == [("a", False, "desc a"), ("b", None, "desc b")]


def test_sensor_rows_come_from_the_adapter_schema():
    adapter = {"schema": {"min_range": {"doc": "metres"}, "nav_state": {"doc": "state"}}}
    rows = manifest.sensor_rows(adapter, {"sensors": {"min_range": 1.5}})
    assert rows == [("min_range", 1.5, "metres"), ("nav_state", None, "state")]

    # A robot with a completely different vocabulary renders with no code change.
    rows = manifest.sensor_rows({"schema": {"gripper_width": {"doc": "m"}}},
                                {"sensors": {"gripper_width": 0.02}})
    assert rows == [("gripper_width", 0.02, "m")]


def test_pushed_spec_is_rejected_for_fields_the_robot_lacks():
    bad = {
        "skill_name": "x",
        "atomic_propositions": {"holding": "True when gripper_force > 1.0. Prose."},
        "ltl_formulas": [{"formula": "G(holding)"}],
    }
    problems = spec_contract.validate(bad, ["min_range", "nav_state"])
    assert any("gripper_force" in p for p in problems)
    # …and accepted once the robot actually provides the field.
    assert spec_contract.validate(bad, ["gripper_force"]) == []


def test_structure_check_runs_without_a_schema():
    # No adapter on the graph yet: still catch a spec that references an AP it never
    # declared, which would silently evaluate as always-false.
    problems = spec_contract.validate_structure({
        "atomic_propositions": {"a": "prose"},
        "ltl_formulas": [{"formula": "G(a & ghost)"}],
    })
    assert any("ghost" in p for p in problems)
    assert spec_contract.validate_structure({}) != []
    assert spec_contract.validate_structure(_spec()) == []
