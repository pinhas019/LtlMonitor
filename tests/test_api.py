"""The wire contract's own tests.

Two jobs. The first is the ordinary one: every payload in docs/api.md round-trips
build -> validate -> JSON -> validate clean, every validator names the problem it
found, and no validator raises on anything at all.

The second is a guard for the whole team: `test_no_hardcoded_topic_literals` greps the
tree and fails the moment a file that is not `core/api.py` hardcodes a topic name. That
is what makes the `/ltl/*` -> `/monitor/*` rename a consequence of importing a constant
rather than a nine-branch sweep one branch forgets.
"""

from __future__ import annotations

import ast
import json
import pathlib
import warnings

import pytest

from skill_monitor.core import api

REPO = pathlib.Path(__file__).resolve().parents[1]


# =============================================================================
# Sample payloads -- one valid instance of every payload in docs/api.md
# =============================================================================

def a_tick() -> dict:
    # `t0` has no default, deliberately: a producer that omitted it would emit a frame
    # claiming the clock started at the epoch, and two such producers would be
    # indistinguishable -- the one thing the field exists to prevent.
    return api.build_tick(seq=1041, t=1041.0, tick_hz=1.0, mode="wall", t0=1700000000.0)


def an_observation() -> dict:
    return api.build_observation(
        seq=1041, t=1041.0, step=88,
        sensors={"min_range": 0.42, "nav_state": "following"},
        ap_values={"path_active": True, "collision_risk": False},
        unknown_aps=[],
        confidence=0.67,
        data_health={
            "points": {"rate_hz": 14.2, "expected_hz": 15.0, "age_s": 0.07,
                       "samples_this_tick": 14, "refreshed": True, "dropped": 0},
            "status": {"rate_hz": 0.0, "expected_hz": 5.0, "age_s": 3.9,
                       "samples_this_tick": 0, "refreshed": False, "dropped": 0},
        },
    )


def a_verdict() -> dict:
    return api.build_verdict(
        seq=1041, t=1041.0, step=88,
        skill_name="G1HumanoidNavigation",
        phase="ExecutionAndTracking", phase_index=1,
        verdict="UNDECIDED",
        formulas=[api.build_formula(name="full_navigation_sequence",
                                    status="INCONCLUSIVE")],
        failure_modes=[api.build_failure_mode(name="collision_imminent",
                                              fault_category="SAFETY",
                                              status="VIOLATED", confidence=0.67)],
        terminal=None,
        risk=api.build_risk(steps_to_timeout=32, seconds_to_timeout=32.0,
                            violations_to_fault=3, warn=False, severity=None,
                            trigger_confidence=0.67, stale_sources=["status"]),
        intervention=api.build_intervention(action="WARN", category="SAFETY",
                                            imminence=None, confidence=0.67),
        missed_ticks=0,
    )


def an_adapter() -> dict:
    return api.build_adapter(
        adapter="real_g1",
        doc="The real TRAV-metric-map G1.",
        tick_hz=1.0,
        warnings=[],
        schema={"min_range": {"doc": "float, metres", "default": 10.0}},
        sources=[{
            "id": "points", "topic": "/depth_anything/points",
            "type": "sensor_msgs/msg/PointCloud2",
            "expected_hz": 15.0, "max_age_s": 0.5,
            "required": True, "tracked": True,
            "keys": ["min_range"],
            # No `threshold`: it is optional on the wire, and this payload is the
            # older producer that proves it. docs/api.md's example is the same shape.
            "steps": [{"keys": ["min_range"], "aggregate": "min", "on": "message"}],
        }],
    )


A_SPEC = {
    "skill_name": "G1HumanoidNavigation",
    "atomic_propositions": {"path_active": "True when nav_state == 'following'."},
    "ltl_formulas": [{"name": "seq", "formula": "F(arrived)"}],
    "execution_phases": [{"phase": "Approach"}, {"phase": "ExecutionAndTracking"}],
}


def a_manifest() -> dict:
    return api.build_skill_manifest(spec=A_SPEC, source="pushed")


def a_command() -> dict:
    return api.build_command(command="reset")


def a_load_spec() -> dict:
    return api.build_load_spec(spec=A_SPEC, source="pushed")


def a_spec_status() -> dict:
    return api.build_spec_status(ok=False, problems=["'x' is not declared"],
                                 skill_name="G1HumanoidNavigation")


def a_raw_echo_request() -> dict:
    return api.build_raw_echo_request(source_id="points")


def a_raw_echo() -> dict:
    return api.build_raw_echo(seq=1041, t=1041.0, step=88, source_id="points",
                              summary={"count": 14, "min": 0.42})


