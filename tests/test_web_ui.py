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

Pane 7 (the phase machine) splits the same way, and the same gap is the reason:

* asserted, below: that the guards the mock reports are exactly the ones the phase
  declares, in the spec's own words; that each guard's truth is true of the propositions
  on the same frame; that a guard reading a proposition the tick could not evaluate is
  `null` and never `False`; that no active phase reports `null` rather than an empty
  guard list; and that the mock gates the field on the validator's own answer. Also, by
  reading the page's source, that both degrade paths name their field and its owner,
  that `null` is rendered as a third thing, and that the page contains no evaluator.
* checked by hand in a browser against `--mock` (and against a throwaway launcher that
  patched `_VERDICT_FIELDS` to answer as P0 will, since this build's contract does not
  admit `phase_guards` yet), not asserted: the vertical SVG chain and its transition
  labels, that the current phase is marked by a caret and a second outline and not by
  colour alone, the in-phase progress bar, and the guard table with each expression's
  propositions and their live values beside it.

Pane 3's echo half splits the same way, with one extra reason for the split: what it
renders is a picture, and no assertion in Python can say a picture looked right.

The summaries the mock publishes are **the producer's own**:
`backend/adapters/raw_echo.py` is stdlib-only, so `--mock` calls it and the console is
reviewed against the code the robot runs -- PNG encoder, downscale, byte cap, rate stride
and all -- rather than against a second implementation written to resemble it. What the
mock fabricates is the message, which is what it fabricates everywhere else.

* asserted, below: that nothing is echoed until a console asks; that a request is one
  source at a time, that a null `source_id` stops it, and that a source the adapter does
  not declare is refused *without* stopping an echo somebody is watching; that a paused
  monitor echoes nothing while its clock goes on; that a tick the source missed produces
  no frame rather than a repeat of the last one; that every frame validates and reports
  the same `samples_this_tick` the row table above it reports, plus the echo's own
  `rate_hz` and `every_n_ticks`; that the mock demonstrates all four of the page's cases
  -- image, fields, `image_unavailable` with the producer's reason, and an unrecognised
  `kind`; that its camera frame costs what a real one costs rather than compressing to
  nothing; and that its image is a real PNG whose data URI passes *the page's own*
  allowlist regular expression, lifted out of the page rather than copied into this file.
  Also, by reading the page's source: that it posts to the verb `INGRESS_TOPICS` actually
  serves, with `api.build_raw_echo_request`'s payload; that the picker offers an explicit
  off and is built from the adapter's own sources; that a refused request moves nothing;
  that a missing ingress route disables the picker and says why; that the only
  interpolated URL sink on the page is the `img` src and that what goes in it is what
  `imageSrc` returned; that a shrunk frame says so; that the frame is dropped on a stop,
  on a switch and across a reconnect; and that it is aged in ticks and marked stale in
  words and in a class, never in colour alone.
* checked by hand in a browser against `--mock`, not asserted: that the synthetic frame
  renders at 160x120 and is not stretched across the pane; that switching source swaps the
  rendering, that switching to off empties it, and that the picture visibly greys and the
  tick count climbs when the monitor is paused; that the `fields` table, the reason
  sentence for `image_unavailable`, and the JSON dump for the unrecognised `kind` are
  legible; and -- against a build with the producer's `gateway.py` edit reverted -- that
  the picker is greyed out with its reason printed beside it.

The monitor controls and the state banner split the same way again, and here the split
matters more than anywhere else on the page, because the thing being controlled can stop
watching a moving robot:

* asserted, below: that the mock honours all four commands; that a paused mock really
  stops -- its step counter, every automaton and, with the step counter, its phase
  machine -- while its clock goes on, which is what makes `since_seq` measurable and what
  makes a paused monitor indistinguishable from a dead one on every other topic; that
  `arm` and `reset` restart the episode and un-pause; that `since_seq` moves only when
  the state does; that the state frame is the shape the console reads and that the mock
  publishes it only when the shipped validator says the topic admits it. And, by reading
  the page's source: that the four buttons are `api.COMMANDS`, that the payload posted is
  `api.build_command`'s and validates, that three of the four confirm and `resume` does
  not, that a refusal is reported with its status and body the way the clock's step
  button reports one, that the state is only ever assigned from a status payload and
  never inferred from the absence of verdicts, that an unrecognised state is unknown
  rather than running, that the banner carries a word and a glyph and not colour alone,
  and that the controls disable themselves with a stated reason -- and that the missing
  state topic is *not* one of those reasons.
* checked by hand in a browser against `--mock`: that the banner is legible without
  scrolling with the page scrolled to the bottom pane, the `window.confirm` texts as they
  appear, the tab title changing while the state is not running, and -- against a
  throwaway launcher that added the status topic to `api.TOPICS`/`LATCHED_TOPICS` as P0
  will, since this build's contract has no such topic yet -- that pausing from the strip
  raises the banner, freezes panes 3 to 7, and that the tick count in the banner goes on
  rising while they stay frozen.

The wall band -- tier 1, above the grid -- splits the same way once more, and this time
the hand-driving was done in headless Chrome over CDP rather than by eye, so the numbers
quoted in it are measurements:

* asserted, below: that the band is above the grid and renders on the verdict; that the
  driving row is *chosen* by the monitor's own safety-first rule from rows the verdict
  already carries and is never graded here; that a verdict with no VIOLATED row says what
  it rests on instead of naming a cause, and says so even when the verdict word
  disagrees; that `terminal` takes the band over when non-null, renders nothing when
  null, and names its field and its owner when the build carries no such field at all;
  that the rung, the `category` and the `imminence` are rendered and none of them
  derived; that the automata moved into the band and pane 6 points at them rather than
  drawing a second copy under the same element ids; that the band reads neither the
  adapter nor the observation nor the absence of anything; that no wire value reaches
  innerHTML unescaped; that the page has exactly one literal type size and it is
  `:root`'s; that every hex is a token in one block; that the 46vh cap is tier 2's alone;
  that the panes fold and remember which; and that both regex hot spots and the state
  banner are keyed on the documents they render from rather than recompiled per tick.
* driven, not asserted: everything quoted in the comment above that section -- the
  verdict and its cause read together, the automata lit on the same verdict, `terminal`
  taking the band over and coming back off, a node's text at ~17.8 screen px against ~7px
  before, the density and the fold surviving a reload, and each degrade path with the
  field deleted off the live payload.

The last section covers **what was already on the wire and rendered nowhere** --
`adapter.warnings`, every `schema[k].doc`, the fold policy of every source, the three
unrendered `risk` fields, the spec's own terminal criteria, and the declared phase
guards -- plus the honesty fixes beside them. Same split, and the same reason:

* asserted, below: the page's source at every point where a rewrite would turn "what
  the producer published" back into a blank, a zero or a guess -- that absent, null and
  empty each keep their own sentence and name their own field; that the health dot, the
  two countdowns and `severity` are graded by a glyph and a word and not by hue; that
  the amber threshold and the monitor's own `warn` are printed rather than re-derived;
  that the plots gap their nulls, carry their bounds and rebuild their canvas list; and
  that every structural read is keyed on the document it came from. Plus, against the
  mock bus, that every one of those fields really is published and really validates,
  asserted in the same test as the page reading it -- a page reading a field the wire
  dropped and a wire carrying a field the page dropped are one fault seen from two ends.
* driven, not asserted, in headless Chrome over CDP against `--mock`: everything listed
  in the comment above that section -- all fifteen of `real_g1`'s warnings on screen and
  the pane's two other answers with the field deleted and emptied; `ⓘ` against every
  documented key and `?` against one whose `doc` was deleted; `nav_stuck → last per
  message · after 10 consecutive messages`; the timing table with the whole `risk` block
  deleted; the declared-guard table appearing under the placeholder; and the plots'
  floor and ceiling, their gap, and their canvas count moving with the schema. Also the
  per-tick cost, measured in the live page and quoted in that section.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import struct
import time
import urllib.parse

import pytest

from skill_monitor.backend import gateway
from skill_monitor.backend.adapters import raw_echo
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
    """The latest payload seen on each streamed topic, once all of them have arrived.

    `/monitor/raw_echo` is the one member of `STREAM_TOPICS` that a monitor publishes
    nothing on until a console asks it to -- the echo is opt-in and one source at a
    time, because a point cloud per frame is not free -- so it is asked for here rather
    than waited for. A helper that only waited would hang the moment P6 puts the topic
    on the stream, and hang for the correct reason, which is the worst kind.

    That the default really is off is not weakened by this: it is asserted on its own in
    `test_nothing_is_echoed_until_a_console_asks_for_it`, on a bus this has not touched.
    """
    if api.RAW_ECHO in gateway.STREAM_TOPICS:
        _ask_echo(bus, bus.adapter["sources"][0]["id"])
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
    if mock_monitor.WIRE_ADMITS_STATUS:
        # Both halves of it: the latched copy a console GETs on boot, and the frame the
        # stream replays to it. They are one payload and both go past the validator.
        assert api.validate_for_topic(
            mock_monitor.STATUS_TOPIC, seen[mock_monitor.STATUS_TOPIC]) == []
        assert api.validate_for_topic(mock_monitor.STATUS_TOPIC, json.loads(
            bus.latched(mock_monitor.NS, mock_monitor.STATUS_TOPIC))) == []


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


# ========================================================= pane 7's phase machine


def _guards_at(bus, step):
    """The guard block one pulse would carry, built the way `_pulse` builds it -- from
    the sensors, the staleness and the AP values of that one step."""
    values, _unknown = bus._aps(bus._sensors(step), bus._stale_sources(step))
    index, _in_phase = bus._phase_at(step)
    return values, mock_monitor.phase_guards(bus.spec, index, values)


def test_the_guards_reported_are_the_ones_the_phase_declares(bus):
    """The pane lists a phase's guards and nothing else. A padded-out set would have it
    show an invariant for a phase that declares none, which is a claim about the spec
    rather than a reading of it -- and the expression must be the spec's own text,
    because that is what the operator is being asked to compare against."""
    for i, phase in enumerate(bus.spec["execution_phases"]):
        block = mock_monitor.phase_guards(bus.spec, i, {})
        assert block["phase"] == phase["phase"] == api.phase_names(
            bus.spec["execution_phases"])[i]
        declared = [k for k in mock_monitor.GUARD_KEYS
                    if isinstance(phase.get(k), str) and phase[k].strip()]
        assert [g["name"] for g in block["guards"]] == declared
        assert [g["expr"] for g in block["guards"]] == [phase[k] for k in declared]

    # A phase declaring only one of them reports only that one.
    spec = json.loads(json.dumps(bus.spec))
    spec["execution_phases"] = [{"phase": "Only", "invariant": "upright"}]
    assert [g["name"] for g in mock_monitor.phase_guards(spec, 0, {})["guards"]] == \
        ["invariant"]


def test_a_guard_is_true_of_the_propositions_on_its_own_frame(bus):
    """The console shows a guard's truth beside the propositions it reads, off the same
    pulse. If the mock's booleans came from anywhere but those propositions, every
    review of that pane would be reviewing a coincidence -- the same reason
    `test_an_ap_is_true_for_the_reason_its_rule_gives` exists one pane down."""
    names = list(bus.spec["atomic_propositions"])
    saw_true = saw_false = saw_null = False
    for step in range(bus._episode_steps()):
        values, block = _guards_at(bus, step)
        assert block is not None
        for guard in block["guards"]:
            reads = mock_monitor.guard_aps(guard["expr"], names)
            if any(name not in values for name in reads):
                assert guard["value"] is None, guard
                saw_null = True
                continue
            assert guard["value"] is bool(
                eval(guard["expr"], {"__builtins__": {}}, dict(values))), guard
            saw_true |= guard["value"] is True
            saw_false |= guard["value"] is False
    # All three truths really occur over an episode, so the pane has all three to draw.
    assert saw_true and saw_false and saw_null


def test_a_guard_whose_proposition_is_unknown_is_null_and_never_false(bus):
    """`null` is the value the whole pane turns on: a depth camera that dropped out
    makes `collision_risk` UNKNOWN, and reporting the invariant that reads it as False
    is how a dead sensor comes to look like a broken invariant. `not evaluated` and
    `does not hold` are different facts, and one of them is a fault."""
    stale_step = 22
    assert bus._stale_sources(stale_step) == ["points"]
    values, block = _guards_at(bus, stale_step)
    assert "collision_risk" not in values
    guards = {g["name"]: g for g in block["guards"]}
    assert guards["invariant"]["expr"] == "upright and not collision_risk"
    assert guards["invariant"]["value"] is None
    assert guards["invariant"]["value"] is not False
    # The guards on the same frame that read only propositions the tick *could* answer
    # are answered: one blind sensor does not blank the phase.
    assert guards["progress_condition"]["value"] is True
    # And the same guard is answered on a tick that can see.
    healthy, _unknown = bus._aps(bus._sensors(0), [])
    answered = {g["name"]: g for g in mock_monitor.phase_guards(
        bus.spec, 0, healthy)["guards"]}
    assert answered["invariant"]["value"] is True


def test_a_guard_reads_the_propositions_it_names_and_no_others(bus):
    """Name matching, not evaluation -- the same question the page asks of the same
    string, so that what it shows beside a guard is what the monitor's answer was a
    function of. A proposition named inside a string literal is not read by the guard."""
    names = list(bus.spec["atomic_propositions"])
    assert set(mock_monitor.guard_aps("upright and not collision_risk", names)) == \
        {"upright", "collision_risk"}
    assert mock_monitor.guard_aps("True", names) == []
    assert mock_monitor.guard_aps("nav_state == 'upright'", names) == []
    # A prefix is not a match: `upright` must not be found inside `uprightish`.
    assert mock_monitor.guard_aps("uprightish", names) == []


def test_no_active_phase_reports_null_rather_than_an_empty_guard_list(bus):
    """`null` and `{"guards": []}` are different sentences: the first is "no phase is
    active", the second is "this phase declares no guards". The console draws them
    differently and the producer must not blur them."""
    assert mock_monitor.phase_guards(bus.spec, None, {}) is None
    assert mock_monitor.phase_guards(bus.spec, 99, {}) is None
    assert mock_monitor.phase_guards(bus.spec, -1, {}) is None
    unphased = json.loads(json.dumps(bus.spec))
    unphased.pop("execution_phases")
    assert mock_monitor.phase_guards(unphased, 0, {}) is None
    assert mock_monitor.phase_guards({"execution_phases": [{"phase": "P"}]},
                                     0, {})["guards"] == []


def test_the_mock_sends_phase_guards_the_moment_the_contract_admits_it(bus):
    """`verdict.phase_guards` is P0's field to open: `_VERDICT_FIELDS` is closed, so a
    producer sending it early publishes frames the shipped validators reject. The mock
    asks the validator itself rather than carrying a flag someone has to remember to
    flip, exactly as it does for `formulas[].state` -- and this asserts the gate really
    is the validator's answer, in both directions."""
    verdict = frames(bus)[api.VERDICT]
    probe = dict(verdict, phase_guards={"phase": "x", "guards": []})
    assert (api.validate_verdict(probe) == []) is \
        mock_monitor.WIRE_ADMITS_PHASE_GUARDS
    assert ("phase_guards" in verdict) is mock_monitor.WIRE_ADMITS_PHASE_GUARDS
    assert api.validate_verdict(verdict) == []


