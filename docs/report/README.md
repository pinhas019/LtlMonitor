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

## Structure: the claim leads

The report opens with **The claim** --- what is being asserted, why grounding is the
obstacle, and the three conditions that would settle it --- and only then explains the
mechanism. Everything after that is organised as evidence for or against those three
conditions. This ordering is the point of the document; do not reinstate a
technical-overview opening.

## It is two pages, and full

943 words of body prose, one specification example, five references; page two runs about
seven-eighths full. There is no status table any more: with progress reported per
workstream and a section assessing the claim, it duplicated both. Anything added now
needs something cut first.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status per workstream, not a defect log. No specific defects,
  file paths or individual bug write-ups --- those were removed on purpose, not for
  space.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates, and forward-looking sentences are phrased as intent
  rather than undertaking. The one date in the file is the report's own, in `\date{}`.

## Before submitting

- No `\TODO` markers remain. The Spot version is Spot 3.
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
