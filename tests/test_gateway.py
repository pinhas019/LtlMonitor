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
import socket
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
    """A tiny HTTP client bound to a running gateway.

    Every request carries `X-Skill-Monitor`, because that is what a non-browser client
    does in one line -- and because the routes that require it now include every proxied
    clock request, GET included. `client_header=False` is how a test plays the part of a
    browser, which cannot set it.
    """

    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None, *, client_header=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            sent = {"Content-Type": "application/json"} if payload else {}
            if client_header:
                sent[gateway.CLIENT_HEADER] = "1"
            sent.update(headers or {})
            connection.request(method, path, payload, sent)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, body, **kwargs):
        return self.request("POST", path, body, **kwargs)

    def json(self, path):
        status, text = self.get(path)
        return status, json.loads(text)

    def headers_for(self, method, path, headers=None, body=None):
        """The response *headers* of one request, which is what a CORS test is about."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            connection.request(method, path, payload, headers or {})
            response = connection.getresponse()
            response.read()
            return response.status, dict(response.getheaders())
        finally:
            connection.close()

    def upgrade(self, path, headers=None):
        """A websocket upgrade attempt that reports the HTTP status instead of raising,
        so a refusal can be asserted on. Only for refusals: a 101 has no body to read."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", path, headers={
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                "Sec-WebSocket-Version": "13",
                **(headers or {}),
            })
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            return response.status, body
        finally:
            connection.close()

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


def test_the_stream_carries_the_run_state(serve):
    """A paused monitor publishes nothing else at all, so a console with a page already
    open would watch a completely idle stream and read it as a calm run. It has to be
    told, on the connection it is already holding, that another operator just stopped
    the monitoring on a robot that is still moving."""
    assert api.MONITOR_STATUS in gateway.STREAM_TOPICS

    bus = FakeBus(namespaces=[""])
    client = serve(bus)
    paused = json.dumps(api.build_monitor_status(
        seq=1041, t=1041.0, state="paused", reason="operator command", since_seq=1038,
    ))

    connection = client.ws("/api/monitors/_/stream")
    try:
        bus.wait_for_listeners(1)
        bus.deliver("", api.MONITOR_STATUS, paused)
        frame_text = connection.recv()
    finally:
        connection.close()

    frame = json.loads(frame_text)
    assert frame["topic"] == api.MONITOR_STATUS
    assert frame["payload"]["state"] == "paused"
    assert gateway.frame_payload_text(frame_text) == paused


def test_the_run_state_has_a_rest_route_of_its_own(serve):
    """The other half, and the one a *newly* connecting console needs. The stream only
    carries changes, and the change a page joining mid-pause is waiting for is the
    operator who caused the pause deciding to end it. Latched plus a derived GET is how
    it learns the truth on connect instead of on the operator's next keypress."""
    assert api.MONITOR_STATUS in api.LATCHED_TOPICS
    assert gateway.LATCHED_ROUTES["status"] == api.MONITOR_STATUS
    assert set(gateway.LATCHED_ROUTES.values()) == set(api.LATCHED_TOPICS)

    paused = json.dumps(api.build_monitor_status(
        seq=1041, t=1041.0, state="paused", reason="operator command", since_seq=1038,
    ))
    bus = FakeBus(namespaces=[""], latched={("", api.MONITOR_STATUS): paused})
    client = serve(bus)

    assert client.get("/api/monitors/_/status") == (200, paused)


def test_a_monitor_with_no_run_state_latched_is_404_not_a_guess(serve):
    """"No status yet" is not "running". A gateway that filled in the optimistic
    default would be inventing the one fact this topic exists to stop anyone
    inferring."""
    client = serve(FakeBus(namespaces=[""]))
    status, text = client.get("/api/monitors/_/status")
    assert status == 404
    assert json.loads(text)["topic"] == api.MONITOR_STATUS


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
    body = json.loads(text)
    assert body["last_known"] == previous
    # Enough for a client to recover rather than guess: the spec DID go out, this is how
    # long we waited, and this is the one request that settles what happened to it.
    assert body["published"] is True
    assert body["timeout_s"] == 0.2
    assert body["retry_with"] == "/api/monitors/_/spec_status"
    assert "request id" in body["why"]