def test_the_verdicts_phase_and_its_guards_name_the_same_phase(bus):
    """The console matches the guard block to the highlighted phase by name, so the two
    have to be one string. Asserted on the wire where the contract admits the field, and
    on the builder where it does not -- the join is what matters either way."""
    verdict = frames(bus)[api.VERDICT]
    if mock_monitor.WIRE_ADMITS_PHASE_GUARDS:
        assert verdict["phase_guards"]["phase"] == verdict["phase"]
    else:
        assert "phase_guards" not in verdict
    for step in (0, 35, 155):
        _values, block = _guards_at(bus, step)
        index, _in_phase = bus._phase_at(step)
        assert block["phase"] == api.phase_names(bus.spec["execution_phases"])[index]


def test_the_bound_the_pane_measures_against_belongs_to_the_phase_it_reports(bus):
    """The pane's whole reason to exist beside pane 6: `step` counts the episode and
    `max_steps` bounds the *phase*, so the in-phase count it draws is `max_steps` minus
    `risk.steps_to_timeout`. That subtraction is only meaningful if the bound, the risk
    and the guards on screen are all the same phase's -- one frame naming a phase whose
    guards are another's would render as a bar measuring nothing."""
    names = api.phase_names(bus.spec["execution_phases"])
    for step in range(bus._episode_steps()):
        index, in_phase = bus._phase_at(step)
        _values, block = _guards_at(bus, step)
        assert block["phase"] == names[index]        # guards, and the bound below
        bound = mock_monitor._max_steps(bus.spec, index)
        assert bound == bus.spec["execution_phases"][index]["timing_bounds"]["max_steps"]
        left = max(0, bound - in_phase)              # what the mock puts on `risk`
        assert bound - left == in_phase              # what the pane derives back
        assert 0 <= left <= bound


# =========================================== pane 7's degrade paths, read off the page


def _page():
    return (web.HERE / "index.html").read_text(encoding="utf-8")


def test_the_page_names_the_field_and_its_owner_when_there_is_no_phase_machine():
    """A build with no phase machine on the manifest gets the placeholder, naming the
    field and who publishes it -- not a blank box, and not a machine inferred from
    `manifest.phases`, which carries names and neither bounds nor guards."""
    page = _page()
    assert 'missing("manifest.execution_phases", "P4"' in page
    # Absent is a spec with no phase machine; present-and-empty is a spec that has one
    # and declares nothing in it. Keyed on `Array.isArray`, not on falsiness, so the two
    # keep their own sentences.
    assert "if (!Array.isArray(phases)) {" in page
    assert "if (!phases.length) {" in page


def test_the_page_says_no_guard_truth_is_reported_rather_than_evaluating_the_guards():
    """The build without the producer half draws the machine and the timing and says
    plainly that no guard truth is on the wire. What it must never do is fall back to
    evaluating the expressions here: a second evaluator in the page is where this
    project's `min_range < 0.25` decimal-point bug lived three times, and a guard the
    page decided for itself is a fault it invented rather than observed."""
    page = _page()
    assert 'missing("verdict.phase_guards"' in page
    assert '!("phase_guards" in v)' in page
    assert "eval(" not in page
    assert "new Function" not in page


def test_the_page_renders_an_unevaluated_guard_as_its_own_thing():
    """`null` is neither true nor false and must not be rendered as either. Strict
    comparisons, so anything that is not exactly `true` or `false` falls through to the
    third rendering rather than to the false one."""
    page = _page()
    assert "value === true" in page
    assert "value === false" in page
    assert "not evaluated" in page
    # A proposition the observation could not answer renders UNKNOWN, the same rule
    # pane 5 renders by -- absent from `ap_values` or named in `unknown_aps`.
    assert "unknown_aps" in page and "hasOwnProperty.call(o.ap_values, name)" in page


#: The panels, in the order the page lays them out.
#:
#: One number has to mean one thing in three places -- the badge on screen, the section
#: marker in `index.html`'s script, and the entry heading in P7's doc -- so that a number
#: said across a room, written in a commit and grepped for all land on the same panel.
#: Two panels have no section marker of their own and say so here rather than being
#: quietly skipped: the verdict rail is rendered by the band's own `renderWall*`, and the
#: schema list is built by panel 5's code because it documents panel 5's keys.
PANELS = [
    (1,  "automaton",            "1 · automaton"),
    (2,  "verdict",              None),
    (3,  "propositions",         "3 · atomic propositions"),
    (4,  "input",                "4 · input data"),
    (5,  "clock",                "5 · clock and replay"),
    (6,  "phase machine",        "6 · phase machine"),
    (7,  "adapter warnings",     "7 · adapter warnings"),
    (8,  "loaded config",        "8 · loaded config"),
    (9,  "schema",               None),
    (10, "description and spec", "10 · description and spec"),
    (11, "plots",                "11 · plots"),
    (12, "timing",               "12 · timing"),
]


def test_every_panel_says_which_number_it_is():
    """A number does not reflow. "The third one" meant a different pane depending on how
    wide the reader's window was, because the grid is `auto-fit` -- and the names are
    jargon, so there was nothing else to point at anything with."""
    page = _page()
    for number, title, _ in PANELS:
        assert f'<span class="num">{number}</span>' in page, number
        assert f'<span class="ttl">{title}</span>' in page, title


def test_the_number_on_screen_is_the_number_in_the_script_and_in_the_doc():
    """The regression this replaces: the script's section markers were the ORIGINAL pane
    order and the page had been re-laid-out twice under them, so `/* == 6 · automaton */`
    described the panel a reader would have called the first one."""
    page = _page()
    doc = (web.HERE.parents[1] / "docs" / "packages" / "P7-frontend.md").read_text(
        encoding="utf-8")
    for number, title, marker in PANELS:
        if marker is not None:
            assert f"/* == {marker} " in page, marker
        assert f"**{number} — " in doc, f"{number} — {title} is not in P7's doc"


def test_no_panel_is_numbered_twice_or_left_out():
    """The failure mode of a hand-kept list: two panels labelled `5` reads as one panel
    that moved, and nothing on the page says otherwise."""
    numbers = [n for n, _, _ in PANELS]
    assert numbers == sorted(numbers) == list(range(1, 13))
    page = _page()
    for number in numbers:
        assert page.count(f'<span class="num">{number}</span>') == 1, number


def test_every_pane_says_what_it_is_for_and_not_only_what_it_is_called():
    """`propositions` and `automaton` are jargon, so the name alone is not enough. But the
    long-form line on every panel was worse than the bare names -- 181 words of subtitle on
    a 1349-word page, on a page read across a room. Three or four words on screen, the
    sentence on `title`: the same rule the AP rules follow."""
    page = _page()
    panes = re.findall(r'<details class="pane"[^>]*>\s*<summary>(.*?)</summary>', page, re.S)
    assert len(panes) == 10
    for summary in panes:
        assert 'class="num"' in summary, summary[:80]
        assert 'class="ttl"' in summary, summary[:80]
        sub = re.search(r'<span class="sub"[^>]*>(.*?)</span>', summary, re.S)
        assert sub, summary[:80]
        words = re.sub(r"<[^>]+>", " ", sub.group(1)).split()
        assert len(words) <= 8, f"{len(words)} words of subtitle: {' '.join(words)}"
        assert "title=" in sub.group(0) or "href=" in sub.group(1), summary[:80]



# ================================================= pane 3's raw echo, from the mock's end
#
# The row table in pane 3 is `data_health` off the observation and costs nothing. This is
# the other half: one source's actual frames, asked for on `/monitor/raw_echo_request`
# and arriving on `/monitor/raw_echo`. Opt-in, one at a time, and a paused monitor echoes
# nothing -- the same rule its automata and its phase machine obey, for the same reason.


def _ask_echo(bus, source_id):
    """One echo request in, by the path the gateway's ingress route takes: the payload
    is `api.build_raw_echo_request`'s, it is validated, and then it is published
    verbatim. `source_id=None` is the contract's own stop."""
    payload = api.build_raw_echo_request(source_id=source_id)
    assert api.validate_raw_echo_request(payload) == []
    bus.publish(mock_monitor.NS, api.RAW_ECHO_REQUEST, json.dumps(payload))


def _echoes(bus, seconds=0.4):
    """Every `/monitor/raw_echo` frame the mock publishes over `seconds`, starting now.

    Subscribed by topic rather than through `STREAM_TOPICS`, so these tests say the same
    thing on this build and on the one where P6 puts the topic on the stream: what is
    under test is the producer, and the route is not its business.
    """
    got = []
    unsubscribe = bus.subscribe(mock_monitor.NS, (api.RAW_ECHO,),
                                lambda _topic, text: got.append(json.loads(text)))
    try:
        time.sleep(seconds)
    finally:
        unsubscribe()
    return got


def _summary_at(bus, source_id, step):
    """The summary the mock's echo produces for one source on one tick, or None.

    Built through the producer's own buffer -- the path `_pulse` takes -- so what is
    asserted below is the summary a real console would be handed, not a shape assembled
    for a test. The thread is not involved: waiting for step 46 to come round is not a
    test, it is a delay.
    """
    bus._echo.select(source_id)
    frame = bus._raw_echo(9, 9.0, step, bus._health(step, bus._stale_sources(step)),
                          bus._sensors(step))
    return None if frame is None else frame["summary"]


def test_nothing_is_echoed_until_a_console_asks_for_it(bus):
    """Off by default, and the default is the whole discipline. A point cloud per frame
    is not free and this console is usually across a link, so an echo nobody asked for
    is bandwidth spent on a pane nobody is looking at."""
    assert bus._echo is None or bus._echo.selected is None
    assert _echoes(bus) == []


def test_every_echo_frame_the_mock_publishes_validates(bus):
    """The same rule the rest of this fixture is held to: the envelope is the contract's,
    built by the shipped builder and passed by the shipped validator. `summary` is not --
    `api.build_raw_echo` says its shape is the adapter's business -- and that is exactly
    why the envelope around it has to be exact."""
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    _ask_echo(bus, "odom")
    got = _echoes(bus)
    assert got, "an echo was requested and nothing arrived"
    for frame in got:
        assert api.validate_for_topic(api.RAW_ECHO, frame) == []
        assert frame["source_id"] == "odom"
        assert isinstance(frame["summary"], dict)


def test_the_echo_is_one_source_at_a_time_and_a_null_stops_it(bus):
    """`{"source_id": null}` is the contract's stop, and a second request replaces the
    first rather than adding to it. That is why the console offers a picker and not a
    row of checkboxes: two sources at once is not a thing the wire can express."""
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    _ask_echo(bus, "odom")
    assert {f["source_id"] for f in _echoes(bus)} == {"odom"}

    _ask_echo(bus, "vision")
    assert {f["source_id"] for f in _echoes(bus)} == {"vision"}

    _ask_echo(bus, None)
    assert _echoes(bus) == []


def test_a_request_naming_no_declared_source_leaves_the_echo_alone(bus):
    """A source this adapter does not declare is refused, and refused means *nothing
    changes* -- not "the echo stops". An operator watching a camera must not lose it to
    somebody else's typo, and the console cannot send this request anyway: its picker is
    built out of the adapter's own `sources`.

    The rule is the producer's `RawEcho.select`, which the mock calls rather than
    reimplements. Asserted here because it is the console's pane that would go blank.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    _ask_echo(bus, "no_such_source")
    assert bus._echo.selected is None
    assert _echoes(bus) == []

    _ask_echo(bus, "odom")
    _ask_echo(bus, "no_such_source")
    assert bus._echo.selected == "odom"


def test_a_malformed_request_changes_nothing(bus):
    """The gateway's ingress route validates before it publishes, so a payload that got
    this far malformed did not come through the console. A fixture that acted on it
    would be more permissive than the system it stands in for."""
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    _ask_echo(bus, "odom")
    bus.publish(mock_monitor.NS, api.RAW_ECHO_REQUEST,
                json.dumps({"source_id": "vision"}))       # no schema_version
    assert api.validate_raw_echo_request({"source_id": "vision"}) != []
    assert bus._echo.selected == "odom"


def test_a_paused_monitor_echoes_nothing(bus):
    """A pause stops the watching, and the echo is part of the watching. A monitor that
    published no verdict and went on shipping camera frames would be a pane contradicting
    the banner above it -- and would be spending the link on a robot nobody is judging.

    The clock keeps going, which is what makes the silence measurable: the console ages
    the frame it is showing in ticks, so a paused echo is visibly a frozen one.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    _ask_echo(bus, "odom")
    assert _echoes(bus), "the echo did not start"
    _command(bus, "pause")
    assert _wait_until(lambda: bus._paused)

    assert _echoes(bus) == []
    assert api.TICK in _seen_after(bus)                 # and the clock did not stop

    _command(bus, "resume")
    assert _echoes(bus), "the echo did not come back with the monitor"


def test_no_frame_is_published_for_a_tick_the_source_missed(bus):
    """The depth camera drops out for six ticks in every sixty, and the echo goes quiet
    with it rather than re-sending the last frame. The console ages what it is showing
    and dims it once it stops being this tick's; a producer that filled the gap would be
    hiding the one thing that pane exists to show."""
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    step = 22                                            # inside the mock's dropout
    assert "points" in bus._stale_sources(step)
    assert bus._health(step, ["points"])["points"]["samples_this_tick"] == 0
    assert _summary_at(bus, "points", step) is None
    assert _summary_at(bus, "points", 0) is not None     # and the tick before it does


def test_the_echo_reports_the_cost_the_row_table_above_it_reports(bus):
    """`samples_this_tick` in the summary is the same number `data_health` gives for the
    same source on the same tick. Two fictions that disagreed would have an operator
    reading the zoom against the table and finding them inconsistent, which is the one
    thing a fixture must never teach somebody about the real system.

    And every summary carries the echo's own rate, whatever its kind: the echo is
    rate-limited to a stride of whole ticks, and "the camera is on" and "the camera is on
    and costing this much" are different things to know.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    step = 5
    health = bus._health(step, bus._stale_sources(step))
    for source in bus.adapter["sources"]:
        summary = _summary_at(bus, source["id"], step)
        if summary is None:
            continue
        assert summary["samples_this_tick"] == health[source["id"]]["samples_this_tick"]
        assert summary["topic"] == source["topic"]
        assert summary["every_n_ticks"] == bus._echo.every_n_ticks
        assert summary["rate_hz"] == bus._echo.rate_hz
        assert summary["rate_hz"] <= bus.tick_hz


def test_the_mock_demonstrates_every_rendering_the_page_has(bus):
    """`--mock` has to light up all four of the console's paths, because there is no
    other way to review them: an `image`, a `fields` value table, an `image_unavailable`
    with the producer's own reason sentence, and -- as a first-class case and not a
    fallback nobody exercises -- a `kind` this page has never heard of, which must render
    as a readable JSON dump rather than as an error.

    That last one is the extension point the opaque `summary` exists for. A depth or
    lidar summary written next month is a new `kind`, and the page must already show an
    operator something useful for it.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    step = 5
    kinds = {source["id"]: (_summary_at(bus, source["id"], step) or {}).get("kind")
             for source in bus.adapter["sources"]}
    assert "image" in kinds.values()
    assert "fields" in kinds.values()
    assert set(kinds.values()) - {"image", "fields", None}, (
        "no source demonstrates a kind the page has no renderer for", kinds)
    # And the unrenderable frame, on the tick the mock publishes one.
    unrenderable = _summary_at(bus, "points", mock_monitor._UNRENDERABLE[0])
    assert unrenderable["kind"] == "image_unavailable"
    assert "16UC1" in unrenderable["reason"]
    assert unrenderable["source_encoding"] == "16UC1"


