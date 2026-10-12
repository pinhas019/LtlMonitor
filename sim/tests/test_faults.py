"""The fault library and the scenario generator.

The table and the generator are pure and always run. The physics tests need mujoco and
the Unitree assets (conftest.py) and check that each fault does to the walking robot what
its name says -- the property an E1 episode is scored against -- and that a reset takes
all of it back.
"""

from __future__ import annotations

import math

import pytest

from g1sim import ScenarioError, from_dict, load
from g1sim import fault_spec, generator

WALK_MPS = 0.5


def _raw(faults=(), obstacles=()):
    return {"name": "t", "start": {"x": -2.0, "y": 0.0, "yaw": 0.0}, "goals": [[3.0, 0.0]],
            "obstacles": list(obstacles), "faults": list(faults)}


# =============================================================================
# The table
# =============================================================================

@pytest.mark.parametrize("kind", sorted(set(fault_spec.FAULTS) - set(fault_spec.REQUIRED)))
def test_every_fault_without_a_required_param_validates_on_its_defaults(kind):
    assert fault_spec.validate({"type": kind, "onset_s": 1.0}) == []


@pytest.mark.parametrize("kind", sorted(fault_spec.REQUIRED))
def test_a_spawning_fault_needs_a_position(kind):
    problems = fault_spec.validate({"type": kind, "onset_s": 1.0})
    assert any("requires param 'pos'" in p for p in problems)
    assert fault_spec.validate({"type": kind, "onset_s": 1.0,
                                "params": {"pos": [1.0, 2.0]}}) == []


@pytest.mark.parametrize("fault,needle", [
    ("push", "must be an object"),
    ({"type": "earthquake", "onset_s": 1}, "type must be one of"),
    ({"type": "push"}, "onset_s must be"),
    ({"type": "push", "onset_s": -1}, "onset_s must be"),
    ({"type": "push", "onset_s": 1, "when": 2}, "unknown key 'when'"),
    ({"type": "push", "onset_s": 1, "params": []}, "params must be an object"),
    ({"type": "push", "onset_s": 1, "params": {"force": 3}}, "has no param 'force'"),
    ({"type": "push", "onset_s": 1, "params": {"force_n": 0}}, "must be > 0"),
    ({"type": "slip", "onset_s": 1, "params": {"mu": True}}, "must be a number"),
    ({"type": "weaken", "onset_s": 1, "params": {"scale": 1.5}}, "within [0, 1]"),
    ({"type": "odom_drift", "onset_s": 1, "params": {"rate_m_s": -1}}, "must be >= 0"),
    ({"type": "obstacle", "onset_s": 1, "params": {"pos": [1]}}, "must be [x, y]"),
    ({"type": "obstacle", "onset_s": 1, "params": {"pos": [1, 1], "size": [1, 1, 0]}},
     "three positive half-extents"),
    ({"type": "scan_dropout", "onset_s": 1, "params": {"duration_s": 0}}, "must be > 0"),
])
def test_invalid_faults_say_what_is_wrong(fault, needle):
    problems = fault_spec.validate(fault)
    assert any(needle in p for p in problems), problems


def test_a_dropout_without_a_duration_lasts_the_episode():
    assert fault_spec.validate({"type": "scan_dropout", "onset_s": 1}) == []
    assert fault_spec.resolved_params({"type": "scan_dropout"})["duration_s"] is None


def test_resolved_params_fill_in_the_defaults_and_keep_what_was_given():
    params = fault_spec.resolved_params({"type": "push", "params": {"force_n": 120.0}})
    assert params == {**fault_spec.FAULTS["push"], "force_n": 120.0}


def test_a_scenario_validates_its_faults_against_the_table():
    with pytest.raises(ScenarioError) as caught:
        from_dict(_raw([{"type": "weaken", "onset_s": 1, "params": {"scale": 2}}]))
    assert any("faults[0]: weaken.scale" in p for p in caught.value.problems)


def test_a_scenario_cannot_spawn_more_boxes_than_the_world_has_spares():
    spawn = {"type": "obstacle", "onset_s": 1, "params": {"pos": [0.0, 2.0]}}
    from_dict(_raw([spawn] * fault_spec.SPARE_BODIES))
    with pytest.raises(ScenarioError) as caught:
        from_dict(_raw([spawn] * (fault_spec.SPARE_BODIES + 1)))
    assert any("may spawn a box" in p for p in caught.value.problems)


def test_a_spawned_box_must_land_inside_the_map():
    with pytest.raises(ScenarioError) as caught:
        from_dict(_raw([{"type": "obstacle", "onset_s": 1, "params": {"pos": [9, 0]}}]))
    assert any("faults[0]: pos lies outside" in p for p in caught.value.problems)


# =============================================================================
# The generator
# =============================================================================

def test_every_family_is_clear_cluttered_or_a_fault():
    assert set(generator.FAMILIES) == {"clear", "cluttered", *fault_spec.FAULTS}


