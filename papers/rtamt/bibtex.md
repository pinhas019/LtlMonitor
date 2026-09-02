# `rtamt2025` — verified entry

## Verification status

**Author list: RESOLVED.** Taken verbatim from page 1 of the arXiv PDF (2501.18608v1), which
carries the byline, affiliations and contact emails:

| # | author | affiliation (as printed) | email (as printed) |
|---|---|---|---|
| 1 | Tomoya Yamaguchi | TRINA, Toyota Motor NA R&D, 1555 Woodridge Ave, Ann Arbor, MI 48105, U.S. | tomoya.yamaguchi@toyota.com |
| 2 | Bardh Hoxha | TRINA, Toyota Motor NA R&D (same address) | bardh.hoxha@toyota.com |
| 3 | Dejan Ničković | AIT Austrian Institute of Technology, Giefinggasse 4, 1210 Vienna, Austria | dejan.nickovic@ait.ac.at |

The `docs/paper/references.bib` `% VERIFY` marker guessed "AIT + Toyota Motor NA R&D" —
correct, and now the order is pinned too. **Note the accent: Ničković**, not "Nickovic"
(the paper's own reference list uses the unaccented form for the same author, so either
spelling appears in the wild; use the accented form and let BibTeX handle it).

## A peer-reviewed version SUPERSEDES the preprint — cite the journal

The arXiv PDF ends with the publisher's accepted-manuscript notice, quoted verbatim:

> "This version of the article has been accepted for publication, after peer review (when
> applicable) but is not the Version of Record and does not reflect postacceptance
> improvements, or any corrections. The Version of Record is available online at:
> http://dx.doi.org/10.1007/S10009-023-00720-3"

So arXiv:2501.18608 (posted 22 Jan 2025) is the **accepted manuscript of a 2024 journal
article**, not a 2025 preprint. The Version of Record is in the *International Journal on
Software Tools for Technology Transfer* (STTT, Springer).

The paper is itself an **extended version of the conference paper**: Ničković & Yamaguchi,
"RTAMT: Online Robustness Monitors from STL", ATVA 2020, pp. 564–571,
doi:10.1007/978-3-030-59152-6_34 — note the *different and shorter author list* there. Cite
the STTT article for the tool; cite ATVA 2020 only if you specifically mean the 2020 tool
release.

**Verification of the volume/pages:** DOI `10.1007/s10009-023-00720-3` is confirmed by the
paper's own accepted-manuscript notice. Journal = STTT, **volume 26, pages 79–99, 2024** is
confirmed by two independent web lookups (Springer article page and dblp record
`journals/sttt/YamaguchiHN24`), but the publisher pages themselves were **not directly
fetchable from this environment** (egress blocked), so the volume/page data is
second-hand-but-corroborated rather than read off the publisher record. **The issue number
is NOT verified** — one lookup reported issue 1, another reported issue 5. It is omitted
from the entry below; add it only after checking the Springer page directly.

## The entry

```bibtex
@article{rtamt2025,
  title        = {{RTAMT} -- Runtime Robustness Monitors with Application to {CPS}
                  and Robotics},
  author       = {Yamaguchi, Tomoya and Hoxha, Bardh and Ni{\v{c}}kovi{\'c}, Dejan},
  journal      = {International Journal on Software Tools for Technology Transfer},
  volume       = {26},
  pages        = {79--99},
  year         = {2024},
  publisher    = {Springer},
  doi          = {10.1007/s10009-023-00720-3},
  eprint       = {2501.18608},
  archivePrefix= {arXiv},
  primaryClass = {cs.LO}
}
```

Keep the key `rtamt2025` (it is already used in `docs/paper/reading_list.md` and
`papers/README.md`), but be aware the year field is **2024** — if any prose says
"RTAMT [2025]", fix it to 2024, or let the `\cite` command render the year.

If house style forbids mixing `doi` and `eprint` in one entry, drop `eprint`/`archivePrefix`/
`primaryClass` and keep the DOI: the Version of Record is the thing to cite.

## Replaces

```bibtex
% VERIFY — author list not confirmed. AIT Austrian Institute of Technology,
% Toyota Motor NA R&D. ...
@article{rtamt2025,
  ...
  author       = {TODO},
  journal      = {arXiv preprint arXiv:2501.18608},
  year         = {2025},
  ...
}
```
at `docs/paper/references.bib:241`. The `% VERIFY` comment can be deleted; keep the
prose note about what the paper is used for if it is useful.

## Related keys this paper hands you

Worth adding to `references.bib` if the "why LTL not STL" paragraph cites them (all read off
RTAMT's own reference list, so titles/venues are verified but **author lists beyond what is
printed there are not independently checked**):

- Maler & Nickovic, "Monitoring temporal properties of continuous signals", FORMATS/FTRTFT
  2004, pp. 152–166 — the origin of STL. Cite for "STL".
- Fainekos & Pappas, "Robustness of temporal logic specifications" — the origin of spatial
  quantitative semantics.
- Donzé & Maler, "Robust satisfaction of temporal logic over real-valued signals" — spatial
  robustness for STL **plus time robustness**. Cite this, not RTAMT, for time robustness.
- Henzinger, Manna & Pnueli, "What good are digital clocks?", ICALP 1992, pp. 545–558 — the
  justification RTAMT gives for its discrete-time interpretation. **This is the citation
  `docs/clocking.md` wants.**
- Ferrère, Nickovic, Donzé, Ito & Kapinski, "Interface-aware signal temporal logic",
  HSCC 2019, pp. 57–66 — IA-STL.
- Maler, Nickovic & Pnueli, "On synthesizing controllers from bounded-response properties",
  CAV 2007, pp. 95–107, and Jakšić, Bartocci, Grosu, Kloibhofer, Nguyen & Nickovic, "From
  signal temporal logic to FPGA monitors", MEMOCODE 2015, pp. 218–227 — pastification.
- Reinbacher et al. (MLTL) and the **R2U2** tool — the three-valued synchronous/asynchronous
  observer line named in RTAMT's related work; closest prior art to our UNKNOWN/UNDECIDED
  design. *Exact citation details not extracted here.*
