# RA-L draft

`ral.tex` + `refs.bib`. Build:

```bash
pdflatex ral && bibtex ral && pdflatex ral && pdflatex ral
```

Verified on TeX Live 2023 (`texlive-latex-base texlive-latex-recommended
texlive-publishers texlive-science texlive-fonts-recommended`): 8 pages, no
undefined references, no undefined citations, no overfull box above 15 pt.

---

## The claim

**Breaking skill execution into phases improves monitoring.** That is the
thesis and the paper is built on it. Portability across embodiments and
natural-language authorship are presented as *consequences* of the same
decomposition (§I-E, H4, H5), not as contributions.

The argument the draft makes, in one line: the formula that states what a
skill is *for* is a guarantee (co-safety) property, guarantee properties have
no bad prefix, so **a flat temporal specification can never report that the
skill failed** — a wedged robot leaves it inconclusive forever. Phases with
deadlines and progress budgets convert that unmonitorable obligation into a
ladder of monitorable safety properties. LTL is kept alongside, not replaced,
because the cross-cutting invariants (`G(!collision_risk)`, `G(upright)`) need
a *permanent* verdict a stage machine cannot promise. Hence LTL **with**
phases: neither layer supplies both bounded obligations and a monotone
verdict.

Two things in the repo made this argument available and should not be lost:

- `skill_monitor/specs/formulas_g1.json` contains **both encodings of the
  same mission** — the nested-F goal formula *and* the three-phase ladder
  over the same propositions. That is Figure 1 and the running example.
- The wedged-humanoid case is real: the planner published `following` while
  the robot was physically stuck. It is the concrete instance of the
  self-report trap, and it appears in §I, §II-D, §III-C and §III-H.

---

## What is drafted

| section | state |
|---|---|
| Abstract | drafted; one `\TODO` for the headline number |
| I. Introduction | **drafted** |
| II. Background | **drafted** — A: how LTL works · B: which finite-prefix semantics (LTL₃) · C: declaration methods + Table I, with the extended behaviour-tree answer · D: **why author from natural language** |
| III. Related Work | **drafted** — six subsections; III-C (stage structure) and III-D (the AHA/Guardian/DoReMi/CaM cluster) are the load-bearing ones |
| IV. Why Phases | **drafted** |
| V. Trace Semantics | skeleton |
| VI. How the Monitor Works | **drafted** — artifacts, the tick end to end, both layers on one assignment, **fault → category → intervention**, embodiment separation |
| VII. Evaluation | **metric drafted and defended** (§VII-B); H1–H7 protocols fixed, no numbers |
| VIII. Threats | skeleton — seven enumerated, all real |
| IX. Conclusion | skeleton with intended shape |

18 `\TODO{}` markers. `grep -c '\\TODO{' ral.tex` is the submission gate.

---

## Semantics: LTL3, decided in §II-B

The draft now says **LTL₃** explicitly rather than "LTL", and §II-B is where
that choice is made and defended. The short version, because the reasoning is
easy to get backwards:

- **LTL₃** (Bauer et al.) evaluates a finite prefix to ⊤/⊥/?, where ⊤ means
  *every* infinite continuation satisfies φ and ⊥ means *none* does. It still
  quantifies over infinite continuations, so it is the semantics of a finite
  **observation of an open-ended run** — not of a trace believed complete.
  Its three verdicts are exactly `MonitorStatus.{ACCEPTED, VIOLATED,
  INCONCLUSIVE}` in `skill_monitor/core/automata.py`. We already implement it.
- **LTLf** (De Giacomo & Vardi) reinterprets the logic over finite traces,
  where the trace *is* the word. There `F finished` is simply **false** if it
  never holds. This is what "I assume the trace is finite" actually names.
- **RV-LTL** (Bauer et al. 2010) refines LTL₃'s single `?` into four values,
  adding presumably-true / presumably-false.

We monitor under LTL₃ online and read the episode fold as finite-trace. The
load-bearing observation, now a contribution bullet: **the phase structure
manufactures the finite trace a finite-trace semantics presupposes** — LTLf
gives a definitive verdict at the last position but cannot say *when the
trace ends*, and what closes the episode is a phase deadline. So adopting
LTLf relocates the need for phases rather than removing it, and the phase
claim does not depend on the semantics choice.

