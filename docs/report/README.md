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

## It is two pages, with a little room

884 words of body prose, one status table, three references; page two is nearly full.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status per workstream, not a defect log. No specific defects,
  file paths or individual bug write-ups --- those were removed on purpose, not for
  space.
- **No calendar, and no hard commitments.** "Next steps" is ordered by dependency
  rather than by date, and forward-looking sentences are phrased as intent rather than
  undertaking. The one date in the file is the report's own, in `\date{}`. If you add a
  step, give it a position in the sequence, not a deadline.

## Before submitting

- One `\TODO{version}` remains, in "Approach". Spot's own citing page
  requires naming the version you ran; read it off the machine that produced the
  results and replace the marker. It typesets as **[TODO: version]**, so it cannot be
  missed.
- `references.bib` holds five entries; three are cited and printed. Every entry was
  copied from the resolved `papers/<slug>/bibtex.md`, **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on. Keep it
  that way if you add a citation.
- `ferrando2020rosmonitoring` and `rtamt2024` are staged but uncited: they were carried
  by a sentence contrasting this work with the closest deployed tools, cut when the
  report moved to overview altitude. Restore both together if the sentence comes back.