# name -> (factory, validator, topic)
PAYLOADS = {
    "tick": (a_tick, api.validate_tick, api.TICK),
    "observation": (an_observation, api.validate_observation, api.OBSERVATION),
    "verdict": (a_verdict, api.validate_verdict, api.VERDICT),
    "adapter": (an_adapter, api.validate_adapter, api.ADAPTER),
    "manifest": (a_manifest, api.validate_skill_manifest, api.MANIFEST),
    "command": (a_command, api.validate_command, api.COMMAND),
    "load_spec": (a_load_spec, api.validate_load_spec, api.LOAD_SPEC),
    "spec_status": (a_spec_status, api.validate_spec_status, api.SPEC_STATUS),
    "raw_echo_request": (a_raw_echo_request, api.validate_raw_echo_request,
                         api.RAW_ECHO_REQUEST),
    "raw_echo": (a_raw_echo, api.validate_raw_echo, api.RAW_ECHO),
}

# Payloads whose validator is closed: an unknown field is a problem. The manifest is
# the deliberate exception -- it passes a spec through as authored, so it must carry
# fields this engine version has never heard of.
CLOSED = [name for name in PAYLOADS if name != "manifest"]

TICK_SCOPED = ("observation", "verdict", "raw_echo")


# =============================================================================
# Topic constants
# =============================================================================

def test_topic_constants_are_the_documented_names():
    assert api.TICK == "/monitor/tick"
    assert api.OBSERVATION == "/monitor/observation"
    assert api.VERDICT == "/monitor/verdict"
    assert api.ADAPTER == "/monitor/adapter"
    assert api.MANIFEST == "/monitor/manifest"
    assert api.COMMAND == "/monitor/command"
    assert api.LOAD_SPEC == "/monitor/load_spec"
    assert api.SPEC_STATUS == "/monitor/spec_status"
    assert api.RAW_ECHO_REQUEST == "/monitor/raw_echo_request"
    assert api.RAW_ECHO == "/monitor/raw_echo"


def test_topics_set_is_exactly_the_ten_constants():
    assert len(api.TOPICS) == 10
    assert all(t.startswith("/monitor/") for t in api.TOPICS)


def test_latched_topics_are_a_subset_of_declared_topics():
    assert api.LATCHED_TOPICS <= api.TOPICS
    assert api.LATCHED_TOPICS == {api.ADAPTER, api.MANIFEST, api.SPEC_STATUS}


def test_every_topic_has_a_validator():
    assert set(api.VALIDATORS) == set(api.TOPICS)


# =============================================================================
# Round trips
# =============================================================================

@pytest.mark.parametrize("name", list(PAYLOADS))
def test_round_trip_through_json_is_clean(name):
    """build -> validate -> dumps -> loads -> validate, with no problems either side.

    The JSON hop is not ceremony: these payloads reach the frontend over a WebSocket
    and reach disk as recorded verdicts, so a builder emitting something json.dumps
    refuses is a real failure mode.
    """
    factory, validate, _ = PAYLOADS[name]
    payload = factory()
    assert validate(payload) == []
    revived = json.loads(json.dumps(payload))
    assert validate(revived) == []
    assert revived == payload


@pytest.mark.parametrize("name", list(PAYLOADS))
def test_builders_fill_the_envelope(name):
    factory, _, _ = PAYLOADS[name]
    payload = factory()
    assert payload["schema_version"] == api.SCHEMA_VERSION


@pytest.mark.parametrize("name", TICK_SCOPED)
def test_tick_scoped_payloads_carry_seq_and_step(name):
    payload = PAYLOADS[name][0]()
    assert payload["seq"] == 1041
    assert payload["t"] == 1041.0
    assert payload["step"] == 88


def test_tick_carries_seq_but_not_step():
    """The clock has no notion of an episode: `arm`/`reset` go to the monitor."""
    payload = a_tick()
    assert payload["seq"] == 1041
    assert "step" not in payload


@pytest.mark.parametrize("name", ["adapter", "manifest", "command", "load_spec",
                                  "spec_status", "raw_echo_request"])
def test_untick_scoped_payloads_omit_step(name):
    assert "step" not in PAYLOADS[name][0]()


def test_builders_reject_positional_arguments():
    """Keyword-only, so a caller cannot swap seq and t and get a valid-looking frame."""
    with pytest.raises(TypeError):
        api.build_tick(1041, 1041.0, 1.0, "wall")
    with pytest.raises(TypeError):
        api.build_command("reset")


# =============================================================================
# Missing and unknown fields
# =============================================================================

# The manifest's other keys are the pass-through spec, which the contract does not
# require: only these four are the manifest's own.
REQUIRED_FIELDS = {"manifest": ("schema_version", "skill_name", "phases", "source")}

# Fields a builder always emits but a validator tolerates absent, because they landed
# after SCHEMA_VERSION 1 and requiring them would invalidate every producer that
# predates them with no version bump to make the mismatch detectable. Declared but not
# required -- the pairing that has to be spelled out somewhere, and this is where.
OPTIONAL_FIELDS = {"verdict": ("phase_guards",)}