def test_post_spec_documents_the_correlation_it_cannot_do(serve):
    """The 504 has a second cause the body cannot distinguish -- a spec that fails
    identically twice -- and concurrent pushes can be handed each other's status. Both
    need a `request_id` echoed in spec_status, which is a P0/P4 contract change and not
    this file's to make. What this file owes the next reader is saying so.
    """
    doc = gateway.Gateway.post_spec.__doc__ or ""
    assert "request_id" in doc
    assert "Concurrent pushes cross" in doc
    assert "one at a time" in doc


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
    tick = json.dumps(api.build_tick(seq=7, t=7.0, t0=0.0, tick_hz=1.0), indent=2)
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


def test_the_module_documents_that_it_has_no_authentication():
    """A deployment reading this file must not have to infer the absence of auth, and
    must be told where to put it -- at the point in the file where the decision is
    made, not in a brief nobody reads at 3am."""
    doc = gateway.__doc__ or ""
    assert "No authentication" in doc
    assert "TLS" in doc
    assert "terminate TLS and authenticate in front of" in doc
    assert "127.0.0.1" in doc                  # ... and that the default is loopback


# ================================================== the trust boundary
#
# The gateway's whole security model is "anything that can reach the port", so these
# tests are about reach: which host it binds, which requests a browser on another origin
# can send, and what a URL segment is allowed to become.


def test_the_default_bind_is_loopback_and_exposure_is_deliberate():
    """This is the robot's control surface with no authentication in front of it.
    0.0.0.0 must be something an operator typed, not something they inherited."""
    assert gateway.DEFAULT_HOST == "127.0.0.1"
    assert gateway.build_parser().parse_args([]).host == "127.0.0.1"
    assert gateway.build_parser().parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"

    import inspect
    default = inspect.signature(gateway.GatewayServer.__init__).parameters["host"].default
    assert default == "127.0.0.1"


BROWSER_PREFLIGHT = {
    "Origin": "https://an-operator-happened-to-visit.example",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}

STATE_CHANGING_PATHS = [
    "/api/monitors/_/command",
    "/api/monitors/_/spec",
    "/api/clock/mode",
    "/api/clock/step",
    "/api/clock/rate",
]


@pytest.mark.parametrize("path", STATE_CHANGING_PATHS)
def test_a_browser_preflight_cannot_unlock_a_state_changing_post(serve, path):
    """The vulnerability this closes, stated as the browser sees it.

    `Allow-Origin: *` plus `Allow-Methods: POST` plus `Allow-Headers: Content-Type` is a
    successful preflight, and a successful preflight means the browser SENDS the
    cross-origin JSON POST. The attacker cannot read the reply and does not need to:
    `{"command": "pause"}` on a live mission, or a pushed spec that redefines what counts
    as a failure, is a write, and the write is the payoff.

    So the preflight for these routes must grant nothing.
    """
    client = serve(FakeBus(namespaces=[""]))
    status, headers = client.headers_for("OPTIONS", path, BROWSER_PREFLIGHT)
    assert status in (204, 200)
    assert "Access-Control-Allow-Origin" not in headers, path
    assert "Access-Control-Allow-Headers" not in headers, path