Why not RV-LTL, which looks like it supplies the missing detection signal:
presumably-false is not monotone (nothing to latch), it is **constant for
most of a successful run** (`F finished` is presumably-false on every prefix
of a *successful* episode until the final tick, so it does not distinguish
stalled from progressing), and it still never says when to give up.

**One terminology fix applied throughout.** Under the standard definition
(some extension yields a definitive verdict) `F p` **is** monitorable, and the
monitorable class is strictly larger than safety ∪ co-safety. What the goal
formula lacks is a **bad prefix**: it is monitorable *for satisfaction* and
not *for violation*. The draft now says that everywhere, and the title changed
from "Monitorable" to "Detectable" for the same reason. An RV reviewer would
have caught the loose version.

This also retroactively justifies a decision already in `docs/clocking.md`
("do not add a member to `MonitorStatus`"): that enum is the LTL₃ verdict
domain, fixed by the semantics. RV-LTL's extra values refine `?` along the
*trace* axis and say nothing about whether the observation was available, so
they are not the fourth value DECIDED/UNDECIDED needs. §IV-F says this.

---

## Page budget — 11 pages, accepted; the owner trims

| | pages |
|---|---|
| §I–§IV + bibliography | 7 |
| + §VI (mechanism) and §VII (metric) written out | **11** |

RA-L allows 8 at most.

> **Owner's decision (standing): keep the draft at 11 pages. Trimming and
> cutting are the owner's to do, not a collaborator's.**

So: **do not trim this paper for length.** Not as a tidy-up, not as a
"while I was here", not on your own judgement about which argument is
weakest. An earlier measured trim pass moved the page count by zero, so
wording is not where the pages are — only scope is, and scope is the owner's
call. If length comes up, report the count and stop.

If the owner later asks for the cut, this is the order I would propose, and it
is a proposal only:

1. **Portability and authorship as contributions** (§I-E, H6, H7, §VI-E's last
   paragraph, the NL→LTL citation cluster) — about a page, already demoted to
   consequences, and a coherent second paper.
2. **§VII-B's metric defence** compressed to one paragraph plus the Lorden
   citation; the four-part version belongs in a journal variant.
3. **§VI's tick walkthrough** reduced to a figure with a caption.

Not candidates at any length: §II-B (semantics), §II-C's behaviour-tree
answer, §II-D (proposer/checker), §IV-A (the detectability gap), §IV-B (phases
as bounded obligations), §IV-G (bounding the flat formula), §III-C/D (the
competitor analysis), and §VII-B's primary metric definition. Those are the
paper.

A venue with room for the whole argument (T-RO, IJRR) remains open and, at 11
pages of genuine content, worth weighing rather than treating RA-L as fixed.

---

## The evaluation metric, and its defence (§VII-B)

**Primary metric: median and worst-case detection delay, with detection rate,
at the tightest (k, m) whose false-alarm rate on held-out nominal episodes is
≤ α₀.**

The defence is that this is **not a metric we invented**. A phase deadline plus
a progress budget is a stopping rule, so the monitor is a *sequential change
detector*, and that problem class has evaluated such rules since Page's CUSUM
by a pair of run lengths — to false alarm, and to detection. Lorden made the
pairing precise (minimise worst-case expected detection delay subject to a
false-alarm constraint) and CUSUM is minimax optimal under it. We adopt the
criterion rather than coining one.

Two adaptations stated in the paper because the correspondence is close but not
exact: episodes are finite, so the analogue of run-length-to-false-alarm is a
per-episode false-alarm **probability**, measured directly rather than
approximated as a reciprocal of an expected time; and our detector is not
likelihood-ratio-derived, so we claim no optimality — only that this is the
right criterion.

Three further reasons it holds up:

- **Neither half is gameable alone.** Detection rate is maximised by k=m=1,
  which detects everything and aborts every healthy run. Any paper reporting
  detection without a false-alarm budget has reported nothing.
- **H2's bound sweep *is* the operating characteristic**, not a side
  experiment. Sweeping (k, m) traces delay against false-alarm rate per class;
  H1 reports one point on it chosen by a stated budget. This is also the answer
  to the sharpest objection available — "your bounds are tuned to your failure
  set" — because the curve is reported, not a point. It also turns a concession
  into a contribution: Code-as-Monitor explicitly states threshold-variation
  effects are unexplored.
