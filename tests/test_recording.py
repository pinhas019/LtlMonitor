"""An episode written down, replayed, and compared.

P9 names verdict equality between two replays of one episode as *the* acceptance test
for the hardware-agnosticism claim. Nothing recorded the episode, so nothing could be
compared. These pin the three properties that make the comparison mean something:

  1. **Only inputs are replayed.** A player that republished `/monitor/verdict` would
     compare the recording against itself and always pass.
  2. **A missing verdict is not a differing verdict.** A monitor that stopped stepping
     must read as "no verdict for these ticks", not as a hundred field differences.
  3. **The recorded order survives.** A command between two ticks changes every verdict
     after it, so replaying by `seq` and hanging commands off the nearest tick would
     replay a different episode.

Pure: no graph, no socket, no file. `Recorder` writes through an injected callable and
`Player` publishes through one.
"""

from __future__ import annotations

import json

from skill_monitor.core import api
from skill_monitor.core.recording import (INPUTS, OUTPUTS, RECORDED, Player, Recorder,
                                          Recording, Relay, bag_topics, compare, diff)


def a_verdict(seq=1, verdict="SATISFIED", action="CONTINUE", **extra):
    return {"version": 1, "seq": seq, "t": float(seq), "step": seq,
            "skill_name": "nav", "phase": "cruise", "phase_index": 1,
            "verdict": verdict, "formulas": [], "failure_modes": [],
            "risk": {}, "intervention": {"action": action}, "terminal": None,
            "missed_ticks": 0} | extra


def a_line(topic, payload, wall=1.0):
    return json.dumps({"wall": wall, "topic": topic, "payload": payload})


def a_recording(*frames):
    return Recording.parse(a_line(t, p, w) for w, t, p in frames)


# =============================================================================
# The format
# =============================================================================

def test_a_recorder_writes_one_json_line_per_frame():
    lines = []
    rec = Recorder(lines.append, now=lambda: 10.5)
    assert rec.on(api.TICK, json.dumps({"seq": 1})) is True

    assert len(lines) == 1 and lines[0].endswith("\n")
    frame = json.loads(lines[0])
    assert frame == {"wall": 10.5, "topic": api.TICK, "payload": {"seq": 1}}


def test_a_frame_that_is_not_json_is_dropped_at_write_time_and_counted():
    """Not written and then found broken on replay months later. `dropped` is what a
    recording session prints, so a stack emitting garbage says so while it is running."""
    lines = []
    rec = Recorder(lines.append, now=lambda: 0.0)

    assert rec.on(api.TICK, "not json") is False
    assert rec.on(api.TICK, "[1, 2]") is False, "a JSON array is not a frame"

    assert lines == []
    assert (rec.written, rec.dropped) == (0, 2)


def test_a_truncated_recording_is_read_up_to_the_cut():
    """A power cut mid-write leaves a partial last line. Refusing the whole file would
    throw away the part that explains what happened before the cut."""
    text = [a_line(api.TICK, {"seq": 1}), a_line(api.TICK, {"seq": 2})[:34]]
    recording = Recording.parse(text)

    assert recording.ticks == 1
    assert recording.unreadable == 1


# =============================================================================
# Inputs and outputs
# =============================================================================

def test_every_recorded_topic_is_an_input_or_an_output_and_not_both():
    assert set(INPUTS).isdisjoint(OUTPUTS)
    assert set(RECORDED) == set(INPUTS) | set(OUTPUTS)
    assert set(RECORDED) <= api.TOPICS, "a recorded topic that is not on the contract"


def test_the_verdict_is_never_replayed():
    """The regression that would make every comparison vacuous."""
    assert api.VERDICT not in INPUTS
    published = []
    recording = a_recording((1.0, api.VERDICT, a_verdict()),
                            (1.0, api.TICK, {"seq": 1}))
    player = Player(recording, lambda t, x: published.append(t))
    while player.step():
        pass

    assert published == [api.TICK]


def test_the_manifest_is_never_replayed():
    """The monitor publishes it from the spec it loaded. A player that published one too
    would put a second producer on a latched topic and the console would show a race."""
    assert api.MANIFEST not in INPUTS
    assert api.MANIFEST in OUTPUTS


def test_the_adapter_is_replayed_because_no_evaluator_runs_during_one():
    assert api.ADAPTER in INPUTS


# =============================================================================
# Playback
# =============================================================================

