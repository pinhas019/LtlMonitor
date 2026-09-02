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