@pytest.mark.parametrize("family", generator.FAMILIES)
def test_a_family_is_deterministic_per_seed_and_varies_across_seeds(family):
    scenarios = [generator.generate(family, seed) for seed in range(30)]
    assert scenarios == [generator.generate(family, seed) for seed in range(30)]
    assert len({(s.start, s.goals) for s in scenarios}) == 30
    assert [s.name for s in scenarios[:2]] == [f"{family}_000", f"{family}_001"]


@pytest.mark.parametrize("family", generator.FAMILIES)
def test_every_generated_route_is_inside_the_arena_and_the_right_length(family):
    lo, hi = (generator.SPAWN_ROUTE_M if family in fault_spec.SPAWNING
              else generator.ROUTE_M)
    for seed in range(30):
        s = generator.generate(family, seed)
        (gx, gy), (sx, sy, _) = s.goals[0], s.start
        assert lo - 1e-2 <= math.hypot(gx - sx, gy - sy) <= hi + 1e-2
        assert max(map(abs, (sx, sy, gx, gy))) <= generator.ARENA_HALF_M + 1e-2


def test_clear_has_nothing_and_cluttered_has_obstacles_but_no_fault():
    for seed in range(20):
        clear, cluttered = (generator.generate(f, seed) for f in ("clear", "cluttered"))
        assert clear.obstacles == () and clear.faults == ()
        assert len(cluttered.obstacles) >= 2 and cluttered.faults == ()


@pytest.mark.parametrize("family", sorted(fault_spec.FAULTS))
def test_a_fault_family_schedules_exactly_its_fault_within_the_onset_range(family):
    lo, hi = (generator.SPAWN_ONSET_S if family in fault_spec.SPAWNING
              else generator.ONSET_S)
    for seed in range(30):
        (fault,) = generator.generate(family, seed).faults
        assert fault["type"] == family
        assert lo <= fault["onset_s"] <= hi
        assert fault_spec.validate(fault) == []


@pytest.mark.parametrize("family", fault_spec.SPAWNING)
def test_a_spawned_box_lands_ahead_of_the_robot_and_clear_of_the_goal(family):
    """Never on top of the robot: at most 0.8 m/s before the latest onset."""
    for seed in range(30):
        s = generator.generate(family, seed)
        params = s.faults[0]["params"]
        px, py = params["pos"]
        reach = 0.8 * generator.SPAWN_ONSET_S[1]
        assert math.hypot(px - s.start[0], py - s.start[1]) - params["size"][0] > reach
        assert math.hypot(px - s.goals[0][0], py - s.goals[0][1]) > params["size"][0]
        for obstacle in s.obstacles:
            assert obstacle.distance_to(px, py) > params["size"][0]


@pytest.mark.parametrize("text,seeds", [("3", [3]), ("0-4", [0, 1, 2, 3, 4]),
                                        ("0-1,10,12-13", [0, 1, 10, 12, 13])])
def test_parse_seeds(text, seeds):
    assert generator.parse_seeds(text) == seeds


def test_the_cli_writes_scenarios_that_load_back(tmp_path):
    assert generator.main(["--family", "clear", "stall", "--seeds", "0-2",
                           "--out", str(tmp_path)]) == 0
    files = sorted(p.name for p in tmp_path.glob("*.json"))
    assert files == [f"{f}_{s:03d}.json" for f in ("clear", "stall") for s in range(3)]
    for path in tmp_path.glob("*.json"):
        family, seed = path.stem.rsplit("_", 1)
        assert load(path) == generator.generate(family, int(seed))


def test_an_unknown_family_is_refused():
    with pytest.raises(ValueError, match="family must be one of"):
        generator.generate("meteor", 0)


# =============================================================================
# Physics: each fault does what it says
# =============================================================================

def run(sim, faults=(), seconds=5.0, obstacles=()):
    """Reset, walk straight ahead, and report what happened."""
    sim.reset(from_dict(_raw(faults, obstacles)))
    start = sim.base_pose()
    sim.set_command(WALK_MPS, 0.0, 0.0)
    upright = True
    for _ in range(int(round(seconds / sim.config.control_dt))):
        sim.step(control_steps=1)
        upright = upright and sim.upright()
    return {"upright": upright, "dx": sim.base_pose()[0] - start[0],
            "events": sim.pop_fault_events()}


@pytest.fixture(scope="module")
def healthy(sim):
    return run(sim)


def test_a_healthy_walk_stays_up_and_covers_ground(healthy):
    assert healthy["upright"] and healthy["dx"] > 1.5 and healthy["events"] == []


def test_a_fault_fires_once_within_one_control_period_of_its_onset(sim):
    outcome = run(sim, [{"type": "stall", "onset_s": 1.0}], seconds=2.0)
    (event,) = outcome["events"]
    assert event["type"] == "stall" and event["onset_s"] == 1.0
    assert 1.0 <= event["t"] < 1.0 + sim.config.control_dt + 1e-9
    assert event["params"] == fault_spec.resolved_params({"type": "stall"})
    assert sim.pop_fault_events() == []                 # handed over once


