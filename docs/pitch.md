# LTL Skill Monitoring for Humanoids — Status

Pinhas Nehoray Aburmad · supervisor Prof. Ronen Brafman · BGU · October 2026

## 1. Scientific claim

Progress states let a runtime monitor catch skill failures that a flat set of safety rules
misses. A progress state is the semantic phase of a skill (starting, approaching,
confirming), each with its own conditions for entering, progressing and leaving, and its own
time limit.

The test (E1) isolates the structure. The generated specification is compared with a control
that has the same propositions, safety rules and end conditions, but its phases merged and
its order removed. Both face the same faults in the same scenarios, and outcomes are judged
from simulator ground truth, so neither arm grades itself.

**What E1 found (1800 episodes).**
- The structure alone added **one detection in fifteen stalls**: a slow crawl that only a
  phase time budget caught (15/15 vs 14/15, p = 1.0).
- What caught stalls was **progress grounded in odometry**. Remove that rule from the flat
  control and stall detection falls to 1/15 (p = 2·10⁻⁷).

So, for this short two-phase skill, the claim is not supported. The supported claim is
narrower: sensor-grounded progress catches the failure the planner cannot see. Whether
phases matter needs a longer, multi-phase skill, where breaking the order is not also a
progress failure.

A supporting claim also holds. The specification was generated from plain language in one
attempt and passed the monitor's own load checks. The monitor reads no planner self-report,
and a test enforces that.

## 2. System setup and status

**How it works.**
1. A plain-language description of a skill is turned by an LLM into an LTL specification:
   phases, safety rules, time limits and failure modes. Spot compiles it into automata.
2. At runtime, an evaluator turns the robot's sensor streams into a fixed vocabulary once per
   tick. The vocabulary is identical on the real G1, MuJoCo and Isaac.
3. The monitor steps the automata and the phase machine and issues one of five
   interventions: continue, warn, re-plan, halt or abort.
4. Progress is measured from odometry against the commanded goal. The monitor reads nothing
   the planner says about itself.

**Test platform.**
- Unitree's 12-DoF G1 in MuJoCo, walking with Unitree's released policy.
- Eight injectable faults, each recorded with the clock tick on which it took effect.
- A deterministic scenario generator.
- An episode runner with three policies:
  - `off` (record only);
  - `detect` (stop at the first intervention);
  - `recover` (re-plan, at most twice).
- Outcomes judged from simulator ground truth.

**E1 setup.**
- **The specification.** Generated from the description by Claude, acting as the describer
  LLM: it was given exactly the describer's prompt. It was accepted on the first attempt and
  committed before any episode ran.
- **Three arms:**
  - `full`: two phases with 15 s and 60 s budgets;
  - `flat`: one phase, budgets summed;
  - `flat strict`: as `flat`, without the terminal-failure rule.
- **The run.** 10 scenario families × 20 seeds × 3 arms × 3 policies = 1800 episodes.
- **What ran headless:**
  - the real evaluator and monitor, with Spot;
  - the MuJoCo G1;
  - a Nav2 stand-in configured from the repository's Nav2 parameters (0.26 m/s), the same
    for every arm.

**E1 results.** Failures caught: faults that made the episode fail under `off`, detected by
each arm.

| Family | Episodes that failed | full | flat | flat strict | Median latency |
|---|---|---|---|---|---|
| push 300 N | 20/20 (fell) | 19 | 19 | 19 | 1 s |
| weaken | 20/20 (fell) | 19 | 19 | 19 | 2 s |
| slip | 11/20 (fell) | 10 | 10 | 10 | 7 s |
| stall | 15/20 (timeout) | **15** | 14 | **1** | 11 s |
| odom drift | 8/20 (false arrival) | 1 | 1 | 1 | — |
| scan dropout | 0/20 | — | — | — | not detected (0/20) |
| obstacle, blocked route | 0/40 | — | — | — | alarms on 35/40 that succeeded |
| clear / cluttered | 0/40 | — | — | — | 3/40 false alarms |

Acting on the monitor lowered success, in every arm alike:
- `off`: 63%;
- `detect`: 43% (−20 pp, p = 9·10⁻⁵);
- `recover`: 52% (−11 pp, p = 0.03).

The cause is the proximity rule (`min_range < 0.3 m`). It fires when the robot passes a
surprise obstacle that the navigator clears safely. Re-planning cannot fix a permanent stall
or a fall.

**Also done and tested.**
- Falls are physical.
- Reset is bit-identical.
- 1418 monitor tests and 125 simulator tests pass in CI.

Full tables and raw records: [`docs/e1/results.md`](e1/results.md); the method:
[`sim/e1/README.md`](../sim/e1/README.md).

**Not done.**
- **The full stack.** Docker, ROS 2 and Nav2 have not run end to end on a real machine. E1
  ran headless with a Nav2 stand-in.
- **One spec.** Only one generated specification has been evaluated, on one skill.
- **The robot.** No G1 runs with TRAV yet; the robot thresholds are uncalibrated.
- **Not started:** a simulated camera, Isaac Sim, and Paper 2.

## 3. Research directions

1. **Make the structure testable** (what E1 says to do next).
   - A longer skill with several ordered phases, where a step skipped or done out of order
     is not also a stall.
   - Several specifications generated per skill.
2. **Fix what E1 exposed.**
   - Calibrate the proximity rule against the navigator's clearance.
   - Add data-health propositions: a stale lidar must count.
   - Add a position source independent of odometry, to catch drift.
3. **The robot.**
   - Generate the G1 specification.
   - Record runs with TRAV and calibrate the thresholds.
   - Compare navigation success with the monitor on and off.
4. **Paper 2: symbolic structure, learned grounding.**
   - Learned propositions in place of hand thresholds.
   - Anomaly detection conditioned on the current LTL phase.
   - Within budget on the Jetson AGX.

   E1's blind spots (drift, stale sensors) are its motivation.
5. **Later.** Isaac Sim, pick and place, and the specification as a reward machine.

## 4. Try it yourself

You need Linux with `git` and Python 3.10 or newer. No GPU, ROS or Docker is needed. It was
developed on Ubuntu 24.04.

```bash
git clone https://github.com/pinhas019/LtlMonitor.git && cd LtlMonitor
git checkout claude/monitoring-paper-submission-1ryynf
python3 -m venv .venv && . .venv/bin/activate
pip install mujoco "numpy<2" pyyaml pytest matplotlib
sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree

python sim/demo.py                     # stall at t=5 s: no_progress turns TRUE at t=16 s
python sim/demo.py --fault push        # the robot falls: upright = NO
python sim/demo.py --fault none        # healthy walk, never flagged
python -m pytest -q sim/tests          # simulator tests, 1–2 min
python sim/e1/summarize_e1.py <(zcat docs/e1/e1_episodes.jsonl.gz) --out /tmp/e1   # E1 tables from the raw records
```

`demo.py` walks the G1 toward a goal, injects the fault, and passes the robot's odometry
through the monitor's real sensor processing at 1 Hz. Each line it prints shows the time,
the distance to the goal, the closing speed, `no_progress` and whether the robot is upright.

**Re-run E1** (about 15 minutes on 4 cores; needs Spot, which comes from conda-forge):
see [`sim/e1/README.md`](../sim/e1/README.md), section "Reproduce".

**With Docker:**

```bash
docker compose -f deploy/docker-compose.test.yml run --rm tests   # the full monitor test suite
docker compose -f deploy/docker-compose.test.yml up console        # web console, mock data: http://127.0.0.1:8799
```