@pytest.mark.parametrize("name", list(PAYLOADS))
def test_a_missing_required_field_is_named(name):
    factory, validate, _ = PAYLOADS[name]
    template = factory()
    tolerated = OPTIONAL_FIELDS.get(name, ())
    for field in REQUIRED_FIELDS.get(name, tuple(template)):
        if field in tolerated:
            continue
        payload = {k: v for k, v in template.items() if k != field}
        problems = validate(payload)
        assert any(f"'{field}'" in p and "missing" in p for p in problems), (
            f"dropping {name}.{field} produced {problems}"
        )


@pytest.mark.parametrize("name", CLOSED)
def test_an_unknown_field_is_named(name):
    factory, validate, _ = PAYLOADS[name]
    payload = factory() | {"nonesuch": 1}
    problems = validate(payload)
    assert any("nonesuch" in p and "unknown" in p for p in problems), problems


def test_the_manifest_tolerates_fields_this_engine_does_not_understand():
    """A client must see the document the engine was given, not a reprojection of it."""
    payload = api.build_skill_manifest(
        spec=A_SPEC | {"invented_by_a_future_version": {"x": 1}}, source="pushed"
    )
    assert api.validate_skill_manifest(payload) == []
    assert payload["invented_by_a_future_version"] == {"x": 1}


def test_the_manifest_passes_the_spec_through_and_adds_phases():
    payload = a_manifest()
    assert payload["atomic_propositions"] == A_SPEC["atomic_propositions"]
    assert payload["phases"] == ["Approach", "ExecutionAndTracking"]
    assert payload["source"] == "pushed"


def test_a_spec_cannot_overwrite_the_envelope():
    """Otherwise a spec authored with its own schema_version misroutes every consumer."""
    payload = api.build_skill_manifest(spec=A_SPEC | {"schema_version": 99})
    assert payload["schema_version"] == api.SCHEMA_VERSION


# =============================================================================
# Validators are total
# =============================================================================

JUNK = [None, [], {}, "", "a string", 0, 1.5, True, ["a", "list"], {"seq": None},
        {"schema_version": "one"}, [{"nested": "list"}], object()]


@pytest.mark.parametrize("validate", sorted(api.VALIDATORS.values(),
                                            key=lambda f: f.__name__))
@pytest.mark.parametrize("junk", JUNK)
def test_validators_never_raise(validate, junk):
    problems = validate(junk)
    assert isinstance(problems, list)
    assert all(isinstance(p, str) for p in problems)


@pytest.mark.parametrize("junk", [None, [], "a string", 7])
def test_a_non_object_payload_is_reported_not_crashed(junk):
    problems = api.validate_verdict(junk)
    assert len(problems) == 1
    assert "must be an object" in problems[0]


def test_validate_for_topic_dispatches():
    assert api.validate_for_topic(api.VERDICT, a_verdict()) == []
    assert api.validate_for_topic(api.VERDICT, None) != []


def test_an_unknown_topic_is_a_problem_not_a_pass():
    problems = api.validate_for_topic("/ltl/state_description", {})
    assert len(problems) == 1
    assert "unknown topic" in problems[0]


# =============================================================================
# Type and vocabulary checks
# =============================================================================

def test_a_wrong_type_names_the_field_and_what_was_expected():
    problems = api.validate_tick(a_tick() | {"seq": "1041"})
    assert any("'seq'" in p and "an int" in p and "a string" in p for p in problems)


def test_a_bool_is_not_an_int():
    """`True` where a seq belongs is a bug worth reporting, not a 1 worth accepting."""
    assert api.validate_tick(a_tick() | {"seq": True}) != []


def test_an_unknown_clock_mode_is_rejected():
    problems = api.validate_tick(a_tick() | {"mode": "turbo"})
    assert any("'mode'" in p for p in problems)


def test_an_unknown_verdict_is_rejected():
    assert api.validate_verdict(a_verdict() | {"verdict": "MAYBE"}) != []


def test_an_unknown_intervention_rung_is_rejected():
    payload = a_verdict()
    payload["intervention"]["action"] = "PANIC"
    assert any("'action'" in p for p in api.validate_verdict(payload))


def test_a_failure_mode_without_confidence_is_rejected():
    """Without it a VIOLATED derived from a dead sensor grades at 1.0 and the ladder
    goes straight to ABORT."""
    payload = a_verdict()
    del payload["failure_modes"][0]["confidence"]
    assert any("confidence" in p and "missing" in p
               for p in api.validate_verdict(payload))


def test_seconds_to_timeout_ships_beside_steps_to_timeout_not_instead_of_it():
    payload = a_verdict()
    del payload["risk"]["steps_to_timeout"]
    assert any("steps_to_timeout" in p for p in api.validate_verdict(payload))