def test_a_cross_origin_post_that_ignores_the_preflight_is_still_refused(serve):
    """Defence that does not depend on the browser behaving: without the header a
    cross-origin fetch cannot set, nothing reaches the graph."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    status, text = client.post("/api/monitors/_/command",
                               api.build_command(command="pause"),
                               client_header=False)
    assert status == 403
    assert gateway.CLIENT_HEADER in json.loads(text)["error"]
    assert bus.published == []                 # nothing reached the graph

    # The same request with the header -- one line for a script, impossible for a page
    # on another origin -- works.
    assert client.post("/api/monitors/_/command",
                       api.build_command(command="pause"))[0] == 202


def test_the_client_header_is_required_on_every_state_changing_route(serve):
    """Including the proxied clock writes: `POST /api/clock/rate` while an episode runs
    silently redefines every tick-denominated timeout in the spec."""
    clock = FakeClock()
    client = serve(FakeBus(namespaces=[""]), clock)
    for path in STATE_CHANGING_PATHS:
        status, _text = client.post(path, {}, client_header=False)
        assert status == 403, path
    assert clock.calls == []                   # not forwarded, not merely unanswered


def test_an_unnamed_origin_cannot_read_the_robots_telemetry_either(serve):
    """There is no CORS wildcard left, not even on the reads.

    `/api/monitors`, `manifest` and `adapter` are the robot's sensor topology and
    resolved schema, and the stream beside them is live sensor values and AP truth. A
    page the operator happens to visit is not entitled to read what the robot senses and
    whether it is about to fail, so the grant is by name or not at all. Nothing here
    touches a non-browser client: CORS is enforced by the browser.
    """
    client = serve(FakeBus(namespaces=[""]))

    for path in ("/api/monitors", "/api/health", "/api/monitors/_/manifest"):
        _status, headers = client.headers_for("GET", path,
                                              {"Origin": "https://not-named.example"})
        assert "Access-Control-Allow-Origin" not in headers, path
        assert headers.get("Vary") == "Origin", path

    _status, headers = client.headers_for("OPTIONS", "/api/monitors", {
        "Origin": "https://not-named.example", "Access-Control-Request-Method": "GET",
    })
    assert "Access-Control-Allow-Origin" not in headers


def test_a_named_origin_reads_across_origins(serve):
    """... and the deployment that has a browser console names it, which is the same
    switch that opens the writes and the stream."""
    client = serve(FakeBus(namespaces=[""]), allowed_origins=("https://console.lab",))
    _status, headers = client.headers_for("GET", "/api/monitors",
                                          {"Origin": "https://console.lab"})
    assert headers["Access-Control-Allow-Origin"] == "https://console.lab"


def test_the_reads_need_no_header_so_a_script_stays_one_line(serve):
    """The header gate is on the writes and on the clock proxy, not on reading a
    verdict: a curl one-liner must still work."""
    client = serve(FakeBus(namespaces=[""]))
    assert client.get("/api/monitors", client_header=False)[0] == 200
    assert client.get("/api/health", client_header=False)[0] == 200


def test_a_named_origin_is_the_deliberate_way_to_allow_a_browser_console(serve):
    """--allow-origin is the explicit allow: a deployment that has a browser frontend
    names its origin, and only that origin gets the grant."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus, allowed_origins=("https://console.lab",))

    _status, headers = client.headers_for("OPTIONS", "/api/monitors/_/command", {
        "Origin": "https://console.lab",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": f"content-type, {gateway.CLIENT_HEADER.lower()}",
    })
    assert headers["Access-Control-Allow-Origin"] == "https://console.lab"
    assert gateway.CLIENT_HEADER in headers["Access-Control-Allow-Headers"]

    # ... and nobody else, so the grant cannot be borrowed.
    _status, headers = client.headers_for("OPTIONS", "/api/monitors/_/command",
                                          BROWSER_PREFLIGHT)
    assert "Access-Control-Allow-Origin" not in headers


# ================================================== namespaces from a URL


ILLEGAL_SEGMENTS = [
    "../../etc",          # becomes the topic /../../etc/monitor/command
    "%2e%2e",             # the same thing, escaped -- refused, not decoded
    "nav/../arm",
    "9lives",             # a ROS name may not start with a digit
    "has-a-dash",
    "~private",           # legal in a URL, not a ROS name
    "nav.left",
    "n" * 200,            # a name long enough to be a payload of its own
]