def test_a_fields_summary_is_the_frame_the_observation_was_folded_from(bus):
    """The value table shows the keys that source feeds, read off the same fabricated
    frame as the row above it. A number in the echo and the same number in pane 3's
    `values this tick` column are one number, so a reviewer comparing them is comparing
    the thing the real system would show."""
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    step = 5
    sensors = bus._sensors(step)
    source = next(s for s in bus.adapter["sources"] if s["id"] == "odom")
    summary = _summary_at(bus, "odom", step)
    assert summary["kind"] == "fields"
    assert summary["values"] == {k: sensors[k] for k in source["keys"] if k in sensors}


def test_the_image_summary_carries_a_png_the_page_will_actually_load(bus):
    """A real `data:image/png;base64,...` and not a string shaped like one.

    The page checks the URI against an allowlist before it ever reaches an `img` src, so
    a mock that faked it would demonstrate the *rejection* path and never the rendering
    one -- and every review of this pane would be a review of the error message. The
    bytes are decoded here and their PNG header read, and the URI is then held against
    the page's own regular expression rather than against a second one written to agree
    with it.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    summary = _summary_at(bus, "points", 1)
    assert summary["kind"] == "image"
    assert _page_regex("DATA_IMAGE").fullmatch(summary["data_uri"])

    head, encoded = summary["data_uri"].split(",", 1)
    assert head == "data:image/png;base64"
    png = base64.b64decode(encoded, validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert summary["bytes"] == len(png)
    # IHDR is the first chunk, and its width and height are what the summary declares.
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (summary["width"], summary["height"])
    # The producer's box, and the frame the mock fabricated is bigger than it -- so the
    # downscale a real 320x240 bgr8 camera frame goes through is on this path too.
    assert (width, height) == (raw_echo.MAX_WIDTH, raw_echo.MAX_HEIGHT)
    assert (summary["source_width"], summary["source_height"]) == \
        (mock_monitor.ECHO_SOURCE_W, mock_monitor.ECHO_SOURCE_H)
    assert summary["source_encoding"] == "bgr8"


def test_the_mocks_camera_frame_costs_what_a_real_one_costs(bus):
    """A synthetic gradient compresses to nothing, and a pane that renders a 700-byte
    "camera frame" teaches a reviewer that the echo is free. Measured on the real G1, a
    160x120 photographic PNG is about 48 KB; the mock's frame is noisy on purpose so
    that the bytes-per-second line beside it is a number worth reading.

    Also within the producer's cap, which is the property that matters: a fixture that
    tripped the halving fallback every frame would review the fallback and never the
    normal path.
    """
    if not mock_monitor.WIRE_ADMITS_RAW_ECHO:
        pytest.skip("this build has no raw-echo topic, or no producer to summarise with")
    summary = _summary_at(bus, "points", 1)
    assert 20_000 < summary["bytes"] < raw_echo.MAX_DATA_URI_BYTES
    assert len(summary["data_uri"]) <= raw_echo.MAX_DATA_URI_BYTES
    assert "downscaled_to_fit" not in summary


def test_the_synthetic_frame_moves_and_could_not_be_a_camera(bus):
    """It has to be obviously fabricated, and it has to change: a still image would make
    a dead echo and a live one look identical, which is precisely the confusion the age
    counter beside it exists to prevent."""
    first = mock_monitor.synthetic_bgr8(1)
    assert first != mock_monitor.synthetic_bgr8(2)
    assert first == mock_monitor.synthetic_bgr8(1)          # and it is deterministic
    assert len(first) == mock_monitor.ECHO_SOURCE_W * mock_monitor.ECHO_SOURCE_H * 3
    # `bgr8`, which is what the G1's colour stream publishes -- so the producer's channel
    # swap is on the path `--mock` exercises rather than only on the robot's.
    frame = mock_monitor.synthetic_frame(1)
    assert frame.encoding == "bgr8"
    assert raw_echo.looks_like_image(frame)


def test_the_mock_echoes_the_moment_the_contract_admits_the_topic():
    """The `WIRE_ADMITS_*` gate again, and for the fourth time the same reason: the
    topic and its validators are P0's, a producer publishing frames the gateway's own
    ingress check would reject is the approximation this module is not allowed to be,
    and a flag someone has to remember to flip is a flag that stays unflipped.

    One extra term this time: the summaries are the producer's, so a build without
    `backend/adapters/raw_echo.py` has nothing to build them with and the mock echoes
    nothing rather than inventing a second convention. Asserted in both directions, so
    this passes on a build with the producer and on one without, and fails on a mock that
    guessed. Note what it is deliberately *not* gated on: whether the gateway forwards the
    topic to a browser. That is `STREAM_TOPICS`, it is P6's, and the mock is valid either
    way.
    """
    admits = (mock_monitor.echo_producer is not None
              and api.RAW_ECHO in api.TOPICS and api.RAW_ECHO_REQUEST in api.TOPICS
              and api.validate_for_topic(
                  api.RAW_ECHO, mock_monitor._probe_raw_echo()) == []
              and api.validate_for_topic(
                  api.RAW_ECHO_REQUEST,
                  api.build_raw_echo_request(source_id=None)) == [])
    assert mock_monitor.WIRE_ADMITS_RAW_ECHO is admits


# ================================================ pane 3's echo half, read off the page


def _page_regex(name):
    """A `const NAME = /.../;` from the page, as a Python pattern.

    The page's own literal and not a copy of it: a test that spelled the rule a second
    time would pass while the page allowed something else through, which for this
    particular rule -- what may be put in an `img` src -- is the failure worth catching.
    """
    match = re.search(rf"^const {name} = /(.+)/;$", _page(), re.M)
    assert match, f"the page has no `const {name} = /.../;`"
    return re.compile(match.group(1))


@pytest.mark.parametrize("uri", [
    "data:image/png;base64,iVBORw0KGgo=",
    "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
])
def test_the_page_loads_a_data_image_uri(uri):
    assert _page_regex("DATA_IMAGE").fullmatch(uri)


@pytest.mark.parametrize("uri", [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "https://example.invalid/x.png",
    "//example.invalid/x.png",
    "/api/monitors/g1/adapter",
    "data:text/html;base64,PHNjcmlwdD4=",
    # SVG is markup that carries script, and it is left out for the same reason `.svg`
    # is not in the gateway's STATIC_TYPES: this origin holds the X-Skill-Monitor grant
    # and the websocket Origin grant.
    "data:image/svg+xml;base64,PHN2Zz4=",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "data:image/png,notbase64",
    'data:image/png;base64,AAA" onerror="alert(1)',
    "data:image/png;base64,AAAA data:image/png;base64,AAAA",
    " data:image/png;base64,AAAA",
    "",
])
def test_the_page_refuses_anything_else_in_an_img_src(uri):
    """`data_uri` comes off the wire, and it is the one string on this page that becomes
    something the browser fetches. An allowlist, not a sanitiser: everything that is not
    a whole base64 data URI of a raster image type fails, and what fails is *reported*
    to the operator rather than loaded."""
    assert _page_regex("DATA_IMAGE").fullmatch(uri) is None


def test_the_page_puts_nothing_but_a_checked_uri_in_an_img_src():
    """The check and the sink, pinned together. There is one `img` in the page, its src
    is the value `imageSrc` returned, and the branch above it is what happens when
    `imageSrc` said no -- so there is no way to reach the sink without the check."""
    page = _page()
    # One interpolated URL sink in the whole page, and this is it.
    assert page.count('src="${') == 1
    assert 'src="${esc(src)}"' in page
    body = _fn(page, "echoImage")
    assert body.count("<img") == 1
    assert "const src = imageSrc(sum.data_uri);" in body
    assert "if (src === null) {" in body
    check = _fn(page, "imageSrc")
    assert 'if (typeof uri !== "string") return null;' in check
    assert "DATA_IMAGE.test(uri) ? uri : null" in check
    # And the size cap, so one frame cannot be a per-tick megabyte of DOM.
    assert "if (uri.length > DATA_URI_MAX) return null;" in check


def test_the_page_asks_for_the_echo_with_the_payload_the_contract_validates():
    """`api.build_raw_echo_request`'s shape, and nothing else: `{schema_version,
    source_id}`, with `null` for the stop. The literal the page builds is asserted, and
    then the shipped validator is asked about that exact literal -- a payload the route
    rejects is a 400 and a picker that does nothing."""
    page = _page()
    assert ("JSON.stringify({ schema_version: SCHEMA_VERSION, source_id: sourceId })"
            in page)
    for source_id in ("points", None):
        assert api.validate_raw_echo_request(
            {"schema_version": api.SCHEMA_VERSION, "source_id": source_id}) == []
        assert api.build_raw_echo_request(source_id=source_id) == {
            "schema_version": api.SCHEMA_VERSION, "source_id": source_id}
    # Through the one `fetch` wrapper, which is where X-Skill-Monitor lives: a
    # hand-rolled fetch here is a 403 the operator reads as a broken robot.
    assert "fetch(" not in _fn(page, "echoAsk")
    assert 'method: "POST"' in _fn(page, "echoAsk")


def test_the_page_offers_one_source_at_a_time_and_an_explicit_off():
    """A picker, not checkboxes: two sources at once is not something the wire can
    express. And an option that says off in words, because "none selected" and "the echo
    is off" have to be the same visible thing."""
    page = _page()
    picker = _fn(page, "renderEcho")
    assert '<option value="">off — nothing is echoed</option>' in picker
    # The options are the adapter's own sources. No source list is spelled in this page.
    assert "sources.map(s =>" in picker
    assert "echoAsk($(\"echo-pick\").value || null)" in picker
    # An empty selection is the null the contract stops on, not the string "".
    state = _fn(page, "updateEchoControls")
    assert 'S.ech.on === null' in state
    assert "off — nothing is echoed, and nothing is by default" in state


def test_the_page_shows_what_is_echoing_and_never_what_was_merely_clicked():
    """A request that was refused turned nothing on. Leaving the picker on the source it
    named would be the page claiming an echo it has no evidence for -- so the control is
    re-synced from `S.ech.on`, and `S.ech.on` moves only on an answer under 400."""
    page = _page()
    ask = _fn(page, "echoAsk")
    assert "} else if (r.status < 400) {" in ask
    assert ask.index("S.ech.on = sourceId;") > ask.index("r.status < 400")
    assert "pick.value = S.ech.on === null ? \"\" : S.ech.on;" in _fn(
        page, "updateEchoControls")


def test_the_page_disables_the_picker_and_says_why_when_there_is_no_route():
    """No ingress route is a dead control, and a dead control that looks live is worse
    than an absent one. The same answer both disables the picker and is printed beside
    it, and the route is learned from the wire -- a 404 or a 405 -- and never guessed
    at."""
    page = _page()
    refusal = _fn(page, "echoRefusal")
    assert "if (!S.seg)" in refusal
    assert 'if (S.ech.route === "absent")' in refusal
    assert "S.ech.busy" in refusal
    assert f"no {api.ADAPTER} is latched" in refusal
    ask = _fn(page, "echoAsk")
    assert "if (r.status === 404 || r.status === 405) {" in ask
    assert 'S.ech.route = "absent";' in ask
    controls = _fn(page, "updateEchoControls")
    assert "pick.disabled = why !== null;" in controls
    assert '$("echo-why").innerHTML' in controls
    # And a refusal that is not a missing route says so with its status and its body,
    # the way the command strip and the clock's step button report one.
    assert "the echo request was refused (${txt(r.status)})" in ask


def test_the_page_says_a_requested_echo_that_never_arrived_is_not_a_frame():
    """Requested and silent is its own state, and it is not the same as off and not the
    same as showing something. Both reasons it could be silent are named -- the producer
    or the route -- rather than one of them being guessed at."""
    frame = _fn(_page(), "renderEchoFrame")
    assert "was requested" in frame
    assert f"no <code>{api.RAW_ECHO}</code> frame has arrived" in frame
    assert "api.RAW_ECHO" in frame and "STREAM_TOPICS" in frame


def test_the_page_stops_showing_the_frame_when_the_echo_stops():
    """The one thing an operator must never see: a picture still on screen after they
    turned the source off. The frame is dropped on the stop and on a switch -- a frame of
    what was echoing before is not a frame of what is echoing now -- and the off branch
    renders no frame at all even if one arrives late."""
    page = _page()
    assert "S.ech.frame = null;" in _fn(page, "echoAsk")
    off = _fn(page, "renderEchoFrame")
    assert "the echo is off, and a frame for" in off
    assert "It is not drawn, because it is not this console's echo." in off


def test_the_page_ages_the_frame_in_ticks_and_dims_it_when_it_is_stale():
    """Not this browser's clock: under replay and under a manual clock a wall-clock age
    is wrong, for the same reason the state banner measures in ticks. And the answer is
    carried twice -- the words and a class that dims and greys the picture -- because a
    screenshot of a stale frame with only a colour to say so is a screenshot somebody
    misreads."""
    page = _page()
    age = _fn(page, "renderEchoAge")
    assert "latestSeq()" in age
    assert "const ticks = now - f.seq;" in age
    assert "Date.now" not in age and "performance.now" not in age
    assert "ticks old" in age
    assert 'body.classList.toggle("stale", stale)' in age
    assert "#echo-body.stale img" in page
    # The two it cannot compute, each said rather than guessed: no seq to measure
    # against, and a frame ahead of the newest seq this page has seen.
    assert "age unknown" in age
    assert "ahead of this page" in age and "no age is" in age
    # The age moves with the clock, so a paused monitor's frame visibly goes stale.
    assert "renderEchoAge()" in _fn(page, "connect")


def test_an_unrecognised_kind_renders_and_is_not_an_error():
    """The extension point, and the reason `summary` is opaque on the wire at all:
    `api.build_raw_echo` says its shape is the adapter's business so that a new sensor
    type does not edit the contract. A page that treated an unknown `kind` as a fault
    would put that cost straight back."""
    page = _page()
    summary = _fn(page, "echoSummary")
    assert 'if (kind === "image") return echoImage(sum);' in summary
    assert 'if (kind === "fields") return echoFields(sum);' in summary
    assert "this console has no renderer for it" in summary
    assert "echoJson(sum)" in summary
    # It is a dump of the summary, clipped, and not an error message.
    dump = _fn(page, "echoJson")
    assert "JSON.stringify(value, null, 2)" in dump
    assert "ECHO_JSON_MAX" in dump


def test_the_page_says_so_when_there_is_no_summary_and_no_kind():
    """Three absences, three sentences. An envelope with no `summary`, a summary with no
    `kind`, and a `kind: image` whose `data_uri` is not an image -- each one said, and
    none of them rendered as a blank box or as the last thing that worked."""
    page = _page()
    summary = _fn(page, "echoSummary")
    assert "the frame carries no <code>summary</code> object" in summary
    assert "the summary carries no <code>kind</code>" in summary
    image = _fn(page, "echoImage")
    assert "is not one this page will load" in image
    assert "Not rendered, and\n        not fetched." in image
    fields = _fn(page, "echoFields")
    assert "carries no <code>values</code> object" in fields


def test_the_page_shows_what_the_echo_costs_beside_what_it_produced():
    """An operator turning a camera on over a field link should be able to see what they
    turned on: the samples, the rate the echo actually runs at, and the bytes, beside the
    picture rather than under it.

    The rate matters because it is not the tick rate. The producer limits the echo to a
    stride of whole ticks and reports `rate_hz` and `every_n_ticks`, so a per-second cost
    figured against the tick would be wrong by that stride -- and the line says which
    clock it used.
    """
    page = _page()
    facts = _fn(page, "echoFacts")
    assert "samples this tick" in facts and "echoSamples(sum)" in facts
    assert "echoRate(sum)" in facts and "echo rate" in facts
    assert "echoBytes(sum)" in facts
    rate = _fn(page, "echoRate")
    assert "sum.rate_hz" in rate and "sum.every_n_ticks" in rate
    cost = _fn(page, "echoBytes")
    assert "S.adapter || {}).tick_hz" in cost
    assert "the echo's rate" in cost and "the adapter's tick rate" in cost
    # A stride means `samples_this_tick` counts a window and not a tick, and saying
    # "this tick" over a five-tick window would be wrong by four ticks of messages.
    samples = _fn(page, "echoSamples")
    assert "the skipped ones included" in samples
    image = _fn(page, "echoImage")
    assert "sum.width" in image and "sum.height" in image
    assert "encoding" in image


def test_the_page_says_a_frame_it_could_not_render_and_why():
    """`image_unavailable` is a normal outcome, not a fault: a depth topic is the first
    thing an operator clicks, and `16UC1` is not something any echo can turn into a
    picture. The producer writes the reason as a sentence for a human, so it is rendered
    as one -- beside the source's own dimensions and encoding -- rather than falling
    through to the JSON dump, which answers nothing.

    And no picture rather than a wrong one: a frame decoded with the wrong stride renders
    as a plausible image of nothing, which is the one output an operator cannot act on.
    """
    page = _page()
    summary = _fn(page, "echoSummary")
    assert ('if (kind === "image_unavailable") return echoImageUnavailable(sum);'
            in summary)
    body = _fn(page, "echoImageUnavailable")
    assert "sum.reason" in body
    assert "no picture from this source" in body
    assert "source_encoding" in body and "source_width" in body
    assert "source_bytes" in body
    # A summary of this kind with no reason on it says that, rather than showing blank.
    assert "gives no <code>reason</code>" in body
    # This kind is rendered, so it must not reach the unknown-kind dump.
    assert "echoJson" not in body


def test_the_page_says_when_a_frame_was_shrunk_to_fit_the_cap():
    """The producer halves a frame that will not fit its data-URI cap. A console that
    drew the smaller picture without saying so would be telling an operator the camera
    sent that, and the detail they went looking for went missing somewhere they cannot
    see."""
    image = _fn(_page(), "echoImage")
    assert "sum.downscaled_to_fit === true" in image
    assert "sum.cap_bytes" in image
    # And the source's own size beside the size that was sent, so the reduction is a
    # number rather than a suspicion.
    assert "sum.source_width" in image and "sum.source_encoding" in image


def test_the_page_posts_to_the_route_the_gateway_serves():
    """`INGRESS_TOPICS`'s key for the request topic is the verb, and the page spells it
    once. A page that guessed a different one would render a permanently dead picker with
    a perfectly good route sitting next to it."""
    page = _page()
    verb = next(v for v, t in gateway.INGRESS_TOPICS.items() if t == api.RAW_ECHO_REQUEST)
    assert f'const ECHO_VERB = "{verb}";' in page
    assert ("api(`/api/monitors/${S.seg}/${ECHO_VERB}`, { method: \"POST\", body })"
            in page)


def test_the_page_does_not_stretch_a_camera_frame_to_fill_the_pane():
    """160x120 blown up to the pane's width is a picture of the pane. Natural size,
    capped, and never `width:100%`."""
    page = _page()
    style = page[page.index("#echo img {"):page.index("#echo pre {")]
    assert "width:auto" in style and "height:auto" in style
    assert "max-width:320px" in style
    assert "width:100%" not in style


# ============================================ the monitor controls, from the mock's end
#
# The console can now stop the monitor, and a stopped monitor is a moving robot with
# nothing watching it. So the fixture the controls are reviewed against has to actually
# stop -- a mock whose values keep changing under a pause would make every review of this
# feature a review of a control that does nothing.


def _command(bus, command):
    """One command in, by the path `POST /api/monitors/{ns}/command` takes: the
    gateway validates `api.build_command`'s payload and publishes it verbatim."""
    payload = api.build_command(command=command)
    assert api.validate_command(payload) == []
    bus.publish(mock_monitor.NS, api.COMMAND, json.dumps(payload))


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _seen_after(bus, seconds=0.05):
    """Which streamed topics the mock puts on the wire over `seconds`, starting now."""
    seen = set()
    unsubscribe = bus.subscribe(mock_monitor.NS, gateway.STREAM_TOPICS,
                                lambda topic, _text: seen.add(topic))
    try:
        time.sleep(seconds)
    finally:
        unsubscribe()
    return seen


def test_the_mock_honours_every_command_the_contract_declares(bus):
    """`--mock` is the only way this console is developed or reviewed on a host with no
    ROS. A command it accepts and drops is a button that looks like it worked."""
    for command in api.COMMANDS:
        _command(bus, command)
        assert bus._state in mock_monitor.MONITOR_STATES
        assert bus._paused is (bus._state != "running")
    assert bus._state == "running"          # `resume` is the last of them


def test_a_paused_mock_stops_its_automata_its_phases_and_its_verdicts(bus):
    """The control has to be real. A paused monitor steps no automaton, changes no phase
    and publishes no verdict -- so the panes the console draws from freeze, which is the
    visible half of "nothing is watching the robot".

    The clock does not stop with it: `seq` goes on counting, because that is the axis the
    banner measures `since_seq` against and the only thing that lets it say how long the
    robot has been running unwatched.
    """
    frames(bus)                                     # running, and getting somewhere
    _command(bus, "pause")
    time.sleep(0.05)                                # let the pulse thread reach the gate
    step, states, seq = bus._step, dict(bus._auto_state), bus._seq

    seen = _seen_after(bus)
    assert bus._step == step                        # the episode's step counter
    assert bus._auto_state == states                # every automaton
    assert bus._phase_at(bus._step) == bus._phase_at(step)      # and the phase machine
    assert api.TICK in seen                         # the clock runs
    assert api.VERDICT not in seen                  # the monitor does not
    assert api.OBSERVATION not in seen
    assert bus._seq > seq


def test_a_paused_monitor_and_a_dead_one_are_the_same_silence(bus):
    """Why the state needs a topic of its own, asserted rather than argued. Every other
    signal a console has -- verdicts, observations, `last_seen` freshness -- says exactly
    the same thing about a paused monitor as about one whose process died. The mock is
    held to that rather than faking a freshness on the monitor's behalf, because a page
    that could tell them apart from the silence would not need the banner."""
    frames(bus)
    _command(bus, "pause")
    time.sleep(0.05)
    last_seen = bus.last_seen(mock_monitor.NS)
    seen = _seen_after(bus)
    assert bus.last_seen(mock_monitor.NS) == last_seen
    # And the clock is running through all of it, which is what makes the silence a
    # statement about the monitor rather than about the whole stack.
    assert api.TICK in seen
    # Everything else is exactly as quiet as it would be if the process had died --
    # except the state topic, which is the only thing on this wire that says which of
    # the two this is. That asymmetry is the entire design.
    assert seen - {api.TICK} == ({mock_monitor.STATUS_TOPIC}
                                 if mock_monitor.WIRE_ADMITS_STATUS else set())


def test_a_resumed_mock_starts_advancing_again(bus):
    """The other half: a control that stops and cannot start is not a control either."""
    frames(bus)
    _command(bus, "pause")
    time.sleep(0.05)
    step = bus._step
    _command(bus, "resume")
    assert _wait_until(lambda: bus._step > step), "resume did not restart the stepping"
    assert bus._state == "running" and bus._paused is False


@pytest.mark.parametrize("command", ["arm", "reset"])
def test_arm_and_reset_restart_the_episode_and_discard_its_history(bus, command):
    """The consequence the console makes the operator confirm, asserted at the end that
    has to honour it: the step counter goes back to zero and every automaton returns to
    its initial state -- and the monitor comes back *running*, because arming into a
    paused state would be a control that appeared to work and did not.

    Asserted as "the step went backwards" rather than as "the step is 0": the pulse
    thread is running and the counter starts climbing again immediately.
    """
    assert _wait_until(lambda: bus._step > 5), "the mock never got going"
    _command(bus, "pause")
    time.sleep(0.05)
    before = bus._step
    _command(bus, command)
    assert bus._step < before
    assert bus._auto_state == mock_monitor._initial_states(bus._automata)
    assert bus._state == "running" and bus._paused is False
    assert bus._state_reason == f"operator command: {command}"


def test_since_seq_moves_only_when_the_state_does(bus):
    """`since_seq` is how long the robot has been unwatched, and the console renders it
    against the current tick. A second `pause` on an already-paused monitor must not
    reset that count back to zero -- the robot has been unwatched since the first one."""
    _command(bus, "pause")
    first = bus._state_since
    assert bus._state == "paused"
    time.sleep(0.02)
    _command(bus, "pause")
    assert bus._state_since == first
    _command(bus, "resume")
    assert bus._state == "running" and bus._state_since >= first


def test_the_status_payload_is_the_shape_the_console_reads(bus):
    """The contract the banner was written against: a closed field set, a state from the
    declared vocabulary, and two fields that are genuinely nullable. `reason: null` and
    `since_seq: null` are values the console renders as their own sentence, so the mock
    has to be able to produce the shape they live in."""
    payload = bus._status_payload()
    assert set(payload) == {"schema_version", "seq", "t",
                            "state", "reason", "since_seq"}
    assert payload["schema_version"] == api.SCHEMA_VERSION
    assert payload["state"] in mock_monitor.MONITOR_STATES
    assert payload["reason"] is None or isinstance(payload["reason"], str)
    assert payload["since_seq"] is None or isinstance(payload["since_seq"], int)
    nullable = mock_monitor._probe_status(reason=None, since_seq=None)
    assert nullable["reason"] is None and nullable["since_seq"] is None
    # The vocabulary is the contract's and not a second opinion about it.
    if hasattr(api, "RUN_STATES"):
        assert mock_monitor.MONITOR_STATES == tuple(api.RUN_STATES)


def test_the_state_a_monitor_starts_in_names_no_tick_it_never_counted(bus):
    """`since_seq: null` at startup, and it is not the same as zero. Nothing has been
    ticked, so there is no tick the running began at, and a 0 would be a tick this
    monitor is claiming to have counted. The console renders it as a length it cannot
    measure rather than as "running for 0 ticks"."""
    fresh = mock_monitor.MockBus(rate_scale=200.0)
    try:
        assert fresh._state == "running"
        assert fresh._state_reason == "monitor started"
        assert fresh._state_since is None
        payload = fresh._status_payload()
        assert payload["since_seq"] is None
        if mock_monitor.WIRE_ADMITS_STATUS:
            assert api.validate_for_topic(mock_monitor.STATUS_TOPIC, payload) == []
    finally:
        fresh.shutdown()


def test_a_console_that_connects_during_a_pause_is_told_at_once(bus):
    """The reason the state is latched *and* streamed, at the end that has to honour it.

    A paused monitor publishes nothing else at all, so a stream that only carried
    changes would tell a console connecting mid-pause nothing until the operator who
    caused the pause ended it. The real bus subscribes to a latched topic with
    TRANSIENT_LOCAL and DDS replays the last sample; the mock replays it itself, so the
    fixture the console is reviewed against does not have the one gap the design is
    built to close.
    """
    if not mock_monitor.WIRE_ADMITS_STATUS:
        pytest.skip("this build's contract has no monitor-state topic")
    frames(bus)
    _command(bus, "pause")
    time.sleep(0.05)

    # A console arriving now, into a wire on which nothing but the clock is moving.
    late = {}
    unsubscribe = bus.subscribe(
        mock_monitor.NS, gateway.STREAM_TOPICS,
        lambda topic, text: late.setdefault(topic, json.loads(text)))
    try:
        assert mock_monitor.STATUS_TOPIC in late, "the pause was not replayed"
        assert late[mock_monitor.STATUS_TOPIC]["state"] == "paused"
        assert late[mock_monitor.STATUS_TOPIC]["since_seq"] is not None
        assert api.VERDICT not in late              # and nothing else says so
    finally:
        unsubscribe()


def test_the_mock_reports_a_state_the_moment_the_contract_admits_the_topic(bus):
    """The `WIRE_ADMITS_*` gate again, and for the third time the same reason: the topic
    is P0's to declare, a producer publishing on a topic with no `VALIDATORS` entry sends
    frames the gateway's own ingress check would reject, and a flag someone has to
    remember to flip is a flag that stays unflipped. The gate is the validator's answer,
    asserted here in both directions -- so this test passes on a build without the topic
    and on the build where it lands, and fails on a mock that guessed.

    The topic is found by its last segment, which is also the gateway's route verb for
    it: `LATCHED_ROUTES` is derived from the topic name, so the console's
    `GET /api/monitors/{seg}/status` appears with no edit to `gateway.py`.
    """
    expected = f"{api.VERDICT.rsplit('/', 1)[0]}/{mock_monitor.STATUS_VERB}"
    assert (mock_monitor.STATUS_TOPIC == expected) is (expected in api.TOPICS)
    assert mock_monitor.WIRE_ADMITS_STATUS is (
        mock_monitor.STATUS_TOPIC is not None
        and api.validate_for_topic(mock_monitor.STATUS_TOPIC,
                                   mock_monitor._probe_status()) == [])

    latched = bus.latched(mock_monitor.NS, mock_monitor.STATUS_TOPIC)
    assert (latched is not None) is mock_monitor.WIRE_ADMITS_STATUS
    if mock_monitor.WIRE_ADMITS_STATUS:
        assert api.validate_for_topic(
            mock_monitor.STATUS_TOPIC, json.loads(latched)) == []
        _command(bus, "pause")
        after = json.loads(bus.latched(mock_monitor.NS, mock_monitor.STATUS_TOPIC))
        assert after["state"] == "paused"
        assert api.validate_for_topic(mock_monitor.STATUS_TOPIC, after) == []
    else:
        # No topic, so nothing to publish on -- and the console's degrade path is what
        # `--mock` demonstrates today. The mock still *has* a state; it just cannot say
        # so, which is exactly the build the banner has to survive.
        assert bus._state == "running"


# ================================== the controls and the banner, read off the page
#
# The same split as panes 6 and 7, for the same reason: there is no JavaScript test
# runner in this repo. What is asserted here is the source, and it is asserted at the
# points where a rewrite would quietly turn a safety control into a decoration.


def _block(page, opening):
    """The body of a top-level `const NAME = {` ... `\n};` declaration, with the closing
    newline kept so the last entry ends the way every other one does."""
    start = page.index(opening) + len(opening)
    return page[start:page.index("\n};", start)] + "\n"


def _fn(page, name):
    """The body of a top-level `function name(...)`, which ends at the first `}` in
    column zero -- everything inside the page's functions is indented."""
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}", start)]


def _code(text):
    """The same text with its comments taken out.

    For the handful of assertions that say a construct is *gone*: the comment that
    records why it went names it, and a bare `in page` would then be satisfied by the
    epitaph. This is a blunt strip -- it does not know about `//` inside a string -- and
    it is only ever used to make a negative assertion stricter."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def test_the_page_offers_exactly_the_commands_the_contract_declares():
    """A command in `api.COMMANDS` and not in this list is a control the console silently
    does not offer; one here and not there is a 400 from the gateway. Pinned against the
    constant, so the contract moving fails here rather than in a browser."""
    page = _page()
    assert "const COMMANDS = [" + ", ".join(
        f'"{c}"' for c in api.COMMANDS) + "];" in page
    for command in api.COMMANDS:
        assert f'id="cmd-{command}"' in page, command


