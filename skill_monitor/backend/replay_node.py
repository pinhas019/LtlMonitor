#!/usr/bin/env python3
"""Write an episode down; run the monitor over it again; say whether it agreed.

    # while the robot runs -- ONE command, ONE directory with everything in it
    python3 -m skill_monitor.backend.replay_node session g1_run1 --note "dead end"

    # before walking away from the robot: what can this bundle NOT be used for?
    python3 -m skill_monitor.backend.replay_node verify g1_run1

    # afterwards, with the monitor up and the clock and evaluator DOWN
    python3 -m skill_monitor.backend.replay_node play g1_run1 --diff

    # or LIVE, with the evaluator on the robot and the monitor on another machine
    ssh robot '... replay_node record -' | python3 -m skill_monitor.backend.replay_node relay

`session` is the one to reach for: it is `record` plus the `ros2 bag record` of the
sensors and the scene, into a single self-describing directory, with a manifest saying
what ran against what. See `core/session.py` for why one directory and not three files.
Every other subcommand takes that directory wherever it takes a `.jsonl`.

`relay` is the same format arriving as it happens instead of being read back off disk,
which is what lets the monitor run a network away from the robot when DDS cannot cross
the link between them. See `core/recording.py`'s `Relay`.

The rule is `core/recording.py`'s: replay the inputs, compare the outputs. The player
publishes the recorded ticks, so the replay's time base **is** the recorded one -- no
clock runs during a replay, which is why the tick count cannot depend on how fast the
replay went. `--diff` fails the process when the verdicts do not match, so this is
runnable from CI over a stored episode.

**The clock and the evaluator must be stopped for `play`.** Both are input producers,
and two producers on `/monitor/tick` interleave into a stream that is neither run. The
player says so on startup rather than discovering it in the diff, by counting the
publishers it is about to compete with.

Everything hard is in `core/recording.py` and tested without a graph. What is here is
the wiring: a subscription per topic, a publisher per topic, and a wait.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import signal
import subprocess
import sys
import time

from skill_monitor.core import api, session
from skill_monitor.core.recording import (RECORDED, INPUTS, Player, Recorder,
                                          Recording, Relay, bag_topics)

#: How long `play` waits for the verdict of an observation before moving on.
#:
#: A wait, and not a sleep between frames: the monitor answers an observation in
#: microseconds, so this is reached only when it is not answering at all -- it is down,
#: it is paused, or it never loaded a spec. Moving on rather than aborting is what makes
#: the report say "no verdict replayed for ticks [4, 5, 6...]", which names the failure
#: better than a traceback at tick 4 would.
DEFAULT_TIMEOUT_S = 2.0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="mode", required=True)

    rec = sub.add_parser("record",
                         help="subscribe to every recorded topic and append JSON Lines")
    rec.add_argument("path", help="a file, or '-' for stdout so the stream can be piped")
    rec.add_argument("--append", action="store_true",
                     help="add to an existing file instead of truncating it")

    ses = sub.add_parser(
        "session",
        help="ONE directory holding the whole session: stream, sensors, scene, manifest")
    ses.add_argument("path", help="the bundle directory to create, e.g. /data/g1_run1")
    ses.add_argument("--note", default="", help="what this run was, in the operator's "
                                                "own words; it lands in session.json")
    ses.add_argument("--no-bag", action="store_true",
                     help="the monitor stream only. The session is then not "
                          "re-executable in a simulator, and says so.")
    ses.add_argument("--adapter-timeout", type=float, default=10.0,
                     help="seconds to wait for the latched adapter frame that names "
                          "the topics to bag")
    ses.add_argument("--append", action="store_true",
                     help="add to an existing bundle instead of refusing it")

    verify = sub.add_parser(
        "verify", help="what a bundle cannot be used for -- run it before walking away")
    verify.add_argument("path", help="a session bundle directory")

    relay = sub.add_parser(
        "relay", help="publish a stream of recorded frames onto THIS machine's graph")
    relay.add_argument("path", nargs="?", default="-",
                       help="a file or fifo, or '-' (the default) for stdin")

    play = sub.add_parser("play", help="republish the recorded inputs to a live monitor")
    play.add_argument("path")
    play.add_argument("--rate", type=float, default=0.0,
                      help="frames per second; 0 (the default) is as fast as the "
                           "monitor answers, which is what a determinism check wants")
    play.add_argument("--diff", action="store_true",
                      help="compare replayed verdicts with recorded ones; exit 1 on any "
                           "difference")
    play.add_argument("--ignore", action="append", default=[], metavar="PATH",
                      help="a verdict path to exclude from --diff, e.g. risk.warn. "
                           "Repeatable. Nothing is ignored unless you say so.")
    play.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)

    topics = sub.add_parser("topics", help="the sensor topics this run's adapter declared")
    topics.add_argument("path")
    topics.add_argument("--scene", action="store_true",
                        help="also the descriptor's scene topics -- terrain, planner "
                             "paths, tf. What re-executing the episode in a simulator "
                             "needs and a monitor replay does not.")

    info = sub.add_parser("info", help="what is in a recording")
    info.add_argument("path")
    return p


def stream_of(path: str) -> str:
    """The stream inside a session bundle, or the path as given.

    So that every subcommand takes `g1_run1/` -- the one thing the operator copied off
    the robot -- as readily as `g1_run1/stream.jsonl`. A bundle is the unit now; asking
    someone to remember which file inside it holds the frames would put the pile back.
    """
    inner = pathlib.Path(path) / session.STREAM
    return str(inner) if inner.exists() else path


def _load(path: str) -> Recording:
    with open(stream_of(path), encoding="utf-8") as fh:
        return Recording.parse(fh)


# =============================================================================
# record
# =============================================================================

def run_record(args) -> int:
    import rclpy
    from std_msgs.msg import String
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                           ReliabilityPolicy)

    latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)

    # '-' is stdout, and stdout is what makes the stream pipeable -- `record -` on the
    # robot through ssh into `relay -` on the operator's machine. Line buffering is what
    # makes it a *live* stream rather than a file that arrives in 8 KB lumps; ROS logging
    # goes to stderr, so nothing else lands in the pipe.
    to_stdout = args.path == "-"
    if to_stdout:
        fh = open(sys.stdout.fileno(), "w", buffering=1, encoding="utf-8", closefd=False)
    else:
        fh = open(args.path, "a" if args.append else "w", buffering=1, encoding="utf-8")
    recorder = Recorder(fh.write)

    rclpy.init()
    node = rclpy.create_node("skill_monitor_recorder")
    for topic in RECORDED:
        qos = latched if topic in api.LATCHED_TOPICS else 10
        node.create_subscription(
            String, topic,
            (lambda t: (lambda msg: recorder.on(t, msg.data)))(topic), qos)
    node.get_logger().info(f"recording {len(RECORDED)} topics to {args.path}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        fh.close()
        node.destroy_node()
        rclpy.try_shutdown()
    print(f"{recorder.written} frames written, {recorder.dropped} dropped", file=sys.stderr)
    return 0


# =============================================================================
# play
# =============================================================================

def run_play(args) -> int:
    recording = _load(args.path)
    if not recording.frames:
        print(f"{args.path}: nothing to replay", file=sys.stderr)
        return 1

    import rclpy
    from std_msgs.msg import String
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                           ReliabilityPolicy)

    latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)

    rclpy.init()
    node = rclpy.create_node("skill_monitor_player")
    log = node.get_logger()

    pubs = {t: node.create_publisher(
        String, t, latched if t in api.LATCHED_TOPICS else 10) for t in INPUTS}

    player = Player(recording, lambda topic, text: pubs[topic].publish(String(data=text)))
    node.create_subscription(String, api.VERDICT,
                             lambda msg: player.feed(msg.data), 10)

    # Discovery is not instant, and a player that published its first tick before the
    # monitor's subscription matched would replay an episode the monitor never saw the
    # start of. Wait for a subscriber on the one topic that steps it.
    deadline = time.monotonic() + 5.0
    while node.count_subscribers(api.OBSERVATION) == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
    if node.count_subscribers(api.OBSERVATION) == 0:
        log.warn(f"nothing is subscribed to {api.OBSERVATION}; is the monitor running?")

    # Two producers on an input topic is not a replay of anything. Named, not fatal:
    # the operator may be deliberately replaying alongside a live run.
    for topic in (api.TICK, api.OBSERVATION):
        others = node.count_publishers(topic) - 1
        if others > 0:
            log.warn(f"{others} other publisher(s) on {topic} -- stop the clock and the "
                     f"evaluator, or this replay is interleaved with a live stream")

    period = 1.0 / args.rate if args.rate > 0 else 0.0
    while rclpy.ok():
        frame = player.step()
        if frame is None:
            break
        if frame["topic"] == api.OBSERVATION:
            seq = frame["payload"].get("seq")
            end = time.monotonic() + args.timeout
            while rclpy.ok() and seq not in player.replayed and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=0.01)
        else:
            rclpy.spin_once(node, timeout_sec=0.0)
        if period:
            time.sleep(period)

    # Anything still in flight when the last observation was answered.
    end = time.monotonic() + 0.25
    while rclpy.ok() and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.01)

    node.destroy_node()
    rclpy.try_shutdown()

    print(f"replayed {player.published} input frames from {args.path}", file=sys.stderr)
    if not args.diff:
        return 0
    result = player.compare(args.ignore)
    print(result.report(), file=sys.stderr)
    return 0 if result.equal else 1


# =============================================================================
# session -- one directory, everything in it
# =============================================================================

def run_session(args) -> int:
    """One command, one artifact. The stream, the sensors, the scene and the manifest.

    This is `record` plus a `ros2 bag record` it launches itself, into one directory,
    with a manifest written before the first frame and closed after the last. The
    reason it is one process and not two commands in two terminals is that two
    artifacts kept together by hand are two artifacts that get separated -- and the
    separation is discovered months later, on the day the missing half was needed.

    The bag's topic list is not known until the latched `/monitor/adapter` frame
    arrives, because it is READ OFF that frame: sources plus the descriptor's scene. So
    the bag starts a moment after the stream does, and if no adapter ever arrives the
    session says so and records the stream alone rather than guessing a topic list.
    """
    import rclpy
    from std_msgs.msg import String
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                           ReliabilityPolicy)

    latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)

    root = pathlib.Path(args.path)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / session.MANIFEST
    if manifest_path.exists() and not args.append:
        # Refused, not merged. Two runs in one bundle is a bundle whose verdicts belong
        # to two episodes, and the `--diff` that later compares them has no way to know.
        print(f"{manifest_path} exists: {root} already holds a session", file=sys.stderr)
        return 2

    doc = session.new(root.name, host=platform.node(), note=args.note)
    _write_manifest(manifest_path, doc)

    stream_path = root / session.STREAM
    fh = open(stream_path, "a" if args.append else "w", buffering=1, encoding="utf-8")
    recorder = Recorder(fh.write)
    frames: list[str] = []

    rclpy.init()
    node = rclpy.create_node("skill_monitor_session")
    log = node.get_logger()
    for topic in RECORDED:
        qos = latched if topic in api.LATCHED_TOPICS else 10
        node.create_subscription(
            String, topic,
            (lambda t: (lambda msg: (recorder.on(t, msg.data), frames.append(t))))(topic),
            qos)

    # The latched frames arrive on subscription, so this is a short wait and not a poll.
    # Spun rather than slept: the callbacks above are what deliver them.
    deadline = time.monotonic() + args.adapter_timeout
    while rclpy.ok() and api.ADAPTER not in frames and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)

    bag = None
    adapter = _latest_frame(stream_path, api.ADAPTER)
    if args.no_bag:
        log.info("--no-bag: recording the monitor stream only")
    elif adapter is None:
        log.error(f"no {api.ADAPTER} in {args.adapter_timeout}s -- is the evaluator "
                  f"running? Recording the stream alone; this session will NOT be "
                  f"re-executable in a simulator.")
    else:
        topics = bag_topics(adapter, scene=True)
        scene = [t for t in (adapter.get("scene") or []) if t in topics]
        log.info(f"bagging {len(topics)} topic(s), {len(scene)} of them scene")
        bag = subprocess.Popen(session.bag_command(root.name, topics, str(root / session.BAG)),
                               stdout=subprocess.DEVNULL)
        doc = session.describe_run(doc, adapter, _latest_frame(stream_path, api.MANIFEST))
        doc["bag"] = {"topics": topics, "scene": scene}
        _write_manifest(manifest_path, doc)

    log.info(f"session {root.name}: recording. Ctrl-C to close it.")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if bag is not None:
            # SIGINT and not kill: rosbag2 closes its database on interrupt and leaves a
            # bag `ros2 bag play` refuses to open if it does not.
            bag.send_signal(signal.SIGINT)
            try:
                bag.wait(timeout=20.0)
            except subprocess.TimeoutExpired:
                log.error("the bag did not close in 20s; killing it. It may be unreadable.")
                bag.kill()
        fh.close()
        node.destroy_node()
        rclpy.try_shutdown()

    recording = _load(str(stream_path))
    verdicts = recording.verdicts()
    doc = session.describe_run(doc, recording.latest(api.ADAPTER),
                               recording.latest(api.MANIFEST))
    doc = session.finalize(doc, frames=recording.summary()["topics"],
                           verdict=verdicts[max(verdicts)] if verdicts else None)
    _write_manifest(manifest_path, doc)

    print("", file=sys.stderr)
    print(session.report(doc), file=sys.stderr)
    return 1 if session.problems(doc) else 0


def _write_manifest(path: pathlib.Path, doc: dict) -> None:
    """Rewritten in full at each of the three moments it changes -- start, adapter,
    end. Small enough that atomicity is not worth a temp file, and rewriting means a
    session killed between two of them still leaves a manifest that parses."""
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _latest_frame(path: pathlib.Path, topic: str) -> dict | None:
    """The latched frame, read back out of the stream that was just written to.

    Out of the file rather than held in a variable beside the recorder: the file is
    what the bundle ships, so reading it is also a check that what was written is what
    a reader will get.
    """
    if not path.exists():
        return None
    return _load(str(path)).latest(topic)


def run_verify(args) -> int:
    """What this bundle cannot be used for. Exit 1 if anything.

    Its whole value is being run while the robot is still standing there.
    """
    root = pathlib.Path(args.path)
    manifest_path = root / session.MANIFEST
    if not manifest_path.exists():
        print(f"{root}: no {session.MANIFEST}, so this is not a session bundle",
              file=sys.stderr)
        return 2
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(session.report(doc))
    return 1 if session.problems(doc) else 0


# =============================================================================
# relay
# =============================================================================

def run_relay(args) -> int:
    """A live stream in, this machine's graph out.

    The mirror image of `play`, and the differences are all one difference: this is not
    a replay of a finished episode, it is the same episode arriving as it happens. So
    there is no `--rate` (the robot's clock already paced it and the tick is inside the
    stream), no `--diff` (there is nothing to compare against yet -- record the verdicts
    on this side and diff later), and no waiting for the monitor to answer each
    observation. Frames go out as they arrive, and the pipe is the pacing.

    It publishes and subscribes to nothing, so it never spins an executor: rclpy
    publishing does not need one, and a blocking read on the pipe is exactly the right
    thing to be doing between frames.
    """
    import rclpy
    from std_msgs.msg import String
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                           ReliabilityPolicy)

    latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE,
                         history=HistoryPolicy.KEEP_LAST)

    rclpy.init()
    node = rclpy.create_node("skill_monitor_relay")
    log = node.get_logger()
    pubs = {t: node.create_publisher(
        String, t, latched if t in api.LATCHED_TOPICS else 10) for t in INPUTS}
    relay = Relay(lambda topic, text: pubs[topic].publish(String(data=text)))

    # The same warning `play` gives, for the same reason and one more. A local clock or
    # evaluator would interleave its own ticks with the robot's, and the tick index the
    # observation carries is the robot's -- so the monitor would be stepped twice per
    # remote tick by two time bases. On the server tier the clock ships `--paused`
    # precisely so this cannot happen; if it warns here, something un-paused it.
    for topic in (api.TICK, api.OBSERVATION):
        others = node.count_publishers(topic) - 1
        if others > 0:
            log.warn(f"{others} other publisher(s) on {topic} -- a local clock or "
                     f"evaluator is running, and this relay is interleaving with it")

    stream = sys.stdin if args.path == "-" else open(args.path, encoding="utf-8")
    log.info(f"relaying {len(INPUTS)} input topic(s) from "
             f"{'stdin' if args.path == '-' else args.path}")
    try:
        for line in stream:
            if not rclpy.ok():
                break
            relay.on_line(line)
    except KeyboardInterrupt:
        pass
    finally:
        if stream is not sys.stdin:
            stream.close()
        node.destroy_node()
        rclpy.try_shutdown()

    # An empty relay is the common failure and it is silent otherwise: the ssh command
    # died, or the robot side was never recording. Say which number was zero.
    print(f"relayed {relay.published} frame(s); skipped {relay.skipped} output frame(s), "
          f"{relay.unreadable} unreadable", file=sys.stderr)
    return 0 if relay.published else 1


# =============================================================================
# topics, info -- no ROS
# =============================================================================

def run_topics(args) -> int:
    from skill_monitor.core.recording import bag_topics
    adapter = _load(args.path).latest(api.ADAPTER)
    if adapter is None:
        print(f"{args.path}: no {api.ADAPTER} frame, so the robot's topics are unknown",
              file=sys.stderr)
        return 1
    for topic in bag_topics(adapter, scene=args.scene):
        print(topic)
    return 0


def run_info(args) -> int:
    recording = _load(args.path)
    print(json.dumps(recording.summary(), indent=2))
    adapter = recording.latest(api.ADAPTER)
    if adapter:
        print(f"adapter: {adapter.get('adapter')} @ {adapter.get('tick_hz')} Hz")
    manifest = recording.latest(api.MANIFEST)
    if manifest:
        print(f"skill:   {manifest.get('skill_name')}")
    verdicts = recording.verdicts()
    if verdicts:
        last = verdicts[max(verdicts)]
        print(f"ended:   {last.get('verdict')} terminal={last.get('terminal')} "
              f"at tick {last.get('seq')}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"record": run_record, "session": run_session, "verify": run_verify,
            "play": run_play, "relay": run_relay,
            "topics": run_topics, "info": run_info}[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
