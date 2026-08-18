"""REST + WebSocket in front of the ROS graph, so a client with no DDS can watch and
drive the system.

It exists because the frontend runs where the operator is -- a laptop, another subnet, a
browser -- and DDS discovery does not cross a WAN. The dev host already cannot see the
robot's graph, which is the concrete case this package answers.

**No authentication, and this is deliberate.** Every endpoint below is open to anything
that can reach the port. The gateway binds to the server tier's network; if that network
is not trusted, the deployment terminates TLS and authenticates *in front* of this
process (a reverse proxy), the same way it would for any other unauthenticated backend.
A token check bolted on here would be worse than none, because it would be believed:
there is no session store, no rate limit, no audit trail and no CSRF defence in this
file, and `POST /api/monitors/{ns}/command` can `reset` a live mission. CORS is
`*` for the same reason -- a same-origin policy is not a security boundary when there
are no credentials to protect, and pretending otherwise only breaks the browser client.

Pass-through, not translator
----------------------------
Payloads are byte-identical on both transports. That is only possible because P0 chose
JSON in ``std_msgs/String``: this module forwards a *string* it does not have to
understand. Nothing here calls a builder from ``core.api``; the only parsing is

  * ``json.loads`` as a well-formedness guard before a payload is embedded in a WS
    frame, so one malformed message from a monitor cannot make the *envelope*
    unparseable and take the drop counter down with it; and
  * ``core.api.validate_for_topic`` on the two ingress routes, where the gateway is the
    one publishing onto the ROS graph and a malformed message would be its own fault.

Topic names are never spelled here. They come from ``core.api`` constants, and the REST
verbs for the latched topics are *derived* from ``api.LATCHED_TOPICS`` rather than
listed, so a topic added to the contract gets an endpoint without an edit to this file.

WS is the stream, REST is the sample
------------------------------------
There is deliberately no ``GET /api/monitors/{ns}/latest``. Anything that must not miss
a tick subscribes to ``WS /api/monitors/{ns}/stream``; a polling endpoint for a
per-tick payload only invites a loop that silently misses ticks between polls. The REST
routes serve latched topics only -- values that change rarely and are complete on their
own.

Backpressure is the gateway's problem
-------------------------------------
A slow WS client must not slow the ROS side. Each client gets a bounded queue that drops
*oldest* when full, and every frame carries ``dropped``: the number of frames shed for
that client since it connected. A viewer whose view is decimated is told so, because a
silent drop is indistinguishable from a monitor that stopped -- the same rule
``data_health.dropped`` follows on the observation topic.

Standalone
----------
Starts and serves with nothing else on the graph: an empty monitor list is a 200 with
``{"monitors": []}``, not an error, and ``services`` in that same response names what
the gateway cannot see (no rclpy, no clock) so an operator can tell "nothing is running"
from "the gateway is broken".

The ROS side is injected
------------------------
``MonitorBus`` is the seam. ``RclpyBus`` is the real one and imports ``rclpy`` lazily
inside its constructor; ``NullBus`` is the standalone fallback; the tests drive the whole
HTTP surface with a fake. The clock is injected the same way through ``ClockBackend``,
because P1 builds that service concurrently and this package codes against
``docs/api.md``, not against their implementation.

Client-facing API
-----------------
::

    GET  /api/health                        gateway liveness; never proxied
    GET  /api/monitors                      {"monitors": [...], "services": {...}}
    GET  /api/monitors/{seg}/manifest       verbatim /monitor/manifest payload
    GET  /api/monitors/{seg}/adapter        verbatim /monitor/adapter payload
    GET  /api/monitors/{seg}/spec_status    verbatim /monitor/spec_status payload
    WS   /api/monitors/{seg}/stream         observation + verdict frames
    POST /api/monitors/{seg}/command        -> /monitor/command
    POST /api/monitors/{seg}/spec           -> /monitor/load_spec, replies spec_status
    *    /api/clock*                        proxied to the clock, same paths

``{seg}`` is the ROS namespace with its leading slash stripped, or ``_`` for the
unnamespaced monitor (``/api/monitors/_/manifest``). A nested namespace keeps its
slashes: ``/nav/left`` is ``/api/monitors/nav/left/manifest``. Clients do not have to
work this out -- every entry of ``GET /api/monitors`` carries both ``ns`` and the
``path`` segment to use.

Run it::

    python3 -m skill_monitor.backend.gateway --port 8080
"""

from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import json
import logging
import os
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from skill_monitor.core import api

log = logging.getLogger("skill_monitor.gateway")

# --------------------------------------------------------------------------- defaults

DEFAULT_PORT = 8080

# P1 owns the clock's own port; this is only where the gateway looks for it by default.
# Both run with host networking in deploy/docker-compose.server.yml, so the gateway's
# 8080 and the clock's neighbour port are on the same loopback.
DEFAULT_CLOCK_URL = os.environ.get("SKILL_MONITOR_CLOCK_URL", "http://127.0.0.1:8081")

# A monitor silent this long is presumed dead. Same number and same meaning as the Skill
# Center's own STALE_AFTER -- an operator watching both must not see two answers.
STALE_AFTER = 5.0

# Frames buffered per WS client before the oldest is shed. Large enough that a browser
# doing a layout pass does not lose data; small enough that a client which has actually
# gone away cannot pin megabytes.
DEFAULT_QUEUE = 256

# How long POST .../spec waits for the monitor's answer on the latched spec_status.
DEFAULT_SPEC_TIMEOUT = 5.0

# A pushed skill spec is the largest thing a client sends. Anything past this is either
# a mistake or an attempt to exhaust memory, and both deserve the same 413.
MAX_BODY_BYTES = 8 * 1024 * 1024

