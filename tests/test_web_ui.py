"""The web console: what it serves, and that its mock speaks the real contract.

No browser and no sockets. The page itself is one static file, so what is testable
here is the two things that can silently rot: the gateway's file route, and the mock
monitor -- which is the fixture every other reviewer will judge the console by, and is
therefore held to the same validators as a real producer.

**What is asserted here and what is not.** This repo has no JavaScript test runner --
a documented gap in `docs/packages/P7-frontend.md`, not an oversight of this file -- so
for pane 6 (the automaton) the split is:

* asserted, below: the frames the pane renders from. That the manifest carries a
  well-formed `automata` block, that every graph is genuinely the formula's own, that
  each verdict row's state is a state of its own graph or an honest null, that a formula
  the mock cannot compile gets no graph rather than a guessed one, and that every frame
  still validates. Also, by reading the page's source, that the degrade path still names
  the missing field and its owner.
* checked by hand in a browser against `--mock`, not asserted: the SVG layout itself,
  that the highlight is a class swap rather than a redraw, that accepting / sink /
  ordinary states are told apart by shape as well as by colour, and that the witnessed
  path caption appears. A DOM harness would assert these; there is nowhere to put one
  yet.
"""

from __future__ import annotations

import json
import time
import urllib.parse

import pytest

from skill_monitor.backend import gateway
from skill_monitor.core import api, spec_contract
from skill_monitor.frontend import mock_monitor, web


# ============================================================== the file route


@pytest.fixture
def served():
    return gateway.Gateway(static_dir=web.HERE)


def test_the_root_is_the_console(served):
    body, content_type = served.static_file("/")
    assert content_type.startswith("text/html")
    assert b"<title>skill monitor" in body


def test_a_gateway_told_of_no_directory_serves_no_files():
    """The default. An API-only deployment must not start answering GETs for whatever
    happens to sit next to it."""
    assert gateway.Gateway().static_file("/index.html") is None


@pytest.mark.parametrize("path", [
    "/../../etc/passwd",
    "/..%2f..%2fetc/passwd",
    "/subdir/index.html",
    "/.hidden.html",
    # A Windows separator is a separator here too, or `..\..\etc` is a legal name.
    "/..\\..\\etc\\passwd",
    "/etc/passwd",                      # absolute, once the leading `/` is stripped
    "/index.html/",                     # a trailing slash is not the same resource
    "/%252e%252e%252findex.html",       # decoded once by the client, not again by us
    "/INDEX.HTML",                      # the extension allowlist is case-sensitive
    # A NUL in the name makes `Path.resolve` raise ValueError, not OSError. Uncaught it
    # escapes `_route`, and the client gets a closed socket and zero bytes instead of a
    # 404 -- an anonymous, one-request way to turn a served gateway into a non-HTTP one.
    "/a\x00.html",
])
def test_nothing_outside_the_directory_is_reachable(served, path):
    assert served.static_file(path) is None


def test_only_the_extensions_the_console_is_built_from_are_served(served):
    """`web.py` and `mock_monitor.py` sit in the served directory. An allowlist is why
    they are not downloadable -- and why a key dropped in there later would not be."""
    assert served.static_file("/web.py") is None
    assert served.static_file("/mock_monitor.py") is None
    # And not SVG. An SVG navigated to runs script *in this origin*, which is the origin
    # holding the `X-Skill-Monitor` grant and the websocket `Origin` grant -- so a file
    # dropped in the served directory would be stored XSS against the robot's controls.
    assert ".svg" not in gateway.Gateway.STATIC_TYPES


def test_a_symlink_out_of_the_directory_is_not_a_way_in(tmp_path, monkeypatch):
    """Resolved-path comparison, not string inspection: `evil.html` is a legal name and
    a legal extension, and only the resolve catches where it points."""
    secret = tmp_path / "secret.html"
    secret.write_text("<b>not yours</b>")
    served_dir = tmp_path / "static"
    served_dir.mkdir()
    (served_dir / "index.html").write_text("ok")
    try:
        (served_dir / "evil.html").symlink_to(secret)
    except (OSError, NotImplementedError):       # pragma: no cover -- no symlinks here
        pytest.skip("this filesystem has no symlinks")
    g = gateway.Gateway(static_dir=served_dir)
    assert g.static_file("/index.html") is not None
    assert g.static_file("/evil.html") is None


