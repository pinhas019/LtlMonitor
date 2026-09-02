# BibTeX — Safe-ROS

Citation key used across this repo: **`saferos2025`**
(`papers/README.md` item 11; `docs/paper/references.bib` carries a `% VERIFY` marker for it).

## Verification status

| field | status | source |
|---|---|---|
| title | **verified** | title page of the arXiv v1 PDF |
| author list (3 authors, order) | **verified** | title page + running header `D.C. Benjumea, M. Farrell & L.A. Dennis` |
| affiliation | **verified** — all three at University of Manchester, Manchester, UK | title page |
| venue | **verified** — FMAS 2025 (7th Intl. Workshop on Formal Methods for Autonomous Systems) | EPTCS front matter on the title page |
| series / volume / pages | **verified** — EPTCS 436, 2025, pp. 48–68 | EPTCS front matter |
| DOI | **verified** — `10.4204/EPTCS.436.6` | EPTCS front matter |
| editors | **verified** — Matt Luckcuck, Maike Schwammberger, Mengwei Xu | EPTCS front matter |
| arXiv ID | **verified** — `2511.14433`, version `v1` | resolved by the PDF-query tool as `2511.14433v1` |
| arXiv submission date | **NOT VERIFIED** — November 2025 inferred from the `2511` identifier only. `arxiv.org` and `www.alphaxiv.org` are both blocked by this session's egress proxy, so the day-of-month could not be confirmed. | — |
| primary arXiv category | **NOT VERIFIED** — a web search surfaced the paper under an arXiv `cs.RO` recent-listing page, which is suggestive but not the abstract page. Do not print `eprintclass` without checking. | — |
| licence | **verified** — Creative Commons Attribution | title page |
| code | **verified as stated in the paper** — `https://github.com/dianabenjumea/Safe-ROS` (pp. 52, 63). Repository not opened. | — |
| funding | **verified** — University of Manchester; EPSRC CRADLE project, grant EP/X02489X/1; Royal Academy of Engineering; a Fellowship at RAICo | acknowledgements, p. 63 |

Note on the first author's name: the title page prints **"Diana C. Benjumea"**, while the
e-mail address is `diana.benjumeahernandez@manchester.ac.uk` and the copyright line reads
"D.C. Benjumea". Her single-author RE 2024 paper (reference [6] in this paper) is credited
to "Diana C Benjumea". **Use `Benjumea, Diana C.`** — that is what the paper itself prints.

---

## Preferred entry — the published (EPTCS) version

Cite this one. It is peer-reviewed, has a DOI, and page numbers.

```bibtex
@inproceedings{saferos2025,
  author    = {Benjumea, Diana C. and Farrell, Marie and Dennis, Louise A.},
  title     = {{Safe-ROS}: An Architecture for Autonomous Robots in
               Safety-Critical Domains},
  booktitle = {Proceedings of the Seventh International Workshop on Formal
               Methods for Autonomous Systems ({FMAS} 2025)},
  editor    = {Luckcuck, Matt and Schwammberger, Maike and Xu, Mengwei},
  series    = {Electronic Proceedings in Theoretical Computer Science},
  volume    = {436},
  pages     = {48--68},
  year      = {2025},
  publisher = {Open Publishing Association},
  doi       = {10.4204/EPTCS.436.6},
  eprint    = {2511.14433},
  archivePrefix = {arXiv}
}
```

## Alternative entry — the arXiv preprint

Use only if the bibliography style in use cannot render `@inproceedings` with EPTCS fields.
The `month` field is deliberately omitted rather than guessed.

```bibtex
@misc{saferos2025arxiv,
  author        = {Benjumea, Diana C. and Farrell, Marie and Dennis, Louise A.},
  title         = {{Safe-ROS}: An Architecture for Autonomous Robots in
                   Safety-Critical Domains},
  year          = {2025},
  eprint        = {2511.14433},
  archivePrefix = {arXiv},
  note          = {EPTCS 436, pp. 48--68, doi:10.4204/EPTCS.436.6},
  doi           = {10.4204/EPTCS.436.6}
}
```

## Fields deliberately left out

- `month` — the submission day/month is not verified (see table above). `2511` implies
  November 2025, but that is an inference from the identifier, not a read of the record.
- `primaryClass` / `eprintclass` — not verified.
- `url` — an `arxiv.org/abs/2511.14433` URL was never successfully fetched from this
  session. The DOI is sufficient and is verified.

## To fold back into `docs/paper/references.bib`

Replace the `% VERIFY`-marked `saferos2025` stub with the **preferred entry** above.
The author list is now confirmed and the `% VERIFY` marker can be dropped for this entry.