@pytest.mark.parametrize("segment", ILLEGAL_SEGMENTS)
def test_an_illegal_namespace_segment_is_400_and_never_a_publisher(serve, segment):
    """A segment arrives from an unauthenticated client and three calls later is a topic
    name. An illegal one must come back as this gateway's 400 with a reason, not as a
    500 out of rclpy -- and must never create a publisher on a name the client chose."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    status, text = client.post(f"/api/monitors/{segment}/command",
                               api.build_command(command="reset"))
    assert status == 400, segment
    assert json.loads(text)["ok"] is False
    assert bus.published == []

    assert client.get(f"/api/monitors/{segment}/manifest")[0] == 400, segment


def test_a_namespace_discovery_has_never_seen_is_404(serve):
    """There is no monitor there. Creating a publisher so a command can be sent to
    nobody is not a service worth offering."""
    bus = FakeBus(namespaces=["/nav"])
    client = serve(bus)

    status, text = client.post("/api/monitors/arm/command",
                               api.build_command(command="reset"))
    assert status == 404
    assert json.loads(text)["ns"] == "/arm"
    assert bus.published == []
    assert client.get("/api/monitors/arm/manifest")[0] == 404
    assert client.upgrade("/api/monitors/arm/stream")[0] == 404

    # The discovered one still works, so this is a check and not a wall.
    assert client.post("/api/monitors/nav/command",
                       api.build_command(command="reset"))[0] == 202


def test_an_unavailable_bus_still_answers_503_and_not_404(serve):
    """With no ROS side every namespace is undiscovered, and "there is no such monitor"
    would be the wrong answer: the honest one is "there is no ROS side"."""
    client = serve(gateway.NullBus("no rclpy in this process"))
    status, text = client.post("/api/monitors/_/command", api.build_command(command="arm"))
    assert status == 503
    assert "rclpy" in json.loads(text)["error"]


def test_namespace_problem_states_the_ros_name_grammar():
    from skill_monitor.core import discovery

    assert discovery.namespace_problem("") is None
    assert discovery.namespace_problem("/nav") is None
    assert discovery.namespace_problem("/nav/left_1") is None
    assert discovery.namespace_problem("/_private") is None

    for bad in ("nav", "/nav/", "/../etc", "/9lives", "/has-a-dash", "/a b", "/nav//left"):
        assert discovery.namespace_problem(bad), bad
    assert discovery.namespace_problem("/" + "n" * 200)
    assert discovery.namespace_problem(None)


def test_segment_problem_is_the_url_face_of_the_same_rule():
    assert gateway.segment_problem("_") is None
    assert gateway.segment_problem("") is None
    assert gateway.segment_problem("nav/left") is None
    assert gateway.segment_problem("../../etc")


# ================================================== the stream cap


def test_streams_are_capped_and_the_refusal_says_so(serve):
    """Each stream holds a thread under ThreadingHTTPServer. The per-client deque bounds
    memory; nothing bounded threads, and an unauthenticated client could open them in a
    loop."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus, max_streams=1)

    first = client.ws("/api/monitors/_/stream")
    try:
        bus.wait_for_listeners(1)
        status, text = client.upgrade("/api/monitors/_/stream")
        assert status == 503
        assert json.loads(text)["max_streams"] == 1
        # The clock's proxied stream comes out of the same budget -- it is the same
        # thread parked on the same kind of socket.
        assert client.upgrade("/api/clock/stream")[0] == 503
    finally:
        first.close()

    # The slot comes back, so this is a cap and not a one-shot.
    deadline = time.monotonic() + 5.0
    while bus.listener_count() and time.monotonic() < deadline:
        time.sleep(0.02)
    second = client.ws("/api/monitors/_/stream")
    second.close()


def test_stream_slots_are_counted_and_returned():
    app = gateway.Gateway(FakeBus(), max_streams=2)
    assert app.acquire_stream() and app.acquire_stream()
    assert app.open_streams == 2
    assert app.acquire_stream() is False
    app.release_stream()
    assert app.acquire_stream() is True
    app.release_stream()
    app.release_stream()
    assert app.open_streams == 0
    app.release_stream()                       # never goes negative
    assert app.open_streams == 0


def test_health_reports_the_stream_budget(serve):
    """So an operator whose next panel is refused can see the cap rather than guess."""
    client = serve(FakeBus(), max_streams=7)
    _status, body = client.json("/api/health")
    assert body["streams"] == {"open": 0, "max": 7}


# ================================================== one discovery, two clients