def test_playback_follows_the_recorded_order_not_the_sequence_number():
    """A command between two ticks changes the verdicts after it and not before."""
    recording = a_recording(
        (1.0, api.TICK, {"seq": 1}),
        (1.5, api.COMMAND, {"command": "pause"}),
        (2.0, api.TICK, {"seq": 2}),
    )
    seen = []
    player = Player(recording, lambda topic, text: seen.append(topic))
    while player.step():
        pass

    assert seen == [api.TICK, api.COMMAND, api.TICK]


def test_a_player_publishes_the_payload_verbatim():
    """Including `t`. The replay's time base is the recorded one -- that is what makes
    the tick count independent of how fast the replay ran."""
    payload = {"seq": 7, "t": 7.0, "tick_hz": 1.0, "t0": 1700.0, "mode": "wall"}
    sent = {}
    player = Player(a_recording((1.0, api.TICK, payload)),
                    lambda topic, text: sent.update({topic: json.loads(text)}))
    player.step()

    assert sent[api.TICK] == payload


def test_feed_indexes_replayed_verdicts_by_seq_and_ignores_anything_else():
    player = Player(a_recording(), lambda t, x: None)

    assert player.feed(json.dumps(a_verdict(seq=3))) == 3
    assert player.feed("not json") is None
    assert player.feed(json.dumps({"seq": "three"})) is None
    assert list(player.replayed) == [3]


# =============================================================================
# The comparison
# =============================================================================

def test_an_identical_replay_is_equal():
    recorded = {1: a_verdict(1), 2: a_verdict(2)}
    result = compare(recorded, {1: a_verdict(1), 2: a_verdict(2)})

    assert result.equal
    assert result.matched == [1, 2]


def test_a_changed_rung_is_reported_by_path():
    result = compare({1: a_verdict(1)}, {1: a_verdict(1, action="HALT")})

    assert not result.equal
    assert result.differed[1] == ["intervention.action: 'CONTINUE' -> 'HALT'"]


def test_a_tick_with_no_replayed_verdict_is_missing_not_differing():
    """Property 2. A monitor that stopped stepping must not read as a hundred field
    differences on every tick after it stopped."""
    result = compare({1: a_verdict(1), 2: a_verdict(2)}, {1: a_verdict(1)})

    assert result.missing == [2]
    assert result.differed == {}
    assert "no verdict replayed for ticks: [2]" in result.report()


def test_a_verdict_for_a_tick_that_was_never_recorded_is_reported_too():
    result = compare({1: a_verdict(1)}, {1: a_verdict(1), 9: a_verdict(9)})

    assert result.extra == [9]
    assert not result.equal


def test_nothing_is_ignored_by_default_including_the_time():
    """A `t` that moved means the replay invented a clock, which is the bug the whole
    comparison exists to catch."""
    assert diff(a_verdict(1), a_verdict(1) | {"t": 99.0}) == ["t: 1.0 -> 99.0"]


def test_ignore_takes_a_whole_subtree():
    a = a_verdict(1, risk={"warn": True, "stale_sources": ["odom"]})
    b = a_verdict(1, risk={"warn": False, "stale_sources": []})

    assert diff(a, b, ignore=["risk"]) == []


def test_a_reordered_formula_list_reads_as_a_difference():
    """Indexed, not set-compared. The order is the automaton's, so a move is a finding."""
    a = a_verdict(1, formulas=[{"name": "x"}, {"name": "y"}])
    b = a_verdict(1, formulas=[{"name": "y"}, {"name": "x"}])

    assert diff(a, b) == ["formulas[0].name: 'x' -> 'y'",
                          "formulas[1].name: 'y' -> 'x'"]


def test_an_added_field_is_a_difference_against_absent():
    assert diff({"a": 1}, {"a": 1, "b": 2}) == ["b: '<absent>' -> 2"]


# =============================================================================
# The geometry half
# =============================================================================

def test_bag_topics_comes_off_the_adapter_so_any_robot_works():
    """Named nowhere in this file. A navigation stack and an arm produce different
    lists from the same call, which is the same property that lets the console render
    a robot it has never seen."""
    adapter = {"sources": [{"id": "odom", "topic": "/t265/odom/sample"},
                           {"id": "cloud", "topic": "/depth/points"},
                           {"id": "dup", "topic": "/t265/odom/sample"}]}

    assert bag_topics(adapter) == ["/t265/odom/sample", "/depth/points"]


def test_bag_topics_of_nothing_is_nothing_rather_than_a_guess():
    assert bag_topics(None) == []
    assert bag_topics({}) == []


# =============================================================================
# Reading a recording back
# =============================================================================

