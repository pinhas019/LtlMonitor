# BibTeX — Bauer, Leucker & Schallhart, TOSEM 2011

## Primary entry (venue version, not the preprint)

```bibtex
@article{BauerLeuckerSchallhart2011,
  author     = {Bauer, Andreas and Leucker, Martin and Schallhart, Christian},
  title      = {Runtime Verification for {LTL} and {TLTL}},
  journal    = {ACM Transactions on Software Engineering and Methodology},
  volume     = {20},
  number     = {4},
  articleno  = {14},
  pages      = {14:1--14:64},
  numpages   = {64},
  year       = {2011},
  month      = sep,
  issn       = {1049-331X},
  publisher  = {Association for Computing Machinery},
  address    = {New York, NY, USA},
  doi        = {10.1145/2000799.2000800}
}
```

Short form for a venue with a compressed bibliography:

```bibtex
@article{BauerLeuckerSchallhart2011,
  author  = {Bauer, Andreas and Leucker, Martin and Schallhart, Christian},
  title   = {Runtime Verification for {LTL} and {TLTL}},
  journal = {ACM Trans. Softw. Eng. Methodol.},
  volume  = {20},
  number  = {4},
  pages   = {14:1--14:64},
  year    = {2011},
  doi     = {10.1145/2000799.2000800}
}
```

Note the braces around `{LTL}` and `{TLTL}` — without them BibTeX styles that lowercase titles
will render "Runtime verification for ltl and tltl".

## Verification status of each field

`dblp.org`, `dl.acm.org`, `link.springer.com`, `semanticscholar.org`, `researchgate.net` and
`arxiv.org` are **all blocked by this environment's network egress proxy**, so neither the DBLP
record `journals/tosem/BauerLS11` nor the ACM DL landing page could be opened directly. Fields
were confirmed as follows:

| Field | Value | How confirmed |
|---|---|---|
| authors | Andreas Bauer, Martin Leucker, Christian Schallhart | **Directly**, from the author manuscript I read (title page, with affiliations NICTA/ANU, TU München, TU Darmstadt) |
| title | Runtime Verification for LTL and TLTL | **Directly**, from the manuscript title page |
| journal | ACM Transactions on Software Engineering and Methodology | **Directly** (manuscript running footer) + search results |
| volume | 20 | Search snippets of the DBLP record, the ACM DL listing, and an independent reference-list citation (below) |
| number | 4 | Same three sources |
| articleno / pages | 14 / 14:1–14:64 | Independent reference-list citation read verbatim (below) + search snippets |
| numpages | 64 | Implied by `14:1--14:64`; the manuscript footer says "Pages 1–68", so the **manuscript is 68 pages and the published article is 64** — a normal typesetting difference. If you need `numpages` to be exact, check the ACM page. |
| year | 2011 | All sources agree |
| month | September | Corroborated by a scholarsportal browse listing for TOSEM v20 i4 dated September 2011. **Weakest field here.** Drop `month` if you want zero risk — no style requires it. |
| issn | 1049-331X | TOSEM's journal ISSN, confirmed by search against the journal's own listings |
| doi | 10.1145/2000799.2000800 | Appears consistently in the DBLP record snippet, the ACM DL URL, and the Lübeck publication page snippet |

**The strongest independent corroboration** is the reference list of Esparza & Fischer,
"Runtime Verification for LTL in Stochastic Systems" (arXiv:2508.07963), which I read in full
via a PDF tool. Its entry [8] reads verbatim:

> Bauer, A., Leucker, M., Schallhart, C.: Runtime verification for LTL and TLTL.
> ACM Trans. Softw. Eng. Methodol. 20(4), 14:1–14:64 (2011)

That confirms volume 20, number 4, article 14, pages 14:1–14:64, year 2011 from a peer-reviewed
source independent of the search snippets.

**What is NOT verified:** I did not see the DBLP page or the ACM DL page rendered. If your
submission checker is strict, paste `10.1145/2000799.2000800` into `doi.org` from an unblocked
machine and export the ACM BibTeX directly.

## Do not cite the preprint

The document I read is the author manuscript at

    https://www.isp.uni-luebeck.de/sites/default/files/publications/tosem09_prelim_1.pdf

It is a legitimate copy but it is **not** the version of record: its footer still reads
"Vol. x, No. y, mm 20yy", its pagination differs (68 vs 64 pages), and it contains at least one
internal inconsistency (§2.5 reports 43 non-monitorable Dwyer formulas, §3.1 reports 44) that
may or may not survive into print. Cite the TOSEM article; use the preprint only for reading.

## Related entries by the same authors, if you need the LTL₃ lineage

These are the RV-era predecessors and follow-ups. **Field values here come from the reference
list of Esparza & Fischer (arXiv:2508.07963), read verbatim, and from search snippets — I did
not open these papers.** Verify before submitting.

```bibtex
@inproceedings{BauerLeuckerSchallhart2006,
  author    = {Bauer, Andreas and Leucker, Martin and Schallhart, Christian},
  title     = {Monitoring of Real-Time Properties},
  booktitle = {FSTTCS},
  series    = {Lecture Notes in Computer Science},
  volume    = {4337},
  pages     = {260--272},
  publisher = {Springer},
  year      = {2006}
}
```

This is the conference precursor. The TOSEM manuscript's own front matter states: "This is a
revised and extended version of [Bauer et al. 2006b] appeared at FSTTCS 2006 in Kolkata,
India." **Verified directly from the paper I read.**

```bibtex
@inproceedings{BauerLeuckerSchallhart2007,
  author    = {Bauer, Andreas and Leucker, Martin and Schallhart, Christian},
  title     = {The Good, the Bad, and the Ugly, But How Ugly Is Ugly?},
  booktitle = {RV},
  series    = {Lecture Notes in Computer Science},
  volume    = {4839},
  pages     = {126--138},
  publisher = {Springer},
  year      = {2007}
}
```

The four-valued **RV-LTL** paper — adds *presumably true* / *presumably false* to split LTL₃'s
`?`. Cite this if you need to explain why `UNDECIDED` must not be a fourth `MonitorStatus`
member: the field's existing fourth value means something else. The TOSEM manuscript itself
points at it (p. 21, as "[Bauer et al. 2007]") and calls it out of scope.

```bibtex
@article{BauerLeuckerSchallhart2010,
  author  = {Bauer, Andreas and Leucker, Martin and Schallhart, Christian},
  title   = {Comparing {LTL} Semantics for Runtime Verification},
  journal = {Journal of Logic and Computation},
  volume  = {20},
  number  = {3},
  pages   = {651--674},
  year    = {2010},
  doi     = {10.1093/logcom/exn075}
}
```

Volume/number/pages/DOI from the Esparza & Fischer reference list plus a search snippet of the
ACM DL record for `10.1093/logcom/exn075`. Referred to in the TOSEM manuscript as
"[Bauer et al. 2008]" (the manuscript predates the journal's final year).
