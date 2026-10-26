# The formal model: research question, definitions, properties, and what they predict

This is the mathematical core of the work, written so it can be defended line by line. Each
definition points to where it is implemented; each property has a one-paragraph proof and the
measured number it predicts. Checked against the code and `docs/e1b_ros/results.md`.

---

## 1. Research question and hypotheses

**RQ.** Does giving a language-generated runtime monitor the **stages** of a skill make it
detect failures earlier, and does earlier detection improve task success?

| | Hypothesis | Measured by |
|---|---|---|
| **H1** | For failures specific to a stage, detection latency with stages < without. | ticks from fault to first alarm, paired by scenario |
| **H2** | With a deadline, on-time success with stages > without; without a deadline, no difference. | delivered within k × nominal time |
| **H3** | The monitor catches failures that hand-written executor checks miss. | failed runs with no alarm ("silent") |
| **H0** (stated up front) | For failures every stage shares (falls), stages change nothing. | same latency in every version |

---

## 2. Definitions

Time is discrete: ticks t = 1, 2, … at 1 Hz.

**D1 — Atomic propositions and labelling.** AP is a finite set of propositions. The
evaluator maps the robot's observations of tick t to the set of true propositions:
σₜ = L(oₜ) ⊆ AP. Each proposition is a rule over sensor keys declared by the robot's
adapter, e.g. `near_object ⇔ object_dist < 0.5`, and
`holding_object ⇔ object_z ≥ 0.3 ∧ ‖object_xy − base_xy‖ ≤ 0.5` (a missed detection keeps the
previous value). *Code:* `skill_monitor/core/adapter_spec.py` (`_fn_object_held`).

**D2 — Specification.** S = ⟨AP, Φ, M, Π, succ, fail⟩:
- Φ: task formulas in LTL (here one: φ = F(task_started ∧ F(near_object ∧ F(holding_object ∧
  F(near_dropoff ∧ F(object_at_dropoff ∧ ¬holding_object)))))).
- M: named safety modes, G-formulas: `G(upright)`, `G(¬obstacle_too_close)`.
- Π = (π₁, …, πₙ): the phases (progress states), in order.
- succ, fail: terminal conditions (Boolean formulas over AP).
*Code:* `skill_monitor/specs/formulas_g1_carry.json`.

**D3 — Phase (progress state).** πᵢ = ⟨enterᵢ, invᵢ, progᵢ, exitᵢ, Tᵢ, kᵢ⟩: Boolean formulas
over AP for entry, the invariant (must hold throughout), progress and exit; a time limit Tᵢ
(ticks); a progress-violation limit kᵢ. Our spec: WalkToObject (T = 45), Grasp (T = 10), Carry
(T = 60, inv = upright ∧ holding_object ∧ ¬obstacle_too_close), Place (T = 10); k = 3.

**D4 — Automata.** Each formula ψ ∈ Φ ∪ M is compiled by Spot into a deterministic, complete,
state-based Büchi automaton A_ψ = ⟨Q_ψ, q⁰_ψ, δ_ψ, F_ψ⟩ over the alphabet 2^AP. A state is a
**rejecting sink** if it is not accepting and its only edge is a true self-loop.
*Code:* `skill_monitor/core/automata.py` (`LTLMonitor`).

**D5 — Monitor state and update.** m = ⟨i, c, v, (q_ψ)_ψ⟩: current phase index, ticks spent in
the phase, progress-violation count, one state per automaton. On label σ:
1. every automaton steps: q_ψ ← δ_ψ(q_ψ, σ);
2. **fault** if σ ⊭ invᵢ (immediately), or c ≥ Tᵢ, or v ≥ kᵢ (v counts ticks with σ ⊭ progᵢ);
3. otherwise, if σ ⊨ exitᵢ: i ← i+1, c ← 0, v ← 0; else c ← c+1.
*Code:* `skill_monitor/backend/monitor_node.py` (phase step; "Hard invariant (immediate
failure)" at ~line 1292).

**D6 — Verdict.** VIOLATED if a phase faults, an automaton is in a rejecting sink, or fail
holds; SATISFIED if succ holds and every task automaton is accepting; otherwise UNDECIDED. A
verdict maps to an action on the ladder continue < warn < slow < re-plan < halt < abort
(`skill_monitor/core/monitor_action.py`).

---

## 3. Properties, with proofs and predictions

**P1 — A stage violation is detected at the tick it is observed.**
If the monitor is in phase i at tick t and σₜ ⊭ invᵢ, the verdict at t is VIOLATED.
*Proof.* Step 2 of D5 checks invᵢ every tick and faults on the first tick it is false. ∎
The only delay is labelling (whether the evaluator already sees the fact at that tick).
*Prediction:* a drop during Carry is caught one tick after it happens.
*Measured:* drop at 21.6 s, alarm at 22 s; median 1 tick over 20/20 runs.

**P2 — The ordered task formula can never be violated on a finite prefix.**
φ = F(a₁ ∧ F(a₂ ∧ … ∧ F aₖ)) is a guarantee (co-safety) property: any finite prefix that has
not yet satisfied φ can be extended to one that does (the robot can still re-grasp and
deliver). So no finite prefix is a *bad prefix*, and the LTL₃ verdict (Bauer, Leucker,
Schallhart 2011) is "?" until φ is satisfied.
*Proof.* For a prefix u not satisfying φ, take u followed by a word in which a₁, …, aₖ become
true in order; it satisfies φ. ∎
*Check:* Spot's automaton for φ has 6 states, one accepting (state 5), and **no rejecting
state** (verified by listing the states).
*Prediction:* the same automata *without* phases ("LTL only") cannot catch a drop during the
task; it is noticed only at the terminal check.
*Measured:* LTL only catches the drop at 14 ticks, exactly like the flat spec.

