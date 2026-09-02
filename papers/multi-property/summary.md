# Multi-Property Temporal Logic Monitoring (LoomRV)

**Arınç Demir, Dogan Ulus** (Boğaziçi University, Istanbul, Türkiye)
arXiv:2605.13668v1 [cs.LO], 13 May 2026 · page header reads "Formal Methods in Computer-Aided Design 2026"
BibTeX key: `multiproperty2026` — see `bibtex.md`

> **Read this first.** This is a *past-time* LTL/MTL paper built on *sequential networks*,
> not a Büchi-automaton or LTL3 paper. It never mentions product automata, state-space
> blowup, good/bad prefixes, or three-valued verdicts. It is nonetheless the single most
> on-point citation for `MultiMonitor`, because it is the only paper in this reading list
> that explicitly benchmarks **n independent monitors vs. one conjoined formula vs. one
> shared structure with one output per property** — and finds the conjoined formula loses.
> Section 6 flags precisely where the paper stops and where our own reasoning begins.

---

## 1. In one paragraph

Runtime verification tools compile each temporal-logic property into its own monitor, so a
system with dozens of properties runs dozens of monitors over the same trace, re-evaluating
whatever subformulas the properties happen to share and re-parsing the trace once per
monitor. Demir and Ulus present **LoomRV**, a C++ online monitoring framework that instead
compiles a *set* of past-time LTL/MTL (PastLTL/PastMTL) specifications into a **single shared
directed acyclic graph of subformula nodes with one designated root — and therefore one
verdict output — per property**. Sharing is achieved by a content-addressable node database
that keys each subformula by a structural hash, so structurally identical subformulas across
different properties collapse to one node evaluated once per timestep. The DAG is then
serialised into a *linearized execution schedule* (a contiguous array of fixed-size node
records in topological order, child references as integer indices) and evaluated by a
recursion-free single forward pass, with all intermediate interval-set state living in a
**zero-allocation double-buffered arena** sized once at monitor creation from a static
`O(N·B)` bound. Against Reelay — a state-of-the-art past-time monitor by the same second
author, which uses the same compositional construction but synthesises one heap-allocated,
object-oriented monitor per property — LoomRV reports 2×–4.5× per-property throughput from
the execution model alone and 6×–12× end-to-end when 30 properties are monitored together,
in both discrete and dense time. Crucially for us, the paper keeps **per-property outputs as
a first-class design requirement** and shows that folding the property set into a single
conjoined formula is *not* the right answer.

---

## 2. Key concepts

| Term | Definition (as the paper uses it) |
|---|---|
| **Multi-property monitoring** | The paper's name for our setting: one execution trace, *m* registered properties, one monitor object, *m* verdict outputs `y₁…y_m` per timestep (Fig. 3). Contrasted throughout with **single-property monitoring**, which instantiates one independent monitor per property over the same trace. This is the terminology to adopt. |
| **Shared / unified computation DAG** | One graph across all properties, where each node is a *unique* subformula and each property is identified by a designated **root node**. Replaces the per-property syntax *tree*. Topology goes tree → DAG; evaluation goes multiple passes → single pass (Table I). |
| **Structural deduplication / content-addressable node database** | The mechanism. During bottom-up parsing each candidate node is hashed on operator type plus, per category: predicate name; child id (negation); child id + interval bounds (Once, Historically); *canonicalised sorted* child pair (commutative ∧, ∨, so `p∧q` and `q∧p` hash alike); ordered child pair + bounds (Since). Hash hit plus confirmed structural equality ⇒ reuse the existing node id. |
| **Node compression** | Their sharing metric: (total nodes for independent monitors) / (nodes in the unified DAG). Ranges 1.31×–4.09× over their four synthetic scenarios; speedup tracks it, especially in dense time. |
| **Linearized execution schedule** | The compiled DAG flattened into a contiguous array of fixed-size records in strict topological order (operands before operators), each holding operator tag, two integer child indices, temporal bound parameters, persistent cross-timestep state, and the current-timestep output. Immutable once finalised. |
| **Zero-allocation double-buffered arena** | Two contiguous buffers `B_prev` / `B_cur` for all interval-set state; nodes read children from earlier regions of `B_cur` and their own history from `B_prev`, and append output at a bump-allocated write cursor. Buffers swap and the cursor resets at each timestep boundary. No heap allocation inside the evaluation loop. |
| **Sequential-network monitor construction** | The baseline it extends (ref. [3], Ulus, LMCS 2026): one computation node per subformula with a stateful update rule, evaluated synchronously each timestep. **This compositionality is what makes subformula sharing possible at all** — and it is exactly what Spot's whole-formula Büchi translation does not give us. |