def test_confidence_outside_the_unit_interval_is_rejected():
    assert api.validate_observation(an_observation() | {"confidence": 1.4}) != []
    assert api.validate_observation(an_observation() | {"confidence": -0.1}) != []


def test_ap_values_are_booleans_only():
    """UNKNOWN never appears here; an unevaluated AP names itself in unknown_aps."""
    payload = an_observation()
    payload["ap_values"]["path_active"] = "UNKNOWN"
    assert any("ap_values" in p for p in api.validate_observation(payload))


def test_an_ap_cannot_be_both_evaluated_and_unknown():
    payload = an_observation()
    payload["unknown_aps"] = ["path_active"]
    assert any("path_active" in p for p in api.validate_observation(payload))


def test_a_data_health_entry_missing_a_field_is_named():
    payload = an_observation()
    del payload["data_health"]["points"]["dropped"]
    problems = api.validate_observation(payload)
    assert any("points" in p and "dropped" in p for p in problems)


def test_an_adapter_source_feeding_an_undeclared_key_is_reported():
    payload = an_adapter()
    payload["sources"][0]["keys"] = ["min_range", "ghost_field"]
    assert any("ghost_field" in p for p in api.validate_adapter(payload))


def test_an_adapter_step_missing_its_aggregate_is_named():
    payload = an_adapter()
    del payload["sources"][0]["steps"][0]["aggregate"]
    problems = api.validate_adapter(payload)
    assert any("steps[0]" in p and "aggregate" in p for p in problems)


def test_a_step_may_omit_threshold_but_not_mistype_it():
    """`threshold` was added after SCHEMA_VERSION 1 shipped. Required would have been
    a wire break: every producer that predates it -- including docs/api.md's own
    example -- becomes invalid, with no version bump to make the mismatch detectable."""
    payload = an_adapter()
    assert "threshold" not in payload["sources"][0]["steps"][0]
    assert api.validate_adapter(payload) == []

    payload["sources"][0]["steps"][0]["threshold"] = 10
    assert api.validate_adapter(payload) == []
    payload["sources"][0]["steps"][0]["threshold"] = None
    assert api.validate_adapter(payload) == []

    payload["sources"][0]["steps"][0]["threshold"] = "ten"
    problems = api.validate_adapter(payload)
    assert any("steps[0]" in p and "threshold" in p for p in problems), problems


def test_the_adapter_example_in_the_wire_doc_still_validates():
    """docs/api.md IS the wire contract as an integrator reads it. An example the
    validator rejects means the doc and the code disagree about the payload, and the
    doc is what someone writes a producer against."""
    import re

    doc = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "api.md").read_text()
    section = doc[doc.index("## `/monitor/adapter`"):]
    block = re.search(r"```json\n(.*?)\n```", section, re.S)
    assert block, "the /monitor/adapter section lost its example"
    assert api.validate_adapter(json.loads(block.group(1))) == []


# =============================================================================
# The automaton graph: `manifest.automata` + `state` on both verdict row types
#
# The split is the whole design. The graph is structural and changes only when a spec
# loads, so it rides the latched manifest at one message per spec; the tick then
# carries a single small integer that indexes into it. These tests pin both halves and,
# just as importantly, pin what a producer that has neither is still allowed to send.
# =============================================================================

def an_automaton() -> dict:
    """One entry of `manifest.automata` -- the shape `LTLMonitor.graph()` emits."""
    return {
        "name": "full_navigation_sequence",
        "formula": "F(mission_started && F(path_active))",
        "initial": 0,
        "states": [
            {"id": 0, "accepting": False, "sink": False},
            {"id": 1, "accepting": False, "sink": False},
            {"id": 2, "accepting": True, "sink": False},
        ],
        "edges": [
            {"from": 0, "to": 1, "label": "mission_started"},
            {"from": 1, "to": 2, "label": "path_active"},
            {"from": 2, "to": 2, "label": "1"},
        ],
    }


def test_a_manifest_carrying_an_automaton_graph_validates():
    payload = api.build_skill_manifest(spec=A_SPEC, source="pushed",
                                       automata=[an_automaton()])
    assert api.validate_skill_manifest(payload) == []
    assert payload["automata"] == [an_automaton()]
    # And it survives the wire, which is the only form the frontend ever sees it in.
    assert api.validate_skill_manifest(json.loads(json.dumps(payload))) == []


def test_a_manifest_with_no_graph_omits_automata_rather_than_emptying_it():
    """The degrade path, and the reason it is an absence and not `[]`.

    A producer that cannot introspect its monitors and a spec that declares none are
    different facts. An empty list asserts the second, so a console would draw an empty
    automaton pane and call it the truth. Absent says "I cannot tell you", which is what
    a consumer needs to leave the pane alone.
    """
    payload = api.build_skill_manifest(spec=A_SPEC, source="pushed", automata=None)
    assert "automata" not in payload
    assert api.validate_skill_manifest(payload) == []