def test_the_page_posts_the_payload_the_command_route_validates():
    """`POST .../command` runs `api.validate_for_topic` and hands the problem list back
    to the client, so a payload missing its envelope version is a 400 and a dead button.
    The literal the page builds is asserted, and then the validator is asked about that
    exact literal."""
    page = _page()
    assert f"const SCHEMA_VERSION = {api.SCHEMA_VERSION};" in page
    assert "JSON.stringify({ schema_version: SCHEMA_VERSION, command: cmd })" in page
    assert "api(`/api/monitors/${S.seg}/command`, {" in page
    for command in api.COMMANDS:
        assert api.validate_command(
            {"schema_version": api.SCHEMA_VERSION, "command": command}) == []
    # And it goes through the one `fetch` wrapper, which is where X-Skill-Monitor lives:
    # a hand-rolled fetch here is a 403 the operator reads as a broken monitor.
    assert "fetch(" not in _fn(page, "command")


def test_the_page_confirms_the_three_commands_that_cannot_be_taken_back():
    """`arm` and `reset` throw the episode away; `pause` leaves the robot moving with
    nothing watching it. `resume` is the one that puts the watching back and asks
    nothing. The confirmations have to name the consequence rather than ask "are you
    sure", which is a question nobody reads."""
    page = _page()
    block = _block(page, "const CMD = {")
    for command in api.COMMANDS:
        entry = re.search(rf"\n  {command}: \{{(.*?)\}},\n", block, re.S)
        assert entry, command
        assert ("confirm:" in entry.group(1)) is (command != "resume"), command
    assert "IT DOES NOT STOP THE ROBOT" in block
    assert block.count("restarts the episode") == 2
    assert "if (ask && !window.confirm(ask))" in page


