# Research roadmap

A working guide for advancing the thesis, written after the September progress report.
Ordered by what settles the claim, not by what is easiest to build.

Companion documents: `docs/report/progress_report.tex` (what the supervisor has seen),
`papers/README.md` (the reading queue), `RESUME.md` (engineering state), `docs/packages/`
(per-package design).

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
experiment rather than an illustration. Construct the gridworld equivalent: a scenario where
the terminal observation looks like success but the skill never passed through the required
progress states. For box-push, candidates are a box that reaches the goal tile without the
agents ever establishing the push formation, or an agent that reports arrival having never
left its first phase.

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

Both are currently stated honestly in the report, and both cap how much any result is worth.

### S1 — Drive the live planner, not scripted reference plans

Everything measured so far drove scripted reference plans. So what is established is that
*detection plus re-planning* helps a scripted executor. The interesting claim — that the
monitor helps a real planner — is not yet tested, and a reviewer will go straight at it.

Re-run E1 under the live MAAOS planner once E1 exists in scripted form. Expect the clean-run
false-alarm rate to be the thing that moves: a real planner produces behaviour the
specification was never shown, which is exactly how the alignment-predicate fault was found.

### S2 — Run in continuous mode

The environment is a continuous version of MiniGrid but the figures come from discrete-mode
episodes. Continuous dynamics are where predicate thresholds start mattering — an alignment
or progress predicate that is crisp in discrete mode becomes a tolerance band — and
calibrating those is work that will be needed again on the robot. Doing it in the gridworld
first is much cheaper than discovering it on the G1.

**Done when:** E1's table is reproduced in continuous mode under the live planner. That table
is the paper's main result.

---

## Then: the engineering that gates hardware

### H1 — Finish P12 before the G1 experiment, not after

`docs/packages/P12-planner-independent-schema.md` records the decision that the monitor reads
the robot's own sensors and the waypoints it was commanded to reach, never the planner's
self-report. **Six of the fourteen current schema keys still come from
`/path_manager/status`, which is the planner's self-report.** The decision is recorded and
nothing enforces it.

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

Same monitor-on / monitor-off ablation as the gridworld. The expectation stated in the report
is that the monitored arm completes more runs, and the reasoning is transferable: the failures
that end a navigation episode — stalling, a stuck recovery loop, a safety-guard violation —
are the classes detection already caught in simulation, where catching them early enough to
re-plan converted a failed run into a completed one.

Decide the recovery action with Elias before running. On the gridworld, recovery meant a
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

Treat this as infrastructure in service of re-running E1/E2 at scale with continuous dynamics
and noisy perception — not as a milestone in itself.

---

## Then: the two gaps the claim names explicitly

### L1 — A learned policy

The claim requires a measurable gain for *learned* policies as well as hand-written skills.
Every skill monitored so far is hand-written or scripted. This is the gap most likely to draw
a direct challenge, because a hand-written skill's progress states can always be accused of
being written to match the implementation.

A learned policy breaks that circularity: the progress description is written from the task,
not from the code. Pick the smallest learned policy that fails in interesting ways rather than
the most impressive one.

### L2 — The VLM proposition layer

Good assessment on hardware needs a vision–language model supplying propositions. Note the
architectural point that makes this tractable: propositions are a flat `{name: bool}`
interface, so a VLM-backed proposition is a drop-in for a rule-backed one and the progress
structure above it does not change. That is worth stating explicitly in the paper — it is the
same substitution `ltl_hybrid` already demonstrates with an LLM.

Keep E1's lesson in view: the hybrid's false alarms were fixed by relaxing the formula, not by
a stronger model. Expect the same with a VLM, and budget specification iteration rather than
model shopping.

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

---

## Order of work

1. **E1** — flattened-specification control. The claim has no direct evidence until this exists.
2. **E3** — cost measurement. Cheapest item here; do it while E1 runs.
3. **E2** — missed-failure scenarios. Needs new scenarios, so it is slower than E1, but it
   carries the strongest half of the argument.
4. **H1** — P12 enforcement and calibration, off a recording. Gates every hardware claim.
5. **S1 + S2** — live planner, continuous mode. Re-run E1; this becomes the main result.
6. **H2** — G1 + TRAV ablation, recovery action agreed in advance.
7. **H3** — simulator reset, for volume.
8. **L1** — a learned policy.
9. **L2** — VLM propositions.

E1 through E3 are a paper on their own: progress states beat the same monitor without them,
catch failures an observation-based judge misses, and cost less per tick. Everything after
step 4 widens that to hardware and to skills the monitor did not shape.
