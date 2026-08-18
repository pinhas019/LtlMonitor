"""The monitor's pure half.

What a client can rely on finding in a manifest, that a pushed spec is judged before it
is run, and -- the part `monitor_node` cannot be tested for directly, because it needs
`rclpy` -- that one tick produces exactly one verdict, that the verdict validates
against the contract it claims to implement, and that a failure mode nobody is sure
about does not actuate the robot.
"""

import json

import pytest

import skill_monitor
from skill_monitor.core import api, manifest, spec_contract
from skill_monitor.core.monitor_action import Action


def _spec():
    return json.loads(skill_monitor.spec_path("g1").read_text())


def _verdict(**overrides):
    """A verdict with the boring fields filled in, so each test states only its point."""
    kwargs = dict(
        seq=1041, t=1041.0, step=88,
        skill_name="G1HumanoidNavigation",
        phase="ExecutionAndTracking", phase_index=1,
        formula_statuses=[("full_navigation_sequence", "INCONCLUSIVE")],
        failure_modes=[],
        confidence=1.0,
    )
    kwargs.update(overrides)
    return manifest.build_verdict_payload(**kwargs)


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


# =============================================================================
# The manifest is `api`'s, not a second copy of it
# =============================================================================

def test_manifest_delegates_to_the_contract_module():
    """P0 reimplemented `skill_manifest`/`phase_names` in `api` rather than importing
    them, to avoid depending on a file another branch was editing. Two copies of "what
    is a phase called" is one too many, so this module now delegates."""
    raw = _spec()
    assert manifest.skill_manifest(raw, "x") == api.build_skill_manifest(spec=raw, source="x")
    assert manifest.phase_names is api.phase_names
    # …and the envelope comes with it, which the hand-rolled copy never carried.
    assert manifest.skill_manifest(raw)["schema_version"] == api.SCHEMA_VERSION


# =============================================================================
# Where the spec comes from  (P8: compose passes a bare name, not a path)
# =============================================================================

def test_a_bare_spec_name_resolves_through_the_config_search_path(tmp_path, monkeypatch):
    """The compose files pass `--formulas-file formulas_g1.json`. Treating that as a
    plain relative path makes a container fail to find a spec it was shipped with."""
    monkeypatch.delenv(skill_monitor.CONFIG_ENV, raising=False)
    skill_monitor.set_config_dir(None)
    assert manifest.resolve_spec_path("formulas_g1.json") == skill_monitor.spec_path("g1")
    assert manifest.resolve_spec_path("g1") == skill_monitor.spec_path("g1")

    # A mounted volume's spec of the same name wins…
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "formulas_g1.json").write_text("{}")
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(tmp_path))
    assert manifest.resolve_spec_path("formulas_g1.json") == specs / "formulas_g1.json"

    # …but an explicit path to a real file still wins over the search, so a developer
    # can point at a scratch spec anywhere on disk.
    scratch = tmp_path / "scratch.json"
    scratch.write_text("{}")
    assert manifest.resolve_spec_path(scratch) == scratch


def test_an_unresolvable_spec_name_says_where_it_looked():
    with pytest.raises(FileNotFoundError) as exc:
        manifest.resolve_spec_path("formulas_no_such_robot.json")
    assert "formulas_no_such_robot.json" in str(exc.value)


# =============================================================================
# Exactly one automaton step per tick
# =============================================================================

def test_one_step_per_seq():
    """A redelivered tick must not advance a debounce or a phase counter twice."""
    ledger = manifest.TickLedger()
    assert ledger.admit(10).step is True
    for _ in range(3):
        again = ledger.admit(10)
        assert again.step is False
        assert again.reason == "redelivered"
    assert ledger.admit(11).step is True
    assert ledger.redelivered == 3


def test_a_tick_older_than_the_last_one_is_refused_not_replayed():
    """Out of order, i.e. a tick the automaton has already moved past. It cannot be
    applied without rewinding state the automaton has no undo for."""
    ledger = manifest.TickLedger()
    ledger.admit(10)
    ledger.admit(11)
    stale = ledger.admit(9)
    assert stale.step is False and stale.reason == "stale"
    assert ledger.last_seq == 11


def test_missed_ticks_are_recorded_not_interpolated():
    """A gap is one number on one verdict, not a burst of catch-up steps."""
    ledger = manifest.TickLedger()
    ledger.admit(100)
    jumped = ledger.admit(104)
    assert jumped.step is True
    assert jumped.missed == 3            # 101, 102, 103
    assert ledger.total_missed == 3
    # One step, not four: the caller is handed a single admission and steps once.
    assert ledger.admit(105).missed == 0
    assert ledger.total_missed == 3


def test_a_payload_with_no_seq_keeps_the_legacy_arrival_behaviour():
    """Legacy `/ltl/evaluations` predates the envelope and carries no tick index. It
    gets the next implicit one, so the un-migrated stack still gets a verdict."""
    ledger = manifest.TickLedger()
    assert [ledger.admit(None).seq for _ in range(3)] == [0, 1, 2]
    assert ledger.admit(None).reason == "implicit"
    # `True` is an int in Python and is a bug where a seq belongs, not a tick index.
    assert manifest.TickLedger().admit(True).reason == "implicit"


