# RA-L draft

`ral.tex` + `refs.bib`. Builds clean with the IEEEtran class:

```bash
pdflatex ral && bibtex ral && pdflatex ral && pdflatex ral
```

Verified on TeX Live 2023 (`texlive-latex-base texlive-latex-recommended
texlive-publishers texlive-science texlive-fonts-recommended`): 8 pages, no
undefined references, no undefined citations, no overfull box above 15 pt.

---

## What is drafted and what is not

| section | state |
|---|---|
| Abstract | drafted; one `\TODO` for the headline number |
| I. Introduction | **drafted** |
| II. Related Work | **drafted** — six subsections including a *Position* subsection that states the gap |
| III. Why Linear Temporal Logic | **drafted** — requirements, the monitor construction, finite traces and three values, alternatives considered, what LTL does not give |
| IV. Trace Semantics | skeleton — bullet list of the points that must survive compression from `docs/clocking.md` |
| V. System | skeleton — six planned subsections, each named with its source document |
| VI. Evaluation | skeleton — **the protocol is fixed, the numbers are not collected** |
| VII. Threats to Validity | skeleton — but the six threats are enumerated and are real |
| VIII. Conclusion | skeleton with the intended shape |

14 `\TODO{}` markers. `grep -c '\\TODO{' ral.tex` is the submission gate.

---

## Page budget — read this before writing section IV

RA-L is **6 pages**, extensible to 8 with overlength charges.

- Abstract + §I–§III + bibliography alone: **6 pages**
- Plus §IV–§VIII *as skeletons*: **8 pages**

So the drafted front matter already consumes the entire standard budget, and
§IV–§VIII written out properly will not fit. Concrete trim targets, in the
order I would cut them:

1. **§III-A (the five requirements R1–R5)** — compress to one paragraph. The
   requirements are doing rhetorical work that §III-D (alternatives) largely
   repeats.
2. **§II-A (runtime verification foundations)** — can lose half its length;
   the anticipation/noisy-RV paragraph is a courtesy to that community and
   is not load-bearing for the argument.
3. **§III-F (what LTL does not give us)** — the four items can become two
   sentences each inside §VII (Threats), where they overlap anyway.
4. **§I-D (the time base subsection)** — forward-reference §IV instead of
   previewing it; roughly half of it is restated there.

Do **not** cut §II-F (*Position*) or §III-C (the three-valued/four-valued
argument). Those two carry the novelty claim.

---

## Claim / evidence audit

The draft is written so that no sentence asserts a measured result that does
not exist. Keep it that way.

**Supported today, by construction or by test:**

| claim | evidence in the repo |
|---|---|
| Monitor engine is unchanged across embodiments | monitor's inputs are a spec + an observation stream, neither of which names an embodiment (`docs/architecture.md`) |
| Monitor never reads an adapter descriptor; evaluator never reads a spec | architectural invariant, stated as checkable in `docs/architecture.md` |
| Schema parity across shipped descriptors | `real_g1`, `mujoco`, `isaac_lab` declare identical 21-key schemas over disjoint topic sets |
| Specs are mechanically validatable | `skill_monitor/core/spec_contract.py` — rejects any AP rule referencing an undeclared key |
| Generate → validate → repair loop exists | `skill_monitor/describer/generate_formulas.py:582` (`generate`) |
| Three-valued APs, freeze-on-unknown | designed and specified in `docs/clocking.md` |
| Suite is green | 1231 passed, 0 skipped in the test container |

**Asserted in the draft but NOT yet measured — every one is a `\TODO`:**

1. **The two-replay-path verdict-equality result (H1).** This is the
   acceptance test for the central claim and it has not been run. The
   recorder (`replay_node record` / `play --diff`) exists; no episode has
   been through both paths.
2. **Any real-robot number at all.** The G1 navigation experiment is still
   the next real work (`RESUME.md`, session 5). Everything quantitative in
   the paper today would be a test count or a construction argument.
3. **Skill-agnosticism across more than one skill family (H2).**
   Navigation is the only family instantiated end to end.
4. **Per-tick cost and coverage (H3).** Never profiled.
5. **Fault detection latency / false-positive rate (H4).** No induced-failure
   campaign has been run.

**Two facts that must stay in §VII and must not be softened:**

- `skill_monitor/specs/formulas_g1.json` is **hand-authored**. It is the
  evaluation reference, not the pipeline's output. Presenting it as a
  generated spec would falsify the authorship claim outright.
- **Five of its eight atomic propositions read the planner's self-report**
  (`mission_started`, `path_active`, `moving_towards_target`, `nav_stuck`,
  `mission_finished`). P12 (planner-independent schema) is designed and not
  deployed. Until it lands, the independence claim is architectural, not
  demonstrated — and the paper says so.

---

## Citation audit

27 entries. Author lists, titles and venues were checked against live
sources during drafting, **except** where an entry is preceded by a
`% VERIFY before submission:` comment in `refs.bib`. Those fields (mostly
DOIs, series volumes and page ranges for well-known older papers) are from
recall and need one pass against the publisher record.

Two entries need more than a field check:

- `liu2023grounding` (Lang2LTL) — only the first author (Jason Xinyu Liu) was
  confirmed; the entry currently reads `and others`. Get the full list.
- `sundarsingh2025conformalnl2ltl` — substituted for SCP-NL2TL
  (arXiv:2608.05439), whose author list could not be confirmed from this
  session. ConformalNL2LTL makes the same point (calibrated
  accept-or-abstain on NL→TL translation) and its authors *are* confirmed.
  If you want SCP-NL2TL specifically, pull its author list and swap it back.

Note: arxiv.org and alphaxiv.org are both blocked from this session's
network, so metadata came via search rather than from the abstract pages.
A session with arXiv allowed could resolve the whole VERIFY list quickly.

---

## Figures still needed

None are in the draft yet; all four exist as Mermaid in the docs and need
extracting to vector files:

| figure | source |
|---|---|
| the tick window (half-open interval, fold, step) | the ASCII diagram in `docs/clocking.md` |
| service / tier map | the `flowchart LR` in `docs/architecture.md` |
| the two replay paths (acceptance test) | the two-path table in `docs/architecture.md` |
| spec ⟂ adapter artifact split | the artifact table in `docs/architecture.md` |

Automaton renders (`output/*.png`) are generated at spec load and are not
committed; regenerate from `formulas_g1.json` if you want one as a figure.

---

## Still missing from the repo

`THESIS_PLAN.md` (revision 4) is the plan of record for the evaluation and
scope boundaries, and it lives in the **other** repo —
`~/TRAV-metric-map`, branch `ltl-skill-monitor`. §VI should be reconciled
against it before the protocol is treated as settled.
