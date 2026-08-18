"""The gateway's HTTP surface, driven with a fake ROS bus and a fake clock.

This host has no rclpy, which is the point: `MonitorBus` and `ClockBackend` are the
injection seams, so every test below exercises the real router, the real WebSocket
codec and the real backpressure queue, and never a ROS graph.

Loopback sockets are used deliberately and only where the thing under test *is* the
socket behaviour -- the WS handshake, frame framing, a stream carrying a payload
verbatim. Everything that can be tested as a pure function (discovery, health, frame
assembly, drop accounting) is tested as one.
"""

from __future__ import annotations

import http.client
import json
import threading
import time

import pytest

from skill_monitor.backend import gateway
from skill_monitor.core import api


# ============================================================== fakes


class FakeBus(gateway.MonitorBus):
    """A ROS graph that never existed. Delivers exactly the payload text it is given."""

    def __init__(self, namespaces=(), latched=None, last_seen=None, publishable=True):
        self._namespaces = list(namespaces)
        self._latched = dict(latched or {})        # (ns, topic) -> payload text
        self._last_seen = dict(last_seen or {})    # ns -> time.time()
        self._listeners = []                       # (ns, topics, callback)
        self._cv = threading.Condition()           # subscribe/unsubscribe cross threads
        self.published = []                        # (ns, topic, payload text)
        self.publishable = publishable
        # Payload text the fake monitor answers a pushed spec with, or None to stay mute.
        self.spec_status_reply = None

    def namespaces(self):
        return list(self._namespaces)

    def latched(self, ns, topic):
        return self._latched.get((ns, topic))

    def last_seen(self, ns):
        return self._last_seen.get(ns)

    def publish(self, ns, topic, payload_text):
        if not self.publishable:
            raise gateway.BusUnavailable("fake bus has no ROS side")
        self.published.append((ns, topic, payload_text))
        if topic == api.LOAD_SPEC and self.spec_status_reply is not None:
            self.deliver(ns, api.SPEC_STATUS, self.spec_status_reply)

    def subscribe(self, ns, topics, callback):
        entry = (ns, tuple(topics), callback)
        with self._cv:
            self._listeners.append(entry)
            self._cv.notify_all()

        def unsubscribe():
            with self._cv:
                if entry in self._listeners:
                    self._listeners.remove(entry)
                self._cv.notify_all()

        return unsubscribe

    def status(self):
        return {"available": True, "detail": "fake bus"}

    # -- test helpers ------------------------------------------------------

    def deliver(self, ns, topic, payload_text):
        """Publish from the robot's side, verbatim."""
        with self._cv:
            self._latched[(ns, topic)] = payload_text
            if topic == api.VERDICT:
                self._last_seen[ns] = time.time()
            listeners = list(self._listeners)
        for listener_ns, topics, callback in listeners:
            if listener_ns == ns and topic in topics:
                callback(topic, payload_text)

    def listener_count(self):
        with self._cv:
            return len(self._listeners)

    def wait_for_listeners(self, count, timeout=5.0):
        """Block until `count` subscriptions exist.

        Counted rather than flagged: the gateway subscribes only *after* the websocket
        handshake returns, so a test that already holds a subscription of its own would
        otherwise race ahead and deliver into a stream nobody is listening to yet.
        """
        with self._cv:
            assert self._cv.wait_for(lambda: len(self._listeners) >= count, timeout), (
                f"expected {count} subscriptions, saw {len(self._listeners)}"
            )


class FakeClock(gateway.ClockBackend):
    """Records the path it was handed. The proxy must not rewrite it."""

    def __init__(self, frames=()):
        self.calls = []
        self.frames = list(frames)
        self.reachable = True

    def request(self, method, path, body):
        self.calls.append((method, path, body))
        if not self.reachable:
            raise gateway.ClockUnreachable("fake clock is down")
        return 200, "application/json", json.dumps({"seen": path}).encode("utf-8")

    def stream(self):
        if not self.reachable:
            raise gateway.ClockUnreachable("fake clock is down")
        yield from self.frames

    def status(self):
        return {"reachable": self.reachable, "detail": "fake clock"}


# ============================================================== fixtures


class Client:
    """A tiny HTTP client bound to a running gateway."""

    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json"} if payload else {}
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body):
        return self.request("POST", path, body)

    def json(self, path):
        status, text = self.get(path)
        return status, json.loads(text)

    def ws(self, path):
        return gateway.ws_connect(f"http://127.0.0.1:{self.port}{path}")