def test_a_reset_does_not_make_a_stale_redelivery_look_fresh():
    """The episode restarts; the global tick stream does not restart with it."""
    ledger = manifest.TickLedger()
    ledger.admit(50)
    ledger.reset()
    assert ledger.admit(50).step is False


# =============================================================================
# One observation, either wire
# =============================================================================

def test_an_observation_reads_the_same_off_either_wire():
    modern = manifest.normalize_observation({
        "schema_version": 1, "seq": 7, "t": 7.0, "step": 3,
        "clock": "external", "tick_membership": "arrival",
        "sensors": {"min_range": 0.42},
        "ap_values": {"path_active": True, "collision_risk": False},
        "unknown_aps": ["blocked"],
        "confidence": 0.5,
        "data_health": {
            "points": {"refreshed": True}, "status": {"refreshed": False},
        },
    })
    assert modern.ap_values == {"path_active": True, "collision_risk": False}
    assert modern.sensors == {"min_range": 0.42}
    assert modern.seq == 7 and modern.step == 3 and modern.confidence == 0.5
    assert modern.stale_sources == ("status",)   # derived from data_health.refreshed
    assert modern.unknown_aps == ("blocked",)
    assert modern.legacy is False

    legacy = manifest.normalize_observation({
        "path_active": True, "collision_risk": False,
        "__sensors__": {"min_range": 0.42},
        "__confidence__": 0.5,
        "__stale__": ["status"],
    })
    assert legacy.ap_values == modern.ap_values
    assert legacy.sensors == modern.sensors
    assert legacy.confidence == modern.confidence
    assert legacy.stale_sources == modern.stale_sources
    assert legacy.seq is None and legacy.legacy is True


def test_reserved_keys_never_reach_the_automaton():
    """`__done__` and friends are metadata about the observation, not part of it: a
    phase guard's eval namespace must never see them."""
    obs = manifest.normalize_observation({"a": True, "__done__": True, "__reset__": True})
    assert obs.ap_values == {"a": True}
    assert obs.control == "done"        # done outranks reset
    assert manifest.normalize_observation({"__reset__": True}).control == "reset"
    assert manifest.normalize_observation("nonsense") is None
    assert manifest.normalize_observation(None) is None


def test_an_out_of_range_confidence_is_clamped_not_propagated():
    """`api.UNIT_INTERVAL` rejects 1.2, and a verdict that fails its own validator
    because a producer sent a stray number is the worse outcome."""
    assert manifest.normalize_observation({"__confidence__": 1.7}).confidence == 1.0
    assert manifest.normalize_observation({"__confidence__": -3}).confidence == 0.0
    assert manifest.normalize_observation({"__confidence__": "nan-ish"}).confidence == 1.0


# =============================================================================
# The verdict
# =============================================================================

def test_verdict_validates_against_api_schema():
    """The monitor's own payload, judged by the contract it claims to implement."""
    assert api.validate_verdict(_verdict()) == []
    # …in every shape the node can produce: idle, mid-phase, and terminal.
    assert api.validate_verdict(_verdict(
        phase=None, phase_index=None, formula_statuses=[], has_data=False,
    )) == []
    assert api.validate_verdict(_verdict(
        terminal="SUCCESS", missed_ticks=4, steps_to_timeout=0,
        violations_to_fault=1, violations_seen=2, stale_sources=["status"],
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
        confidence=0.2,
    )) == []


def test_verdict_carries_confidence_on_every_failure_mode():
    """Required, not optional. Without it a VIOLATED derived from a dead sensor grades
    at 1.0 and the intervention ladder goes straight to ABORT."""
    v = _verdict(
        confidence=0.4,
        failure_modes=[
            {"name": "fell_over", "fault_category": "SAFETY", "status": "VIOLATED"},
            {"name": "wandered", "fault_category": "PROGRESS", "status": "INCONCLUSIVE"},
        ],
    )
    assert [fm["confidence"] for fm in v["failure_modes"]] == [0.4, 0.4]
    assert all("confidence" in fm for fm in v["failure_modes"])


