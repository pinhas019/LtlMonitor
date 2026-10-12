"""P12, as a test: the monitor reads the robot's own sensors and the goals it was
commanded -- never what the navigation algorithm says about itself.

A planner that reports `following` while the robot is physically wedged is exactly the
failure the monitor exists to catch, and it is invisible to a monitor that asks the
planner. So no shipped descriptor may subscribe to a planner self-report at all -- not
for one key, not as an unused source. The sim runs Nav2 and the robot runs TRAV; a
monitor that read either one's status would also stop transferring between them.

Forbidden (docs/packages/P12-planner-independent-schema.md, "Inputs"):
  * any topic whose last segment is `status` -- TRAV's /path_manager/status and any
    other planner's equivalent;
  * any action server's GoalStatusArray, matched by TYPE as well, so renaming the
    topic does not launder it;
  * the planner's chosen path (/traversable_path*) and the surface it acts on
    (/filtered_map, traversability_projected) -- agreeing with those would blind the
    monitor to exactly the errors the planner makes.

Admitted, and checked below so the guard is not vacuously passing: odometry, range,
the commanded goal (/waypoint, /goal_pose), the intermediate point (/next_waypoint --
where the robot is being sent, not whether the planner thinks it is succeeding), and
the monitor-side vision score.
"""

from __future__ import annotations

import pytest

import skill_monitor
from skill_monitor.core import adapter_spec

_FORBIDDEN_PREFIXES = ("/traversable_path", "/filtered_map")
_FORBIDDEN_SEGMENTS = ("status", "traversability_projected")
_STATUS_TYPES = ("action_msgs/msg/GoalStatusArray",)

#: The inputs P12 admits, on every shipped descriptor.
ADMITTED = {
    "/t265/odom/sample", "/odom",
    "/depth_anything/points", "/scan", "/g1/lidar/points",
    "/waypoint", "/next_waypoint", "/goal_pose",
    "/vision/goal_similarity", "/depth_anything/color_image",
}


def is_planner_self_report(topic: str, type_: str) -> bool:
    """Whether a topic is the navigation algorithm talking about itself.

    Structural rather than a list of known planners, so a descriptor wired to a planner
    nobody has heard of yet is caught too.
    """
    path = topic.rstrip("/")
    return (path.rsplit("/", 1)[-1] in _FORBIDDEN_SEGMENTS
            or path.startswith(_FORBIDDEN_PREFIXES)
            or type_ in _STATUS_TYPES)


def planner_sources(spec) -> list[str]:
    return [f"{s.id} ({s.topic}, {s.type})" for s in spec.sources
            if is_planner_self_report(s.topic, s.type)]


# =============================================================================
# The guard
# =============================================================================

@pytest.mark.parametrize("name", adapter_spec.available())
def test_no_forbidden_topic_in_any_descriptor(name):
    offending = planner_sources(adapter_spec.load(name))
    assert not offending, (
        f"{name} subscribes to the planner's account of itself: {offending}. The "
        f"monitor observes the robot and the goal it was commanded; progress comes "
        f"from odometry against that goal (closing_speed, no_progress), never from "
        f"the planner's status")


@pytest.mark.parametrize("name", adapter_spec.available())
def test_every_shipped_source_is_an_admitted_input(name):
    """The positive side, so the guard cannot pass by matching nothing: every topic a
    descriptor reads is one P12 admits. A new topic has to be argued into this list,
    which is where the judgement call (is it the robot, or the planner?) belongs."""
    topics = {s.topic for s in adapter_spec.load(name).sources}
    assert topics <= ADMITTED, f"{name}: not yet admitted: {sorted(topics - ADMITTED)}"


def test_no_schema_key_is_the_planners_vocabulary():
    """The six keys that came off the planner's status are gone from the vocabulary,
    so no spec can be written over them -- a spec that tries is refused at load as
    reading a field the robot does not provide."""
    gone = {"nav_state", "nav_mode", "nav_stuck", "mission_finished",
            "num_waypoints", "current_target_idx"}
    for name in adapter_spec.available():
        assert not gone & set(adapter_spec.load(name).keys()), name


# =============================================================================
# The guard catches what it exists for
# =============================================================================

def _sabotaged(topic, type_, **source):
    schema, _ = adapter_spec.compose_schema(
        ["pose_schema.json", "nav_schema.json"], skill_monitor.adapters_dir())
    return adapter_spec.from_dict({
        "name": "sabotaged", "schema": dict(schema),
        "defaults": {k: v.get("default") for k, v in schema.items()},
        "sources": [{"id": "planner", "topic": topic, "type": type_,
                     "steps": [{"key": "goal_x", "field": "target_x", "default": 0.0}],
                     **source}],
    })


@pytest.mark.parametrize("topic,type_,extra", [
    ("/path_manager/status", "std_msgs/msg/String", {"decode": "json"}),
    ("/some_new_planner/status", "std_msgs/msg/String", {"decode": "json"}),
    ("/where_am_i_going", "action_msgs/msg/GoalStatusArray", {"decode": "goal_status"}),
    ("/navigate_to_pose/_action/status", "action_msgs/msg/GoalStatusArray",
     {"decode": "goal_status"}),
    ("/traversable_path", "std_msgs/msg/String", {"decode": "json"}),
    ("/traversable_path_smoothed", "std_msgs/msg/String", {"decode": "json"}),
    ("/filtered_map", "std_msgs/msg/String", {"decode": "json"}),
    ("/elevation/traversability_projected", "std_msgs/msg/String", {"decode": "json"}),
])
def test_the_guard_catches_a_planner_source(topic, type_, extra):
    assert planner_sources(_sabotaged(topic, type_, **extra)) == [
        f"planner ({topic}, {type_})"]


@pytest.mark.parametrize("topic", sorted(ADMITTED))
def test_the_guard_admits_every_allowed_input(topic):
    assert not is_planner_self_report(topic, "geometry_msgs/msg/PointStamped")
