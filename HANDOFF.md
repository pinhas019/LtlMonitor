# Handoff: laptop session

**For Claude on Pinhas's laptop.** This is where the cloud session stopped. Read it first,
then `docs/pitch.md` (the supervisor pitch) and `sim/e1/README.md` (every experiment's
method and findings). Branch: `claude/monitoring-paper-submission-1ryynf`. Do not open a
PR unless asked.

**Who and why.** Pinhas Nehoray Aburmad (BGU, supervisor Prof. Ronen Brafman) is preparing
a meeting with his supervisor. He needs:
1. the pitch and the deck;
2. a live demo running on this laptop;
3. the last experiment (unanticipated faults) finished and written up.

**The research in one line.** An LTL runtime monitor with *progress states* (phases), whose
spec an LLM generates from a plain-language task description, monitoring a Unitree G1 in
MuJoCo. It reads only ROS 2 messages and infers success or failure from them.

---

## 1. Install on this laptop

Linux or macOS. On Windows, everything goes inside WSL2 (Ubuntu). No GPU, ROS or Docker
is needed for the demo. The monitor needs **Spot**, which comes from **conda-forge only**
(`pip` cannot install it), so use Miniforge, conda or micromamba.

```bash
git clone https://github.com/pinhas019/LtlMonitor.git && cd LtlMonitor
git checkout claude/monitoring-paper-submission-1ryynf
conda create -y -n ltl -c conda-forge python=3.12 spot pyyaml "numpy<2" matplotlib pytest
conda activate ltl && pip install mujoco
sim/fetch_assets.sh ~/unitree          # Unitree's G1 model + walking policy (pinned commit)
export G1SIM_ASSETS=~/unitree          # put this in the shell profile
```

Check the install:

```bash
python -c "import spot, mujoco; print(spot.version(), mujoco.__version__)"   # Spot 2.x, MuJoCo 3.x
python -m pytest -q tests              # ~1430 tests, all must pass
python -m pytest -q sim/tests          # ~140 tests (physics tests need G1SIM_ASSETS)
python sim/demo_e1b.py --no-view       # text-only episode: alarm at ~22 s, "FAILED (false_arrival)"
```

Run pytest on its own and read its exit status. Do not pipe it into `tail` before an
`&&`: that hid a failure once.

## 2. The demo (for the meeting)

`sim/demo_e1b.py` runs one fetch-and-deliver episode with the **real** evaluator and monitor
(Spot automata, phase machine).
- A MuJoCo window shows the robot, the yellow object and the blue drop-off pad.
- An overlay in the window, and the terminal, show the monitor's phase, the inferred
  "held", the verdict and every alarm next to the simulator's ground truth.
- **macOS:** the viewer needs `mjpython sim/demo_e1b.py ...` instead of `python`.
- `--no-view` gives text only.

Suggested order for the meeting, about 1–2 min each:

```bash
python sim/demo_e1b.py --fault clear                     # nothing goes wrong, nothing flagged
python sim/demo_e1b.py                                   # object dropped ~22 s; full spec alarms at the next tick
python sim/demo_e1b.py --spec flat                       # same drop; flat spec only notices at the end (37 s)
python sim/demo_e1b.py --fault grasp_fail --policy recover   # caught, re-planned, delivered
python sim/demo_e1b.py --fault drop --spec closed_loop            # hand-coded checks catch the fault they were written for
python sim/demo_e1b.py --fault wrong_dropoff --spec closed_loop   # ...but report success at the wrong place, silently
python sim/demo_e1b.py --fault wrong_dropoff             # full monitor: alarm when it lets go in the wrong place
```

Options:
- `--fault`: any family in `sim/e1/carry/task.py` `FAMILIES`.
- `--spec`: `full`, `flat`, `flat_strict`, `ltl_only`, `closed_loop` or `closed_loop_full`.
- `--policy`: `off`, `detect` or `recover`.
- `--seed N`.
- `--speed` (default 2× real time).

**Older demo.** `python sim/demo.py [--fault stall|push|none]` is walking only, text only.

**If the window does not open:**
- Linux needs a display and OpenGL (Mesa is fine).
- On WSL2, WSLg must be enabled.
- Fall back to `--no-view`.

## 3. The pitch and the deck

- **Pitch:** `docs/pitch.md`. It renders on GitHub (same branch) with all figures. It
  contains:
  - claim, setup, results, what is not done, directions;
  - the generated automata (`docs/figures/automata/`);
  - "Try it yourself" (the same install as above).
- **Deck:** a private claude.ai artifact owned by Pinhas,
  https://claude.ai/artifact/7EiBmWB6He5MXZRt94h3X2 (12 slides).
  - Pinhas exports it as PDF/PPTX from its Share menu.
  - If this session has an Artifact tool and he wants slides changed, read the artifact
    first and update it in place. Slides live under `project/slides/<id>.html`, the index
    under `project/deck.json`.
  - Otherwise write the slide text and let him paste it.
