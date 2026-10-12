# Implementation plan

The engineering behind the two RA-L papers in `docs/ral-papers.md`. Ordered by the critical path:
**the simulator first**, because every new result depends on it and it is currently the weakest
part of the system.

Each work package names its files, its tests, and the condition that says it is done. The merge
contract does not change: `docker compose -f deploy/docker-compose.test.yml run --rm tests` stays
green with zero skipped, and `deploy/Dockerfile.test` stays pure Python — machine-learning code
gets its own image.

## Milestone 1 — done

SIM.1, SIM.2, WP0.1 and the episode-record half of WP0.4 are in. What that means, and how to
run it, is in `sim/README.md`.

- **SIM.1 reset:** the bridge answers `/g1/reset` → `/g1/reset_done`, scenarios live in
  `sim/scenarios/`, and `ablation_runner` runs N episodes back to back with a CLI. It fails
  fast on a rejected or unanswered reset and ignores Nav2 statuses and verdicts left over
  from the previous episode.
- **SIM.2 real dynamics:** Unitree's 12-DoF G1 walks under their released policy at the
  pinned commit in `sim/NOTICE`. The policy is an LSTM evaluated in numpy, pinned to
  TorchScript within 1e-5, so torch is not needed. A push makes it fall. A massless torso
  capsule stops a fall sinking through the floor. The scan plane is at 0.3 m.
- **WP0.1:** the evaluator folds sensors on every clock pulse and publishes
  `/monitor/observation` with per-source data health. Recordings now carry sensor values.
- **WP0.4 (records):** `core/episode_record.py`. Analysis followed in milestone 2.

Verified here as pure and headless tests: the main suite (1288 passed, 0 skipped) and
`sim/tests` (36 passed). **Not verified here:** the ROS stack end to end. This environment
has no Docker daemon and no ROS, so the bridge was exercised against stub ROS modules only.
The first `docker compose -f sim/docker-compose.sim.yml up --build` on a real machine is
the remaining check.

## Milestone 2 — done: E1 can run

Faults, progress from the robot's own sensors, a control arm, recovery, and the table are
in. Running E1 is four commands, listed under "Running E1" in `sim/README.md`.

- **SIM.4 faults:** `sim/g1sim/fault_spec.py` and `faults.py` implement `push`, `slip`,
  `weaken`, `stall`, `obstacle`, `block_route`, `odom_drift` and `scan_dropout`.
  - Each fault's effect is measured and pinned by a physics test.
  - The bridge publishes each injection on `/g1/fault_injected`. The runner stamps it with
    the clock tick as `injected_tick`.
  - Goal-image spoof is not done, because the sim has no camera yet.
- **Procedural scenarios:** `sim/g1sim/generator.py` provides `generate(family, seed)`.
  It is deterministic and varies start, goal, clutter, fault onset and parameters. The
  runner's `--scenario-dir` takes a directory of them.