- **It states the baseline's failure correctly, not unfairly.** The flat
  encoding's curve on progress failures is *empty*: ρ = 0 at every budget,
  because no parameter setting gives a guarantee property a bad prefix. That is
  a property of the encoding, not of tuning.

**Three statistical commitments, each guarding a specific error:**

1. Delay is **right-censored**. Report detection rate separately and median
   delay over detected episodes — never a mean that silently drops
   non-detections, which flatters whichever arm detects less often but faster.
2. **Stratify by failure class.** A topple trips an invariant on tick 1 under
   both encodings; pooling it with a stall dilutes the effect under test.
3. **Gate on coverage.** Exclude and count episodes whose undecided fraction
   exceeds a stated bound, or a sensor dropout gets reported as a result.

**Why not AUROC** (which much of the neighbouring cluster reports): it
summarises a frame-wise classification and is threshold-free, whereas this is a
stopping problem where *when* is the whole question. Perfect AUROC firing on the
last tick is worthless and AUROC cannot distinguish it from firing at onset.

**Secondary metric: execution not wasted** (ticks from onset to episode end).
This is the utility measure that does not require recovery to succeed — which
matters because an unreachable goal admits no intervention, so a
success-rate-only evaluation would score a *perfect* monitor at zero.

**Tertiary: task success rate, four arms** — (A) no monitor, (B) flat, (C)
phase, (D) oracle fired at ground-truth onset — with the intervention policy and
recovery repertoire held fixed. Claim is C > B; D bounds what any monitor could
achieve with this repertoire, so the result reports a *fraction of achievable
gain* rather than an unanchored percentage. Precedent: DoReMi's oracle arm.
Stated plainly in the paper: success rate is joint over (monitor, intervention
policy, recovery repertoire), and only fixing the latter two makes the
comparison about the first.

---

## Why LTL and not behaviour trees (§II-C)

The old draft rested on "a BT is the controller", which has a hole — you can
write a monitoring-only BT, and people do (Ahmad et al., CASE 2025, verify BT
conditions and add missing preconditions at runtime). Three stronger reasons now
lead, in descending order:

1. **A BT does not denote a language of traces.** Its meaning is its
   tick-by-tick traversal, so there is no object of which to ask whether it has
   a bad prefix. The paper's central argument cannot be *stated* in BT
   formalism, let alone checked. Not a claim about expressive power — about what
   kind of thing the artifact is.
2. **No permanence.** A condition node is recomputed each tick and returns
   success/failure/running; nothing latches. Hand-rolled latching makes
   monotonicity a property of bookkeeping rather than of the construction, with
   nothing to appeal to when it is wrong.
3. **A generated tree is a program.** Validating one is validating a program;
   validating a generated formula is a compile plus a key-existence check. This
   is why §II-C and §II-D are not separable.

The practical reason then stands alongside: in robotics a BT is usually *the*
controller, and the `following`-while-wedged case shows that blindness is
structural.

---

## Why from natural language (§II-D)

The argument is **proposer / checker**, not "the model is reliable":

- A spec comes from one of three places. **Hand-authored** is the status quo and
  the reason platforms have monitors for one or two skills, not thirty — cost
  scales skills × embodiments and is paid by whoever can write temporal logic.
  **Learned** works (93% phase accuracy from 52 labelled episodes; 49K
  synthesised pairs) at the cost of annotating per skill and binding the monitor
  to the embodiment via training data. **Derived from a description** uses the
  one artifact that already exists.
- Ambiguity is answered by two mechanical gates, neither needing a human or a
  robot: every formula must compile under Spot, and every sensor key named by a
  grounding rule must be declared in the schema. Failure → rejected and
  repaired. **Ambiguity surfaces as a rejected proposal, not as a monitor that
  is quietly wrong.**
- **The phase structure is what makes the gates strong**, and this is where the
  two streams meet: a ladder over a declared vocabulary is far more constrained
  than free-form LTL — a sequence of stages, a small fixed set of guard kinds,
  Boolean expressions over declared keys, two integers. The same decomposition
  that makes failures refutable makes the specification checkable. One
  structure, both streams.
