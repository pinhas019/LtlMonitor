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

## Structure: the proposal's claim leads

The report opens with **The claim**, and the claim is the one from the research proposal:
skill execution represented as a finite set of **progress states** --- equivalence classes
of world-robot configurations indistinguishable with respect to task advancement, joined
by transition guards --- yielding dimensionality reduction and explainability, and fixing
the limited context awareness of language- and vision-based monitors.

An earlier draft led instead with the *grounding* claim (that a generated specification
can be checked against a live sensor schema). That is the tools-paper positioning for the
implementation, not the thesis claim. It now appears once, demoted, in "How it works".
Do not promote it back.

The three conditions at the end of the claim section are the proposal's own research
goals: descriptions for **coded and learned** skills; a monitor given them measurably
outperforming the same monitor without them; and this holding on a **real humanoid**, not
only in benchmarks. "How far the claim has got" is structured against those three, in
order. If the conditions change, that section changes with them.

Two sentences carry more weight than anything else on the page and must not be cut for
space: the dropped-object example in the claim section, and the scripted-reference-plans
caveat in the second condition.

## It is two pages, and full

1027 words of body prose, one specification example, five references. Anything added now
needs something cut first. Cut order: the simulation paragraph in "Progress this period",
then the ROS-comparison clause in "Next steps".

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status per workstream, not a defect log.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates. The one date in the file is the report's own.

## Before submitting

- No `\TODO` markers remain. The Spot version is Spot 3.
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
