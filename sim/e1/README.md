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
object and gripper as ground truth.
