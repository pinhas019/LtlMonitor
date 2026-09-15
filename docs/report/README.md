# Progress report

`progress_report.tex` --- a two-page progress report for the supervisor. Source only;
the PDF is not tracked.

## Build

```bash
pdflatex progress_report && pdflatex progress_report
```

**Two passes, no `bibtex`.** The report has no bibliography --- see "No citations" below.
Or upload `progress_report.tex` to Overleaf and build with pdfLaTeX. Verified here against
TeX Live 2023 (Ubuntu `texlive-latex-base`, `-latex-recommended`, `-latex-extra`,
`-fonts-recommended`, `lmodern`): **2 pages, no warnings, no overfull or underfull boxes.**

`lmodern` is not optional --- `microtype`'s font expansion refuses to run against the
non-scalable default fonts and the build dies with
`auto expansion is only possible with scalable fonts`.

## No citations

**All `\cite` commands and the bibliography were removed deliberately.** Prior work is
named in prose instead (Spot 3, three-valued LTL semantics, the `papers/` queue in "Next
steps"). `references.bib` is left in place unused, so citations can be reinstated without
rebuilding it --- if you do, restore `\bibliographystyle`, `\bibliography{references}` and
the four-pass build. Do not re-add `\cite` markers piecemeal.

## Structure

**The claim.** Progress states are the **semantic** state of the robot with respect to the
task --- equivalence classes of world-robot configurations indistinguishable with respect
to task advancement. The transitions are **semantic predicates**, and only *part* of those
predicates translates into boolean guards --- an earlier draft said flatly that "transitions
between them are boolean guards", which overclaims. The guards' role in the argument is that
they make per-tick assessment **cheap where it applies**; do not re-describe them as where
the semantics live, and do not restore the unqualified version. The skill **can** deviate ---
not *must*, not *does*.

Three things were removed deliberately and must not be reinstated:

- **The dimensionality-reduction property.** Earlier drafts paired it with explainability
  as "two properties follow". Only explainability remains, folded into the first paragraph.
- **The dropped-cup pick-and-place example**, which used to illustrate the
  context-awareness weakness.
- **The LangGraph/LangChain comparison.** The grounding sentence now says progress states
  lift the assessment from a free-text prompt into "a semi-structured state graph" and
  stops there. Naming a framework read as a claim about the implementation; it was only
  ever meant as an example.

**Two streams.** The repository section frames the work as two streams and the prose must
keep them distinct: *skill description* (an LLM drafts the progress structure, converted to
LTL, compiled by **Spot 3**) and *skill monitoring* (an LLM plus Python boolean guard
evaluators supply the propositions at runtime). The framing sentence is **declarative, not
a question** --- an earlier draft ended it with "...and monitored against it at runtime?"
and the question mark read as though the project were still asking rather than building.

**Where it runs.** Simple tasks in a **continuous version of MiniGrid**, integrated with
MAAOS; TRAV navigation is *under development*, not deployed. TRAV and MAAOS are examples,
not the subject. The credit line is specific and should stay specific: *MAAOS is Fouzi's
project, and I worked on it to integrate it into the continuous version of MiniGrid* --- the
contribution is the integration, not the project.

**Results** open by **describing the environment and the task** --- continuous-dynamics grid
world, lava hazards, the single-agent push, the two-agent align-and-push formation, and the
three scenarios (clean, hazard approach, injected fault) --- before any number. Then four
findings, organised by what was learned rather than by setting. All four are load-bearing:

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

**The G1** is *currently under development*, not a finished result: partial specification
and the navigation experiment not run. The section must state that the intended use is
**monitoring Elias's TRAV navigation application** --- the first skill developed
independently of the monitor --- and that good assessment there needs a **VLM in the
proposition layer**, which is not built. The embodiment-independence argument (three
adapters, one schema, one engine) is folded into this section; it used to be its own.

**Next steps is a three-item bulleted list**, and should stay one --- prose here was hard to
scan:

1. **Simulation integration** (Isaac Sim / MuJoCo; the robot's own stack and scenario reset
   are what remain), which is also where pick-and-place and a learned policy come in.
2. **Deploy on the G1 and the TRAV navigation application**, evaluated by the same
   monitor-on / monitor-off ablation as MiniGrid. This bullet must carry the **expectation
   that the monitored arm completes more runs**, and the reason: the failures that end a
   navigation episode (stalling, a stuck recovery loop, a safety-guard violation) are the
   classes detection already caught in simulation, where catching them early enough to
   re-plan is what converted a failed run into a completed one. TRAV is being developed
   independently of the monitor, so this is the first test on a skill the monitor did not
   shape.
3. **Papers review** --- the review on description and monitoring is **complete**; the
   twenty-paper queue in `papers/` is the next reading, introduced in three directions:
   positioning (NL-to-LTL grounding, verify-repair), foundations and tools (LTL3, Spot,
   RTAMT, ROSMonitoring, Reelay, Safe-ROS), and the contrast class (Foresight, FailSafe,
   embedding TL). Keep the contrast class's framing: the "why not just a VLM?" objection is
   answered on interpretability, auditability and zero training data --- **not** on accuracy,
   which is not a fight worth picking. See `papers/README.md`.

## It is two pages, and it is full

~1320 words of body prose and one specification example, and it is at the page boundary ---
adding two sentences pushes it to three pages. Paying for the Next-steps bullets already cost
the "settling the claim" sentence, the GinSign contrast clause, and half the
embodiment-independence argument in the G1 section. If a trim is forced again, cut in this
order --- the contrast-class clause in "Next steps", the remaining embodiment-independence
clause, then the specification example table.

Two register choices are deliberate and easy to undo by accident:

- **Overview altitude.** Status and results, not a defect log.
- **No calendar, and no hard commitments.** "Next steps" is paced by what becomes
  available rather than by dates. The one date in the file is the report's own.

## Before submitting

- **No `\TODO` markers remain.** The `\TODO` macro is still defined for future use;
  `grep 'TODO{' progress_report.tex` should match only the `\newcommand` line.
- The Spot version is **Spot 3**.
- Adding a **hazard** type is not specification-only; adding a **skill** is. An earlier
  draft had this backwards. The environment's hazard categories are a hardcoded chain,
  so a new hazard needs an environment change plus a matching proposition name.
- If citations are ever reinstated: `references.bib` holds five verified entries, each
  copied from the resolved `papers/<slug>/bibtex.md` and **not** from
  `docs/paper/references.bib` --- sixteen entries in that file still carry a literal
  `author = {TODO}`, which BibTeX typesets silently instead of erroring on.