- Residual, stated: the gates cannot catch whether a spec that compiles says
  what the author *meant*. Mitigation is the round trip — the generator emits
  prose back from the spec, so the human reviews English, not LTL. And a wrong
  *threshold* passes both gates and every review, which is why §VII treats the
  bounds as an object of measurement.

---

## The objection a reviewer will raise first

*"Just write a bounded eventually, `F≤k`, and your flat formula is monitorable
too."* This is correct and the draft answers it directly in §III-H, in three
parts: one global bound is one bound (30 ticks for planning vs 120 for
tracking cannot be expressed as a single number); a bounded formula still does
not localise, so the per-stage invariants and progress predicates have nowhere
to live; and bounded operators compile to counter automata that grow with the
bounds, while the ladder is one integer plus a few guard evaluations.

Keep that answer sharp. If it weakens, the paper weakens.

---

## Claim / evidence audit

**Supported today:**

| claim | evidence |
|---|---|
| Flat goal formulas are not monitorable for violation | standard property-class result, cited (`manna1990hierarchy`, `bauer2011runtime`) — this is the one headline claim that needs no experiment |
| The phase machine has five guard kinds and two budgets | `docs/api.md` phase_guards contract; `formulas_g1.json` |
| A breach localises to stage + guard | fault naming `phase:<phase>:<invariant\|timeout\|progress\|precondition>` (`docs/api.md`) |
| A breach grades into an intervention | fault categories → ladder; the TIMEOUT/PROGRESS vs SAFETY table in `docs/packages/P5-supervisor.md` |
| Episode outcome is a function of refutable guards | the terminal table in `docs/api.md` |
| Monitor never reads an adapter descriptor | architectural invariant, `docs/architecture.md` |
| Specs are mechanically validatable | `skill_monitor/core/spec_contract.py` |
| Suite green | 1231 passed, 0 skipped in the test container |

**Not yet measured — every one is a `\TODO`:**

1. **H1, the phase-vs-flat ablation.** The paper's main experiment. Not run.
2. **H2, bound sensitivity.** §III-D concedes that phases move the burden onto
   chosen bounds; without a sweep that concession is unquantified and a
   reviewer will say so. Not run.
3. **H3, cost and coverage.** Never profiled.
4. **H4, two-replay-path verdict equality.** Recorder exists; no episode has
   been through both paths.
5. **H5, generated phase ladders.** The shipped spec is hand-authored.

**Good news on H1, and it is a real change in the critical path.** H1 is an
*encoding-level* ablation: both arms replay the **same** observation stream
and differ only in which specification the monitor loaded. So it needs one
recorded corpus with induced failures, not one robot session per arm — and the
analysis is entirely offline. `replay_node record` / `play --diff` is the
tooling and it exists.

It may even be runnable in simulation first, which would de-risk the whole
paper before touching the G1. **One blocker if you try that:** the progress
debounce counts messages rather than ticks, and in simulation the source
publishes only on status transitions, so the stuck signal *never fires in
sim at all*. Fix that first or the sim arm measures nothing. It is also, as
§IV notes, the cleanest possible illustration of why the trace-semantics
section exists.

**Two facts that must stay in §VII and must not be softened:**

- `formulas_g1.json` is hand-authored — evaluation reference, not generator
  output. Presenting it as generated would falsify H5.
- **Five of its eight propositions read the planner's self-report.** This is
  no longer just an honesty note: it is the trap §III-C names, so H1 **must
  report the self-report cases separately**. They are the cases where the flat
  encoding appears to detect a stall, for the wrong reason — the planner
  happened to admit it. Reporting them pooled would flatter the baseline and
  hide the result.

---

## Citation audit

34 entries. Author lists, titles and venues checked against live sources
while drafting, **except** entries preceded by a `% VERIFY before submission:`
comment in `refs.bib` (mostly DOIs and page ranges for older well-known
papers). BibTeX treats `%` as a literal, not a comment, so those notes sit
*between* entries — do not move them inside one or parsing breaks silently.

Two entries need more than a field check:

- `liu2023grounding` (Lang2LTL) — only the first author confirmed; reads
  `and others`. Get the full list.
- `sundarsingh2025conformalnl2ltl` — substituted for SCP-NL2TL
  (arXiv:2608.05439), whose authors could not be confirmed from this session.
  Same point, verified authors.

Key new citations for the phase claim, all verified:

