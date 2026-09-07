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

## It is two pages by a small margin

908 words of body prose, one table, three references. The layout is tuned to land
exactly on two pages: 2.0 cm margins, compact `titlesec` headings, `\small` table,
`\footnotesize` bibliography. **Adding a paragraph will push it to three.** If you need
room, the cut order is: the table (worth about nine lines), then the two-concessions
sentence in "The claim, and the check behind it", then the opening paragraph.

## Before submitting

- One `\TODO{version}` remains, in "What the monitor is". Spot's own citing page
  requires naming the version you ran; read it off the machine that produced the
  results and replace the marker. It typesets as **[TODO: version]**, so it cannot be
  missed.
- `references.bib` holds five entries; three are cited and printed. Every entry was
  copied from the resolved `papers/<slug>/bibtex.md`, **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on. Keep it
  that way if you add a citation.
- `ferrando2020rosmonitoring` and `rtamt2024` are staged but uncited: they were carried
  by a sentence contrasting this work with the closest deployed tools, cut for length.
  Restore both together if the sentence comes back.