def test_a_fault_at_onset_zero_fires_at_the_start_not_while_settling(sim):
    outcome = run(sim, [{"type": "stall", "onset_s": 0.0}], seconds=0.1)
    assert [e["t"] for e in outcome["events"]] == [0.0]


@pytest.mark.parametrize("kind", ["push", "weaken"])
def test_push_and_weaken_bring_the_robot_down(sim, kind):
    assert run(sim, [{"type": kind, "onset_s": 1.0}])["upright"] is False


def test_slip_brings_the_robot_down(sim):
    assert run(sim, [{"type": "slip", "onset_s": 1.0}])["upright"] is False


def test_stall_stops_the_robot_while_the_command_stands(sim, healthy):
    """The fault only progress-from-odometry can see: the planner's command is intact."""
    outcome = run(sim, [{"type": "stall", "onset_s": 1.0}])
    assert outcome["upright"]
    assert outcome["dx"] < healthy["dx"] / 2
    assert sim.command[0] == pytest.approx(WALK_MPS)
    assert sim.executed_command[0] == pytest.approx(0.0)


def test_odom_drift_moves_the_reported_pose_and_not_the_robot(sim, healthy):
    outcome = run(sim, [{"type": "odom_drift", "onset_s": 1.0,
                         "params": {"rate_m_s": 0.1, "angle": math.pi / 2}}])
    assert outcome["dx"] == pytest.approx(healthy["dx"], abs=0.05)
    x, y, _, _ = sim.base_pose()
    rx, ry, _, _ = sim.reported_pose()
    assert rx == pytest.approx(x, abs=1e-9)
    assert ry - y == pytest.approx(0.1 * (sim.time - 1.0), abs=0.03)


def test_scan_dropout_lasts_its_duration(sim):
    sim.reset(from_dict(_raw([{"type": "scan_dropout", "onset_s": 0.5,
                               "params": {"duration_s": 1.0}}])))
    seen = []
    for _ in range(100):
        sim.step(control_steps=1)
        seen.append((round(sim.time, 2), sim.scan_available()))
    gone = [t for t, ok in seen if not ok]
    assert gone and 0.5 <= gone[0] <= 0.54 and 1.48 <= gone[-1] <= 1.52


def test_scan_dropout_without_a_duration_lasts_the_episode(sim):
    sim.reset(from_dict(_raw([{"type": "scan_dropout", "onset_s": 0.1}])))
    sim.step(5.0)
    assert sim.scan_available() is False


def test_a_spawned_box_is_solid(sim, healthy):
    outcome = run(sim, [{"type": "obstacle", "onset_s": 0.5,
                         "params": {"pos": [-0.8, 0.0]}}], seconds=8.0)
    assert outcome["upright"]
    assert sim.base_pose()[0] < -0.8 - 0.25          # stopped at the box's near face


def test_a_spawned_box_scans_exactly_like_one_built_into_the_world(sim):
    """`mj_multiRay` prunes by the body's BVH box, so a resized spare whose bounds were
    not updated is solid but invisible to the scan from some directions."""
    import numpy as np
    wide = {"pos": [-2.0, 1.5], "size": [0.15, 1.5, 0.5], "yaw": math.pi / 2}
    sim.reset(from_dict(_raw([{"type": "block_route", "onset_s": 0.0, "params": wide}])))
    sim.step(control_steps=1)
    spawned = sim.ranges()
    sim.reset(from_dict(_raw(obstacles=[{"type": "box", "pos": wide["pos"],
                                         "size": [1.5, 0.15, 0.5]}])))
    sim.step(control_steps=1)
    built = sim.ranges()
    # The robot sways a little between the two settles; the shapes must match.
    hit = np.isfinite(built) & (built < 3.0)
    assert hit.sum() > 20
    assert np.allclose(spawned[hit], built[hit], atol=0.05)


def test_a_reset_takes_every_fault_back(sim, healthy):
    """A same-layout reset reuses the model, so whatever a fault mutated in it must be
    restored -- or the next episode starts slippery, weak or blind."""
    run(sim, [{"type": "slip", "onset_s": 0.1}, {"type": "weaken", "onset_s": 0.1},
              {"type": "stall", "onset_s": 0.1}, {"type": "odom_drift", "onset_s": 0.1},
              {"type": "scan_dropout", "onset_s": 0.1},
              {"type": "obstacle", "onset_s": 0.1, "params": {"pos": [2.0, 2.0]}},
              {"type": "block_route", "onset_s": 0.1, "params": {"pos": [2.0, -2.0]}}],
        seconds=1.0)
    again = run(sim)
    assert again == healthy
    assert sim.reported_pose() == sim.base_pose() and sim.scan_available()
    assert sim.command_scale == 1.0 and sim.locomotion.torque_scale == 1.0
