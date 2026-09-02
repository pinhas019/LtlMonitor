# BibTeX — Multi-Property Temporal Logic Monitoring

Key: `multiproperty2026` (matches `papers/README.md` row 20 and `docs/paper/references.bib`).

## Author list: RESOLVED

The `% VERIFY` marker can be removed. The author list is confirmed from **two independent
sources**:

1. The byline on page 1 of the PDF itself (retrieved 2026-09-02):
   - **Arınç Demir** — Boğaziçi University, Istanbul, Türkiye — `arinc.demir@std.bogazici.edu.tr`
   - **Dogan Ulus** — Boğaziçi University, Istanbul, Türkiye — `dogan.ulus@bogazici.edu.tr`
2. The arXiv listing for 2605.13668, which gives the same two authors in the same order.

Order is Demir, then Ulus. The `std.` in the first author's address is Boğaziçi's student
subdomain, consistent with a student first author and Ulus as supervising author. Ulus is also
the sole author of both the construction this paper extends (ref. [3], LMCS 2026) and the
baseline it is measured against (Reelay, ref. [4], arXiv:2604.22384 — see `papers/reelay/`).

**Diacritic note.** The PDF preserves Turkish diacritics elsewhere on the page ("Arınç",
"Boğaziçi", "Türkiye"), and the second author's given name is nevertheless printed as
**"Dogan"**, without the breve. The entry below reproduces the byline as printed. If you prefer
the author's usual rendering, "Doğan Ulus" (`Do\u{g}an Ulus`) is how he appears in his other
publications — but that spelling is *not* what this paper's byline shows, so it is a
substitution, not a correction.

## Primary entry (use this one — every field verified against the PDF)

```bibtex
@misc{multiproperty2026,
  title        = {Multi-Property Temporal Logic Monitoring},
  author       = {Ar{\i}n\c{c} Demir and Dogan Ulus},
  year         = {2026},
  month        = may,
  eprint       = {2605.13668},
  archivePrefix = {arXiv},
  primaryClass = {cs.LO},
  url          = {https://arxiv.org/abs/2605.13668},
  note         = {arXiv:2605.13668v1, 13 May 2026}
}
```

## Venue entry (only if you can confirm the proceedings details yourself)

Page 1 of the preprint carries the running header **"Formal Methods in Computer-Aided Design
2026"**, the FMCAD proceedings CC-BY-4.0 licence line, and an **empty** `https://doi.org/`
field — i.e. it is typeset in the FMCAD camera-ready template with the DOI not yet assigned.
That is strong evidence of acceptance at FMCAD 2026, but it is **not** confirmation that the
proceedings have appeared, and the pages, DOI, editors and publisher are **not verified**.

```bibtex
@inproceedings{multiproperty2026,
  title     = {Multi-Property Temporal Logic Monitoring},
  author    = {Ar{\i}n\c{c} Demir and Dogan Ulus},
  booktitle = {Formal Methods in Computer-Aided Design (FMCAD)},
  year      = {2026}
  % VERIFY pages     — not verified
  % VERIFY doi       — not verified (blank in the preprint)
  % VERIFY publisher — not verified
  % VERIFY editor    — not verified
  % VERIFY series/volume — not verified
}
```

Prefer the `@misc` arXiv entry unless and until the FMCAD 2026 proceedings entry can be checked
against the published table of contents.

## Verified metadata

| Field | Value | Source |
|---|---|---|
| Title | Multi-Property Temporal Logic Monitoring | PDF p. 1; arXiv listing |
| Authors | Arınç Demir; Dogan Ulus (in that order) | PDF byline; arXiv listing |
| Affiliation (both) | Boğaziçi University, Istanbul, Türkiye | PDF byline |
| arXiv ID | 2605.13668, version v1 | PDF footer stamp |
| Primary class | cs.LO | PDF footer stamp |
| Submission date | 13 May 2026 | PDF footer stamp; arXiv listing |
| Licence | Creative Commons Attribution 4.0 International | PDF p. 1 |
| System name | LoomRV | Abstract, §I, §IV, §VI |
| Venue header | "Formal Methods in Computer-Aided Design 2026" | PDF p. 1 running header |
| DOI | **none** — the preprint's DOI field is empty | PDF p. 1 |

## Not verified

- FMCAD 2026 acceptance status, page range, DOI, editors, publisher, series.
- Whether a version later than v1 exists.
- Whether LoomRV has a public source release (none is cited anywhere in the paper — there is no
  artefact, repository or availability statement in the text retrieved).
- ORCIDs; the exact preferred Latin transliteration of the second author's given name (see the
  diacritic note above).

*arxiv.org is blocked by this environment's egress proxy, so the arXiv abstract page could not be
fetched directly; the arXiv-side confirmation above comes from a web search result reporting the
listing's title, date and author names, which agrees with the PDF byline in every particular.*