def test_the_console_names_its_own_origin():
    """The gateway refuses a websocket from an Origin it was not told about, and the
    console's origin is its own. If this list stops covering it the page connects to
    nothing and every pane sits empty."""
    origins = web.own_origins("127.0.0.1", 8080)
    assert "http://127.0.0.1:8080" in origins
    assert "http://localhost:8080" in origins
    assert web.own_origins("0.0.0.0", 9000) == ["http://127.0.0.1:9000",
                                                "http://localhost:9000"]


def test_an_ipv6_origin_is_spelled_the_way_a_browser_spells_it():
    """A browser reached at `[::1]:8080` sends `Origin: http://[::1]:8080`. Without the
    brackets the allowlist holds `http://::1:8080`, which matches nothing the browser
    will ever send and which `urlsplit` cannot pull a hostname out of either -- so the
    Host allowlist derived from it is wrong in the same breath."""
    assert web.own_origins("::1", 8080) == ["http://127.0.0.1:8080",
                                            "http://localhost:8080",
                                            "http://[::1]:8080"]
    assert urllib.parse.urlsplit("http://[::1]:8080").hostname == "::1"
    # A wildcard IPv6 bind names nothing of its own, but it *is* reached at [::1].
    assert "http://[::1]:9000" in web.own_origins("::", 9000)


def test_the_stream_carries_the_tick():
    """The console reads t0 and mode off `/monitor/tick`. They exist nowhere else, so
    dropping the topic from the stream empties the clock pane."""
    assert api.TICK in gateway.STREAM_TOPICS


# ============================================================== the mock monitor


@pytest.fixture
def bus():
    b = mock_monitor.MockBus(rate_scale=200.0)
    yield b
    b.shutdown()


def frames(bus, timeout=3.0):
    """The latest payload seen on each streamed topic, once all three have arrived."""
    seen = {}
    bus.subscribe(mock_monitor.NS, gateway.STREAM_TOPICS,
                  lambda topic, text: seen.__setitem__(topic, json.loads(text)))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(t in seen for t in gateway.STREAM_TOPICS):
            return seen
        time.sleep(0.01)
    raise AssertionError(f"only saw {sorted(seen)} within {timeout}s")


def test_every_frame_the_mock_publishes_validates(bus):
    """The fiction is held to the contract, not to a resemblance of it. This is the one
    test that fails when the wire moves and the mock does not.

    Every topic the mock puts on the wire, streamed or latched -- because each of them
    reaches a browser through a route of its own, and one that is only *nearly* the
    contract is a pane rendering a field no real monitor will ever send.
    """
    seen = frames(bus)
    assert api.validate_tick(seen[api.TICK]) == []
    assert api.validate_observation(seen[api.OBSERVATION]) == []
    assert api.validate_verdict(seen[api.VERDICT]) == []
    assert api.validate_adapter(json.loads(bus.latched(mock_monitor.NS, api.ADAPTER))) == []
    assert api.validate_skill_manifest(
        json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))) == []
    assert api.validate_spec_status(
        json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))) == []


def test_the_answer_to_a_pushed_spec_validates_too(bus):
    """The latched `spec_status` is rebuilt on every `load_spec`, so validating only the
    one built at startup would leave the reload path free to grow a field of its own."""
    bus.publish(mock_monitor.NS, api.LOAD_SPEC,
                json.dumps(api.build_load_spec(spec=bus.spec)))
    assert api.validate_spec_status(
        json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))) == []

    spec = json.loads(json.dumps(bus.spec))
    spec["atomic_propositions"]["impossible"] = "True when no_such_sensor > 1."
    bus.publish(mock_monitor.NS, api.LOAD_SPEC,
                json.dumps(api.build_load_spec(spec=spec)))
    rejected = json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))
    assert rejected["ok"] is False
    assert api.validate_spec_status(rejected) == []