def test_low_confidence_safety_violation_grades_below_abort():
    """The live bug this closes: a `fell_over` derived from a sensor that stopped
    publishing used to grade at full confidence and abort the mission."""
    dead_sensor = _verdict(
        confidence=0.2, stale_sources=["imu"],
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert dead_sensor["intervention"]["action"] == "WARN"
    assert Action[dead_sensor["intervention"]["action"]] < Action.HALT

    # Safety is not softened away, only de-escalated while the evidence is weak: the
    # same fault on fresh data still aborts.
    live_sensor = _verdict(
        confidence=1.0,
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert live_sensor["intervention"]["action"] == "ABORT"


def test_the_intervention_token_ships_in_the_verdict():
    """The monitor decides the rung; the supervisor only enforces. A verdict with no
    token would leave the decision in the actuator, and unlogged."""
    quiet = _verdict()
    assert quiet["intervention"]["action"] == "CONTINUE"
    assert quiet["intervention"]["category"] is None

    # A phase about to time out is a pre-emptive rung, before any hard fault.
    soon = _verdict(steps_to_timeout=2, violations_to_fault=3, confidence=0.9)
    assert soon["risk"]["severity"] == "TIMEOUT"
    assert soon["intervention"]["action"] == "REPLAN"
    assert soon["intervention"]["imminence"] == "2 steps"
    assert soon["intervention"]["confidence"] == 0.9


def test_seconds_to_timeout_accompanies_steps_to_timeout():
    """Beside, never replacing: spec bounds stay tick-denominated until P11 and a
    consumer asserting on the existing field has to keep working."""
    at_1hz = _verdict(steps_to_timeout=32, tick_hz=1.0)["risk"]
    assert at_1hz["steps_to_timeout"] == 32
    assert at_1hz["seconds_to_timeout"] == 32.0

    # The same 32-tick budget is 6.4 seconds at 5 Hz — which is exactly why the two
    # numbers travel together rather than one being derived at the consumer.
    at_5hz = _verdict(steps_to_timeout=32, tick_hz=5.0)["risk"]
    assert at_5hz["steps_to_timeout"] == 32
    assert at_5hz["seconds_to_timeout"] == pytest.approx(6.4)

    no_bound = _verdict()["risk"]
    assert no_bound["steps_to_timeout"] is None
    assert no_bound["seconds_to_timeout"] is None


def test_missed_ticks_travel_on_the_verdict():
    assert _verdict()["missed_ticks"] == 0
    assert _verdict(missed_ticks=7)["missed_ticks"] == 7


# =============================================================================
# The two INCONCLUSIVEs are different axes
# =============================================================================

def test_no_data_is_a_different_axis_from_a_formula_being_inconclusive():
    """`MonitorStatus` is deliberately not extended. "The prefix neither proves nor
    refutes" is the normal state of a healthy run; "nothing arrived" is a statement
    about the sensors. Both travel, in different fields."""
    healthy = _verdict(has_data=True)
    assert healthy["verdict"] == "UNDECIDED"
    assert healthy["formulas"][0]["status"] == "INCONCLUSIVE"

    silent = _verdict(has_data=False)
    assert silent["verdict"] == "INCONCLUSIVE_NO_DATA"
    assert silent["formulas"][0]["status"] == "INCONCLUSIVE"   # unchanged by the silence
    assert set(api.FORMULA_STATUSES).isdisjoint({"INCONCLUSIVE_NO_DATA"})


def test_a_proven_violation_outranks_a_silent_tick():
    """It is already proven, and a later absence of data does not unprove it."""
    v = _verdict(has_data=False, formula_statuses=[("nav", "VIOLATED")])
    assert v["verdict"] == "VIOLATED"


def test_all_property_formulas_accepted_is_satisfied():
    v = _verdict(formula_statuses=[("a", "ACCEPTED"), ("b", "ACCEPTED")])
    assert v["verdict"] == "SATISFIED"
    # One straggler is enough to keep it undecided.
    assert _verdict(
        formula_statuses=[("a", "ACCEPTED"), ("b", "INCONCLUSIVE")]
    )["verdict"] == "UNDECIDED"


# =============================================================================
# Closed vocabularies
# =============================================================================

def test_an_authored_fault_category_is_mapped_onto_the_closed_vocabulary():
    """`fault_category` is closed on the wire, and specs author more names than it
    holds -- the shipped G1 spec has a `precondition_fault_category` of "NONE"."""
    assert manifest.wire_fault_category("SAFETY") == "SAFETY"
    assert manifest.wire_fault_category("precondition") == "INVARIANT"
    assert manifest.wire_fault_category("NONE") is None
    assert manifest.wire_fault_category(None) is None
    # Unclassifiable is not thereby mild.
    assert manifest.wire_fault_category("WEIRD") == manifest.UNCLASSIFIED_CATEGORY
    assert manifest.UNCLASSIFIED_CATEGORY in api.FAULT_CATEGORIES


def test_a_spec_with_odd_fault_categories_still_produces_a_valid_verdict():
    v = _verdict(failure_modes=[
        {"name": "unnamed", "fault_category": "UNKNOWN", "status": "VIOLATED"},
        {"name": "pre", "fault_category": "PRECONDITION", "status": "INCONCLUSIVE"},
    ])
    assert api.validate_verdict(v) == []
    assert [fm["fault_category"] for fm in v["failure_modes"]] == ["INVARIANT", "INVARIANT"]


def test_warn_steps_is_read_from_the_ladder_not_copied():
    """One definition of the horizon, not a fourth literal `3` in this module."""
    from skill_monitor.core.monitor_action import grade_action
    assert manifest.WARN_STEPS == grade_action.__kwdefaults__["warn_steps"]
    assert manifest.MIN_CONFIDENCE == grade_action.__kwdefaults__["min_confidence"]
