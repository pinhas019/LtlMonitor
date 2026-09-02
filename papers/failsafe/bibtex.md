# BibTeX — FailSafe

## Author list (verified)

Zijun Lin¹⁻², Jiafei Duan³⁻⁴, Haoquan Fang³⁻⁴, Dieter Fox³⁻⁴, Ranjay Krishna³⁻⁴,
Cheston Tan², Bihan Wen¹

1. Nanyang Technological University
2. Centre for Frontier AI Research (CFAR), A*STAR
3. Allen Institute for AI
4. University of Washington

Order and affiliation superscripts read directly off p.1 of the retrieved PDF, and independently
corroborated by two web searches returning the same seven names in the same order. The brief's
listed institutions (UW / NTU / AI2 / CFAR A*STAR) are all correct.

## arXiv entry

```bibtex
@misc{lin2025failsafe,
  title         = {FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models},
  author        = {Lin, Zijun and Duan, Jiafei and Fang, Haoquan and Fox, Dieter and
                   Krishna, Ranjay and Tan, Cheston and Wen, Bihan},
  year          = {2025},
  eprint        = {2510.01642},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO},
  url           = {https://arxiv.org/abs/2510.01642},
  note          = {Project page: https://jimntu.github.io/FailSafe/}
}
```

## Version and venue notes

- **Versions.** The PDF retrieved for the summary is **v4**, whose page-1 stamp reads
  `arXiv:2510.01642v4 [cs.RO] 7 Jul 2026`. This is directly verified from the document itself.
  Web search reports v1 as 2 Oct 2025 and v4 as the latest revision (7 Jul 2026); the v1 date is
  consistent with the arXiv ID (2510 = October 2025) but was **not** verified directly, since
  `arxiv.org`, `alphaxiv.org` and `semanticscholar.org` are all blocked by this environment's
  egress proxy.

- **Venue — reported, NOT directly verified.** Two independent web searches reported the paper as
  **accepted to IROS 2026**. I was unable to confirm this against the arXiv abstract page's
  `Comments:` field or any publisher record (egress blocked), and the PDF itself carries **no venue
  header** — p.1 shows only the arXiv stamp. Treat "IROS 2026" as likely but unconfirmed; check the
  arXiv abstract page before citing it as published. If confirmed, the entry becomes:

```bibtex
@inproceedings{lin2026failsafe,
  title     = {FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models},
  author    = {Lin, Zijun and Duan, Jiafei and Fang, Haoquan and Fox, Dieter and
               Krishna, Ranjay and Tan, Cheston and Wen, Bihan},
  booktitle = {IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)},
  year      = {2026},
  note      = {VENUE NOT VERIFIED -- confirm against arXiv:2510.01642 Comments field before use}
}
```

  DOI, pages, and publisher: **not verified** (no record retrievable from this environment).

- **Code/data release.** The paper states "We plan to release the FailSafe code to the community"
  (p.1) and gives the project page `https://jimntu.github.io/FailSafe/`. Whether code or the 131k-pair
  dataset is actually available is **not verified** — the project page was not reachable.

## Citation hygiene note

Until the venue is confirmed, cite the arXiv `@misc` form. If your bibliography style renders the
year from the eprint, note the mismatch: the ID and v1 are 2025, but the current revision is 2026.
