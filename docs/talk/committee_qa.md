# Committee Q&A: the whole work

How to use this: read §0 and §1 the night before (memorise the cards), skim the rest, and
practise saying the bold answers out loud. Related work in depth is in
`related_work_prep.md`. Every number below comes from `docs/e1b_ros/results.md`, the E1
results, `docs/report/progress_report.md` or the code; nothing is rounded up.

---

## 0. How to answer (the habits that show you know what you're doing)

1. **Answer first, in one sentence.** Then the evidence (a number or a mechanism). Then the
   limit, before they find it. *Claim → evidence → limit.*
2. **Name weak points yourself, with the fix.** "Yes, that is a limitation; here is why it
   happens and what we are doing about it." Never defend something weak.
3. **Use numbers, not adjectives.** "1 s vs 14 s, 20 of 20 runs", not "much faster".
4. **Separate what you showed from what you believe.** "We showed X in simulation. We expect
   Y on the robot, and this is the experiment that will test it."
5. **If you don't know:** "I don't know yet. What I do know is …, and I would find out by …"
   That is a strong answer, not a weak one.
6. **Turn hostile questions into the contribution.** "Isn't this just a state machine?" →
   "Yes, and the point is *where it comes from*: generated from words, checked against the
   robot's sensors, with no task code."
7. **Keep answers short.** 20–40 seconds. Stop and let them ask the follow-up.

---

## 1. Cards to memorise

### 1a. The contribution
**One sentence:** a monitor that is generated from a plain-language skill description, knows
the **stages** of the task, and reads only the robot's own sensors, catches failures *when
they happen* instead of at the end.

**Three bullets:**
1. **Progress-state specifications**: phases with their own rules, exit conditions and time
   limits, plus LTL rules and safety modes, drafted by an LLM from the description, compiled
   with Spot, checked against the robot's sensor schema before they run.
2. **A runtime on ROS 2**: evaluator and monitor as separate nodes, sensor-only facts (no
   planner status), a graded intervention ladder, record-and-replay; the same engine on the
   real G1, MuJoCo and Isaac adapters.
3. **Evidence with controls**: the same spec with stages removed (flat), with only the LTL
   automata (LTL-only), and hand-written checks, on a simulated humanoid over real ROS 2.

### 1b. Numbers card

| | |
|---|---|
| **E1 (walk)** | 1800 runs = 10 fault types × 20 seeds × 3 spec versions × 3 reactions. Falls caught in 1–7 s by all versions. Stalls: full 15/15, flat 14/15, no progress check 1/15. Fault-free false alarms 3/40. Success: 63% report only, 43% stop on alarm (p = 9·10⁻⁵), 52% re-plan (p = 0.03). |
| **E1b (fetch & deliver)** | ROS 2; 1440 runs in the main comparison, 3360 in total. Drop: 1 s vs 14 s; failed grasp: 4 s vs 19 s; earlier in 20/20 paired runs (sign test p = 1.9·10⁻⁶). Deliver after re-plan: 34.5 s vs 63 s (drop), 36.5 s vs 72 s (grasp). No deadline: 82% vs 84% (from 35% with no action). Deadline 1.5×: **64% vs 36%** (p = 7·10⁻⁷); LTL only 36%; hand-written checks 81%; no monitor 34%. Fault-free false alarms 3/40. |
| **Unplanned faults** | Wrong drop-off + too close: hand-written checks 40/40 silent → 0/40 with the monitor added; no measurable cost (132 vs 136 of 160, p = 0.65). Slowness and detours: missed by everyone. |
| **MiniGrid + MAAOS pilot** | Corrupted plan: 0 → every seed with monitor + re-plan (Δ = +1.00). Two-agent deadlock: off fails every seed (80-step budget); LTL + re-plan recovers every seed in ≈45 steps. Detect-only Δ = 0. Free-text LLM judge Δ = 0. Clean runs: 1.00 success, 0 false alarms. 10 seeds/cell (5 for LLM arms). |
| **Statistics** | Fisher's exact test (proportions), sign test (paired latencies), Wilson intervals. Designs and predictions committed before each run. |
| **Spec facts** | Tick 1 Hz. Holding = object ≥ 0.3 m off the floor and ≤ 0.5 m from the base (from perception: 2 cm noise, 5% missed detections; a missed detection keeps the last value). "Near" = 0.5 m. Progress = closing speed > 0.05 m/s; "stalled" after 10 s without progress. "Too close" = 0.3 m. Phases: Walk ≤ 45 s, Grasp ≤ 10 s, Carry ≤ 60 s (must hold), Place ≤ 10 s. |

