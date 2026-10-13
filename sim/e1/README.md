# E1 — do progress states matter?

E1 compares a monitor running the **generated specification** with **the same specification
with its phase order removed**. Both face the same faults in the same scenarios. Results:
[`docs/e1/results.md`](../../docs/e1/results.md).

## Arms

All three specs were committed before the first episode ran (`66a64fa`).

| arm | spec | what it is |
|---|---|---|
| `full` | `skill_monitor/specs/formulas_g1_sim.json` | The LLM-generated spec. Two phases, each with its own time budget: GettingStarted (15 s), Approaching (60 s, progress = `not stalled`). A terminal failure on `stalled`. |
| `flat` | `formulas_g1_sim_flat.json` | `spec_ablation.flatten(full)`: one phase, budgets summed (75 s), progress `True`, the ordered LTL chain replaced by `F(success)`. Keeps the terminal failure. |
| `flat_strict` | `formulas_g1_sim_flat_strict.json` | As `flat`, without the terminal failure. |

**How the spec was generated.** The describer's prompt is `formulas_prompt(description,
mujoco vocabulary)`, kept verbatim in
[`docs/e1/describer_prompt.txt`](../../docs/e1/describer_prompt.txt). It was answered by
Claude, in the development session, acting as the describer LLM. The reply went through
`generate_spec`'s gates unchanged and was accepted on the first attempt. Provenance is in
`formulas_g1_sim.provenance.json`.

## Scenarios, policies, episodes

- **Scenarios.** 10 families × seeds 0–19, from `sim/g1sim/generator.py`, each deterministic
  per seed:
  - `clear` and `cluttered` (no fault);
  - one family per fault: push, slip, weaken, stall, obstacle, block_route, odom_drift,
    scan_dropout.
- **Policies** (`core/episode_outcome.decide_step`). An intervention is REPLAN or worse, or
  a terminal FAILURE.
  - `off`: the monitor reports and nothing acts.
  - `detect`: the first intervention ends the episode.
  - `recover`: an intervention re-arms the monitor, clears the navigator's obstacle memory
    and re-sends the goal, at most twice.
- **Outcome**, judged from the simulator and never from the monitor.
  - Success is the navigator reporting arrival **and** the true distance being ≤ 0.5 m.
  - A latched fall is a failure under every policy.
  - The time limit is the scenario's 60 s.
- **Detection**, scored from the `off` episodes (`core/analysis.detection`).
  - The first intervention at or after the injection tick is a detection.
  - An intervention on a fault-free episode, or before the injection, is a false alarm.

## How it runs

`run_e1.py` runs each episode in one process, headless:

| part | real or stand-in |
|---|---|
| G1 in MuJoCo, Unitree's policy, fault library | real (`sim/g1sim`) |
| Evaluator: `GenericClientNode` + `mujoco` descriptor | real |
| Monitor: `LtlMonitorNode` + `MultiMonitor` (Spot 2.16), `--passive` | real |
| Episode decision and records | real (`episode_outcome`, `episode_record`) |
| ROS transport | stand-in: `tests/ros_stub.py` nodes plus a bus delivering each published message to every subscriber of its topic |
| Nav2 | stand-in: `sim/g1sim/navigator.py`, same for every arm (see below) |
| Clock | simulated time: monitor 1 Hz, odometry and scan 10 Hz, control 50 Hz |

`navigator.py` is A* on the scenario map, plus a 2 s memory of scan hits for obstacles the
map does not contain, with a pure-pursuit follower. Its parameters come from
`sim/nav2_params.yaml`:
- maximum speed 0.26 m/s;
- goal tolerance 0.25 m;
- abort after 0.05 m of progress in 30 s.

It plans from reported odometry, as Nav2 does. The full ROS 2 + Nav2 stack is the deployed
form; this harness is what makes thousands of episodes possible without it.

## Reproduce

```bash
# Spot comes from conda-forge
micromamba create -p .e1 -c conda-forge python=3.12 spot pyyaml "numpy<2"
.e1/bin/pip install mujoco matplotlib
sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree
.e1/bin/python sim/e1/run_e1.py --seeds 0-19 --out e1.jsonl          # ~15 min on 4 cores
.e1/bin/python sim/e1/summarize_e1.py e1.jsonl --out docs/e1
```

`run_e1.py` skips episodes already in `--out`, so an interrupted sweep resumes where it
stopped.

## Findings (1800 episodes: 10 families × 20 seeds × 3 arms × 3 policies)

Full tables are in [`docs/e1/results.md`](../../docs/e1/results.md). The raw records are in
`docs/e1/e1_episodes.jsonl.gz`.

1. **The phase structure added almost nothing over a flat spec with the same rules.**
   - On nine of ten families, `full` and `flat` detect exactly the same episodes at the same
     tick.
   - The only difference is one stall in fifteen. There the legs crawled at 0.044 m/s, just
     under the 0.05 m/s progress threshold. Only the Approaching phase's 60 s budget caught
     it (TIMEOUT).
   - Stalls that caused a failure: `full` caught 15/15, `flat` 14/15 (Fisher p = 1.0).
2. **What carries stall detection is the progress proposition, wherever it sits.**
   - Remove the rule that reads it (`flat_strict`) and stall detection falls to 1/15.
     Against `full`: p = 2·10⁻⁷.
   - The value is in grounding progress in odometry (`no_progress`), not in the ordering.
3. **Falls are caught within 1–2 ticks** whatever the spec: push 19/20, weaken 19/20, slip
   10/11 of the episodes that failed.
   - The one miss in each family is an episode that ended on the fall in the same tick the
     monitor saw it.
4. **Acting on the monitor lowered success in this setup.**
   - Success under `off` was 63%. Under `detect` it was 43% (−20 pp, p = 9·10⁻⁵); under
     `recover` 52% (−11 pp, p = 0.03). This held for every arm.
   - The cause is `collision_imminent` (`min_range < 0.3`). It fired on 35 of 40
     surprise-obstacle episodes and on 3 of 20 cluttered ones, all of which the navigator
     completed anyway.
   - Re-planning cannot fix the faults that remain: a stall is permanent, and a fall ends
     the episode.
5. **Blind spots.**
   - `scan_dropout`: 0/20 detected. No proposition reads data freshness.
   - `odom_drift`: 1 of the 8 resulting false arrivals detected. Every distance is measured
     in the frame that drifts.

**Reading.** In this skill, the claim that progress *states* catch what flat rules miss is
not supported beyond a single slow-crawl case. What the results support is narrower:
**sensor-grounded progress** is what catches the failure the planner cannot see.

Two things limit any structural effect here:
- **The skill is short.** There are two phases, and stall detection fires in both.
- **The safety threshold is set loosely against the navigator's clearance.**

Three follow-ups:
- longer, multi-phase skills, where an order violation is not also a progress violation;
- a calibrated proximity threshold;
- data-health and independent-position propositions (Paper 2's learned grounding).

**Limits.**
- One generated spec.
- A navigator stand-in for Nav2.
- 20 seeds per family.
- Single-fault scenarios.
- A monitor running at 1 Hz.
- The `detect` policy, by construction, turns every intervention into a failed episode.

---

# E1b — a longer skill: fetch and deliver

E1's skill was too short for order to matter. E1b repeats the comparison on a four-phase
manipulation skill, where the right condition depends on the phase: "the object is held"
is required while carrying and meaningless while walking to it. Results:
[`docs/e1b/results.md`](../../docs/e1b/results.md).

## The skill

`sim/e1/carry/task.py`. The robot walks to an object, grasps it, carries it to a drop-off
station and puts it down. Objects and drop-offs are 2.5–4 m apart in a 6.8 m arena;
150 s limit.

- **Executor.** `CarryExecutor` sequences the navigator (the same one as E1) open-loop, as
  a plain behaviour tree does. Grasp and release are actions that "return". It never
  checks that the grasp took or that the object is still held, and it reports success
  when its sequence finishes.
- **Grasp.** The legs-only G1 has no arm. A grasp attaches the object if the pelvis is
  within 0.6 m of it (`G1Sim.grasp`); a release sets it down in front of the robot.
- **Sensing.** The evaluator gets `sim/e1/carry/mujoco_carry.json`: the navigation sources
  plus the task (`/task`, the drop-off), the object's position (`/object/pose`) and the
  gripper (`/gripper/holding`). The new keys are in `carry_schema.json`.
- **Families** (8 × seeds 0–19):
  - `clear`, `cluttered` (no fault);
  - `grasp_fail`: the first grasp does not take;
  - `drop`: the object falls a few seconds into the carry;
  - `skip_pickup`: the plan goes straight to the drop-off, empty-handed;
  - `object_moved`: the object is moved before the robot reaches it;
  - `stall`, `push`: the simulator's faults, at a random moment of the task.

## Arms

All committed before the first episode (`348239e`).

| arm | spec | what it is |
|---|---|---|
| `full` | `formulas_g1_carry.json` | Generated from `specs/descriptions/g1_fetch_and_deliver.md`, the same way as E1 (prompt in [`docs/e1/describer_prompt_carry.txt`](../../docs/e1/describer_prompt_carry.txt)). Four phases: WalkToObject (45 s), Grasp (10 s), Carry (60 s, invariant `holding_object`), Place (10 s). |
| `flat` | `formulas_g1_carry_flat.json` | `flatten(full, invariants="shared")`: one phase; the invariant is what every phase states (`upright and not obstacle_too_close`); 125 s budget; `F(success)`. |
| `flat_strict` | `formulas_g1_carry_flat_strict.json` | As `flat`, without the terminal failure. |

Why `shared`: conjoining every phase's invariant would demand `holding_object` from the
first tick, which is not a control but a spec that is always violated. A phase-specific
condition cannot be stated without phases; that is the thing being measured.

**The completion check, for every arm.** When the executor reports the task done, the
monitor must confirm it within 2 ticks (its spec SATISFIED, or terminal success reached),
or the runner raises `completion_unverified`. It is the one check a flat spec can make, so
leaving it out would deny the control a fair chance. It comes too late to save the
attempt, though: the question is whether a monitor catches the fault **during** the task.

Outcome is ground truth: success means the object rests within 0.5 m of the drop-off, is
not held, and the robot never fell.

## Reproduce

```bash
.e1/bin/python sim/e1/run_e1b.py --seeds 0-19 --out e1b.jsonl
.e1/bin/python sim/e1/summarize_e1.py e1b.jsonl --out docs/e1b --title "E1b results"
# or, from the committed records:
python sim/e1/summarize_e1.py <(zcat docs/e1b/e1b_episodes.jsonl.gz) --out /tmp/e1b
```

## Findings (1440 episodes: 8 families × 20 seeds × 3 arms × 3 policies)

1. **Phase-specific faults are caught during the task only by the full spec.** Episodes
   that failed under `off`, caught before the executor claimed success:

   | fault | full | flat | first full-spec alarm | median s to detection (full / flat) |
   |---|---|---|---|---|
   | drop | 20/20 | 0/20 | Carry invariant (`holding_object`) | 1 / 14 |
   | grasp_fail | 20/20 | 0/20 | Grasp phase time budget | 4 / 19 |
   | object_moved | 8/20 | 0/20 | phase time budget | 31 / 32 |
   | skip_pickup | 0/20 | 0/20 | — (completion check only) | 21 / 21 |
   | push (fall) | 13/13 | 13/13 | `fell_over` | 1 / 1 |
   | stall | 11/11 | 11/11 | terminal failure (`stalled`) | 11 / 11 |

   The flat arms catch drop, grasp_fail and object_moved only at the completion check.
   Paired by scenario, the full spec was earlier on 20/20 drops and 20/20 failed grasps
   (sign test p = 1.9·10⁻⁶ each) and never later on any family.
2. **Earlier detection means faster delivery under `recover`.** Median simulated seconds to
   a delivered object, scenarios both arms completed: drop 34.5 vs 63; grasp_fail 37 vs 72;
   object_moved 70 vs 75. The full spec was faster on 20/20 drops and 20/20 failed grasps
   (p = 1.9·10⁻⁶ each), on 7 of the object_moved scenarios, and slower on none.
3. **Final success is the same.** `recover`: full 82%, flat 84%, flat_strict 84%, against
   35% under `off` (+48 to +49 pp, p < 10⁻¹⁷). These faults can be repaired after the fact:
   re-perceive and fetch the object again. The completion check is enough to trigger that,
   only later.
4. **Where the full spec fails.**
   - `skip_pickup` is caught by nobody during the task. The progress proposition is "closer
     to *where the robot is walking*", not "closer to *the object*", so walking straight to
     the drop-off looks like progress in WalkToObject, and the executor finishes inside the
     45 s budget.
   - On slow partial stalls (legs at 15–17% strength) the phase budgets fire on runs that
     would have finished late. Re-planning then re-arms the monitor at phase one while the
     task is mid-way. Stall under `recover`: full 6/20, flat 9/20 (Fisher p = 0.51).
   - False alarms: 3/20 cluttered episodes (`collision_imminent`), the same in every arm.
   - `detect` lowers success by 2–4 pp (n.s.) in every arm.

**Reading.** With a phase-dependent condition, progress states pay off: the full spec
catches lost and failed grasps seconds after they happen, where a flat spec with the same
propositions can only notice at the end, and re-planning on the early alarm halves the
time to deliver. They do not raise final success here, because the faults are recoverable
and the end-of-task check triggers the same repair. Where failure is not recoverable after
the fact (a fragile object, a deadline, a human waiting), the latency is the outcome.

**Follow-ups.**
- Phase-relative progress ("closer to the phase's target"), which would catch
  `skip_pickup`.
- Re-arming the monitor at the phase the task is in, not at phase one.
- Budgets calibrated from nominal runs rather than from the description.
- A deadline or an irreversible-failure variant, to turn latency into outcome.

**Limits.** All of E1's, plus a simulated grasp (attachment, no arm), and perception of the
object and gripper as ground truth. The ROS 2 rerun below removes the last two of these
from the monitor's side: it no longer reads the gripper, and it sees the object through
noise and missed detections.

---

# E1b over ROS 2 — the outcome inferred from messages only

The run above delivered Python objects to the node callbacks in one process, and the
monitor learned "held" from `/gripper/holding`, which was the simulator's own flag. This
rerun closes both gaps:

- **Real transport.** The evaluator and the monitor run as their own processes
  (`python -m skill_monitor.backend.evaluator_node` / `monitor_node`, exactly as
  deployed), talking over DDS (ROS 2 Humble, FastDDS) to a driver node
  (`sim/e1/ros_e1b.py`) that owns the simulator, the navigator and the executor.
  Episode logic is `run_e1b.play_episode`, shared with the in-process run; only the
  transport differs (`RosLink` vs `InProcess`).
- **What the monitor reads.** `/odom` (nav_msgs/Odometry), `/scan`
  (sensor_msgs/LaserScan), `/goal_pose`, `/task` (the drop-off) and `/object/pose`
  (geometry_msgs/PointStamped from a perception stand-in: the object's position with
  2 cm noise per axis and 5% missed detections). Nothing else: no gripper, no executor
  status (`/task/status` is published but forbidden to the monitor by the
  planner-independence guard), no simulator state.
- **"Held" is inferred** by the evaluator's `object_held` extractor: the object is lifted
  (z ≥ 0.3 m; it rests at 0.08 m) and within 0.5 m of the base from odometry. The spec's
  proposition is unchanged (`holding == True`); the key's grounding changed after the
  spec was generated.
- **Success and failure are the monitor's own conclusion**: its last verdict
  (SATISFIED / terminal success, VIOLATED / terminal failure, or undecided), scored
  against the simulator's ground truth, which never leaves the driver.
- **Lockstep on simulated time.** The driver publishes `/clock` (the evaluator runs with
  `use_sim_time`), then each second's sensor messages, then the tick, and waits for that
  tick's verdict before simulating on. Each worker has its own `ROS_DOMAIN_ID` and refuses
  a domain where another monitor already answers.

## Reproduce (ROS 2)

```bash
# ROS 2 Humble from RoboStack, Spot from conda-forge, MuJoCo from pip
micromamba create -p .ros -c robostack-staging -c conda-forge python=3.11 \
    ros-humble-ros-base spot pyyaml "numpy<2" matplotlib pytest