def test_the_page_reports_a_refused_command_the_way_it_reports_a_refused_step():
    """The clock's step button prints the status and the body of a 503 rather than
    swallowing it, and the same refusal from the command route has to read the same way:
    a control that fails silently is a control the operator believes worked."""
    page = _page()
    # Three now: the clock's step, the command strip, and pane 3's echo request. Every
    # control on this page that can be refused reports the refusal the same way.
    assert page.count("r.text.slice(0, 300)") == 3
    assert "step refused (${r.status})" in page
    assert "refused (${txt(r.status)})" in page
    # A 202 is "published", not "done". The state is the monitor's own answer.
    assert "published (${txt(r.status)})" in page
    assert "this page does not assume" in page


def test_the_page_never_reads_the_state_from_the_absence_of_verdicts():
    """The bug this whole feature exists to fix. A paused monitor publishes no verdicts
    and a dead one publishes none either, so any inference from silence gets one of the
    two wrong -- and it is the dangerous one it gets wrong.

    Asserted structurally: the only two things ever assigned to the state are a payload
    off the status topic and `null`.
    """
    page = _page()
    assert re.findall(r"S\.mon\.status = ([^;]+);", page) == [
        "null",
        '(payload && typeof payload === "object") ? payload : null',
    ]
    banner = _fn(page, "renderStateBanner")
    assert "S.mon.status" in banner
    for inferred in ("S.verdict", "S.connected", "last_seen", "missed_ticks"):
        assert inferred not in banner, inferred


def test_the_page_names_the_field_and_its_owner_when_no_state_is_reported():
    """The build without the producer half is this one, so this is the path `--mock`
    actually shows today. It gets the same placeholder every other unreported field on
    the page gets -- the field, its owner, and no inference -- rather than a console
    quietly drawing a monitor that is running."""
    page = _page()
    topic = f"{api.VERDICT.rsplit('/', 1)[0]}/{mock_monitor.STATUS_VERB}"
    assert f'missing("{topic}", "P0, then P4"' in page
    assert "STATE UNREPORTED" in page
    # The two silences a 404 can be, told apart by whether the gateway's error names the
    # topic it looked for: no route in this build, or a route and a monitor that has
    # never published one.
    assert "S.mon.route = !!body.topic;" in page


def test_the_page_treats_an_unrecognised_state_as_unknown_and_not_as_running():
    """`state` absent, `state` null, `state` a word this console has no meaning for: all
    three are unknown, all three raise the banner, and none of them is running."""
    page = _page()
    banner = _fn(page, "renderStateBanner")
    assert 'const name = typeof s.state === "string" ? s.state : null;' in banner
    assert "Object.prototype.hasOwnProperty.call(MON_STATES, name)" in banner
    assert "const alarm = !known || meta.alarm;" in banner
    assert "STATE UNKNOWN" in banner
    assert "never as running" in banner


def test_the_banner_does_not_carry_the_state_in_colour_alone():
    """A monochrome screen, a colour-blind operator, a photograph of the screen sent to
    somebody else. The state is a word, in capitals, beside a glyph -- and every state
    that is not `running` says the same three words, so the alarm is one thing to
    recognise rather than four."""
    page = _page()
    block = _block(page, "const MON_STATES = {")
    for state in mock_monitor.MONITOR_STATES:
        entry = re.search(rf"\n  {state}: \{{(.*?)\}},\n", block, re.S)
        assert entry, state
        assert ("alarm: false" in entry.group(1)) is (state == "running"), state
        assert "mark:" in entry.group(1) and "says:" in entry.group(1), state
    assert block.count('mark: "NOT MONITORING"') == 3
    assert 'class="mark"' in page
    # And it is in the sticky header rather than in a pane, so it is read without
    # scrolling to the strip that caused it.
    assert page.index('id="mon-banner"') < page.index('<div class="grid">')
    assert "header .row" in page


def test_the_page_disables_the_controls_and_says_why_when_it_cannot_send():
    """A dead button that looks live is worse than an absent one. The same answer both
    disables the buttons and is printed beside them, so there is no way to have one
    without the other.

    And the monitor's *state* is deliberately not one of the reasons: the command route
    does not depend on the status topic, and taking the robot's stop button away over a
    field no producer publishes yet would be a worse failure than the one it prevents.
    """
    page = _page()
    refusal = _fn(page, "controlRefusal")
    assert "if (!S.seg)" in refusal                          # no monitor selected
    assert 'if (S.mon.post === "absent")' in refusal          # no POST route
    assert "S.mon.busy" in refusal                           # one in flight
    assert "S.mon.status" not in refusal and "S.mon.state" not in refusal
    controls = _fn(page, "updateControls")
    assert 'disabled = why !== null' in controls
    assert '$("cmd-why").innerHTML' in controls
    # The route is learned from the wire -- a 404 or a 405 -- and never guessed at.
    assert "if (r.status === 404 || r.status === 405) {" in page


def test_the_banner_measures_the_state_against_the_tick_and_not_this_browsers_clock():
    """How long the robot has been unwatched, in the unit the wire gives. A wall-clock
    duration measured in the browser would be wrong under replay, wrong under a manual
    clock, and wrong by the width of the link at every other time."""
    page = _page()
    body = _fn(page, "sinceText")
    assert "since_seq" in body and "latestSeq()" in body
    assert "const ticks = now - since;" in body
    assert "Date.now" not in body and "performance.now" not in body
    # The three things it cannot compute, each said rather than guessed: no `since_seq`,
    # no seq to measure against, and a `since_seq` ahead of the newest seq seen.
    assert body.count("no <code>since_seq</code>") == 1
    assert "nothing to measure it against" in body
    assert "no duration is derived from that" in body


def test_the_page_re_reads_the_state_after_a_gap_it_did_not_watch():
    """A reconnect is a hole, and another operator may have paused the monitor inside it.
    The state is latched precisely so it can be re-read; trusting the one held across the
    gap would be the console asserting something about a period nobody was watching."""
    page = _page()
    assert "refreshMonitorStatus()" in _fn(page, "connect")
    assert "await refreshMonitorStatus();" in _fn(page, "boot")


# ================================ tier 1: the wall band, read off the page
#
# The same split as every other pane, and the same reason: there is no JavaScript test
# runner in this repo. What is asserted below is the page's source, at the points where
# a rewrite would quietly turn "what the monitor said" into "what the page worked out".
#
# What was instead driven by hand, in headless Chrome over CDP against
# `python3 -m skill_monitor.frontend.web --mock`, and is recorded here so the next
# reader knows it was checked rather than assumed:
#
#   * the band renders VIOLATED with `collision_imminent` — SAFETY, confidence 1 —
#     beside it, and the automata light `aut0n4 / aut1n1 / aut2n0` on the same verdict;
#   * with no VIOLATED row it reads "no row on this verdict is VIOLATED / 3 rows:
#     2 ACCEPTED · 1 INCONCLUSIVE", and adds the warning line when the verdict says
#     VIOLATED anyway;
#   * `terminal` takes the band over — `#wall` gains `.over`, the hero drops from 51px
#     to 35px, and SUCCESS / FAILURE / an unrecognised word each render their own
#     sentence; `null` renders nothing and the class comes off;
#   * a node's text renders at ~17.8 screen px in a 1920-wide band against ~7px before;
#   * `A+` twice moves `:root` 13px → 17px and the number survives a reload, as does a
#     pane opened by hand (`skillmon.pane.plots`);
#   * every degrade path below, with the field deleted off the live payload.


def _style(page):
    """The page's one `<style>` block."""
    match = re.search(r"<style>(.*?)</style>", page, re.S)
    assert match
    return match.group(1)


#: The band's own render functions, for the properties that hold across all of them.
_WALL_FNS = ("renderWall", "renderWallTerminal", "renderWallVerdict", "wallCause",
             "wallRests", "renderWallAction", "renderWallWhere", "drivingRow",
             "wallStale", "declaredAs", "rowDeclared")


def test_the_wall_is_the_first_thing_on_the_page_and_carries_the_two_readings():
    """Tier 1 is above the grid and outside it. The two things an operator across a room
    is reading -- the verdict with why, and the automaton with its live state -- were a
    fold and two grid columns apart: the header said VIOLATED and the row that drove it
    was the last thing in pane 6."""
    page = _page()
    assert page.index('<section id="wall">') < page.index('<div class="grid">')
    # The header's banner still comes before both: a paused monitor is read before
    # anything the paused monitor said.
    assert page.index('id="mon-banner"') < page.index('<section id="wall">')
    for cell in ("wall-terminal", "wall-verdict", "wall-why", "wall-act", "wall-where",
                 "wall-graphs", "wall-rows"):
        assert f'id="{cell}"' in page, cell
    # And it is rendered from the verdict, on the verdict.
    assert "renderHeader(); renderWall(); renderAutomaton();" in page


def test_the_band_names_the_row_the_verdict_rests_on_the_way_the_monitor_does():
    """`breached_mode` scans for a VIOLATED SAFETY mode wherever it sits before falling
    back, because a de-escalated SAFETY entry still outranks a VIOLATED PROGRESS one
    that grades above it. The band picks by that rule -- and it *picks*, from rows the
    verdict already carries. It does not grade: the ladder runs on confidences and
    imminences this page cannot see, and a second grader in a browser would report a
    rung the monitor never chose."""
    page = _page()
    body = _fn(page, "drivingRow")
    assert 'r.status === "VIOLATED"' in body
    assert 'r.fault_category === "SAFETY"' in body
    # Safety first, then any violated row, and the fallback is the *first* such row.
    assert body.index("const safety") < body.index("const row = safety || violated[0];")
    # Nothing violated is null, and never a row chosen anyway.
    assert "if (!violated.length) return null;" in body
    # Both row kinds are candidates, and which kind it was is reported.
    assert "failure_modes" in body and "formulas" in body
    assert '"failure mode"' in body and '"formula"' in body
    # No grading here: none of the ladder's inputs is compared against anything.
    for graded in ("MIN_CONFIDENCE", "confidence >", "confidence <", "grade"):
        assert graded not in body, graded
    cause = _fn(page, "wallCause")
    assert "d.others" in cause and "other VIOLATED" in cause


def test_the_band_says_what_the_verdict_rests_on_when_nothing_is_violated():
    """No VIOLATED row means there is no cause to name, and the band must not invent
    one. What it prints instead is a count off the rows the verdict carries -- counting
    is not inferring -- and when the verdict itself says VIOLATED with no VIOLATED row
    on it, that disagreement is printed rather than resolved."""
    page = _page()
    body = _fn(page, "wallRests")
    assert "no row on this verdict is VIOLATED" in body
    assert 'v.verdict === "VIOLATED"' in body
    assert "This band names no cause" in body
    # A verdict with no rows at all is its own sentence, not a table of nothing.
    assert "this verdict carries no formula and no failure-mode row at" in body
    assert "what the verdict rests on, counted off the rows it" in body


def test_the_band_shows_the_episode_end_and_only_when_the_wire_says_so():
    """`verdict.terminal` is the only thing on the wire that says an episode ended, and
    it appeared nowhere on this page. Non-null takes the band over. `null` is a running
    episode and renders nothing. An *absent* field is a build that cannot say either
    way, and gets the placeholder with its owner rather than being read as running."""
    page = _page()
    body = _fn(page, "renderWallTerminal")
    for word in ("SUCCESS", "FAILURE", "ABORTED"):
        assert f"  {word}: {{" in _block(page, "const TERMINAL = {"), word
    assert 'missing("verdict.terminal", "P0, then P4"' in body
    assert '!("terminal" in v)' in body                     # absent is its own case
    assert "t === null || t === undefined" in body          # and so is null
    assert 'wall.classList.add("over")' in body
    assert 'wall.classList.remove("over")' in body
    # A word this console has no meaning for is still an ended episode, shown as it
    # arrived. The validator types this field as any string, so this case is reachable.
    assert "hasOwnProperty.call(TERMINAL, t)" in body
    assert "has no meaning for" in body
    # Never colour alone: a glyph and the word EPISODE ENDED, in capitals.
    assert "EPISODE ENDED" in body
    assert '#wall.over .big' in _style(page)


def test_the_band_shows_the_rung_the_category_and_the_imminence():
    """`intervention.category` and `intervention.imminence` are on the wire and were
    rendered nowhere. `imminence` arrives already worded from `manifest._imminence_label`
    and is printed, never recomputed -- and the rung is placed on the ladder by name, so
    the band says which rung of how many rather than only which word."""
    page = _page()
    assert "const RUNGS = [" + ", ".join(
        f'"{a}"' for a in api.INTERVENTION_ACTIONS) + "];" in page
    body = _fn(page, "renderWallAction")
    assert "i.category" in body and "i.imminence" in body
    assert "esc(i.category)" in body and "esc(i.imminence)" in body
    assert "rung ${rung + 1} of ${RUNGS.length}" in body
    # Both are genuinely nullable and neither null is a fault: no breach graded this
    # tick is a normal, reportable state.
    assert body.count("=== null || i.") == 2
    assert "none reported" in body
    # A verdict with no intervention block at all names the field and its owner.
    assert 'missing("verdict.intervention", "P4"' in body
    # The three confidences on this page are different numbers; this one says which,
    # on `title` rather than as a line of the band -- it is the same sentence every tick.
    assert "The intervention's own confidence" in body
    # And no imminence is derived here from anything.
    assert "steps_to_timeout" not in body