def test_the_latched_frames_are_the_last_ones_seen():
    recording = a_recording((1.0, api.ADAPTER, {"adapter": "sim"}),
                            (2.0, api.ADAPTER, {"adapter": "real_g1"}))

    assert recording.latest(api.ADAPTER) == {"adapter": "real_g1"}
    assert recording.latest(api.MANIFEST) is None


def test_a_redelivered_verdict_does_not_become_a_second_verdict_for_one_tick():
    recording = a_recording((1.0, api.VERDICT, a_verdict(1)),
                            (1.1, api.VERDICT, a_verdict(1, verdict="VIOLATED")))

    assert recording.verdicts()[1]["verdict"] == "VIOLATED"
    assert len(recording.verdicts()) == 1


def test_summary_counts_what_is_there():
    recording = a_recording((1.0, api.TICK, {"seq": 1}),
                            (2.0, api.OBSERVATION, {"seq": 1}),
                            (3.0, api.VERDICT, a_verdict(1)))
    summary = recording.summary()

    assert summary["frames"] == 3
    assert summary["seconds"] == 2.0
    assert summary["topics"][api.TICK] == 1


# =============================================================================
# The same stream, live, on another machine
# =============================================================================

def relayed(*lines):
    """A relay fed those lines, and what it published, in order."""
    sent = []
    relay = Relay(lambda topic, text: sent.append((topic, json.loads(text))))
    for line in lines:
        relay.on_line(line)
    return relay, sent


def test_a_relay_publishes_the_inputs_as_they_arrive():
    """No queue, no wait, no rate: the robot's clock already paced this stream and the
    tick is inside it. The pipe is the pacing."""
    relay, sent = relayed(a_line(api.ADAPTER, {"adapter": "real_g1"}),
                          a_line(api.TICK, {"seq": 1, "t": 1.0}),
                          a_line(api.OBSERVATION, {"seq": 1}))

    assert [t for t, _ in sent] == [api.ADAPTER, api.TICK, api.OBSERVATION]
    assert relay.published == 3


def test_a_relay_never_republishes_the_robots_verdict():
    """Sharper than the same rule in `Player`. The monitor on this side is computing its
    own verdicts, so a relayed one would put two producers on `/monitor/verdict` and the
    console would show whichever landed last -- the robot's answer or this machine's,
    with nothing saying which."""
    relay, sent = relayed(a_line(api.VERDICT, a_verdict(1)),
                          a_line(api.MANIFEST, {"skill_name": "nav"}),
                          a_line(api.TICK, {"seq": 1}))

    assert [t for t, _ in sent] == [api.TICK]
    assert relay.skipped == 2


def test_the_payload_crosses_the_link_verbatim():
    """Including `t`. The far side's monitor advances on the tick inside the
    observation, so a relay that restamped anything would be a second clock."""
    payload = {"seq": 7, "t": 7.0, "tick_hz": 1.0, "t0": 1700.0, "mode": "wall"}
    _, sent = relayed(a_line(api.TICK, payload))

    assert sent == [(api.TICK, payload)]


def test_a_torn_line_is_counted_and_the_stream_carries_on():
    """A dropped ssh connection or a full pipe truncates mid-line. That costs one frame;
    a relay that raised there would cost the rest of the episode."""
    torn = a_line(api.TICK, {"seq": 9})[:30]           # cut where the pipe cut it
    relay, sent = relayed(a_line(api.TICK, {"seq": 1}),
                          torn,
                          a_line(api.TICK, {"seq": 2}))

    assert [p["seq"] for _, p in sent] == [1, 2]
    assert relay.unreadable == 1


def test_blank_keepalive_lines_are_not_unreadable_frames():
    """Blank lines survive most pipes and mean nothing. Counting them as damage would
    make `unreadable` useless as the number that says the link is failing."""
    relay, _ = relayed("", "\n", "   \n")

    assert (relay.unreadable, relay.published, relay.skipped) == (0, 0, 0)


def test_a_frame_a_recording_accepts_is_a_frame_a_relay_accepts():
    """One parser for both, so a live episode and the same episode read back off disk
    are the same frames -- which is what makes `record | relay` and `record` then `play`
    two spellings of one thing rather than two formats."""
    lines = [a_line(api.TICK, {"seq": 1}), "not json", a_line(api.OBSERVATION, {"seq": 1})]
    relay, sent = relayed(*lines)
    recording = Recording.parse(lines)

    assert [f["topic"] for f in recording.inputs()] == [t for t, _ in sent]
    assert recording.unreadable == relay.unreadable == 1