---

## 3. Method

**Frontend (compile time).**
1. Properties are written in the Reelay Expression Format and parsed one at a time into syntax trees.
2. The *runtime builder* does not keep those trees separate. Building bottom-up, before inserting any subformula node it computes the structural hash above and looks it up in the content-addressable database; on a hit (with confirmed structural equality) it returns the existing node id, otherwise it assigns a new id and records the node. The returned id propagates upward as the child reference in the parent (Fig. 5).
   *Worked example (Fig. 6):* φ₁ = P<sub>[0,10]</sub>(p∧q) and φ₂ = H(p∧q) share `p`, `q` and `p∧q`; only the two roots are unique. Five nodes instead of eight. `p∧q` is evaluated once per timestep no matter how many properties reference it.
3. Properties **may be registered incrementally** — each registration appends new nodes and records a new root index. The *config module* then selects the time model (discrete or dense) and **finalises** the monitor by serialising the DAG into the linearized execution schedule. **After finalisation the schedule is immutable** and the monitor begins accepting trace data.

**Runtime (per timestep).**
1. *Input processor* turns rich messages (JSON records, binary formats, raw structs) into atomic-predicate valuations. Two interchangeable feeders: JSON (newline-delimited records, SIMD-accelerated parser, ref. [5]) and binary (pre-encoded bitfield, no parse cost on the hot path). The feeder distinction turns out to matter a lot to the headline numbers.
2. *Execution engine* walks the array in topological order, one forward pass, no recursion. Each node computes from its dependencies' current values plus, for temporal operators, its own `B_prev` state.
3. *Output processor* reads the root node of each property and emits the verdict vector.

**Memory bound.** For predicate/Boolean/untimed nodes the output is `O(1)`. For a metric temporal node the state is a set of intervals in a sliding window bounded by the operator's upper bound `b`; worst-case fragmentation is an adversarial alternating signal against a point-interval property such as P<sub>[b:b]</sub>q, giving at most ⌈b/2⌉ disjoint non-adjacent points, hence `O(b)` intervals per timed node and **`O(N·B)`** total for `N` nodes and maximum bound `B`. Because that depends only on static formula parameters and not on trace length, the arena is allocated exactly once — no dynamic allocation and no overflow handling at runtime. The authors note actual consumption stayed well below the bound in their experiments (no figure given).

**Semantics monitored.** Discrete-time PastMTL: `φ ::= ⊥ | p | ¬φ | φ₁∧φ₂ | Yφ | φ₁ S_[a:b] φ₂`, with P (Past Eventually) and H (Historically) derived from timed Since. Dense time shares the infrastructure with interval-valued rather than scalar outputs.

---

## 4. Results

Setup: Intel Core i7-10750H (6 cores, 2.60 GHz base, 12 MB L3), Linux-based containerised
benchmarking environment. Benchmarks from the *Timescales* MTL benchmark generator (ref. [6],
Ulus, RV 2019): 30 properties, traces of 1 000 000 steps (discrete) / maximum simulated time
1 000 000 (dense). The authors verified **none of the 30 Timescales formulas contains a
repeated subexpression**, so no *intra*-formula deduplication occurs — all sharing is
cross-property.

**(a) Sharing ablation** — four synthetic 10-formula sets with known node compression,
1 000 000 timesteps:

| Scenario | Node compression | Discrete: Multi vs. Reelay-Seq | Multi vs. LoomRV-Seq |
|---|---|---|---|
| Nested best-case | 4.09× (75% dedup) | 16.1× JSON / 10.6× binary | 5.3× / 3.1× |
| Best-case shared core | 3.57× (72%) | (Table II) | — |
| Worst-case unique leaves | 1.67× (40%) | (Table II) | — |
| Nested worst-case | 1.31× (23%) | 11.4× JSON / 6.6× binary | 3.2× / 1.5× |