def test_an_ap_is_true_for_the_reason_its_rule_gives(bus):
    """The console shows a rule beside a boolean. If the mock's booleans came from
    anywhere but the rule, every AP pane review would be reviewing a coincidence."""
    o = frames(bus)[api.OBSERVATION]
    for name, rule in bus.spec["atomic_propositions"].items():
        if name in o["unknown_aps"]:
            continue
        expected = bool(eval(spec_contract.rule_of(rule), {}, o["sensors"]))
        assert o["ap_values"][name] == expected, name


def test_a_stale_source_makes_its_aps_unknown_not_false(bus):
    """The reason `unknown_aps` is a sibling list: a dropout must not be able to
    fabricate `not collision_risk` and let the page render a safe robot."""
    blind_keys = set()
    for source in bus.adapter["sources"]:
        if source["id"] == "points":
            blind_keys = set(source["keys"])
    o = None
    for step in range(20, 26):
        o = _observation_at(bus, step)
    assert o["data_health"]["points"]["refreshed"] is False
    for name in o["unknown_aps"]:
        assert spec_contract.sensor_keys_in_rule(
            bus.spec["atomic_propositions"][name]) & blind_keys
        assert name not in o["ap_values"]


def _observation_at(bus, step):
    """One pulse's observation, built directly -- the thread's timing is not the thing
    under test and waiting for step 23 to come round is not a test, it is a delay."""
    sensors = bus._sensors(step)
    stale = bus._stale_sources(step)
    values, unknown = bus._aps(sensors, stale)
    return api.build_observation(
        seq=step, t=float(step), step=step, sensors=sensors, ap_values=values,
        unknown_aps=unknown, confidence=0.5 if stale else 1.0,
        data_health=bus._health(step, stale))


def test_pushing_a_spec_restarts_the_episode_and_says_which_spec_is_loaded(bus):
    """Hot reload, and the visible consequence of it. A swap that left `step` running
    would have the console counting one episode's ticks against another's bounds."""
    frames(bus)                                     # let it get somewhere first
    spec = dict(bus.spec, skill_name="RenamedSkill")
    bus.publish(mock_monitor.NS, api.LOAD_SPEC,
                json.dumps(api.build_load_spec(spec=spec)))

    status = json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))
    assert status["ok"] and status["problems"] == []
    assert status["skill_name"] == "RenamedSkill"
    manifest = json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))
    assert manifest["skill_name"] == "RenamedSkill"
    assert manifest["source"] == "load_spec"
    assert bus._step <= 1


def test_a_spec_the_robot_cannot_evaluate_is_refused_with_its_reasons(bus):
    """The console renders `problems` verbatim, so they have to be the validator's."""
    spec = json.loads(json.dumps(bus.spec))
    spec["atomic_propositions"]["impossible"] = (
        "True when no_such_sensor > 1. A key this robot does not have.")
    bus.publish(mock_monitor.NS, api.LOAD_SPEC,
                json.dumps(api.build_load_spec(spec=spec)))

    status = json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))
    assert status["ok"] is False
    assert any("no_such_sensor" in p for p in status["problems"])
    assert bus.spec["skill_name"] == "G1HumanoidNavigation"   # and it was not loaded


def test_the_episode_ends_rather_than_counting_past_its_own_bounds(bus):
    """`step` against `max_steps` is a pane. A counter that runs past the sum of every
    phase's bound renders as "440 / 10 in phase", which is not a bound at all."""
    assert bus._episode_steps() == sum(
        p["timing_bounds"]["max_steps"] for p in bus.spec["execution_phases"])
    for step in range(bus._episode_steps()):
        index, in_phase = bus._phase_at(step)
        assert 0 <= in_phase <= (mock_monitor._max_steps(bus.spec, index) or 0)


