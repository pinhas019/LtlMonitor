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

## Structure

**The claim.** Progress states are the **semantic** state of the robot with respect to the
task --- equivalence classes of world-robot configurations indistinguishable with respect
to task advancement. Boolean guards are the *transitions*, and their role in the argument
is that they make per-tick assessment **cheap**; do not re-describe them as where the
semantics live. Keep dimensionality reduction, explainability, and the context-awareness
weakness. The skill **can** deviate --- not *must*, not *does*.

An earlier draft illustrated the context-awareness weakness with a dropped-cup
pick-and-place example. **It was removed deliberately** and replaced by the statement that
progress states ground the assessment, lifting it from a single free-text prompt into a
semi-structured, LangGraph-like state-graph machine. Do not reinstate the example.

**Two streams.** The repository section frames the work as two streams and the prose must
keep them distinct: *skill description* (an LLM drafts the progress structure, converted to
LTL, compiled by **Spot 3**) and *skill monitoring* (an LLM plus Python boolean guard
evaluators supply the propositions at runtime). The research question --- can a
natural-language skill description be lifted to LTL and monitored? --- and the repository
URL lead the section.

**Where it runs.** Simple tasks in a **continuous version of MiniGrid**, integrated with
MAAOS; TRAV navigation is *under development*, not deployed. TRAV and MAAOS are examples,
not the subject.

**Results are organised by finding, not by setting** --- where the monitor helped, where it
did not, and why. Earlier drafts were keyed to conditions and then to settings; both were
replaced. The four findings are load-bearing and should survive a trim:

1. Recovery is what pays. Detection coupled to re-planning is +1.00 on both the corrupted
   single-agent plan and the cooperative deadlock.
2. Detection alone is +0.00 everywhere. Halting stops drift; it does not reach the goal.
3. The unstructured LLM judge is +0.00 *even with recovery*, where the LTL monitors are
   +1.00 on the same scenario and seeds. This is the argument for progress states, measured
   --- it is the most valuable number in the report.
4. Zero false alarms on clean and hazard-navigation runs; the one failure was a
   specification fault (a predicate demanded continuous alignment that the real push skill
   never sustains). A stronger judge model did not fix it; relaxing the formula did.

Two caveats in that section are **load-bearing and must not be cut**: the runs drove
**scripted reference plans**, not the live MAAOS planner, and the figures come from
**discrete-mode** episodes rather than continuous physics. The sentence crediting **MAAOS
as Fouzi's project** must also survive.

**The G1** is *under development*, not a finished result: partial specification, navigation
experiment not run, and good assessment on hardware needs a **VLM in the proposition
layer**, which is not built. The embodiment-independence argument (three adapters, one
schema, one engine) is folded into this section --- it used to be its own section.

**Next steps**: deploy on the simulator (Isaac Sim / MuJoCo), extend to more skills
(pick-and-place next), and refine against the literature review, which is **complete** on
description and monitoring --- earlier drafts said "ongoing at twenty papers".

## It is two pages, and it is full

~1120 words of body prose, one specification example, five references. There is no
headroom left: anything added needs something else cut. If a trim is forced, cut in this
order --- the ALFWorld/VLABench/NaVila evaluation sentence, then the ROS-comparison clause,
then the specification example table.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status and results, not a defect log.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates. The one date in the file is the report's own.

## Before submitting

- **No `\TODO` markers remain.** The `\TODO` macro is still defined for future use;
  `grep 'TODO{' progress_report.tex` should match only the `\newcommand` line.
- The Spot version is **Spot 3**.
- **ALFWorld, VLABench, NaVila and the 2025 MIT vision-language work are named in prose
  with no `\cite`, deliberately.** The proposal carries them as unresolved `[ref]`
  placeholders and there is no verified BibTeX for any of them. Do not invent entries.
- Adding a **hazard** type is not specification-only; adding a **skill** is. An earlier
  draft had this backwards. The environment's hazard categories are a hardcoded chain,
  so a new hazard needs an environment change plus a matching proposition name.
- `references.bib` holds five entries; all five are cited and printed. Every entry was
  copied from the resolved `papers/<slug>/bibtex.md`, **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on. Keep it
  that way if you add a citation.