Dense time, maximum sharing: 12.3× JSON / 11.5× binary over Reelay-Seq; 3.6× / 2.3× over
LoomRV-Seq. Minimum sharing: the advantage over LoomRV-Seq shrinks to 1.8× / 1.2×.

**(b) Single-property (30 properties, one at a time)** — isolates the execution model:
discrete median speedup over Reelay 2.00× JSON (mean 2.01×) and 1.81× binary (mean 2.01×),
individual range 1.55×–2.82×. Dense, across 90 configurations (Dense1/Dense10/Dense100):
median 3.45× JSON (mean 3.46×) and 4.53× binary (mean 4.43×), range 2.2×–5.8×.

**(c) The ablation that matters to us** — all 30 properties at once, five configurations:

| Configuration | Discrete (s) | Speedup | Dense (s) | Speedup |
|---|---|---|---|---|
| Reelay-Sequential (JSON) | 9.34 | 1.0× | 27.49 | 1.0× |
| Reelay-**AND** (JSON) | 6.38 | 1.5× | 24.26 | 1.1× |
| LoomRV Sequential (JSON) | 4.42 | 2.1× | 9.63 | 2.9× |
| LoomRV-**AND** (JSON) | 0.80 | 11.6× | 4.05 | 6.8× |
| **LoomRV Multi (JSON)** | **0.80** | **11.7×** | **3.77** | **7.3×** |
| Reelay-Sequential (binary) | 4.66 | 1.0× | 22.28 | 1.0× |
| Reelay-AND (binary) | 3.63 | 1.3× | 21.78 | 1.0× |
| LoomRV Sequential (binary) | 1.58 | 3.0× | 5.80 | 3.8× |
| LoomRV-AND (binary) | 0.70 | 6.6× | 3.72 | 6.0× |
| **LoomRV Multi (binary)** | **0.71** | **6.6×** | **3.45** | **6.4×** |

*"AND"* = all 30 properties conjoined into a single formula via explicit `∧` operators,
monitored by one instance — i.e. the monolithic-conjunction strategy. **Multi vs. AND is the
direct answer to our design question.** In discrete time they tie (0.80 vs 0.80 s JSON;
0.71 vs 0.70 s binary), because scalar-Boolean node evaluation makes the 29 extra conjunction
nodes free. In dense time, where each node does interval-set work, Multi wins: the shared DAG
holds **107 nodes vs 136** for the AND formulation, and Multi is faster (3.77 vs 4.05 s JSON;
3.45 vs 3.72 s binary). So the conjoined formula is at best a tie and at worst measurably
slower — **and it produces one verdict instead of thirty.**

Two honest observations from the authors' own text: Reelay-AND gains only 1.0×–1.5× over
Reelay-Sequential (its object-oriented evaluator still processes every node independently);
and in discrete time much of Multi's advantage over LoomRV-Sequential comes from ingesting
and parsing the trace **once** rather than 30 times — they say so explicitly, and it is why
the relative multipliers are smaller with the fast binary feeder.

---

## 5. Limitations

1. **Past-time only.** PastLTL/PastMTL. No future operators, no Büchi automata, no LTL3.
   Verdicts are per-timestep Booleans (or interval-valued in dense time), not ⊤/⊥/?.
2. **No semantic analysis whatsoever.** The paper never asks whether separate outputs mean
   something different from a conjoined verdict. *This is structural, not an oversight*: a
   past-time formula has a definite Boolean value at every timestep, so `output(φ₁) ∧
   output(φ₂) = output(φ₁∧φ₂)` holds trivially and pointwise. **The interesting composition
   question only exists in a future-time, three-valued setting — i.e. in ours.** See §6 Q2.
3. **Speedup is confounded with I/O.** LoomRV Sequential — no sharing at all — already
   collects 2.1×–3.8×, and at only 1.31× node compression Multi still gets 3.2× over
   LoomRV Sequential largely by parsing once. The shared-DAG contribution is real but
   smaller than the headline 6×–12× suggests.
