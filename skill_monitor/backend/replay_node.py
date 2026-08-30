#!/usr/bin/env python3
"""Write an episode down; run the monitor over it again; say whether it agreed.

    # while the robot runs
    python3 -m skill_monitor.backend.replay_node record run.jsonl

    # afterwards, with the monitor up and the clock and evaluator DOWN
    python3 -m skill_monitor.backend.replay_node play run.jsonl --diff

    # and, for the geometry rviz2 and Isaac replay from
    ros2 bag record -o run.bag $(python3 -m skill_monitor.backend.replay_node topics run.jsonl)

    # or LIVE, with the evaluator on the robot and the monitor on another machine
    ssh robot '... replay_node record -' | python3 -m skill_monitor.backend.replay_node relay

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
import sys
import time

from skill_monitor.core import api
from skill_monitor.core.recording import (RECORDED, INPUTS, Player, Recorder,
                                          Recording, Relay)

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

    info = sub.add_parser("info", help="what is in a recording")
    info.add_argument("path")
    return p


def _load(path: str) -> Recording:
    with open(path, encoding="utf-8") as fh:
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
    for topic in bag_topics(adapter):
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
    return {"record": run_record, "play": run_play, "relay": run_relay,
            "topics": run_topics, "info": run_info}[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