@pytest.fixture
def serve():
    """Start a gateway on an ephemeral port; stop it however the test ends."""
    servers = []

    def start(bus=None, clock=None, **kwargs):
        app = gateway.Gateway(bus or FakeBus(), clock or FakeClock(), **kwargs)
        server = gateway.GatewayServer(app, "127.0.0.1", 0)
        server.start()
        servers.append(server)
        return Client(server.port)

    yield start
    for server in servers:
        server.stop()


# A recorded verdict, encoded the way a producer that is not this process would encode
# it: two-space indent and a key order no `json.dumps(parsed)` would reproduce. Any
# re-serialisation in the gateway shows up as an inequality in the headline test.
RECORDED_VERDICT = json.dumps(
    api.build_verdict(
        seq=1041, t=1041.0, step=88,
        skill_name="G1HumanoidNavigation",
        phase="ExecutionAndTracking", phase_index=1,
        verdict="UNDECIDED",
        formulas=[api.build_formula(name="full_navigation_sequence",
                                    status="INCONCLUSIVE")],
        failure_modes=[api.build_failure_mode(name="collision_imminent",
                                              fault_category="SAFETY",
                                              status="VIOLATED", confidence=0.67)],
        risk=api.build_risk(steps_to_timeout=32, seconds_to_timeout=32.0,
                            violations_to_fault=3, warn=False,
                            trigger_confidence=0.67, stale_sources=["status"]),
        intervention=api.build_intervention(action="WARN", category="SAFETY",
                                            confidence=0.67),
    ),
    indent=2, sort_keys=True,
)

RECORDED_MANIFEST = json.dumps(
    api.build_skill_manifest(
        spec={"skill_name": "G1HumanoidNavigation",
              "execution_phases": [{"phase": "Approach"}, {"phase": "Dock"}]},
        source="/config/specs/formulas_g1.json",
    ),
    indent=2,
)


# ============================================================== the headline


def test_ws_frame_is_byte_identical_to_the_topic_payload(serve):
    """One recorded frame down both transports, compared byte for byte.

    This is the property that makes the gateway a pass-through rather than a translator,
    and it only holds because the payload text is embedded in the frame by
    concatenation instead of being parsed and re-encoded.
    """
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    # Path A: straight off the topic, the way a ROS client would see it.
    from_topic = []
    bus.subscribe("", (api.VERDICT,), lambda topic, text: from_topic.append(text))

    # Path B: through the gateway's websocket.
    connection = client.ws("/api/monitors/_/stream")
    try:
        bus.wait_for_listeners(2)          # path A's, plus the gateway's
        bus.deliver("", api.VERDICT, RECORDED_VERDICT)
        frame_text = connection.recv()
    finally:
        connection.close()

    assert from_topic == [RECORDED_VERDICT]

    frame = json.loads(frame_text)
    assert frame["topic"] == api.VERDICT
    assert frame["ns"] == ""
    assert frame["dropped"] == 0

    # Byte-identical, not merely equal-once-parsed.
    assert gateway.frame_payload_text(frame_text) == RECORDED_VERDICT
    assert RECORDED_VERDICT in frame_text
    assert frame["payload"] == json.loads(RECORDED_VERDICT)


def test_ws_stream_carries_observations_and_verdicts_tagged_by_topic(serve):
    bus = FakeBus(namespaces=[""])
    client = serve(bus)
    observation = json.dumps(api.build_observation(
        seq=1041, t=1041.0, step=88, sensors={"min_range": 0.42},
        ap_values={"path_active": True}, confidence=1.0, data_health={},
    ))

    connection = client.ws("/api/monitors/_/stream")
    try:
        bus.wait_for_listeners(1)
        bus.deliver("", api.OBSERVATION, observation)
        bus.deliver("", api.VERDICT, RECORDED_VERDICT)
        first = json.loads(connection.recv())
        second = json.loads(connection.recv())
    finally:
        connection.close()

    assert [first["topic"], second["topic"]] == [api.OBSERVATION, api.VERDICT]


# ============================================================== REST


def test_rest_manifest_matches_the_latched_topic_value(serve):
    bus = FakeBus(namespaces=[""], latched={("", api.MANIFEST): RECORDED_MANIFEST})
    client = serve(bus)

    status, text = client.get("/api/monitors/_/manifest")
    assert status == 200
    assert text == RECORDED_MANIFEST          # verbatim, not re-encoded


