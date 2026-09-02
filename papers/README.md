# Papers

Twenty papers, one subfolder each. Every subfolder gets a `summary.md` written by a
study agent — one-paragraph summary, key concepts, method, results, limitations, what
it means for this repo, and a `bibtex.md` carrying the **verified** entry.

Read in the order below. It is sorted by *what could still change the experiment*,
not by importance — items 05 and 06 carry decisions that alter E1's design, so they
come before day 2's foundational reading.

The `% VERIFY` markers in `docs/paper/references.bib` exist because 21 of 30 entries
there have a confirmed title, arXiv ID and date but an **unconfirmed author list**.
Each agent resolves its own paper's entry into `papers/<slug>/bibtex.md`; those are
what should be folded back into `references.bib`.

---

## Day 1 — Paper A's positioning (3 h 50 m)

| # | folder | paper | id | key | min |
|---|---|---|---|---|---|
| 01 | `ginsign/` | GinSign: Grounding Natural Language Into System Signatures for Temporal Logic Translation | [arXiv:2512.16770](https://arxiv.org/abs/2512.16770) | `english2025ginsign` | 60 |
| 02 | `lang2ltl/` | Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments (Lang2LTL) | [arXiv:2302.11649](https://arxiv.org/abs/2302.11649) | `liu2023lang2ltl` | 40 |
| 03 | `nl2tl/` | NL2TL: Transforming Natural Languages to Temporal Logics using LLMs | [arXiv:2305.07766](https://arxiv.org/abs/2305.07766) | `chen2023nl2tl` | 30 |
| 04 | `nl2spec/` | nl2spec: Interactively Translating Unstructured Natural Language to Temporal Logics | [doi:10.1007/978-3-031-37703-7_18](https://doi.org/10.1007/978-3-031-37703-7_18) | `cosler2023nl2spec` | 30 |
| 05 | `nl2ltl/` | NL2LTL: A Python Package for Converting NL Instructions to LTL Formulas | AAAI 2023 — no arXiv ID confirmed | `fuggitti2023nl2ltl` | 20 |
| 06 | `verify-repair-stop/` | Verify, Repair, Repeat, or Stop? Robust Stopping for Noisy Verify-Repair Loops in LLM Agents | [arXiv:2607.17641](https://arxiv.org/abs/2607.17641) | `verifyrepairstop2026` | 25 |
| 07 | `structured-feedback/` | Structured Feedback Improves Repair in an LLM Agent Loop | [arXiv:2607.14167](https://arxiv.org/abs/2607.14167) | `structuredfeedback2026` | 25 |

**Stop rule.** Items 05 and 06 carry decisions, not citations. If NL2LTL turns out to
be a runnable second baseline for E1, or if the stopping paper says `attempts=2` should
become a sweep over *k*, write that into the plan **before** opening the next paper.
That is the entire reason related work runs ahead of the experiment rather than beside it.

## Day 2 — foundations and tools (method sections only)

| # | folder | paper | id | key |
|---|---|---|---|---|
| 08 | `ltl3-bauer/` | Runtime Verification for LTL and TLTL | TOSEM 2011 — cite the venue version | `bauer2011runtime` |
| 09 | `spot/` | Spot — the LTL/ω-automata library | [spot.lre.epita.fr](https://spot.lre.epita.fr/citing.html) | `duretlutz2022spot` |
| 10 | `rtamt/` | RTAMT — Runtime Robustness Monitors with Application to CPS and Robotics | [arXiv:2501.18608](https://arxiv.org/abs/2501.18608) | `rtamt2025` |
| 11 | `safe-ros/` | Safe-ROS: An Architecture for Autonomous Robots in Safety-Critical Domains | [arXiv:2511.14433](https://arxiv.org/abs/2511.14433) | `saferos2025` |
| 12 | `rosmonitoring/` | ROSMonitoring: A Runtime Verification Framework for ROS | TAROS 2020 | `ferrando2020rosmonitoring` |
| 13 | `reelay/` | Reelay: Online Temporal Logic Monitoring Framework | [arXiv:2604.22384](https://arxiv.org/abs/2604.22384) | `reelay2026` |
| 14 | `ltl-finite-observations/` | Semantics for Linear-time Temporal Logic with Finite Observations | [arXiv:2411.14581](https://arxiv.org/abs/2411.14581) | `ltlfiniteobs2024` |

**08 is not optional.** `MonitorStatus` in `core/automata.py` *is* this paper's LTL3.
**09 is not optional either** — every automaton in that file comes out of
`spot.translate()`, and not citing your own backend is a red flag to any formal-methods
reviewer.

## Day 3 — framing and the contrast class (skim)

| # | folder | paper | id | key |
|---|---|---|---|---|
| 15 | `fm-robots-survey/` | Revisiting Formal Methods for Autonomous Robots: A Structured Survey | [arXiv:2509.20488](https://arxiv.org/abs/2509.20488) | `fmras2025survey` |
| 16 | `tl-synthesis-survey/` | Temporal Logics and Formal Synthesis for Robot Planning and Control | [arXiv:2606.21438](https://arxiv.org/abs/2606.21438) | `tlsynthesis2026survey` |
| 17 | `foresight/` | Foresight: Failure Detection for Long-Horizon Robotic Manipulation | [arXiv:2606.23085](https://arxiv.org/abs/2606.23085) | `foresight2026` |
| 18 | `failsafe/` | FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models | [arXiv:2510.01642](https://arxiv.org/abs/2510.01642) | `failsafe2025` |
| 19 | `embedding-tl/` | Runtime Monitoring of Perception-Based Autonomous Systems via Embedding Temporal Logic | [arXiv:2605.12651](https://arxiv.org/abs/2605.12651) | `embeddingtl2026` |
| 20 | `multi-property/` | Multi-Property Temporal Logic Monitoring | [arXiv:2605.13668](https://arxiv.org/abs/2605.13668) | `multiproperty2026` |

17 and 18 are the **contrast class**: a reviewer will ask "VLMs detect robot failures
now, why do I need a spec?" The answer argues interpretability, auditability and zero
training data — *not* accuracy, which is not a fight worth picking.

---

## Cited but not queued

In `references.bib` and worth citing, but no folder and no agent — they are one-line
mentions, not reading:

`hsiung2022lifted` · `scpnl2tl2026` · `skillforge2026` · `veriact2026` ·
`skillsentry2026` · `whymonitorsfail2026` · `patch2026` · `actprobe2026` · `vlafail2026`

Promote one to a folder if a reviewer's likely objection turns out to live there.

## Folder contents

```
papers/<slug>/
  summary.md    written by the study agent — read this before the PDF
  bibtex.md     the verified entry, to fold back into docs/paper/references.bib
```

Put your own reading notes in `papers/<slug>/notes.md`. Nothing generates that one.
