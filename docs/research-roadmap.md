# Research roadmap

A working guide for advancing the thesis, written after the September progress report.
Ordered by what settles the claim, not by what is easiest to build.

Companion documents: `docs/report/progress_report.md` (what the supervisor has seen),
`papers/README.md` (the reading queue), `RESUME.md` (engineering state), `docs/packages/`
(per-package design).

**Publication plan:** `docs/ral-papers.md` (two RA-L papers) and `docs/implementation-plan.md`
(the work packages behind them).

> **Simulator first.** New evidence comes from MuJoCo with real dynamics, then Isaac Sim, then
> the robot. The MAAOS / continuous-MiniGrid work is **frozen** — no new experiments there; its
> pilot numbers serve only as preliminary motivation. Experiments below that mention the
> gridworld now run in MuJoCo; the simulator work is at the top of the order of work.

---

## Direction: a hybrid, with structure symbolic and grounding learned

The question of whether to pursue the learned method or the symbolic one has a clear answer,
and it comes from the results already in hand rather than from preference. **Neither alone. The
structure should be symbolic and the grounding should be learned**, because each is strong
exactly where the other failed.

| | symbolic LTL | pure learned | hybrid |
|---|---|---|---|
| knows *where* in the skill the robot is | yes, explicitly | only if it learns memory | yes, from LTL |
| catches failures nobody specified | no | yes | yes |
| robust propositions | no: hand thresholds (`min_range < 0.25`, `similarity > 0.75`) | yes | yes, learned |
| explains the failure | yes, by named phase and guard | no, a score | yes |
| training data needed | none | a lot, labelled | little: the structure is free |

Two measured results put the line in that place:

- **The unstructured LLM judge scored +0.00 even with recovery; the LTL monitors scored
  +1.00.** Learned judgement without structure said something was wrong but could not locate
  it in the skill's progress. Structure is what made recovery possible.
- **The one LTL failure was the alignment predicate.** The structure was right and the
  *grounding* was brittle: a hand-written condition demanded something the real skill never
  does. Grounding is where learning belongs.

A pure-learned monitor is also the wrong fight to pick. At 1 Hz an episode yields about 100
samples, there are no honest labels yet, a model trained on one task must be retrained for the
next, and it gives up context and explainability, which are the two properties the claim rests
on. The vision–language failure detectors in `papers/` already occupy that space, and
competing with them on accuracy is not a fight worth picking.

**The thesis this gives:** progress states are the structure (E1–E3 show it matters), and
learning supplies what the structure cannot — better grounding for the propositions it is
written in (D1), and detection of deviations no proposition covers (D2). One contribution per
stream. Everything below is ordered to build that case.

---

## The problem to fix first

**The claim is about progress states. Nothing measured so far isolates them.**

The claim, restated: skill execution can be represented as a finite set of progress states
— the robot's semantic state with respect to the task — and a monitor that tracks which
progress state a skill is in is *cheaper to evaluate* and *harder to mislead* than one
judging from the current observation alone.

What the ablation measured was three arms: monitor off, detection-only, detection with
re-planning. That establishes something real and worth having — **intervention is what
pays, detection alone is worth nothing** — but it is a claim about *monitoring plus
recovery*, not about progress states. Swap the progress-state monitor for any other
detector that fires at the same step and the numbers would not move.

The one result that does bear on the claim is `llm_judge` at +0.00 against the LTL monitors
at +1.00, same scenario and same seeds. That is the right *shape* of comparison, and it is
the most valuable number in the report. But it is confounded: `llm_judge` differs from
`ltl_rule` in two ways at once — no progress structure **and** a completely different
evaluation mechanism (free-text verdict instead of a compiled automaton over boolean
predicates). The gap cannot be attributed to progress states while both vary. It is also
n=5, one scenario, one judge model.

Three experiments fix this. They are the thesis's spine, they are all cheap relative to the
hardware and simulator work, and none of them needs new infrastructure.

---

## E1 — The flattened-specification control

**The experiment the claim actually needs.** Hold the mechanism completely fixed — same
engine, same atomic propositions, same evaluators, same recovery pipeline — and remove only
the progress structure.

Three arms:

| arm | specification | what it isolates |
|---|---|---|
| **full** | the current progress formula, all intermediate phases | the claim |
| **flattened** | one phase: safety guards plus a terminal goal check, no intermediate progress | the same monitor *without* progress states |
| **off** | no monitor | baseline difficulty |

