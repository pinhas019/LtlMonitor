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
| I. Introduction | **drafted** — detectability argument, Figure 1, localise/grade, why LTL too |
| II. Related Work | **drafted** — six subsections; **II-C is the central one** (stage structure in monitoring) |
| III. Why Phases, and Why LTL | **drafted** — the detectability gap, phases as bounded obligations, three-valued propositions, alternatives |
| IV. Trace Semantics | skeleton — now load-bearing, because deadlines are counted in ticks |
| V. System | skeleton — six subsections, phase machine first |
| VI. Evaluation | skeleton — **protocols fixed, numbers not collected** |
| VII. Threats | skeleton — seven enumerated, all real |
| VIII. Conclusion | skeleton with intended shape |

16 `\TODO{}` markers. `grep -c '\\TODO{' ral.tex` is the submission gate.

---

## Page budget — this is now tight

RA-L is **6 pages**, extensible to 8 with overlength charges.

- Abstract + §I–§III + bibliography: **7 pages**
- Plus §IV–§VIII *as skeletons*: **8 pages**

§III grew by a page in the rewrite because it now carries the contribution,
which is the right place for the weight but leaves no room. Trim targets, in
the order I would cut:

1. **§II-E (specification acquisition)** — now explicitly secondary. Two
   sentences and a citation cluster is enough.
2. **§II-F (Position)** — overlaps §I-F. Compress to three sentences.
3. **§I-E (two consequences we did not design for)** — one paragraph; §II and
   H4/H5 cover the detail.
4. **§III-A (the four questions Q1–Q4)** — useful scaffolding, but the Q-labels
   recur throughout and could be inlined.
5. **§III-F (why both layers)** — partially restates §I-D. Merge them.
6. **Figure 1** is a tabular placeholder eating a third of a column; a drawn
   figure would be tighter and better.

Do **not** cut: §III-C (the detectability gap), §III-D (phases as bounded
obligations), the first item of §III-H (bounding the flat formula — see
below), or §II-C (the competitor analysis). Those four are the paper.

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
