#!/usr/bin/env python3
"""Preflight: does the ROS graph the adapter describes actually exist, here, now?

Deployment glue, not part of `skill_monitor` -- the same rule the rest of `tools/`
follows. Nothing here is imported by the package.

The failure this exists to prevent is the expensive one: bring the stack up beside a
running robot, watch the console show `INCONCLUSIVE_NO_DATA` on every proposition, and
spend the battery finding out that one topic is named something else. The adapter
descriptor already declares every topic and every type the evaluator will subscribe to.
This asks the live graph whether they are there, and says which are not, in the seconds
before the run rather than the minutes after it.

    python3 tools/g1_preflight.py                          # real_g1, packaged descriptor
    python3 tools/g1_preflight.py --adapter mujoco
    python3 tools/g1_preflight.py --descriptor /config/adapters/real_g1.json
    python3 tools/g1_preflight.py --rates                  # also measure Hz (slow)

It shells to `ros2 topic list -t` rather than importing `rclpy`, for two reasons that
are both about where it runs. On the G1 the host and every TRAV container are Python
3.8 while `skill_monitor` declares `requires-python = ">=3.10"`, so a preflight that
imported the package could not run in the place that most needs it -- **keep this file
3.8-clean**, exactly like `bridge_tx.py`. And a subscriber of our own would join the
graph it is measuring; `ros2 topic list` reports what the evaluator will find without
adding a publisher, a QoS negotiation or a discovery round to it.

What it cannot tell you: whether the *contents* are right. A `/t265/odom/sample` that
publishes at 10 Hz with a frozen pose passes every check here. That is what the console's
input pane (panel 4) and `min_range` on a metre stick are for.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

#: Packaged descriptors, resolved relative to this file so the tool works from any cwd.
#: `--descriptor` takes a path when the run is reading a mounted /config instead.
PACKAGED_ADAPTERS = pathlib.Path(__file__).resolve().parents[1] / "skill_monitor" / "adapters"

#: A source publishing slower than this fraction of its declared `expected_hz` is
#: reported. Not an error: a rate is a declaration about a healthy robot, and the
#: evaluator's own freshness logic -- not this tool -- decides what a slow source does
#: to a proposition. Loose enough that jitter and a short measurement window do not
#: cry wolf.
RATE_FLOOR = 0.5

#: Seconds spent measuring one topic under `--rates`. `ros2 topic hz` prints its first
#: average after a second or so; anything under ~4 s on a 1 Hz source measures nothing.
RATE_WINDOW_S = 5.0

ERROR = "error"
WARN = "warn"
OK = "ok"


# =============================================================================
# The descriptor
# =============================================================================

def load_descriptor(name_or_path: str) -> dict:
    """A descriptor by bare name (packaged) or by path (a mounted config volume)."""
    path = pathlib.Path(name_or_path)
    if not path.suffix:
        path = PACKAGED_ADAPTERS / (name_or_path + ".json")
    with open(str(path), encoding="utf-8") as fh:
        return json.load(fh)


def declared_sources(descriptor: dict) -> List[dict]:
    """The sources, with `tracked`/`required` resolved the way `adapter_spec` resolves
    them: `tracked` defaults true, and `required` defaults to `tracked` -- "only because
    that is what today's descriptors mean when they say nothing"
    (`core/adapter_spec.py`). Mirrored here rather than imported, because importing it
    would need Python 3.10 on a robot that has 3.8.
    """
    out = []
    for raw in descriptor.get("sources") or []:
        if not isinstance(raw, dict) or not raw.get("topic"):
            continue
        tracked = bool(raw.get("tracked", True))
        out.append({
            "id": raw.get("id") or raw["topic"],
            "topic": raw["topic"],
            "type": raw.get("type"),
            "tracked": tracked,
            "required": bool(raw.get("required", tracked)),
            "expected_hz": raw.get("expected_hz"),
        })
    return out


# =============================================================================
# Reading the live graph
# =============================================================================

_TOPIC_LINE = re.compile(r"^\s*(/\S*)\s*\[(.+)\]\s*$")


def parse_topic_list(text: str) -> Dict[str, List[str]]:
    """`ros2 topic list -t` output -> {topic: [type, ...]}.

    A topic can carry more than one type when two publishers disagree, and the bracket
    then holds a comma-separated list. That is itself a finding, so the parse keeps
    every type rather than the first.
    """
    live = {}  # type: Dict[str, List[str]]
    for line in text.splitlines():
        match = _TOPIC_LINE.match(line)
        if match:
            types = [t.strip() for t in match.group(2).split(",") if t.strip()]
            live[match.group(1)] = types
    return live


_AVERAGE_RATE = re.compile(r"average rate:\s*([0-9]+\.?[0-9]*)")


def parse_hz(text: str) -> Optional[float]:
    """The last `average rate:` line of `ros2 topic hz`, or None if it never printed
    one -- which is what a topic with no publisher looks like, and is not zero."""
    found = _AVERAGE_RATE.findall(text or "")
    return float(found[-1]) if found else None


class NoRos2(Exception):
    """`ros2` is not on PATH. Not a robot problem and not a preflight failure: this
    shell simply cannot answer the question, which is a different thing from answering
    it with "nothing is there"."""


def _run(argv: Sequence[str], timeout: float) -> str:
    """A command's output, however it ended. `ros2 topic hz` never exits on its own, so
    a timeout is the normal path here and not an error."""
    try:
        proc = subprocess.Popen(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
    except OSError as exc:
        raise NoRos2("cannot run %s: %s" % (argv[0], exc))
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out or ""


def live_topics(timeout: float = 15.0) -> Dict[str, List[str]]:
    return parse_topic_list(_run(["ros2", "topic", "list", "-t"], timeout))


def measure_hz(topic: str, window_s: float = RATE_WINDOW_S) -> Optional[float]:
    return parse_hz(_run(["ros2", "topic", "hz", topic], window_s))


# =============================================================================
# The verdict
# =============================================================================

def check(sources: List[dict],
          live: Dict[str, List[str]],
          rates: Optional[Dict[str, Optional[float]]] = None,
          ) -> List[Tuple[str, str, str]]:
    """`(severity, source_id, message)` per source, in descriptor order.

    A missing *required* source is an error because the evaluator will hold every
    proposition over its keys at UNKNOWN; a missing optional one is a warning because
    the run is still worth having without it. A type mismatch is an error either way:
    the subscription is created on the declared type and simply never fires.
    """
    rates = rates or {}
    findings = []
    for src in sources:
        topic, declared, sid = src["topic"], src["type"], src["id"]
        severity = ERROR if src["required"] else WARN
        types = live.get(topic)

        if types is None:
            findings.append((severity, sid, "%s is NOT PUBLISHED" % topic))
            continue
        if declared and declared not in types:
            findings.append((ERROR, sid, "%s carries %s, descriptor declares %s"
                             % (topic, "/".join(types), declared)))
            continue

        measured = rates.get(topic)
        expected = src["expected_hz"]
        if measured is None and topic in rates:
            findings.append((severity, sid, "%s is advertised but nothing arrived" % topic))
        elif measured is not None and expected and measured < RATE_FLOOR * float(expected):
            findings.append((WARN, sid, "%s at %.1f Hz, declares %.1f" % (topic, measured, float(expected))))
        else:
            rate = " at %.1f Hz" % measured if measured is not None else ""
            findings.append((OK, sid, "%s%s" % (topic, rate)))
    return findings


def summarise(findings: List[Tuple[str, str, str]], live_count: int) -> Tuple[int, List[str]]:
    """Exit code, plus the lines that go under the table.

    The all-missing case gets its own sentence. Every topic absent almost never means
    every node is down -- it means this shell is looking at a different graph than the
    robot's, and naming the two settings that decide that saves the ten minutes usually
    spent restarting healthy nodes.
    """
    errors = [f for f in findings if f[0] == ERROR]
    warns = [f for f in findings if f[0] == WARN]
    lines = []
    if findings and not [f for f in findings if f[0] == OK]:
        lines.append(
            "NOT ONE declared topic is visible%s. Before restarting a single healthy "
            "node: is this shell on the robot, does ROS_DOMAIN_ID match the TRAV "
            "stack's, and does RMW_IMPLEMENTATION?"
            % ("" if live_count else ", and the graph is empty"))
    if errors:
        lines.append("PREFLIGHT FAILED: %d required source(s) missing or mistyped." % len(errors))
    elif warns:
        lines.append("Preflight passed with %d warning(s): the run is worth having, and "
                     "the propositions over those sources will read UNKNOWN." % len(warns))
    else:
        lines.append("Preflight passed: every declared source is live.")
    return (1 if errors else 0), lines


# =============================================================================
# Entry point
# =============================================================================

_MARK = {ERROR: "FAIL", WARN: "warn", OK: "ok  "}


def report(descriptor: dict, findings: List[Tuple[str, str, str]],
           live_count: int, out=sys.stdout) -> int:
    print("adapter:  %s" % descriptor.get("name", "?"), file=out)
    print("domain:   ROS_DOMAIN_ID=%s  RMW_IMPLEMENTATION=%s"
          % (os.environ.get("ROS_DOMAIN_ID", "0 (unset)"),
             os.environ.get("RMW_IMPLEMENTATION", "default (unset)")), file=out)
    print("graph:    %d topic(s) visible" % live_count, file=out)
    print("", file=out)
    width = max([len(f[1]) for f in findings] or [1])
    for severity, sid, message in findings:
        print("  %s  %-*s  %s" % (_MARK[severity], width, sid, message), file=out)
    print("", file=out)
    code, lines = summarise(findings, live_count)
    for line in lines:
        print(line, file=out)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the live ROS graph against an adapter descriptor, before a run.")
    parser.add_argument("--adapter", default="real_g1",
                        help="bare descriptor name, resolved against the packaged adapters")
    parser.add_argument("--descriptor", default=None, metavar="PATH",
                        help="a descriptor file, e.g. on a mounted /config volume")
    parser.add_argument("--rates", action="store_true",
                        help="also measure each topic's publish rate (adds ~%ds per "
                             "topic)" % int(RATE_WINDOW_S))
    parser.add_argument("--window", type=float, default=RATE_WINDOW_S,
                        help="seconds spent measuring one topic under --rates")
    args = parser.parse_args(argv)

    try:
        descriptor = load_descriptor(args.descriptor or args.adapter)
    except (OSError, ValueError) as exc:
        print("cannot read the descriptor: %s" % exc, file=sys.stderr)
        return 2

    sources = declared_sources(descriptor)
    if not sources:
        print("%s declares no sources with a topic" % descriptor.get("name", "?"),
              file=sys.stderr)
        return 2

    try:
        live = live_topics()
        rates = None
        if args.rates:
            rates = {}
            for src in sources:
                if src["topic"] in live:
                    rates[src["topic"]] = measure_hz(src["topic"], args.window)
    except NoRos2 as exc:
        # Exit 2, not 1. "I could not check" and "I checked and it is not ready" are
        # different answers, and a launch script that cannot tell them apart either
        # retries a typo forever or drives onto a robot it never looked at.
        print("%s -- source a ROS 2 setup.bash first" % exc, file=sys.stderr)
        return 2
    return report(descriptor, check(sources, live, rates), len(live))


if __name__ == "__main__":
    sys.exit(main())