def test_the_mock_says_on_the_wire_that_it_is_a_fiction(bus):
    """Not in a log line the operator never reads: in `services.ros`, which is where
    the page's MOCK DATA badge comes from."""
    status = bus.status()
    assert status["mock"] is True
    assert "MOCK" in status["detail"]


# ============================================================== pane 6's automata


def _graphs(bus):
    """The latched manifest's graphs, by name."""
    manifest = json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))
    return {graph["name"]: graph for graph in manifest["automata"]}


def test_the_manifest_carries_a_graph_for_every_monitor_it_can_compile(bus):
    """Pane 6 draws from the latched manifest, so the graphs have to be there, be
    well-formed, and be named the way the verdict names its rows -- matching a graph to
    a row is by `name` and nothing else."""
    manifest = json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))
    assert api.validate_skill_manifest(manifest) == []

    graphs = manifest["automata"]
    declared = [f["name"] for f in bus.spec["ltl_formulas"]] + \
               [m["name"] for m in bus.spec["named_failure_modes"]]
    assert [g["name"] for g in graphs] == declared        # order and all of them
    for graph in graphs:
        ids = [s["id"] for s in graph["states"]]
        assert len(ids) == len(set(ids))
        assert all(isinstance(i, int) for i in ids)
        assert graph["initial"] in ids
        assert isinstance(graph["formula"], str) and graph["formula"]
        for state in graph["states"]:
            assert isinstance(state["accepting"], bool)
            assert isinstance(state["sink"], bool)
        for edge in graph["edges"]:
            assert edge["from"] in ids and edge["to"] in ids
            assert isinstance(edge["label"], str) and edge["label"]
        # Deterministic, or the state the page lights depends on edge order.
        assert len({(e["from"], e["label"]) for e in graph["edges"]}) == \
            len(graph["edges"])


def test_a_chained_eventuality_compiles_to_the_chain_the_formula_spells(bus):
    """The shipped formula, not a formula shaped like it: one state per eventuality
    still outstanding, in the order the nesting gives them, and the last state both
    accepting and absorbing because nothing after it can take the verdict back."""
    graph = _graphs(bus)["full_navigation_sequence"]
    advances = [e["label"] for e in graph["edges"]
                if e["from"] != e["to"]]
    assert advances == ["mission_started", "path_active",
                        "moving_towards_target", "mission_finished"]
    assert [s["id"] for s in graph["states"]] == [0, 1, 2, 3, 4]
    assert [s["accepting"] for s in graph["states"]] == [False] * 4 + [True]
    assert [s["sink"] for s in graph["states"]] == [False] * 4 + [True]
    # Every non-final state waits where it is while its own eventuality has not held.
    for i in range(4):
        assert {"from": i, "to": i, "label": f"!{advances[i]}"} in graph["edges"]


@pytest.mark.parametrize("name,hold,fail", [
    ("collision_imminent", "!collision_risk", "collision_risk"),
    ("fell_over", "upright", "!upright"),
])
def test_a_safety_property_compiles_to_an_accepting_state_and_a_sink(bus, name, hold,
                                                                     fail):
    """`G(p)` is two states: hold in the accepting one while `p` holds, absorb the tick
    it does not. The sink is what makes a violated safety mode stay violated instead of
    flickering back the moment the sensor reading recovers."""
    graph = _graphs(bus)[name]
    assert graph["states"] == [{"id": 0, "accepting": True, "sink": False},
                               {"id": 1, "accepting": False, "sink": True}]
    assert graph["initial"] == 0
    assert {"from": 0, "to": 0, "label": hold} in graph["edges"]
    assert {"from": 0, "to": 1, "label": fail} in graph["edges"]
    # `1`, not `true`: Spot's `bdd_format_formula` prints an unconditional guard that
    # way, so that is the string the console has to be able to render, and the mock's
    # job is to hand it the strings a real monitor will.
    assert {"from": 1, "to": 1, "label": "1"} in graph["edges"]
    assert mock_monitor.label_holds("1", {}) is True