def test_the_gateway_does_not_add_a_third_copy_of_discovery():
    """The honest claim, which is narrower than "there is now one implementation".

    `parse_namespaces` and `health` were copied into the gateway from the Skill Center.
    The gateway's copy is gone and these names are re-exports of `core.discovery`.
    `frontend/skill_center.py` still has its own -- that file belongs to P7 and this
    package must not edit it, so the duplication is reduced from three to two and P7
    closes it. Asserting anything stronger here would be a test that lies.
    """
    from skill_monitor.core import discovery

    assert gateway.parse_namespaces is discovery.parse_namespaces
    assert gateway.health is discovery.health
    assert gateway.STALE_AFTER == discovery.STALE_AFTER

    from pathlib import Path
    source = Path(gateway.__file__).read_text(encoding="utf-8")
    assert "def parse_namespaces" not in source
    assert "def health(" not in source
    # And the module that owns them says the same thing, rather than claiming the
    # migration is finished while a second copy is still shipping.
    assert "not yet the only implementation" in (discovery.__doc__ or "")


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
        connection.putheader(gateway.CLIENT_HEADER, "1")
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


# ================================================== requests that are not what they look like
#
# These are driven over a real loopback socket, deliberately. A fabricated handler cannot
# observe connection state -- whether a second pipelined request executed, whether the
# socket was closed -- and connection state is exactly what is under test.


def raw_exchange(port, request_bytes, timeout=10.0):
    """Send bytes, read until the server closes or goes quiet. Returns what came back."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(request_bytes)
        received = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received += chunk
        except socket.timeout:
            pass
        return received
    finally:
        sock.close()


def test_transfer_encoding_is_refused_so_a_proxy_cannot_be_desynced(serve):
    """CL.TE request smuggling, against the very proxy this package tells people to run.

    This handler frames by Content-Length; RFC 9112 requires a proxy to prefer
    Transfer-Encoding. Accepting both means the proxy and this process disagree about
    where the first request ends, and the trailing bytes become a second request the
    proxy never saw -- past the authentication the documented deployment puts there, and
    carrying `X-Skill-Monitor` because the attacker writes that header themselves.

    Over a real socket, because "the smuggled request did not execute" and "the
    connection was closed" are both facts about the connection.
    """
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    reset = json.dumps(api.build_command(command="reset"))
    smuggled = (
        f"POST /api/monitors/_/command HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{client.port}\r\n"
        f"{gateway.CLIENT_HEADER}: smuggled\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(reset)}\r\n\r\n{reset}"
    )
    body = "0\r\n\r\n" + smuggled
    request = (
        f"POST /api/monitors/_/command HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{client.port}\r\n"
        f"{gateway.CLIENT_HEADER}: 1\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: 5\r\n"
        f"Transfer-Encoding: chunked\r\n\r\n{body}"
    )

    received = raw_exchange(client.port, request.encode("utf-8"))

    assert received.startswith(b"HTTP/1.1 400")
    assert received.count(b"HTTP/1.1 ") == 1        # one response, never two
    assert b"Connection: close" in received         # said on the wire, not merely done
    assert bus.published == []                      # the smuggled command never ran


def test_transfer_encoding_is_refused_even_without_a_content_length(serve):
    """TE alone is refused too: this server does not implement chunked framing, so
    accepting it would mean guessing where the body ends."""
    client = serve(FakeBus(namespaces=[""]))
    request = (
        f"POST /api/monitors/_/command HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{client.port}\r\n"
        f"{gateway.CLIENT_HEADER}: 1\r\n"
        f"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
    )
    received = raw_exchange(client.port, request.encode("utf-8"))
    assert received.startswith(b"HTTP/1.1 400")
    assert b"Transfer-Encoding" in received


def test_a_pipelined_request_on_a_healthy_connection_still_works(serve):
    """The refusal above is about ambiguous framing, not about keep-alive: two properly
    framed requests on one connection both run, so the fix is not a blanket hang-up."""
    client = serve(FakeBus(namespaces=[""]))
    one = (f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{client.port}\r\n\r\n")
    received = raw_exchange(client.port, (one + one).encode("utf-8"), timeout=2.0)
    assert received.count(b"HTTP/1.1 200") == 2


# ================================================== Host, and DNS rebinding


def test_a_request_addressed_to_another_name_is_refused(serve):
    """DNS rebinding walks through the loopback default and the CSRF header together.

    A page on evil.example whose name is re-pointed at 127.0.0.1 after it loads is
    *same-origin* with this gateway: no preflight is sent, no CORS applies, and it sets
    `X-Skill-Monitor` itself. The one thing it cannot change is the Host header the
    browser derives from the name in the URL.
    """
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    status, text = client.post(
        "/api/monitors/_/command", api.build_command(command="reset"),
        headers={"Host": f"evil.example:{client.port}",
                 "Origin": f"http://evil.example:{client.port}"},
    )
    assert status == 400
    assert "evil.example" in json.loads(text)["error"]
    assert bus.published == []

    # The stream is behind the same check, so rebinding cannot read telemetry either.
    assert client.upgrade("/api/monitors/_/stream",
                          headers={"Host": f"evil.example:{client.port}"})[0] == 400


def test_a_named_host_is_served(serve):
    """--allow-host is how a deployment reached by DNS name says so."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus, allowed_hosts=("console.lab",))
    status, _text = client.post("/api/monitors/_/command",
                                api.build_command(command="reset"),
                                headers={"Host": f"console.lab:{client.port}"})
    assert status == 202
    assert len(bus.published) == 1