All three with recovery enabled, since recovery is already known to be the only arm where
success moves.

The flattened arm is a specification variant, not new code — write it as a sibling spec file
and point the existing suite at it. If **full** recovers the deadlock and **flattened** does
not, progress states are doing the work with the mechanism held fixed, and the claim's first
requirement is met. If both recover it, the progress structure is not what is buying the
result on that scenario, and the honest move is to say so and find a scenario where it is.

Run it over every scenario at ≥10 seeds, not just the deadlock. Keep `llm_judge` in as a
fourth arm — it stops being the load-bearing comparison and becomes a useful second
contrast.

**Done when:** a table of full / flattened / off / llm_judge × all scenarios, ≥10 seeds per
cell, with Wilson intervals. Keep the flattened spec in the repo next to the full one; it is
a permanent control, not a one-off.

---

## E2 — The missed-failure experiment

**The "harder to mislead" half of the claim is completely untested.**

The ablation reports zero false alarms — the monitor does not flag correct behaviour. That
is a false-*positive* result. The claim is about false *negatives*: an observation-based
monitor concluding success when the skill has in fact failed. No current scenario can
produce that, so the strongest half of the argument has no evidence behind it.

This is what the dropped-cup example in earlier drafts was describing, and it was always an
experiment rather than an illustration. Construct it in the simulator: a scenario where the
terminal observation looks like success but the skill never passed through the required
progress states. For the G1, candidates are a spoofed goal image that makes the robot look
arrived, or an arrival reported without the path having been followed.

Then measure recall, not success rate: on those episodes, does the observation-based judge
return SUCCESS where the progress-state monitor returns FAILURE?

**Done when:** a confusion matrix per monitor on a scenario set containing genuine failures
that look like successes. This is the number that answers "why not just ask a VLM?", and it
answers it on grounds you can win — interpretability and auditability — rather than on raw
accuracy, which is not a fight worth picking.

---

## E3 — The cost measurement

**"Cheaper to evaluate" is asserted everywhere and measured nowhere.**

Instrument per-tick cost and report it: wall-clock per tick, and tokens-and-currency per
episode, for the rule-based LTL monitor, the LLM-labelled hybrid, and the pure LLM judge.

This is an afternoon's work and it converts a hand-wave into a column. It is also the
argument that survives contact with a reviewer who does not care about formal methods: a
monitor that runs at control rate for free is a different kind of object from one that costs
an API call per tick.

**Done when:** a cost column sits beside the success column in the same table.

---

## Then: remove the two caveats that limit every number you have

Both are stated honestly in the report, and both cap how much the pilot numbers are worth: the
runs drove **scripted reference plans**, and they were **discrete-mode** episodes. Moving to the
simulator removes both by construction rather than by re-running the gridworld.

### S1 — A live planner

In MuJoCo the robot is driven by Nav2, and on the hardware by TRAV — live planners, neither
written for the monitor. Expect the clean-run false-alarm rate to be the thing that moves: a
real planner produces behaviour the specification was never shown, which is exactly how the
alignment-predicate fault was found.

### S2 — Real dynamics

The MuJoCo bridge is currently kinematic; with the G1 walking policy from `unitree_rl_gym`
driving real physics (implementation plan SIM.2), continuous dynamics, contact and falls are
real. That is where predicate thresholds start mattering — a crisp condition becomes a tolerance
band — and calibrating them in simulation is much cheaper than discovering them on the G1.

**Done when:** E1's table is produced in MuJoCo with real dynamics under Nav2. That table is
Paper 1's main result.

---

## Then: the engineering that gates hardware

### H1 — Finish P12 before the G1 experiment, not after

`docs/packages/P12-planner-independent-schema.md` records the decision that the monitor reads
the robot's own sensors and the waypoints it was commanded to reach, never the planner's
self-report. **Six of the twenty-one current schema keys still come from
`/path_manager/status`, which is the planner's self-report** — `nav_mode`, `nav_state`,
`mission_finished`, `num_waypoints`, `current_target_idx` and `nav_stuck`
(`skill_monitor/adapters/real_g1.json`). P12's "six of fourteen" predates the four pose keys.
Worse, five of the eight propositions in `formulas_g1.json` read those keys. The decision is
recorded and nothing enforces it.