**P3 — A time limit bounds detection of a stuck stage.**
If phase i is entered at tick t₀ and never exits, a fault is reported by tick t₀ + Tᵢ.
*Proof.* c increases by one per tick in phase i (D5 step 3) and step 2 faults when c ≥ Tᵢ. ∎
*Prediction:* a failed grasp (the robot never reaches "holding") is caught by Grasp's 10-tick
limit, well before the end.
*Measured:* 4 ticks after the failure with phases vs 19 without (20/20).

**P4 — What the flat spec cannot say.**
The flat spec has a single phase whose invariant must hold for the whole task. holding_object is
false before the grasp, so it cannot be part of a whole-task invariant; the flat invariant is
upright ∧ ¬obstacle_too_close.
*Consequence:* a drop violates nothing the flat spec checks until the terminal condition is
evaluated (when the executor claims success).
*Measured:* flat catches the drop at 14 ticks, at completion.

**P5 — Shared failures are unaffected (H0).**
If a failure violates a condition that every phase's invariant contains (upright), the flat
spec contains it too, and both detect it at the same tick by P1.
*Measured:* falls caught in 1 tick by every version.

**Honest note on expressiveness.** Phases do not make the logic more expressive. The Carry
rule can be written in LTL, e.g. G(grasped → (holding_object U near_dropoff)), and the time
limits in a timed logic (MTL / STL). The claim is not expressiveness; it is that **organising
the specification by stages makes such conditional rules explicit, so a language model writes
them**, and the experiments show these are exactly the rules that catch failures early.

---

## 4. The decision-making view: a POMDP

**Model.** ⟨S, A, O, T, Z, R⟩ (Kaelbling, Littman, Cassandra 1998):
- s = ⟨x, κ, f⟩: physical state x, **true stage κ**, fault flag f — hidden.
- o: the ROS messages of one tick; Z(o | s) includes perception noise (2 cm, 5% missed).
- a ∈ {continue, warn, slow, re-plan, halt, abort}; T: physics, executor and faults.
- R: delivered within the deadline; cost of false alarms.

Belief update: b′(s′) ∝ Z(o | s′) Σₛ T(s′ | s, a) b(s).

**Our monitor as a belief filter.** The monitor state m (D5) is a *point* belief over the task
part of s: (stage, automaton states). If labelling is correct (L(o) reports the true
propositions) and stage changes are determined by the propositions, the belief over the task
state is a point mass and D5 is the exact belief update for it. With noisy labels it is a
deterministic approximation; the policy (D6 → action) is fixed, not optimised.

**Why stages matter, in this view.** The stage is part of s. The same observation
"not holding" is likely under κ = WalkToObject and very unlikely under κ = Carry with f = 0, so
it is informative exactly when the stage is tracked.

**Value of information — why the deadline matters.** Let ℓ be detection latency after a fault,
r the time a re-plan needs to recover, and d the time left before the deadline. A recoverable
fault ends in on-time success only if ℓ + r ≤ d. Lowering ℓ (P1, P3) therefore raises on-time
success when d is tight, and changes nothing when there is no deadline (d = ∞).
*Measured:* deadline 1.5×: 64% with stages vs 36% without (LTL only also 36%); no deadline:
82% vs 84%.

---

## 5. Results, as answers to the hypotheses

| | Result | Verdict |
|---|---|---|
| **H1** | drop 1 vs 14 ticks; failed grasp 4 vs 19; earlier in 20 of 20 paired runs | supported (P1, P3) |
| **H2** | 64% vs 36% with a deadline; 82% vs 84% without | supported (value of information) |
| **H3** | hand-written checks 40/40 silent → 0/40 with the monitor added | supported |
| **H0** | falls caught in 1 tick by every version | as predicted (P5) |
| Not predicted / missed | slow navigation and detours within the time limits; skipped pick-up; odometry drift | reported; fixes: calibrated limits, progress toward each stage's target |

**How sure — say counts, not tests:** "Stages caught it earlier in all 20 paired runs, later in
none; for success, 64% vs 36% over 160 runs per version."

*Only if asked about statistics* (backup, don't volunteer):
- 20 of 20 is like 20 coin flips all landing heads: about 1 in a million (p = 1.9·10⁻⁶).
- 64% vs 36% of 160 runs each; a split that uneven by chance has p = 7·10⁻⁷.

---

## 6. Assumptions and limits (say them before they are asked)

1. **Correct labelling** is assumed by P1 and by "exact belief". Real perception is noisier
   than our stand-in.
2. **ACCEPTED is not LTL₃ "true" for safety modes:** `G(upright)` starts in an accepting state
   (verified). We act only on VIOLATED, which is sound; the fix is Spot's monitor construction
   for safety formulas.
3. **Sink detection is sound but incomplete** (multi-state rejecting components are missed);
   none occur in our formulas.
4. **Thresholds are uncalibrated** (written by the LLM from the words).
5. **Simulation**: attached grasp, simulated perception; the real G1 is next.
