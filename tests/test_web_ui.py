"""The web console: what it serves, and that its mock speaks the real contract.

No browser and no sockets. The page itself is one static file, so what is testable
here is the two things that can silently rot: the gateway's file route, and the mock
monitor -- which is the fixture every other reviewer will judge the console by, and is
therefore held to the same validators as a real producer.
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
