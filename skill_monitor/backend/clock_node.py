#!/usr/bin/env python3
"""The clock service: one ROS publisher, one HTTP server, no decisions.

    python3 -m skill_monitor.backend.clock_node --tick-hz 1.0 --mode wall
    python3 -m skill_monitor.backend.clock_node --rate 1.0 --source replay --paused

Every rule this process enforces lives in `skill_monitor/core/clock.py`, which is pure
and tested. What is left here is transport: publish the pulse on the topic, serve the
same payload over HTTP and WebSocket, and answer `/api/clock*` by handing the request to
`ClockService.handle`. The split is deliberate -- "a rate change is refused while a
monitor is armed" must be a tested rule and not a branch inside a request handler on a
host with no ROS installed.

`rclpy` and `std_msgs` are imported inside `main()`, not at module scope, so this file
stays importable (and its WebSocket framing testable) on a laptop with no ROS -- the same
property `core/` has, for the same reason.

**Standalone**: this service pulses and answers queries with nothing else on the graph.
That is its whole job, so it has no degraded mode.

**No authentication, and this is deliberate.** Every endpoint is open to anything that
can reach the port, and the write endpoints are not read-only conveniences: `POST
/api/clock/mode {"paused": true}` stops the tick for every service on the tier, and on
the robot tier that is the clock the safety monitor advances on. A token check bolted on
here would be worse than none, because it would be believed -- there is no session
store, no rate limit, no audit trail and no CSRF defence in this file. If the network is
not trusted, terminate TLS and authenticate *in front* of this process (a reverse proxy,
or the gateway's own front door), the same way P6 says for the gateway.

What this file does instead is refuse to make the exposure accidental: **the default
bind is `127.0.0.1`**, so a clock is reachable by the containers sharing its network
namespace -- which under `network_mode: host` is the whole tier's stack, including the
gateway that proxies `/api/clock*` -- and by nothing else. Publishing it to a network is
`--host 0.0.0.0`, an act someone has to perform on purpose and can be grepped for in a
compose file. CORS stays `*`: a same-origin policy is not a security boundary when there
are no credentials to protect, and pretending otherwise only breaks the browser client.

A loopback bind is necessary and **not sufficient**, so the `Host:` header is checked
against an allowlist before anything routes. A DNS-rebinding page re-resolves its own
hostname to 127.0.0.1 and is then same-origin with this service -- no preflight, any
method, any header -- and CORS is irrelevant to it. `Host` is the one value the page
cannot choose. See `LOOPBACK_HOSTS`.

The HTTP surface is stdlib `http.server` plus ~30 lines of RFC 6455 framing rather than a
web framework: the clock must build in a bare `ros:humble` image with no pip install, and
one send-only WebSocket is not worth a dependency in every tier's image.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from skill_monitor.core import api
from skill_monitor.core.clock import (
    MAX_TICK_HZ, ArmedTracker, ClockService, TickEngine, valid_tick_hz,
)

#: Not 8080 -- that is the gateway (P6), and both tiers run with host networking.
DEFAULT_PORT = 8081

#: Loopback. Exposing the clock has to be a deliberate `--host 0.0.0.0` -- see the
#: module docstring for why an unauthenticated `pause` is worth that friction.
DEFAULT_HOST = "127.0.0.1"

#: `Host:` values a loopback-bound clock answers to.
#:
#: Binding 127.0.0.1 stops a *remote* attacker reaching the port. It does nothing about
#: a browser on the operator's own machine: a DNS-rebinding page re-resolves its own
#: hostname to 127.0.0.1, at which point the request is **same-origin** with this
#: service -- no preflight, any method, any header -- and `POST /api/clock/mode
#: {"paused": true}` stops the tick for every service on the tier. The `Host` header is
#: the one thing the page cannot forge, because the browser sets it from the name it
#: dialled, so an allowlist checked before routing is the standard mitigation.
#:
#: This is the clock's ONLY browser defence: unlike the gateway there is no
#: custom-header gate here to fall back on. The gateway (P6, PR #5) is fixing its own
#: copy of this in parallel -- separate image, separate lifetime, deliberately not
#: shared code.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

#: The largest request body this service will read. Every payload it accepts is a few
#: dozen bytes (`{"tick_hz": 5.0}`), so this is pure denial-of-service ceiling rather
#: than a real limit; without it a declared `Content-Length` is an allocation request
#: from anyone who can open the port.
#:
#: The gateway (P6) *will* carry the other copy of this shape -- `MAX_BODY_BYTES` and
#: `_read_body` in `skill_monitor/backend/gateway.py`, whose ceiling is 8 MiB because it
#: accepts pushed skill specs. That file is on PR #5 and is NOT on this branch yet; when
#: it merges the two have to stay in step, and this comment is the only link between
#: them. Two call sites in two processes with two ceilings is not a shared helper.
MAX_BODY_BYTES = 64 * 1024

#: How much finer than the tick period the poll timer runs.
#:
#: The pulse count does not depend on this -- that is the engine's invariant -- so this
#: number is chosen for CPU cost alone, and it is spent on a Jetson beside the
#: perception stack. Latency is therefore *proportional*: a boundary is noticed within
#: Delta/20, i.e. 5% of a period, at every rate. A 0.1 Hz clock noticing a boundary
#: 0.5 s late is exactly as prompt, in the only units the tick has, as a 1 Hz clock
#: noticing one 50 ms late.
#:
#: The previous absolute 20 ms ceiling made the divisor dead at every realistic rate: it
#: won for any tick_hz below 2.5, so the shipped 1 Hz clock woke 50 times a second to
#: discover that nothing had happened 49 of them.
_POLL_DIVISOR = 20

#: Never busier than 5 kHz, whatever the rate. At `MAX_TICK_HZ` this is Delta/5, so the
#: floor still leaves five polls per period; it binds only above 250 Hz.
_POLL_FLOOR_S = 0.0002

#: And never lazier than once a second, so a pathologically slow clock (Delta > 20 s)
#: still wakes often enough to notice a shutdown. This one only makes latency better.
_POLL_CEILING_S = 1.0

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ------------------------------------------------------------------ websocket

def hostname_of(header: str) -> str:
    """The host part of a `Host:` header, lowercased, without its port.

    `[::1]:8081` keeps its brackets (that is how an IPv6 literal is spelled in a Host
    header, and splitting it on `:` would leave `[`); everything else splits on the
    first colon.
    """
    value = (header or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value if end == -1 else value[:end + 1]
    return value.split(":", 1)[0]


def allowed_hosts(bind: str, extra=()) -> frozenset[str]:
    """`Host:` values to answer to when bound to `bind`.

    Loopback always, plus the bind address when it names a real interface, plus
    anything `--allowed-host` added. A wildcard bind cannot name the host a client will
    dial, so an exposed deployment has to say what it is reachable as -- that is what
    `--allowed-host` is for, and it is the same act of deliberate exposure `--host` is.
    """
    names = set(LOOPBACK_HOSTS)
    for name in (bind, *extra):
        cleaned = hostname_of(name)
        if cleaned and cleaned not in {"0.0.0.0", "::", "[::]"}:
            names.add(cleaned)
    return frozenset(names)


def ws_accept(key: str) -> str:
    """The `Sec-WebSocket-Accept` value for a client's `Sec-WebSocket-Key`."""
    digest = hashlib.sha1((key + _WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def ws_frame(payload: bytes) -> bytes:
    """One unmasked binary-safe text frame. Server frames are never masked."""
    header = bytearray([0x81])  # FIN + text
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


class _WebSocketClient:
    """One streaming client. Writes are locked: pulses arrive on the ROS timer thread."""

    def __init__(self, wfile):
        self._wfile = wfile
        self._lock = threading.Lock()
        self.alive = True

    def send(self, payload: dict) -> None:
        frame = ws_frame(json.dumps(payload).encode("utf-8"))
        with self._lock:
            if not self.alive:
                return
            try:
                self._wfile.write(frame)
                self._wfile.flush()
            except (OSError, ValueError):
                # A client that went away mid-pulse must not take the clock with it.
                self.alive = False


# ----------------------------------------------------------------- http server

class ClockRequestHandler(BaseHTTPRequestHandler):
    """Routes to `ClockService.handle`, streams `/api/clock/stream`, decides nothing."""

    protocol_version = "HTTP/1.1"

    #: Set by `serve_http` on the generated subclass.
    service: ClockService = None  # type: ignore[assignment]
    log_line = staticmethod(lambda message: None)
    allowed_hosts: frozenset = LOOPBACK_HOSTS

    STREAM_PATH = "/api/clock/stream"

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib hook
        type(self).log_line(fmt % args)

    def _respond(self, status: int, payload: dict, *, close: bool = False) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if close:
            # Both the header (so the client knows) and the flag (so the server acts on
            # it). `send_header("Connection", "close")` sets `close_connection` itself,
            # but it is set explicitly too: the flag is what actually prevents the
            # desync in `_refuse`, and it must not depend on a stdlib side effect.
            self.send_header("Connection", "close")
            self.close_connection = True
        # The frontend may be served from anywhere, and the clock is queryable
        # standalone -- with no gateway in front of it there is no other origin to
        # inherit. Not because the endpoints are harmless (`mode` pauses the tick) but
        # because there are no credentials here for a same-origin policy to protect:
        # the boundary is the loopback bind and whatever proxy fronts it, never CORS.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _foreign_host(self) -> bool:
        """True (having answered 400) if the `Host` header is not one of ours.

        Checked before ANY routing, on every verb including the WebSocket upgrade: a
        DNS-rebinding page is same-origin with this service, so it needs no preflight
        and `do_OPTIONS` is not a chokepoint. `Host` is the one header the page cannot
        choose -- the browser fills it in from the name it dialled.
        """
        header = self.headers.get("Host")
        if hostname_of(header) in self.allowed_hosts:
            return False
        self._refuse(400, f"Host {header!r} is not served here; this clock answers to "
                          f"{sorted(self.allowed_hosts)}. Name it with --allowed-host "
                          f"if it should.")
        return True

    def do_GET(self):  # noqa: N802 - stdlib hook
        if self._foreign_host():
            return
        path = self._path()
        if path.rstrip("/") == self.STREAM_PATH:
            self._stream()
            return
        self._respond(*self.service.handle("GET", path))

    def _refuse(self, status: int, message: str) -> None:
        """Answer, then hang up. **Always hang up.**

        This is a `keep-alive` server (`protocol_version = "HTTP/1.1"`), so refusing a
        request without either draining its body or closing the connection leaves the
        undrained bytes in the socket to be parsed as the NEXT request -- classic
        request smuggling. One connection carrying `Content-Length: 99999999` followed
        by `POST /api/clock/mode {"paused": true}` would get a 413 for the first and a
        200 for the second, and the tick every service on the tier advances on would
        stop. That defeats the exact mitigation this module's docstring prescribes: a
        fronting proxy sees and authorises one request while the clock executes two.

        Draining instead of closing is not an option: the excess is unbounded and
        entirely attacker-controlled, which is the reason there is a limit at all.
        """
        self._respond(status, {"error": message}, close=True)

    def _read_body(self) -> bytes | None:
        """The request body, or `None` having already answered why there is not one.

        Same shape as `_read_body` in the gateway (P6, PR #5, not yet on this branch) --
        400 on a `Content-Length` that is not an integer, 413 above `MAX_BODY_BYTES` --
        and deliberately a second copy rather than a shared helper, because two call
        sites in two processes with two different ceilings is not an abstraction. When
        that lands, the two must stay in step; this comment is the only link between
        them.
        """
        # Refused rather than implemented: `http.server` does not decode chunked bodies,
        # so ignoring the header leaves the whole body unread in the socket -- the same
        # desync as an oversized one, reached by a header instead of a length.
        if (self.headers.get("Transfer-Encoding") or "").strip():
            self._refuse(400, "Transfer-Encoding is not supported; send Content-Length")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._refuse(400, "Content-Length is not an integer")
            return None
        # A negative length silently became an empty body, so the real body stayed in
        # the socket: the smuggle again, spelled `-5`.
        if length < 0:
            self._refuse(400, "Content-Length is negative")
            return None
        if length > MAX_BODY_BYTES:
            self._refuse(413, f"body larger than {MAX_BODY_BYTES} bytes")
            return None
        return self.rfile.read(length) if length > 0 else b""

    def do_POST(self):  # noqa: N802 - stdlib hook
        # Before the body is even read: a foreign Host is refused whatever it carries.
        if self._foreign_host():
            return
        raw = self._read_body()
        if raw is None:
            return
        if raw:
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                self._respond(400, {"error": f"body is not JSON: {exc}"})
                return
        else:
            # An empty body is a legitimate `POST /api/clock/step`.
            body = {}
        self._respond(*self.service.handle("POST", self._path(), body))

    def do_OPTIONS(self):  # noqa: N802 - stdlib hook
        if self._foreign_host():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _stream(self) -> None:
        """`WS /api/clock/stream` -- one frame per pulse, identical to the topic payload.

        The frame is not re-serialised from the clock's state; it is the very dict the
        publisher was handed, so "byte for byte" is structural.
        """
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in (self.headers.get("Upgrade") or "").lower():
            self._respond(426, {
                "error": f"{self.STREAM_PATH} is a WebSocket endpoint",
                "hint": "GET /api/clock is the sample; it is up to one tick period stale "
                        "and polling it will miss ticks",
            })
            return

        self.close_connection = True
        self.wfile.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + ws_accept(key).encode("ascii") + b"\r\n\r\n"
        )
        self.wfile.flush()

        client = _WebSocketClient(self.wfile)
        sink = self.service.subscribe(client.send)
        try:
            # Read only to notice the client leaving: this endpoint is send-only, so
            # incoming frames (including a close) are drained, never parsed.
            while client.alive:
                if not self.connection.recv(1024):
                    break
        except OSError:
            pass
        finally:
            client.alive = False
            self.service.unsubscribe(sink)


def serve_http(service: ClockService, *, host: str = DEFAULT_HOST,
               port: int = DEFAULT_PORT, extra_hosts=(),
               log=lambda message: None) -> ThreadingHTTPServer:
    """Start the HTTP surface on a daemon thread and return the server.

    Threading, because a WebSocket client holds its connection open for the run: a
    single-threaded server would answer `GET /api/clock` for exactly as long as nobody
    was streaming.

    `host` defaults to loopback. There is no authentication on any of these endpoints
    and one of them pauses the tick the safety monitor advances on, so binding to a
    network is a caller's explicit decision, never this function's default. `Host`
    headers are checked against `allowed_hosts(host, extra_hosts)` before routing,
    because a loopback bind alone does not stop a rebound browser tab.
    """
    handler = type("BoundClockRequestHandler", (ClockRequestHandler,),
                   {"service": service, "log_line": staticmethod(log),
                    "allowed_hosts": allowed_hosts(host, extra_hosts)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="clock-http", daemon=True).start()
    return server


# ------------------------------------------------------------------------ cli

def _tick_hz_arg(value: str) -> float:
    """`--tick-hz`, validated by the same rule `POST /api/clock/rate` applies.

    Here rather than in `main`, so an out-of-range rate is a usage error on the command
    line instead of a traceback out of a constructor after `rclpy.init`.
    """
    try:
        return valid_tick_hz(float(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clock_node",
        description="Pulses the tick every other service advances on.",
    )
    # --rate / --source are what deploy/docker-compose.*.yml pass; --tick-hz / --mode are
    # the names in the docs. Aliases rather than a rename: the compose files belong to
    # P8, and a flag name is not worth a cross-package edit.
    parser.add_argument("--tick-hz", "--rate", dest="tick_hz", type=_tick_hz_arg,
                        default=1.0,
                        help=f"declared tick frequency in Hz, 0 < hz <= {MAX_TICK_HZ:g}; "
                             f"the period is 1/tick_hz SECONDS on the active clock "
                             f"(default: 1.0)")
    parser.add_argument("--mode", "--source", dest="mode", default="wall",
                        choices=list(api.CLOCK_MODES),
                        help="wall: live. replay: advanced by a driver, so replay speed "
                             "cannot change the tick count. manual: one tick per "
                             "POST /api/clock/step (default: wall)")
    parser.add_argument("--paused", action="store_true",
                        help="start emitting nothing; time spent paused produces no "
                             "ticks and no gap. An explicit step still advances")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"HTTP port for the clock API (default: {DEFAULT_PORT})")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"HTTP bind address (default: {DEFAULT_HOST}). There is no "
                             f"authentication on this API and POST /api/clock/mode can "
                             f"pause the tick every service advances on, so publishing "
                             f"it to a network is an explicit --host 0.0.0.0 behind a "
                             f"proxy that authenticates")
    parser.add_argument("--allowed-host", dest="allowed_hosts", action="append",
                        default=[], metavar="NAME",
                        help="extra Host: header value to answer to; repeatable. "
                             "Loopback and --host are always allowed. Needed only when "
                             "the clock is exposed and reached by a name it cannot "
                             "infer, because Host is what stops a DNS-rebinding page "
                             "in the operator's browser from driving this API")
    parser.add_argument("--no-http", action="store_true",
                        help="topic only; for a tier that reaches the clock over DDS")
    return parser


def poll_period(delta: float) -> float:
    """Timer period for a tick period of `delta` seconds.

    Only affects how promptly a boundary is noticed. The pulse count is a function of
    elapsed clock time and the declared rate, never of this number -- which is the
    invariant that lets it be chosen for CPU cost alone.

    `Delta/_POLL_DIVISOR`, clamped by a floor (never busier than 5 kHz) and a ceiling
    (never lazier than 1 s). Both clamps only ever make the period *smaller* than the
    tick, so the guarantee that survives every rate is `poll_period(d) <= d / 5`.
    """
    return min(_POLL_CEILING_S, max(_POLL_FLOOR_S, delta / _POLL_DIVISOR))


class PollTimerTuner:
    """Keeps the poll timer's period in step with a rate that can change at runtime.

    The timer is created once, from the period the clock started at. `set_rate` changes
    the engine's Delta but not the timer, and `poll()` emits **at most one pulse per
    call** -- so a timer left at the old period silently caps the tick rate at its own
    frequency. Measured: `POST /api/clock/rate` from 1 Hz to 1000 Hz produced 20
    pulses/s instead of 1000, with `skipped=49` on every pulse and a stall warning in
    the log each time. The clock would report, accurately and uselessly, that it was
    failing to keep up with itself.

    Two threads, so the hand-off is explicit: `request` is called on the HTTP thread
    (from `ClockService`'s rate hook) and only *records* what the timer should become;
    `apply` is called from the timer's own callback, on the executor thread that owns
    it, and is the only place the period actually changes. Re-tuning a live rclpy timer
    from a request handler would be a data race on the executor's internals.
    """

    def __init__(self, delta: float):
        self._lock = threading.Lock()
        self._period = poll_period(delta)
        self._wanted = self._period

    @property
    def period(self) -> float:
        """The period the timer is running at now."""
        return self._period

    def request(self, tick_hz: float) -> None:
        """Record the period `tick_hz` wants. Safe from any thread."""
        with self._lock:
            self._wanted = poll_period(1.0 / tick_hz)

    def apply(self, set_period: Callable[[float], None]) -> float | None:
        """Re-tune if the rate moved. Returns the new period, or `None` if unchanged.

        Called from the timer callback on every pulse; the common case is one lock
        acquisition and a float comparison.
        """
        with self._lock:
            wanted = self._wanted
        if wanted == self._period:
            return None
        set_period(wanted)
        self._period = wanted
        return wanted


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)

    import rclpy
    from std_msgs.msg import String

    engine = TickEngine(tick_hz=args.tick_hz, mode=args.mode, paused=args.paused)
    armed = ArmedTracker()

    rclpy.init()
    node = rclpy.create_node("skill_monitor_clock")
    log = node.get_logger()

    publisher = node.create_publisher(String, api.TICK, 10)
    tuner = PollTimerTuner(engine.delta)
    service = ClockService(
        engine,
        armed=armed,
        subscribers=lambda: node.count_subscribers(api.TICK),
        on_rate_change=tuner.request,
    )
    service.subscribe(lambda payload: publisher.publish(String(data=json.dumps(payload))))

    def _on_json(handler):
        def _cb(msg):
            try:
                handler(json.loads(msg.data))
            except ValueError:
                pass  # a malformed frame from someone else is not the clock's problem
        return _cb

    node.create_subscription(String, api.COMMAND, _on_json(armed.on_command), 10)
    # A verdict carrying a non-null `step` is an armed monitor saying so once per tick;
    # it is what makes the rate refusal correct for a clock restarted mid-episode.
    node.create_subscription(String, api.VERDICT, _on_json(armed.on_verdict), 10)

    def _retune(period: float) -> None:
        # rclpy exposes the live period as nanoseconds; setting it re-arms the timer in
        # place, which is why the timer is not destroyed and recreated under the
        # executor that is currently driving it.
        timer.timer_period_ns = int(period * 1e9)

    def _on_timer():
        # Before the poll, and on the executor thread that owns the timer: a rate change
        # that arrived on the HTTP thread since the last tick takes effect now.
        retuned = tuner.apply(_retune)
        if retuned is not None:
            log.info(f"poll timer re-tuned to {retuned:g}s for {engine.tick_hz:g} Hz")

        pulse = service.pulse()
        if pulse is not None and pulse.skipped:
            log.warning(
                f"stalled: {pulse.skipped} boundary(ies) passed unpublished before "
                f"seq={pulse.seq}; one pulse emitted, no catch-up"
            )

    timer = node.create_timer(tuner.period, _on_timer)

    server = None
    if not args.no_http:
        server = serve_http(service, host=args.host, port=args.port,
                            extra_hosts=args.allowed_hosts,
                            log=lambda message: log.debug(message))
        log.info(f"clock API on http://{args.host}:{args.port}/api/clock")
    log.info(f"tick {engine.tick_hz} Hz, mode {engine.mode}"
             f"{', paused' if engine.paused else ''}, t0={engine.t0}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
