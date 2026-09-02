# BibTeX — Semantics for Linear-time Temporal Logic with Finite Observations

**A peer-reviewed version exists. Cite it, not the arXiv preprint.**

## Primary entry — the EXPRESS/SOS 2024 proceedings version (use this one)

```bibtex
@inproceedings{amjad2024ltlfiniteobs,
  title     = {Semantics for Linear-time Temporal Logic with Finite Observations},
  author    = {Rayhana Amjad and Rob van Glabbeek and Liam O'Connor},
  editor    = {Georgiana Caltais and Cinzia Di Giusto},
  booktitle = {Proceedings Combined 31st International Workshop on Expressiveness
               in Concurrency and 21st Workshop on Structural Operational Semantics
               (EXPRESS/SOS 2024)},
  series    = {Electronic Proceedings in Theoretical Computer Science},
  volume    = {412},
  pages     = {35--50},
  publisher = {Open Publishing Association},
  year      = {2024},
  doi       = {10.4204/EPTCS.412.4},
  url       = {https://doi.org/10.4204/EPTCS.412.4}
}
```

The repo's `docs/paper/references.bib` currently keys this as `ltlfiniteobs2024`. If you keep that
key, just swap the body in; if you adopt `amjad2024ltlfiniteobs`, update `papers/README.md` row 14.

## Alternative — arXiv preprint (only if you need the eprint field)

```bibtex
@misc{amjad2024ltlfiniteobs-arxiv,
  title         = {Semantics for Linear-time Temporal Logic with Finite Observations},
  author        = {Rayhana Amjad and Rob van Glabbeek and Liam O'Connor},
  year          = {2024},
  month         = nov,
  eprint        = {2411.14581},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LO},
  note          = {Published version: EPTCS 412, pp. 35--50, \doi{10.4204/EPTCS.412.4}},
  url           = {https://arxiv.org/abs/2411.14581}
}
```

## Companion — the extended successor paper

`arXiv:2608.23096` contains 2411.14581 as a proper part (its own reference [12] calls the
conference paper "an extended abstract of (part of) this paper") and adds the monitorability
hierarchy, the guarantee kernel, and the topological re-proof of Alpern & Schneider. Cite it for
anything about monitorability classes or safety/liveness.

```bibtex
@misc{amjad2026infinitefinite,
  title         = {The Infinite, in Finite Time},
  author        = {Rayhana Amjad and Rob van Glabbeek and Liam O'Connor},
  year          = {2026},
  month         = aug,
  eprint        = {2608.23096},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LO},
  url           = {https://arxiv.org/abs/2608.23096}
}
```

## Mechanisation — the Isabelle/HOL development

Cited by the paper itself as `[AGO24]`. Worth citing if you lean on Theorem 11.

```bibtex
@article{amjad2024ltl3afp,
  title   = {Definitive Set Semantics for {LTL3}},
  author  = {Rayhana Amjad and Rob van Glabbeek and Liam O'Connor},
  journal = {Archive of Formal Proofs},
  year    = {2024},
  note    = {Formal proof development},
  url     = {https://isa-afp.org/entries/LTL3_Semantics.html}
}
```

---

## Verification note

**Verified directly off page 1 of the arXiv PDF** (paper `2411.14581`, via
`mcp__alphaXiv__answer_pdf_queries`), which carries the EPTCS masthead:

- Title: *Semantics for Linear-time Temporal Logic with Finite Observations*
- **Full author list, in order: Rayhana Amjad, Rob van Glabbeek, Liam O'Connor.**
  Running head on every subsequent page: "R.Y. Amjad, R.J. van Glabbeek & L. O'Connor".
- Affiliations and contact addresses as printed:
  Rayhana Amjad — University of Edinburgh, Edinburgh, Scotland, `rayhana.amjad@ed.ac.uk`;
  Rob van Glabbeek — University of Edinburgh, Edinburgh, Scotland, `rvg@cs.stanford.edu`;
  Liam O'Connor — Australian National University, Canberra, Australia, `liam.oconnor@anu.edu.au`.
- Masthead: "G. Caltais and C. Di Giusto (Eds.): EXPRESS/SOS 2024 — EPTCS 412, 2024, pp. 35–50,
  doi:10.4204/EPTCS.412.4". Licence: Creative Commons Attribution.
- Editors' initials expanded to **Georgiana Caltais** and **Cinzia Di Giusto** from the EXPRESS/SOS
  2024 volume; the paper prints only "G. Caltais and C. Di Giusto".
- Workshop location/date **Calgary, Canada, 9th September 2024** and the publisher **Open Publishing
  Association** are taken verbatim from reference [12] of arXiv:2608.23096, which cites this paper
  in full.

**Independently corroborated** by a web search returning the arXiv listing, the Edinburgh Research
Explorer record, and ResearchGate, all agreeing on the three authors, the EPTCS 412 volume, pages
35–50, and DOI `10.4204/EPTCS.412.4`.

**Successor paper verified** off page 1 of arXiv:2608.23096: same three authors; affiliations
`a` University of Edinburgh, `b` Australian National University, `c` University of New South Wales
(van Glabbeek carries `a` and `c`, O'Connor carries `b` and `a`); footnote "Supported by Royal
Society Wolfson Fellowship RSWF\R1\221008"; arXiv stamp `arXiv:2608.23096v1 [cs.LO] 24 Aug 2026`.

### Not verified

- **arXiv metadata pages could not be fetched** — `arxiv.org` and `dblp.org` both return
  `EGRESS_BLOCKED` from this environment's proxy. So: the arXiv **submission date** (the search
  result reported "published November 20, 2024" and EPTCS online publication "November 22, 2024" —
  these disagree by two days and **neither was confirmed against a metadata record**), the
  **cross-list categories**, the `comments` field, and any **v2** revision are unconfirmed.
  `month = nov, year = 2024` in the arXiv entry rests on the arXiv ID `2411.*` prefix plus the
  search result, not on a metadata record.
- **`primaryClass = {cs.LO}`** for 2411.14581 is an **inference** — it was not read off the PDF.
  It *was* read off page 1 of the successor (2608.23096), so cs.LO is near-certain for the
  preprint too, but treat it as unconfirmed. It does not appear in the primary `@inproceedings`
  entry, so this only affects the optional arXiv entry.
- **The AFP entry's exact citation form** (its canonical AFP author field, submission date, and
  whether AFP prefers `@article` with `journal = {Archive of Formal Proofs}`) was **not** checked
  against `isa-afp.org` — the entry above reproduces the paper's own reference `[AGO24]` and the
  URL printed there. AFP publishes a canonical BibTeX snippet on each entry page; prefer that if
  you can reach it. Note also that 2608.23096 ref [11] flags the AFP entry as "not yet up to date
  with the repository linked above".
- **2608.23096 has no stated venue.** It reads as a journal submission (numbered sections,
  keywords list, Elsevier-style numeric citations), but **no journal is named in the retrieved
  text**. Do not assert one. Its arXiv date (24 Aug 2026) is read off the page-1 stamp and is
  reliable.
- The GitHub repository `https://github.com/rayhanayasmin/the_infinite_in_finite_time` is quoted
  from reference [10] of 2608.23096. It was **not visited** from this environment.