def test_the_automata_are_the_main_panel_and_are_drawn_once():
    """Drawn in the band and nowhere else. The highlight is a class on a node found by
    element id: two copies of one graph would be two elements under `aut0n3`, the wrong
    one would be lit, and nothing on the page would say so. So panel 1 IS the band, and
    panel 3 points at it rather than redrawing anything."""
    page = _page()
    body = _fn(page, "renderAutomaton")
    assert 'const box = $("wall-graphs");' in body
    assert '$("wall-rows").innerHTML = formulaTable(v);' in body
    assert 'id="automaton"' not in page                     # no pane draws it
    assert "1 · automaton" in page                          # and it says what it is
    assert 'href="#wall"' in page
    # The layout is untouched -- the drawing is *sized* from the scale, not re-laid-out.
    assert "const AUT = { R: 15, COL: 136, ROW: 66, PAD: 34, TOP: 70 };" in page
    assert 'style="${svgStyle(w)}"' in page
    assert "width:${w}px" not in page


def test_the_band_lights_the_state_the_verdict_reports_and_never_infers_one():
    """The rule pane 6 was written on, kept where the drawing went. A row whose `state`
    is null, or no row of that name at all, lights nothing: the initial state is where
    an automaton *starts*, not where it is."""
    page = _page()
    assert "lightAutomata(graphs, v);" in _fn(page, "renderAutomaton")
    light = _fn(page, "lightAutomata")
    assert 'typeof row.state === "number" ? row.state : null' in light
    assert 'el.classList.toggle("cur", at !== null && Number(s.id) === at);' in light
    assert "nothing is lit" in light
    # And the two degrade paths that predate the band still fire, in the band.
    aut = _fn(page, "renderAutomaton")
    assert 'missing("manifest.automata' in aut
    assert "if (!Array.isArray(graphs)) {" in aut
    assert "} else if (!graphs.length) {" in aut


def test_the_band_degrades_to_no_verdict_no_manifest_and_no_adapter():
    """The three silences the band has to survive, none of which is an error. No verdict
    has reached the page; the manifest declares no phase machine to place a phase in;
    and the adapter -- which the band never reads -- is not needed for any of it."""
    page = _page()
    for name in ("renderWallVerdict", "renderWallAction", "renderWallWhere"):
        assert "if (!v) {" in _fn(page, name), name
    # The topic is named from the constant, so a rename fails here rather than in a
    # browser looking at a sentence about a topic that no longer exists.
    assert f"no <code>{api.VERDICT}</code> has reached this page yet" in _fn(
        page, "renderWallVerdict")
    where = _fn(page, "renderWallWhere")
    assert "Array.isArray(phases) && phases.length" in where
    assert "the manifest declares no phase" in where
    # One phase resolution where there is a machine to resolve against: pane 7's, which
    # says which of `phase` and `phase_index` it believed and why.
    assert "currentPhase(phases, v)" in where
    # The band reads the verdict and the manifest. Not the adapter, not the observation,
    # and never the *absence* of any of them.
    for fn in _WALL_FNS:
        body = _fn(page, fn)
        for forbidden in ("S.adapter", "S.obs", "S.connected", "S.hist"):
            assert forbidden not in body, (fn, forbidden)


def test_nothing_the_band_takes_off_the_wire_reaches_innerhtml_unescaped():
    """Same rule as the rest of the page, on the part of it that is largest and most
    likely to be photographed. A wire field is not markup: no wire object is
    interpolated directly, and every one of its fields goes through esc/txt/num."""
    page = _page()
    for fn in _WALL_FNS:
        body = _fn(page, fn)
        # The hazard is a wire value dropped straight in; a ternary *testing* one is
        # not that, and its branches are esc'd below.
        raw = re.findall(r"\$\{\s*(?:v|r|i|row|f|sum)\.\w+\s*\}", body)
        assert raw == [], (fn, raw)
    cause = _fn(page, "wallCause")
    assert "txt(r.name)" in cause and "esc(r.fault_category)" in cause
    assert "num(r.confidence, 2)" in cause
    assert "txt(v.verdict)" in _fn(page, "renderWallVerdict")
    assert "txt(v.step)" in _fn(page, "renderWallWhere")
    assert "txt(t)" in _fn(page, "renderWallTerminal")


# ==================================== the type scale, the density control, the fold


def test_one_number_decides_the_whole_pages_type():
    """Seven literal px sizes, from 9 up, are one scale in rem off `:root{font-size}`.
    Exactly one literal size is left and it is that root -- everything else is a token,
    so the density control moves one number and the page moves with it."""
    page = _page()
    style = _style(page)
    assert re.findall(r"font(?:-size)?:\s*([0-9.]+)(px|rem|em)", style) == [("13", "px")]
    assert "font-size:13px;" in style
    for step in ("--t-xxs:", "--t-xs:", "--t-sm:", "--t-md:", "--t-base:", "--t-lg:",
                 "--t-xl:"):
        assert step in style, step
    # Type drawn inside an SVG viewBox is the marked exception: a `px` there is a user
    # unit, it is geometry, and it scales with a drawing that is itself sized in rem.
    for graph in ("--g-name:11px", "--g-edge:10px", "--g-sub:9px"):
        assert graph in style, graph
    assert "a `px` is a user unit" in style
    # Tier 1 has its own multiplier over the top of the same scale, applied by
    # redefining the scale for its subtree -- one control, not a second set of rules.
    assert "--wall:1.9;" in style
    assert "calc(1rem * var(--wall))" in style


def test_the_drawings_are_sized_from_the_number_the_stylesheet_declares():
    """The graph was 682px squeezed into a 430px column, so its node text landed near
    7px. It is sized in rem now, from `:root`'s own number, so the density control
    carries the drawing and the type inside it at one ratio -- and `--aut-zoom` is the
    band's extra multiplier. A base guessed at in the script would be the one thing on
    the page that did not move with the rest of it."""
    page = _page()
    root = re.search(r"font-size:([0-9]+)px;", _style(page))
    assert root
    assert f"const REM = {root.group(1)};" in page
    assert "max-width:100%;height:auto`;" in page          # allowed to shrink, never
    assert "var(--aut-zoom,1)" in page                     # to stretch
    # The band's multiplier and no more. Going past it made the widest graph fill the
    # column and blew a two-state safety automaton up to 781x377 -- size on a dashboard
    # reads as importance, and `drawGraph` sizes per graph precisely so it does not.
    assert "#wall .aut-view { --aut-zoom:var(--wall); }" in _style(page)
    assert "grid-template-columns:minmax(0,7fr) minmax(0,5fr)" in _style(page)


def test_the_density_control_is_one_number_and_is_remembered():
    """The same page serves a projector across a room and a laptop on a bench. A+/A-
    moves `:root`'s font-size and nothing else, and the choice is remembered per
    browser -- a console that is illegible until somebody re-presses a button twice is
    one nobody presses at all."""
    page = _page()
    assert 'id="dens-up"' in page and 'id="dens-down"' in page
    body = _fn(page, "setDensity")
    assert 'document.documentElement.style.fontSize = next + "px";' in body
    assert "STORE.set(DENSITY.key" in body
    assert "Math.min(DENSITY.max, Math.max(DENSITY.min, px))" in body   # clamped
    assert 'key: "skillmon.density"' in page
    # localStorage throws outright where storage is turned off, and a console that
    # cannot remember a preference still has to render one.
    store = _block(page, "const STORE = {")
    assert "catch (e) { return fallback; }" in store
    assert "localStorage" not in _fn(page, "setDensity")   # only ever through STORE


def test_the_band_panels_are_boxes_like_every_other_panel():
    """Panels 1 and 2 were bare `<div>`s with a caption on the page background, while 3,
    4 and 5 were bordered boxes with a header. So the top half of the console read as
    loose text beside a diagram and the bottom half read as panels, and "what is where"
    had no answer above the fold. One vocabulary for all five."""
    page = _page()
    band = page.split('<div class="grid">')[0]
    panes = re.findall(r'<section class="pane">\s*<h2>(.*?)</h2>', band, re.S)
    assert len(panes) == 2
    for head in panes:
        assert 'class="num"' in head and 'class="ttl"' in head and 'class="sub"' in head
    # The same rule that styles a pane's summary styles these, so they cannot drift.
    assert "section > h2, details.pane > summary {" in _style(page)


def test_the_verdict_is_four_labelled_rows_in_one_column():
    """It was an `auto-fit` grid: three columns of 213px inside a 666px rail, cells 255,
    309, 568 and 276px tall, and `where` wrapping onto a second row *under* `verdict`.
    Four things scattered rather than four things in order.

    One column, a fixed label column, a rule between rows. Every row the same shape,
    which is the whole of what makes a block of text scannable by somebody who did not
    write it."""
    page = _page()
    style = _style(page)
    assert "#wall .cell { display:grid; grid-template-columns:9.5rem minmax(0,1fr);" in style
    assert "repeat(auto-fit,minmax(15rem,1fr))" not in style
    # Row 1 of column 1 and nothing else. `span 99` made the grid HAVE 99 rows, and 98
    # empty ones at a 4px gap added 392px of nothing to every cell.
    assert "#wall .cell > .lead { grid-column:1; grid-row:1;" in style
    assert "grid-row:1 / span" not in style
    # And the hero fits its column: at 1.8 it was 51px, and `✖ VIOLATED` needed 258px
    # of a 213px column and ran out over the cell beside it.
    assert "font-size:calc(var(--t-xl) * 1.25); font-weight:700;" in style
    assert "overflow-wrap:anywhere" in style.split("#wall .big")[1].split("}")[0]


def test_the_header_does_not_repeat_the_panel_under_it():
    """It carried verdict, intervention, phase, step and tick as well -- all of which
    panels 2 and 5 say, larger and with their evidence beside them. Two places showing
    `VIOLATED` is not twice as clear: it is a reader wondering which one is real."""
    page = _page()
    head = page.split("<header>")[1].split("</header>")[0]
    for gone in ("h-verdict", "h-action", "h-phase", "h-step"):
        assert gone not in page, gone
    assert 'id="h-skill"' in head and 'id="h-tick"' in head
    body = _fn(page, "renderHeader")
    assert "verdictClass" not in body and "intervention" not in body


def test_the_page_is_five_things_and_the_rest_is_behind_one_fold():
    """Eleven panes competing with the band is what this layout was, and the operator's
    word for it was "so so noisy". Then six, and the word was "super bad".

    Five now, named by the operator: the automaton with its current state, the clock, the
    verdict, the input data, and the propositions with their evaluations. Panels 1 and 2
    are the band; 3, 4 and 5 are the grid under it.

    **The phase machine is behind the fold**, and that is the change that hurt: it is a
    real view and it is one click away, but it is not one of the five. Keeping a sixth
    panel because the sixth panel is good is how this page reached eleven. Nothing is
    deleted -- `adapter.warnings` is what surfaced the `min_range` fold gap, and a warning
    that is gone is worse than one a click away."""
    page = _page()
    band, rest = page.split('<div class="grid">', 1)
    grid = rest.split('<details id="more"', 1)[0]

    # The band is two of the five, and it is not inside the grid.
    assert '<section id="wall">' in band
    assert re.findall(r'<span class="ttl">([^<]+)</span>', band) == ["automaton", "verdict"]
    # The other three, all open.
    top = re.findall(r'<details class="pane" data-pane="([a-z]+)"( open)?>', grid)
    assert [p[0] for p in top] == ["aps", "inputs", "clock"]
    assert all(p[1] for p in top), "every panel starts open; the fold is the `more` one"

    # The rest, behind one control, and none of it deleted.
    more = page.split('<details id="more"', 1)[1]
    behind = set(re.findall(r'data-pane="([a-z]+)"', more)) - {"more"}
    assert behind == {"machine", "warnings", "config", "schema", "spec", "plots", "timing"}
    assert 'const PANE_CLOSED = ["more", "plots", "timing", "replay"];' in page
    assert 'STORE.get(paneKey(name)' in page


def test_a_proposition_shows_its_condition_not_its_whole_description():
    """A spec's AP reads `True when <expr>. <prose>`. The expression decides the value
    and belongs on a projected screen; the prose explains it and belongs on hover. That
    split is most of this pane's word count, and `ruleOf` already knew how to make it."""
    body = _fn(_page(), "renderAps")
    assert "const cond = ruleOf(rule) || rule;" in body
    assert 'title="${esc(rule)}"' in body and "${esc(cond)}" in body

def test_the_cap_belongs_to_tier_two_alone():
    """`max-height:46vh` on every pane is what put nine scrollbars on one page. Tier 1
    is the thing being read across the room and is never a box with its own scrollbar;
    the panes below it keep a bound so that nine of them cannot push it off the top."""
    page = _page()
    style = _style(page)
    assert "max-height:46vh" not in style
    assert ".grid > details.pane > .body { overflow:auto; max-height:64vh; }" in style
    # And the band is outside the grid, so the rule cannot reach it.
    assert page.index('<section id="wall">') < page.index('<div class="grid">')


def test_every_colour_on_the_page_is_a_token_in_one_block():
    """Eleven hexes were spelled into rules and one into the script, where the canvas
    could not take a `var()`. A projector or a light theme is one block to change, so
    every hex is in `:root` and the script reads the ones it needs back out."""
    page = _page()
    root = re.search(r"\n  :root \{(.*?)\n  \}", page, re.S)
    assert root
    outside = [m.group(0) for m in re.finditer(r"#[0-9a-fA-F]{6}(?![0-9a-zA-Z_-])", page)
               if not (root.start(1) <= m.start() <= root.end(1))]
    assert outside == [], outside
    for name in ("--well:", "--rowline:", "--seen:", "--note:", "--ctl:", "--on-acc:",
                 "--alarm-bg:", "--unreported-bg:", "--calm-bg:"):
        assert name in root.group(1), name
    assert 'g.strokeStyle = token("--acc");' in page


# ============================================ the hot path, read off the page


def test_the_name_matchers_are_compiled_once_per_spec_and_not_once_per_tick():
    """`keysInRule` compiled one `RegExp` per schema key per AP **per observation** --
    168 of them a tick on the mock's own spec -- and `apsInExpr` one per AP name per
    guard per verdict. Both derive from documents that change only when a spec is
    pushed, so both are keyed on those documents, the same structural guard
    `renderAutomaton` and `renderPhases` already use.

    Measured in the live page against the mock's manifest: 0.064 ms → 0.011 ms per
    observation, and 0.0127 ms → 0.0053 ms per verdict."""
    page = _page()
    for hot in ("keysInRule", "apsInExpr"):
        assert "new RegExp" not in _fn(page, hot), hot
        assert "rxGuard();" in _fn(page, hot), hot
    guard = _fn(page, "rxGuard")
    assert "if (key === RX.key) return;" in guard
    assert guard.count("new RegExp") == 2
    assert "S.adapter || {}).schema" in guard
    assert "S.manifest || {}).atomic_propositions" in guard
    # A pushed spec throws the memo away rather than leaving it stale.
    assert "RX.rule = new Map();" in guard and "RX.expr = new Map();" in guard
    # The escape stays: one metacharacter in a declared key is an exception, and an
    # exception here is not a bad row, it is no pane.
    assert "reEsc(k)" in guard and "reEsc(n)" in guard