- **Every number in the pitch and deck comes from `docs/e1b_ros/results.md` and
  `docs/e1/results.md`.** Regenerate them, never type them:
  ```bash
  python sim/e1/summarize_e1.py <(zcat docs/e1b_ros/e1b_ros_episodes.jsonl.gz) \
      --out docs/e1b_ros --title "E1b over ROS 2: fetch and deliver"
  ```

## 4. Where the research stands (what is established)

All results are in simulation, with the monitor fed only ROS 2 messages.
- "Held" is inferred from a noisy object detector plus odometry.
- Outcomes are scored from simulator ground truth, which the monitor never sees.

**E1, a short walk (1800 episodes).** Phases added almost nothing over a flat spec (1
stall in 15). Sensor-grounded progress did the work.

**E1b, fetch and deliver** (4 phases; 2080 episodes over real ROS 2):
- **Detection timing.** The full spec catches a drop in 1 s and a failed grasp in 4 s.
  Flat and LTL-only catch them only at completion (14 s / 19 s). Full was earlier on
  20/20 of each, p = 1.9·10⁻⁶.
- **Success.** With no deadline, final success is the same: full 82%, flat 84%, LTL-only
  83%, against 35% with no monitor.
- **With a deadline** (1.5× the nominal time to deliver): full 64% vs flat 36%
  (p = 1.3·10⁻⁶) vs LTL-only 36%. **The phase machine does the work, not LTL.**
- **A hand-coded closed-loop executor does as well or better:** 81% at 1.5×. It knows its
  own state; the monitor needs no task code.
- **Verdicts.** The monitor's own verdict never called a failed task a success
  (0/104 failed episodes).

**The honest claim today.** Progress states catch phase-specific failures as they happen,
and when time matters that means more successes. Not yet shown: an advantage over checks
hand-written into the executor. That is the experiment in flight.

## 5. In flight: the unanticipated-fault experiment. Continue here

**Design, metric and predictions** are committed *before* the sweep, in
`sim/e1/README.md`, section "Unanticipated faults (design, committed before the sweep)".
Do not change them after seeing results. Report deviations from the predictions as they
are.

**Fault families.** One per requirement of the task description that the hand-coded
executor does not check:
- `wrong_dropoff`: the executor's own drop-off is off by 1.5–2.5 m;
- `slow_nav`: navigator speed limit cut to 25–35%;
- `detour`: carry leg via a waypoint 2.5–3.5 m off the line;
- `close_pass`: obstacle inflation cut to 0.05 m, with a pillar on the line.

The code is in `sim/e1/carry/task.py`, `sim/g1sim/navigator.py` (`set_inflation`) and
`sim/e1/run_e1b.py` (arms `closed_loop`, `closed_loop_full`).

**Main metric: silent failures**, i.e. failed episodes nothing flagged. The table is
"Unanticipated faults" in `results.md`, built by `summarize_e1.py`
(`unanticipated_rows`).

**Status when the cloud session stopped.**
- The sweep (1120 episodes: 800 on the new families, plus 320 of `closed_loop_full` on
  the original families) was running in the cloud.
- **Check first:** does `docs/e1b_ros/results.md` already have a section
  "Unanticipated faults: what nobody wrote a check for", computed on 20 seeds?
  - **If yes:** the cloud session finished it. Go to "write-up" below.
  - **If no** (or it shows only 2 seeds): run it here. This is in-process, needs no ROS,
    and gives about the same results; the transports agreed on 18/18 noise-free pilot
    episodes.
    ```bash
    python sim/e1/run_e1b.py --families wrong_dropoff slow_nav detour close_pass --seeds 0-19 \
        --arms full flat closed_loop closed_loop_full --workers 4 --out ua.jsonl
    python sim/e1/run_e1b.py --families clear cluttered grasp_fail drop skip_pickup object_moved stall push \
        --seeds 0-19 --arms closed_loop_full --workers 4 --out clf.jsonl
    cat <(zcat docs/e1b_ros/e1b_ros_episodes.jsonl.gz) ua.jsonl clf.jsonl > all.jsonl
    python sim/e1/summarize_e1.py all.jsonl --out docs/e1b_ros --title "E1b over ROS 2: fetch and deliver"
    gzip -c all.jsonl > docs/e1b_ros/e1b_ros_episodes.jsonl.gz
    ```
    - About 2 s per episode on 4 cores, so roughly 20 minutes.
    - **Say in the README** that these episodes ran in-process, not over ROS 2. The
      record field `timing.transport` says which. Optionally the summary could split by
      transport.
    - The ROS 2 runner is `sim/e1/ros_e1b.py`. It needs ROS 2 Humble, e.g. RoboStack:
      `conda create -n ros -c robostack-staging -c conda-forge python=3.11
      ros-humble-ros-base spot pyyaml "numpy<2" matplotlib pytest`, then
      `pip install mujoco`.

**What the 2-seed pilot showed** (not counted):
- `wrong_dropoff`: the hand-coded executor was silent (reported success at the wrong
  place); the full monitor flagged it at release.
