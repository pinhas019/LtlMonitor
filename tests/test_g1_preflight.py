"""The preflight's parsing and its verdict, with no ROS and no robot.

Every interesting case here is one a robot produces at the worst moment -- a renamed
topic, a topic advertised by a publisher that then sends nothing, a whole graph on the
wrong domain -- and none of them is reproducible on demand beside a real G1. They are
pure functions over text, so they are checkable here instead.

`tools/` is not a package, so the import below adds it to the path the same way
`test_camera_bridge.py` does.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import g1_preflight as pf                                             # noqa: E402


TOPIC_LIST = """\
/parameter_events [rcl_interfaces/msg/ParameterEvent]
/t265/odom/sample [nav_msgs/msg/Odometry]
/next_waypoint [geometry_msgs/msg/PointStamped]
/depth_anything/points [sensor_msgs/msg/PointCloud2]
/path_manager/status [std_msgs/msg/String]
/vision/goal_similarity [std_msgs/msg/Float32]
/depth_anything/color_image [sensor_msgs/msg/Image]
"""


def _sources():
    return pf.declared_sources(pf.load_descriptor("real_g1"))


def _by_id(findings):
    return {sid: (severity, message) for severity, sid, message in findings}


# =============================================================================
# Reading what the graph says
# =============================================================================

def test_the_topic_list_is_read_as_topic_to_types():
    live = pf.parse_topic_list(TOPIC_LIST)
    assert live["/t265/odom/sample"] == ["nav_msgs/msg/Odometry"]
    assert len(live) == 7


def test_two_publishers_disagreeing_about_a_type_keeps_both():
    """`ros2 topic list -t` puts both types in one bracket when two publishers disagree.
    Keeping only the first would let a descriptor match the wrong one and report ok on
    a topic the evaluator's subscription will never fire for."""
    live = pf.parse_topic_list("/goal [geometry_msgs/msg/PointStamped, std_msgs/msg/String]\n")
    assert live["/goal"] == ["geometry_msgs/msg/PointStamped", "std_msgs/msg/String"]


def test_noise_around_the_list_is_not_read_as_a_topic():
    """Sourcing a setup.bash prints; so does a DDS warning. A line without the
    `/topic [type]` shape is not a topic."""
    assert pf.parse_topic_list("sourcing /opt/ros/humble/setup.bash\n\n") == {}


def test_the_last_average_rate_wins():
    """`ros2 topic hz` prints a running average once a second. The last one saw the
    most messages, so it is the measurement; the first is the one printed before the
    window filled."""
    assert pf.parse_hz("average rate: 3.100\naverage rate: 9.980\n\tmin: 0.09\n") == 9.98


def test_a_topic_that_never_printed_a_rate_is_none_and_not_zero():
    """Nothing arrived and "it arrived at 0 Hz" are different claims, and only one of
    them can be measured. `check` turns the first into "advertised but nothing
    arrived", which is the symptom of a publisher that came up and then died."""
    assert pf.parse_hz("no new messages\n") is None
    assert pf.parse_hz("") is None


# =============================================================================
# required vs tracked, resolved the way the evaluator resolves it
# =============================================================================

def test_required_defaults_to_tracked_exactly_as_the_adapter_does():
    """`core/adapter_spec.py` defaults `required` to `tracked` and `tracked` to true.
    A preflight that guessed differently would call a run ready that the evaluator
    then refuses to trust -- or, worse, fail a run over an optional camera."""
    sources = {s["id"]: s for s in _sources()}
    assert sources["odom"]["required"] is True          # tracked, says nothing
    assert sources["goal"]["required"] is False         # tracked: false
    assert sources["camera"]["required"] is False       # required: false, explicit


def test_a_source_with_no_topic_is_not_checkable_and_is_dropped():
    assert pf.declared_sources({"sources": [{"id": "x"}, "nonsense", {"topic": "/y"}]}) == [
        {"id": "/y", "topic": "/y", "type": None, "tracked": True,
         "required": True, "expected_hz": None},
    ]


# =============================================================================
# The verdict
# =============================================================================

def test_a_live_graph_that_matches_the_descriptor_passes():
    findings = pf.check(_sources(), pf.parse_topic_list(TOPIC_LIST))
    assert {f[0] for f in findings} == {pf.OK}
    assert pf.summarise(findings, 7)[0] == 0


def test_a_missing_required_source_fails_the_preflight():
    """The evaluator holds every proposition over a missing required source at UNKNOWN,
    so this is the run not being worth starting."""
    live = pf.parse_topic_list(TOPIC_LIST)
    del live["/t265/odom/sample"]
    findings = pf.check(_sources(), live)
    assert _by_id(findings)["odom"][0] == pf.ERROR
    assert pf.summarise(findings, 6)[0] == 1


def test_a_missing_optional_source_warns_and_still_passes():
    """`/vision/goal_similarity` comes from the CLIP matcher, which is a separate
    launch. Without it the visual-goal proposition reads UNKNOWN and every other one
    is unaffected -- a run worth recording, not a run to abort."""
    live = pf.parse_topic_list(TOPIC_LIST)
    del live["/vision/goal_similarity"]
    findings = pf.check(_sources(), live)
    assert _by_id(findings)["vision"][0] == pf.WARN
    assert pf.summarise(findings, 6)[0] == 0