def test_the_state_banner_is_rebuilt_only_when_the_state_changes():
    """It rebuilt the whole banner -- a fixed multi-sentence paragraph included -- and
    reassigned `document.title`, every tick, for a string that moves when an operator
    moves it. Now the structure is keyed on the status and only the duration, which
    really is per-tick, is written each time.

    Measured in the live page: 0.0073 ms → 0.0033 ms a tick, and 300 title writes per
    300 ticks → 1."""
    page = _page()
    refresh = _fn(page, "refreshStateBanner")
    assert "S.mon.sig" in refresh
    assert "renderStateBanner();" in refresh
    assert '$("mon-since")' in refresh and "sinceText()" in refresh
    # The tick calls the guarded one, and nothing calls the rebuild on a tick.
    assert "renderClock(); refreshStateBanner(); renderEchoAge();" in page
    assert "sinceText()" not in _fn(page, "renderStateBanner")
    title = _fn(page, "setTitleMark")
    assert "if (document.title !== next) document.title = next;" in title


def test_the_wire_carries_every_field_the_band_reads(bus):
    """The band reads six fields off the verdict. Three of them were rendered nowhere
    before, so this asserts they are really on the wire and really validate -- a band
    built against a field the producer does not publish would degrade for ever and
    nobody would notice."""
    page = _page()
    for read in ('"terminal" in v', "i.category", "i.imminence",
                 "r.fault_category", "r.confidence", "txt(v.step)"):
        assert read in page, read
    seen = frames(bus)
    verdict = seen[api.VERDICT]
    assert api.validate_for_topic(api.VERDICT, verdict) == []
    assert "terminal" in verdict                       # nullable, and present regardless
    intervention = verdict["intervention"]
    assert set(intervention) == {"action", "category", "imminence", "confidence"}
    assert intervention["action"] in api.INTERVENTION_ACTIONS
    assert intervention["category"] is None or \
        intervention["category"] in api.FAULT_CATEGORIES
    assert intervention["imminence"] is None or isinstance(intervention["imminence"], str)
    for row in verdict["failure_modes"]:
        assert row["fault_category"] in api.FAULT_CATEGORIES
        assert 0.0 <= row["confidence"] <= 1.0
    # `--mock` never ends an episode, so the absent/`null` terminal path is the one the
    # fixture demonstrates and the takeover was driven by hand. Said here rather than
    # left as a gap somebody rediscovers.
    assert verdict["terminal"] is None


# ============================ what was already on the wire and rendered nowhere
#
# Same split as everything above it, and the same reason: no JavaScript test runner in
# this repo. What is asserted here is the page's source at the points where a rewrite
# would turn "what the producer published" back into a blank, a zero or a guess -- plus,
# against the mock bus, that every field below really is on the wire, because a pane
# written against a field no producer publishes would degrade for ever and read as
# working.
#
# What was instead driven by hand, in headless Chrome over CDP against
# `python3 -m skill_monitor.frontend.web --mock`, and is recorded here so the next reader
# knows it was checked rather than assumed:
#
#   * pane 10 lists all fifteen of `real_g1`'s warnings, including the `min_range` fold
#     one; with the field deleted off the live adapter it names the field and its owner,
#     and with it set to `[]` it says "checked, and clean";
#   * pane 3 renders `ⓘ` against every key and `?` against one whose `doc` was deleted,
#     with the doc, the default and the debounce spelled out under the table;
#   * pane 2 prints `nav_stuck → last per message · after 10 consecutive messages` and
#     `dist_to_goal → last per tick`, and `⚠ no adapter.sources['odom'].steps` with the
#     array deleted;
#   * pane 7's timing table reads `✔ 63 — the monitor does not report this as close to a
#     bound`, and with the whole `risk` block deleted every row names its own field;
#   * with `phase_guards` deleted the declared-structure table appears under the
#     placeholder, marked as structure and with `invariant → SAFETY`;
#   * the plots: `-0.092 … 0.15` as a floor and ceiling, a null pushed into a series
#     leaves the count unmoved and the label reads `· 1 tick ago`, and dropping a key
#     from the schema takes its canvas from ten to nine while a new key gains one.
#
# And measured, in the same live page, over 239 observations and 239 verdicts each,
# against `real_g1`'s twenty-one keys:
#
#   per observation, plots folded (the default)   2.55 ms -> 0.89 ms
#   per observation, plots unfolded               2.51 ms -> 2.23 ms
#   per verdict                                   0.56 ms -> 0.66 ms
#
# The observation path is cheaper in both fold states, and the old one cost the same
# either way -- it re-derived every series from all of `S.hist` per key per tick whether
# or not there was a box to draw into. The verdict path buys the risk rows, the declared
# guards and the wall's stale-source line.


def test_the_band_says_which_sources_went_quiet_beside_the_verdict():
    """`risk.stale_sources` is *why* a fault was de-escalated: a named failure mode is
    graded on the freshness of the sources feeding its own propositions, so a quiet
    source lowers that mode's confidence and the ladder answers a lower rung. The band
    showed the de-escalated rung and nothing beside it said what caused it.

    Empty is not absent. Empty is "checked, every source fresh"; absent is a verdict
    with no risk block to check, and the two get different sentences."""
    page = _page()
    body = _fn(page, "wallStale")
    assert "risk.stale_sources" in body
    assert "Array.isArray(stale)" in body                  # a non-array is its own case
    assert "if (!stale.length) {" in body                  # and so is empty
    assert "every source\n      fresh" in body
    assert 'absent("verdict.risk.stale_sources"' in body
    # The names come off the wire and are escaped like everything else.
    assert "stale.map(s => `<b>${txt(s)}</b>`)" in body
    # Never colour alone: a glyph and a count.
    assert "⚠ ${stale.length} stale" in body
    # And it is drawn beside the verdict itself, not in a pane.
    assert "wallStale(v)" in _fn(page, "renderWallVerdict")


def test_the_timing_table_carries_the_monitors_own_risk_fields():
    """Three fields of `verdict.risk` were on the wire and rendered nowhere, and one of
    them -- `warn` -- is the monitor's own "close to a bound" boolean, which the page was
    re-deriving worse from `steps_to_timeout <= 0`."""
    page = _page()
    body = _fn(page, "phaseTiming")
    for row in ("seconds to timeout", "close to a bound", "trigger confidence"):
        assert f'["{row}"' in body, row
    assert "risk.seconds_to_timeout" in body
    assert "risk.trigger_confidence" in body
    assert "riskWarn(risk)" in body
    warn = _fn(page, "riskWarn")
    assert "risk.warn === true" in warn and "risk.warn === false" in warn
    assert 'absent("verdict.risk.warn"' in warn
    # A null seconds_to_timeout is a reported answer, not a missing field.
    assert "risk.seconds_to_timeout === null" in body
    # Each absence names its own field rather than one dash for the block.
    for field in ("verdict.risk.seconds_to_timeout", "verdict.risk.trigger_confidence",
                  "verdict.risk.severity", "verdict.risk.steps_to_timeout",
                  "verdict.risk.violations_to_fault"):
        assert f'absent("{field}"' in page, field


def test_the_adapter_warnings_get_a_pane_and_absent_is_not_empty():
    """`_build_warnings`' own docstring says these are published "so they are visible on
    the wire rather than only in a log nobody reads" -- and the console read the topic
    they travel on and dropped the field. For `real_g1` today the list is not empty.

    Three answers, because there are three facts: a build that does not report them at
    all is not a clean bill of health, and must not read as one."""
    page = _page()
    assert '<details class="pane" data-pane="warnings" open>' in page
    body = _fn(page, "renderWarnings")
    assert 'missing("adapter.warnings", "P3"' in body
    assert "That is not the same " in body                 # absent != empty, in words
    assert "if (!w.length) {" in body
    assert "Checked, and clean" in body
    # Every line is wire data going into innerHTML.
    assert "w.map(line => `<div class=\"missing\">" not in body
    assert "${txt(line)}" in body
    # Glyph and word on both ends, never the colour alone.
    assert "✔ <b>none.</b>" in body
    assert "⚠ <b>${w.length}" in body
    # And it is built from the latched read, not from a tick.
    assert "renderWarnings();" in _fn(page, "refreshLatched")
    assert "renderWarnings();" in _fn(page, "boot")
    for hot in ("onObservation", "onVerdict"):
        assert "renderWarnings" not in _fn(page, hot), hot


def test_every_value_carries_what_the_descriptor_says_the_key_is():
    """`adapter.schema[k].doc` is where the units live, and where a key says what a
    value of it does *not* mean. None of it was on this page.

    The mark differs in the glyph and not in the hue -- `ⓘ` documented, `?` not -- and
    the full text is spelled out under pane 3's table as well as being in the title, so
    it can be read without hovering anything."""
    page = _page()
    mark = _fn(page, "schemaMark")
    assert "entry.doc" in mark
    assert '`no adapter.schema.${k}.doc' in mark
    assert 'doc ? "ⓘ" : "?"' in mark                       # the glyph carries it
    assert "invents none" in mark
    facts = _fn(page, "schemaFacts")
    assert 'hasOwnProperty.call(entry, "default")' in facts    # `default: 0` is a value
    assert "no declared default" in facts
    assert "entry.debounce_ticks" in facts
    assert "no debounce_ticks" in facts
    note = _fn(page, "schemaNote")
    assert 'missing(`adapter.schema.${k}.doc`, "P3"' in note
    # Panes 3, 4 and 5 all read the same cache rather than building it three times.
    for fn in ("renderInputs", "renderPlots", "renderAps"):
        assert "adapterStruct()" in _fn(page, fn), fn
    assert 'id="schema"' in page
    assert "renderSchema();" in _fn(page, "refreshLatched")
    # An empty schema is its own sentence and not an empty pane.
    assert "exposes no keys" in _fn(page, "renderSchema")


def test_the_fold_policy_of_every_source_is_on_the_page():
    """`adapter.sources[].steps[]` decides what a number on this page *is*: a key folded
    `last` from a 10 Hz source against a 1 Hz tick is the newest of ten samples and not
    the smallest of them. And a `threshold` counts in the units of `on` -- `nav_stuck`'s
    10 is ten consecutive *messages*, not ten ticks. None of it was rendered."""
    page = _page()
    body = _fn(page, "sourceSteps")
    assert "st.aggregate" in body
    assert "st.threshold" in body
    assert 'typeof (st || {}).on === "string"' in body
    # The units of the threshold come off `on`, and are never assumed to be ticks.
    assert 'on === "message" ? "messages" : on === "tick" ? "ticks"' in body
    assert "consecutive\n         ${esc(unit)}" in body
    # Absent and null are the same fact for `threshold` -- the contract makes it
    # optional and null is how a step that does not debounce spells it.
    assert "no threshold" in body
    # An absent steps array is not an empty one.
    assert "Array.isArray(steps)" in body
    assert 'absent(`adapter.sources[\'${raw(s.id)}\'].steps`' in body
    assert "declares no steps" in body
    assert "sourceSteps(s)" in _fn(page, "renderConfig")


def test_a_sources_declared_bounds_sit_beside_the_numbers_they_grade():
    """`max_age_s` and `tracked` were on the wire and nowhere on the page. An `age 0.42
    s` with no bound beside it is unreadable, and `required` and `tracked` are different
    claims -- one is whether a spec may be refused for want of this source, the other is
    whether anybody watches whether it is still arriving."""
    page = _page()
    assert "max_age_s" in _fn(page, "adapterStruct")
    assert 'absent("adapter.sources[].max_age_s"' in page
    assert "st.age[src.id]" in _fn(page, "renderInputs")
    flags = _fn(page, "sourceFlags")
    assert 's.required === "boolean"' in flags
    assert 's.tracked === "boolean"' in flags
    assert "◉ tracked" in flags and "○ not tracked" in flags   # glyph, not hue alone
    assert "without becoming a stale source" in flags
    assert 'absent("adapter.sources[].tracked"' in flags
    assert "sourceFlags(s)" in _fn(page, "renderConfig")


def test_the_driving_row_says_what_the_spec_declared_it_as():
    """The band named `collision_imminent` and nothing on screen said what
    `collision_imminent` means. `named_failure_modes[].description` and `.formula` are
    both on the latched manifest.

    A row with no entry under that name is not a fault: a formula is declared in
    `ltl_formulas` and a `phase:<phase>:<kind>` fault is declared nowhere."""
    page = _page()
    body = _fn(page, "declaredAs")
    assert "declaredMode(name)" in body
    assert "esc(mode.description)" in body and "esc(mode.formula)" in body
    assert "if (mode === null) {" in body
    assert "declares no\n      <code>named_failure_modes</code> entry" in body
    # Each absence names its own field rather than one dash for the whole entry.
    assert "].description`" in body and "].formula`" in body
    assert "declaredAs(r.name)" in _fn(page, "wallCause")
    # And the same on every row of the table beside the automata, clipped with the whole
    # of it in the title -- the treatment an edge label already gets.
    rows = _fn(page, "rowDeclared")
    assert "ROW_DECLARED_MAX" in rows and 'title="${esc(full)}"' in rows
    assert "rowDeclared(f.name)" in _fn(page, "formulaTable")


def test_pane_one_says_what_this_spec_calls_success_and_failure():
    """`terminal_success` / `terminal_failure` carry a `condition` and a `description`,
    and the console showed neither -- so an operator could read that an episode ended
    without anything on the page saying what ending it that way would have taken.

    They are criteria and not a live truth. Whether either holds is the monitor's answer
    and arrives as `verdict.terminal`; nothing here evaluates a condition, for the same
    reason pane 7 does not evaluate a guard."""
    page = _page()
    block = _block(page, "const TERMINAL_SPEC = [")
    assert '"terminal_success"' in block and '"terminal_failure"' in block
    body = _fn(page, "renderSpecTerminal")
    assert "block.condition" in body and "block.description" in body
    assert 'missing(`manifest.${field}`' in body
    assert 'absent(`manifest.${field}.condition`' in body
    assert 'absent(`manifest.${field}.description`' in body
    # No manifest at all is a different silence from a spec with no terminal block. The
    # topic is named from the constant, so a rename fails here rather than in a browser.
    assert f'missing("{api.MANIFEST}", "P4"' in body
    # Criteria, not truth, and said so on screen.
    assert "nothing here is evaluated on" in body
    assert 'id="spec-terminal"' in page
    assert "renderSpecTerminal(m);" in _fn(page, "renderSpec")


