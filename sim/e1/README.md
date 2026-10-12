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
