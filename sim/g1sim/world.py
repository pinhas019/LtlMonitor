"""The MuJoCo world for a Scenario: Unitree's 12-DoF G1, a floor, walls and obstacles.

Built with MjSpec on top of `g1_12dof.xml` rather than by editing XML text, so the
robot model is used exactly as Unitree ships it and only the environment is ours.

Geom groups are how the lidar tells the world from the robot:
    ENV_GROUP     walls and obstacles -- what the simulated scan sees
    TARGET_GROUP  the goal marker, visual only
The robot's meshes are group 1 and the floor group 0; neither is in the scan.

Boxes that appear mid-episode (the `obstacle` and `block_route` faults) are spare mocap
bodies built in from the start and parked out of the arena, so no fault rebuilds the
model and the robot's simulation state never has to be carried across a recompile.
They are ENV_GROUP, so the scan sees one the moment it is placed -- and Nav2's map does
not, exactly as with a real surprise.

The shipped model collides through eight small foot spheres only, so a falling robot
would sink its torso through the floor and walk through walls. `body_collision` adds one
massless torso capsule that collides with the world but not with the robot's own feet
or legs (contype/conaffinity bits below), so a fall lands like a fall without changing
the masses or the gait the policy was trained on.
"""

from __future__ import annotations

from pathlib import Path

import mujoco

from .fault_spec import SPARE_BODIES
from .scenario import Scenario

ENV_GROUP = 2
TARGET_GROUP = 3
WALL_HEIGHT_M = 1.0
WALL_THICKNESS_M = 0.1          # matches occupancy.WALL_THICKNESS_M
PELVIS = "pelvis"
TARGET = "target"
SPARE = "spare_{}"

#: Where an unused spare waits: far outside any arena, clear of the floor (a mocap box
#: resting on the plane would generate a contact every step for nothing), and beyond
#: the scan's range.
_SPARE_SIZE = (0.25, 0.25, 0.5)


def spare_park(index: int) -> tuple[float, float, float]:
    return (100.0 + 5.0 * index, 100.0, _SPARE_SIZE[2] + 0.01)

# Collision bits. World geoms (floor, walls, obstacles) and the feet keep MuJoCo's
# default contype = conaffinity = 1. The torso capsule is contype 2, conaffinity 1:
# it collides with anything of contype 1, and nothing of contype 1 or 2 collides
# back into it except through that pairing -- so it never touches another capsule.
_BODY_CONTYPE, _BODY_CONAFFINITY = 2, 1


def build_model(scenario: Scenario, model_xml: str | Path, *, timestep: float = 0.002,
                body_collision: bool = True) -> mujoco.MjModel:
    spec = mujoco.MjSpec.from_file(str(model_xml))
    world = spec.worldbody

    world.add_light(pos=[0, 0, 4], dir=[0, 0, -1])
    world.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05],
                   rgba=[0.25, 0.3, 0.35, 1])

    if scenario.walls:
        half_x, half_y = scenario.map_size[0] / 2.0, scenario.map_size[1] / 2.0
        half_t, half_h = WALL_THICKNESS_M / 2.0, WALL_HEIGHT_M / 2.0
        for name, pos, size in (
            ("wall_n", [0, half_y - half_t, half_h], [half_x, half_t, half_h]),
            ("wall_s", [0, -half_y + half_t, half_h], [half_x, half_t, half_h]),
            ("wall_e", [half_x - half_t, 0, half_h], [half_t, half_y, half_h]),
            ("wall_w", [-half_x + half_t, 0, half_h], [half_t, half_y, half_h]),
        ):
            world.add_geom(name=name, type=mujoco.mjtGeom.mjGEOM_BOX, pos=pos, size=size,
                           group=ENV_GROUP, rgba=[0.6, 0.6, 0.6, 1])

    for i, obstacle in enumerate(scenario.obstacles):
        half_h = obstacle.size[-1]
        if obstacle.kind == "box":
            kind, size = mujoco.mjtGeom.mjGEOM_BOX, list(obstacle.size)
        else:
            kind, size = mujoco.mjtGeom.mjGEOM_CYLINDER, [obstacle.size[0], half_h, 0]
        world.add_geom(name=f"obstacle_{i}", type=kind, size=size,
                       pos=[obstacle.x, obstacle.y, half_h], group=ENV_GROUP,
                       rgba=[0.8, 0.45, 0.2, 1])

    goal_x, goal_y = scenario.goals[0]
    target = world.add_body(name=TARGET, pos=[goal_x, goal_y, 0.05], mocap=True)
    target.add_geom(type=mujoco.mjtGeom.mjGEOM_CYLINDER, size=[0.15, 0.02, 0],
                    contype=0, conaffinity=0, group=TARGET_GROUP, rgba=[0.1, 0.8, 0.2, 0.6])

    for i in range(SPARE_BODIES):
        spare = world.add_body(name=SPARE.format(i), pos=list(spare_park(i)), mocap=True)
        spare.add_geom(name=SPARE.format(i), type=mujoco.mjtGeom.mjGEOM_BOX,
                       size=list(_SPARE_SIZE), group=ENV_GROUP, rgba=[0.85, 0.2, 0.2, 1])

    if body_collision:
        spec.body(PELVIS).add_geom(
            name="torso_collision", type=mujoco.mjtGeom.mjGEOM_CAPSULE,
            fromto=[0, 0, 0.0, 0, 0, 0.45], size=[0.12, 0, 0], density=0,
            contype=_BODY_CONTYPE, conaffinity=_BODY_CONAFFINITY, group=4)

    model = spec.compile()
    model.opt.timestep = timestep
    return model
