"""One session, one directory, and the check that says what it cannot be used for.

Three artifacts kept together by hand are three artifacts that get separated, and the
separation is found months later on the day the missing half was needed. These pin the
properties that make one directory a record instead of a pile:

  1. **A manifest exists from the first frame**, not from the last. A session that ends
     in a flat battery still leaves a directory that says what it was.
  2. **The manifest indexes the stream and never contradicts it.** Counts come off
     `Recording.summary()`, so `session.json` and `stream.jsonl` cannot drift.
  3. **Completeness is named against what it costs.** "Incomplete" is not actionable;
     "this cannot be re-executed in a simulator" is, while the robot is still there.

Pure: no ROS, no filesystem, no clock -- `now` is injected, as everywhere else here.
"""

from __future__ import annotations

from skill_monitor.core import api, session


def a_session(**over):
    """A complete manifest, which each test then breaks in exactly one way."""
    doc = session.new("g1_run1", host="jetson", note="dead end on purpose",
                      now=lambda: 1000.0)
    doc = session.describe_run(
        doc, {"adapter": "real_g1", "tick_hz": 1.0}, {"skill_name": "G1Nav"})
    doc = session.finalize(
        doc,
        frames={api.ADAPTER: 1, api.MANIFEST: 1, api.TICK: 40,
                api.OBSERVATION: 40, api.VERDICT: 40},
        bag={"topics": ["/t265/odom/sample", "/filtered_map"], "scene": ["/filtered_map"]},
        verdict={"verdict": "VIOLATED", "terminal": "nav_stuck", "seq": 40},
        now=lambda: 1042.0)
    return doc | over


# =============================================================================
# The manifest exists before the session does
# =============================================================================

def test_a_manifest_is_written_at_the_start_and_says_it_did_not_finish():
    """The battery dies, ssh drops, someone trips over the robot. A bundle that only
    existed once it was finished would leave nothing at all; this leaves a directory
    that names itself and admits what is missing."""
    doc = session.new("g1_run1", host="jetson", now=lambda: 1000.0)

    assert doc["session"] == "g1_run1" and doc["started"] == 1000.0
    assert doc["ended"] is None
    assert session.duration_s(doc) is None
    assert "DID NOT FINISH" in session.report(doc)


def test_the_run_describes_itself_from_the_latched_frames():
    """Which robot, which skill, what tick rate -- the question asked of a directory
    before anything inside it is opened. Copied onto the manifest so `session.json`
    alone answers it."""
    doc = session.describe_run(session.new("s", now=lambda: 0.0),
                               {"adapter": "real_g1", "tick_hz": 1.0},
                               {"skill_name": "G1Nav"})

    assert (doc["adapter"], doc["tick_hz"], doc["skill"]) == ("real_g1", 1.0, "G1Nav")


def test_frames_that_never_arrived_leave_the_fields_alone():
    """No evaluator, no adapter frame. The manifest must say `null`, not invent a
    plausible robot name -- a bundle that names a schema it never saw is worse than one
    that admits it has none."""
    doc = session.describe_run(session.new("s", now=lambda: 0.0), None, None)

    assert doc["adapter"] is None and doc["skill"] is None


def test_the_end_records_how_the_episode_came_out():
    doc = a_session()

    assert session.duration_s(doc) == 42.0
    assert doc["verdict"] == {"verdict": "VIOLATED", "terminal": "nav_stuck", "seq": 40}
    assert "VIOLATED" in session.report(doc)


# =============================================================================
# What the bundle cannot do
# =============================================================================

def test_a_complete_session_has_no_problems():
    assert session.problems(a_session()) == []
    assert "Complete" in session.report(a_session())


def test_no_adapter_frame_means_the_bundle_cannot_explain_its_own_sensor_keys():
    """The evaluator was not running. Every number in the stream is then unlabelled --
    `min_range` is a float with no declared meaning, no unit and no source."""
    doc = a_session()
    doc["frames"] = {k: v for k, v in doc["frames"].items() if k != api.ADAPTER}

    assert any("sensor schema" in p for p in session.problems(doc))


def test_no_verdicts_means_a_replay_can_only_produce_them_never_check_them():
    """The monitor was down, or never loaded a spec. `play --diff` then has nothing to
    diff against, which is the acceptance test quietly not happening."""
    doc = a_session()
    doc["frames"] = {k: v for k, v in doc["frames"].items() if k != api.VERDICT}
    found = session.problems(doc)

    assert any("compare a replay against" in p for p in found)


def test_no_bag_is_reported_before_the_missing_scene_is():
    """One finding, not two. A session with no bag at all has no scene either, and
    saying both would make the report read as twice the damage."""
    doc = a_session()
    doc["bag"] = {"topics": [], "scene": []}
    found = session.problems(doc)

    assert any("no sensor bag" in p for p in found)
    assert not any("re-executed in a simulator" in p for p in found)


def test_a_bag_without_the_scene_is_the_silent_one_and_it_is_named():
    """The failure this whole check exists for. Everything looks recorded -- there is a
    bag, it has topics, the stream is complete -- and the world the episode happened in
    is not in it. Discovered months later, when the arena cannot be built."""
    doc = a_session()
    doc["bag"] = {"topics": ["/t265/odom/sample"], "scene": []}

    assert any("re-executed in a simulator" in p for p in session.problems(doc))


def test_an_empty_frame_count_is_as_missing_as_an_absent_topic():
    """A subscription that matched and then received nothing writes `{topic: 0}`. Zero
    frames is not evidence of a recording."""
    doc = a_session()
    doc["frames"] = doc["frames"] | {api.OBSERVATION: 0}

    assert any("no stream to replay" in p for p in session.problems(doc))


def test_the_report_says_the_findings_are_unfixable_after_you_leave():
    """The one sentence that decides whether a second run happens now or never. It is
    in the report rather than in the runbook because this is what an operator reads
    while the robot is still standing there."""
    doc = a_session()
    doc["bag"] = {"topics": [], "scene": []}
    text = session.report(doc)

    assert "INCOMPLETE" in text
    assert "walk away" in text


# =============================================================================
# The pieces a reader has to find
# =============================================================================

def test_the_four_names_in_a_bundle_are_constants():
    """A reader written next year looks them up here. A typo in one is a session
    recording to a file nothing will ever open."""
    assert (session.MANIFEST, session.STREAM, session.BAG, session.NOTES) == (
        "session.json", "stream.jsonl", "sensors", "notes.md")


def test_the_bag_command_is_built_in_one_place():
    argv = session.bag_command("g1_run1", ["/a", "/b"], "/data/g1_run1/sensors")

    assert argv == ["ros2", "bag", "record", "-o", "/data/g1_run1/sensors", "/a", "/b"]


def test_a_manifest_round_trips_through_json():
    """It is written three times per session and read by things that are not this
    package. Anything unserialisable in it would fail at the end of a run, which is the
    worst possible moment."""
    import json

    assert json.loads(json.dumps(a_session())) == a_session()