def test_a_mistyped_automata_block_is_named():
    payload = api.build_skill_manifest(spec=A_SPEC, source="pushed")
    payload["automata"] = "a graph, honest"
    assert any("automata" in p for p in api.validate_skill_manifest(payload))


def test_an_automaton_missing_a_structural_field_is_named():
    graph = an_automaton()
    del graph["initial"]
    problems = api.validate_automata([graph])
    assert any("automata[0]" in p and "initial" in p for p in problems), problems


def test_a_duplicate_state_id_is_named():
    """`verdict.formulas[].state` is nothing but a state id. Two states answering to
    the same number makes "the monitor is in state 1" ambiguous on the wire."""
    graph = an_automaton()
    graph["states"].append({"id": 1, "accepting": True, "sink": False})
    problems = api.validate_automata([graph])
    assert any("duplicate state id 1" in p for p in problems), problems


def test_an_initial_state_that_was_never_declared_is_named():
    """Well-typed nonsense: every field passes its own check and the graph still has
    no node to start at. Caught here rather than as a pane that renders blank."""
    graph = an_automaton()
    graph["initial"] = 7
    problems = api.validate_automata([graph])
    assert any("initial state 7 is not a declared state" in p for p in problems), problems


def test_an_edge_endpoint_that_was_never_declared_is_named():
    graph = an_automaton()
    graph["edges"].append({"from": 2, "to": 9, "label": "ghost"})
    problems = api.validate_automata([graph])
    assert any("edges[3]" in p and "'to' state 9" in p for p in problems), problems

    graph = an_automaton()
    graph["edges"][0]["from"] = 42
    problems = api.validate_automata([graph])
    assert any("edges[0]" in p and "'from' state 42" in p for p in problems), problems


def test_a_malformed_graph_fails_the_manifest_it_rides_on():
    """The validator is only worth having if the payload's own validator runs it."""
    graph = an_automaton()
    graph["initial"] = 7
    payload = api.build_skill_manifest(spec=A_SPEC, automata=[graph])
    assert any("initial state 7" in p for p in api.validate_skill_manifest(payload))


@pytest.mark.parametrize(
    "garbage", [None, "nonsense", 7, [None], ["nonsense"], [{}], [[]], {}],
)
def test_validate_automata_never_raises(garbage):
    """Same rule as every other validator here: a consumer handed a malformed frame
    must be able to report it, not die on it."""
    assert isinstance(api.validate_automata(garbage), list)


def test_a_formula_row_carries_the_state_it_is_in():
    payload = a_verdict()
    payload["formulas"] = [api.build_formula(
        name="full_navigation_sequence", status="INCONCLUSIVE", state=1)]
    assert api.validate_verdict(payload) == []
    assert payload["formulas"][0]["state"] == 1


def test_a_failure_mode_row_carries_the_state_it_is_in():
    payload = a_verdict()
    payload["failure_modes"] = [api.build_failure_mode(
        name="collision_imminent", fault_category="SAFETY", status="VIOLATED",
        confidence=0.67, state=3)]
    assert api.validate_verdict(payload) == []
    assert payload["failure_modes"][0]["state"] == 3


@pytest.mark.parametrize("rows", ["formulas", "failure_modes"])
def test_a_state_that_is_not_an_int_is_rejected(rows):
    """A string state indexes nothing. `null` is the contract's word for "I cannot
    report one" -- a stringly-typed 1 is a producer bug, not a degraded producer."""
    payload = a_verdict()
    payload[rows][0]["state"] = "1"
    problems = api.validate_verdict(payload)
    assert any(rows in p and "state" in p for p in problems), problems

    payload[rows][0]["state"] = None
    assert api.validate_verdict(payload) == []


@pytest.mark.parametrize("rows", ["formulas", "failure_modes"])
def test_a_row_may_omit_state_entirely(rows):
    """`state` landed after SCHEMA_VERSION 1. Required would invalidate every producer
    that predates it -- with no version bump to make the mismatch detectable -- which
    is the same rule `threshold` follows on an adapter step."""
    payload = a_verdict()
    del payload[rows][0]["state"]
    assert api.validate_verdict(payload) == []


@pytest.mark.parametrize("rows", ["formulas", "failure_modes"])
def test_the_row_field_sets_stay_closed_around_state(rows):
    """`state` had to be *declared* precisely because these two are closed: an
    undeclared field is rejected outright, so a verdict carrying it would have been
    thrown out entirely rather than merely ignored."""
    payload = a_verdict()
    assert payload[rows][0]["state"] is None
    assert api.validate_verdict(payload) == [], "a declared field is not an unknown one"

    payload[rows][0]["stat"] = 1        # a typo, not a new field
    assert any("unknown field 'stat'" in p for p in api.validate_verdict(payload))


