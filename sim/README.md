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
    fault_spec.py        the fault table: types, defaults, validation (pure)
    faults.py            FaultInjector: fires scheduled faults as the episode runs
    generator.py         procedural scenarios: generate(family, seed)
  mujoco_ros_bridge.py   the ROS shell around G1Sim
  generate_map.py        Nav2's startup map from a scenario
  generate_scenarios.py  writes procedural scenarios to a directory
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
    --scenario-dir sim/scenarios/generated --arm full --policy recover --out episodes.jsonl
```

`--scenario FILE --episodes N` repeats one scenario instead. Each episode follows the same
sequence:

1. Publish the scenario on `/g1/reset`.
2. Wait for `/g1/reset_done`.
3. Arm the monitor.
4. Send the first goal.
5. Run until the episode ends.
6. Write one line of `skill_monitor/core/episode_record.py`.

If a reset is rejected or never answered, the runner records that and does not drive the
robot.

**The outcome is ground truth, never the monitor's opinion.** The bridge publishes
`/g1/ground_truth` with a latched `fell` flag and the true distance to the goal:

- A fall ends the episode under every policy.
- Nav2's `succeeded` counts only if the robot is truly within 0.5 m of the goal. An
  odometry drift that fools Nav2 is recorded as `false_arrival`.

The arms of E1 differ only in the monitor's specification, so a verdict-judged outcome
would let the arm under test grade itself.

**What the monitor's interventions do** (`--policy`). An intervention is a REPLAN or worse
token, or `terminal: FAILURE`.

| policy | on an intervention |
|---|---|
| `off` | nothing; recorded only |
| `detect` | the episode ends, cause `monitor:<mode>` |
| `recover` | re-plan, up to `--max-recoveries` (2), then as `detect` |

A re-plan does three things, in this order:

1. Open a fresh Nav2 goal-status window, so the preempted goal's `aborted` cannot end the
   episode.
2. Re-arm the monitor, so its phase machine starts over.
3. Re-send the goal.

`detected_tick` is recorded under every policy, `off` included. Re-planning lives here
rather than in the supervisor: P5's deployed supervisor stops on REPLAN.

The monitor runs `--passive` in this stack. A fault sends it idle with
`terminal: FAILURE` instead of shutting it and the evaluator down, so a sweep survives
falls.

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

## Faults

A fault is `{"type", "onset_s", "params"}`. It fires within one 20 ms control period of
`onset_s` (episode time, after settling). The bridge publishes it once on
`/g1/fault_injected` as `{reset, type, onset_s, t, params}`. The runner stamps it with the
clock tick current on arrival (`injected_tick`), which is what time-to-detection is
measured from. The monitor never supplies that number.

| type | effect | defaults | measured on the walking G1 |
|---|---|---|---|
| `push` | force on the pelvis, `angle` relative to heading | 300 N, π/2, 0.3 s | falls |
| `slip` | sliding friction of **every** geom | μ 0.1 | μ ≤ 0.12 falls, 0.15 still walks |
| `weaken` | leg torque scale | 0.5 | ≤ 0.6 collapses, 0.8 still walks |
| `stall` | scale on the *executed* command; the commanded one is untouched | 0.0 | stands still, upright |
| `obstacle` | a box appears (`pos` required) | 0.25 × 0.25 × 0.5 m half-extents | solid, and seen by the scan |
| `block_route` | a wide box appears across the route | 0.15 × 1.5 × 0.5 m | the same |
| `odom_drift` | reported pose walks off the true one | 0.05 m/s, angle 0 | `/odom` and TF drift, the robot does not |
| `scan_dropout` | `/scan` stops publishing | `duration_s` none = rest of episode | no scan |

Notes on the table:

- **`slip` lowers every geom's friction.** MuJoCo takes a contact's friction as the
  maximum of the two geoms, so lowering only the floor changes nothing.
- **`stall` is the fault only sensor-grounded progress can see.** The planner keeps
  commanding and keeps reporting "following".
- **Spawned boxes are hidden spare bodies**, two per world, parked out of the arena, so
  no fault rebuilds the model. Nav2's map does not contain them; the costmap learns them
  from the scan, as with a real surprise. Resizing a spare also updates its BVH bounds:
  `mj_multiRay` prunes by those, and without that update a spawned box was solid but
  invisible to the scan from some angles.
- **A reset puts everything back.** A same-layout reset reuses the model, so friction,
  torque scale, command scale, drift, dropout and the spares are restored. A test checks
  that the next episode is bit-identical to a clean one.

## Procedural scenarios

```bash
python3 sim/generate_scenarios.py --family clear cluttered weaken stall slip push \
    --seeds 0-19 --out sim/scenarios/generated
```

`generate(family, seed)` is deterministic: the same arguments give the same scenario on
every machine. The seed varies:

- the start pose;
- the goal, 3–6 m away;
- the clutter;
- for a fault family, the fault's onset (2–10 s) and parameters.

Fault parameters are drawn from the range measured to actually stop or fell the robot.

The families are `clear`, `cluttered`, and one per fault type. A spawned box lands at
least 2.2 m ahead along the route with onset ≤ 2 s, so it never appears on top of the
robot.

## Running E1

Every step below except the first runs here as tests. The first needs the LLM endpoint.

1. **Generate the spec** from the plain-language description, over the MuJoCo
   vocabulary. It is written only if it passes the monitor's own load gates, with a
   `.provenance.json` beside it:

   ```bash
   python -m skill_monitor.describer.generate_spec --adapter mujoco \
       --description skill_monitor/specs/descriptions/g1_navigation.md \
       --out skill_monitor/specs/formulas_g1_sim.json --api-url ... --model ...
   ```

2. **Build the control** — the same spec with its order removed:

   ```bash
   python -m skill_monitor.core.spec_ablation skill_monitor/specs/formulas_g1_sim.json \
       --out skill_monitor/specs/formulas_g1_sim_flat.json
   ```

   Add `--drop-terminal-failure` for the stricter reading: a stall reaches the monitor
   through `terminal_failure`, so whether to keep it changes what the control can catch.

3. **Run both arms** with the stack started as `SPEC=formulas_g1_sim.json` and then
   `SPEC=formulas_g1_sim_flat.json`, each over the same scenario directory and policies
   (`off`, `detect`, `recover`), labelled `--arm full` and `--arm flat`.

4. **Make the table**:

   ```bash
   python tools/analyze_episodes.py runs/*.jsonl --out results.md
   ```

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
- **Spot in this repo's CI.** The monitor compiles the generated formulas with Spot,
  which is in the monitor image but not in the pure test container, so a generated spec
  is first compiled on the stack.
- **Runtime map reload.** When the layout changes between episodes, the bridge asks
  `map_server` to load the new map. This is the least-tested piece. If it misbehaves,
  run one layout per stack start (`SCENARIO=...`), which always works.