def test_rest_adapter_and_spec_status_are_routed_from_the_latched_topic_set(serve):
    """The latched REST verbs are derived from api.LATCHED_TOPICS, not listed here."""
    adapter = json.dumps(api.build_adapter(
        adapter="real_g1", doc="the real G1", tick_hz=1.0,
        schema={"min_range": {"doc": "float", "default": 10.0}}, sources=[],
    ))
    spec_status = json.dumps(api.build_spec_status(ok=True, skill_name="G1"))
    bus = FakeBus(
        namespaces=[""],
        latched={("", api.ADAPTER): adapter, ("", api.SPEC_STATUS): spec_status},
    )
    client = serve(bus)

    assert client.get("/api/monitors/_/adapter") == (200, adapter)
    assert client.get("/api/monitors/_/spec_status") == (200, spec_status)
    assert set(gateway.LATCHED_ROUTES.values()) == set(api.LATCHED_TOPICS)


def test_missing_latched_value_is_404_not_an_empty_object(serve):
    """An absent manifest and a manifest with no fields are different facts."""
    client = serve(FakeBus(namespaces=[""]))
    status, text = client.get("/api/monitors/_/manifest")
    assert status == 404
    body = json.loads(text)
    assert body["ok"] is False
    assert body["topic"] == api.MANIFEST


def test_there_is_no_latest_endpoint(serve):
    """WS is the stream, REST is the sample: a per-tick polling route invites a loop
    that silently misses ticks, so it does not exist."""
    client = serve(FakeBus(namespaces=[""]))
    for path in ("/api/monitors/_/latest",
                 "/api/monitors/_/verdict",
                 "/api/monitors/_/observation"):
        status, _text = client.get(path)
        assert status == 404, path


def test_stream_without_an_upgrade_is_426_not_a_snapshot(serve):
    client = serve(FakeBus(namespaces=[""]))
    status, text = client.get("/api/monitors/_/stream")
    assert status == 426
    assert "websocket" in json.loads(text)["error"]


# ============================================================== discovery


def test_empty_graph_serves_an_empty_monitor_list_not_an_error(serve):
    """Standalone: nothing on the graph is an answer, not a failure."""
    client = serve(gateway.NullBus("no rclpy in this process"), gateway.NullClockBackend())

    status, body = client.json("/api/monitors")
    assert status == 200
    assert body["monitors"] == []
    # ... and it names what it cannot see, so "nothing is running" is distinguishable
    # from "the gateway is broken".
    assert body["services"]["ros"]["available"] is False
    assert "rclpy" in body["services"]["ros"]["detail"]
    assert body["services"]["clock"]["reachable"] is False

    status, health = client.json("/api/health")
    assert status == 200
    assert health["ok"] is True
    assert health["auth"] == "none"


def test_monitor_list_reports_live_stale_and_gone(serve):
    now = time.time()
    bus = FakeBus(
        namespaces=["", "/nav", "/arm"],
        last_seen={"": now, "/nav": now - 60.0},   # "/arm" has never published
        latched={("", api.MANIFEST): RECORDED_MANIFEST},
    )
    client = serve(bus, stale_after=5.0)

    _status, body = client.json("/api/monitors")
    by_ns = {m["ns"]: m for m in body["monitors"]}
    assert by_ns[""]["health"] == "live"
    assert by_ns["/nav"]["health"] == "stale"      # crashed after publishing
    assert by_ns["/arm"]["health"] == "gone"       # never started
    assert by_ns["/arm"]["last_seen"] is None
    assert by_ns[""]["skill_name"] == "G1HumanoidNavigation"
    # Every entry carries the URL segment, so a client never derives it.
    assert by_ns[""]["path"] == "_"
    assert by_ns["/nav"]["path"] == "nav"


def test_parse_namespaces_keys_off_the_verdict_topic():
    """A monitor is anything publishing <ns>/monitor/verdict -- discovery mirrors the
    topic contract rather than a registry."""
    assert gateway.parse_namespaces([api.VERDICT]) == [""]
    assert gateway.parse_namespaces(
        [f"/nav{api.VERDICT}", f"/arm{api.VERDICT}", api.OBSERVATION]
    ) == ["/arm", "/nav"]
    assert gateway.parse_namespaces([api.VERDICT + "_debug", "/other"]) == []
    assert gateway.parse_namespaces([]) == []
    assert gateway.parse_namespaces(None) == []
    assert gateway.parse_namespaces([None, 7]) == []