# =============================================================================
# `verdict.phase_guards` -- the evaluated truth of the active phase's guards
#
# The structural half of a phase already rides the latched manifest: its conditions,
# its `max_steps`, its violation limit. What a console cannot get from there is whether
# each condition holds *right now* -- and it must not work that out itself, because a
# second implementation of the expression evaluator is where this project's
# `min_range < 0.25` decimal-point bug lived three times. These tests pin the field the
# monitor publishes instead, and above all pin that its `null` survives: "we did not
# check" and "it does not hold" are different facts and one of them is a fault.
# =============================================================================

def _guarded(*guards, phase="PlanningAndInitiation") -> dict:
    """A verdict whose phase_guards block carries exactly `guards`."""
    return a_verdict() | {
        "phase_guards": api.build_phase_guards(phase=phase, guards=list(guards)),
    }


def test_a_verdict_carries_the_evaluated_truth_of_each_phase_guard():
    """The whole contract in one payload: which phase, which guards it declares, the
    expression as the spec authored it, and what the monitor computed for each."""
    payload = _guarded(
        api.build_phase_guard(name="enter_condition", expr="mission_started", value=True),
        api.build_phase_guard(name="invariant", expr="upright and not collision_risk",
                              value=True),
        api.build_phase_guard(name="progress_condition", expr="not nav_stuck", value=True),
        api.build_phase_guard(name="exit_condition", expr="path_active", value=False),
    )
    assert api.validate_verdict(payload) == []
    assert payload["phase_guards"]["phase"] == "PlanningAndInitiation"
    assert [g["name"] for g in payload["phase_guards"]["guards"]] == [
        "enter_condition", "invariant", "progress_condition", "exit_condition"
    ]
    # The expression is carried, not derived. The console shows the operator their own
    # words; it never parses them.
    assert payload["phase_guards"]["guards"][1]["expr"] == "upright and not collision_risk"
    assert json.loads(json.dumps(payload)) == payload


def test_a_guard_that_was_not_evaluated_is_null_and_never_false():
    """The load-bearing null. A guard the phase machine short-circuited past, or one
    whose expression read an AP in `unknown_aps`, has no truth value this tick. Spelling
    that `false` reports an invariant as breached that was never asked."""
    payload = _guarded(
        api.build_phase_guard(name="exit_condition", expr="path_active", value=None),
    )
    assert api.validate_verdict(payload) == []
    row = payload["phase_guards"]["guards"][0]
    assert row["value"] is None
    assert row["value"] is not False, "null and false are different facts"


def test_a_guard_row_defaults_to_not_evaluated():
    """`value` is the one field a builder may not guess at. A caller that has no answer
    gets `null` for free; a caller that computed one has to say so."""
    assert api.build_phase_guard(name="invariant", expr="upright")["value"] is None


def test_a_verdict_with_no_active_phase_carries_a_null_block():
    """Idle, done, or a producer with no phase machine at all. `null` for the whole
    block is the same absence `phase_index` reports, spelled the same way -- not an
    empty guard list, which would claim a phase is running and declares nothing."""
    payload = a_verdict()
    assert payload["phase_guards"] is None
    assert api.validate_verdict(payload) == []
    assert api.validate_verdict(a_verdict() | {"phase_guards": None}) == []


def test_a_verdict_may_omit_phase_guards_entirely():
    """It landed after SCHEMA_VERSION 1. Required would invalidate every producer that
    predates it with no version bump to make the mismatch detectable -- the same rule
    `state` and an adapter step's `threshold` already follow."""
    payload = a_verdict()
    del payload["phase_guards"]
    assert api.validate_verdict(payload) == []


def test_phase_guards_is_declared_so_it_is_not_an_unknown_field():
    """`_VERDICT_FIELDS` is closed. Undeclared, a verdict carrying the block would be
    thrown out whole rather than merely ignored -- so the pane's producer could not
    ship it at all."""
    payload = _guarded(
        api.build_phase_guard(name="invariant", expr="upright", value=True),
    )
    assert api.validate_verdict(payload) == []
    payload["phase_guard"] = payload["phase_guards"]      # a typo, not a new field
    assert any("unknown field 'phase_guard'" in p
               for p in api.validate_verdict(payload))


@pytest.mark.parametrize("value", ["true", 1, 0, "", [], {}])
def test_a_guard_value_that_is_not_a_bool_is_named(value):
    """A stringly-typed "true" is truthy in every consumer language there is. The one
    reading this field exists to prevent is a guard rendered as holding on evidence the
    monitor never produced."""
    payload = _guarded(
        api.build_phase_guard(name="invariant", expr="upright") | {"value": value},
    )
    problems = api.validate_verdict(payload)
    assert any("phase_guards" in p and "guards[0]" in p and "'value'" in p
               for p in problems), problems


