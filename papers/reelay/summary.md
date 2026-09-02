# Reelay: Online Temporal Logic Monitoring Framework

**arXiv:2604.22384v1 [cs.LO], 24 April 2026** · single author: **Dogan Ulus**
(no co-authors; the `% VERIFY` uncertainty on this entry is resolved — see `bibtex.md`)

Read for: the **tool comparison table** in the determinism/replay companion paper.
Priority: lower than RTAMT and ROSMonitoring.

---

## 1. In one paragraph

Reelay is a header-only C++17 library (plus a pybind11 Python wrapper) that compiles a
temporal-logic specification into a **sequential network** — a synchronous dataflow
computation graph — and then advances that graph by one update per incoming message. Its
selling point is *unification*: one specification language and one execution engine
covering PastLTL, PastMTL, PastSTL and their robustness (`Ro`) and first-order (`FO`)
extensions, evaluated over either a **discrete-time** or a **dense-time** behaviour model
without changing the specification text. Input is a stream of key/value data messages
(newline-delimited JSON in all the paper's examples; CSV and length-delimited binary are
named as alternatives), and Reelay additionally accepts **delta-encoded** messages that
carry only the fields that changed. The paper is a tool/framework paper: it restates the
formal foundations by reference to the author's sequential-networks paper, walks a worked
Door-Open-Warning case study through both the C++ and Python APIs, and reports per-message
processing times against RTAMT and DejaVu on the Timescales and DejaVu benchmark suites.
It is **strictly past-time only** — a deliberate choice, justified as guaranteeing
"strictly causal analysis" and immediate feedback.

---

## 2. Key concepts

**Temporal behaviour.** A sequence of data messages ordered by timestamp, required to
satisfy **strict monotonicity** (timestamps strictly increase between successive
messages). This is the only stated well-formedness condition on input.

**Sequential network (the unifying abstraction).** A specification is *not* interpreted at
runtime. It is recursively decomposed into subexpressions and compiled into a synchronous
computation graph, one node per logical operator, with common-subexpression elimination
merging identical subformulas so each is evaluated once per time step. This graph *is* the
runtime engine — "not merely a structural representation of the specification, but an
optimized, high-throughput execution engine."

**Product algebras over per-domain algebraic data structures.** The second half of the
unification. Each semantics gets its own algebra — LTL operators over the Boolean domain,
timed MTL operators over **interval-set representations** of the time domain, robustness
over **min-max algebra** on numeric fields, first-order quantification over **BDDs**
(implemented with CUDD) — and heterogeneous semantics are combined by composing these
domains through product algebras inside a single runtime. The graph's *shape* is fixed by
the formula; the *algebra* its nodes compute in is what varies by logic.

**Discrete-time vs dense-time model.** Discrete: timestamps are **implicit and determined
by position in the sequence**; timing constraints `[a:b]` count step indices, not physical
time. Dense: every message carries an explicit timestamp (default top-level `time` field,
configurable); intervals between messages are arbitrary and non-uniform. Figures 2 and 3
show a dense behaviour beside "its equivalent discrete-time representation".

**Delta-encoded behaviour.** Messages transmit only fields that changed since the previous
step. Message data is treated as **persistent**: an omitted key retains its last known
value until explicitly updated or set to `null`. An empty message `{}` denotes the passage
of one discrete time unit with no data change. Motivated by bandwidth-constrained links.

**Reference variables and quantifiers.** `*var` binds a message field value symbolically;
`exists[v]. RYEXPR` / `forall[v]. RYEXPR` quantify over a **categorical domain discovered
incrementally as data arrives**, i.e. unbounded — contrasted with MonPoly's finite
domains. Restricted to string (categorical) variables, and unavailable under robustness
semantics.

**Compile-time message-format specialization.** C++ template specialization lets the
compiler statically bind field access to a concrete data structure (including user-defined
structs), so input handling is resolved at compile time rather than by runtime dispatch.

---

## 3. Method / architecture