# What a stream carries. Exactly the two per-tick topics: the latched ones are REST,
# because a client that reconnects wants their current value, not to wait for a change
# that may never come.
STREAM_TOPICS = (api.OBSERVATION, api.VERDICT)

# Endpoint name -> topic, for the routes where the client is the publisher. The names
# are docs/api.md's ("spec", not "load_spec"); the topics come from the constants.
INGRESS_TOPICS = {
    "command": api.COMMAND,
    "spec": api.LOAD_SPEC,
}

# Latched topics get a GET each, derived rather than listed: `/monitor/manifest` becomes
# `manifest`. A topic added to api.LATCHED_TOPICS gains an endpoint with no edit here.
LATCHED_ROUTES = {topic.rsplit("/", 1)[-1]: topic for topic in sorted(api.LATCHED_TOPICS)}

API_PREFIX = "/api"
MONITORS_PREFIX = "/api/monitors"
CLOCK_PREFIX = "/api/clock"

# The path segment standing in for the unnamespaced monitor, whose namespace is the
# empty string and would otherwise produce `/api/monitors//manifest`.
ROOT_SEGMENT = "_"


# ============================================================== discovery (pure)
#
# These two functions are byte-for-byte the semantics `frontend/skill_center.py`
# implements today, reimplemented here rather than imported because P7 owns that file
# and this package may not touch it. They belong in `core/` -- see the note in the
# package report; until they move, changing one means changing both.


def parse_namespaces(topic_names, key_topic: str = api.VERDICT) -> list[str]:
    """Namespaces of every discovered monitor, ``''`` for the unnamespaced one.

    A monitor *is* something publishing ``<ns>/monitor/verdict``. Discovery mirrors the
    topic contract rather than keeping a registry, so a monitor that nobody told the
    gateway about still appears, and one that dies stops appearing on its own.

    Pure, so it is testable with no ROS graph.
    """
    suffix = key_topic if key_topic.startswith("/") else "/" + key_topic
    out = set()
    for name in topic_names or ():
        if not isinstance(name, str):
            continue
        if name == suffix:
            out.add("")
        elif name.endswith(suffix):
            out.add(name[: -len(suffix)])
    return sorted(out)


def health(last_seen, now: float, stale_after: float = STALE_AFTER) -> str:
    """``'live'`` | ``'stale'`` | ``'gone'``.

    A monitor that published and then stopped is NOT the same as one that never
    published: the first is a crash, the second is a stack that was never started, and
    the operator needs to tell them apart. ``gone`` is the second -- the topic is
    advertised but no message has ever arrived.
    """
    if last_seen is None:
        return "gone"
    return "live" if (now - last_seen) <= stale_after else "stale"


def ns_to_segment(ns: str) -> str:
    """The URL path segment for a ROS namespace. ``''`` becomes ``_``."""
    trimmed = (ns or "").strip("/")
    return trimmed or ROOT_SEGMENT


def segment_to_ns(segment: str) -> str:
    """Inverse of :func:`ns_to_segment`. ``_`` and ``''`` both mean the root namespace."""
    trimmed = (segment or "").strip("/")
    if trimmed in ("", ROOT_SEGMENT):
        return ""
    return "/" + trimmed


def topic_for(ns: str, topic: str) -> str:
    """The fully qualified topic name under ``ns``. ``ns=''`` is the global namespace."""
    return f"{ns}{topic}" if ns else topic


# ============================================================== the ROS seam


class MonitorBus:
    """The ROS side, injected.

    Every method deals in the raw ``std_msgs/String`` payload *text* -- never a parsed
    dict -- because that is what makes byte-identity across transports a property of the
    code rather than a coincidence of two JSON encoders agreeing on key order.
    """

    def namespaces(self) -> list[str]:
        """Namespaces currently advertising ``<ns>/monitor/verdict``."""
        raise NotImplementedError

    def latched(self, ns: str, topic: str) -> str | None:
        """Last value seen on a latched topic, verbatim, or None if there is none."""
        raise NotImplementedError

    def last_seen(self, ns: str) -> float | None:
        """``time.time()`` of the last verdict from ``ns``, or None if never."""
        raise NotImplementedError

    def publish(self, ns: str, topic: str, payload_text: str) -> None:
        """Publish ``payload_text`` verbatim on ``<ns><topic>``."""
        raise NotImplementedError

    def subscribe(self, ns: str, topics, callback):
        """Call ``callback(topic, payload_text)`` for each message; return an unsubscribe.

        ``topic`` is the unqualified constant from ``core.api``, not the namespaced name,
        so a client of a stream does not have to strip the namespace back off. The
        callback runs on the bus's own thread and must not block -- see the queue.
        """
        raise NotImplementedError

    def status(self) -> dict:
        """What this bus can and cannot see, for the ``services`` block."""
        return {"available": False, "detail": "no bus"}


class NullBus(MonitorBus):
    """The standalone fallback: no ROS, no monitors, and it says so.

    Used when rclpy is absent or ``--no-ros`` is given. Every route still answers; the
    monitor list is empty and ``services.ros.detail`` carries the reason, which is the
    difference between "nothing is running" and "the gateway is broken".
    """

    def __init__(self, detail: str = "rclpy is not available in this process"):
        self._detail = detail

    def namespaces(self):
        return []

    def latched(self, ns, topic):
        return None

    def last_seen(self, ns):
        return None

    def publish(self, ns, topic, payload_text):
        raise BusUnavailable(self._detail)

    def subscribe(self, ns, topics, callback):
        return lambda: None

    def status(self):
        return {"available": False, "detail": self._detail}


class BusUnavailable(RuntimeError):
    """Raised by a bus that cannot publish. Surfaces as 503, never as a 500."""