def test_the_declared_guards_stand_in_when_no_build_reports_their_truth():
    """`verdict.phase_guards` is optional, and a build that does not report it left
    pane 7 with a placeholder and nothing else. The *structure* is on the latched
    manifest regardless: what the guards are, in the spec's own words, and the fault
    category each one raises.

    Marked as structure and not as truth, in as many words. No column says whether a
    guard held, because nothing on the wire says so and this page does not evaluate an
    expression to find out -- which is the rule the live table renders by too."""
    page = _page()
    names = page[page.index("const GUARD_NAMES = ["):page.index("\n];", page.index(
        "const GUARD_NAMES = ["))]
    assert re.findall(r'\["(\w+)",', names) == list(api.PHASE_GUARD_NAMES)
    body = _fn(page, "declaredGuards")
    assert 'p[name + "_fault_category"]' in body
    assert "structure, not this\n      tick's truth" in body
    assert "does not evaluate an expression" in body
    assert "declares no <code>${esc(name)}</code>" in body
    assert "names no category for this one" in body        # and does not guess a default
    # It is the fallback, and only the fallback: the live table is untouched.
    guards = _fn(page, "phaseGuards")
    assert "declaredGuards(phases, i)" in guards
    assert guards.count("declaredGuards(") == 1
    assert '!("phase_guards" in v)' in guards
    # No evaluator, here of all places.
    for evaluated in ("eval(", "new Function", "=== true ?"):
        assert evaluated not in body, evaluated


def test_the_three_confidences_are_each_labelled_as_whose():
    """Three numbers on this page are called confidence and they are not the same
    number: the intervention's, the observation's, and a failure-mode row's own. Two of
    them were printed as `conf` with nothing saying which."""
    page = _page()
    aps = _fn(page, "renderAps")
    assert "<b>observation</b> confidence" in aps
    assert "are not the same number" in aps
    table = _fn(page, "formulaTable")
    assert "mode conf" in table
    assert "conf</th>" not in table.replace("mode conf</th>", "")
    assert "neither the intervention's confidence above nor the" in table
    # The band's was labelled in pass 1 and stays labelled, on `title` rather than as a
    # line of the band -- it is the same sentence every tick.
    assert "The intervention's own confidence" in _fn(page, "renderWallAction")


def test_severity_is_graded_and_not_always_painted_the_same_red():
    """`severity` was rendered `.bad` whatever it said, so a PROGRESS severity -- a run
    that is behind -- was the same red as a SAFETY one and the colour carried nothing.

    Graded by the buckets `monitor_action.grade_action` grades them by, and a word this
    console has no bucket for is shown as it arrived rather than quietly as either."""
    page = _page()
    block = _block(page, "const SEVERITY = {")
    for name in ("SAFETY", "INVARIANT", "TIMEOUT", "PROGRESS"):
        assert f"  {name}: {{" in block, name
    assert block.count('cls: "bad"') == 2 and block.count('cls: "warn"') == 2
    body = _fn(page, "riskSeverity")
    assert "hasOwnProperty.call(SEVERITY, s)" in body
    assert "no bucket for" in body
    # Null is a reported answer here, not an absence, and not a fault.
    assert "if (s === null) {" in body
    # The distinction survives the cut to the prose: null is a REPORTED answer and is
    # graded `ok`, while an absent field goes through `absent()`. The sentence saying so
    # moved to a `title` -- what must not happen is the two collapsing into one render.
    assert "reported" in body and 'class="ok"' in body
    assert 'absent("verdict.risk.severity"' in body
    # Glyph and word, so the grade survives a photograph of the screen.
    assert "meta.glyph" in body
    assert 'glyph: "✖"' in block and 'glyph: "⚠"' in block
    # And the old blanket red is gone.
    assert '`<span class="bad">${esc(risk.severity)}</span>' not in page


def test_a_sources_health_is_a_glyph_and_a_word_and_its_threshold_is_on_screen():
    """The last place on this page that carried a state in colour alone -- a bare `●` in
    three hues, in the pane an operator looks at to find out whether a sensor is still
    arriving. And the rule that turns it amber, `rate_hz < 0.6 * expected_hz`, was a
    literal in the expression and appeared nowhere in the output."""
    page = _page()
    block = _block(page, "const HEALTH = {")
    for state in ("fresh", "slow", "stale", "unrated"):
        assert f"  {state}: {{" in block, state
    assert block.count("glyph:") == 4
    assert len({m for m in re.findall(r'glyph: "(.)"', block)}) == 4   # four distinct
    assert block.count("word:") == 4
    body = _fn(page, "sourceHealth")
    assert "h.refreshed === false" in body
    assert "SLOW_FRACTION * h.expected_hz" in body
    assert "const SLOW_FRACTION = 0.6;" in page
    inputs = _fn(page, "renderInputs")
    assert "${state.glyph} ${esc(state.word)}" in inputs
    # The threshold is printed as a number beside the rate it grades.
    assert "${num(SLOW_FRACTION * h.expected_hz, 2)} Hz" in inputs
    assert "· amber below" in inputs
    assert "no expected_hz, so the rate is not graded" in inputs


def test_the_two_countdowns_are_graded_the_right_way_round():
    """`steps to timeout` was green until it hit zero, so one step from a timeout looked
    exactly as healthy as thirty. `violations to fault` was amber whenever it was
    positive, so a healthy `5 of 5` read as a warning while `0 of 5` -- the fault -- was
    the only thing that read worse. Both backwards.

    And the fix does not invent a threshold: proximity is graded on `risk.warn`, the
    monitor's own boolean on its own `warn_steps`. Where the monitor does not report it
    the number is printed ungraded and the row says why."""
    page = _page()
    steps = _fn(page, "stepsToTimeout")
    assert "if (left <= 0) {" in steps
    assert "risk.warn === true" in steps and "risk.warn === false" in steps
    assert "this page holds no threshold" in steps
    assert 'absent("verdict.risk.warn"' in steps
    assert "✖" in steps and "⚠" in steps and "✔" in steps  # never the hue alone
    viol = _fn(page, "violationsToFault")
    # Positive is the good case now, and `1` is arithmetic and not a threshold.
    assert 'n <= 0\n    ? `<span class="bad">' in viol
    assert 'n === 1' in viol
    assert '`<span class="ok">✔ ${n}</span>' in viol
    assert "violations still" in viol
    # The old rules are gone from the page entirely.
    assert 'bound !== null && left <= 0 ? "bad" : "ok"' not in page
    assert 'risk.violations_to_fault <= 0 ? "bad" : "warn"' not in page


def test_the_plots_carry_their_own_bounds_and_gap_their_nulls():
    """Three quiet faults. A `filter` dropped the ticks where a key was absent instead
    of leaving a gap, so every earlier sample slid one place to the right and a source
    that dropped ten frames drew a history ten ticks shorter than it was. There is no
    y-axis on a 34px sparkline, so a 0.001 wobble and a forty-metre swing drew the same
    line. And a series ending in nulls printed its last value as if it were this
    tick's."""
    page = _page()
    push = _fn(page, "pushPlotSample")
    assert "series.push(numeric ? v : null);" in push
    assert "PLOTS.counts[k]--" in push                     # the count follows the shift
    plots = _fn(page, "renderPlots")
    assert '.filter(v => typeof v === "number")' not in plots
    spark = _fn(page, "drawSpark")
    assert 'if (typeof v !== "number") { open = false; return; }' in spark
    assert "return { lo: lo, hi: hi, flat: flat };" in spark
    assert "Math.min(...series)" not in page               # one pass, and null-safe
    assert 'ps-${esc(k)}' in plots and "bounds[i].flat" in plots
    assert "flat at ${num(bounds[i].lo)}" in plots
    last = _fn(page, "lastNumber")
    assert "series.length - 1 - i" in last
    assert "tick${last.age === 1" in plots
    # And the accent is the stylesheet's, not a second copy of it.
    assert 'g.strokeStyle = token("--acc");' in page
    assert "#6aa9ff" not in page.split(":root {")[1].split("\n  }")[1]


def test_the_canvas_list_is_rebuilt_when_the_schema_changes():
    """`#plots` was built once, behind `if (!$("plots").childElementCount)`, and never
    again. A pushed spec that renamed a key left the old canvas on screen for ever,
    still showing the last value the old key ever had."""
    page = _page()
    assert '!$("plots").childElementCount' not in _code(page)
    plots = _fn(page, "renderPlots")
    assert "if (key !== PLOTS.key) {" in plots
    assert "adapterStruct().keys.filter" in plots
    push = _fn(page, "pushPlotSample")
    assert "keys.indexOf(k) < 0" in push                   # and its history goes with it
    # A pushed spec and an arm/reset both throw the canvases away with the history
    # behind them, rather than leaving a key the new spec does not declare on screen.
    assert "function clearPlots()" in page
    assert page.count("clearPlots();") == 2               # arm/reset, and the spec push
    assert "clearPlots();" in _fn(page, "command")


def test_everything_structural_is_cached_against_the_document_it_came_from():
    """Panes 2 to 7 now render a great deal that comes off the latched adapter and
    manifest, and three of the panes that read it are rebuilt at the tick rate. All of
    it is built once and keyed on the payload's identity -- `refreshLatched` replaces
    both documents wholesale, so a new object is a new document and the comparison is
    free where re-serialising a twenty-key schema every tick would not be.

    Measured in the live page over 239 observations, plots folded (the default):
    2.55 ms per observation before, 0.89 ms after."""
    page = _page()
    guard = _fn(page, "adapterStruct")
    assert "if (S.adapter === STRUCT.a) return STRUCT;" in guard
    assert "STRUCT.a = S.adapter;" in guard
    mguard = _fn(page, "manifestStruct")
    assert "if (S.manifest === STRUCT.m) return STRUCT;" in mguard
    # No per-tick serialisation of a latched document anywhere on the hot path.
    for hot in ("renderInputs", "renderPlots", "renderAps", "pushPlotSample",
                "formulaTable", "phaseTiming"):
        assert "JSON.stringify" not in _fn(page, hot), hot
    # The series is kept incrementally, not re-derived from the whole of S.hist.
    assert "S.hist" not in _fn(page, "renderPlots")
    assert "pushPlotSample(o);" in _fn(page, "onObservation")
    # And whether the pane is folded is read off `open`, never off a layout property --
    # a layout read straight after an innerHTML write forces a whole-page reflow.
    plots = _code(_fn(page, "renderPlots"))
    assert 'PLOT_PANE.closest("details:not([open])")' in plots
    for layout in ("clientWidth", "offsetParent", "getBoundingClientRect"):
        assert layout not in plots, layout
    # Every drawing, then every label: `drawSpark` reads `clientWidth`, and a layout read
    # after a DOM write forces a reflow, so interleaved they cost one per plot per tick.
    assert plots.index("bounds.push(") < plots.index("el.textContent")


def test_the_wire_carries_every_field_these_panes_now_read(bus):
    """Every field above is published and validated today; none of them needed a
    backend change. This asserts that against the mock -- which is held to the shipped
    validators -- because a pane written against a field no producer publishes degrades
    for ever and reads as working.

    Both halves, in one test, deliberately: a page reading a field the wire stopped
    carrying and a wire carrying a field the page stopped reading are the same fault
    seen from two ends, and neither shows up if the two are asserted apart."""
    page = _page()
    for read in ("a.warnings", "entry.debounce_ticks", "entry.doc", "st.threshold",
                 "s.max_age_s", "s.tracked", "risk.trigger_confidence",
                 "risk.seconds_to_timeout", "risk.stale_sources", "risk.warn",
                 "mode.description", "mode.formula", "block.condition",
                 'p[name + "_fault_category"]'):
        assert read in page, read
    verdict = frames(bus)[api.VERDICT]
    adapter = json.loads(bus.latched(mock_monitor.NS, api.ADAPTER))
    manifest = json.loads(bus.latched(mock_monitor.NS, api.MANIFEST))
    assert api.validate_adapter(adapter) == []
    assert api.validate_skill_manifest(manifest) == []

    # `warnings` is published, and for this adapter it is not empty.
    assert isinstance(adapter["warnings"], list) and adapter["warnings"]
    assert any("min_range" in w for w in adapter["warnings"])

    # Every schema entry carries the doc the units live in.
    assert all(isinstance(e.get("doc"), str) and e["doc"]
               for e in adapter["schema"].values())
    assert any("default" in e for e in adapter["schema"].values())

    for source in adapter["sources"]:
        assert isinstance(source["max_age_s"], (int, float))
        assert isinstance(source["tracked"], bool)
        assert isinstance(source["required"], bool)
        for step in source["steps"]:
            assert isinstance(step["aggregate"], str)
            assert step["on"] in ("message", "tick")
            assert step.get("threshold") is None or \
                isinstance(step["threshold"], (int, float))
    # The two facts pane 2 exists to make visible: a `last` fold, and a threshold whose
    # units are messages rather than ticks.
    steps = [s for src in adapter["sources"] for s in src["steps"]]
    assert any(s["aggregate"] == "last" for s in steps)
    assert any(s["threshold"] is not None and s["on"] == "message" for s in steps)

    risk = verdict["risk"]
    assert set(risk) == {"steps_to_timeout", "seconds_to_timeout",
                         "violations_to_fault", "warn", "severity",
                         "trigger_confidence", "stale_sources"}
    assert isinstance(risk["warn"], bool)
    assert 0.0 <= risk["trigger_confidence"] <= 1.0
    assert isinstance(risk["stale_sources"], list)
    assert risk["severity"] is None or isinstance(risk["severity"], str)

    for mode in manifest["named_failure_modes"]:
        assert isinstance(mode["description"], str) and mode["description"]
        assert isinstance(mode["formula"], str) and mode["formula"]
    for field in ("terminal_success", "terminal_failure"):
        assert isinstance(manifest[field]["condition"], str)
        assert isinstance(manifest[field]["description"], str)
    # The declared guards pane 7 falls back to, on the latched manifest regardless of
    # whether any producer evaluates them.
    for phase in manifest["execution_phases"]:
        assert any(name in phase for name in api.PHASE_GUARD_NAMES)
    assert any("invariant_fault_category" in p for p in manifest["execution_phases"])


# =============================================================================
# The page is one script, so it parses or nothing does
# =============================================================================
#
# These two shell out to `node`, which the project's testing rule otherwise forbids --
# no real processes in a unit test. The exception is deliberate and narrow: the thing
# under test *is* a syntax checker, Python cannot parse JavaScript, and the page has no
# test runner in this repo. There is no way to assert this property without running a
# JavaScript engine. Everything else in this file stays fully mocked.

def test_the_page_parses():
    """The page ships as a single `<script>`, so one syntax error anywhere in it stops
    the whole script parsing and every pane goes blank at once -- not the one that was
    edited. That has happened: a backtick inside an HTML comment inside a template
    literal ended the literal early, and the console rendered nothing at all. It was
    found by loading it in a browser, because nothing here could see it."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed; the page's JavaScript cannot be checked")
    assert web.page_syntax_problems() == []


def test_a_page_that_does_not_parse_is_reported_with_its_own_name(tmp_path):
    """The regression, reproducing the original failure exactly. Also pins that the
    scratch file node actually compiles is not what the reader is told about: a path
    under /tmp is not something anyone can go and fix."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed; the page's JavaScript cannot be checked")
    page = tmp_path / "index.html"
    page.write_text("<script>\nconst x = `<!-- a ` backtick -->`;\n</script>",
                    encoding="utf-8")
    problems = web.page_syntax_problems(page)
    assert len(problems) == 1
    assert "SyntaxError" in problems[0]
    assert problems[0].startswith("index.html:")
    assert str(tmp_path / "broken") not in problems[0]


def test_check_exits_non_zero_without_binding_anything():
    """`--check` is what CI and a pre-commit hook run. It must answer from the file
    alone -- no port, no bus, no ROS -- so that a page which cannot parse is caught
    before a server comes up looking perfectly healthy in front of a blank console."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed; the page's JavaScript cannot be checked")
    assert web.main(["--check"]) == 0