def test_a_request_with_no_host_header_is_refused(serve):
    """HTTP/1.1 requires one. A request without it is not a browser and is not
    addressed to anything in particular."""
    client = serve(FakeBus(namespaces=[""]))
    received = raw_exchange(
        client.port, b"GET /api/health HTTP/1.0\r\n\r\n", timeout=2.0)
    assert received.startswith(b"HTTP/1.0 400") or received.startswith(b"HTTP/1.1 400")


def test_host_allowed_is_a_pure_check_on_the_names_configured():
    app = gateway.Gateway(FakeBus(), allowed_hosts=("console.lab",))
    for good in ("127.0.0.1", "127.0.0.1:8080", "localhost:9", "[::1]:8080",
                 "console.lab", "CONSOLE.LAB:8080"):
        assert app.host_allowed(good), good
    for bad in ("evil.example", "evil.example:8080", "127.0.0.1.evil.example", "", None):
        assert not app.host_allowed(bad), bad

    # '*' is the escape hatch for a deployment whose proxy already does this.
    assert gateway.Gateway(FakeBus(), allowed_hosts=("*",)).host_allowed("anything")


def test_bare_host_strips_the_port_and_keeps_ipv6_brackets():
    assert gateway.bare_host("127.0.0.1:8080") == "127.0.0.1"
    assert gateway.bare_host("Console.Lab") == "console.lab"
    assert gateway.bare_host("[::1]:8080") == "[::1]"
    assert gateway.bare_host("::1") == "::1"
    assert gateway.bare_host(None) == ""


def test_the_host_allowlist_is_derived_from_what_the_deployment_was_told():
    """Loopback is added by the Gateway itself; this is the rest of it."""
    assert gateway.host_allowlist("127.0.0.1", [], []) == {"127.0.0.1"}
    # A wildcard bind names nothing, so a deployment that exposes the gateway also says
    # what it is reached as.
    assert gateway.host_allowlist("0.0.0.0", [], []) == set()
    assert gateway.host_allowlist("0.0.0.0", ["https://console.lab:8443"], []) == \
        {"console.lab"}
    assert "robot.lab" in gateway.host_allowlist("0.0.0.0", [], ["robot.lab"])


# ================================================== parked threads


def test_the_handler_has_a_socket_timeout(serve):
    """MAX_BODY_BYTES checks the declared length, never the arrival rate, so a body
    dribbled a byte at a time parked a thread for as long as the client liked."""
    assert gateway._Handler.timeout == gateway.REQUEST_TIMEOUT_S
    assert 0 < gateway.REQUEST_TIMEOUT_S < 120


def test_a_dribbled_request_is_reclaimed_rather_than_parked_forever(serve, monkeypatch):
    """The timeout shortened so the test is a second rather than twenty, but the
    behaviour under test is the class attribute above."""
    monkeypatch.setattr(gateway._Handler, "timeout", 0.5)
    client = serve(FakeBus(namespaces=[""]))

    sock = socket.create_connection(("127.0.0.1", client.port), timeout=10)
    try:
        # A request that never ends: headers begun, never terminated.
        sock.sendall(b"POST /api/monitors/_/spec HTTP/1.1\r\n")
        sock.sendall(f"Host: 127.0.0.1:{client.port}\r\n".encode())
        started = time.monotonic()
        sock.settimeout(5.0)
        try:
            while sock.recv(4096):
                pass
        except socket.timeout:
            pytest.fail("the server never reclaimed the dribbled connection")
        assert time.monotonic() - started < 5.0
    finally:
        sock.close()