- **Sensor-grounded progress (P12's keys):** `goal_active`, `closing_speed` and
  `no_progress` come from odometry and the commanded goal, on all three descriptors. The
  evaluator resets its per-episode state on `arm` and `reset`.
- **Ground-truth outcomes:** the bridge publishes `/g1/ground_truth`: a latched fall and
  the true distance to goal. The episode outcome is judged from these, not from any
  verdict, so the arm under test cannot grade itself.
- **Recovery:** `--policy off|detect|recover` in the runner. `recover` re-plans: it opens
  a fresh goal-status window, re-arms the monitor and re-sends the goal. The sim monitor
  runs `--passive` so a sweep survives faults. Records gain `policy` and `recoveries`.
- **WP1.1 control:** `core/spec_ablation.py` `flatten()`, with the `terminal_failure` choice
  exposed as a flag.
- **WP0.4 analysis:** `core/analysis.py` (Wilson, Fisher exact, bootstrap, detection scored
  against injected ground truth) and `tools/analyze_episodes.py`.
- **The sim spec is generated, not written:** `describer/generate_spec.py` repairs against
  the monitor's own load gates and writes provenance. The describer's prompt no longer
  offers a fault category the monitor cannot grade.

Verified here: the main suite (1398 passed, 0 skipped) and `sim/tests` (115 passed). The
bridge's fault and ground-truth paths were run against stub ROS.

**Still to do on a real machine:**
- generating the spec, which needs the LLM endpoint;
- the first full stack run;
- checking that Nav2 Humble preempts and re-plans on a re-sent `/goal_pose`.

## Where things stood before milestone 1

| piece | state today |
|---|---|
| MuJoCo bridge | kinematic: `qpos[0] += v_x_world*dt`, `qpos[2] = 0.78` pinned (`sim/mujoco_ros_bridge.py`, ~L109–119). No contact, no fall — `fell_over` cannot fire |
| reset | `backend/ablation_runner.py` publishes `/g1/reset` and waits for `/g1/reset_done`; **nothing subscribes** |
| goals | `sim/send_goal.py` reads stdin or uses a hardcoded default |
| Isaac | adapter descriptor only (`adapters/isaac_lab.json`); no simulator, image deleted |
| per-tick features | `SensorState.tick()` (`core/adapter_spec.py:1008`) has no call site — values stay at schema defaults |
| observations | `/monitor/observation` has no producer, though `api.OBSERVATION` is already recorded (`core/recording.py:56`) |
| monitor clock | `wall` and `replay` modes; `replay` is advanced by a driver via `POST /api/clock/step` (`backend/clock_node.py`) — usable for lockstep with a simulator |
| gridworld | **frozen** — no new MAAOS or MiniGrid work |

---

## WP-SIM — the simulator (critical path)

### SIM.1 Reset and scenarios
- Subscribe `/g1/reset` in `sim/mujoco_ros_bridge.py`: parse the scenario JSON, reset the MuJoCo
  state (`mj_resetData` plus the scenario's start pose, goals and obstacles), publish
  `/g1/reset_done`.
- Scenario files under `sim/scenarios/`, carrying layout, start, goals, fault type, fault onset
  and seed.
- Goals come from the scenario; `sim/send_goal.py` stays as a manual tool only.
- **Done when:** `ablation_runner` runs 20 episodes back to back, unattended, with no manual step.

### SIM.2 Real dynamics
- Replace the kinematic integration with physics stepping, driven by the G1 walking policy that
  Unitree releases in `unitree_rl_gym` (`deploy/deploy_mujoco/deploy_mujoco.py g1.yaml`, pretrained
  weights at `deploy/pre_train/g1/motion.pt` — verified; `g1.yaml` fixes the command in
  `cmd_init`, which the simulator replaces with `/cmd_vel`).
- The policy's velocity command comes from `/cmd_vel`, so Nav2 drives a walking robot.
- `upright_flag`, `base_roll`, `base_pitch` and `base_height` are computed from the physics state,
  not pinned.
- **Done when:** a push perturbation makes the robot fall and the `upright` proposition goes false
  in the monitor's verdict.

### SIM.3 Sensors
- Range by ray casting, publishing `/scan` and feeding `min_range`.
- An RGB camera rendered offscreen, feeding `image_similarity_to_goal`.
- Odometry from the physics state with configurable noise and bias.
- **Done when:** all 21 schema keys move during an episode — none sit at their defaults.

### SIM.4 Fault library
- Push perturbation, friction change, actuator weakening, spawned obstacle, blocked route,
  odometry drift, sensor dropout, goal-image spoof.
- Each fault records its **injection tick** and writes ground truth to the episode record, never
  to a monitor topic.
- **Done when:** every fault type fires at a scenario-chosen tick and its ground truth appears in
  the episode record.

### SIM.5 Lockstep and volume
- The bridge publishes `/clock`; Nav2 already sets `use_sim_time`.
- A sweep driver advances the monitor clock in `replay` mode, one step per simulated tick, so runs
  are deterministic and faster than real time.
- Several headless workers in parallel, one compose project each.
- **Done when:** a seeds × scenarios × arms sweep of at least 200 episodes runs without a person
  watching, and the same seed reproduces the same verdicts.

### SIM.6 Isaac Sim (after Paper 1's data exists)
- A G1 scene in Isaac Sim / Isaac Lab behind the existing `isaac_lab` adapter, with the same
  specification and scenario files.
- Needs a GPU host — open decision.
- **Done when:** the Paper 1 sweep runs in Isaac and the verdicts are comparable with MuJoCo's.

---

## WP0 — Monitor foundations (in parallel with SIM.1–SIM.2)

### 0.1 The feature pipeline
- Call `SensorState.tick()` once per monitor tick in the evaluator path
  (`backend/evaluator_node.py`).
- Publish `/monitor/observation` with `api.build_observation` (`core/api.py:426`). It is already in
  the recorder's set, so recordings gain sensors, `ap_values`, confidence and data health, joinable
  to verdicts on `seq`.
- Retire the legacy path that sets `seq=None` (`core/manifest.py:428`).
- **Tests:** an observation is published per tick with a `seq` matching the verdict;
  `replay_node play --diff` still exits 0 on an existing recording.

### 0.2 Semantics
- Settle the three-valued question in `core/automata.py`: `_observation_to_bdd` turns unknown
  propositions into `False`. Review and merge or close the branch `claude/lucid-shamir-440151`.
- **Done when:** the documentation's wording about the semantics matches what the code does.

### 0.3 One schema source
- Derive `CANONICAL_SENSOR_EVAL_KEYS` (`backend/adapters/base.py:106`) from `AdapterSpec` rather
  than the nav-only copy that drops the four pose keys.

### 0.4 Episode records and analysis
- `core/episode_record.py` (pure): arm, seed, scenario parameters, fault type, injection tick,
  ground truth, outcome, time-to-detection, timing. One writer, used by every runner.
- `tools/analysis/`: Wilson intervals, Fisher exact and bootstrap tests, precision, recall, F1,
  time-to-detection, and the paper tables generated straight from episode records.
- **Tests:** in the main suite, pure Python.

### 0.5 Planner independence (P12) — done

See the Status section of `docs/packages/P12-planner-independent-schema.md`. What remains
needs the robot:
- the generated robot spec, which replaces the interim `formulas_g1.json`;
- threshold calibration;
- confirming the depth topic.

- Ship `test_no_forbidden_topic_in_any_descriptor`.
- Move propositions off `/path_manager/status`: today six of the twenty-one keys come from it, and
  five of the eight propositions read them.
- **Why it is on the critical path:** simulation runs Nav2 and the robot runs TRAV. If the monitor
  reads planner status, simulation results do not transfer to the robot.

---

## WP1 — Paper 1

| id | work | files | done when |
|---|---|---|---|
| 1.1 | flattened specification, derived automatically | `core/spec_ablation.py: flatten(spec)` | unit tests: safety invariants, failure modes and terminal success preserved; intermediate progress removed |
| 1.2 | fair baselines | LLM judge with full observation history; VLM judge on MuJoCo renders | both run as arms in the sweep |
| 1.3 | cost instrumentation | per-tick wall-clock and tokens into the episode record (`_VERDICT_FIELDS` at `core/api.py:564` is closed, so not on the verdict) | the cost table is generated from records |
| 1.4 | sweep runner | `backend/ablation_runner.py` extended to seeds × scenarios × arms | one command produces the full main-table dataset |
| 1.5 | specification-generation evaluation | drafting pipeline run over both skills | schema-check pass rate and edits recorded |
| 1.6 | hardware validation | arm64 image (`RESUME.md:640`), recorded TRAV runs, on/off ablation | episodes recorded and replayed with identical verdicts |

---

## WP2 — Paper 2

| id | work | files | done when |
|---|---|---|---|
| 2.1 | feature encoding | `core/features.py` (pure): yaw → sin/cos, enum one-hot, sentinel bits, relative goal, freshness mask | unit-tested in the main suite |
| 2.2 | dataset builder | `tools/dataset/`: recordings → per-tick arrays joined on `seq` with phase and ground truth | a sweep's recordings become a train/test split |
| 2.3 | models | `ml/` behind an `[ml]` extra; `deploy/Dockerfile.ml`, `deploy/docker-compose.ml.yml`: Mahalanobis baseline, GRU encoder, per-phase models, phase-prediction head | the conditioning ablation runs end to end |
| 2.4 | learned propositions | evaluator plug-in: soft values, debounced to booleans, same `{name: bool}` contract | swappable per proposition against the hand threshold |
| 2.5 | anomaly node | `backend/anomaly_node.py`: subscribes observation and verdict, numpy inference from exported `.npz` weights, publishes `/monitor/anomaly` | runs live in the simulator alongside the monitor |
| 2.6 | on-device timing | the anomaly node in the arm64 image | ms/tick and memory measured on the Jetson |
| 2.7 | vision | visual encoder via ONNX Runtime at a reduced rate; MuJoCo renders, then Isaac | the visual arm runs in the sweep |

---

## Order of work

1. **SIM.1** reset → **SIM.2** real dynamics. Nothing else produces new evidence until these exist.
2. **WP0.1–0.4** alongside them.
3. **SIM.3–SIM.5** sensors, faults, lockstep sweeps, plus **WP0.5** planner independence.
4. **WP1** experiments in MuJoCo → **Paper 1 drafted**, while **WP2.1–2.3** train on the
   recordings those sweeps produce.
5. **SIM.6** Isaac and **WP1.6** hardware.
6. **WP2.4–2.7** → **Paper 2**.

## Open decisions

- Can TRAV run against MuJoCo? Ask Elias.
- Which GPU host runs Isaac, and from when?
- Paper 1's second skill: visual-goal approach (cheap) or pick-and-place (stronger, needs Isaac).