def test_a_guard_name_outside_the_known_set_is_named():
    """The name is a row label a console renders. An unrecognised one is drawn as a
    guard nobody can name, so it is rejected at the edge instead."""
    payload = _guarded(
        api.build_phase_guard(name="postcondition", expr="arrived", value=True),
    )
    problems = api.validate_verdict(payload)
    assert any("guards[0]" in p and "'name'" in p for p in problems), problems
    for name in api.PHASE_GUARD_NAMES:
        assert api.validate_verdict(_guarded(
            api.build_phase_guard(name=name, expr="x", value=True)
        )) == []


def test_a_guard_with_no_expression_is_named():
    """`expr` is what the operator reads. A null one leaves a row labelled `invariant`
    with nothing beside it and no way to tell which condition it is about."""
    payload = _guarded(
        api.build_phase_guard(name="invariant", expr="upright") | {"expr": None},
    )
    assert any("guards[0]" in p and "'expr'" in p
               for p in api.validate_verdict(payload)), api.validate_verdict(payload)


def test_the_guard_rows_stay_closed():
    payload = _guarded(
        api.build_phase_guard(name="invariant", expr="upright", value=True)
        | {"valeu": True},
    )
    assert any("unknown field 'valeu'" in p for p in api.validate_verdict(payload))


@pytest.mark.parametrize("block", [[], "PlanningAndInitiation", 7, True])
def test_a_phase_guards_block_that_is_not_an_object_is_named(block):
    """The message has to say what was wrong with it, not merely that the field was
    involved -- "unknown field 'phase_guards'" would satisfy a looser assertion while
    meaning the contract never admitted the block at all."""
    payload = a_verdict() | {"phase_guards": block}
    problems = api.validate_verdict(payload)
    assert any("'phase_guards'" in p and "an object or null" in p
               for p in problems), problems


def test_a_phase_guards_block_missing_its_own_fields_is_named():
    for block, wanted in (({"guards": []}, "phase"), ({"phase": "P"}, "guards")):
        problems = api.validate_verdict(a_verdict() | {"phase_guards": block})
        assert any(f"'{wanted}'" in p and "missing" in p for p in problems), problems
    problems = api.validate_verdict(
        a_verdict() | {"phase_guards": {"phase": "P", "guards": "none"}}
    )
    assert any("'guards'" in p for p in problems), problems


def test_a_phase_guards_block_stays_closed():
    payload = a_verdict() | {
        "phase_guards": {"phase": "P", "guards": [], "phase_index": 1},
    }
    assert any("unknown field 'phase_index'" in p
               for p in api.validate_verdict(payload))


def test_the_builder_does_not_alias_the_block_it_is_handed():
    """`risk` and `intervention` are copied for the same reason: a caller that mutates
    its own dict after building must not retroactively edit a published frame."""
    block = api.build_phase_guards(phase="P", guards=[])
    payload = api.build_verdict(
        seq=1, t=1.0, step=1, skill_name="s", phase="P", phase_index=0,
        verdict="UNDECIDED", formulas=[], failure_modes=[],
        risk=api.build_risk(steps_to_timeout=None, seconds_to_timeout=None,
                            violations_to_fault=None, warn=False,
                            trigger_confidence=1.0),
        intervention=api.build_intervention(action="CONTINUE", confidence=1.0),
        phase_guards=block,
    )
    block["phase"] = "SomethingElse"
    assert payload["phase_guards"]["phase"] == "P"


def test_the_verdict_example_in_the_wire_doc_still_validates():
    """docs/api.md IS the wire contract as an integrator reads it, and the pane's author
    writes their consumer against that example. An example carrying a `phase_guards`
    block the validator rejects means the doc and the code disagree about the payload."""
    import re

    doc = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "api.md").read_text()
    section = doc[doc.index("## `/monitor/verdict`"):]
    block = re.search(r"```json\n(.*?)\n```", section, re.S)
    assert block, "the /monitor/verdict section lost its example"
    payload = json.loads(block.group(1))
    assert api.validate_verdict(payload) == []
    # …and the example is an example *of this field*: it shows both a real value and the
    # null, because a doc that only ever showed `true`/`false` would teach the one
    # reading the field exists to prevent.
    values = [g["value"] for g in payload["phase_guards"]["guards"]]
    assert None in values and True in values and False in values


def test_an_unknown_command_is_rejected():
    assert api.validate_command(a_command() | {"command": "launch"}) != []
    for command in api.COMMANDS:
        assert api.validate_command(api.build_command(command=command)) == []


def test_spec_status_cannot_be_ok_and_have_problems():
    payload = api.build_spec_status(ok=True, problems=["something"], skill_name="s")
    assert any("ok is true" in p for p in api.validate_spec_status(payload))


def test_a_raw_echo_request_may_stop_the_echo():
    payload = api.build_raw_echo_request(source_id=None)
    assert api.validate_raw_echo_request(payload) == []
    assert payload["source_id"] is None