def test_in_flight_requests_are_capped_not_only_streams(serve):
    """`POST .../spec` parks a thread for spec_timeout waiting on a monitor that may be
    mute, and that is not a stream, so the stream cap never saw it."""
    bus = FakeBus(namespaces=[""])
    bus.spec_status_reply = None                    # the monitor stays silent
    client = serve(bus, spec_timeout=2.0, max_requests=1)

    parked = threading.Thread(
        target=lambda: client.post("/api/monitors/_/spec", {"skill_name": "Walk"}),
        daemon=True)
    parked.start()
    try:
        # Wait for the request to actually park rather than polling health against a
        # deadline. The slot is taken before routing and the spec goes out just before
        # the handler blocks, so `published` IS the moment the slot is held. The old
        # poll ran a 2 s deadline against a 2 s spec_timeout and lost that race under
        # load: the parked request finished before health was ever sampled.
        deadline = time.monotonic() + 5.0
        while not bus.published and time.monotonic() < deadline:
            time.sleep(0.005)
        assert bus.published, "the spec never went out, so the request never parked"

        status, text = client.get("/api/health")
        assert status == 503
        assert json.loads(text)["max_requests"] == 1
    finally:
        parked.join(timeout=10.0)

    # The slot comes back when the parked request finishes.
    assert client.get("/api/health")[0] == 200


def test_request_slots_are_counted_and_returned():
    app = gateway.Gateway(FakeBus(), max_requests=2)
    assert app.acquire_request() and app.acquire_request()
    assert app.open_requests == 2
    assert app.acquire_request() is False
    app.release_request()
    assert app.acquire_request() is True
    app.release_request()
    app.release_request()
    app.release_request()                           # never goes negative
    assert app.open_requests == 0