This is not a tidiness issue, it is the embodiment- and planner-agnosticism claim. The report
states the mechanism is embodiment-independent; the schema currently contradicts it. TRAV
replaced Nav2 and the monitor should not have noticed — today it would have broken. If a
reviewer finds this before you fix it, the agnosticism argument goes with it.

Two concrete pieces, both named in P12 and `RESUME.md`:

1. Ship `test_no_forbidden_topic_in_any_descriptor` so the constraint is enforced rather than
   documented. It does not exist yet.
2. Resolve the two facts only the robot can supply: the D435i depth topic name (likely
   `/camera/camera/depth/color/points`) and calibration of `arrival_radius`, the
   `closing_speed` epsilon, the `no_progress` debounce and the `min_range` height band.

`RESUME.md`'s standing instruction is the right order: **run the robot as-is, record the
episode, calibrate P12 off the recording.** The recorder and deterministic replay already
work, so calibration is an offline exercise against a recording rather than robot time.

### H2 — The G1 + TRAV ablation

The first test of the claim on a skill the monitor did not shape. TRAV is being developed
independently, which is exactly what makes it worth measuring.

Same monitor-on / monitor-off ablation as in simulation. The expectation stated in the report
is that the monitored arm completes more runs, and the reasoning is transferable: the failures
that end a navigation episode — stalling, a stuck recovery loop, a safety-guard violation —
are the classes detection already caught in simulation, where catching them early enough to
re-plan converted a failed run into a completed one.

Decide the recovery action with Elias before running. In the pilot, recovery meant a
high-level re-plan; on the robot the equivalent has to be something TRAV can actually be asked
to do. If no recovery action exists, the experiment measures detection only — and detection
alone is already known to be worth +0.00 on success rate, so pick a different dependent
variable (time-to-detection, or operator interventions avoided) rather than running an
experiment whose result you can predict.

### H3 — Simulator, for volume

What remains is the robot's own stack inside the simulator, and scenario reset. Reset is the
one that matters for research throughput: without it you cannot run seeds in volume, and
volume is the difference between evaluating the claim and demonstrating it. `sim/` already has
the MuJoCo bridge, arena and Nav2 configuration.

The protocol is already written on one side: `backend/ablation_runner.py` publishes the
scenario on `/g1/reset` and waits for `/g1/reset_done`. **Nothing subscribes.** Adding that
subscriber to `sim/mujoco_ros_bridge.py` is the whole job, and it also gates D2, which needs
episodes in volume, so it moves earlier in the order than it used to sit.

Two limits to keep in view. The bridge is **kinematic, not dynamic** — it integrates
`qpos[0] += v_x_world*dt` and pins `qpos[2] = 0.78` — so there is no contact and no fall, and
the `fell_over` failure mode cannot fire there at all. And Isaac is an adapter descriptor with
no simulator behind it. Anything that depends on contact physics waits for a dynamic
simulator.

Treat this as infrastructure in service of re-running E1/E2 at scale and feeding D2 — not as
a milestone in itself.

---

## Then: the hybrid — learned grounding under a symbolic structure

Three directions, in order. The first two are the contributions; the third serves them.

### Prerequisite — make the training data exist

None of the learned work can start until per-tick features are recorded and joinable to the
phase the monitor was in. Three defects stand in the way, all verified in the code:

1. **`SensorState.tick()` is never called.** The only references in the tree are docstrings.
   Sensor values stay frozen at schema defaults (`core/adapter_spec.py:947` says so). This is
   package P3's fix, and it is now also the gate on D1 and D2.
2. **`/monitor/observation` has no producer.** `api.build_observation` is called only by
   `frontend/mock_monitor.py`. But `api.OBSERVATION` is *already* in the recorder's
   `RECORDED` set (`core/recording.py:56`), so **one producer in the evaluator turns the
   existing recorder into the dataset generator**, with sensors, `ap_values`, confidence and
   data health joinable to `verdict.phase` on `seq`. This is the highest-leverage change in the
   whole learned programme.
3. **The legacy `/ltl/evaluations` wire hard-sets `seq=None`** (`core/manifest.py:428`), so
   features published there today cannot be joined to a phase at all.

Read the schema through `AdapterSpec.keys()`. `backend/adapters/base.py:103` holds a drifted
nav-only copy that silently drops the four pose keys.

