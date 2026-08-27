"""Skill Center's logic, with no Tk and no ROS.

The panel's job is to turn a stream of manifests and state payloads into something an
operator can act on, so what is tested here is that translation -- not the widgets.
"""

import json

import skill_monitor
from skill_monitor.core import manifest as manifest_mod
from skill_monitor.frontend import skill_center as sc


def _state(**kw):
    base = {"phase": "Exec", "phase_index": 0, "step": 1, "risk": {}}
    return base | kw


def test_no_events_when_nothing_changed():
    s = _state()
    assert sc.timeline_events(s, s) == []


def test_phase_transitions_are_logged_with_their_step():
    events = sc.timeline_events(_state(phase="Plan"), _state(phase="Exec", step=42))
    assert events == [("info", "[  42] phase → Exec")]


def test_a_violated_failure_mode_is_logged_as_bad():
    prev = _state(named_failure_modes=[{"name": "collision", "status": "INCONCLUSIVE"}])
    new = _state(named_failure_modes=[{"name": "collision", "status": "VIOLATED"}])
    (sev, text), = sc.timeline_events(prev, new)
    assert sev == "bad" and "collision" in text and "VIOLATED" in text
    # …and not re-logged every tick while it stays violated.
    assert sc.timeline_events(new, new) == []


def test_a_failure_mode_seen_for_the_first_time_is_not_a_transition():
    # First manifest arrival is not an event: the monitor may have been running for
    # an hour before this panel connected.
    new = _state(named_failure_modes=[{"name": "collision", "status": "VIOLATED"}])
    assert sc.timeline_events(_state(), new) == []


def test_staleness_is_logged_once_and_recovery_is_logged():
    fresh = _state(risk={"trigger_confidence": 1.0})
    stale = _state(risk={"trigger_confidence": 0.67, "stale_sources": ["points"]})
    (sev, text), = sc.timeline_events(fresh, stale)
    assert sev == "warn" and "0.67" in text and "points" in text
    assert sc.timeline_events(stale, stale) == []
    (sev, text), = sc.timeline_events(stale, fresh)
    assert sev == "info" and "fresh again" in text


def test_halt_and_the_next_episode_are_both_marked():
    running = _state()
    halted = _state(state="halt", reason="fell over")
    (sev, text), = sc.timeline_events(running, halted)
    assert sev == "bad" and "fell over" in text
    texts = [t for _, t in sc.timeline_events(halted, running)]
    assert any("new episode" in t for t in texts)


def test_warn_onset_is_logged_once():
    calm = _state(risk={"warn": False})
    warn = _state(risk={"warn": True, "severity": "TIMEOUT", "steps_to_timeout": 2,
                        "violations_to_fault": 1})
    (sev, text), = sc.timeline_events(calm, warn)
    assert sev == "warn" and "TIMEOUT" in text and "2 steps" in text
    assert sc.timeline_events(warn, warn) == []


def test_monitors_accumulates_and_bounds_the_timeline():
    m = sc.Monitors()
    m.discovered(["/g1"])
    for i in range(sc.MAX_EVENTS + 50):
        m.apply("state", "/g1", _state(phase=f"P{i}", step=i))
    slot = m.get("/g1")
    assert len(slot["events"]) == sc.MAX_EVENTS
    assert slot["desc"]["phase"] == f"P{sc.MAX_EVENTS + 49}"   # newest kept
    assert slot["last"] is not None


def test_monitors_keeps_manifest_and_adapter_apart_from_state():
    m = sc.Monitors()
    m.apply("manifest", "", {"skill_name": "X"})
    m.apply("adapter", "", {"adapter": "real_g1"})
    slot = m.get("")
    assert slot["manifest"]["skill_name"] == "X"
    assert slot["adapter"]["adapter"] == "real_g1"
    assert slot["desc"] == {}, "a manifest must not be mistaken for live state"


def test_the_panel_renders_a_robot_it_has_never_heard_of():
    """The agnosticism claim, checked at the render layer: rows come from the
    manifest, so a manipulation monitor needs no code here."""
    man = {"atomic_propositions": {"grasped": "True when gripper_force > 1.0. Held."}}
    adapter = {"schema": {"gripper_force": {"doc": "newtons"}}}
    state = {"ap_values": {"grasped": True}, "sensors": {"gripper_force": 3.2}}
    assert manifest_mod.ap_rows(man, state) == [("grasped", True, man["atomic_propositions"]["grasped"])]
    assert manifest_mod.sensor_rows(adapter, state) == [("gripper_force", 3.2, "newtons")]


def test_the_mock_source_produces_what_the_panel_expects():
    """The --mock path is the only way to exercise this panel on a host with no ROS,
    so it has to speak the real protocol, not an approximation of it."""
    import queue
    q = queue.Queue()
    src = sc.MockSource(q, period=0.01)
    src.start()
    seen = {}
    deadline = 200
    while deadline and "state" not in seen:
        kind, ns, payload = q.get(timeout=5)
        seen.setdefault(kind, payload)
        deadline -= 1
    src.stop()

    assert set(seen) >= {"discovered", "manifest", "adapter", "state"}
    assert seen["manifest"]["phases"], "manifest must carry phase names"
    state = seen["state"]
    for key in ("phase", "phase_index", "phases", "ap_values", "sensors", "risk",
                "named_failure_modes", "step"):
        assert key in state, f"mock state is missing {key}, which the panel renders"
    # The sensor keys it invents must be the ones the real adapter declares.
    from skill_monitor.core import adapter_spec
    assert set(state["sensors"]) == set(adapter_spec.load("real_g1").keys())


def test_the_mock_run_actually_trips_a_failure_mode():
    """Without this the demo run looks healthy forever and the timeline's most
    important line -- a failure mode going VIOLATED -- is never exercised."""
    import queue
    src = sc.MockSource(queue.Queue())
    spec = json.loads(skill_monitor.spec_path("g1").read_text(encoding="utf-8"))
    phases = [p["phase"] for p in spec["execution_phases"]]
    prev, events = {}, []
    for step in range(80):
        src._step = step
        state = src._state(spec, phases)
        events += sc.timeline_events(prev, state)
        prev = state
    assert any("VIOLATED" in t for _, t in events), [t for _, t in events]


def test_generated_spec_from_the_mock_model_validates_against_the_schema():
    from skill_monitor.core import adapter_spec, spec_contract
    from skill_monitor.describer import generate_formulas as gen
    schema = adapter_spec.load("real_g1").docs()
    spec, problems = gen.generate("walk to the kitchen", schema, llm=sc._mock_llm)
    assert problems == []
    assert spec_contract.validate(spec, schema.keys()) == []
    assert json.loads(json.dumps(spec)) == spec


def test_bundled_spec_still_matches_the_bundled_robot():
    """Guards the demo path everything else here assumes: the shipped spec must be
    executable against the shipped adapter."""
    from skill_monitor.core import adapter_spec, spec_contract
    spec = json.loads(skill_monitor.spec_path("g1").read_text(encoding="utf-8"))
    assert spec_contract.validate(spec, adapter_spec.load("real_g1").keys()) == []