def test_a_stream_hands_its_request_slot_back(serve):
    """A stream is bounded by the stream cap, so holding an in-flight slot for the life
    of the socket would make one viewer eat the request budget."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus, max_requests=2, max_streams=4)
    connection = client.ws("/api/monitors/_/stream")
    try:
        bus.wait_for_listeners(1)
        status, body = client.json("/api/health")
        assert status == 200
        assert body["streams"]["open"] == 1
        assert body["requests"]["open"] == 1        # the health request itself, only
    finally:
        connection.close()


# ================================================== the clock proxy


def test_the_clock_proxy_is_confined_under_its_own_prefix(serve):
    """The proxy forwards whatever arrives under /api/clock without enumerating the
    clock's endpoints. Without normalisation that included `/api/clock/../../secret` --
    an arbitrary path on an upstream this gateway does not police, fetched for an
    anonymous client and handed back."""
    clock = FakeClock()
    client = serve(FakeBus(), clock)

    for path in ("/api/clock/../../secret",
                 "/api/clock/a/../../../../admin/shutdown",
                 "/api/clock/%2e%2e/%2e%2e/secret"):
        status, _text = client.get(path)
        assert status == 400, path
    assert clock.calls == []                        # nothing reached the upstream


def test_a_clock_path_that_merely_looks_odd_still_reaches_the_clock(serve):
    """Normalisation, not rejection-by-vibe: a tidy path inside the prefix goes on."""
    clock = FakeClock()
    client = serve(FakeBus(), clock)
    client.get("/api/clock/a/../health")
    assert clock.calls[-1][1] == "/api/clock/health"


def test_clock_proxy_path_is_pure():
    assert gateway.clock_proxy_path("/api/clock") == "/api/clock"
    assert gateway.clock_proxy_path("/api/clock/step") == "/api/clock/step"
    assert gateway.clock_proxy_path("/api/clock/a/../health") == "/api/clock/health"
    assert gateway.clock_proxy_path("/api/clock/../../secret") is None
    assert gateway.clock_proxy_path("/api/clock/%2e%2e/secret") is None
    assert gateway.clock_proxy_path("/api/monitors") is None


def test_every_clock_request_needs_the_header_including_get(serve):
    """GET was exempt from the header gate by design, and the proxy is deliberately
    method- and path-transparent -- so `GET /api/clock/step`, reachable from an <img>
    tag on any page, advanced a tick. This gateway cannot know which of the clock's GETs
    are side-effect free, so the whole proxied surface is treated as state-changing."""
    clock = FakeClock()
    client = serve(FakeBus(), clock)

    for path in ("/api/clock", "/api/clock/step", "/api/clock/health"):
        status, _text = client.get(path, client_header=False)
        assert status == 403, path
    assert clock.calls == []

    assert client.get("/api/clock/step")[0] == 200   # with the header, as before
    assert clock.calls[-1][1] == "/api/clock/step"


# ================================================== the stream's own origin gate


def test_a_browser_cannot_open_a_stream_it_was_not_named_for(serve):
    """The same-origin policy does not apply to WebSockets, so CORS never protected the
    streams: any page could open one and read live sensor values and AP truth. A browser
    must send Origin on a handshake and cannot forge it; a non-browser client sends
    none."""
    bus = FakeBus(namespaces=[""])
    client = serve(bus)

    status, text = client.upgrade("/api/monitors/_/stream",
                                  headers={"Origin": "https://not-named.example"})
    assert status == 403
    assert "not-named.example" in json.loads(text)["error"]
    assert client.upgrade("/api/clock/stream",
                          headers={"Origin": "https://not-named.example"})[0] == 403

    # No Origin at all -- the desktop console, a script, this file's ws_connect.
    connection = client.ws("/api/monitors/_/stream")
    connection.close()


def test_a_named_origin_may_open_a_stream(serve):
    bus = FakeBus(namespaces=[""])
    client = serve(bus, allowed_origins=("https://console.lab",))
    connection = gateway.ws_connect(f"http://127.0.0.1:{client.port}"
                                    "/api/monitors/_/stream")
    connection.close()
    # The refusal above is by name, so the named one is admitted; asserted through the
    # policy object because ws_connect cannot set an Origin.
    app_origins = gateway.Gateway(FakeBus(),
                                  allowed_origins=("https://console.lab",)).allowed_origins
    assert "https://console.lab" in app_origins


# ================================================== NaN is not JSON


def test_a_nan_payload_lands_in_problems_instead_of_breaking_the_browser():
    """`json.loads` accepts NaN and Infinity; `JSON.parse` does not. A monitor
    publishing confidence=float('nan') emits a bare NaN, which sailed through the
    well-formedness guard and was embedded verbatim -- so every browser on the stream
    threw on the frame carrying `dropped`, the one field that says frames are being
    lost."""
    payload = json.dumps({"confidence": float("nan"), "seq": 3})
    assert "NaN" in payload                          # what json.dumps really emits

    frame_text = gateway.stream_frame("", api.VERDICT, payload, 4)
    frame = json.loads(frame_text)                   # parses, and would not have
    assert frame["payload"] is None
    assert frame["dropped"] == 4
    assert frame["problems"]
    assert "NaN" not in frame_text


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_every_non_json_constant_is_refused(token):
    frame = json.loads(gateway.stream_frame("", api.VERDICT, '{"x": %s}' % token, 0))
    assert frame["payload"] is None


# ================================================== logs are not a resource to exhaust


def test_a_client_reset_does_not_print_a_traceback(serve):
    """socketserver's default prints a full traceback per failed connection, and the
    commonest failure is a client hanging up -- which anyone can do in a loop. Hundreds
    of lines of stderr from a twenty-probe scan is a log-exhaustion primitive, and it
    buries the exceptions that matter."""
    import contextlib
    import io

    app = gateway.Gateway(FakeBus())
    server = gateway.GatewayServer(app, "127.0.0.1", 0)
    try:
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            try:
                raise ConnectionResetError("peer went away")
            except ConnectionResetError:
                server.handle_error(None, ("127.0.0.1", 5555))
        assert captured.getvalue() == ""
    finally:
        server.server_close()
