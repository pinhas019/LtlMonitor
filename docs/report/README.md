# Progress report

`progress_report.tex` --- a two-page progress report for the supervisor. Source only;
the PDF is not tracked.

## Build

```bash
pdflatex progress_report && bibtex progress_report && \
pdflatex progress_report && pdflatex progress_report
```

Or upload `progress_report.tex` + `references.bib` to Overleaf and build with pdfLaTeX.
Verified here against TeX Live 2023 (Ubuntu `texlive-latex-base`,
`-latex-recommended`, `-latex-extra`, `-fonts-recommended`, `lmodern`): four passes,
**2 pages, no warnings, no overfull or underfull boxes.**

`lmodern` is not optional --- `microtype`'s font expansion refuses to run against the
non-scalable default fonts and the build dies with
`auto expansion is only possible with scalable fonts`.

## Structure: the claim, then the repository, then results by setting

**The claim** comes first, and it is the proposal's: skill execution as a finite set of
**progress states** --- equivalence classes of world-robot configurations indistinguishable
with respect to task advancement, joined by transition guards --- giving dimensionality
reduction and explainability, and fixing the limited context awareness of language- and
vision-based monitors.

**This repository** then frames `LtlMonitor` as the ongoing development of the question the
project started from: can a skill described in natural language be lifted to LTL, given an
LTL description of its progress, and monitored against it? **TRAV and MAAOS are examples,
not subjects** --- the report says so explicitly and the prose must keep it that way.

**Results are organised by setting**, not by workstream and not by condition. Earlier
drafts had a three-condition list closing the claim section and an evidence section keyed
to it; both were removed deliberately. Do not reinstate either --- and note that the
progress and evidence sections used to say the same things twice, which is what paid for
the current structure.

Three things must survive any future trim: the dropped-object example in the claim
section, the scripted-reference-plans caveat under MAAOS, and the sentence crediting
**MAAOS as Fouzi's project**.

## It is two pages, with room reserved

966 words of body prose, one specification example, five references. Page two has roughly
110 words of headroom and **that headroom is reserved for the two `\TODO` figure slots**
under MiniGrid and simple tasks. Fill those and the report stays at two pages; add
anything else first and it will not.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status and results, not a defect log.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates; "Why this should carry to the G1" is an argument from
  mechanism, phrased as expectation rather than promise. The one date in the file is the
  report's own.

## Before submitting

- **Two `\TODO` markers remain**, under MiniGrid and simple tasks in "Where it has been
  applied": the monitor-OFF / detection-only / detection-with-recovery figures from the
  consolidated ablation report. They typeset as **[TODO: ...]** so they cannot be missed.
  The Spot version is Spot 3.
- **ALFWorld, VLABench, NaVila and the 2025 MIT vision-language work are named in prose
  with no `\cite`, deliberately.** The proposal carries them as unresolved `[ref]`
  placeholders and there is no verified BibTeX for any of them. Do not invent entries.
- **The scripted-plan caveat in Assessment is load-bearing.** The deadlock figures come
  from runs driving scripted reference plans, not the live MAAOS planner, and the
  measured episodes and ablation results live on a different branch of the MiniGrid
  repository (`pinhas-monitor-benchmark`) from the working one. Do not drop that
  sentence to save a line --- without it the paragraph claims more than the evidence
  supports.
- Adding a **hazard** type is not specification-only; adding a **skill** is. An earlier
  draft had this backwards. The environment's hazard categories are a hardcoded chain,
  so a new hazard needs an environment change plus a matching proposition name.
- `references.bib` holds five entries; three are cited and printed. Every entry was
  copied from the resolved `papers/<slug>/bibtex.md`, **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on. Keep it
  that way if you add a citation.
- All five entries in `references.bib` are now cited and printed.