.ros/bin/pip install mujoco
sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree
.ros/bin/python sim/e1/ros_e1b.py --seeds 0-19 --workers 4 --out e1b_ros.jsonl
python sim/e1/summarize_e1.py e1b_ros.jsonl --out docs/e1b_ros --title "E1b over ROS 2"
```

While it runs, `ROS_DOMAIN_ID=20 ros2 node list` shows `ltl_generic_client`,
`ltl_monitor_node` and `e1b_driver`, and `ros2 topic echo /monitor/verdict` the verdicts.


## Findings over ROS 2 (1440 episodes, 8 families × 20 seeds × 3 arms × 3 policies)

Full tables: [`docs/e1b_ros/results.md`](../../docs/e1b_ros/results.md); raw records:
`docs/e1b_ros/e1b_ros_episodes.jsonl.gz`. Transport health: 2 verdict timeouts and 14
late duplicate verdicts (discarded) in about 100 000 ticks; 30 minutes on 4 cores.

1. **The monitor infers the outcome from the messages, and never claims a false success.**
   Policy `off`, its last verdict against ground truth:

   | arm | succeeded → said success | failed → said success | failed → said failure | failed → undecided |
   |---|---|---|---|---|
   | full | 52/56 | **0/104** | **71/104** | 33/104 |
   | flat | 52/56 | 0/104 | 22/104 | 82/104 |
   | flat strict | 53/56 | 0/104 | 24/104 | 80/104 |

   The 4 successes it called failures are the 3 close passes in clutter
   (`collision_imminent`) and one slow stall that finished late, the same in every arm.
   The full spec names a failure as a failure three times as often as the flat ones; a
   flat spec mostly stays undecided (it waits for an eventual completion that never comes).
2. **The headline replicates with inferred holding and noisy perception.** Caught during
   the task: drop 20/20 vs 0/20 (1 s vs 14 s), failed grasp 20/20 vs 0/20 (4 s vs 19 s),
   both 20/20 earlier (p = 1.9·10⁻⁶); object moved 7/20 vs 0/20. Under `recover`, time to
   deliver 34.5 vs 63 s after a drop and 36.5 vs 72 s after a failed grasp (20/20 faster,
   p = 1.9·10⁻⁶). Success: full 82%, flat 84%, flat strict 84%, from 35% under `off`.
3. **What the transport changed.** Noise-free, 18/18 pilot episodes were identical to the
   in-process run; with noisy perception 23/24. Over the sweep the flat arm caught 9 of 11
   failed stalls instead of 11: topics are not ordered with respect to one another, so a
   message published just before a tick is sometimes folded into the next window, and a
   slow crawl's `no_progress` debounce can restart. That is the same asynchrony a robot
   has.

**Limits that remain.** The perception stand-in is the simulator's object position plus
noise and misses, not a camera. The grasp is an attachment. One spec per skill.

## What the phases add, and against what (2080 episodes over ROS 2)

Three comparisons were added on the same 160 scenarios, over ROS 2 as above:

- **`ltl_only`** (`formulas_g1_carry_ltl.json`, `spec_ablation.strip_phases`): the full
  spec minus its phase machine. The ordered-task automaton, the safety automata and both
  terminals are unchanged. 480 episodes (off, detect, recover).
- **`closed_loop`**: no monitor acting. The executor carries the checks a developer would
  write into a behaviour tree (`CarryExecutor(closed_loop=True)`): "still holding it?"
  while carrying, and "is it at the drop-off?" before reporting success. It reads the same
  noisy perception and re-plans with the same `replan()`. 160 episodes (off).
- **Deadlines** (analysis only; a deadline judges an episode and changes nothing the robot
  does). Delivered within k × the scenario's nominal time to deliver: the straight-line
  walk at 0.22 m/s (the median of the fault-free runs) plus 4 s of grasp and release.

Delivered by a deadline (all 160 scenarios, families pooled):

| way of running the task | 1.25× | 1.5× | 2× | no deadline |
|---|---|---|---|---|
| full spec + re-plan | 58% | **64%** | 73% | 82% |
| flat + re-plan | 34% | 36% | 54% | 84% |
| LTL only + re-plan | 32% | 36% | 51% | 83% |
| hand-coded checks, no monitor | **74%** | **81%** | 84% | 85% |
| no monitor | 34% | 34% | 34% | 35% |

The p-values below are for 1.5×.

1. **The phase machine is what does the work, not LTL.** LTL-only catches no drop and no
   failed grasp during the task (0/20 each, the same as flat): the ordered automaton has
   no rejecting state, so "eventually" can always still come true. Against the full spec at
   1.5×: 36% vs 64% (Fisher p = 7·10⁻⁷).
2. **Earlier detection turns into success once time matters.** With no deadline every
   monitored arm ends at 82–84%. With a deadline of 1.5× the nominal time, the full spec
   delivers 64% against flat's 36% (p = 1.3·10⁻⁶); at 2×, 73% vs 54% (p = 5·10⁻⁴).
3. **A hand-coded closed-loop executor does as well or better.**
   - Drop and failed grasp: the same delivery times (34.5 vs 34.5 s; 36 vs 36.5 s).
   - Object moved: 46 vs 70 s. Skipped pick-up: 32.5 vs 57.5 s.
   - At 1.5×: 81% vs 64% (p = 0.001).
   - It knows its own state ("I am carrying now"). The monitor has to infer the phase from
     what it observes, and it never left WalkToObject when the pick-up was skipped.
   - Final success is the same (85% vs 82%, p = 0.65).

**Reading.** On these faults the generated monitor gets most of what hand-written checks
get, but not all of it. It does so without a line of task-specific code: the checks come
from the plain-language description. What the comparison does not show is the monitor's
claimed advantage over hand-coded checks:
- generality across skills;
- catching failures the developer did not anticipate;
- independence from the executor's own (possibly wrong) belief about its state.

Each needs a test of its own: several skills, faults outside the developer's list, and
an executor whose state estimate is wrong.

## Unanticipated faults (design, committed before the sweep)

**Question.** Does an independent monitor, generated from the task description, catch
failures that the hand-coded executor has no check for? And does it add anything on top
of that executor (`closed_loop_full`: the same checks, plus the full monitor)?

**Families.** One per requirement the description states and the executor does not check
(`task.UNANTICIPATED`; parameters deterministic per seed). The executor checks only
"holding while carrying" and "at its drop-off before reporting success".

| requirement (g1_fetch_and_deliver.md) | family | injected as |
|---|---|---|
| put it down at the drop-off station: the *commanded* one, on `/task` | `wrong_dropoff` | the executor's own drop-off is 1.5-2.5 m off (stale configuration, frame error) |
| reach it in ~45 s, carry it in ~60 s | `slow_nav` | from 5-15 s, the navigator's speed limit drops to 25-35% |
| get steadily closer | `detour` | the carry leg goes via a waypoint 2.5-3.5 m off the line (planner bug) |
| never come dangerously close to an obstacle | `close_pass` | obstacle inflation cut to 0.05 m, a pillar on the object -> drop-off line |

**Arms.** All over ROS 2, 20 seeds each:
- `full` and `flat` (off, recover);
- `closed_loop` (off: no monitor acting);
- `closed_loop_full` (off, recover).

`closed_loop_full` also runs on the 8 original families, to see whether the monitor on
top costs anything where the executor's checks suffice.

**Main metric: silent failures.** A failed episode that nothing flagged.
- **What counts as failed:**
  - `wrong_dropoff`: not delivered to the commanded drop-off;
  - `slow_nav` and `detour`: not delivered within 1.5× the nominal time;
  - `close_pass`: true clearance under 0.3 m at any time (from the simulator's geometry,
    `timing.min_clearance_m`), or not delivered.
- **What counts as flagged:**
  - for monitor arms, any monitor intervention, the completion check included;
  - for `closed_loop`, an executor recheck or an aborted executor (its record's monitor
    fields are ignored, since no monitor acts in that deployment);
  - for `closed_loop_full`, either.

**Predictions** (from the plan, before any episode):
- **`wrong_dropoff`.** `closed_loop` silent on all of them. `full` catches it when the
  object is released away from the commanded drop-off (Carry invariant); `flat` catches it
  at completion. Re-planning cannot fix it (it reuses the wrong drop-off), so the value is
  detection.
- **`slow_nav`.** `full` catches it by its phase time budgets, `flat` only by its 125 s
  total, and `closed_loop` is silent.
- **`detour`.** Possibly nobody: the monitor measures progress toward the goal the
  executor publishes. `full` catches it via the Carry budget only if the detour is long
  enough.
- **`close_pass`.** Every monitor arm flags `collision_imminent`; `closed_loop` is silent.
  The rule's false-alarm rate on safe passes (E1) is reported next to it.

A 2-seed mechanics pilot (not counted) already suggests that `slow_nav` and `detour` stay
inside the monitor's budgets. The predictions are kept as written.
