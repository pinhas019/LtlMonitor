"""The operator console: the gateway, plus the page, on one origin.

    python3 -m skill_monitor.frontend.web --mock     # no ROS, no robot, no clock
    python3 -m skill_monitor.frontend.web            # the real graph

One process and one origin on purpose. The gateway refuses a state-changing request
without ``X-Skill-Monitor`` and refuses a websocket from an ``Origin`` it was not told
about; both refusals are correct, and both would have to be relaxed if the page were
served from somewhere else. Serving it here means the console's own origin is the only
one that ever needs naming -- and this file names it, rather than asking an operator to
work out that ``--allow-origin http://127.0.0.1:8080`` is the incantation.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from skill_monitor.backend import gateway as gw

HERE = pathlib.Path(__file__).resolve().parent
log = logging.getLogger("skill_monitor.console")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m skill_monitor.frontend.web",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="loopback by default; this console has no authentication")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mock", action="store_true",
                        help="serve a monitor that exists only in this process. Every "
                             "sensor value is fabricated and the page says so.")
    parser.add_argument("--mock-rate", type=float, default=4.0, metavar="SCALE",
                        help="wall-clock speed-up of the mock's pulse. The tick_hz on "
                             "the wire stays the robot's; only the delay changes.")
    parser.add_argument("--clock-url", default="",
                        help="clock service to proxy; empty disables the proxy")
    parser.add_argument("--allow-origin", action="append", default=[], metavar="ORIGIN",
                        help="an extra browser origin, beyond this console's own")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                        help="an extra Host header value, beyond loopback and --host")
    parser.add_argument("--log-level", default="INFO")
    return parser


def own_origins(host: str, port: int) -> list[str]:
    """The origins this process is reached at, so its own page can open a stream.

    A wildcard bind is reachable as any name the deployment has, and this file cannot
    enumerate them -- loopback is still named because it is still true, and anything
    else is the operator's ``--allow-origin``.
    """
    names = ["127.0.0.1", "localhost"]
    if host not in ("0.0.0.0", "::", "*", "127.0.0.1", "localhost"):
        names.append(host)
    return [f"http://{name}:{port}" for name in names]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.mock:
        from skill_monitor.frontend.mock_monitor import MockBus
        bus = MockBus(rate_scale=args.mock_rate)
        log.warning("--mock: there is no ROS. Every value on this page is fabricated.")
    else:
        bus = gw.build_bus(True)

    origins = own_origins(args.host, args.port) + list(args.allow_origin)
    clock = gw.HttpClockBackend(args.clock_url) if args.clock_url \
        else gw.NullClockBackend()
    gateway = gw.Gateway(
        bus, clock,
        allowed_origins=origins,
        allowed_hosts=gw.host_allowlist(args.host, origins, args.allow_host),
        static_dir=HERE,
    )
    server = gw.GatewayServer(gateway, args.host, args.port)

    log.info("console on http://%s:%d  (NO AUTHENTICATION -- trusted network only)",
             args.host, server.port)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "bound to %s: an unauthenticated control surface for the robot is now "
            "reachable from every host that can route here.", args.host)
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
