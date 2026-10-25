# Demo script: what happens at each stage, and what to say

Start the stack (`docker run --rm -p 8080:8080 ghcr.io/pinhas019/ltlmonitor-demo`, or
`python3 run.py`), open http://localhost:8080 and click the presets top to bottom. Times
are simulated seconds at seed 0, measured over ROS 2; expect them within a second or so.
**Pause** (next to Run) freezes the robot and the monitor at any stage so you can explain
it; press it again to resume.

## Reading the page

- **Robot view** (top left): the MuJoCo G1, the yellow object and the blue drop-off pad.
- **What the monitor is doing** (under the robot), refreshed every tick:
  - **The sentence at the top** says, in words, which phase the monitor is in, what it
    must keep true, what moves it on, and which state the LTL task automaton is in. It
    turns red on an alarm and green on success.
  - **Phase machine:** Idle → WalkToObject → Grasp → Carry → Place → Done, plus FAULT.
    The blue box is the current phase, ✓ marks finished phases, a red outline marks the
    phase that broke, and the FAULT box fills red. Each box shows its time budget, its
    invariant ("keep") and its exit condition ("next when").
  - **LTL task automaton:** the 6-state automaton Spot built from the ordered formula.
    The current state is filled and the edge just taken is highlighted. Under each state:
    what it means and what keeps it there ("stays while").
  - **Propositions this tick:** the values the evaluator computed from the robot's ROS
    messages and the monitor stepped on (✓ true, ✗ false, ? not evaluable this tick).
  - **This phase's checks:** the current phase's guards as the monitor evaluated them
    (✓ held, ✗ failed, · not checked this tick).
  - **Safety automata:** `G(upright)` and `G(!obstacle_too_close)`, ok or VIOLATED.
- **Monitor table** (right): the last row, *truth (simulator)*, is ground truth, which the
  monitor never sees. Everything above it is the monitor's.
- **ROS 2 graph** (right): three separate nodes, `ltl_generic_client` (the evaluator),
  `ltl_monitor_node` (the monitor) and `e1b_driver` (the simulated robot).

One sentence to open with: *"The monitor sees only ROS messages: odometry, laser scan,
object pose and the task. It infers 'holding' from where the object is relative to the
hand. Everything on this card is published by the monitor itself."*

## 1. Clean run (full spec): nothing goes wrong, nothing is flagged

| t | What you see | Say |
|---|---|---|
| 1–12 s | WalkToObject; automaton 0 → 1 | "Phase 1 of 4: it must stay upright and clear, and it moves on when near the object." |
| 13 s | Grasp; automaton → 2 | "At the object. Grasp has a 10 s budget." |
| 17 s | Carry; automaton → 3; `holding_object` ✓ | "Holding. From now on the Carry invariant requires holding_object." |
| 27 s | Place; automaton → 4 | "At the drop-off." |
| 31 s | Done (green); automaton → 5, accepting | "Delivered, every check held, no alarm." |

**Takeaway:** the monitor follows the task step by step and stays quiet when nothing is
wrong.

## 2. Dropped object, full spec: caught the moment it happens

| t | What you see | Say |
|---|---|---|
| 17 s | Carry; automaton state 3 | "Carrying. The invariant is now upright ∧ holding_object ∧ ¬obstacle_too_close." |
| 21.6 s | The object falls (tick log: `fault injected: drop`) | "We drop it, silently: the executor doesn't know." |
| 22 s | **FAULT** (red), Carry outlined; sentence names `holding_object = false`; invariant ✗ | "One tick later the Carry invariant breaks and the monitor says so." |
| 22 s | Automaton still in **state 3** | "The LTL automaton alone has not noticed: 'eventually' can still come true. The phase is what catches it." **Pause here.** |
| 37 s | Truth: executor claims success, object not delivered | "The executor would have reported success 15 s later." |

**Takeaway:** the phase machine turns a silent failure into an alarm at the moment it
happens, not at the end.

## 3. Dropped object, flat spec: the same drop, without phases

| t | What you see | Say |
|---|---|---|
| 1–37 s | One phase, Execution; the 2-state automaton stays in **state 0** | "Same propositions and safety rules, but the task is just 'eventually delivered'." |
| 22 s | Nothing changes | "The drop happens here. The flat monitor has no state in which holding must be true." |
| 37 s | Alarm: *executor claims success; the monitor does not confirm it* | "It only objects when the executor claims success: 15 s late." |

**Takeaway:** the same monitor, minus the phase structure, finds out at the end.

## 4. Failed grasp, full spec + re-plan: caught, recovered, delivered

| t | What you see | Say |
|---|---|---|
| 16 s | Grasp; automaton state 2 | "At the object, trying to grasp." |
| 18.6 s | Tick log: `fault injected: grasp_fail` | "The grasp fails silently." |
| 22 s | Alarm: *phase took longer than its time budget* | "Grasp ran over its budget. The policy is 're-plan', so the executor retries." |
| 32 s | Carry; automaton → 3 | "Second grasp worked." |
| 51 s | Done (green); automaton state 5 | "Delivered, 20 s later than a clean run, instead of failing." |

**Takeaway:** an alarm can act: the monitor's verdict drives recovery.

## 5. Hand-coded checks, dropped object: the engineering baseline

The card says *no monitor acting in this run*: only the executor's own checks. (The ROS
graph still lists `ltl_monitor_node`: it runs for the record, as in the experiments, but
nothing it says is shown or acted on.)

| t | What you see | Say |
|---|---|---|
| 22 s | Alarm: *executor check: not holding the object while carrying*; it re-grasps | "A good engineer anticipated a drop and coded a check for it." |
| 37 s | Delivered | "For an anticipated fault, hand-coded checks work." |

## 6. Hand-coded checks, wrong drop-off: the fault nobody coded for

| t | What you see | Say |
|---|---|---|
| 20.9 s | Tick log: `fault injected: wrong_dropoff` | "Now the robot puts the object down somewhere else." |
| 35 s | Executor reports **succeeded**; truth: **FAILED** | "No check was written for this, so nothing says anything. A silent failure." |

## 7. Monitor, wrong drop-off: the same fault, with the monitor

| t | What you see | Say |
|---|---|---|
| 21 s | Carry; automaton state 3 | "Carrying." |
| 33 s | **FAULT**: Carry invariant, `holding_object = false`; still in Carry | "It put the object down, but never reached the drop-off, so the monitor is still in Carry and letting go breaks the Carry invariant. Nobody wrote a check for this fault; it follows from the task description." |
| 35 s | Truth: FAILED | "Caught before the executor's false success." |

**Takeaway (close with this):** the hand-coded checks catch what someone thought of; the
monitor, generated from a plain-language description of the task, catches violations of
the task itself.

## If something goes wrong

- **Page doesn't load / "port is already allocated":** `docker stop $(docker ps -q)`, or
  run with `-p 9090:8080` and open http://localhost:9090.
- **A run looks stuck:** click the preset again; it restarts the run.
- **No network in the room:** `docker pull ghcr.io/pinhas019/ltlmonitor-demo` beforehand.
  The image needs no network when it runs.