@pytest.mark.parametrize("formula", [
    "G(upright) && G(!collision_risk)",   # `G(` at the front and `)` at the back is not
    "F(mission_finished) || G(upright)",  # the same thing as one G over the whole text
    "X(mission_started)",
    "mission_finished U nav_stuck",
    "",
])
def test_a_formula_the_mock_cannot_compile_gets_no_graph_rather_than_a_guess(formula):
    """The mock hand-compiles two shapes. For anything else it publishes nothing, and
    the row simply has no graph to match -- which the page has to survive regardless,
    because the phase machine's own faults never have one either."""
    assert mock_monitor.compile_automaton("whatever", formula) is None


def test_a_spec_whose_formulas_do_not_compile_still_latches_a_valid_manifest(bus):
    """The pane's degrade path from the producing end: `automata` is an empty list, not
    a missing key filled with invented graphs, and the manifest still validates."""
    spec = json.loads(json.dumps(bus.spec))
    spec["ltl_formulas"] = [{"name": "compound",
                             "formula": "G(upright) && G(!collision_risk)"}]
    spec["named_failure_modes"] = []
    bus.publish(mock_monitor.NS, api.LOAD_SPEC,
                json.dumps(api.build_load_spec(spec=spec)))

    manifest = json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))
    assert json.loads(bus.latched(mock_monitor.NS, api.SPEC_STATUS))["ok"] is True
    assert manifest["automata"] == []
    assert api.validate_skill_manifest(manifest) == []


def test_the_state_advances_with_the_aps_the_mock_is_already_fabricating(bus):
    """A lit node has to be lit for the reason the edge label gives. Stepped here over
    the mock's own sensors and its own AP evaluation, for a whole episode -- so this
    fails if the fabricated sensors and the reported state ever come apart.

    Driven through the module's pure stepper rather than through `bus._auto_state`,
    which the running thread is mutating at the same time.
    """
    graph = _graphs(bus)["full_navigation_sequence"]
    ids = {s["id"] for s in graph["states"]}
    state, reached = graph["initial"], []
    for step in range(bus._episode_steps()):
        values, _unknown = bus._aps(bus._sensors(step), bus._stale_sources(step))
        nxt = mock_monitor.successor(graph, state, values)
        assert nxt is not None            # this formula's guards are never blinded
        assert nxt in ids
        assert nxt >= state               # a chain of eventualities never un-discharges
        assert nxt - state <= 1           # and discharges at most one per tick
        # Whether it moved is exactly whether the outstanding eventuality held.
        outstanding = [e for e in graph["edges"]
                       if e["from"] == state and e["to"] != state]
        if outstanding:
            assert (nxt != state) == bool(values[outstanding[0]["label"]])
        state = nxt
        reached.append(state)
    assert reached[-1] == 4 and 4 in ids
    assert [s for s in graph["states"] if s["id"] == 4][0]["accepting"] is True


def test_a_guard_this_tick_cannot_answer_reports_no_state_rather_than_a_stale_one(bus):
    """`state: null` is a real value on the wire and the mock has to produce it: while
    the depth camera is out, `collision_risk` is UNKNOWN, and stepping the safety
    automaton on a guard nobody evaluated would advance it on evidence it does not
    have. The page draws nothing lit for that tick."""
    stale_step = 22
    assert bus._stale_sources(stale_step) == ["points"]
    values, unknown = bus._aps(bus._sensors(stale_step), bus._stale_sources(stale_step))
    assert "collision_risk" in unknown and "collision_risk" not in values

    graph = _graphs(bus)["collision_imminent"]
    assert mock_monitor.successor(graph, 0, values) is None
    # And a tick that *can* answer still steps, from the state the blind tick left.
    healthy, _unknown = bus._aps(bus._sensors(0), [])
    assert mock_monitor.successor(graph, 0, healthy) == 0


