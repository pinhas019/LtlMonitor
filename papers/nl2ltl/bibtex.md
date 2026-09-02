# NL2LTL — BibTeX

## Verification status

| Field | Value | How verified |
|---|---|---|
| Authors | Francesco Fuggitti; Tathagata Chakraborti | `AUTHORS.md` + `pyproject.toml` in the official repo (read directly); corroborated by PyPI metadata and by REQ2LTL's reference list |
| Title | NL2LTL — a Python Package for Converting Natural Language (NL) Instructions to Linear Temporal Logic (LTL) Formulas | Repo README's own BibTeX; search snippets; REQ2LTL ref. [24] |
| Venue | AAAI Conference on Artificial Intelligence (AAAI-23) | Two independent search snippets; REQ2LTL ref. [24] |
| Year | 2023 | same |
| Volume / number | 37 / 13 | Search snippet of the AAAI OJS listing; REQ2LTL ref. [24] |
| Pages | 16428–16430 (3 pages) | Search snippet of the IBM Research publications listing; REQ2LTL ref. [24] gives "pp. 16 428–16 430" |
| DOI | `10.1609/aaai.v37i13.27068` | REQ2LTL ref. [24] states it verbatim; the ACM DL URL `dl.acm.org/doi/10.1609/aaai.v37i13.27068` appeared as a search result title for this paper |
| **Demo track** | **Yes** | Two lines of evidence, below |
| **arXiv ID** | **None found** | See below |

### Demo track — the evidence

I could not open the AAAI page (`ojs.aaai.org` and `aaai-23.aaai.org` are both blocked by
this session's egress proxy), so this rests on two converging independent sources:

1. AAAI Proceedings **Vol. 37 No. 13** is titled *"AAAI-23 Special Programs, IAAI-23,
   EAAI-23, Student Papers and Demonstrations"* and contains a Demonstrations section
   (from the OJS issue listing, via search). This paper is in v37i13 at pp. 16428–16430 —
   a 3-page paper, consistent with a demo.
2. **The authors' own BibTeX**, committed in the repo README, annotates the AAAI entry
   `note = {System Demonstration.}`.

Treat "demo track" as confirmed. If you want a primary-source check before submission,
open <https://ojs.aaai.org/index.php/AAAI/article/view/27068> from an unrestricted machine.

### arXiv — searched, not found

`mcp__alphaXiv__answer_pdf_queries` was queried by full title and **resolved to a different
paper** (REQ2LTL, arXiv:2512.17334), which is what the tool does when the requested paper is
not in the arXiv corpus. Three targeted WebSearch queries for an NL2LTL arXiv entry returned
none. Neither the repo README, `CHANGES.md`, `docs/references.md`, nor `pyproject.toml`
mentions an arXiv ID; the README's own BibTeX entries cite ICAPS and AAAI only.

**Conclusion: there is no arXiv preprint. Use the DOI.** Do not invent an arXiv ID.

---

## Primary entry — use this one

AAAI's OJS publishes the proceedings as a journal (volume/issue/pages), so `@article` is the
form that matches the DOI's own metadata:

```bibtex
@article{fuggitti2023nl2ltl,
  author  = {Fuggitti, Francesco and Chakraborti, Tathagata},
  title   = {{NL2LTL} -- a {P}ython Package for Converting Natural Language ({NL})
             Instructions to Linear Temporal Logic ({LTL}) Formulas},
  journal = {Proceedings of the {AAAI} Conference on Artificial Intelligence},
  volume  = {37},
  number  = {13},
  pages   = {16428--16430},
  year    = {2023},
  doi     = {10.1609/aaai.v37i13.27068},
  url     = {https://ojs.aaai.org/index.php/AAAI/article/view/27068},
  note    = {AAAI-23 Demonstration Track. Code: \url{https://github.com/IBM/nl2ltl}}
}
```

### `@inproceedings` variant (DBLP/ACM style)

If your bibliography style prefers proceedings entries — most robotics/ICRA styles do:

```bibtex
@inproceedings{fuggitti2023nl2ltl,
  author    = {Fuggitti, Francesco and Chakraborti, Tathagata},
  title     = {{NL2LTL} -- a {P}ython Package for Converting Natural Language ({NL})
               Instructions to Linear Temporal Logic ({LTL}) Formulas},
  booktitle = {Proceedings of the Thirty-Seventh {AAAI} Conference on Artificial Intelligence
               ({AAAI-23})},
  publisher = {{AAAI} Press},
  volume    = {37},
  number    = {13},
  pages     = {16428--16430},
  year      = {2023},
  doi       = {10.1609/aaai.v37i13.27068},
  note      = {Demonstration Track}
}
```

Both are the same paper; pick one, not both. The `@article` form is closer to what the DOI
resolves to.

---

## Companion: the ICAPS 2023 demo paper

The authors published a second demonstration of the same system at ICAPS 2023, where it won
the **People's Choice Best System Demonstration Award Runner-Up** (stated in the repo
README). Their README bibtex cites **both** venues, so consider doing the same if NL2LTL is
load-bearing in your related work.

**Caveat:** `icaps23.icaps-conference.org` is blocked by this session's egress proxy, so I
could **not** read the ICAPS PDF or verify its page numbers. The entry below is reproduced
from the authors' own BibTeX in the repo README and deliberately carries no pages or DOI —
**fill those in from the PDF before submitting, or drop this entry.**

```bibtex
@inproceedings{fuggitti2023nl2ltl-icaps,
  author    = {Fuggitti, Francesco and Chakraborti, Tathagata},
  title     = {{NL2LTL} -- A Python Package for Converting Natural Language ({NL})
               Instructions to Linear Temporal Logic ({LTL}) Formulas},
  booktitle = {Proceedings of the International Conference on Automated Planning and
               Scheduling ({ICAPS}), System Demonstration Track},
  year      = {2023},
  note      = {Best System Demonstration Award Runner-Up.
               UNVERIFIED: pages and DOI not checked --
               \url{https://icaps23.icaps-conference.org/demos/papers/6374_paper.pdf}}
}
```

---

## Software citation

If you run it as a baseline, cite the artifact as well as the paper. Verified from PyPI JSON
and the repo:

```bibtex
@software{nl2ltl-software,
  author  = {Fuggitti, Francesco and Chakraborti, Tathagata},
  title   = {{NL2LTL}: Natural Language ({NL}) to Linear Temporal Logic ({LTL})},
  version = {0.0.6},
  year    = {2024},
  month   = feb,
  url     = {https://github.com/IBM/nl2ltl},
  note    = {MIT License. Version 0.0.6 released 2024-02-15; last commit on \texttt{main}
             also 2024-02-15. Requires Python >=3.8,<3.11 and \texttt{openai==1.12.0}.}
}
```

---

## Related entry you will likely need alongside it

REQ2LTL is the source of the only third-party quantitative measurements of NL2LTL I could
locate (see `summary.md` §4.1). Verified by reading the PDF directly via alphaXiv.

```bibtex
@article{ma2025req2ltl,
  author  = {Ma, Zhi and Wen, Cheng and Su, Zhexin and Liang, Xiao and Tian, Cong
             and Qin, Shengchao and Yang, Mengfei},
  title   = {Bridging Natural Language and Formal Specification -- Automated Translation
             of Software Requirements to {LTL} via Hierarchical Semantics Decomposition
             Using {LLM}s},
  journal = {arXiv preprint arXiv:2512.17334},
  year    = {2025},
  note    = {arXiv:2512.17334 [cs.SE], 19 December 2025}
}
```
