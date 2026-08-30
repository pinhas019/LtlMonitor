"""One session, one thing on disk, and a check that says whether it is complete.

An episode used to be three artifacts that had to be kept together by hand: a `.jsonl`
of the monitor's stream, a `ros2 bag` of the sensors, and whatever the operator wrote
down. Three things is not a record. They get copied off the robot separately, renamed
separately, and the day one of them is missing is months after the only day it could
have been recorded.

A **session bundle** is one directory:

    g1_run1/
      session.json     this manifest -- what ran, against what, when, and what is here
      stream.jsonl     /monitor/* -- the monitor's inputs AND its outputs
      sensors/         a rosbag2 of the adapter's sources and the descriptor's scene
      notes.md         the operator's, free text, written by hand

It is **self-describing on purpose**. `stream.jsonl` carries the latched
`/monitor/adapter` and `/monitor/manifest` frames, which is the robot's whole sensor
schema and the skill spec *exactly as authored*. So a bundle read six months later on a
machine that has never seen this repo still knows which robot it came from, which spec
was being monitored, and what every sensor key meant. Nothing has to be looked up
beside it, which is the property that makes one directory a record rather than a pile.

This module is the manifest and the completeness rule, and it is pure: no ROS, no
filesystem, no clock. `backend/replay_node.py` supplies all three.

**Completeness is reported, never enforced.** A session with no verdicts is still worth
keeping -- it is a sensor bag with a schema attached, and P12's calibration needs
exactly that. What must not happen is *believing* it holds a verdict comparison when it
does not, which is why `problems()` names each missing piece against the thing it makes
impossible rather than returning a bare boolean.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

from skill_monitor.core import api

#: Bumped when the manifest's shape changes in a way a reader must notice. Separate from
#: `api.SCHEMA_VERSION`: that versions the wire, this versions an archive that outlives
#: any particular wire.
SCHEMA_VERSION = 1

#: The four names inside a bundle. Constants because a reader written next year looks
#: them up here, and because a typo in one of them is a session that silently records
#: to a file nothing will ever open.
MANIFEST = "session.json"
STREAM = "stream.jsonl"
BAG = "sensors"
NOTES = "notes.md"

#: What each missing piece costs, named against the thing it makes impossible. The whole
#: value of the check: "incomplete" is not useful, "this cannot be re-executed in a
#: simulator" is.
#: The topic is interpolated rather than spelled: `test_no_hardcoded_topic_literals`
#: refuses a topic name written out anywhere but `api.py`, and it is right to -- a
#: rename that left these strings behind would have the report naming a topic nobody
#: subscribes to any more.
_MISSING_FRAMES = (
    (api.ADAPTER, "the evaluator was not running, so the sensor schema this run used "
                  "is NOT recorded and the bundle cannot explain its own sensor keys"),
    (api.MANIFEST, "the monitor was not running or loaded no spec, so the skill being "
                   "monitored is not recorded"),
    (api.OBSERVATION, "there is no stream to replay, which is the whole of the first "
                      "replay path"),
    (api.VERDICT, "nothing to compare a replay against, so `play --diff` can only "
                  "produce verdicts, never check them"),
)

_COSTS = {
    "bag": ("no sensor bag -- rviz2 has nothing to show and P12 has nothing to "
            "calibrate against"),
    "scene": ("the bag holds no scene topics -- this session can be replayed against "
              "the monitor and can NOT be re-executed in a simulator, because the "
              "world it happened in was not recorded"),
}


def new(session_id: str, *, host: str = "", note: str = "",
        now: Callable[[], float] = time.time) -> dict:
    """A manifest at the moment recording starts.

    Written before the first frame arrives, not after the last one. A session that ends
    in a crash, a flat battery or a dropped ssh connection then still has a directory
    that says what it was -- `ended` absent is itself the finding, and a bundle that
    only existed once it was finished would leave nothing at all.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "session": session_id,
        "host": host,
        "note": note,
        "started": now(),
        "ended": None,
        "adapter": None,
        "skill": None,
        "tick_hz": None,
        "frames": {},
        "bag": {"topics": [], "scene": []},
        "verdict": None,
    }