def test_health_distinguishes_crashed_from_never_started():
    assert gateway.health(None, 100.0) == "gone"
    assert gateway.health(99.0, 100.0, stale_after=5.0) == "live"
    assert gateway.health(90.0, 100.0, stale_after=5.0) == "stale"


def test_namespace_url_segments_round_trip():
    for ns in ("", "/nav", "/nav/left"):
        assert gateway.segment_to_ns(gateway.ns_to_segment(ns)) == ns
    assert gateway.ns_to_segment("") == "_"
    assert gateway.segment_to_ns("_") == ""


def test_nested_namespace_is_addressable(serve):
    bus = FakeBus(namespaces=["/nav/left"],
                  latched={("/nav/left", api.MANIFEST): RECORDED_MANIFEST})
    client = serve(bus)
    assert client.get("/api/monitors/nav/left/manifest") == (200, RECORDED_MANIFEST)


# ============================================================== ingress


def test_command_post_publishes_the_matching_topic_message(serve):
    bus = FakeBus(namespaces=["/nav"])
    client = serve(bus)

    status, text = client.post("/api/monitors/nav/command",
                               api.build_command(command="reset"))
    assert status == 202
    assert json.loads(text)["ok"] is True

    assert len(bus.published) == 1
    ns, topic, payload_text = bus.published[0]
    assert (ns, topic) == ("/nav", api.COMMAND)
    assert json.loads(payload_text) == api.build_command(command="reset")