| ref | why it matters |
|---|---|
| `ajith2026robomonitor` | **closest competitor.** Same premise ("monitoring requires identifying the current execution phase") but *learns* the phase: 93% accuracy, and must suppress spurious phase switching 15.2%→5.0%. Our phase is a declared machine state, so it is exact and cannot switch spuriously. This contrast is the heart of §II-C |
| `sliwowski2025conditionnet` | learned preconditions/effects, anomaly detection by comparing expected vs predicted phase |
| `shi2026dynsteer` | **independent evidence for the thesis** from LLM agents: stage-wise beats whole-trajectory by >85% discriminability. Different domain, no formal guards |
| `wang2026progressbar` | self-reported progress is unreliable and collapses mid-task; "check against independent state, not sole control authority". The general form of our planner-self-report bug |
| `xu2024nl2hltl2plan` | hierarchical LTL — closest *formal* work, but decomposes for planning, and its sub-formulas inherit non-monitorability |
| `colledanchise2021formalizing` | runtime verification around behaviour-tree execution context |
| `manna1990hierarchy` | the safety/liveness/guarantee hierarchy the detectability argument rests on |

**The foundation-model failure-detection cluster** (§III-D), traced from primary
sources, not from other papers' characterisations:

| ref | why it matters |
|---|---|
| `duan2025aha` | AHA, ICLR 2025. Predicts success **for a given sub-task** from keyframes — it *consumes* a decomposition. Its seven synthesised failure modes are all action-centric and include **no progress or timeout class at all**, which is a citable reason the gap has gone unremarked |
| `pacaud2025guardian` | Guardian. Conditioned on **proposed plans or subtasks**; verifies execution from before/after frames. "No progress" is its **best-detected class** — read as support: stage boundaries are what make progress failure visible |
| `liu2023reflect` | REFLECT, CoRL 2023. Post-hoc failure explanation from a hierarchical experience summary. **RoboFail is REFLECT's dataset, not a separate paper** |
| `guo2024doremi` | DoReMi, IROS 2024. **Closest in spirit**: LLM emits per-skill constraints, VLM checks them every 0.2 s. But they are *state* constraints, and the only temporal bound is a **global** task timeout — the single mission-level bound §IV-G argues against |
| `zhou2024codeasmonitor` | Code-as-Monitor. Compiles constraints to code; separates during-execution from on-completion constraints, which **map closely onto our invariant and exit condition**. Also states that **threshold-variation effects remain unexplored** — that is our H2, so bound sensitivity is a contribution, not only a concession |
| `degiacomo1998execution` | the classical ancestor: execution monitoring of high-level robot programs |

**The positioning this forced, and it is a real change.** Stage structure is *not*
what to claim as novel — this cluster has plenty of it, produced as well as
consumed. The defensible gap is narrower and sharper: **none of them attaches a
horizon to a stage.** The obligations are states to maintain, never bounds within
which to make progress, so the property class never changes and the stall stays
unrefutable. §III-F (Position) now says this explicitly, and §IV-A names
per-stage state constraints as a third escape that "catches a great deal, but not
a robot that is stuck while every declared state still holds."

arxiv.org and alphaxiv.org are both blocked from this session's network, so
metadata came via search and the alphaXiv MCP tools rather than abstract
pages. A session with arXiv allowed could clear the VERIFY list quickly.

---

## Figures needed

Figure 1 exists as a `tabular` placeholder (the two encodings side by side)
and should become a real figure: the two encodings **plus an annotated stall
trace** showing the tick at which each reports. That single figure carries the
paper's argument and is worth real effort.

Also still needed, all currently Mermaid in the docs:

| figure | source |
|---|---|
| the tick window (half-open interval, fold, step) | ASCII diagram in `docs/clocking.md` |
| the phase machine (guard order, budgets, fault naming) | `docs/api.md` phase_guards + `P5-supervisor.md` |
| service / tier map | `flowchart LR` in `docs/architecture.md` |
| the two replay paths (H4) | two-path table in `docs/architecture.md` |

---

## Still missing from the repo

`THESIS_PLAN.md` (revision 4) is the plan of record for evaluation and scope,
and it lives in the **other** repo — `~/TRAV-metric-map`, branch
`ltl-skill-monitor`. §VI should be reconciled against it, particularly now
that H1 has changed.