def test_step_may_be_null_when_no_episode_is_armed():
    payload = api.build_observation(
        seq=1, t=1.0, step=None, sensors={}, ap_values={}, confidence=0.0,
        data_health={},
    )
    assert api.validate_observation(payload) == []


def test_a_plain_payload_may_carry_seq_but_must_not_require_it():
    with_seq = api.build_command(command="arm", seq=7, t=7.0)
    assert api.validate_command(with_seq) == []
    assert with_seq["seq"] == 7
    assert api.validate_command(api.build_command(command="arm")) == []


def test_a_payload_from_a_future_schema_version_is_reported():
    assert any("schema_version" in p
               for p in api.validate_tick(a_tick() | {"schema_version": 99}))


# =============================================================================
# The module is pure
# =============================================================================

def test_api_imports_no_ros():
    """core/ must be importable on a laptop with no ROS: the spec generator, the
    contract oracle and every unit test depend on it."""
    source = (REPO / "skill_monitor" / "core" / "api.py").read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"rclpy", "std_msgs", "rosidl_runtime_py", "spot"}, imported


# =============================================================================
# No stray topic literals anywhere else in the tree
# =============================================================================

# Files that still hardcode `/ltl/*` because the rename has not happened yet. Each is
# owned by a package that will land later and replace the literal with an `api.*`
# constant.
#
#   THIS LIST MUST SHRINK TO EMPTY. Delete an entry the moment its package lands;
#   an empty list is the end state, and this comment goes with it.
#
# The list is here rather than "just skip backend/" on purpose: a NEW hardcoded topic
# in any file not named below fails immediately, which is the entire point.
AWAITING_MIGRATION = {
    "skill_monitor/backend/evaluator_node.py",        # P3 -- feat-evaluator-tick
    "skill_monitor/backend/monitor_node.py",          # P4 -- feat-verdict-topic
    "skill_monitor/backend/intervention_supervisor.py",  # P5 -- refactor-supervisor-token
    "skill_monitor/frontend/skill_center.py",         # P7 -- feat-observation-panel
}

# The two files that are allowed to name topics forever: api.py declares them, and
# this file pins the declared values.
DECLARATION_SITES = {
    "skill_monitor/core/api.py",
    "tests/test_api.py",
}

SCANNED = ("skill_monitor", "tests", "sim")


def _topic_literals(path: pathlib.Path) -> list[tuple[int, str]]:
    """String literals in `path` that name a monitor topic, docstrings excluded.

    Docstrings are excluded because prose describing the wire is not a wire
    dependency: renaming a topic does not require the docstring to change to keep the
    code correct, and the docs are P9's to update. Everything else -- including a help
    string a user copies and pastes -- counts.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for needle in ("monitor/", "ltl/"):
            idx = node.value.find(needle)
            # The segment must start at a boundary, so `ltl_formulas` (a spec field)
            # and `/api/monitors/{ns}` (a gateway route) do not trip the check.
            while idx != -1:
                if idx == 0 or node.value[idx - 1] == "/":
                    start = idx - 1 if idx else idx
                    found.append((node.lineno, node.value[start:start + 40]))
                    break
                idx = node.value.find(needle, idx + 1)
    return found


def _python_files():
    for top in SCANNED:
        for path in sorted((REPO / top).rglob("*.py")):
            yield path, path.relative_to(REPO).as_posix()


def test_no_hardcoded_topic_literals():
    """A topic name outside api.py is a rename that a later branch will forget.

    This test fails for whoever wrote the literal, not for whoever does the rename --
    which is the only ordering that makes the constant hold.
    """
    offenders = []
    for path, rel in _python_files():
        if rel in DECLARATION_SITES or rel in AWAITING_MIGRATION:
            continue
        for lineno, text in _topic_literals(path):
            offenders.append(f"{rel}:{lineno}: {text!r}")
    assert not offenders, (
        "hardcoded topic literals; import the constant from skill_monitor.core.api "
        "instead:\n  " + "\n  ".join(offenders)
    )


def test_the_migration_allowlist_is_still_accurate():
    """Every allowlisted file must still exist and still contain a literal.

    Deliberately a warning and not a failure: a package that migrates its own file
    would otherwise turn this file -- which it does not own -- red on a green branch.
    The warning is the prompt to delete the entry; an empty AWAITING_MIGRATION is the
    end state.
    """
    stale = []
    for rel in sorted(AWAITING_MIGRATION):
        path = REPO / rel
        if not path.exists():
            stale.append(f"{rel} no longer exists")
        elif not _topic_literals(path):
            stale.append(f"{rel} has no topic literals left")
    if stale:
        warnings.warn(
            "AWAITING_MIGRATION in tests/test_api.py is stale, remove: "
            + "; ".join(stale),
            UserWarning,
        )