### 1c. Definitions card (say each in one breath)
- **LTL**: logic over sequences of states. **G p** always p; **F p** eventually p; **X p** p
  at the next step; **p U q** p until q.
- **Runtime verification**: checking one execution as it happens (vs. **model checking**:
  all executions of a model, offline).
- **LTL₃** (Bauer, Leucker, Schallhart 2011): on a finite prefix the verdict is **true**
  (every continuation satisfies), **false** (every continuation violates), or **?**.
- **Safety property**: "nothing bad happens"; a violation has a finite witness (G upright).
  **Liveness**: "something good eventually happens"; no finite violation (F deliver).
  **Monitorable**: no prefix after which the verdict can never be decided.
- **Büchi automaton**: an automaton on infinite words that accepts if it visits accepting
  states infinitely often. We ask Spot for **deterministic** (one successor per input),
  **complete** (a successor for every input) and **state-based** acceptance.
- **LTL vs STL**: STL adds real-valued signals and time intervals, with a robustness value
  ("how much" a rule holds).
- **Progress state / phase**: a stage of the skill with an enter condition, an invariant
  (must stay true), a progress condition, an exit condition, and a time limit.
- **POMDP** ⟨S, A, O, T, Z, R⟩: hidden state, actions, observations, transitions,
  observation model, reward. **Belief** = probability over hidden states; update
  b′(s′) ∝ Z(o|s′) Σₛ T(s′|s,a) b(s). **Value of information**: knowing is worth something
  only if it changes the action or the outcome.

---

## 2. Big picture

**Q: What is your research question?**
**Does giving a runtime monitor the stages of a skill let it catch failures during the task,
and does that improve outcomes?** We test it by holding everything fixed and removing only the
stages.

**Q: Why does this matter?**
Robots fail mid-task and report success; the planner only knows what it commanded. Finding out
at the end wastes time and some failures cannot be undone (a fall, a collision). With a
deadline, catching early is the difference between 64% and 36% delivered.

**Q: What exactly is new?**
Three things together: the monitor is **generated from words**, it has **stages**, and it uses
**only the robot's sensors**. Each exists separately (NL→LTL, runtime verification, VLM
detectors); the combination, and the controlled evidence that the stages are what matters,
is ours.

