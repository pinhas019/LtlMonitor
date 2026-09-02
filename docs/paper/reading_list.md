# Reading list

Three days, ~12 read closely, ~25 skimmed. Entries live in
[references.bib](references.bib); citation keys are given below.

Until this is done there is no paper. The repo has never cited anything, which
means no claim in it has been checked against the neighbours.

## Before anything: two novelty threats

Resolve both before writing a word of an introduction. Each one, if left
unaddressed, is a reviewer's whole review.

### 1 — GinSign already had the grounding idea

`english2025ginsign` grounds every atomic proposition into a many-sorted system
signature ⟨types, predicates, constants⟩, and argues — nearly in the words of
`core/spec_contract.py`'s docstring — that ungrounded LTL is "semantically
useless." Read it in full, not the abstract.

The three differences that are ours, and each must appear in the first two pages:

| | GinSign | here |
|---|---|---|
| grounding target | a hand-authored PDDL-style signature, fixed at inference | the **live adapter schema**, off a latched topic — change robots, the target changes, nothing retrains |
| the check | a learned BERT classifier, 95.5% grounded logical equivalence | a **free-variable check, sound by construction** — an undeclared key *will* raise `NameError`, so `unknown_keys` cannot false-negative |
| evaluation | VLTL-Bench only | **a robot** |

The soundness point is a trade, not a win: we buy it with coverage, because an AP
with no extractable `True when` rule falls to the LLM slow path instead. Say that
plainly rather than letting a reviewer find it.

### 2 — the generate→validate→repair loop is not novel

It is a standard 2026 pattern with its own literature: `verifyrepairstop2026`
(when to stop — directly about our `attempts=2`), `structuredfeedback2026` (the
validation→next-call interface, which is what `REPAIR_PROMPT`'s "found by a
mechanical check, not an opinion" is doing), `skillforge2026`, `veriact2026`.

**Do not claim the loop.** Claim the oracle — what it checks, and why the check is
sound — and the deployment.

## Day 1 — read closely. Paper A's positioning.

- [ ] `english2025ginsign` — threat 1. In full.
- [ ] `liu2023lang2ltl` — the other grounding approach: embedding similarity
      against a semantic map.
- [ ] `chen2023nl2tl` — the lifting-then-translation decomposition everyone builds on.
- [ ] `cosler2023nl2spec` — interactive sub-translation resolution. The
      human-in-the-loop alternative to a mechanical oracle; contrast explicitly.
- [ ] `fuggitti2023nl2ltl` — the template/few-shot baseline. Short.
- [ ] `hsiung2022lifted` — lifted LTL across domains.
- [ ] `verifyrepairstop2026`, `structuredfeedback2026` — threat 2. Skim, cite both.

## Day 2 — read the method sections. Foundations and tools.

- [ ] `bauer2011runtime` — **`MonitorStatus` in `core/automata.py` is this paper's
      LTL3.** Cite it and say so. Also the monitorability argument that justifies
      the UNDECIDED design in `docs/clocking.md:165-198`.
- [ ] `duretlutz2022spot` — every automaton comes from `spot.translate()`. Not
      citing the backend is a red flag.
- [ ] `rtamt2025` — closest tool comparison, and the source of the "why LTL and
      not STL" paragraph we owe the reader. **Cite the STTT 2024 journal version, not
      the arXiv preprint** — arXiv:2501.18608 is the accepted manuscript, and the key
      saying 2025 is a misnomer.
- [ ] `saferos2025` — architectural comparison for the two-tier deployment.
- [ ] `ferrando2020rosmonitoring` — the ROS-RV baseline a reviewer names first.
- [ ] `reelay2026` — for the tool table.
- [ ] `ltlfiniteobs2024` — only if Paper B's finite-trace semantics needs rigour.

## Day 3 — skim and cite.

**Surveys, for the introductions:** `fmras2025survey`, `tlsynthesis2026survey`.

**The contrast class.** A reviewer will ask "VLMs detect robot failures now, why do
I need a spec?" One paragraph answers it, and it argues **interpretability,
auditability and no training data** — not accuracy. Skim three or four:
`foresight2026`, `failsafe2025`, `patch2026`, `actprobe2026`, `vlafail2026`.

**Adjacent, cite in passing:**

- `embeddingtl2026` — closest to the CLIP-based `visually_at_goal` AP.
- `skillsentry2026` — shares our title-space in the LLM-agent domain. One sentence.
- `multiproperty2026` — `MultiMonitor` runs one automaton per formula rather than a
  product; this is where that trade-off is discussed.
- `whymonitorsfail2026` — a coverage-limits argument to pre-empt.

## The table Paper B needs

| | spec synthesis from NL | schema grounding | embodiment portability | deterministic replay |
|---|---|---|---|---|
| `ferrando2020rosmonitoring` | | | | |
| `rtamt2025` | | | | |
| `reelay2026` | | | | |
| `saferos2025` | | | | |
| **this work** | | | | |

We should be the only row with all four — **verify each cell against the tool's own
paper before printing it.** This is exactly the claim a reviewer who wrote one of
those tools will check, and getting a cell wrong costs more than the row is worth.

## Sourcing

Entries marked `% VERIFY` in `references.bib` have a confirmed title, arXiv ID and
date but an **unconfirmed author list** — they carry `author = {TODO}`. Resolve
every one from arXiv or DBLP before submitting anything. Entries marked `% CLASSIC`
are pre-2024 and published at a venue: cite the venue version from DBLP, not a
preprint.
