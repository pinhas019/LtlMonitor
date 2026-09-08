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

## It is two pages, with one slot reserved

711 words of body prose, one status table, one specification example, five references.
Page two has roughly 140 words of headroom, and that headroom is **reserved for the
MAAOS paragraph** in Assessment. Drop that content in and the report stays at two
pages; add anything else first and it will not.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status per workstream, not a defect log. No specific defects,
  file paths or individual bug write-ups --- those were removed on purpose, not for
  space.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates, and forward-looking sentences are phrased as intent
  rather than undertaking. The one date in the file is the report's own, in `\date{}`.

## Before submitting

- One `\TODO{}` remains, in Assessment: the MAAOS scenarios --- what the monitor
  caught, how, and what it changed. It typesets as **[TODO: ...]**, so it cannot be
  missed. Nothing else is outstanding; the Spot version is resolved to Spot 3.
- `references.bib` holds five entries; three are cited and printed. Every entry was
  copied from the resolved `papers/<slug>/bibtex.md`, **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on. Keep it
  that way if you add a citation.
- All five entries in `references.bib` are now cited and printed.
