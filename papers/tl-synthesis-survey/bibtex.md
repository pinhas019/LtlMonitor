# BibTeX — `tlsynthesis2026survey`

## Verified entry

Author list **confirmed** from page 1 of the PDF (arXiv:2606.21438v1). The `% VERIFY`
marker on this entry in `docs/paper/references.bib` can be removed once this is folded
back in.

```bibtex
@article{tlsynthesis2026survey,
  title        = {Temporal Logics and Formal Synthesis for Robot Planning and
                  Control},
  author       = {Tumova, Jana and Verhagen, Joris and Vahs, Matti},
  journal      = {arXiv preprint arXiv:2606.21438},
  year         = {2026},
  month        = jun,
  eprint       = {2606.21438},
  archivePrefix= {arXiv},
  primaryClass = {cs.RO}
}
```

## What was verified, and how

| field | value | source |
|---|---|---|
| title | Temporal logics and formal synthesis for robot planning and control | PDF title page |
| authors | Jana Tumova; Joris Verhagen; Matti Vahs — **in that order** | PDF title page |
| affiliation | KTH Royal Institute of Technology (all three) | PDF title page |
| emails | `tumova@kth.se`, `jorisv@kth.se`, `vahs@kth.se` | PDF title page |
| arXiv ID / version | 2606.21438**v1** | stamp in the PDF left margin, p. 1 |
| category | cs.RO | same stamp |
| date | 19 Jun 2026 | same stamp |
| funding | WASP (Knut and Alice Wallenberg Foundation); Wenner-Gren Foundations | Acknowledgement section |

The margin stamp reads verbatim: `arXiv:2606.21438v1 [cs.RO] 19 Jun 2026`.

## Journal version

**Not verified — no venue could be confirmed.**

- No journal reference, DOI, venue footer, copyright line or "to appear" note appears
  anywhere in the PDF, including the title page and the acknowledgement.
- arXiv.org and alphaxiv.org are both blocked by this environment's egress proxy, so the
  arXiv `comments` and `journal-ref` metadata fields could not be read. This is the one
  check still outstanding.
- Circumstantial evidence that a venue is intended: the document calls itself a
  "manuscript" five times (never a "survey" or "paper"), opens with an explicit
  **Objectives** bullet list, carries worked Examples and per-section **Main takeaways**
  boxes, and its own citations include two Annual Review articles of the same shape (Belta
  & Sadraddini 2019; Kress-Gazit, Lahijanian & Raman 2018). That structure is typical of a
  book chapter or an Annual-Review-style tutorial article. **This is inference, not
  evidence — do not put a venue in the entry on the strength of it.**

**Action before submission:** re-check `https://arxiv.org/abs/2606.21438` from an
unrestricted network for a `journal-ref` / DOI. If one exists, switch to `@article` with
`journal`/`volume`/`pages` or to `@incollection`, and cite the venue version — a
peer-reviewed citation is worth more against a formal-methods reviewer than an arXiv
preprint.

## Companion entries to add

These are the six works recommended in `summary.md` §4.3. They are **not yet verified**
beyond what the manuscript's own bibliography states, so each is marked. Verify author
lists and page numbers before folding into `references.bib`.

```bibtex
% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@misc{wang2025conformalnl2ltl,
  title        = {{ConformalNL2LTL}: Translating Natural Language Instructions into
                  Temporal Logic Formulas with Conformal Correctness Guarantees},
  author       = {Wang, Jun and Sundarsingh, David Smith and
                  Deshmukh, Jyotirmoy V. and Kantaros, Yiannis},
  year         = {2025},
  eprint       = {2504.21022},
  archivePrefix= {arXiv},
  note         = {\url{https://arxiv.org/abs/2504.21022}}
}

% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@inproceedings{maler2004monitoring,
  title        = {Monitoring Temporal Properties of Continuous Signals},
  author       = {Maler, Oded and Nickovic, Dejan},
  booktitle    = {Formal Techniques, Modelling and Analysis of Timed and
                  Fault-Tolerant Systems (FORMATS/FTRTFT)},
  pages        = {152--166},
  year         = {2004},
  publisher    = {Springer}
}

% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@inproceedings{yang2024safetychip,
  title        = {Plug in the Safety Chip: Enforcing Constraints for
                  {LLM}-driven Robot Agents},
  author       = {Yang, Ziyi and Raman, Shreyas S. and Shah, Ankit and
                  Tellex, Stefanie},
  booktitle    = {IEEE International Conference on Robotics and Automation (ICRA)},
  pages        = {14435--14442},
  year         = {2024}
}

% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@inproceedings{fainekos2011revising,
  title        = {Revising Temporal Logic Specifications for Motion Planning},
  author       = {Fainekos, Georgios E.},
  booktitle    = {IEEE International Conference on Robotics and Automation (ICRA)},
  pages        = {40--45},
  year         = {2011}
}

% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@inproceedings{shah2018bayesian,
  title        = {Bayesian Inference of Temporal Task Specifications from
                  Demonstrations},
  author       = {Shah, Ankit and Kamath, Pritish and Shah, Julie A. and Li, Shen},
  booktitle    = {Advances in Neural Information Processing Systems},
  volume       = {31},
  year         = {2018},
  publisher    = {Curran Associates, Inc.}
}

% VERIFY — transcribed from the bibliography of arXiv:2606.21438; not independently checked.
@article{kressgazit2018synthesis,
  title        = {Synthesis for Robots: Guarantees and Feedback for Robot Behavior},
  author       = {Kress-Gazit, Hadas and Lahijanian, Morteza and Raman, Vasumathi},
  journal      = {Annual Review of Control, Robotics, and Autonomous Systems},
  volume       = {1},
  pages        = {211--236},
  year         = {2018}
}
```

Note: `yang2024safetychip` shares an author (Tellex) and a first-name collision with
`liu2023lang2ltl` (Ziyi Yang appears in both author lists) — this is the same person, not a
transcription error.