- `close_pass`: true clearance was 0.19–0.20 m; the monitor's proximity rule fired; the
  executor was silent.
- `slow_nav` and `detour` were silent for **every** arm: they stay inside the monitor's
  phase budgets. That contradicts the `slow_nav` prediction. Report it as such.

**Write-up, once the table exists:**
1. **`sim/e1/README.md`.** Add "Unanticipated faults: findings" under the design section:
   the table, each prediction against its outcome, and the reading. The reading must be
   honest:
   - The likely result is that the monitor catches the requirements it can observe
     directly: the commanded drop-off from `/task`, and proximity from the scan.
   - Neither the monitor nor the executor catches slowness or a detour inside generous
     budgets.
   - `closed_loop_full` shows whether the monitor adds anything on top of good
     hand-written checks, and whether it costs anything on the original families
     (success, false alarms).
2. **`docs/pitch.md`.** Update:
   - the claim paragraph in §1 ("Not yet shown: …");
   - a short "Faults nobody wrote a check for" block in §2 next to the comparisons table;
   - directions in §3.
3. **Deck.** Add one slide "Faults nobody wrote a check for": the silent-failure counts per
   family for hand-coded vs hand-coded + monitor vs full. Update the claim slide.
4. Commit in that order (results, README, pitch) and push to the branch.

## 6. Next steps after that

The pitch's "Research directions" has the full list. The open ones, roughly in order:
- **Phase-relative progress.** "Closer to the object" during WalkToObject would catch a
  skipped pick-up, which nothing catches during the task today.
- **Re-arm at the current phase.** Re-arm the monitor at the phase the task is actually in
  after a re-plan; today it restarts at phase one, which caused repeat TIMEOUTs.
- **Calibration.** Calibrate the 0.3 m proximity rule and the phase budgets from nominal
  runs.
- **Further comparisons with hand-written checks.**
  - Generality: one description → monitors for several skills.
  - An executor whose belief about its own state is wrong.
- **Several generated specs per skill.** Today there is one spec per skill.
- **The real robot.**
  - Generate `formulas_g1.json` with the LLM endpoint; today's file is an interim,
    hand-written spec (see `RESUME.md`, session 7b).
  - Record with TRAV; calibrate thresholds.
- **Paper 2:** learned grounding of propositions.

## 7. Map of the code

| path | what |
|---|---|
| `skill_monitor/core/automata.py` | LTL → Spot automata (deterministic, complete, state-based Büchi) |
| `skill_monitor/backend/monitor_node.py` | the monitor node: automata + phase machine + interventions (`--passive`) |
| `skill_monitor/backend/evaluator_node.py` | the evaluator: ROS topics → propositions per tick (`--adapter <name or .json>`, `--clock ros`) |
| `skill_monitor/core/adapter_spec.py` | descriptor engine and extractors (`object_held`, `no_progress`, …) |
| `skill_monitor/specs/formulas_g1_carry*.json` | E1b specs: full (generated), `_flat`, `_flat_strict`, `_ltl` |
| `skill_monitor/core/spec_ablation.py` | `flatten`, `strip_phases`: the controls |
| `sim/g1sim/` | MuJoCo G1 (Unitree policy in numpy), faults, navigator |
| `sim/e1/carry/` | E1b task: generator, `CarryExecutor` (open / closed loop), perception stand-in, descriptor |
| `sim/e1/run_e1b.py` | in-process E1b runner; `play_episode` is the one episode loop |
| `sim/e1/ros_e1b.py` | the same episodes over real ROS 2 (separate evaluator/monitor processes, DDS) |
| `sim/e1/summarize_e1.py` | every table and figure from episode records |
| `tools/report/render_automata.py` | renders a spec's automata and phase machine |
| `sim/demo_e1b.py`, `sim/demo.py` | demos |

## 8. Conventions and pitfalls learned the hard way

- **Commit generated specs and experiment designs before running episodes**
  (pre-registration). Record predictions; report what happens.
- **No hand-typed numbers.** Every number in docs comes from `summarize_e1.py` output.
- **Encoding.** `tests/test_portability.py` forbids text-mode `open`/`read_text` without
  `encoding="utf-8"`. It has broken CI twice.
- **Import order.** In-process runs import the real `spot` *before* `tests/ros_stub.py`
  installs its stand-ins; `run_e1._init_worker` does this.
- **ROS 2 runs.** A crashed worker once left an evaluator and monitor running on its
  `ROS_DOMAIN_ID`, and they answered later runs. Workers now refuse a busy domain and
  their nodes die with them. Still, check for stray `monitor_node`/`evaluator_node`
  processes before a sweep.
- **ROS topic ordering.** Topics are not ordered against each other, so a sensor message
  can land in the next tick's window. Over ROS 2 the flat arm missed 2 of 11 slow stalls
  that the in-process run caught. Expect differences of this size between transports.
- **Viewer.** The MuJoCo viewer on macOS needs `mjpython`. The object and drop-off are in
  geom group 3, which the demo switches on.