class RclpyBus(MonitorBus):
    """The real bus. Imports rclpy inside ``__init__`` so this module stays importable,
    and this file's tests stay runnable, on a host that has no ROS at all.

    One node, one executor thread. Subscriptions to the per-tick topics are created per
    connected stream and torn down with it, so an idle gateway subscribes to nothing and
    a monitor's publisher sees no subscriber count it has to serve.
    """

    # How long a freshly created publisher is given to be discovered before its first
    # message goes out. DDS discovery is not instantaneous, and without this the first
    # `POST .../command` after startup publishes into a graph where nobody is subscribed
    # yet -- an operator pressing reset and watching nothing happen, exactly once.
    PUBLISHER_SETTLE_S = 0.3

    def __init__(self, node_name: str = "skill_monitor_gateway"):
        import rclpy  # noqa: PLC0415 -- deliberately lazy; see the class docstring
        from rclpy.node import Node
        from rclpy.qos import (
            DurabilityPolicy,
            HistoryPolicy,
            QoSProfile,
            ReliabilityPolicy,
        )
        from std_msgs.msg import String

        self._rclpy = rclpy
        self._String = String

        if not rclpy.ok():
            rclpy.init(args=None)
        self._node: Node = Node(node_name)

        # Depth 1, TRANSIENT_LOCAL, reliable -- the QoS docs/api.md calls "latched". A
        # subscriber with a mismatched durability silently receives nothing from a
        # TRANSIENT_LOCAL publisher, which is the failure mode this profile exists to
        # avoid.
        self._latched_qos = QoSProfile(
            depth=1,
            history=HistoryPolicy.KEEP_LAST,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self._lock = threading.Lock()
        self._latched: dict[tuple[str, str], str] = {}
        self._last_seen: dict[str, float] = {}
        self._publishers: dict[str, object] = {}
        self._latched_subs: dict[str, list] = {}
        self._verdict_subs: dict[str, object] = {}
        self._listeners: dict[str, list] = {}

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, name="gateway-ros", daemon=True)
        self._thread.start()

    # -- lifecycle ---------------------------------------------------------

    def _spin(self):
        while not self._stop.is_set():
            try:
                self._rclpy.spin_once(self._node, timeout_sec=0.1)
            except Exception:  # pragma: no cover -- executor teardown races
                if self._stop.is_set():
                    return
                log.exception("gateway ROS executor")
                time.sleep(0.1)

    def shutdown(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            self._node.destroy_node()
        except Exception:  # pragma: no cover
            pass

    # -- discovery ---------------------------------------------------------

    def namespaces(self):
        names = [name for name, _types in self._node.get_topic_names_and_types()]
        found = parse_namespaces(names)
        for ns in found:
            self._ensure_tracking(ns)
        return found

    def _ensure_tracking(self, ns: str):
        """Subscribe to a newly discovered monitor's verdict and latched topics.

        Health needs a verdict subscription whether or not anyone is streaming, or a
        monitor would read ``gone`` until the first viewer connected. The latched topics
        need one so a REST GET answers immediately rather than waiting out a round trip.
        """
        with self._lock:
            if ns in self._verdict_subs:
                return
            self._verdict_subs[ns] = self._node.create_subscription(
                self._String, topic_for(ns, api.VERDICT),
                lambda msg, ns=ns: self._on_verdict(ns, msg.data), 10,
            )
            self._latched_subs[ns] = [
                self._node.create_subscription(
                    self._String, topic_for(ns, topic),
                    lambda msg, ns=ns, topic=topic: self._on_latched(ns, topic, msg.data),
                    self._latched_qos,
                )
                for topic in sorted(api.LATCHED_TOPICS)
            ]

    def _on_verdict(self, ns: str, text: str):
        with self._lock:
            self._last_seen[ns] = time.time()
            listeners = list(self._listeners.get(ns, ()))
        for topics, callback in listeners:
            if api.VERDICT in topics:
                callback(api.VERDICT, text)

    def _on_latched(self, ns: str, topic: str, text: str):
        with self._lock:
            self._latched[(ns, topic)] = text
            listeners = list(self._listeners.get(ns, ()))
        for topics, callback in listeners:
            if topic in topics:
                callback(topic, text)

    def latched(self, ns, topic):
        with self._lock:
            return self._latched.get((ns, topic))

    def last_seen(self, ns):
        with self._lock:
            return self._last_seen.get(ns)

    # -- publish -----------------------------------------------------------

    def publish(self, ns, topic, payload_text):
        full = topic_for(ns, topic)
        created = False
        with self._lock:
            publisher = self._publishers.get(full)
            if publisher is None:
                qos = self._latched_qos if topic in api.LATCHED_TOPICS else 10
                publisher = self._node.create_publisher(self._String, full, qos)
                self._publishers[full] = publisher
                created = True
        if created:
            time.sleep(self.PUBLISHER_SETTLE_S)  # see PUBLISHER_SETTLE_S
        message = self._String()
        message.data = payload_text
        publisher.publish(message)

    # -- subscribe ---------------------------------------------------------

    def subscribe(self, ns, topics, callback):
        self._ensure_tracking(ns)
        wanted = tuple(topics)
        entry = (wanted, callback)

        extra = []
        for topic in wanted:
            if topic in (api.VERDICT, *api.LATCHED_TOPICS):
                continue  # already tracked for health / REST
            extra.append(
                self._node.create_subscription(
                    self._String, topic_for(ns, topic),
                    lambda msg, topic=topic: callback(topic, msg.data), 10,
                )
            )
        with self._lock:
            self._listeners.setdefault(ns, []).append(entry)

        def unsubscribe():
            with self._lock:
                listeners = self._listeners.get(ns, [])
                if entry in listeners:
                    listeners.remove(entry)
            for sub in extra:
                try:
                    self._node.destroy_subscription(sub)
                except Exception:  # pragma: no cover
                    pass

        return unsubscribe

    def status(self):
        return {"available": True, "detail": f"node {self._node.get_name()}"}


# ============================================================== the clock seam


class ClockBackend:
    """The clock's own HTTP API, injected.

    P1 builds that service concurrently, so this package codes against
    ``docs/api.md § Clock API`` and never against their implementation. The proxy does
    not enumerate the clock's endpoints -- it forwards whatever path arrives under
    ``/api/clock`` -- which is how "the same paths the clock serves" stays true when P1
    adds one.
    """

    def request(self, method: str, path: str, body: bytes | None):
        """Return ``(status, content_type, body_bytes)``. Raise ClockUnreachable."""
        raise NotImplementedError

    def stream(self):
        """Yield raw frame texts from ``WS /api/clock/stream``. Raise ClockUnreachable."""
        raise NotImplementedError

    def status(self) -> dict:
        return {"reachable": False, "detail": "no clock backend"}


class ClockUnreachable(RuntimeError):
    """The clock is not answering. Surfaces as 503 with the reason, never as a 500."""


class HttpClockBackend(ClockBackend):
    """Forwards to a real clock over HTTP, and the stream over a WebSocket.

    Reachability is probed lazily and cached, because ``GET /api/monitors`` reports it
    and a 1-second connect timeout on every list request would make the frontend feel
    broken whenever the clock is merely absent -- which, per the architecture, is a
    normal state the gateway must serve through.
    """

    PROBE_CACHE_S = 2.0

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self._probe_lock = threading.Lock()
        self._probe: tuple[float, dict] | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def request(self, method, path, body):
        request = urllib.request.Request(
            self._url(path), data=body, method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return (
                    response.status,
                    response.headers.get("Content-Type", "application/json"),
                    response.read(),
                )
        except urllib.error.HTTPError as exc:
            # The clock's own 4xx is the clock's answer, not a proxy failure: forward it
            # verbatim so a client sees the reason the clock refused, which for
            # `POST /api/clock/rate` while a monitor is armed is the whole point.
            return (exc.code, exc.headers.get("Content-Type", "application/json"), exc.read())
        except (urllib.error.URLError, OSError) as exc:
            raise ClockUnreachable(f"{self.base_url}: {exc}") from exc

    def stream(self):
        url = self._url("/api/clock/stream")
        try:
            connection = ws_connect(url, timeout=self.timeout)
        except OSError as exc:
            raise ClockUnreachable(f"{url}: {exc}") from exc
        try:
            while True:
                text = connection.recv()
                if text is None:
                    return
                yield text
        finally:
            connection.close()

    def status(self):
        with self._probe_lock:
            cached = self._probe
            if cached is not None and (time.monotonic() - cached[0]) < self.PROBE_CACHE_S:
                return cached[1]
        try:
            status, _ctype, _body = self.request("GET", "/api/clock/health", None)
            result = {"reachable": 200 <= status < 400, "url": self.base_url,
                      "detail": f"HTTP {status}"}
        except ClockUnreachable as exc:
            result = {"reachable": False, "url": self.base_url, "detail": str(exc)}
        with self._probe_lock:
            self._probe = (time.monotonic(), result)
        return result


class NullClockBackend(ClockBackend):
    """No clock configured. Every ``/api/clock*`` route answers 503 with the reason."""

    def __init__(self, detail: str = "no clock URL configured"):
        self._detail = detail

    def request(self, method, path, body):
        raise ClockUnreachable(self._detail)

    def stream(self):
        raise ClockUnreachable(self._detail)

    def status(self):
        return {"reachable": False, "detail": self._detail}


# ============================================================== WebSocket wire
#
# RFC 6455, the subset this gateway needs, on the stdlib. A dependency would buy async
# plumbing and permessage-deflate, neither of which a 1-5 Hz verdict stream wants, and
# would put a pip install between `python3 -m pytest` and a green suite on a host that
# has no ROS -- exactly the property core/ exists to preserve.

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


def ws_accept_key(client_key: str) -> str:
    """The ``Sec-WebSocket-Accept`` value for a client's ``Sec-WebSocket-Key``."""
    digest = hashlib.sha1((client_key + WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def ws_encode(payload: bytes, opcode: int = OP_TEXT, *, mask: bool = False) -> bytes:
    """One unfragmented frame. ``mask`` is required of clients, forbidden of servers."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header += struct.pack("!H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack("!Q", length)
    if not mask:
        return bytes(header) + payload
    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + key + masked


def _read_exactly(rfile, count: int) -> bytes:
    data = rfile.read(count)
    if data is None or len(data) < count:
        raise ConnectionError("websocket peer closed mid-frame")
    return data


def ws_read(rfile):
    """Read one *message*, reassembling continuation frames.

    Returns ``(opcode, payload_bytes)``; the opcode is the first frame's, so a
    fragmented text message still reads as text. Raises ConnectionError at EOF, which
    the callers treat as a disconnect rather than an error worth logging.
    """
    opcode = None
    buffer = bytearray()
    while True:
        first, second = _read_exactly(rfile, 2)
        fin = bool(first & 0x80)
        this_opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", _read_exactly(rfile, 2))
        elif length == 127:
            (length,) = struct.unpack("!Q", _read_exactly(rfile, 8))
        if length > MAX_BODY_BYTES:
            raise ConnectionError(f"websocket frame of {length} bytes refused")
        key = _read_exactly(rfile, 4) if masked else b""
        payload = _read_exactly(rfile, length) if length else b""
        if masked:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))

        if this_opcode in (OP_CLOSE, OP_PING, OP_PONG):
            # A control frame may be interleaved between fragments and is never itself
            # fragmented, so it is returned immediately without disturbing `buffer`.
            return this_opcode, payload
        if opcode is None:
            opcode = this_opcode if this_opcode != OP_CONT else OP_TEXT
        buffer += payload
        if fin:
            return opcode, bytes(buffer)


class WSConnection:
    """A client-side WebSocket, used to proxy ``/api/clock/stream`` -- and, in the tests,
    to drive this gateway's own streams."""

    def __init__(self, sock: socket.socket, rfile=None):
        self._sock = sock
        # The handshake reader is handed over rather than replaced: a BufferedReader
        # reads ahead, so a server that sends its first frame immediately after the 101
        # has already put those bytes in this buffer. Opening a second makefile here
        # would silently drop them -- which looks exactly like a stream that never sent
        # anything.
        self._rfile = rfile if rfile is not None else sock.makefile("rb")
        self._lock = threading.Lock()
        self._closed = False

    def send(self, text: str):
        with self._lock:
            self._sock.sendall(ws_encode(text.encode("utf-8"), OP_TEXT, mask=True))

    def recv(self):
        """The next text message, or None once the peer closes."""
        while True:
            try:
                opcode, payload = ws_read(self._rfile)
            except (ConnectionError, OSError):
                return None
            if opcode == OP_CLOSE:
                return None
            if opcode == OP_PING:
                with self._lock:
                    self._sock.sendall(ws_encode(payload, OP_PONG, mask=True))
                continue
            if opcode == OP_PONG:
                continue
            return payload.decode("utf-8", "replace")

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                self._sock.sendall(ws_encode(b"", OP_CLOSE, mask=True))
        except OSError:
            pass
        try:
            self._rfile.close()
        finally:
            self._sock.close()


def ws_connect(url: str, timeout: float = 5.0) -> WSConnection:
    """Open a client WebSocket to ``url`` (http/ws scheme, no TLS -- see the docstring
    on authentication: TLS terminates in front of this tier, not inside it)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("wss", "https"):
        raise ClockUnreachable("TLS is terminated in front of this tier, not by it")
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 80
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.sendall(
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n".encode("ascii")
    )
    rfile = sock.makefile("rb")
    status_line = rfile.readline().decode("latin-1").strip()
    headers = {}
    while True:
        line = rfile.readline().decode("latin-1").strip()
        if not line:
            break
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    if "101" not in status_line:
        rfile.close()
        sock.close()
        raise ClockUnreachable(f"websocket upgrade refused: {status_line}")
    if headers.get("sec-websocket-accept") != ws_accept_key(key):
        rfile.close()
        sock.close()
        raise ClockUnreachable("websocket accept key mismatch")
    sock.settimeout(None)
    return WSConnection(sock, rfile)


# ============================================================== backpressure


class ClientStream:
    """A bounded, drop-oldest queue for one WS client.

    Offering never blocks and never raises, because the caller is a ROS subscription
    callback and the async rules in docs/api.md forbid a blocking call there. When the
    queue is full the *oldest* frame goes -- a viewer wants the current verdict, not the
    one from thirty seconds ago -- and the count of everything shed since this client
    connected rides out on the next frame.
    """

    def __init__(self, maxlen: int = DEFAULT_QUEUE):
        self._items: collections.deque = collections.deque()
        self._maxlen = max(1, int(maxlen))
        self._dropped = 0
        self._cv = threading.Condition()
        self._closed = False

    @property
    def dropped(self) -> int:
        with self._cv:
            return self._dropped

    def offer(self, item) -> None:
        with self._cv:
            if self._closed:
                return
            if len(self._items) >= self._maxlen:
                self._items.popleft()
                self._dropped += 1
            self._items.append(item)
            self._cv.notify()

    def take(self, timeout: float | None = None):
        """``(item, dropped_so_far)``, or None on timeout or once closed."""
        with self._cv:
            if not self._items and not self._closed:
                self._cv.wait(timeout)
            if self._closed or not self._items:
                return None
            return self._items.popleft(), self._dropped

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._items.clear()
            self._cv.notify_all()


# ---------------------------------------------------------------- frame assembly

_PAYLOAD_SEPARATOR = ', "payload": '


def stream_frame(ns: str, topic: str, payload_text: str, dropped: int) -> str:
    """One WS frame, with the topic payload embedded **verbatim**.

    Built by concatenation rather than ``json.dumps({... "payload": parsed})`` on
    purpose: re-encoding would re-order keys and reformat floats, and byte-identity
    across the two transports would then depend on two JSON encoders agreeing. Here the
    payload's bytes are the bytes that came off the topic, and
    :func:`frame_payload_text` recovers them exactly.

    A payload that is not well-formed JSON is replaced with ``null`` and reported in
    ``problems``, because embedding it would make the *envelope* unparseable and take
    ``dropped`` down with it -- the client would lose the one field telling it that it
    is losing frames.
    """
    try:
        json.loads(payload_text)
    except (ValueError, TypeError):
        return json.dumps({
            "ns": ns, "topic": topic, "dropped": dropped, "payload": None,
            "problems": [f"{topic}: payload is not well-formed JSON"],
        })
    head = json.dumps({"ns": ns, "topic": topic, "dropped": dropped})
    return head[:-1] + _PAYLOAD_SEPARATOR + payload_text + "}"


def frame_payload_text(frame_text: str) -> str | None:
    """The verbatim payload substring of a frame built by :func:`stream_frame`.

    The inverse the byte-identity test asserts against, and useful to a client that
    wants to persist exactly what the topic carried.
    """
    index = frame_text.find(_PAYLOAD_SEPARATOR)
    if index < 0:
        return None
    return frame_text[index + len(_PAYLOAD_SEPARATOR): -1]


# ============================================================== the application


class Gateway:
    """Routing and policy. Knows nothing about sockets -- :class:`GatewayServer` owns
    those -- so every route below is callable from a test with a fake bus."""

    def __init__(
        self,
        bus: MonitorBus | None = None,
        clock: ClockBackend | None = None,
        *,
        stale_after: float = STALE_AFTER,
        queue_size: int = DEFAULT_QUEUE,
        spec_timeout: float = DEFAULT_SPEC_TIMEOUT,
    ):
        self.bus = bus or NullBus()
        self.clock = clock or NullClockBackend()
        self.stale_after = stale_after
        self.queue_size = queue_size
        self.spec_timeout = spec_timeout
        self.started_at = time.time()

    # -- GET /api/health ---------------------------------------------------

    def gateway_health(self) -> dict:
        """The gateway's own liveness. Never proxied -- ``/api/clock/health`` is the
        clock's, and a health endpoint that answers for a *different* process is how a
        dead service reports green."""
        return {
            "ok": True,
            "uptime_s": round(time.time() - self.started_at, 3),
            "monitors": len(self.bus.namespaces()),
            "auth": "none",
            "services": self.services(),
        }

    def services(self) -> dict:
        """What the gateway can and cannot see. Present even when everything is fine, so
        a client never has to infer absence from a missing key."""
        return {"ros": self.bus.status(), "clock": self.clock.status()}

    # -- GET /api/monitors -------------------------------------------------

    def list_monitors(self) -> dict:
        """Discovered namespaces plus health. An empty graph is a 200 with an empty
        list -- "no monitors" is an answer, not a failure."""
        now = time.time()
        monitors = []
        for ns in self.bus.namespaces():
            last_seen = self.bus.last_seen(ns)
            manifest = self.bus.latched(ns, api.MANIFEST)
            monitors.append({
                "ns": ns,
                # The URL segment to use, so a client never has to work out the `_`
                # convention or how a nested namespace is spelled.
                "path": ns_to_segment(ns),
                "health": health(last_seen, now, self.stale_after),
                "last_seen": last_seen,
                "age_s": None if last_seen is None else round(now - last_seen, 3),
                "skill_name": _skill_name(manifest),
            })
        return {"monitors": monitors, "services": self.services()}

    # -- GET /api/monitors/{ns}/{latched} ----------------------------------

    def latched(self, ns: str, verb: str):
        """``(status, body_text)`` for a latched topic, forwarded verbatim.

        404 when the monitor has never published it: the value is genuinely absent, and
        an empty object would be indistinguishable from a manifest with no fields.
        """
        topic = LATCHED_ROUTES.get(verb)
        if topic is None:
            return 404, _error(f"no such resource {verb!r}")
        text = self.bus.latched(ns, topic)
        if text is None:
            return 404, _error(
                f"no {verb} latched for namespace {ns or '/'!r}",
                topic=topic, ns=ns,
            )
        return 200, text

    # -- POST /api/monitors/{ns}/command -----------------------------------

    def post_command(self, ns: str, body: bytes):
        """Validate against the contract, then publish verbatim.

        This is the one direction where the gateway is the publisher, so a malformed
        message on the graph would be its own fault -- hence
        ``api.validate_for_topic``, whose problem list goes straight back to the client
        rather than being logged and swallowed.
        """
        return self._publish_validated(ns, INGRESS_TOPICS["command"], body)

    def _publish_validated(self, ns: str, topic: str, body: bytes):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return 400, _error(f"body is not valid JSON: {exc}")
        problems = api.validate_for_topic(topic, payload)
        if problems:
            return 400, json.dumps({"ok": False, "topic": topic, "problems": problems})
        # Re-encoded rather than forwarded byte-for-byte: this payload did not come off
        # a topic, so there is nothing to be identical *to*, and a canonical encoding is
        # what keeps a client's whitespace out of the recorded stream.
        text = json.dumps(payload)
        try:
            self.bus.publish(ns, topic, text)
        except BusUnavailable as exc:
            return 503, _error(str(exc), topic=topic, ns=ns)
        return 202, json.dumps({"ok": True, "topic": topic, "published": payload})

    # -- POST /api/monitors/{ns}/spec --------------------------------------

    def post_spec(self, ns: str, body: bytes):
        """Push a spec and answer with the monitor's own ``spec_status``, verbatim.

        The wait is for a status *different* from the one latched before the push. A
        latched topic replays its current value to a new subscriber, so "the next
        message" would otherwise be the previous answer; comparing the text is the only
        discriminator available without inventing a correlation id the contract does not
        have. The cost is honest and documented: pushing a spec that fails in exactly
        the same way twice times out into a 504 whose body still carries the status.
        """
        topic = INGRESS_TOPICS["spec"]
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return 400, _error(f"body is not valid JSON: {exc}")

        # A client may post the load_spec payload, or the bare spec document. Both are
        # unambiguous: the wrapper has a `spec` key and a skill document does not.
        if isinstance(payload, dict) and "spec" not in payload:
            payload = api.build_load_spec(spec=payload)
        problems = api.validate_for_topic(topic, payload)
        if problems:
            return 400, json.dumps({"ok": False, "topic": topic, "problems": problems})

        before = self.bus.latched(ns, api.SPEC_STATUS)
        answered = threading.Event()
        box: dict[str, str] = {}

        def on_status(_topic, text):
            if text != before and "text" not in box:
                box["text"] = text
                answered.set()

        unsubscribe = self.bus.subscribe(ns, (api.SPEC_STATUS,), on_status)
        try:
            self.bus.publish(ns, topic, json.dumps(payload))
        except BusUnavailable as exc:
            unsubscribe()
            return 503, _error(str(exc), topic=topic, ns=ns)
        try:
            answered.wait(self.spec_timeout)
        finally:
            unsubscribe()

        text = box.get("text")
        if text is None:
            return 504, _error(
                f"no {api.SPEC_STATUS} from namespace {ns or '/'!r} "
                f"within {self.spec_timeout}s",
                topic=api.SPEC_STATUS, ns=ns, last_known=before,
            )
        # Verbatim: this text came off a topic and the frontend compares it against the
        # same payload arriving over ROS.
        status = 200 if _status_ok(text) else 400
        return status, text

    # -- WS /api/monitors/{ns}/stream --------------------------------------

    def open_stream(self, ns: str):
        """``(ClientStream, unsubscribe)``. The subscription callback only offers to the
        queue, so nothing on the ROS thread can be slowed by a client."""
        stream = ClientStream(self.queue_size)

        def on_message(topic, text):
            stream.offer((topic, text))

        unsubscribe = self.bus.subscribe(ns, STREAM_TOPICS, on_message)
        return stream, unsubscribe

    # -- /api/clock* -------------------------------------------------------

    def proxy_clock(self, method: str, path: str, body: bytes | None):
        """Forward under the clock's *own* paths, unexamined.

        The gateway does not enumerate the clock's endpoints. Whatever arrives under
        ``/api/clock`` goes on unchanged, so "the same paths the clock serves" holds for
        endpoints P1 has not written yet and this file never has to learn about them.
        """
        try:
            return self.clock.request(method, path, body)
        except ClockUnreachable as exc:
            return 503, "application/json", _error(str(exc), service="clock").encode("utf-8")


def _skill_name(manifest_text):
    """The skill name off a latched manifest, or None. Never raises: a monitor pushing a
    malformed manifest must still appear in the list with its health."""
    if not manifest_text:
        return None
    try:
        parsed = json.loads(manifest_text)
    except (ValueError, TypeError):
        return None
    return parsed.get("skill_name") if isinstance(parsed, dict) else None


def _status_ok(text: str) -> bool:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return False
    return bool(isinstance(parsed, dict) and parsed.get("ok"))


def _error(message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": message, **extra})


# ============================================================== HTTP transport


class _Handler(BaseHTTPRequestHandler):
    """One request, or one hijacked socket for a WebSocket. ``self.server.gateway`` is
    the application; nothing here decides policy."""

    protocol_version = "HTTP/1.1"
    server_version = "skill-monitor-gateway/1"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    @property
    def gateway(self) -> Gateway:
        return self.server.gateway  # type: ignore[attr-defined]

    def _cors(self):
        # `*` with no credentials, matching the module docstring: there is no session to
        # protect, and a stricter policy here would only break a browser client while
        # protecting nothing.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, status: int, body, content_type: str = "application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, _error("Content-Length is not an integer"))
            return None
        if length > MAX_BODY_BYTES:
            self._send(413, _error(f"body larger than {MAX_BODY_BYTES} bytes"))
            return None
        return self.rfile.read(length) if length else b""

    def _is_upgrade(self) -> bool:
        return "websocket" in (self.headers.get("Upgrade") or "").lower()

    # -- routing -----------------------------------------------------------

    def do_OPTIONS(self):  # noqa: N802 -- BaseHTTPRequestHandler's naming
        self._send(204, b"", "text/plain")

    def do_GET(self):  # noqa: N802
        self._route("GET")

    def do_POST(self):  # noqa: N802
        self._route("POST")

    def do_PUT(self):  # noqa: N802
        self._route("PUT")

    def do_DELETE(self):  # noqa: N802
        self._route("DELETE")

    def _route(self, method: str):
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"

        if path == f"{API_PREFIX}/health" and method == "GET":
            self._send(200, json.dumps(self.gateway.gateway_health()))
            return

        if path == CLOCK_PREFIX or path.startswith(CLOCK_PREFIX + "/"):
            self._clock(method, parts)
            return

        if path == MONITORS_PREFIX and method == "GET":
            self._send(200, json.dumps(self.gateway.list_monitors()))
            return

        if path.startswith(MONITORS_PREFIX + "/"):
            self._monitor(method, path)
            return

        self._send(404, _error(f"no such resource {parts.path!r}"))

    def _monitor(self, method: str, path: str):
        rest = path[len(MONITORS_PREFIX) + 1:]
        segment, _, verb = rest.rpartition("/")
        if not verb:
            self._send(404, _error(f"no such resource {path!r}"))
            return
        if not segment:
            # /api/monitors/<seg> with no verb: the namespace alone is not a resource,
            # and answering it would be a second, undocumented way to ask for a monitor.
            self._send(404, _error(
                "a namespace alone is not a resource; ask for "
                f"{'|'.join(sorted(LATCHED_ROUTES))}, stream, command or spec"
            ))
            return
        ns = segment_to_ns(segment)

        if verb == "stream":
            if method != "GET":
                self._send(405, _error("stream is a websocket; GET with an Upgrade"))
            elif not self._is_upgrade():
                # Explicitly not a fallback to JSON polling: the stream is the only
                # thing that does not miss ticks, and a client that silently got a
                # snapshot instead would look like it worked.
                self._send(426, _error(
                    "WS /api/monitors/{ns}/stream requires a websocket upgrade; "
                    "there is no polling equivalent, by design"
                ))
            else:
                self._stream(ns)
            return

        if method == "GET":
            status, body = self.gateway.latched(ns, verb)
            self._send(status, body)
            return

        if method == "POST":
            body = self._read_body()
            if body is None:
                return
            if verb == "command":
                status, text = self.gateway.post_command(ns, body)
            elif verb == "spec":
                status, text = self.gateway.post_spec(ns, body)
            else:
                self._send(404, _error(f"no such resource {verb!r}"))
                return
            self._send(status, text)
            return

        self._send(405, _error(f"{method} is not allowed on {verb!r}"))

    # -- clock proxy -------------------------------------------------------

    def _clock(self, method: str, parts):
        path = parts.path
        if parts.query:
            path = f"{path}?{parts.query}"
        if self._is_upgrade():
            self._clock_stream(path)
            return
        body = self._read_body() if method in ("POST", "PUT") else None
        if body is None and method in ("POST", "PUT"):
            return
        status, content_type, payload = self.gateway.proxy_clock(method, path, body)
        self._send(status, payload, content_type or "application/json")

    def _clock_stream(self, path: str):
        if not self._handshake():
            return
        try:
            frames = self.gateway.clock.stream()
        except ClockUnreachable as exc:
            self._ws_send(_error(str(exc), service="clock"))
            self._ws_close()
            return
        try:
            # Forwarded verbatim: docs/api.md says the clock's stream frame is the
            # identical payload to /monitor/tick, and wrapping it here would make the
            # proxied path differ from the direct one.
            for text in frames:
                self._ws_send(text)
        except (OSError, ConnectionError, ClockUnreachable):
            pass
        finally:
            self._ws_close()

    # -- websocket ---------------------------------------------------------

    def _handshake(self) -> bool:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send(400, _error("missing Sec-WebSocket-Key"))
            return False
        self.close_connection = True  # the socket is ours now, not the server loop's
        self.wfile.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + ws_accept_key(key).encode("ascii") + b"\r\n"
            b"Access-Control-Allow-Origin: *\r\n\r\n"
        )
        self.wfile.flush()
        return True

    def _ws_send(self, text: str):
        self.wfile.write(ws_encode(text.encode("utf-8"), OP_TEXT))
        self.wfile.flush()

    def _ws_close(self):
        try:
            self.wfile.write(ws_encode(b"", OP_CLOSE))
            self.wfile.flush()
        except OSError:
            pass

    def _stream(self, ns: str):
        if not self._handshake():
            return
        stream, unsubscribe = self.gateway.open_stream(ns)
        stop = threading.Event()

        def reader():
            """Drain the client's own frames so a browser's ping does not fill the
            receive buffer, and notice a close promptly rather than on the next write."""
            while not stop.is_set():
                try:
                    opcode, payload = ws_read(self.rfile)
                except (ConnectionError, OSError, ValueError):
                    break
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    try:
                        self.wfile.write(ws_encode(payload, OP_PONG))
                        self.wfile.flush()
                    except OSError:
                        break
            stop.set()
            stream.close()

        threading.Thread(target=reader, name="gateway-ws-reader", daemon=True).start()
        try:
            while not stop.is_set():
                item = stream.take(timeout=0.5)
                if item is None:
                    continue
                (topic, text), dropped = item
                self._ws_send(stream_frame(ns, topic, text, dropped))
        except (OSError, ConnectionError):
            pass
        finally:
            stop.set()
            unsubscribe()
            stream.close()
            self._ws_close()


class GatewayServer(ThreadingHTTPServer):
    """A threading HTTP server carrying a :class:`Gateway`.

    Threads rather than asyncio: a WebSocket here is a long-lived socket doing almost
    nothing, the ROS side is already threaded, and one thread per viewer of a lab
    console is not the axis this system scales on.
    """

    daemon_threads = True
    allow_reuse_address = True
    # socketserver joins every handler thread in server_close() by default, and a
    # websocket handler is by construction a thread that is blocked on a socket which
    # may never produce another byte. Shutdown would then hang on the one connection
    # nobody closed. The threads are daemons, so there is nothing to join.
    block_on_close = False

    def __init__(self, gateway: Gateway, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        super().__init__((host, port), _Handler)
        self.gateway = gateway

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self, poll_interval: float = 0.05) -> threading.Thread:
        """Serve on a background thread. The poll interval is also how long ``stop``
        takes, which is why it is well under socketserver's 0.5s default."""
        thread = threading.Thread(
            target=self.serve_forever, args=(poll_interval,),
            name="gateway-http", daemon=True,
        )
        thread.start()
        return thread

    def stop(self):
        self.shutdown()
        self.server_close()


# ============================================================== entry point


def build_bus(use_ros: bool = True) -> MonitorBus:
    """The real bus if ROS is present, otherwise the one that says why it is not.

    Falling back rather than exiting is the standalone requirement: an operator whose
    ROS install is broken should get a gateway that *tells them so* over HTTP, not a
    container that restart-loops with the reason only in a log.
    """
    if not use_ros:
        return NullBus("--no-ros: the ROS side is disabled")
    try:
        return RclpyBus()
    except Exception as exc:  # noqa: BLE001 -- any import or init failure is the same answer
        log.warning("no ROS side: %s", exc)
        return NullBus(f"rclpy unavailable: {exc}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="skill_monitor.backend.gateway",
        description="REST + WebSocket in front of the ROS graph. No authentication: "
                    "bind it to a trusted network or put a TLS-terminating proxy in front.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--clock-url", default=DEFAULT_CLOCK_URL,
                        help="base URL of the clock's own API; '' disables the proxy")
    parser.add_argument("--stale-after", type=float, default=STALE_AFTER,
                        help="seconds of silence after which a monitor reads 'stale'")
    parser.add_argument("--queue", type=int, default=DEFAULT_QUEUE,
                        help="frames buffered per websocket client before dropping oldest")
    parser.add_argument("--spec-timeout", type=float, default=DEFAULT_SPEC_TIMEOUT,
                        help="seconds POST .../spec waits for the monitor's spec_status")
    parser.add_argument("--no-ros", action="store_true",
                        help="serve with no ROS side at all (an empty monitor list)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bus = build_bus(not args.no_ros)
    clock = HttpClockBackend(args.clock_url) if args.clock_url else NullClockBackend()
    gateway = Gateway(bus, clock, stale_after=args.stale_after,
                      queue_size=args.queue, spec_timeout=args.spec_timeout)
    server = GatewayServer(gateway, args.host, args.port)

    log.info("gateway on http://%s:%d  (NO AUTHENTICATION -- trusted network only)",
             args.host, server.port)
    log.info("clock proxy: %s", args.clock_url or "disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
        shutdown = getattr(bus, "shutdown", None)
        if callable(shutdown):
            shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