**And the labels must be honest.** There is no fault injection in this repository and no
ground truth; the scenario names from past experiments live in the gridworld repository. The
only labels available here are the monitor's own outputs — `verdict.terminal`,
`failure_modes[]`, `intervention.action` — and scoring a learned detector against those is
circular. Inject faults with a recorded injection tick, and store the ground truth outside the
monitor's output path, so per-tick F1 is possible rather than only per-episode.

### D1 — Learned propositions (first contribution)

A learned model computes calibrated, soft truth values for propositions from the robot's
features; the LTL structure above them is unchanged. This is the direct fix for the one
failure measured so far — the alignment predicate was a brittle hand threshold — and it is the
same substitution `ltl_hybrid` already makes with an LLM. The flat `{name: bool}` interface
means a learned proposition is a drop-in for a rule-backed one, and that is worth stating
explicitly in the paper.

It also converges with H1. Five of the eight current propositions read the planner's
self-report; a proposition learned from the robot's own sensors is planner-independent by
construction. Done this way, D1 is the P12 fix as well as a contribution.

**The experiment:** learned propositions against hand thresholds, same specification, same
episodes — false-alarm rate and F1 on injected faults. Soft truth values need a semantics
decision before they meet the automaton: threshold with debounce (simplest, keeps the current
semantics) or a quantitative robustness semantics (more expressive, a larger change). Start
with the first.

Keep E1's lesson in view: the hybrid's false alarms were fixed by relaxing the formula, not by
a stronger model. Expect the same here, and budget specification iteration alongside model
work.

### D2 — Phase-conditioned anomaly detection (second contribution)

Learn an embedding of the robot's features and model what *nominal* execution looks like
**per progress phase**; flag deviation from the nominal manifold of the phase the symbolic
monitor says the robot is in. This catches what no proposition covers — the long tail nobody
wrote a predicate for. The conditioning variable is already published every tick as
`verdict.phase` and `phase_index`.

**Why conditioning is the contribution:** a whole skill's nominal behaviour is multi-modal —
approach looks nothing like push — so an unconditioned detector models a wide, lumpy
distribution and pays for it in false positives. Within one phase it is close to unimodal. So
the experiment is **per-phase model against one global model, same encoder, same data**, F1 on
held-out injected faults. It is E1's logic in learned form.

Design constraints that follow from the codebase:

- **Train on nominal episodes only** and hold faults out for test, so the detector is never fit
  to the few fault types available.
- **The tick rate is 1 Hz** (`DEFAULT_TICK_HZ`, and P1 says it stays there until P11). That
  gives ~1000 ms per inference, so latency on the AGX is not the problem: a small recurrent
  encoder over the 21-key schema costs microseconds, and a ResNet-18-class vision encoder about
  10 ms on an Orin. TensorRT is not worth its complexity at this rate. The real AGX blocker is
  `RESUME.md:640`, the unbuilt arm64 image. The same 1 Hz cuts the other way for modelling:
  short windows (8–16 ticks) and a low-capacity nominal model.
- **Start with a baseline the deep model has to beat:** per-phase Mahalanobis distance on
  standardised features, no encoder. If the encoder cannot beat it, publish the simple one.
- **Encode the schema carefully:** `yaw` as `(sin, cos)`; one-hot `nav_state`; explicit
  sentinel bits for `min_range = 10.0` and for a missing goal; relative goal coordinates. Append
  the freshness mask from `SensorState.refreshed_keys()` — without it the model learns
  zero-order-held values as if they were measurements.
