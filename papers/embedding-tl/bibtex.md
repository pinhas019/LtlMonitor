# BibTeX — Embedding Temporal Logic (ETL)

```bibtex
@misc{embeddingtl2026,
  title         = {Runtime Monitoring of Perception-Based Autonomous Systems via
                   Embedding Temporal Logic},
  author        = {Parv Kapoor and Abigail Hammer and Ashish Kapoor and
                   Karen Leung and Eunsuk Kang},
  year          = {2026},
  month         = may,
  eprint        = {2605.12651},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  note          = {Preprint. Carnegie Mellon University, Scaled Foundations,
                   University of Washington},
  url           = {https://arxiv.org/abs/2605.12651}
}
```

Replaces the `% VERIFY` stub at `docs/paper/references.bib:300–312`, which had
`author = {TODO}` and an `@article` type with `journal = {arXiv preprint ...}`.
Two changes beyond the author list, both deliberate:

- `@article` → `@misc` with `eprint`/`archivePrefix`, matching the arXiv-preprint style
  already used elsewhere in the repo (e.g. `english2025ginsign`). There is no journal.
- The stale comment on `references.bib:311–312` ("Shares our title-space ('skill' +
  'runtime assurance') in the LLM-agent domain rather than robotics") **does not describe
  this paper** and should be deleted, not carried over. It appears to belong to a
  different entry. ETL is a robotics/CPS runtime-monitoring paper with no LLM-agent
  content and no "skill" terminology; the correct one-line distinguisher is that ETL
  defines predicates over pretrained-encoder embeddings and monitors bounded-horizon
  robustness, whereas `skill_monitor` runs an ω-automaton over Boolean APs.

## Verification note

**Verified.** Title, the full author list, affiliations and the equal-contribution marking
were read directly off page 1 of the PDF via `mcp__alphaXiv__answer_pdf_queries` (paper
`2605.12651`):

- **Parv Kapoor**\*, Software and Societal Systems Department, Carnegie Mellon University
  — `parvk@andrew.cmu.edu`
- **Abigail Hammer**\*, Software and Societal Systems Department, Carnegie Mellon University
  — `arhammer@andrew.cmu.edu`
- **Ashish Kapoor**, Scaled Foundations — `ashish@generalrobotics.company`
- **Karen Leung**, Aeronautics and Astronautics Department, University of Washington
  — `kymleung@uw.edu`
- **Eunsuk Kang**, Software and Societal Systems Department, Carnegie Mellon University
  — `eunsukk@andrew.cmu.edu`

\* Parv Kapoor and Abigail Hammer are marked as equal contributors ("∗ Indicates equal
contribution", p.1). Author order above is the order printed on the paper. Note that
**Parv Kapoor and Ashish Kapoor are different people at different institutions** — do not
merge or deduplicate them.

The arXiv identifier, version, primary class and date come from the stamp printed down the
left margin of page 1: `arXiv:2605.12651v1 [cs.LG] 12 May 2026`. Hence `year = 2026`,
`month = may`, `primaryClass = {cs.LG}`.

**Not verified.** The arXiv abstract page at `https://arxiv.org/abs/2605.12651` was not
fetched from this environment, so: cross-listed categories (`cs.RO`, `cs.AI` and `cs.LO`
would all be plausible for this content, but are **not** confirmed), the `comments` field
(page count, venue), the canonical arXiv author-string spelling, and the existence of any
`v2` revision are all unconfirmed. No venue is stated anywhere in the paper — every page
header reads "Preprint." — so `note` records affiliations only. If a venue is later
confirmed, convert to `@inproceedings` and keep the `eprint` field.

The artifacts footnote on p.7 gives
`https://github.com/ETLMonitoringAuthors/ETLMonitoring`. That is an **anonymised** author
handle from the review cycle; it was not fetched and may not resolve. Do not put it in the
BibTeX entry until it has been checked, and prefer a de-anonymised URL if one appears in a
later version.