4. **Immutable after finalisation.** Incremental registration is a *compile-time* facility;
   once the execution schedule is serialised it cannot change. Adding or retiring a property
   at runtime means recompiling the whole monitor. Independent monitors have no such constraint.
5. **Evaluation breadth.** One baseline (Reelay), one machine, one specification suite,
   synthetic sharing scenarios. No repetition count, variance or confidence intervals
   reported. No measured memory footprint (only the analytical `O(N·B)` bound plus a
   qualitative remark) and no measured compilation time.
6. **Benchmarks admitted to be the weak point.** The conclusion calls for standardised
   multi-property benchmark suites and states that the degree of subexpression overlap in
   industrial specification sets "remains difficult to quantify" — so the practical value of
   deduplication on real specification sets is unestablished.
7. **No robotics or CPS case study**, and no expensive/perception-derived predicates. All APs
   are treated as free inputs available every timestep (see §6 Q3 — this is the crux for us).
8. Distributed monitoring over publish-subscribe networks and FPGA synthesis are future work only.

---

## 6. For `skill_monitor`

Files in scope: `/home/user/LtlMonitor/skill_monitor/core/automata.py` —
`MultiMonitor` (line 416), `LTLMonitor.get_required_aps` (line 327),
`LTLMonitor._find_sink_states` (line 387), `LTLMonitor._compute_status` (line 404).

### Q1 — What the literature says about product vs. parallel

