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
import re
import shutil
import subprocess
import sys
import tempfile

from skill_monitor.backend import gateway as gw

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"
log = logging.getLogger("skill_monitor.console")

#: The page is one `<script>`. That is deliberate -- no build step, no module graph, one
#: file to serve -- and it has one consequence worth a guard: a syntax error anywhere in
#: it stops the *whole* script parsing, so every pane goes blank at once. That has
#: happened, from a backtick inside an HTML comment inside a template literal, and no
#: test in this repo could see it: Python cannot parse JavaScript, and the page has no
#: test runner.
_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def page_syntax_problems(page: pathlib.Path | None = None) -> list[str]:
    """Problems `node --check` finds in the page's JavaScript. Empty means it parses.

    Returns a problem rather than raising when node is missing, so a caller can decide
    whether an unavailable checker is a skip or a failure. It is not this function's
    business to know which.
    """
    page = page or PAGE
    if not page.exists():
        return [f"{page}: no such file"]
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        return ["node is not installed, so the page's JavaScript was not checked"]

    blocks = _SCRIPT.findall(page.read_text())
    if not blocks:
        return [f"{page}: no <script> block to check"]

    problems = []
    for i, source in enumerate(blocks):
        # A real file, because `node --check -` reads stdin as CommonJS regardless of
        # what the source looks like, and the error text is what a reader has to act on.
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(source)
            scratch = fh.name
        try:
            done = subprocess.run([node, "--check", scratch],
                                  capture_output=True, text=True, timeout=30)
            if done.returncode != 0:
                where = "" if len(blocks) == 1 else f" (script block {i + 1})"
                # node names the scratch file; the reader cares about the page.
                detail = (done.stderr or done.stdout).replace(scratch, str(page))
                problems.append(f"{page.name}{where}: {detail.strip()}")
        finally:
            pathlib.Path(scratch).unlink(missing_ok=True)
    return problems


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
    parser.add_argument("--check", action="store_true",
                        help="syntax-check the page and exit, without binding a port. "
                             "Needs node. The page is one script, so one error blanks "
                             "every pane at once.")
    return parser


def own_origins(host: str, port: int) -> list[str]:
    """The origins this process is reached at, so its own page can open a stream.

    A wildcard bind is reachable as any name the deployment has, and this file cannot
    enumerate them -- loopback is still named because it is still true, and anything
    else is the operator's ``--allow-origin``.

    ``port`` must be the **bound** port, not the one asked for: with ``--port 0`` the
    kernel picks it, and an origin list naming port 0 matches nothing the browser sends.
    """
    names = ["127.0.0.1", "localhost"]
    if host in ("::", "::1"):
        # An IPv6 bind is reached at ::1 too, and `::` names nothing of its own.
        names.append("::1")
    elif host not in ("0.0.0.0", "*", "127.0.0.1", "localhost"):
        names.append(host)
    return [f"http://{_authority(name)}:{port}" for name in names]


def _authority(name: str) -> str:
    """An IPv6 literal in a URL is bracketed. A browser at ``[::1]:8080`` sends
    ``Origin: http://[::1]:8080``, and ``http://::1:8080`` is not that string -- nor is
    it something ``urlsplit`` can pull a hostname out of, so the Host allowlist derived
    from these origins would be wrong in the same breath."""
    return f"[{name}]" if ":" in name and not name.startswith("[") else name


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Before anything is built or bound: a page that does not parse serves a blank
    # console, and the server would come up looking perfectly healthy while it did.
    if args.check:
        problems = page_syntax_problems()
        for problem in problems:
            log.error("%s", problem)
        if not problems:
            log.info("%s parses", PAGE.name)
        return 1 if problems else 0

    if args.mock:
        from skill_monitor.frontend.mock_monitor import MockBus
        bus = MockBus(rate_scale=args.mock_rate)
        log.warning("--mock: there is no ROS. Every value on this page is fabricated.")
    else:
        bus = gw.build_bus(True)

    # Bind first, then name the origin. With `--port 0` the port does not exist until
    # the socket is bound, and a gateway that allowlists `http://127.0.0.1:0` refuses
    # the websocket from the very page it just served. `server.gateway` is the real one;
    # nothing is served in between because `serve_forever` has not been called yet.
    server = gw.GatewayServer(gw.Gateway(), args.host, args.port)
    origins = own_origins(args.host, server.port) + list(args.allow_origin)
    clock = gw.HttpClockBackend(args.clock_url) if args.clock_url \
        else gw.NullClockBackend()
    server.gateway = gw.Gateway(
        bus, clock,
        allowed_origins=origins,
        allowed_hosts=gw.host_allowlist(args.host, origins, args.allow_host),
        static_dir=HERE,
    )

    log.info("console on http://%s:%d  (NO AUTHENTICATION -- trusted network only)",
             _authority(args.host), server.port)
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
