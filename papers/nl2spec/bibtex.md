# nl2spec — verified BibTeX

## Entry

```bibtex
@inproceedings{cosler2023nl2spec,
  title        = {nl2spec: Interactively Translating Unstructured Natural Language
                  to Temporal Logics with Large Language Models},
  author       = {Cosler, Matthias and Hahn, Christopher and Mendoza, Daniel and
                  Schmitt, Frederik and Trippel, Caroline},
  booktitle    = {Computer Aided Verification (CAV 2023)},
  series       = {Lecture Notes in Computer Science},
  volume       = {13965},
  pages        = {383--396},
  year         = {2023},
  publisher    = {Springer},
  address      = {Cham},
  doi          = {10.1007/978-3-031-37703-7\_18},
  note         = {Preprint: arXiv:2303.04864}
}
```

Drop-in replacement for the current `cosler2023nl2spec` entry in `docs/paper/references.bib`
(lines 74–84). The existing entry is **correct** — author list, page range, year, publisher and
DOI all check out. This version adds `series`, `volume`, `address` and the arXiv note, and escapes
the underscore in the DOI.

If a separate preprint citation is ever wanted:

```bibtex
@misc{cosler2023nl2spec-arxiv,
  title         = {nl2spec: Interactively Translating Unstructured Natural Language
                   to Temporal Logics with Large Language Models},
  author        = {Cosler, Matthias and Hahn, Christopher and Mendoza, Daniel and
                   Schmitt, Frederik and Trippel, Caroline},
  year          = {2023},
  eprint        = {2303.04864},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LO}
}
```

Do not cite both in the same paper — cite the CAV version.

---

## Verification log

| field | value | how verified |
|---|---|---|
| Authors | Matthias Cosler, Christopher Hahn, Daniel Mendoza, Frederik Schmitt, Caroline Trippel | **Read off the PDF title page** (arXiv v1 p. 1). Affiliations: Cosler and Schmitt — CISPA Helmholtz Center for Information Security, Saarbrücken; Hahn, Mendoza and Trippel — Stanford University. Author order confirmed. This resolves the `% VERIFY` marker: the author list in `references.bib` was already right. |
| Title | exactly as above, lowercase `nl2spec` | PDF title page. Keep the braces off `nl2spec` only if your `.bst` does not case-fold titles; if it does, brace it as `{nl2spec}`. The current `references.bib` entry does not brace it — check the rendered output once. |
| Year | 2023 | PDF; Springer listing |
| DOI | `10.1007/978-3-031-37703-7_18` | **Confirmed.** Web search returns `https://link.springer.com/chapter/10.1007/978-3-031-37703-7_18` titled "nl2spec: Interactively Translating Unstructured Natural Language ..." — DOI and title match. The DOI inherited from another paper's reference list is correct. |
| Pages | 383–396 | Confirmed via search result metadata for the Springer chapter page. **Not** read off the camera-ready PDF (`link.springer.com` is egress-blocked here), so this is second-hand but consistent across sources. |
| Series / volume | LNCS 13965 | Confirmed: ISBN prefix `978-3-031-37703-7` = LNCS 13965, CAV 2023 **Part II** ("Decision procedures; model checking; neural networks and machine learning"). |
| Proceedings | *Computer Aided Verification: 35th International Conference, CAV 2023, Paris, France, July 17–22, 2023, Proceedings, Part II* | Springer/ACM book-level listings. Editors: **Constantin Enea** (LIX, École Polytechnique, CNRS / Institut Polytechnique de Paris) and **Akash Lal** (Microsoft Research, Bangalore). 67 full papers selected from 261 submissions across the three-volume set (13964/13965/13966). Add `editor = {Enea, Constantin and Lal, Akash}` if the style file wants it. |
| Open access | The CAV 2023 proceedings set is open access | Stated on the OAPEN and Springer book listings. Not independently confirmed for this specific chapter. |
| arXiv ID | **2303.04864** | Confirmed two ways: `arxiv.org/abs/2303.04864` returned by web search with matching title/authors, and the preprint's own left-margin stamp, `arXiv:2303.04864v1 [cs.LO] 8 Mar 2023`, visible in the retrieved page 1. Primary class `cs.LO`. |
| arXiv version | v1, 8 Mar 2023 | The alphaXiv tool resolved to `2303.04864v1`, which is evidence v1 is what is indexed. **Whether a v2 exists is not verified** — `arxiv.org` is egress-blocked in this environment, so the listing page could not be opened. If it matters, check `arxiv.org/abs/2303.04864` directly. |
| Code | `https://github.com/realChrisHahn2/nl2spec` | Given in the paper itself, arXiv v1 p. 3, footnote 3. Repository not visited; liveness not verified. |
| Conference dates | Paris, France, July 17–22, 2023 | From the proceedings' own subtitle as reported by multiple retailer/library listings. Consistent across sources but not read off a Springer page directly. |

## What was tried and blocked

Egress-blocked by the proxy in this environment, all returning `EGRESS_BLOCKED`:
`link.springer.com`, `dl.acm.org`, `dblp.org` (API), `arxiv.org`, `api.crossref.org`,
`api.semanticscholar.org`, `cs.stanford.edu` (Trippel's CV). `curl` to Crossref and Semantic
Scholar failed with `CONNECT tunnel failed, response 403`.

What worked: `mcp__alphaXiv__answer_pdf_queries` (returned the preprint's full text, which is the
source for author list, title, arXiv ID and the paper's own footnotes) and `WebSearch` (which
returned the Springer chapter URL, the page range, the LNCS volume and the editors).

**Nothing in the entry above is guessed.** The two fields resting on search-result metadata rather
than on a primary document are `pages` and the conference dates; both are marked as such in the
table.
