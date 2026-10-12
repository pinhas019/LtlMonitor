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