1. **Specification** in the Reelay expression format ("RYE"). Atomic expressions use a
   curly-bracket syntax grouping constraints over message fields:
   `{p1: true, nd > 9.0, enm1: "B"}` — shorthand for the conjunction of those field
   constraints at one time point. Custom Boolean-valued predicates over the message are
   registered and invoked as `${func1}`, in both C++ and Python.
2. **Boolean operators**: `not`/`!`, `and`/`&&`, `or`/`||`, `implies`/`->`.
   **Past temporal operators**: `pre`/`Y` (previously — noted as *uniquely meaningful in
   discrete time*, since it refers to the specific previous message), `once`/`P`,
   `always`/`H` (historically), `since`/`S`. Timed variants take `[a:b]` bounds, e.g.
   `H[0:5]{open}`. Binary temporal operators are left-associative; unary operators bind
   tightest, then `and`, then `or`, then binary temporal.
3. **Compilation** into the sequential network, with CSE.
4. **Monitor instantiation** via `options` + `make_monitor`. The C++ options object fixes
   the time representation, data types and output behaviour, e.g.
   `reelay::discrete_timed<intmax_t>::monitor<reelay::json, reelay::json>::options()
   .disable_condensing()`. Python mirrors it:
   `reelay.discrete_timed_monitor(s, condense=False)`.
5. **Execution**: `m.update(msg)` advances the graph by one message and returns a result
   object; `result["value"]` holds the truth value, `m.now()` the current monitor time.
   The canonical loop reads newline-delimited JSON, parses, updates, and reports on a
   `false` verdict — valid because the case-study properties are safety properties
   expected to hold globally.

**Verdict domain.** Boolean (`true`/`false`) under standard semantics, or a real robustness
value under `Ro*` semantics. **No three-valued or inconclusive verdict appears anywhere in
the paper** — with past-only operators every formula has a definite value at every step, so
LTL3's "unknown" has no role.

**Deployment surfaces** benchmarked in §6: `ryjson` (C++ core + simdjson), `ryjson-py`
(Python bindings + stdlib `json`), `rybinx` (C++ over binary serializations of native
structs).

**Case study (§5).** Door Open Warning for "an autonomous robotic home assistant": a `dow`
module with `open`/`suppr` inputs and a `warn` output, sampled at fixed one-minute
intervals. Two informal requirements are hand-formalized into four RYE formulas, e.g.
`(H[0:5]{open} and not {suppr}) -> {warn}` and `{warn} -> not(pre({open} since {warn}))`.
The paper is explicit that the informal→formal step is a *human design activity*: such
dependencies "are often implicit in informal specifications, they must be stated explicitly
in automated verification." No tooling automates it. The trace shown is a hand-written
9-message synthetic log.

---

## 4. Evaluation

Setup: Timescales and DejaVu benchmark suites; every log ≈ **1,000,000 messages**; metric
is **average per-message processing time** = total log-processing time ÷ messages;
hardware **3.80 GHz Intel Xeon W-2235, 32 GB, Linux**. No variance, repetition counts, or
confidence intervals are reported.