**Terminology to adopt.** Call our setting **multi-property monitoring**, and the alternative
**single-property monitoring** (Demir and Ulus's own words). Their Table I is the vocabulary
table: *monitor structure* (one dedicated monitor vs. one shared monitor), *construction*
(independent vs. unified), *computation topology* (tree vs. DAG), *computation reuse* (none
vs. shared), *evaluation* (multiple passes vs. single pass), and **outputs (one per monitor
vs. one per property)**. Note that "one output per property" appears as a *design requirement*
of their unified monitor, not as an artefact of the naive baseline — they went to the trouble
of keeping designated roots precisely so attribution survives sharing. That is our argument,
made by someone else, in a venue a reviewer will accept.

**The real trade, honestly stated.** There are three points on the axis, not two:

| | one monitor per formula (`MultiMonitor` today) | one shared structure, per-property roots (LoomRV Multi) | one monolithic conjunction (Reelay-AND / a product automaton) |
|---|---|---|---|
| State cost | sum of component sizes, Σ\|Qᵢ\| | one deduplicated DAG | product, up to Π\|Qᵢ\| in the automaton setting *(standard automata theory; **not** measured in this paper)* |
| Verdict attribution | **per formula, free** | **per formula, preserved by design** | **lost** — one verdict for the whole set |
| Which formula's state to display | each monitor's own `current_state` | each root | a joint state that projects back only with extra bookkeeping |
| Add / remove a formula | independent, at any time | compile-time only; schedule immutable after finalisation | full retranslation |
| Redundant work | shared subformulas re-evaluated; trace ingested once per monitor if naive | eliminated | eliminated, but pays for the extra `∧` nodes |
| Measured cost, 30 properties, dense, JSON | 9.63 s (LoomRV Seq) | **3.77 s** | 4.05 s (LoomRV-AND) |

**Is anything *lost* by monitoring separately?** Per this paper: only computation — redundant
subformula evaluation and redundant trace ingestion. It never claims a semantic loss, and in
its past-time setting there is none. **In our future-time three-valued setting there *is* a
possible loss, and the paper cannot tell us about it — see Q2.** Cite this paper for cost and
attribution; never for semantic equivalence.

**Two facts about our own design worth stating explicitly**, because a reviewer will otherwise
assume we simply took the easy road:

- Our `Σ|Qᵢ|` is genuinely small — a liveness formula plus two `G(...)` invariants are a
  handful of states each — whereas a degeneralised product over the same set is where the
  blowup risk lives. Put the actual number in the paper (`LTLMonitor.num_states()` gives it).
- **Componentwise acceptance is strictly more informative than a single conjunction
  automaton's acceptance.** `all_accepted()` is exactly the *generalized*-Büchi condition over
  the component automata; translating `φ₁ ∧ φ₂ ∧ φ₃` into one Büchi automaton degeneralises
  that condition into a rotating-counter construction, from which the individual components'
  acceptance is no longer readable off the state. Keeping them apart preserves information
  that a product destroys. That is a formal-methods argument, not just an engineering one.

### Q2 — The correctness subtlety. Yes, there is one. Take it seriously.

> Everything in this subsection is our own reasoning under LTL3 (Bauer, Leucker and
> Schlingloff — `papers/ltl3-bauer/`). **The paper contains none of it** and cannot, for the
> reason in Limitation 2. It has not been machine-checked; the counterexamples below are small
> enough to confirm by hand or with Spot in ten minutes, and that should be done before
> anything goes in the paper.

Write `[u ⊨ φ]` for the LTL3 verdict on a finite prefix `u`: `⊤` if every infinite extension
satisfies φ (a *good prefix*), `⊥` if no extension does (a *bad prefix*), `?` otherwise.

**Result A — the good news composes exactly.**
`[u ⊨ φ₁∧φ₂] = ⊤  ⟺  [u ⊨ φ₁] = ⊤ and [u ⊨ φ₂] = ⊤`.
Proof: `∀w. uw ⊨ φ₁∧φ₂` iff `(∀w. uw ⊨ φ₁) ∧ (∀w. uw ⊨ φ₂)` — the universal quantifier
distributes over the conjunction in the matrix. Both directions hold. **So conjunctive
composition of ⊤ is sound and complete; an `all_accepted()`-style rule is exactly right.**

**Result B — the bad news composes only one way.**
`[u ⊨ φᵢ] = ⊥ for some i  ⟹  [u ⊨ φ₁∧φ₂] = ⊥`. **The converse is false.**
So `any_violated()` is **sound** (we never raise a violation the conjunction would not also
call a violation — no false alarms) but **incomplete** (the conjunction can be `⊥` while every
component is still `?`). In Bauer–Leucker–Schlingloff's vocabulary this is a **loss of
anticipation**: parallel monitors can report a violation *later than*, or *never* where, a
joint monitor reports it immediately. This is exactly what a formal-methods reviewer will probe.

**Counterexample 1 — safety × liveness, our actual spec shape.**
Let `φ₁ = F g` (a liveness goal) and `φ₂ = G(h → G ¬g)` (a safety mode: once halted, never
reach the goal). Take the one-step prefix `u = ⟨h true, g false⟩`.
- `[u ⊨ φ₁] = ?` — `F g` has no bad prefix at all; some extension always contains `g`.
- `[u ⊨ φ₂] = ?` — no bad prefix yet; the extension where `g` never occurs satisfies it.
- `[u ⊨ φ₁∧φ₂] = ⊥` — every extension must contain `g` (φ₁) and must not (φ₂, after `h`).

Two independent monitors sit at `INCONCLUSIVE` **forever**. A conjunction monitor reports
`VIOLATED` immediately. This is not a delay; it is a permanent miss.

**Counterexample 2 — both properties are pure safety, so "safety is fine" is not the escape.**
`φ₁ = G(a → X b)`, `φ₂ = G(a → X ¬b)`, prefix `u = ⟨a⟩`. Neither is `⊥` on `u` (each has a
satisfying extension), but `φ₁∧φ₂ ≡ G ¬a`, which *is* `⊥` on `u`. So the honest answer to
"no for safety properties, yes otherwise" is **no — it can differ even when every formula is a
safety property.** Here the delay is one step; with nesting or metric bounds it can be
arbitrarily long.

**So when *is* independent monitoring provably equivalent?** Three usable conditions:

- **(S1) Disjoint atomic propositions.** If `AP(φᵢ) ∩ AP(φⱼ) = ∅` for all `i ≠ j`, independent
  monitoring is *exactly* equivalent to joint monitoring on all three verdicts. Sketch: each
  `φᵢ`'s truth depends only on its own APs, so witnessing extensions for the components merge
  coordinate-wise into one common extension. **Cheap, syntactic, checkable at spec-load.**
- **(S2) Pure state invariants.** If every formula is `G(ψ)` with `ψ` a Boolean combination of
  *current-step* APs (no nesting, no `X`, no bounds), then `[u ⊨ G ψ] = ⊥` iff `ψ` fails at
  some position of `u`, and `⊥` of the conjunction iff `⊥` of some conjunct. Exact.
  **`G(!collision_risk)` and `G(upright)` are both of this shape, so those two together are
  provably safe.** Our exposure is not there.
- **(S3) Offline product-emptiness certificate — the recommendation.** The general condition is
  decidable and cheap *once*, at spec-load time, off the control loop: build
  `spot.product(a₁, …, a_n)` and check whether any reachable product state is **empty (no
  accepting run from it) while every one of its component projections is non-empty**. If no
  such state exists, parallel monitoring loses nothing for *this* specification set, and we can
  say so with a certificate rather than a hope. If one exists, it is a concrete witness prefix
  that a reviewer would otherwise construct for us. **This buys the product's completeness at
  compile time while keeping n independent automata on the hot path — the best of both, and a
  defensible contribution in its own right.**

**Where `skill_monitor` is actually exposed.** Not `G(!collision_risk)` and `G(upright)` — S2
covers them. The risk is the **liveness formula against a safety mode over shared APs**, and
especially anything in the `TIMEOUT`/`PROGRESS` categories: a bounded-liveness obligation (the
`timing_bounds` `max_steps` machinery in `format_automaton`'s state annotations) combined with a
safety mode that forbids the very proposition the deadline requires. Concretely —
`F[0,10] goal_reached` as a PROGRESS property plus `G(docked → G ¬goal_reached)` as a named
safety mode: once `docked` holds the conjunction is dead, but both monitors keep reporting
`INCONCLUSIVE` until the deadline elapses, and the PROGRESS fault fires ten steps late. Our
specs are LLM-generated, so we cannot assume such interactions will never be written.

**A second, unrelated issue found while reading `automata.py`** — flagged as an observation
about our code, not a paper claim, and **not verified against a real Spot** (the docstring on
`LTLMonitor.graph` states Spot is not installed on that host):

- `_compute_status` (line 404) reports `ACCEPTED` whenever the current state is Büchi-accepting.
  **That is not LTL3's ⊤.** `G(a)` after reading `a` sits in an accepting state, yet a later
  `¬a` refutes it — the prefix is not a good prefix. The docstring already hedges ("the property
  holds over the finite prefix observed so far"), but the paper must say so precisely or a
  reviewer will call `ACCEPTED` a mislabelled ⊤. If we want the real ⊤ verdict, the test is an
  *accepting sink* (a state whose residual language is universal), and by Result A
  `all_accepted()` over accepting sinks is then exactly the LTL3 ⊤ of the conjunction — a clean,
  citable statement.
- `_find_sink_states` (line 387) recognises a violation sink **syntactically**: non-accepting,
  exactly one outgoing edge, self-loop on `bddtrue`. This is *sound* (such a state truly cannot
  accept) but potentially *incomplete*: a dead region spanning more than one state, or a dead
  state whose self-loop edges were not merged into a single `bddtrue` edge, is missed, and the
  monitor reports `INCONCLUSIVE` forever where it should report `VIOLATED`. Spot's postprocessing
  usually collapses these (simulation-based merging makes all empty-language states equivalent,
  and `merge_edges` ORs parallel edges), but **nothing in our code guarantees it and nothing
  tests it against a real Spot.** The robust test is backward reachability: state `s` is dead iff
  no accepting state is reachable from `s`. Worth replacing — it is a few lines, and it removes a
  silent-miss failure mode from a safety monitor.

### Q3 — Is there an optimisation worth adopting?

**What does *not* transfer: the shared subformula DAG itself.** LoomRV's deduplication works
because sequential-network monitors are *compositional over subformulas* — every subformula is a
first-class node with its own state and update rule, so identical subformulas are literally
identical objects to merge. `spot.translate()` is a whole-formula construction: the automaton
for `G(!collision_risk)` exposes states and BDD edge conditions, not subformula nodes. There is
nothing to hash and nothing to merge. **The paper's central technique is not available to an
automaton-based monitor**, and we should say that plainly rather than gesture at it as future work.

**What *does* transfer, and is already in our code.** Their discrete-time analysis is explicit
that when node evaluation is cheap, the dominant win is **ingesting the trace once and fanning it
out to every property** — they get 3.2× over their own sequential baseline at only 1.31× node
compression, and attribute it to avoiding 10 separate initialisations and parses. That is exactly
what `MultiMonitor.step()` does today: one shared `observation` dict, built once, handed to every
`LTLMonitor`. **This paper is direct empirical support for the observation-sharing half of our
design**, and that is a better use of the citation than the DAG.

**Interaction with our per-state required-AP optimisation: bad fit, and in our favour.**
LoomRV's execution model is **eager, unconditional and state-independent**: every node in the DAG
is evaluated on every timestep in topological order, single pass, and all `n` atomic predicates
`p₁…p_n` are supplied as inputs at every step (Fig. 3). There is no mechanism — and, given the
statically sized arena and the immutable schedule, no easy place to add one — for skipping a
predicate because nothing currently depends on it. Adopting the shared-DAG design would therefore
**cost us `get_required_aps()`**, our most valuable optimisation precisely because some APs are
evaluated by an LLM on a slow path. The two systems live in opposite cost regimes: LoomRV assumes
AP valuations are free inputs and that node evaluation and memory traffic dominate; `skill_monitor`
assumes AP evaluation dominates everything else by orders of magnitude. **Say this in the
related-work paragraph — it converts "we did not do the clever thing" into "the clever thing
optimises the wrong term for us."**

Note that the pruning is *not* what puts us at risk in Q2. At a product state the required APs
would be the union of what all components need at that joint state — the same set
`MultiMonitor.get_required_aps()` computes. The pruning is orthogonal to the composition question.
Two smaller cautions, both about our code rather than the paper:

- A `VIOLATED` monitor returns `set()` and drops out of the union (line 335). Sound for its own
  verdict, and harmless for the conjunction (already `⊥`), but the set of evaluated APs shrinks
  after a fault — worth a sentence so nobody reads a post-fault trace as complete.
- `_observation_to_bdd` (line 367) does `observation.get(name, False)`: **any AP not supplied
  silently becomes False.** For `G(!collision_risk)` that default reads as "safe" — a fail-open
  default. The more aggressively we prune AP evaluation, and the more often the LLM slow path
  fails to return in time, the more this matters. Consider raising, or carrying an explicit
  unknown value, rather than defaulting.

**Three things genuinely worth borrowing:**
1. **The Multi-vs-AND ablation as an experiment template.** Running `n` monitors against one
   conjoined formula and reporting *both* cost and verdict quality is a small experiment that
   pre-empts the obvious reviewer question. Their result gives the expected shape of the cost
   answer; ours would add the attribution answer they do not measure.
2. **Their "node compression" metric, translated.** Our analogue is AP-level: how much smaller
   `MultiMonitor.get_required_aps()` is than the full AP set, averaged over a run, and how many
   LLM-evaluated AP calls that saves. That is a reportable ICRA number, and it is the metric
   their framework structurally cannot produce.
3. **The S3 product-emptiness certificate** (our proposal, Q2) — offline product, online parallel
   monitors.

### Q4 — The sentence

Primary, for the design-justification paragraph:

> We instantiate one deterministic Büchi monitor per formula rather than a single monitor for
> their conjunction, so that each named failure mode retains its own verdict, its own automaton
> state and its own fault category; recent multi-property monitoring work likewise treats one
> output per property as a first-class requirement, and reports that folding a property set into
> a single conjoined formula is at best cost-neutral and measurably slower once per-node
> evaluation is non-trivial, while yielding a single undifferentiated verdict [multiproperty2026].

Shorter, if space is tight:

> Following recent multi-property monitoring practice [multiproperty2026], we keep one monitor
> and one verdict per formula rather than conjoining the specification into a single automaton,
> preserving per-failure-mode attribution at a state cost linear rather than multiplicative in
> the number of properties.

If the S3 check gets implemented, this is the stronger version and worth the extra clause:

> We monitor each formula with its own automaton rather than their product; because independent
> three-valued monitoring is sound but not anticipation-complete for a conjunction, we discharge
> the difference once at specification-load time by checking the product for states that are
> empty while all component projections remain live, keeping per-property attribution online at
> no loss of detection [multiproperty2026, bauer2011runtime].

*Do not* cite this paper for the claim that independent monitoring is semantically equivalent to
joint monitoring. It does not say that, and in our setting it is false (Q2).

---

## 7. Check yourself

**1. Why can this paper not answer whether monitoring `φ₁` and `φ₂` separately is equivalent to
monitoring `φ₁ ∧ φ₂`?**
Because it monitors *past-time* LTL/MTL with a definite Boolean verdict at every timestep. Under
those semantics `output(φ₁) ∧ output(φ₂) = output(φ₁∧φ₂)` holds pointwise and trivially, so the
question never arises. Composition can only fail in a future-time setting where a finite prefix
leaves the verdict undetermined — exactly the three-valued LTL3 setting `MonitorStatus` implements.

**2. State the soundness and completeness of `any_violated()` and `all_accepted()` with respect to
the conjunction, and name the counterexample class.**
`all_accepted()` (read as ⊤) is **sound and complete**: `∀w` distributes over `∧`. `any_violated()`
is **sound but not complete**: if some component is `⊥` the conjunction is `⊥`, but the conjunction
can be `⊥` while every component is `?`. The counterexample class is *interacting formulas over
shared APs* — e.g. `F g` with `G(h → G ¬g)` after `h`, where both components stay `?` forever while
the conjunction is dead. It also bites when **all** formulas are safety (`G(a → X b)` with
`G(a → X ¬b)` after `a`), so "we only monitor safety properties" is not a defence.

**3. What is LoomRV's "Multi vs. AND" result, and what does it license us to claim?**
LoomRV Multi (shared DAG, one root per property) against LoomRV-AND (all 30 properties conjoined
into one formula): a tie in discrete time (0.80 vs 0.80 s JSON), a win for Multi in dense time
(3.77 vs 4.05 s JSON; 3.45 vs 3.72 s binary), traced to 107 shared-DAG nodes against 136 for the
conjunction's extra 29 `∧` nodes. It licenses: *the monolithic-conjunction strategy buys no speed
and loses per-property attribution.* It does **not** license any claim about semantic equivalence,
about the state-space size of a Büchi product, or about robotics workloads.

**4. Why is LoomRV's shared-DAG technique the wrong optimisation for `skill_monitor` — one
sentence for each of the two reasons?**
(i) *It is unavailable*: subformula deduplication needs a compositional per-subformula monitor
construction, and `spot.translate()` produces a whole-formula automaton with no subformula nodes
to share. (ii) *It optimises the wrong term*: LoomRV evaluates its entire DAG and consumes all `n`
predicates unconditionally every timestep, whereas our cost is dominated by LLM-evaluated APs,
which `get_required_aps()` prunes per automaton state — an optimisation that a shared-DAG,
statically scheduled, statically sized-arena design has no place to accommodate.

---

## Cross-references in this repo

- `papers/reelay/` — Reelay (arXiv:2604.22384), this paper's **baseline** and its ref. [4]; same second author.
- `papers/ltl3-bauer/` — the LTL3 semantics all of §6 Q2 is stated in; `MonitorStatus` *is* this.
- `papers/spot/` — the backend that builds every automaton in `core/automata.py`.
- `papers/rtamt/` — the other per-property monitoring toolchain in the reading list.
- The paper's own multi-property pointers are all from **formal verification** rather than runtime
  verification (its refs [20]–[24]): Goldberg et al., DATE 2018; Dureja et al., FMCAD 2019;
  Das et al. (PURSE), DATE 2024; Das et al. (SISCO), ASP-DAC 2025; Roy et al. (MPBMC), VLSID 2026.
  Its refs [25], [26] (Baumeister et al., RV 2020 and CAV 2025) are the common-subexpression-
  elimination line for stream-based monitors. If a reviewer asks for prior art on property
  ordering or clustering, PURSE and SISCO are the names — **we have not read them.**
