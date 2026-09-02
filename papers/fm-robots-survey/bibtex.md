# BibTeX — `fmras2025survey`

## Verification status

| Field | Status |
|---|---|
| Author list | **VERIFIED.** Read from the PDF title block, arXiv:2509.20488v1 p. 1, and confirmed independently against the Springer chapter record. Four authors, in order: Atef Azaiez, David A. Anisi, Marie Farrell, Matt Luckcuck. |
| Affiliations | **VERIFIED** (p. 1). Azaiez & Anisi: Faculty of Science and Technology, Norwegian University of Life Sciences (NMBU), Ås, Norway. Farrell: Department of Computer Science, University of Manchester, UK. Luckcuck: School of Computer Science, University of Nottingham, UK. |
| Peer-reviewed version | **YES — exists, and should be the cited version.** TAROS 2025 (26th Annual Conference Towards Autonomous Robotic Systems), York, UK, 20–22 August 2025. Springer, Lecture Notes in Computer Science vol. 16045 (LNAI subseries), pp. 338–352, DOI `10.1007/978-3-032-01486-3_26`. Volume editors: Ana Cavalcanti, Simon Foster, Robert Richardson. |
| arXiv | 2509.20488v1 [cs.RO], submitted 24 Sep 2025 — i.e. the preprint postdates the conference. |
| Page range 338–352 | Read from the Springer chapter listing via web search; **not** confirmed against the publisher page directly (`link.springer.com` was unreachable from this environment). Low risk, but re-check before camera-ready. |
| "(Invited Paper)" | The ResearchGate record titles this "…: A Structured Survey (Invited Paper)". Whether Springer's official chapter title carries that suffix is **not verified**. The entry below omits it; the arXiv title does not have it. |
| Supplementary dataset | The 181-paper surveyed-literature set is published separately on Zenodo, DOI `10.5281/zenodo.15199605` (Apr 2025). Second entry below. |
| Funding (p. 12) | Norwegian Research Council RoboFarmer project 336712; EPSRC EP/Y001532/1; Royal Academy of Engineering. |

## Use this entry — the published version

```bibtex
@inproceedings{fmras2025survey,
  author       = {Azaiez, Atef and Anisi, David A. and Farrell, Marie and
                  Luckcuck, Matt},
  title        = {Revisiting Formal Methods for Autonomous Robots: A Structured
                  Survey},
  booktitle    = {Towards Autonomous Robotic Systems (TAROS 2025)},
  series       = {Lecture Notes in Computer Science},
  volume       = {16045},
  pages        = {338--352},
  publisher    = {Springer},
  address      = {Cham},
  year         = {2025},
  doi          = {10.1007/978-3-032-01486-3_26},
  eprint       = {2509.20488},
  archivePrefix= {arXiv},
  primaryClass = {cs.RO}
}
```

This replaces the `author = {TODO}` `@article` stub at `docs/paper/references.bib:392`,
and the `% VERIFY — author list not confirmed.` marker above it can be deleted. Note the
type change from `@article` to `@inproceedings`.

## Preprint-only fallback

Only if a venue's style forbids mixing published and preprint forms, or if the page range
cannot be confirmed in time:

```bibtex
@article{fmras2025survey,
  author       = {Azaiez, Atef and Anisi, David A. and Farrell, Marie and
                  Luckcuck, Matt},
  title        = {Revisiting Formal Methods for Autonomous Robots: A Structured
                  Survey},
  journal      = {arXiv preprint arXiv:2509.20488},
  year         = {2025},
  eprint       = {2509.20488},
  archivePrefix= {arXiv},
  primaryClass = {cs.RO}
}
```

## Companion dataset

Cite this if you derive any count from the 181-paper corpus (see `summary.md` §5.4 —
this is the route to a defensible hardware-deployment number).

```bibtex
@dataset{azaiez2025surveyset,
  author       = {Azaiez, Atef and Anisi, David A. and Farrell, Marie and
                  Luckcuck, Matt},
  title        = {Revisiting Formal Methods for Autonomous Robots: A Structured
                  Survey --- Surveyed Literature Set},
  year         = {2025},
  month        = apr,
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.15199605}
}
```

## The prior survey this one revisits — you should be citing it too

Reference [17] of the surveyed paper. Author list and venue read from that reference list
(p. 14); **not** independently verified against the ACM record, though the entry is
unusually complete and self-consistent.

```bibtex
@article{luckcuck2019survey,
  author       = {Luckcuck, Matt and Farrell, Marie and Dennis, Louise A. and
                  Dixon, Clare and Fisher, Michael},
  title        = {Formal Specification and Verification of Autonomous Robotic
                  Systems: A Survey},
  journal      = {ACM Computing Surveys},
  volume       = {52},
  number       = {5},
  year         = {2019},
  month        = sep,
  doi          = {10.1145/3342355}
}
```