def test_a_verdict_row_carries_the_state_of_its_own_graph(bus):
    """Matching is by `name`: every graph has a row, and a row that has a graph reports
    a state of that graph or an honest null."""
    verdict = frames(bus)[api.VERDICT]
    graphs = _graphs(bus)
    assert graphs
    rows = verdict["formulas"] + verdict["failure_modes"]
    assert {r["name"] for r in rows} >= set(graphs)
    for row in rows:
        if row["name"] not in graphs:
            continue
        if mock_monitor.WIRE_ADMITS_STATE:
            assert "state" in row
            ids = {s["id"] for s in graphs[row["name"]]["states"]}
            assert row["state"] is None or row["state"] in ids
        else:
            assert "state" not in row
    assert api.validate_verdict(verdict) == []


def test_the_mock_sends_state_the_moment_the_contract_admits_it(bus):
    """`formulas[].state` is P0's field to open: `_FORMULA_FIELDS` is closed and its
    entries are checked by `_check_each`, so a producer sending it early publishes a
    frame the shipped validators reject. The mock therefore asks the validator itself
    rather than carrying a flag someone has to remember to flip -- and this asserts that
    the gate really is the validator's answer, in both directions."""
    verdict = frames(bus)[api.VERDICT]
    probe = dict(verdict, formulas=[dict(verdict["formulas"][0], state=0)])
    assert (api.validate_verdict(probe) == []) is mock_monitor.WIRE_ADMITS_STATE


def test_a_status_follows_the_automaton_that_produced_it(bus):
    """The status column and the lit node are two readings of one thing. An accepting
    state is ACCEPTED even when it is also absorbing; a non-accepting sink is VIOLATED;
    an unknown state claims nothing."""
    chain = _graphs(bus)["full_navigation_sequence"]
    safety = _graphs(bus)["collision_imminent"]
    assert mock_monitor.status_of(chain, 4) == "ACCEPTED"
    assert mock_monitor.status_of(chain, 0) == "INCONCLUSIVE"
    assert mock_monitor.status_of(safety, 0) == "ACCEPTED"
    assert mock_monitor.status_of(safety, 1) == "VIOLATED"
    assert mock_monitor.status_of(safety, None) == "INCONCLUSIVE"
    assert mock_monitor.status_of(None, 1) == "INCONCLUSIVE"


def test_the_page_still_names_the_field_and_its_owner_when_there_are_no_automata():
    """The build without the producer half is the one the pane has to degrade for. The
    page's JS has no test runner here, so this asserts the source rather than the DOM:
    the `missing()` call naming `manifest.automata` and P4 must survive any rewrite of
    the pane, because it is what the operator reads instead of a blank box.

    An *absent* `automata` is that build; an empty one is a build that can report them
    and has none for this spec. The page keys the placeholder on the first, which is
    why the test looks for the `Array.isArray` guard and not a falsiness test.
    """
    page = (web.HERE / "index.html").read_text(encoding="utf-8")
    assert 'missing("manifest.automata' in page
    assert "S.manifest || {}).automata" in page
    assert "if (!Array.isArray(graphs)) {" in page
    # And the unconditional guard is spelt out rather than left as a bare `1` beside a
    # state numbered 1.
    assert '{ "1": "any input", "0": "never" }' in page


def test_the_mock_splits_a_rule_with_the_shared_splitter(bus):
    """There were once three copies of this regex and all three truncated
    `min_range < 0.25` at the decimal point, so `collision_risk` could never fire. A
    fourth copy in here would be the same bug waiting in a different file -- so the
    mock calls `spec_contract.rule_of`, and this asserts the result rather than the
    call, because that is what a future rewrite would break."""
    assert not hasattr(mock_monitor, "_condition")
    sensors = bus._sensors(0) | {"min_range": 0.1}
    values, _unknown = bus._aps(sensors, [])
    assert values["collision_risk"] is True          # 0.1 < 0.25, not 0.1 < 0
    values, _unknown = bus._aps(sensors | {"min_range": 3.0}, [])
    assert values["collision_risk"] is False