def describe_run(session: dict, adapter: dict | None, manifest: dict | None) -> dict:
    """Fold in what the latched frames say about the run, as they arrive.

    Duplicated onto the manifest rather than left only inside `stream.jsonl` so that
    `session.json` alone answers "what is this?" -- the question someone asks of a
    directory before deciding whether to open anything in it. The frames remain the
    authority; this is an index, and `problems()` checks the index against them.
    """
    out = dict(session)
    if isinstance(adapter, dict):
        out["adapter"] = adapter.get("adapter")
        out["tick_hz"] = adapter.get("tick_hz")
    if isinstance(manifest, dict):
        out["skill"] = manifest.get("skill_name")
    return out


def finalize(session: dict, *, frames: dict, bag: dict | None = None,
             verdict: dict | None = None, now: Callable[[], float] = time.time) -> dict:
    """Close the manifest: when it ended, what landed, and how it came out.

    `frames` is topic -> count, straight off `Recording.summary()["topics"]`, so the
    manifest's own numbers and the stream's cannot drift. `verdict` is the last one
    seen, kept in full rather than as a string: "how did this session end" is the
    question a directory of forty of them gets asked, and answering it should not need
    forty files opened.
    """
    out = dict(session)
    out["ended"] = now()
    out["frames"] = dict(frames)
    if bag is not None:
        out["bag"] = dict(bag)
    if verdict is not None:
        out["verdict"] = {"verdict": verdict.get("verdict"),
                          "terminal": verdict.get("terminal"),
                          "seq": verdict.get("seq")}
    return out


def duration_s(session: dict) -> float | None:
    started, ended = session.get("started"), session.get("ended")
    if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
        return round(ended - started, 3)
    return None


def problems(session: dict) -> list[str]:
    """What this bundle cannot be used for, and why. Empty means complete.

    Run at the END of a session, while the robot is still standing there and a second
    run costs ten minutes rather than a return trip. That timing is the entire point:
    every one of these is unfixable the moment the operator walks away.
    """
    found = []
    frames = session.get("frames") or {}
    for topic, cost in _MISSING_FRAMES:
        # Zero is as absent as missing: a subscription that matched and then received
        # nothing writes `{topic: 0}`, and no frames is not evidence of a recording.
        if not frames.get(topic):
            found.append(f"no {topic} frame(s) -- {cost}")

    bag = session.get("bag") or {}
    if bag.get("failed"):
        # Distinct from "no bag was asked for". The recorder was launched and produced
        # nothing, which is a broken robot-side setup rather than an operator's choice,
        # and it is worth saying which happened.
        found.append(f"{_COSTS['bag']} -- {bag['failed']}")
    elif not bag.get("topics"):
        found.append(_COSTS["bag"])
    elif not bag.get("scene"):
        found.append(_COSTS["scene"])
    return found


def report(session: dict) -> str:
    """The one screen an operator reads before walking away from the robot."""
    lines = [
        f"session  {session.get('session')}"
        + (f"  on {session['host']}" if session.get("host") else ""),
        f"skill    {session.get('skill') or '(none)'}"
        f"   adapter {session.get('adapter') or '(none)'}"
        + (f" @ {session['tick_hz']} Hz" if session.get("tick_hz") else ""),
    ]
    seconds = duration_s(session)
    lines.append(f"ran      {seconds} s" if seconds is not None
                 else "ran      DID NOT FINISH -- no end time was written")

    frames = session.get("frames") or {}
    if frames:
        lines.append("frames   " + ", ".join(
            f"{topic.rsplit('/', 1)[-1]}={count}" for topic, count in sorted(frames.items())))
    bag = session.get("bag") or {}
    if bag.get("topics"):
        lines.append(f"bag      {len(bag['topics'])} topic(s), "
                     f"{len(bag.get('scene') or [])} of them scene")
    verdict = session.get("verdict")
    if verdict:
        lines.append(f"ended    {verdict.get('verdict')} "
                     f"terminal={verdict.get('terminal')} at tick {verdict.get('seq')}")
    if session.get("note"):
        lines.append(f"note     {session['note']}")

    found = problems(session)
    lines.append("")
    if found:
        lines.append(f"INCOMPLETE -- {len(found)} thing(s) this bundle cannot do:")
        lines.extend("  * " + p for p in found)
        lines.append("Every one of these is unfixable once you walk away from the robot.")
    else:
        lines.append("Complete: replayable against the monitor and re-executable in sim.")
    return "\n".join(lines)


def bag_command(session_id: str, topics: Iterable[str], out_dir: str = BAG) -> list[str]:
    """The `ros2 bag record` argv for this session, so one place decides its shape."""
    return ["ros2", "bag", "record", "-o", out_dir, *topics]