- **Add a phase-prediction head.** Disagreement with the symbolic phase ("still looks like it
  is approaching; the monitor says pushing") is an anomaly that names itself, which keeps the
  explainability the claim rests on. A bare scalar score would give it up.
- **Keep it out of the test contract.** `deploy/Dockerfile.test` forbids anything beyond
  pytest, and the suite is the merge gate. Training code and torch go behind an optional extra
  with their own compose service; on the robot, a model this small runs as a numpy forward pass
  with no torch at all.
- **Vision is staged.** It has no simulator home yet: MuJoCo renders but is kinematic, Isaac is
  absent, and the gridworld has volume but no images. Validate the plumbing — a visual
  embedding at a lower rate than the symbolic monitor, entering through the existing
  `image_similarity_to_goal` key and `visually_at_goal` proposition — on MuJoCo renders now.
  Visual anomaly science waits for a simulator with contact physics.

### D3 — LTL as a reward machine, for the learned policy

The claim requires a gain for *learned* policies as well as hand-written skills, and every
skill monitored so far is hand-written or scripted. That is the gap most likely to draw a
direct challenge, because a hand-written skill's progress states can always be accused of
being written to match the implementation. A learned policy breaks that circularity: the
progress description is written from the task, not the code.

The automaton is a ready-made reward machine — reward on phase advancement, penalty on safety
violation — which makes Deep RL the natural way to get that policy. But treat it as **a test
subject for D1 and D2, not a contribution of its own**: LTL-shaped reinforcement learning is
an established literature. Pick the smallest learned policy that fails in interesting ways
rather than the most impressive one. Note that the G1's walking controller in simulation is
already a learned RL policy, so the monitored stack contains a learned skill before any policy
is trained here; if a task-level policy is still needed, Isaac Lab is the place to train it.

---

## Running alongside: positioning

The review on description and monitoring is complete; `papers/README.md` holds the queue. Three
directions, each with something specific to settle:

- **Natural language to temporal logic** — whether the translation can come off the shelf. If
  it can, the contribution stays on the progress structure rather than the parsing, which is
  the stronger position. Check whether any of these are a runnable second baseline for E1.
- **Runtime-verification foundations and tools** — what to adopt from existing engines and
  semantics, and how to state the difference from monitors handed a written specification.
  The difference is the derivation, and it needs one clean sentence.
- **Vision–language failure detection** — the baseline to measure against, and what it offers
  the proposition layer. E2 is the experiment that makes this comparison fair.

---

## Decision points

Places where a result should change the plan rather than be absorbed into it.

| if | then |
|---|---|
| E1's flattened arm recovers as well as the full arm | progress states are not buying the result on that scenario. Find one where they do, or narrow the claim to the scenario class where the gap appears. Do not bury it. |
| E2 shows the observation-based judge rarely misses failures | the "harder to mislead" half is weaker than assumed. Shift weight onto cost and interpretability, which E3 and the trace support. |
| the live planner raises the false-alarm rate | specification engineering is a first-class contribution, not a footnote. The alignment-predicate fault becomes a finding rather than an anecdote. |
| TRAV has no available recovery action | H2 measures detection latency, not success rate. Decide this before spending robot time. |
| D1's learned propositions do not beat hand thresholds | the brittleness was specification, not grounding. Fold the result into the specification-engineering finding and move weight to D2. |
| D2's per-phase F1 ≈ global F1 | conditioning is not buying anything. The likeliest cause is that three phases is too coarse: try raw automaton states or sub-phases before abandoning it. If it still holds, report it. |
| D2's per-phase Mahalanobis baseline ≈ the deep encoder | publish the simple model. Do not add deep learning for its own sake. |
| D2 only re-finds what the symbolic guards already catch, and no earlier | the learned layer adds nothing; its value has to be the failures nobody specified. If there are none to find, say so. |
| labels can only be derived from the monitor's own output | stop. A circular benchmark is worse than none. |

---

## Order of work

Superseded in detail by `docs/implementation-plan.md`; the shape is:

**Build the simulator**

1. **SIM.1–SIM.2** — reset, then real dynamics with the G1 walking policy. Nothing else produces
   new evidence until these exist.
2. **Prerequisite** — `SensorState.tick()`, `/monitor/observation`, episode records — alongside.
3. **SIM.3–SIM.5** — sensors, the fault library with injection ticks, lockstep sweeps; plus
   **H1** planner independence, since simulation runs Nav2 and the robot runs TRAV.

**Prove the structure matters — Paper 1**

4. **E1** flattened-specification control, **E3** cost, **E2** missed failures — all in MuJoCo.
5. **H2** — hardware validation on the G1 with TRAV.

**Add learning where the structure is weak — Paper 2**

6. **D1** learned propositions, **D2** phase-conditioned anomaly detection, on recordings from
   the sweeps.
7. **Isaac Sim** — photoreal vision for D1 and D2, and the same specification on a third
   embodiment.

Steps 1–5 are Paper 1: progress states beat the same monitor without them, catch failures an
observation-based judge misses, and cost less per tick, on a humanoid with real dynamics. Steps
6–7 are Paper 2: learning makes the structure's propositions robust and covers the failures
nobody specified, without giving up the context and explainability that made the structure worth
having.