**Q: Why a humanoid?**
It is the platform we have (the lab's G1), and it is hard: falls, slow walking, a learned
locomotion policy. The method itself is embodiment-agnostic; only the adapter changes.

**Q: If you had to show one result?**
E1b: same monitor, same rules, stages on vs. off — the drop is caught 1 s after it happens
instead of 14 s, in 20 of 20 paired runs; and with a deadline that is 64% vs 36% delivered.

---

## 3. Method and system

**Q: Walk me through the pipeline.**
Plain-language description → an LLM writes the spec (propositions with rules over sensor keys,
LTL formulas, failure modes, phases, terminal conditions) → a schema check against the robot
adapter rejects anything unmeasurable → Spot compiles the formulas to automata → at runtime an
**evaluator** node turns ROS 2 messages into true/false propositions once per second and a
**monitor** node steps the automata and the phase machine and publishes a verdict and an
action.

**Q: How does a proposition get its value?**
Each proposition is a rule over sensor keys declared by the adapter, for example
`near_object: object_dist < 0.5`. The adapter computes the keys from topics (odometry, laser,
object pose, task). Each second the evaluator folds the messages of that second into values.

**Q: How do you know the robot is holding the box? There's no gripper sensor.**
We infer it from perception: the object is at least 0.3 m off the floor and within 0.5 m of the
base. A missed detection keeps the previous value so one dropped frame does not flip it. It is
deliberately not a gripper flag: a slipped grasp is exactly when a flag would lie.

**Q: What exactly is a phase? How does it fail?**
Enter condition, invariant (must stay true), progress condition, exit condition, time limit.
A phase faults if the invariant breaks, the time limit runs out, or progress fails repeatedly
(the limit is 3 in our spec). In Carry the invariant is `upright and holding_object and not
obstacle_too_close`.

**Q: What does the monitor do on an alarm?**
A graded ladder: continue → warn → slow → re-plan → halt → abort. In the experiments we used
three reactions: report only, stop, re-plan.

**Q: Why 1 Hz?**
It matches the evaluator's tick and is plenty for these skills: a drop is caught 1 s after it
happens. The slow detections (a moved object ≈31 s, a stall ≈11 s with its 10 s debounce) are
slow because of the rules, not the rate.

**Q: Where do the thresholds come from?**
The LLM wrote them from the words ("dangerously close" → 0.3 m). They are **not calibrated** —
and E1 shows the cost: the 0.3 m rule fired on safe passes and lowered success when we acted on
it. Calibration from fault-free runs is the first item of future work.

**Q: Why not use the planner's status?**
Because the planner reports what it *commanded*. In the stall the planner keeps commanding
0.5 m/s while the robot has stopped. A test in the code forbids any descriptor from reading
planner status, action status or the planned path.

**Q: What does "embodiment-agnostic" mean concretely?**
The spec talks about sensor keys (position, object distance, upright). Each robot has an
adapter mapping its topics to those keys. The real G1, MuJoCo and Isaac adapters expose the same
schema, and one engine runs on all of them unchanged.

---

## 4. Formal soundness (expect this from a formal-methods person)

**Q: Is your "ACCEPTED" the LTL₃ "true"?**
**Not for every formula, and I know exactly where it differs.** The monitor reports ACCEPTED
when the Büchi automaton is in an accepting state. For the nested "eventually" task formula that
automaton is terminal, so ACCEPTED really means "satisfied". For a safety formula like
`G(upright)` the initial state is already accepting, so it reads ACCEPTED before anything
happened — LTL₃ would say "?". We never use ACCEPTED of a safety mode as proof; we only act on
VIOLATED. The fix is per formula class: Spot's monitor construction for safety formulas, and the
Bauer product (automaton for φ and for ¬φ) to decide "true".

**Q: Is VIOLATED sound?**
Yes, when it fires: it fires when the automaton enters a non-accepting state whose only edge is
a true self-loop, from which no accepting state is reachable. It is **incomplete**: a rejecting
component with several states would not be detected, so the monitor would stay "?" too long.
Fix: SCC reachability, linear time. For our current formulas (state invariants and nested F)
this case does not occur.

**Q: Spot's "det" option doesn't guarantee determinism.**
Right, it is a preference. A deterministic Büchi automaton exists only for recurrence
properties or simpler; every formula in our specs qualifies, which is why it has not bitten. The
fix is to assert `is_deterministic` and `is_complete` at construction and reject the spec
otherwise — important because specs are LLM-generated.

**Q: What if a proposition has no value this tick?**
Today it defaults to False, which is **fail-open** for `G(!x)` ("no obstacle" when we don't
know). The design for this is an UNDECIDED value that freezes the automaton for that tick; it
is documented and not yet implemented. Our current facts always have a value (or keep their
last one), so it did not affect the experiments.

**Q: You run one automaton per formula. Is that equivalent to the conjunction?**
For "all satisfied", yes. For "violated", no: two formulas can each be "?" while their
conjunction is already false. Separate automata are the right choice for explaining *which*
rule broke; an offline product check at spec load would catch conflicting rules.

**Q: Is the phase machine itself formal?**
It is a deterministic machine over the same propositions, with counters for time limits and
progress. It could be compiled into the automaton (time limits as bounded operators), at the
cost of much larger automata and less readable verdicts. We kept it separate on purpose so the
monitor can say *which stage* failed.

---

## 5. The LLM part

**Q: Which LLM, and how many tries?**
Claude, acting as the "describer". One call; three attempts were allowed; the first passed all
checks. The description and spec are hashed in a provenance file, and the spec was committed
before any experiment ran.

**Q: You built the system with the same assistant that wrote the spec. Isn't that biased?**
It is a real risk and I won't pretend otherwise. Mitigations: the description was written
first, and the spec generated in one attempt and frozen (hashes committed) before the runs.
The proper test is several specs from several independent models per skill, with the spread
reported — that is planned for Paper 1.

**Q: What if the LLM writes a wrong spec?**
The checks catch specs that **cannot run** (unknown or unmeasurable propositions). They do not
catch specs that run but mean the wrong thing. That happened once, in MiniGrid: a rule required
two agents to stay aligned continuously, but pushing interleaves alignment and pushing, so it
raised false alarms. Running fault-free episodes found it. The fix we propose: accept a spec only
if fault-free runs raise no alarms (in E1b, 3 of 40 fault-free runs raised one).

**Q: Can I reproduce it?**
Yes: the spec is in the repo with its hash, the runs are seeded, and the demo runs with one
command (`docker run …`). Regenerating the spec with a different model is the variability
question above.

---

## 6. Experiments and statistics

**Q: Describe the design.**
Each fault type is injected at a known tick into 20 seeded scenarios. Every scenario is run with
each version of the monitor, so comparisons are paired. Ground truth comes from the simulator
and the injection log, never from the monitor.

**Q: What are your controls and what does each isolate?**
- **Flat**: same propositions and safety rules, all stages merged into one — removes the stages.
- **Flat strict**: also removes the terminal-failure rule — shows what "eventually" alone gives.
- **LTL only**: the full spec's automata without the phase machine — separates automata from
  stages.
- **Hand-written checks**: the engineering baseline, no monitor.
- **Hand-written checks + monitor**: does the monitor add anything on top?

**Q: Why these tests?**
Fisher's exact test for success proportions (small counts, no normal approximation); the sign
test for paired latencies (same scenario, which arm caught it first, no distribution
assumption); Wilson intervals for proportions near 0 or 1.

**Q: Was it pre-registered?**
The design and predictions for each experiment were committed to the repository before the
runs. One prediction was wrong (we predicted catching the slowed navigator; we did not), and we
report it.

**Q: How many false alarms?**
3 of 40 fault-free runs in E1, and 3 of 40 in E1b. In E1b all three were in cluttered scenes
(0/20 in clear scenes, 3/20 cluttered), raised by the 0.3 m "too close" rule, and the same in
the full, flat and flat-strict versions — so they come from an uncalibrated threshold, not from
the stages.

**Q: Why only simulation?**
To get thousands of controlled runs with ground truth. It is real physics (MuJoCo, Unitree's
learned walking policy) and the monitor runs over real ROS 2 as separate processes, as on the
robot. The robot is the next step.

**Q: The grasp isn't real and perception is a stand-in.**
Correct. The legs-only G1 model has no arms, so the box is attached; its position comes from a
simulated detector with 2 cm noise and 5% missed detections. The monitor never sees the
simulator's truth. Real perception and a real arm are part of the Isaac Sim / robot step.

**Q: Does ROS 2 change the results compared to the in-process version?**
Barely: noise-free, 18 of 18 pilot episodes were identical; over the full run the numbers agree
within one or two episodes (the flat arm missed two slow stalls because ROS topics are not
ordered against each other).

---

## 7. Interpreting the results

**Q: Why did stages help in E1b but not in E1?**
In E1 (walking) the two stages check the same invariant, so stages add nothing a flat rule
lacks. In E1b, Carry has a condition of its own — holding the box — which a flat rule cannot
state (it would be false while walking to the box). **Stages help exactly when a stage has a
condition of its own.**

**Q: Without a deadline success is the same (82% vs 84%). So what's the point?**
Those faults can be repaired late: re-planning after a late alarm still works. The value of
early detection appears when time matters (64% vs 36% with a deadline) or when a failure cannot
be undone. That is the value-of-information point.

**Q: Hand-written checks beat you (81% vs 64%). Why bother?**
They know the executor's internal state and someone foresaw those faults. On faults nobody wrote
a check for, they missed 40 of 40; adding our monitor made it 0 of 40 with no measurable cost.
The monitor is generated, not written, and complements them.

**Q: What did you miss, and why?**
- **Slowness and detours** within the time limits: progress is "getting closer to where the
  robot walks", and the budgets are generous. Fix: calibrated limits.
- **Skipped pick-up**: walking straight to the drop-off still counts as progress. Fix: progress
  toward each stage's own target.
- **Odometry drift** (1 of 8 caught): distances are measured in the frame that drifts.
- **Scan dropout**: no proposition checks data freshness.

**Q: In E1, acting on alarms lowered success (63% → 43% / 52%). Isn't the monitor harmful?**
The drop is the uncalibrated 0.3 m proximity rule firing on safe passes and stopping runs that
would have finished. That is a threshold problem, not a monitoring problem, and it is why
calibration is first on the list.

**Q: Was the full spec ever worse?**
Yes: on slow partial stalls its time limits fired on runs that would have finished late, and
re-planning restarted the monitor from the first stage. Stall recovery 6/20 vs 9/20 for flat,
not significant (p = 0.51). Fix: restart at the current stage.

---

## 8. Related work and novelty (short; details in `related_work_prep.md`)

**Q: Difference from Bauer et al. / RTAMT / ROSMonitoring?**
Those are monitoring engines for rules a person writes. We use the same theory; we add stages
and generate the spec from words.

**Q: Why not a VLM (AHA, FailSafe, Foresight)?**
They need failure data and give no checkable reason. Ours needs no training data and names the
stage and rule that broke. Complementary: a VLM can compute some of our facts from a camera.

**Q: Why not an LLM judge?**
We tested it: in MiniGrid a free-text judge gave Δ = 0 where the LTL monitor gave +1.00 — it
says "wrong" but not *where*. An LLM judge with full history is a planned arm in Paper 1.

**Q: NL→LTL already exists.**
It stops at the formula, for planning or spec writing. We add stages, ground every word to a
sensor rule, and run it on a robot.

---

## 9. MiniGrid + MAAOS

**Q: What was the MiniGrid work and what was your part?**
Box pushing in a continuous version of MiniGrid (continuous motion, lava hazards), with one
agent or two agents pushing together. MAAOS is Fouzi's multi-agent project; I integrated it into
the continuous MiniGrid and ran the monitor on it.

**Q: What did it show?**
Detection alone gives nothing (Δ = 0); detection with re-planning fixed every seed (Δ = +1.00);
a free-text LLM judge gave nothing even with re-planning; no false alarms on clean runs. It is
where the "stages" argument started.

**Q: Why is it frozen?**
It drove scripted reference plans, not the live MAAOS planner, in discrete-mode episodes. The
next evidence needed real dynamics, so we moved to MuJoCo.

---

## 10. Future, papers and timeline

**Q: What are the papers?**
Two RA-L papers. **Paper 1, "structure matters"**: stages vs. flat vs. LLM judge vs. VLM judge
vs. heuristic, all with recovery, on the G1 in simulation, validated on hardware. Done so far:
full, flat, LTL-only and hand-written checks; the LLM/VLM judge arms on the G1 are still to
run. **Paper 2, "learning supplies the grounding"**: learned, probabilistic facts (camera)
inside the stage structure — the full POMDP.

**Q: Next steps?**
Calibrate limits and thresholds from fault-free runs; progress toward each stage's target;
Isaac Sim (cameras, more skills); the real G1 with Elias's TRAV navigation app, monitor on vs.
off.

**Q: What would show you are wrong?**
If on the robot, with real perception, monitor-on does not beat monitor-off on time-limited
tasks; or if real sensor noise makes fault-free runs raise frequent false alarms.

**Q: Biggest risk?**
Perception. Our facts are only as good as "holding" and "near", and today they come from a
stand-in. That is why Paper 2 is about the grounding.

---

## 11. Curveballs

**Q: Isn't this just a state machine with timers?**
Structurally, yes — and that is the point. The contribution is where it comes from (generated
from words, checked against the sensors), that it reads only sensors, and the controlled
evidence that the stages, not the machinery, are what catch the failures.

**Q: Why not learn everything end-to-end?**
Learning needs failure data we don't have for each new skill, and gives no readable reason. Our
spec works on day one from a description, and every alarm names the stage and rule. Learning
belongs in the facts (Paper 2), not in the structure.

**Q: What is *your* contribution, versus Spot and the LLM?**
Spot compiles formulas; the LLM drafts text. I designed the spec format (stages with their
guards, failure modes, sensor-grounded propositions), the checks, the runtime on ROS 2, the
fault library and simulator harness, and the experiments with their controls.

**Q: Does it scale to 50 skills?**
The cost per skill is one description and one spec check; the per-robot cost is the adapter,
paid once. Runtime cost is small automata stepped once a second. What does not scale yet is
validation: each new spec should pass fault-free runs before it is trusted.

**Q: What if the sensors lie?**
Then the facts are wrong and so is the verdict; the monitor is only as good as its grounding.
We already handle missing detections (keep the last value) and noise (2 cm in the
experiments). Sensors that fail silently (scan dropout) were invisible in E1 — data-freshness
propositions are the fix.

**Q: Why should a roboticist care about LTL?**
Because it gives a readable, checkable contract for a skill, written once from a description,
that tells you *which step* went wrong and *when* — not a score.

**Q: Is it really a POMDP if there are no probabilities?**
The problem is a POMDP; the monitor today is a deterministic approximation: the belief is a
single point (stage + automaton states), the update is one automaton step, the policy a fixed
rule. Adding probabilities is Paper 2.

---

## 12. Attacks on the formal model (see `formal_model.md` for the full write-up)

**Q: State your model formally.**
Each tick, a labelling L maps the robot's messages to the set of true propositions σₜ ⊆ AP.
The spec is S = ⟨AP, Φ, M, Π, succ, fail⟩: LTL task rules, safety rules, phases, end
conditions. A phase is ⟨enter, inv, prog, exit, T, k⟩. The monitor state is ⟨phase i, time in
phase c, progress misses v, automaton states q⟩; on each σ every automaton steps, and the phase
faults if its invariant is false, or c ≥ T, or v ≥ k, and advances when its exit holds.

**Q: What does the model guarantee?**
Four properties, each a few lines from the definitions:
P1, a broken stage invariant is reported at the tick it is observed;
P2, the ordered "eventually" task rule can never fail on a finite run (any unfinished run can
still finish), so LTL alone cannot catch a mid-task failure;
P3, a stuck stage fails within its time limit;
P4, the flat spec cannot contain "holding", because holding is false before the grasp.
Each one predicted a measured number before we looked: 1 tick; LTL-only 14 ticks; 4 ticks;
flat 14 ticks.

**Q: Prove P2.**
φ = F(a₁ ∧ F(a₂ ∧ … F aₖ)). Take any finite run u that has not satisfied φ. Extend u with a
continuation in which a₁ … aₖ become true in order (re-grasp, deliver). The extension satisfies
φ, so u is not a bad prefix; LTL₃ gives "?" until φ is satisfied. Spot's automaton confirms it:
6 states, one accepting, no rejecting state.

**Q: Phases are just syntactic sugar for LTL.**
In expressiveness, yes, and I say so: G(grasped → (holding U near_dropoff)) is LTL, and time
limits fit a timed logic. The claim is not expressiveness. It is that organising the spec by
stages makes these *conditional* rules explicit, so a language model writes them; the flat spec
generated from the same description did not contain them, and that is exactly the difference
we measured.

**Q: P1 assumes perfect labels. With real perception it breaks.**
P1 is about the monitor: given the labels, detection is immediate. Wrong labels give wrong
verdicts — that is the grounding problem, and it is the subject of Paper 2. Today we model it
partly: 2 cm noise and 5% missed detections, with a missed detection keeping the last value.

**Q: Your "belief" isn't Bayesian; the POMDP is decorative.**
The POMDP defines the problem; the monitor is a deterministic belief filter. If the labels are
correct and stage changes are determined by the labels, the belief over (stage, rule states) is
a point mass and our update *is* the exact one. With noisy labels it is an approximation, and
the policy is a fixed rule rather than optimised. The POMDP is also where the deadline result
comes from: on-time success needs ℓ + r ≤ d, so lowering ℓ only matters when d is tight —
which is the 64% vs 36% (deadline) vs 82% vs 84% (no deadline) pattern.

**Q: What is the time complexity per tick?**
One automaton step per rule (a table lookup over a small automaton: 6 states for the task rule,
2 per safety rule) plus evaluating a few Boolean formulas for the current phase. Constant per
tick for a fixed spec; negligible at 1 Hz.

---

## 13. Statistics in plain words (only if asked)

**The one idea behind every test:** "If the stages made no difference, how likely is a result
this lopsided just by luck?" That number is the **p-value**. Small means unlikely to be luck;
the usual line is 0.05.

**Sign test — "who caught it first?"** Same 20 scenarios, run with and without stages; in
each pair, which caught the drop first? Stages won 20 of 20. With no real difference each pair
is a coin flip; 20 heads in a row is (1/2)²⁰ ≈ 1 in a million, ×2 for "either version could
win" = **1.9·10⁻⁶** — exactly our number. *Paired* because both versions face the same scenario,
so its luck cancels.

**Fisher's exact test — "is one success rate really higher?"** Put the counts in a 2×2 table
(delivered / not × with / without stages) and ask how likely so uneven a split is if stages
didn't matter. "Exact" = it counts every possible split; right for small numbers.
64% vs 36% → p = 7·10⁻⁷ (real). Stall recovery 6/20 vs 9/20 → p = 0.51 (could be luck: we
claim nothing). 132 vs 136 of 160 → p = 0.65 ("no measurable cost").

**Wilson interval — an error bar for a percentage.** 20/20 successes does not mean exactly
100%; the true rate is plausibly 84–100%. Better than "± x%" near 0% or 100%.

**Size vs. sureness.** The numbers (1 s vs 14 s; 64% vs 36%) say *how big*; p says *how sure*.

**If asked:**
- *Why these tests?* "Our outcomes are success counts and paired runs: Fisher for counts (exact
  for small samples), the sign test for pairs (count who won each pair), Wilson for error bars."
- *Why 20 seeds?* "Enough to see large effects like ours clearly; small effects, like the stall
  case, we cannot resolve, and we say so."
- *Did you correct for many comparisons?* "Our key p-values (1.9·10⁻⁶, 7·10⁻⁷) stay significant
  under any reasonable correction: even 0.05 split over 50 tests is 0.001."
- *"Not significant" means no effect?* "No — it means not shown with 20 runs."
