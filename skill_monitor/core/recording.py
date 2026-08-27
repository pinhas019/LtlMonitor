"""An episode on disk, and the rule for replaying one.

The acceptance test `docs/packages/P9-docs.md` states for the agnosticism claim is that
two replay paths -- Isaac re-execution and pure stream replay -- **produce the same
verdict for the same episode**. That equality was not checkable, because nothing wrote
the episode down: `/monitor/observation` had no recorder and `/monitor/verdict` had no
recorder, so there was nothing to replay and nothing to compare against.

This module is that file format and the rule that makes a replay meaningful:

    **Replay the monitor's inputs. Compare its outputs.**

Which is which is not a judgement call, it is `INPUTS` and `OUTPUTS` below, and every
recorded topic is in exactly one of them. Replaying an output would be circular -- push
the recorded verdicts back onto `/monitor/verdict` and of course they match. Replaying
`api.MANIFEST` would be worse than circular: the monitor *publishes* the manifest from
the spec it loaded, so a replayer that also published one would put two producers on a
latched topic and the console would show whichever landed last.

**Why not `ros2 bag`.** For the sensor topics, use one -- that is what rviz2 and Isaac
replay from, and `bag_topics()` below writes the record line for you off the adapter the
run declared. A bag cannot do the job here for two reasons. It replays on *wall* time,
so the tick count of a replay depends on how fast the machine felt, which is the one
thing `core/clock.py` exists to prevent; and its payloads are serialized CDR, so a diff
between two runs is a diff of bytes rather than of `intervention.action`. The tick is
already in the stream, so a replay that publishes the recorded ticks is exact by
construction and needs no clock at all.

Pure Python, no ``rclpy``: a `Recorder` is handed a `write`, a `Player` is handed a
`publish`. `backend/replay_node.py` supplies the ROS ones and nothing else.

The format is JSON Lines, one frame per line, in arrival order::

    {"wall": 1756141482.913, "topic": "/monitor/tick", "payload": {...}}

Arrival order and not sequence order, deliberately. A command arrives between two ticks
and the run state it sets changes the verdicts that follow it, so a player that walked
the ticks in `seq` order and hung the commands off them somewhere would have to invent
an ordering the recording already knows. Playback is `for frame in recording.inputs()`.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Iterable, Iterator

from skill_monitor.core import api

#: What the monitor consumes. Replayed, in recorded order.
#:
#: `api.ADAPTER` is here because the monitor validates a spec against the robot's schema
#: and the evaluator that publishes it is not running during a replay. `api.LOAD_SPEC`
#: is here because a spec pushed mid-run changes every verdict after it, and an episode
#: that is missing the push is not the episode that was recorded.
INPUTS = (api.ADAPTER, api.TICK, api.OBSERVATION, api.COMMAND, api.LOAD_SPEC)

#: What the monitor produces. Recorded as the expected result, never replayed.
OUTPUTS = (api.VERDICT, api.MANIFEST, api.SPEC_STATUS, api.MONITOR_STATUS)

#: Everything a recording holds. Sorted so the `ros2 topic`/`ros2 bag` lines a operator
#: copies out of `--topics` are stable between runs.
RECORDED = tuple(sorted(set(INPUTS) | set(OUTPUTS)))


class Recorder:
    """Frames in, JSON Lines out.

    `write` takes one complete line including its newline, which is exactly
    `file.write`. `now` is injected for the same reason it is everywhere else in this
    codebase: a test asserts on the wall stamps rather than waiting for them.

    Text in, text out. The payload is re-parsed rather than passed through so that a
    frame which is not JSON is dropped *here*, with a count, instead of being written
    and then breaking a replay months later. `dropped` is the honest number.
    """

    def __init__(self, write: Callable[[str], None],
                 now: Callable[[], float] = time.time):
        self._write = write
        self._now = now
        self.written = 0
        self.dropped = 0

    def on(self, topic: str, text: str) -> bool:
        """One frame. True if it was written."""
        try:
            payload = json.loads(text)
        except Exception:
            self.dropped += 1
            return False
        if not isinstance(payload, dict):
            self.dropped += 1
            return False
        self._write(json.dumps(
            {"wall": self._now(), "topic": topic, "payload": payload},
            separators=(",", ":"), sort_keys=True) + "\n")
        self.written += 1
        return True


class Recording:
    """A parsed episode: the frames in order, plus the verdicts indexed by tick.

    `unreadable` counts lines that were not a frame. It is reported rather than raised
    because a recording truncated by a power cut is still worth replaying up to the cut,
    and a replay that refuses the whole file teaches nothing about where it stopped.
    """

    def __init__(self, frames: list[dict], unreadable: int = 0):
        self.frames = frames
        self.unreadable = unreadable

    @classmethod
    def parse(cls, lines: Iterable[str]) -> "Recording":
        frames: list[dict] = []
        unreadable = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
                topic = frame["topic"]
                payload = frame["payload"]
            except Exception:
                unreadable += 1
                continue
            if not isinstance(topic, str) or not isinstance(payload, dict):
                unreadable += 1
                continue
            frames.append({"wall": frame.get("wall"), "topic": topic,
                           "payload": payload})
        return cls(frames, unreadable)

    def of(self, topic: str) -> list[dict]:
        return [f["payload"] for f in self.frames if f["topic"] == topic]

    def latest(self, topic: str) -> dict | None:
        """The last frame on a latched topic -- the manifest a replay is judged under."""
        found = self.of(topic)
        return found[-1] if found else None

    def inputs(self) -> Iterator[dict]:
        """The frames a player publishes, in recorded order."""
        return (f for f in self.frames if f["topic"] in INPUTS)

    def verdicts(self) -> dict[int, dict]:
        """Recorded verdicts by `seq`. Later wins: a redelivered frame is not evidence
        of two verdicts for one tick, and the monitor's own contract is one per tick."""
        return {v["seq"]: v for v in self.of(api.VERDICT) if isinstance(v.get("seq"), int)}

    @property
    def ticks(self) -> int:
        return len(self.of(api.TICK))

    def summary(self) -> dict:
        counts = {}
        for f in self.frames:
            counts[f["topic"]] = counts.get(f["topic"], 0) + 1
        span = [f["wall"] for f in self.frames if isinstance(f.get("wall"), (int, float))]
        return {
            "frames": len(self.frames),
            "unreadable": self.unreadable,
            "topics": counts,
            "seconds": round(max(span) - min(span), 3) if len(span) > 1 else 0.0,
        }


