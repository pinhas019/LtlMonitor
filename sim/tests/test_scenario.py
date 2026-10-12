"""Scenario parsing and the Nav2 map built from it. Pure Python."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from g1sim import Scenario, ScenarioError, from_dict, load
from g1sim.occupancy import FREE, OCCUPIED, occupancy_grid, write_map

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def _raw(**overrides):
    base = {"name": "t", "goals": [[3.0, 0.0]]}
    base.update(overrides)
    return base


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.json")), ids=lambda p: p.stem)
def test_every_shipped_scenario_loads(path):
    scenario = load(path)
    assert scenario.name == path.stem


def test_a_minimal_scenario_takes_the_defaults():
    s = from_dict(_raw())
    assert s.map_size == (10.0, 10.0) and s.start == (0.0, 0.0, 0.0)
    assert s.walls and s.obstacles == () and s.faults == ()


def test_to_dict_round_trips():
    raw = json.loads((SCENARIOS / "box_in_path.json").read_text(encoding="utf-8"))
    scenario = from_dict(raw)
    assert from_dict(scenario.to_dict()) == scenario


def test_every_problem_is_reported_at_once():
    with pytest.raises(ScenarioError) as caught:
        from_dict({"name": "", "seed": 1.5, "goals": [], "colour": "red"})
    problems = caught.value.problems
    assert any("unknown key 'colour'" in p for p in problems)
    assert any(p.startswith("name") for p in problems)
    assert any(p.startswith("seed") for p in problems)
    assert any(p.startswith("goals") for p in problems)


@pytest.mark.parametrize("overrides,needle", [
    ({"start": {"x": 9.0, "y": 0.0, "yaw": 0.0}}, "start lies outside"),
    ({"goals": [[0.0, 7.0]]}, "goals[0] lies outside"),
    ({"obstacles": [{"type": "cone", "pos": [1, 1]}]}, "type must be"),
    ({"obstacles": [{"type": "box", "pos": [1, 1], "size": [1, 1]}]}, "half-extents"),
    ({"obstacles": [{"type": "cylinder", "pos": [1, 1], "radius": 0}]}, "radius"),
    ({"obstacles": [{"type": "box", "pos": [3.0, 0.0], "size": [0.2, 0.2, 0.5]}]},
     "goals[0] is within"),
    ({"faults": [{"type": "push"}]}, "faults[0]"),
    ({"duration_s": 0}, "duration_s"),
])
def test_invalid_scenarios_say_what_is_wrong(overrides, needle):
    with pytest.raises(ScenarioError) as caught:
        from_dict(_raw(**overrides))
    assert any(needle in p for p in caught.value.problems), caught.value.problems


def test_the_layout_key_ignores_what_does_not_change_the_world():
    base = from_dict(_raw())
    moved = from_dict(_raw(start={"x": 1.0, "y": 1.0, "yaw": 1.0}, goals=[[2.0, 2.0]],
                           seed=9))
    walled = from_dict(_raw(obstacles=[{"type": "box", "pos": [1, -2],
                                        "size": [0.2, 0.2, 0.5]}]))
    assert base.layout_key() == moved.layout_key()
    assert base.layout_key() != walled.layout_key()


def test_obstacle_footprint_distance():
    s = from_dict(_raw(obstacles=[{"type": "box", "pos": [1, -2], "size": [0.5, 0.25, 0.5]},
                                  {"type": "cylinder", "pos": [-2, 2], "radius": 0.3,
                                   "height": 1.0}]))
    box, cyl = s.obstacles
    assert box.distance_to(1.0, -2.0) == 0.0
    assert box.distance_to(2.0, -2.0) == pytest.approx(0.5)
    assert cyl.distance_to(-2.0, 3.0) == pytest.approx(0.7)
    assert cyl.height == pytest.approx(1.0)


# =============================================================================
# The map comes from the same object
# =============================================================================

def _cell(width, height, pixels, scenario, x, y, resolution):
    col = int((x + scenario.map_size[0] / 2) / resolution)
    row = height - 1 - int((y + scenario.map_size[1] / 2) / resolution)
    return pixels[row * width + col]


def test_the_map_marks_walls_and_obstacles_and_nothing_else():
    s = load(SCENARIOS / "box_in_path.json")
    res = 0.1
    w, h, px = occupancy_grid(s, resolution=res)
    assert (w, h) == (100, 100)
    assert _cell(w, h, px, s, 0.0, 0.0, res) == FREE
    assert _cell(w, h, px, s, -2.0, 0.0, res) == FREE              # the start
    assert _cell(w, h, px, s, 0.5, 0.0, res) == OCCUPIED           # the box
    assert _cell(w, h, px, s, 1.5, 1.6, res) == OCCUPIED           # the cylinder
    assert _cell(w, h, px, s, 4.97, 0.0, res) == OCCUPIED          # east wall
    assert _cell(w, h, px, s, 0.0, -4.97, res) == OCCUPIED         # south wall


def test_the_first_image_row_is_the_top_of_the_map():
    """map_server reads row 0 as the largest y. An obstacle at +y must be near the top."""
    s = from_dict(_raw(walls=False,
                       obstacles=[{"type": "box", "pos": [0, 4], "size": [0.3, 0.3, 0.5]}]))
    w, h, px = occupancy_grid(s, resolution=0.1)
    occupied_rows = {i // w for i, v in enumerate(px) if v == OCCUPIED}
    assert occupied_rows and max(occupied_rows) < h // 4


def test_write_map_produces_a_map_server_pair(tmp_path):
    s = load(SCENARIOS / "clear.json")
    pgm, yaml_path = write_map(s, tmp_path, resolution=0.1)
    data = pgm.read_bytes()
    assert data.startswith(b"P5\n100 100\n255\n")
    assert len(data) == len(b"P5\n100 100\n255\n") + 100 * 100
    text = yaml_path.read_text(encoding="utf-8")
    assert "image: map.pgm" in text and "origin: [-5.0, -5.0, 0.0]" in text