**Base PastMTL (Table 2).** `ryjson` 182–480 ns/msg; `rybinx` 75–206 ns/msg (a further
50–60 % reduction, at the cost of hard-coded structs requiring "schema-specific tailoring
at compile time"); `ryjson-py` 2182–3717 ns/msg. Key finding: **latency stays nearly
constant as the timing bound scales 10 → 100 → 1000**, attributed to symbolic
representation of time intervals.

**Robustness / PastSTL vs RTAMT (Table 3).** `ryjson` 408–1427 ns; `ryjson-py`
2516–5177 ns; `rtamt-app` (an author-written Python app over the rtamt interface,
mirroring `ryjson-py`) 15,183–164,822 ns, and **dnf** (timeout) on all three
`RoRespondBQR` properties. Explanation given: RTAMT's timed monitoring "relies on the
explicit enumeration of time intervals", so it is sensitive to bound magnitude; Reelay is
not. Also noted: Reelay shows no slowdown under robustness relative to Boolean semantics.

**First-order vs DejaVu (Table 4).** Untimed PastFOLTL: Reelay faster on all six (e.g.
LocksDeadlocks 3975 ns vs 36,617 ns), attributed to C++/CUDD vs Scala/JavaBDD rather than
to algorithmic difference — both use the same BDD technique. Timed PastFOMTL: DejaVu
degrades sharply and **dnf** at bound 70 on both benchmarks; Reelay stays in the
5.4–6.5 µs range.

Caveat for the table: all competitor numbers were produced by this paper's author, with a
wrapper application he wrote, on traces he converted into his own formats. Indicative, not
an independent head-to-head.

---

## 5. Limitations

- **Past-time only, by design.** No future operators at all. Any future-time obligation
  must be re-expressed in past form or abandoned.
- **No three-valued verdict.** Boolean or robustness value only; no `unknown`, no notion
  of a verdict becoming permanently settled.
- **First-order support excludes robustness semantics** (stated explicitly), and reference
  variables work **only for categorical/string variables**.
- **Robotics is aspiration, not result.** "Autonomous robotic platforms" appears in the
  abstract and the case study is framed as a home assistant, but there is no robot, no
  ROS, no hardware, no real trace, no latency-under-load measurement. Future work names
  "decentralized monitoring techniques, specifically targeting the pub/sub architectures
  prevalent in modern IoT and robotics applications" — i.e. explicitly not done yet.
- **Multi-property monitoring is future work**, so one monitor = one formula today.
- **`rybinx`'s speed is bought with rigidity**: native structs are hard-coded and require
  compile-time, schema-specific tailoring.
- **Undocumented API surface.** `disable_condensing()` / `condense=False` appear in both
  code listings with no definition anywhere in the text. Given the name, condensing
  plausibly suppresses repeated identical outputs; if so, its default state directly
  affects how many outputs a trace produces. **Not verified** — that requires reading the
  library. It matters here specifically (see §6.3).
- No memory-footprint numbers, no worst-case latency (averages only), no graph-construction
  or cold-start cost.

---

## 6. For `skill_monitor`

### 6.1 Scope

| dimension | Reelay | skill_monitor |
|---|---|---|
| logics | PastLTL, PastMTL, PastSTL + `Ro` (robustness) and `FO` (first-order) variants — 8 fragments in the Fig. 1 hierarchy | LTL over Boolean APs |
| temporal direction | **past only**, strictly causal | future-time LTL via Büchi automata |
| time model | **both** discrete and dense; dense split further into sample-based vs state-based (Reelay does state-based and explicitly marks sample-based dense MTL as *not supported*) | discrete only |
| verdict | Boolean, or real-valued robustness | three-valued (LTL3) |
| engine | sequential network / synchronous computation graph, product algebras, BDDs for FO | deterministic complete Büchi automaton from Spot |
| atoms | field constraints over JSON-ish messages: Boolean, numeric comparison, string equality, registered custom predicates | thresholded sensor values → Boolean APs |

**The "fragmentation" being addressed** is *tool and formalism* fragmentation, not
specification-language or grounding fragmentation. The argument in §1 and Table 1: DejaVu
gives first-order but only discrete time; MonPoly gives dense time but sample-based
evaluation coupled to the sampling scheme (which "may mask violations occurring between
sampling instants") plus only finite quantification domains; RTAMT gives dense-time STL
with robustness but is centred on numeric data; AMT2 covers some dense MTL/STL. Each has
its own specification language and input syntax. Reelay's unification claim: **one
expression language, one computational model (sequential networks), one set of composable
algebras, spanning all eight fragments and both time models** — so the same spec text runs
against a live high-frequency stream or a recorded log without editing.

Note the shape of that claim carefully, because it is *adjacent to* the companion paper's
but not the same. Reelay claims a **specification** is portable across time models and data
formats. The companion paper claims a **verdict** is invariant across execution rates and
machines. Reelay never makes the second claim.

### 6.2 Tool-table row

| cell | verdict | evidence |
|---|---|---|
| **spec synthesis from natural language** | **No** | §5.1–5.2 do the informal→formal translation entirely by hand and treat it as a human design responsibility. No LLM, no NL front-end, no synthesis of any kind anywhere in the paper. |
| **schema grounding** | **Partial — qualified** | Specs bind to message data by *field name* (`{open}`, `nd > 9.0`) and to registered host functions (`${func1}`); `rybinx` binds to concrete C++ structs via template specialization, described as "schema-specific tailoring at compile time"; the dense-time timestamp field name is configurable. But there is **no schema artifact, no schema declaration, no validation of a spec against a declared schema, and no spec type checking described**. A misspelled field name is not discussed. Safe phrasing: "field-name binding + optional compile-time struct typing; no schema document or spec/schema validation." |
| **embodiment portability** | **Claimed, not substantiated** | Claim: header-only C++17, small footprint, "predictable, low-latency execution profile", suitable "from resource-constrained embedded systems to autonomous robotic platforms"; case study framed as a home-assistant robot. Evidence: none. All experiments run on a desktop Xeon over 1M-message log files. No robot, no ROS, no embedded target, no cross-platform result. Pub/sub robotics integration is **future work**. |
| **deterministic replay** | **Not addressed — flag as absent** | See 6.3. |

Suggested one-line entry: *past-time LTL/MTL/STL (+robustness, +first-order), discrete and
dense time, sequential-network engine, C++/Python; no NL front-end, field-name grounding
only, robotics claimed but unevaluated, replay determinism not discussed.*

### 6.3 Determinism, reproducibility, replay

**Direct answer: the paper says nothing about determinism, reproducibility, or replaying a
recorded trace to the same verdict. The words do not appear. There is no replay
experiment, no rate-variation experiment, no identical-verdict claim, and no tick-count
accounting.** That silence is reportable, and it is the *expected* silence — this is a
performance-and-expressiveness tool paper that measures nanoseconds per message, not
verdict stability.

Four things in it are nonetheless load-bearing and worth citing precisely rather than
dismissing:

1. **Reelay's own design decisions quietly presuppose what the companion paper makes
   explicit.** The discrete-time model defines timestamps as *implicit and determined by
   position in the sequence*, with timing constraints interpreted over step indices rather
   than physical time. That is exactly the external-clock / one-step-per-tick discipline,
   arrived at as an input-format convention rather than as a determinism guarantee. Reelay
   never argues that this decouples the verdict from wall-clock rate — but it is the reason
   it would. A *supporting* citation, not a competing claim.
2. **The strict-monotonicity precondition is the only input contract stated**, and it
   concerns timestamp ordering, not tick counts or drop-freedom. Reelay does not say what
   happens if a message is dropped, duplicated, reordered, or delayed by transport — the
   exact failure modes a 1×/5×/20× replay is designed to expose. A monitor whose
   discrete-time verdict is a function of *message position* is by construction sensitive to
   a dropped message, and the paper does not discuss it.
3. **Figures 2a/2b and 3a/3b assert representational equivalence without proving verdict
   identity.** A delta-encoded behaviour is said to be "equivalent to" the full-state
   behaviour, and a dense behaviour is shown alongside "an equivalent discrete-time
   behaviour". These are precisely the "same data, different encoding — same verdict?"
   questions the companion paper formalizes. Reelay asserts the equivalence at the level of
   behaviours, does not carry it through to verdicts, does not state it as a theorem, and
   does not test it. Cleanest hook available: an unproven equivalence claim in a widely used
   tool, of exactly the kind checked empirically here.
4. **The condensing option is a live confound for tick counting.** Both listings pass
   `disable_condensing()` / `condense=False`, and nothing in the text says what condensing
   does. If it suppresses unchanged outputs, then the *default* configuration produces an
   output count that is a function of the verdict sequence rather than of the message count
   — which would break a naive "identical tick counts" check against Reelay. **Not verified
   from the paper.** If Reelay is to be run as a baseline rather than only cited, read
   `include/reelay/` for `condense`/`condensing` first; if only the table row is needed, the
   safe statement is "output condensing is configurable and its semantics are not documented
   in the paper."

**What it does not give you.** No cross-machine reproducibility claim. No statement that
verdicts are independent of processing speed. No log/replay tooling beyond "iterate over a
newline-delimited file". No handling of the transport layer at all — Reelay is a library
that consumes messages; who delivers them, at what rate, and whether any are lost is
entirely outside its scope. Which is exactly the gap the companion paper occupies. Reelay
is a good citation for *"even the framework that explicitly set out to unify time models
and data encodings never states that the verdict is a function of the observed data
alone."*

**Fit as a runnable baseline: poor.** Past-only operators and a Boolean verdict domain mean
it cannot express or reproduce three-valued future-time LTL3 monitors. Cite it in the
table; do not plan to run skill_monitor specs on it.

---

## 7. Check yourself

**Q1. Reelay supports both discrete and dense time. Does that mean it can monitor a
future-time LTL formula in either model?**
No. The time-model axis and the temporal-direction axis are independent, and Reelay fixes
the second. *All* supported formalisms are past fragments — PastLTL, PastMTL, PastSTL and
their `Ro`/`FO` extensions — chosen so analysis is strictly causal and every verdict is
available immediately at the current step. Dense time buys non-uniform sampling and
state-based evaluation; it does not buy `until` or `eventually`.

**Q2. skill_monitor emits a three-valued LTL3 verdict. What is the closest thing Reelay
emits, and why does the difference exist?**
`result["value"]`, a plain Boolean (or a real number under robustness semantics). There is
no inconclusive verdict because none is needed: LTL3's "unknown" exists to express that a
*future* obligation is not yet settled on a finite prefix, and Reelay has no future
obligations. Every past formula is definitely true or false at every step. A tool-table
cell comparing "three-valued verdict" should read "N/A by design", not "missing feature".

**Q3. Reelay says a delta-encoded trace is "equivalent" to the full-state trace it came
from. Is that the same as the companion paper's replay-determinism claim?**
No, and the gap is the point. Reelay's equivalence is about *encodings of a behaviour*: an
omitted key is defined to retain its last value, so the two message sequences denote the
same behaviour. The companion claim is about *verdicts*: the output must be a function of
the observed data alone, independent of machine, transport and replay rate. Reelay's
assertion is a necessary ingredient of that, stated informally, never proved, never tested
— and in particular it says nothing about a transport dropping or reordering one of those
delta messages, which under Reelay's position-implies-timestamp discrete model would
silently shift every subsequent step index.

**Q4. Can Reelay be cited as evidence that determinism/replay is an underserved problem?**
Yes, carefully — this is the paper's strongest use here. Frame it as: Reelay is the
framework whose entire stated purpose is to unify time models, logical formalisms and data
encodings under one computational model, and even it evaluates only per-message throughput
(ns/message over 1M-message logs on a desktop Xeon) and never asks whether the same
recorded data yields the same verdict under different execution conditions. Do not overstate
it as a criticism: it is a library-boundary question, not a bug. State it as scope and let
the absence do the work. Do **not** claim Reelay is non-deterministic — nothing in the paper
supports that, and given a fixed message sequence it very likely is deterministic.

---

## Provenance notes

- Every number, quoted phrase and API signature above comes from arXiv:2604.22384v1,
  retrieved in full text. Table values are transcribed from Tables 2–4.
- The author's **affiliation is not present** in the retrieved preprint text (it uses the
  Springer "Noname manuscript No." template with the address block unfilled). Public
  sources list Doğan Ulus at Boğaziçi University — **not verified from the paper**.
- The semantics of `condense`, and whether Reelay's dense-time and discrete-time
  evaluations of the same behaviour provably agree, are **not verified** — both would
  require reading the source at https://github.com/doganulus/reelay.
