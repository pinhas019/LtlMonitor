"""The demo page's "what the monitor is doing" card, from a hand-built manifest and verdict.

Pure Python: the view reads only what the monitor publishes (manifest, verdict) and the
evaluator's observation, so no ROS, Spot or MuJoCo is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stack_view import automata_view  # noqa: E402

TASK = "fetch_and_deliver_in_order"
MANIFEST = {
    "skill_name": "G1FetchAndDeliver",
    "atomic_propositions": {
        "holding_object": "True when holding == True. The gripper reports the object held.",
        "upright": "True when upright_flag > 0.5. The robot is standing.",
        "obstacle_too_close": "True when min_range < 0.3. Something is too close.",
        "near_dropoff": "True when dist_to_dropoff < 0.5. At the drop-off.",
    },
    "execution_phases": [
        {"phase": "Grasp", "invariant": "upright and not obstacle_too_close",
         "exit_condition": "holding_object", "timing_bounds": {"max_steps": 10}},
        {"phase": "Carry", "invariant": "upright and holding_object and not obstacle_too_close",
         "exit_condition": "near_dropoff", "progress_condition": "not stalled",
         "timing_bounds": {"max_steps": 60}},
    ],
    "terminal_success": {"description": "Delivered."},
    "automata": [
        {"name": TASK, "formula": "F(a && F(b))", "initial": 0,
         "states": [{"id": 0}, {"id": 3}, {"id": 5, "accepting": True}],
         "edges": [{"from": 0, "to": 0, "label": "!a"}, {"from": 0, "to": 3, "label": "a"},
                   {"from": 3, "to": 3, "label": "!near_dropoff"},
                   {"from": 3, "to": 5, "label": "b"}, {"from": 5, "to": 5, "label": "1"}]},
        {"name": "fell_over", "formula": "G(upright)", "initial": 0,
         "states": [{"id": 0, "accepting": True}, {"id": 1, "sink": True}],
         "edges": [{"from": 0, "to": 0, "label": "upright"}]},
    ],
}


def verdict(**kw):
    v = {"t": 18.0, "phase": "Carry", "terminal": None, "verdict": "UNDECIDED",
         "formulas": [{"name": TASK, "status": "INCONCLUSIVE", "state": 3}],
         "failure_modes": [{"name": "fell_over", "status": "ACCEPTED", "state": 0}],
         "risk": {"seconds_to_timeout": 58.0},
         "phase_guards": {"phase": "Carry", "guards": [
             {"name": "invariant", "expr": "upright and holding_object", "value": True}]}}
    return v | kw


def test_no_manifest_no_view():
    assert automata_view(None, verdict(), {}) is None


def test_before_the_first_verdict_the_graphs_are_drawn_at_their_initial_state():
    view = automata_view(MANIFEST, None, None)
    assert view["phase"] == "Idle"
    assert [a["name"] for a in view["automata"]] == [TASK]   # safety graphs are chips
    assert view["automata"][0]["current"] == 0
    assert view["now"].startswith("Idle")


def test_a_running_phase_names_its_invariant_exit_and_the_automaton_state():
    view = automata_view(MANIFEST, verdict(), {"ap_values": {"holding_object": True}},
                         prev_states={TASK: 0})
    assert [p["name"] for p in view["phases"]] == ["Idle", "Grasp", "Carry", "Done"]
    assert view["phase"] == "Carry" and not view["success"]
    task = view["automata"][0]
    assert (task["current"], task["prev"]) == (3, 0)
    st = {s["id"]: s for s in task["states"]}
    assert st[3]["meaning"] == "holding it, carrying"       # the generated task's table
    assert st[3]["stay"] == "!near_dropoff"                  # read off the self-loop
    assert all(e["from"] != e["to"] for e in task["edges"])
    assert view["safety"] == [{"name": "fell_over", "status": "ACCEPTED", "state": 0,
                               "means": "the robot stays upright", "formula": "G(upright)"}]
    assert "Phase Carry (≤60 s, 58 s left)" in view["now"]
    assert "near_dropoff" in view["now"] and "state 3: holding it, carrying" in view["now"]
    props = {p["name"]: p["value"] for p in view["props"]}
    assert props["holding_object"] is True and props["upright"] is None
    assert view["guards"][0]["name"] == "invariant"


def test_a_broken_invariant_names_the_proposition_that_broke_it():
    v = verdict(t=22.0, terminal="FAILURE", verdict="VIOLATED", failure_modes=[
        {"name": "fell_over", "status": "ACCEPTED", "state": 0},
        {"name": "phase:Carry:invariant", "fault_category": "INVARIANT",
         "status": "VIOLATED", "state": None}])
    obs = {"ap_values": {"holding_object": False, "upright": True,
                         "obstacle_too_close": False}}
    view = automata_view(MANIFEST, v, obs)
    assert view["fault"] == {"name": "phase:Carry:invariant", "category": "INVARIANT"}
    assert view["now"].startswith("FAULT at 22 s")
    assert "(holding_object = false)" in view["now"]          # not upright, not the obstacle
    assert "still in state 3" in view["now"]


def test_a_violated_safety_automaton_is_the_fault():
    v = verdict(terminal="FAILURE", failure_modes=[
        {"name": "fell_over", "status": "VIOLATED", "state": 1}])
    view = automata_view(MANIFEST, v, {"ap_values": {"upright": False}})
    assert view["fault"]["name"] == "fell_over"
    assert "fell_over was violated" in view["now"]


def test_done_without_a_terminal_is_success():
    v = verdict(phase="Done", verdict="SATISFIED",
                formulas=[{"name": TASK, "status": "ACCEPTED", "state": 5}])
    view = automata_view(MANIFEST, v, {})
    assert view["success"] and view["phase"] == "Done"
    assert view["now"].startswith("Done")