def bag_topics(adapter: dict | None) -> list[str]:
    """The sensor topics to hand `ros2 bag record`, off the adapter the run declared.

    The monitor's own stream is this module's business; the *geometry* -- the cloud, the
    grid map, the paths -- is rviz2's and Isaac's, and it is not on `/monitor/*` at all.
    Reading the list off `api.ADAPTER` rather than naming topics here is the whole point:
    it is the same reason the console can render a robot it has never seen. A navigation
    stack and an arm produce different lists from the same call.
    """
    if not isinstance(adapter, dict):
        return []
    seen = []
    for source in adapter.get("sources") or []:
        topic = source.get("topic") if isinstance(source, dict) else None
        if isinstance(topic, str) and topic and topic not in seen:
            seen.append(topic)
    return seen


def _leaves(node, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Every scalar in a payload, by path. Lists are indexed, so a formula that moved
    from row 0 to row 1 reads as two differences and not as one silent reordering --
    the order is the automaton's, and if it changed, that is the finding."""
    if isinstance(node, dict):
        for key in sorted(node):
            yield from _leaves(node[key], f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _leaves(item, f"{prefix}[{i}]")
    else:
        yield prefix, node


def diff(recorded: dict, replayed: dict, ignore: Iterable[str] = ()) -> list[str]:
    """Differing paths between two payloads, as readable lines.

    Nothing is ignored by default, including `t`. A replay publishes the *recorded*
    ticks, so the time base is the recorded one and a `t` that moved means the replay
    invented a clock -- which is the bug this comparison exists to catch, not noise to
    filter out. `ignore` is there for a caller who has looked at a difference and
    decided it is expected; it is not there to make a first run pass.
    """
    skip = tuple(ignore)

    def kept(path: str) -> bool:
        return not any(path == s or path.startswith(s + ".") or
                       path.startswith(s + "[") for s in skip)

    left = {p: v for p, v in _leaves(recorded) if kept(p)}
    right = {p: v for p, v in _leaves(replayed) if kept(p)}
    out = []
    for path in sorted(set(left) | set(right)):
        a, b = left.get(path, "<absent>"), right.get(path, "<absent>")
        if a != b:
            out.append(f"{path}: {a!r} -> {b!r}")
    return out


class Comparison:
    """The result of a replay: what matched, what did not, and what was never produced.

    A missing verdict is kept apart from a differing one on purpose. A tick the replay
    produced no verdict for is a monitor that stopped stepping, and reporting that as
    "every field differs" would bury one failure under a hundred lines of noise.
    """

    def __init__(self, matched: list[int], differed: dict[int, list[str]],
                 missing: list[int], extra: list[int]):
        self.matched = matched
        self.differed = differed
        self.missing = missing
        self.extra = extra

    @property
    def equal(self) -> bool:
        return not self.differed and not self.missing and not self.extra

    def report(self, limit: int = 10) -> str:
        lines = [f"{len(self.matched)} verdicts identical, "
                 f"{len(self.differed)} differ, {len(self.missing)} missing, "
                 f"{len(self.extra)} unexpected"]
        if self.missing:
            lines.append(f"  no verdict replayed for ticks: "
                         f"{self.missing[:limit]}{' ...' if len(self.missing) > limit else ''}")
        if self.extra:
            lines.append(f"  verdict replayed for unrecorded ticks: "
                         f"{self.extra[:limit]}{' ...' if len(self.extra) > limit else ''}")
        for seq in sorted(self.differed)[:limit]:
            lines.append(f"  tick {seq}:")
            for line in self.differed[seq][:limit]:
                lines.append(f"    {line}")
        if len(self.differed) > limit:
            lines.append(f"  ... and {len(self.differed) - limit} more ticks")
        return "\n".join(lines)


def compare(recorded: dict[int, dict], replayed: dict[int, dict],
            ignore: Iterable[str] = ()) -> Comparison:
    matched, differed = [], {}
    for seq in sorted(set(recorded) & set(replayed)):
        problems = diff(recorded[seq], replayed[seq], ignore)
        if problems:
            differed[seq] = problems
        else:
            matched.append(seq)
    return Comparison(matched, differed,
                      sorted(set(recorded) - set(replayed)),
                      sorted(set(replayed) - set(recorded)))


class Player:
    """Walks a recording's inputs, collects what the monitor answers.

    `publish(topic, text)` is the only thing it needs, and `feed()` is how the recomputed
    verdicts get back in -- so the whole of playback is testable without a ROS graph and
    without a socket, which is the house rule for control-stack code.

    `step()` returns the frame it published, or None when the recording is spent. The
    caller decides what to wait for between frames: `replay_node` waits for the verdict
    of an observation and does not wait at all for anything else, because only an
    observation steps the automaton.
    """

    def __init__(self, recording: Recording, publish: Callable[[str, str], None]):
        self.recording = recording
        self._publish = publish
        self._queue = list(recording.inputs())
        self._at = 0
        self.replayed: dict[int, dict] = {}
        self.published = 0

    @property
    def remaining(self) -> int:
        return len(self._queue) - self._at

    def step(self) -> dict | None:
        if self._at >= len(self._queue):
            return None
        frame = self._queue[self._at]
        self._at += 1
        self._publish(frame["topic"], json.dumps(frame["payload"]))
        self.published += 1
        return frame

    def feed(self, text: str) -> int | None:
        """A verdict off the wire. Returns its `seq`, or None if it was not one."""
        try:
            payload = json.loads(text)
        except Exception:
            return None
        seq = payload.get("seq")
        if not isinstance(seq, int):
            return None
        self.replayed[seq] = payload
        return seq

    def compare(self, ignore: Iterable[str] = ()) -> Comparison:
        return compare(self.recording.verdicts(), self.replayed, ignore)
