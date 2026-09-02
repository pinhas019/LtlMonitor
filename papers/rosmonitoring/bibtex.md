# BibTeX — ROSMonitoring

## Primary entry — the venue version (TAROS 2020)

Author list **verified**. Use this key: `ferrando2020rosmonitoring`.

```bibtex
@inproceedings{ferrando2020rosmonitoring,
  author       = {Angelo Ferrando and
                  Rafael C. Cardoso and
                  Michael Fisher and
                  Davide Ancona and
                  Luca Franceschini and
                  Viviana Mascardi},
  editor       = {Abdelkhalick Mohammad and
                  Xin Dong and
                  Matteo Russo},
  title        = {{ROSMonitoring}: {A} Runtime Verification Framework for {ROS}},
  booktitle    = {Towards Autonomous Robotic Systems - 21st Annual Conference, {TAROS}
                  2020, Nottingham, UK, September 16, 2020, Proceedings},
  series       = {Lecture Notes in Computer Science},
  volume       = {12228},
  pages        = {387--399},
  publisher    = {Springer},
  year         = {2020},
  doi          = {10.1007/978-3-030-63486-5\_40},
  url          = {https://doi.org/10.1007/978-3-030-63486-5\_40}
}
```

DBLP record key: `DBLP:conf/taros/FerrandoC0AFM20`
(`https://dblp.org/rec/conf/taros/FerrandoC0AFM20.bib`).

## Successor — cite this too if you mention services, ordering, or ROS2

The FMAS 2024 (EPTCS) version is the venue version; arXiv:2411.14367 is the same paper.
Suggested key: `saadat2024rosmonitoring2`.

```bibtex
@inproceedings{saadat2024rosmonitoring2,
  author       = {Maryam Ghaffari Saadat and
                  Angelo Ferrando and
                  Louise A. Dennis and
                  Michael Fisher},
  editor       = {Matt Luckcuck and
                  Mengwei Xu},
  title        = {{ROSMonitoring} 2.0: Extending {ROS} Runtime Verification to Services
                  and Ordered Topics},
  booktitle    = {Proceedings Sixth International Workshop on Formal Methods for Autonomous
                  Systems, {FMAS@iFM} 2024, Manchester, UK, 11th and 12th of November
                  2024},
  series       = {{EPTCS}},
  volume       = {411},
  pages        = {38--55},
  year         = {2024},
  doi          = {10.4204/EPTCS.411.3},
  url          = {https://doi.org/10.4204/EPTCS.411.3}
}
```

## How the author lists were verified

**dblp.org and dblp.uni-trier.de are blocked by this environment's egress proxy**, as are
`link.springer.com`, `dl.acm.org`, `semanticscholar.org`, `researchgate.net` and
`research.manchester.ac.uk`. The entries above were therefore assembled from three
independent sources that *were* readable, and cross-checked field by field. They agree
completely.

1. **Reference [15] of the ROSMonitoring 2.0 paper** — read verbatim from the FMAS 2024 PDF:
   > Angelo Ferrando, Rafael C. Cardoso, Michael Fisher, Davide Ancona, Luca Franceschini &
   > Viviana Mascardi (2020): *ROSMonitoring: A Runtime Verification Framework for ROS.*
   > In Abdelkhalick Mohammad, Xin Dong & Matteo Russo, editors: Proc. 21st Annual Conference
   > on Towards Autonomous Robotic Systems (TAROS), Lecture Notes in Computer Science 12228,
   > Springer, pp. 387–399. `https://doi.org/10.1007/978-3-030-63486-5_40`

2. **Reference [12] of Varanus** (Luckcuck, Ferrando & Faruq, arXiv:2506.14426) — read
   verbatim. Identical author order, editors, volume, pages, publisher, year.

3. **The DBLP-exported BibTeX in the official repository's README**
   (`github.com/autonomy-and-verification-uol/ROSMonitoring`, `master`, read directly). It
   carries the DBLP `biburl`/`bibsource`/`timestamp` fields and matches (1) and (2) exactly.
   This is a DBLP *export* recovered from the authors' own repo, not a DBLP page I loaded.

The 2.0 entry's bibliographic data comes from the **PDF's own title block** — "Matt Luckcuck
and Mengwei Xu (Eds.): Sixth International Workshop on Formal Methods for Autonomous Systems
(FMAS 2024), EPTCS 411, 2024, pp. 38–55, doi:10.4204/EPTCS.411.3" — plus the author block
listing Maryam Ghaffari Saadat (University of Manchester), Angelo Ferrando (University of
Modena and Reggio Emilia), Louise A. Dennis (Manchester) and Michael Fisher (Manchester).
The repo README's DBLP export for it is filed under the `journals/corr` key
(`DBLP:journals/corr/abs-2411-14367`) even though its fields describe the FMAS proceedings;
the entry above uses `@inproceedings` with the venue data, which is what you want to cite.

**Not verified:** nothing in either entry is unconfirmed. The one field I would not assert
beyond what is above is the FMAS 2024 DBLP conference key, since DBLP was unreachable — if you
need the exact `DBLP:conf/fmas/...` key, look it up when you have network access to dblp.org.

## Code artefact

If you cite the implementation as well as the papers:

- `https://github.com/autonomy-and-verification-uol/ROSMonitoring` — MIT licence.
- `master` was rewritten **29 June 2026** (commit `6ab3032`, "New ROSMonitoring integrating
  ROS1, ROS2, services, and ordering"; HEAD `d03aa5b`), declaring package version **3.0.0**.
  The pre-rewrite ROS1 line lives on the `ros1_legacy` branch.
- **Pin a commit SHA** in any artefact description — `master` is three commits deep and the
  history was squashed.
