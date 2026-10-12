# LTL Skill Monitoring for Humanoids — Status

Pinhas Nehoray Aburmad · supervisor Prof. Ronen Brafman · BGU · October 2026

## 1. Scientific claim

Progress states let a runtime monitor catch skill failures that a flat set of safety rules
misses. A progress state is the semantic phase of a skill (starting, approaching,
confirming), each with its own conditions for entering, progressing and leaving, and its own
time limit.

The test isolates the structure. The full specification is compared with a control that has
the same propositions, safety rules and end conditions, but its phases merged into one and
its ordering removed. Both face the same faults and scenarios, and outcomes are judged from
simulator ground truth, so neither arm grades itself. The claim holds if the structured
specification detects more failures, detects them earlier, or recovers more often. We expect
this especially for failures that look safe at every instant but break the expected order or
rate of progress: stalls, and phases that run over time.

A supporting claim: such specifications can be generated reliably from plain language,
checked against the robot's sensor vocabulary, and grounded in the robot's own sensors
rather than its planner. That makes results transfer from simulation (Nav2) to the robot
(TRAV).

## 2. System setup and status

**How it works.**
1. A plain-language description of a skill is turned by an LLM into an LTL specification:
   phases, safety rules, time limits and failure modes. Spot compiles it into automata.
2. At runtime, an evaluator turns the robot's sensor streams into a fixed vocabulary once per
   tick. The vocabulary is identical on the real G1, MuJoCo and Isaac.
3. The monitor steps the automata and the phase machine and issues one of five
   interventions: continue, warn, re-plan, halt or abort.
4. Progress is measured from odometry against the commanded goal. The monitor reads nothing
   the planner says about itself, and a test enforces this.

**Test platform.**
- Unitree's 12-DoF G1 in MuJoCo, walking with Unitree's released policy.
- Eight injectable faults, each recorded with the clock tick on which it took effect.
- A deterministic scenario generator.
- An episode runner with three policies: record only, stop, or re-plan.
- Outcomes judged from simulator ground truth: a latched fall, and the true distance to the
  goal.
- An analysis tool for success rates (Wilson intervals, Fisher tests) and detection
  precision, recall and F1.

**Done and tested.**

| What | Scenario | Result |
|---|---|---|
| Falls are real | Walk at 0.5 m/s; push 300 N / slip μ 0.1 / torque ×0.5 at t = 3 s | Fell in all three |
| Stall | Legs stop at t = 3 s; the command continues | Stood still, upright, after 1.5 m |
| Odometry drift | 0.1 m/s from t = 3 s | Robot unaffected; the reported pose drifts |
| Surprise obstacle | Wall appears across the route | Robot stops at it; lidar range 2.91 → 1.83 m within 1 s |
| Monitor sees a stall the planner cannot | Stall at t = 6 s, goal 11 m away, monitor at 1 Hz | Command stays 0.5 m/s, measured speed ≈ 0.01 m/s; `no_progress` fires at t = 17 s (10 s debounce + 1 tick) |
| Reset | A clean episode after any fault | Bit-identical to a fresh one |
| Scenario generator | 10 families × 100 seeds | All 1000 valid and reproducible |
| Software | 1418 monitor tests + 115 simulator tests | All pass in CI |

Every scenario in the table is a **single episode**. These results show the mechanism works;
they are not statistics.

**Not done.**
- **The E1 experiment.** It has not run, so there are no comparative results yet.
- **Spec generation.** The specification has not yet been generated with the real LLM. The
  shipped `formulas_g1.json` is a labelled, hand-written interim spec.
- **The full stack.** Docker, ROS 2 and Nav2 have not run end to end on a real machine.
  These parts were tested here with stand-ins for ROS and the LLM.
- **Robot thresholds.** The G1 robot thresholds are uncalibrated.
- **Not started:** a simulated camera, faster-than-real-time sweeps, Isaac Sim, and Paper 2.

## 3. Research directions

1. **First full run on the lab machine.** Generate the spec, bring up the stack, and run one
   episode per policy.
2. **E1.**
   - The generated specification versus the flattened control.
   - Each fault family × 20 seeds × 3 policies.
   - Reported with confidence intervals, significance tests, and detection precision and
     recall.
3. **The robot.**
   - Generate the G1 specification.
   - Record runs with the TRAV navigation app and calibrate the thresholds.
   - Compare navigation success with the monitor on and off.
4. **Paper 2** keeps the LTL structure and learns the grounding:
   - learned propositions in place of hand thresholds;
   - anomaly detection conditioned on the current LTL phase, for failures no rule covers;
   - within budget on the Jetson AGX.
5. **Later.** Isaac Sim, more skills (pick and place), and the specification as a reward
   machine for learned policies.

## 4. Try it yourself

You need Linux with `git` and Python 3.10 or newer. No GPU, ROS or Docker is needed. It was
developed on Ubuntu 24.04.

```bash
git clone https://github.com/pinhas019/LtlMonitor.git && cd LtlMonitor
git checkout claude/monitoring-paper-submission-1ryynf
python3 -m venv .venv && . .venv/bin/activate
pip install mujoco "numpy<2" pyyaml pytest
sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree

python sim/demo.py                     # stall at t=5 s: no_progress turns TRUE at t=16 s
python sim/demo.py --fault push        # the robot falls: upright = NO
python sim/demo.py --fault none        # healthy walk: closing ≈ 0.45–0.48 m/s, never flagged
python -m pytest -q sim/tests          # 115 simulator tests (1 skips without torch), 1–2 min
```

`demo.py` walks the G1 toward a goal, injects the fault, and passes the robot's odometry
through the monitor's real sensor processing at 1 Hz. Each line it prints shows the time,
the distance to the goal, the closing speed, `no_progress` and whether the robot is upright.

**With Docker:**

```bash
docker compose -f deploy/docker-compose.test.yml run --rm tests   # the full monitor test suite
docker compose -f deploy/docker-compose.test.yml up console        # web console, mock data: http://127.0.0.1:8799
```

The full simulation stack (`sim/docker-compose.sim.yml`) and the robot/server stacks
(`deploy/docker-compose.{robot,server}.yml`) are described in
[`sim/README.md`](../sim/README.md). They are the next step to bring up.