def test_command_post_rejects_a_payload_the_contract_refuses(serve):
    """Validation is `api.validate_for_topic`, so the problem list a client sees is the
    same one every other consumer of the contract produces."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    status, text = client.post("/api/monitors/_/command",
                               {"schema_version": 1, "command": "self_destruct"})
    assert status == 400
    body = json.loads(text)
    assert body["ok"] is False
    assert any("command" in problem for problem in body["problems"])
    assert bus.published == []          # nothing reached the graph


def test_command_post_without_a_ros_side_is_503_not_500(serve):
    client = serve(FakeBus(namespaces=[""], publishable=False))
    status, text = client.post("/api/monitors/_/command",
                               api.build_command(command="arm"))
    assert status == 503
    assert json.loads(text)["ok"] is False


def test_spec_post_returns_the_monitors_spec_status(serve):
    spec = {"skill_name": "Walk", "execution_phases": [{"phase": "Go"}]}
    reply = json.dumps(api.build_spec_status(ok=True, skill_name="Walk"), indent=2)
    bus = FakeBus(namespaces=[""])
    bus.spec_status_reply = reply
    client = serve(bus, spec_timeout=2.0)

    status, text = client.post("/api/monitors/_/spec", spec)
    assert status == 200
    assert text == reply                       # the monitor's own answer, verbatim

    ns, topic, payload_text = bus.published[0]
    assert (ns, topic) == ("", api.LOAD_SPEC)
    # A bare spec document is wrapped into the load_spec envelope; the spec itself is
    # passed through unaltered.
    assert json.loads(payload_text)["spec"] == spec


def test_spec_post_accepts_the_load_spec_envelope_too(serve):
    spec = {"skill_name": "Walk", "execution_phases": []}
    bus = FakeBus(namespaces=[""])
    bus.spec_status_reply = json.dumps(api.build_spec_status(ok=True, skill_name="Walk"))
    client = serve(bus, spec_timeout=2.0)

    status, _text = client.post("/api/monitors/_/spec",
                                api.build_load_spec(spec=spec, source="pushed"))
    assert status == 200
    assert json.loads(bus.published[0][2])["source"] == "pushed"


def test_spec_post_returns_400_when_the_monitor_rejects_it(serve):
    reply = json.dumps(api.build_spec_status(
        ok=False, problems=["phase 'Go': unknown sensor 'lidar'"], skill_name="Walk"))
    bus = FakeBus(namespaces=[""])
    bus.spec_status_reply = reply
    client = serve(bus, spec_timeout=2.0)

    status, text = client.post("/api/monitors/_/spec", {"skill_name": "Walk"})
    assert status == 400
    assert text == reply


def test_spec_post_times_out_into_504_with_the_last_known_status(serve):
    """A monitor that never answers must not hang the request thread forever."""
    previous = json.dumps(api.build_spec_status(ok=True, skill_name="Old"))
    bus = FakeBus(namespaces=[""], latched={("", api.SPEC_STATUS): previous})
    bus.spec_status_reply = None               # the fake monitor stays mute
    client = serve(bus, spec_timeout=0.2)

    status, text = client.post("/api/monitors/_/spec", {"skill_name": "Walk"})
    assert status == 504
    assert json.loads(text)["last_known"] == previous


# ============================================================== backpressure


def test_slow_client_is_dropped_oldest_and_told():
    """The queue sheds the oldest frame and every frame carries the count, because a
    silent drop is indistinguishable from a monitor that stopped."""
    stream = gateway.ClientStream(maxlen=2)
    for seq in range(10):
        stream.offer((api.VERDICT, json.dumps({"seq": seq})))

    (topic, text), dropped = stream.take(timeout=0)
    assert dropped == 8                       # 10 offered, 2 retained
    assert json.loads(text)["seq"] == 8       # oldest gone, newest kept

    frame = json.loads(gateway.stream_frame("", topic, text, dropped))
    assert frame["dropped"] == 8

    (_topic, text), dropped = stream.take(timeout=0)
    assert json.loads(text)["seq"] == 9
    assert dropped == 8                       # cumulative since connect, monotonic
    assert stream.take(timeout=0) is None


def test_offering_to_a_closed_stream_never_raises():
    """The offer runs on a ROS subscription callback; nothing there may raise or block."""
    stream = gateway.ClientStream(maxlen=1)
    stream.close()
    stream.offer((api.VERDICT, "{}"))
    assert stream.take(timeout=0) is None
    assert stream.dropped == 0


def test_a_full_queue_does_not_block_the_publisher():
    stream = gateway.ClientStream(maxlen=1)
    started = time.monotonic()
    for seq in range(5000):
        stream.offer((api.VERDICT, json.dumps({"seq": seq})))
    assert time.monotonic() - started < 2.0
    assert stream.dropped == 4999


def test_a_disconnected_client_stops_its_subscription(serve):
    bus = FakeBus(namespaces=[""])
    client = serve(bus)
    connection = client.ws("/api/monitors/_/stream")
    bus.wait_for_listeners(1)
    connection.close()

    deadline = time.monotonic() + 5.0
    while bus.listener_count() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert bus.listener_count() == 0


# ============================================================== frame assembly


def test_stream_frame_embeds_the_payload_verbatim():
    payload = '{"b": 1,   "a": 2}'            # key order and spacing json.dumps would lose
    frame_text = gateway.stream_frame("/nav", api.VERDICT, payload, 3)
    assert gateway.frame_payload_text(frame_text) == payload
    frame = json.loads(frame_text)
    assert frame == {"ns": "/nav", "topic": api.VERDICT, "dropped": 3,
                     "payload": {"b": 1, "a": 2}}


def test_a_malformed_payload_does_not_break_the_envelope():
    """Embedding unparseable text would take `dropped` down with it -- the one field
    telling a client it is losing frames."""
    frame = json.loads(gateway.stream_frame("", api.VERDICT, "not json at all", 7))
    assert frame["payload"] is None
    assert frame["dropped"] == 7
    assert frame["problems"]


# ============================================================== clock proxy


CLOCK_PATHS = [
    ("GET", "/api/clock"),
    ("GET", "/api/clock/health"),
    ("POST", "/api/clock/mode"),
    ("POST", "/api/clock/step"),
    ("POST", "/api/clock/rate"),
]


def test_clock_proxy_paths_match_the_clocks_own_paths(serve):
    """Same paths, so the frontend needs one origin and not two CORS policies."""
    clock = FakeClock()
    client = serve(FakeBus(), clock)

    for method, path in CLOCK_PATHS:
        status, text = client.request(method, path, {} if method == "POST" else None)
        assert status == 200, path
        assert json.loads(text)["seen"] == path

    assert [(method, path) for method, path, _body in clock.calls] == CLOCK_PATHS


def test_clock_proxy_forwards_paths_it_has_never_heard_of(serve):
    """The gateway does not enumerate the clock's endpoints, so a path P1 adds later
    works without an edit here."""
    clock = FakeClock()
    client = serve(FakeBus(), clock)

    client.get("/api/clock/something-p1-adds-later?verbose=1")
    assert clock.calls[-1][1] == "/api/clock/something-p1-adds-later?verbose=1"


def test_clock_proxy_forwards_the_request_body(serve):
    clock = FakeClock()
    client = serve(FakeBus(), clock)
    client.post("/api/clock/rate", {"tick_hz": 5.0})
    assert json.loads(clock.calls[-1][2]) == {"tick_hz": 5.0}


def test_an_absent_clock_is_503_with_the_reason(serve):
    clock = FakeClock()
    clock.reachable = False
    client = serve(FakeBus(), clock)

    status, text = client.get("/api/clock")
    assert status == 503
    assert json.loads(text)["service"] == "clock"


def test_clock_stream_is_proxied_frame_for_frame(serve):
    """docs/api.md: the clock's stream frame is the identical payload to /monitor/tick,
    so wrapping it here would make the proxied path differ from the direct one."""
    tick = json.dumps(api.build_tick(seq=7, t=7.0, tick_hz=1.0), indent=2)
    clock = FakeClock(frames=[tick])
    client = serve(FakeBus(), clock)

    connection = client.ws("/api/clock/stream")
    try:
        assert connection.recv() == tick
    finally:
        connection.close()


# ============================================================== websocket codec


@pytest.mark.parametrize("size", [0, 5, 125, 126, 200, 65535, 65536])
@pytest.mark.parametrize("mask", [False, True])
def test_websocket_frames_round_trip_at_every_length_boundary(size, mask):
    import io

    payload = b"x" * size
    encoded = gateway.ws_encode(payload, gateway.OP_TEXT, mask=mask)
    opcode, decoded = gateway.ws_read(io.BytesIO(encoded))
    assert opcode == gateway.OP_TEXT
    assert decoded == payload


def test_websocket_reassembles_a_fragmented_message():
    import io

    first = bytes([0x01, 0x03]) + b"abc"       # text, not final
    last = bytes([0x80, 0x03]) + b"def"        # continuation, final
    opcode, payload = gateway.ws_read(io.BytesIO(first + last))
    assert (opcode, payload) == (gateway.OP_TEXT, b"abcdef")


def test_websocket_read_at_eof_is_a_disconnect_not_a_crash():
    import io

    with pytest.raises(ConnectionError):
        gateway.ws_read(io.BytesIO(b""))


def test_accept_key_matches_rfc_6455():
    # The example from RFC 6455 section 1.3.
    assert gateway.ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == \
        "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


# ============================================================== misc


def test_unknown_paths_are_404(serve):
    client = serve(FakeBus())
    assert client.get("/")[0] == 404
    assert client.get("/api/nope")[0] == 404
    assert client.get("/api/monitors/_")[0] == 404


def test_cors_is_open_because_there_is_no_authentication(serve):
    client = serve(FakeBus())
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    try:
        connection.request("OPTIONS", "/api/monitors")
        response = connection.getresponse()
        response.read()
        assert response.getheader("Access-Control-Allow-Origin") == "*"
    finally:
        connection.close()


def test_the_module_documents_that_it_has_no_authentication():
    """A deployment reading this file must not have to infer the absence of auth."""
    doc = gateway.__doc__ or ""
    assert "No authentication" in doc
    assert "TLS" in doc


def test_no_monitor_topic_literal_is_spelled_in_this_module():
    """Topic names live in core/api.py and nowhere else.

    Docstrings and comments name the topics in prose -- that is documentation. A string
    *constant* would be a second source of truth, and the `/ltl/*` rename would then be
    a sweep that a branch could forget.
    """
    import ast
    from pathlib import Path

    # Derived, not spelled: tests/test_api.py runs this same rule over tests/ too.
    prefix = api.TICK.rsplit("/", 1)[0] + "/"

    tree = ast.parse(Path(gateway.__file__).read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    offenders = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and prefix in node.value
    ]
    assert offenders == []


def test_body_larger_than_the_cap_is_413(serve):
    """Refused on the declared length, before a byte of it is read into memory."""
    client = serve(FakeBus(namespaces=[""]))
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    try:
        connection.putrequest("POST", "/api/monitors/_/spec")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(gateway.MAX_BODY_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        assert response.status == 413
    finally:
        connection.close()


def test_build_bus_falls_back_to_the_null_bus_without_ros():
    """A broken ROS install must yield a gateway that says so over HTTP, not a
    restart loop with the reason only in a log."""
    bus = gateway.build_bus(use_ros=True)
    assert bus.namespaces() == [] or isinstance(bus, gateway.RclpyBus)
    if isinstance(bus, gateway.NullBus):
        assert bus.status()["available"] is False
        assert bus.status()["detail"]


def test_no_ros_flag_yields_the_null_bus():
    bus = gateway.build_bus(use_ros=False)
    assert isinstance(bus, gateway.NullBus)
    assert "--no-ros" in bus.status()["detail"]
    with pytest.raises(gateway.BusUnavailable):
        bus.publish("", api.COMMAND, "{}")
