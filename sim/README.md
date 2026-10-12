# Simulator — a Unitree G1 walking under MuJoCo physics

The G1 here walks with Unitree's released locomotion policy on their 12-DoF legs-only model,
under real MuJoCo dynamics. It can fall, slip and be pushed, and it resets between episodes
on request. Nav2 drives it in simulation; the monitor watches it through the same evaluator
and specification it uses on the robot, with only `--adapter mujoco` changed.

```
sim/
  g1sim/                 ROS-free core, testable headless
    scenario.py          a scenario as data: layout, start, goals, obstacles, faults
    occupancy.py         Nav2's map, from the same scenario
    world.py             MJCF: Unitree's G1 + floor + walls + obstacles + goal marker
    policy.py            the walking policy (an LSTM) in numpy, loaded without torch
    locomotion.py        Unitree's sim2sim control loop, command from /cmd_vel
    sim.py               G1Sim: reset, set_command, step, pose, upright, scan, push
  mujoco_ros_bridge.py   the ROS shell around G1Sim
  generate_map.py        Nav2's startup map from a scenario
  scenarios/*.json       scenario files
  tests/                 sim-core tests
  fetch_assets.sh        Unitree assets at a pinned commit (see NOTICE)
```

## Run the stack

```bash
docker compose -f sim/docker-compose.sim.yml up --build
```

The G1 starts in `scenarios/clear.json`. Nav2 sends it the scenario's first goal after
15 s; watch it in Foxglove. Pick another scenario with `SCENARIO=box_in_path docker
compose ... up`.

## Run episodes in volume

Start the stack with the auto-goal off, then run the episode runner from any container
on the same ROS graph:

```bash
AUTO_GOAL=0 docker compose -f sim/docker-compose.sim.yml up --build
python -m skill_monitor.backend.ablation_runner \
    --scenario sim/scenarios/clear.json --episodes 20 --arm full --out episodes.jsonl
```

Each episode follows the same sequence:

1. Publish the scenario on `/g1/reset`, with the run's seed.
2. Wait for `/g1/reset_done`.
3. Arm the monitor.
4. Send the first goal.
5. Write one line of `skill_monitor/core/episode_record.py` once the episode ends.

If a reset is rejected or never answered, the runner records that and does not drive the
robot.

To record what the monitor saw, run `python -m skill_monitor.backend.replay_node record`
alongside. Each tick's `/monitor/observation` carries the folded sensor values, the
proposition values and per-source data health. Each verdict carries the phase. The two join
on `seq`.

## Run the sim tests

```bash
pip install mujoco "numpy<2" pyyaml pytest      # numpy<2 only to match the ROS image
sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree
python -m pytest sim/tests
```

Inside the image, assets are already at `/opt/unitree_rl_gym`:

```bash
docker compose -f sim/docker-compose.sim.yml run --rm mujoco-sim \
    bash -c "pip3 install pytest && python3 -m pytest tests"
```

These tests are separate from the main suite (`testpaths = ["tests"]`), which stays pure
Python. If torch is importable, one more test checks the numpy policy against TorchScript
(tolerance 1e-5); without torch that test is skipped.

## Scenarios

```json
{"name": "box_in_path", "seed": 0, "map_size": [10, 10],
 "start": {"x": -2, "y": 0, "yaw": 0}, "goals": [[2.5, 0]],
 "obstacles": [{"type": "box", "pos": [0.5, 0], "size": [0.3, 0.6, 0.5]},
               {"type": "cylinder", "pos": [1.5, 1.6], "radius": 0.2, "height": 1.0}],
 "walls": true, "duration_s": 90, "faults": []}
```

Box `size` gives half-extents, as in MuJoCo. Validation reports every problem at once.

The start and every goal must be at least 0.4 m clear of every obstacle.

A reset rebuilds the MuJoCo model only when the layout changes. Moving the start, the goals
or the seed reuses it.

`faults` is validated but nothing injects faults yet; the fault library is SIM.4 in
`docs/implementation-plan.md`.

## What changed from the kinematic bridge, and why it matters

| | before | now |
|---|---|---|
| motion | integrated the commanded velocity, height pinned at 0.78 m | physics, driven by the walking policy |
| falls | impossible, so `upright` never went false | a push makes it fall, and `upright` goes false |
| odometry twist | echoed the command | measured |
| scan plane | pelvis height + 0.5 m (≈1.3 m), so it missed anything shorter | 0.3 m above the floor |
| obstacles | the map read them from `<body>` elements and the lidar from worldbody geoms, so each obstacle was seen by only one | both come from the same scenario |
| reset | none | `/g1/reset` → `/g1/reset_done` |
| robot | 29-DoF menagerie G1, no controller | Unitree's 12-DoF G1 and the policy trained on it |

Two choices in the model are worth knowing:

- **A torso capsule.** In Unitree's model only eight small spheres under the feet collide.
  A falling robot would sink through the floor, and a walking one would pass through
  walls. `world.py` adds one massless capsule on the pelvis. It collides with the world
  but not with the robot's own feet or legs, so the trained gait is unchanged.
- **No torch.** The policy has about 40k parameters. `policy.py` reads its weights
  straight from the TorchScript archive and evaluates the LSTM in numpy. Neither the
  simulator image nor, later, the robot needs a torch build for it.

## Not done yet

- **Simulated time.** The bridge runs at wall time, and Nav2 and the monitor clock follow
  wall time. Faster-than-real-time sweeps, with the bridge publishing `/clock` and stepping
  the monitor's `replay` clock, are SIM.5.
- **Camera.** `image_similarity_to_goal` still has to be published by hand for the
  VisualGoalConfirmation phase (see the header of `docker-compose.sim.yml`).
- **Runtime map reload.** When the layout changes between episodes, the bridge asks
  `map_server` to load the new map. This is the least-tested piece. If it misbehaves,
  run one layout per stack start (`SCENARIO=...`), which always works.