def test_a_renamed_type_on_the_right_topic_is_always_an_error():
    """The subscription is created on the declared type. A mismatch is not a degraded
    source, it is a subscription that never fires -- on an optional source too, which
    is why this does not follow `required`."""
    live = pf.parse_topic_list(TOPIC_LIST)
    live["/vision/goal_similarity"] = ["std_msgs/msg/Float64"]
    findings = pf.check(_sources(), live)
    severity, message = _by_id(findings)["vision"]
    assert severity == pf.ERROR
    assert "Float64" in message and "Float32" in message


def test_a_topic_advertised_with_nothing_arriving_is_reported():
    """A publisher that came up and then stopped still advertises. This is the case
    `ros2 topic list` alone cannot see, and the only reason --rates exists."""
    live = pf.parse_topic_list(TOPIC_LIST)
    rates = {"/t265/odom/sample": None}
    severity, message = _by_id(pf.check(_sources(), live, rates))["odom"]
    assert severity == pf.ERROR
    assert "nothing arrived" in message


def test_a_source_far_under_its_declared_rate_warns_but_does_not_fail():
    """A rate is a declaration about a healthy robot, and what a slow source does to a
    proposition is the evaluator's freshness logic to decide, not this tool's."""
    live = pf.parse_topic_list(TOPIC_LIST)
    rates = {"/t265/odom/sample": 1.0}                   # declares 10.0
    severity, message = _by_id(pf.check(_sources(), live, rates))["odom"]
    assert severity == pf.WARN
    assert "1.0 Hz" in message and "10.0" in message


def test_jitter_around_the_declared_rate_is_not_a_finding():
    live = pf.parse_topic_list(TOPIC_LIST)
    rates = {"/t265/odom/sample": 8.7}
    assert _by_id(pf.check(_sources(), live, rates))["odom"][0] == pf.OK


# =============================================================================
# The failure that looks like every other failure
# =============================================================================

def test_an_empty_graph_names_the_two_settings_that_cause_it():
    """Every topic missing is almost never every node being down. It is this shell
    looking at a different graph, and the ten minutes usually spent restarting healthy
    nodes are the reason this sentence exists."""
    code, lines = pf.summarise(pf.check(_sources(), {}), 0)
    assert code == 1
    assert "ROS_DOMAIN_ID" in lines[0] and "RMW_IMPLEMENTATION" in lines[0]


def test_a_partial_graph_does_not_claim_the_domain_is_wrong():
    """One topic present proves the domain is right, so the advice above would be
    wrong -- and advice that is wrong half the time gets ignored the other half."""
    live = {"/t265/odom/sample": ["nav_msgs/msg/Odometry"]}
    _, lines = pf.summarise(pf.check(_sources(), live), 1)
    assert "ROS_DOMAIN_ID" not in " ".join(lines)


# =============================================================================
# Where the descriptor comes from
# =============================================================================

def test_a_bare_name_resolves_against_the_packaged_adapters():
    assert pf.load_descriptor("real_g1")["name"] == "real_g1"


def test_a_path_is_read_as_a_path_so_a_mounted_config_volume_works(tmp_path):
    """On the robot the descriptor being run is the one on /config, which is not the
    one packaged in this checkout. Checking the packaged copy there would preflight a
    file the evaluator is not reading."""
    path = tmp_path / "real_g1.json"
    path.write_text(json.dumps({"name": "mounted", "sources": []}), encoding="utf-8")
    assert pf.load_descriptor(str(path))["name"] == "mounted"


def test_every_packaged_descriptor_is_checkable():
    """The tool is not G1-specific -- the sim stack has the same failure mode. A
    descriptor this cannot read is one no preflight covers."""
    for path in sorted(pf.PACKAGED_ADAPTERS.glob("*.json")):
        descriptor = pf.load_descriptor(str(path))
        if "sources" not in descriptor:
            continue                                     # a schema fragment, not an adapter
        assert pf.declared_sources(descriptor), path.name


def test_a_descriptor_that_is_not_there_exits_two_rather_than_raising(capsys):
    """Exit 2 for "could not check", distinct from exit 1 for "checked, and it is not
    ready" -- a launch script that treats a typo as a failed preflight retries forever."""
    assert pf.main(["--descriptor", "/nope/missing.json"]) == 2
    assert "cannot read the descriptor" in capsys.readouterr().err


def test_no_ros2_on_path_is_could_not_check_and_not_a_failed_preflight(monkeypatch, capsys):
    """An unsourced shell reports every topic missing, which reads exactly like a robot
    with nothing running. Answering "not ready" there would send someone to restart
    healthy nodes; the shell is what is wrong."""
    def no_ros2(*_args, **_kwargs):
        raise OSError(2, "No such file or directory")
    monkeypatch.setattr(pf.subprocess, "Popen", no_ros2)

    assert pf.main([]) == 2
    assert "setup.bash" in capsys.readouterr().err
