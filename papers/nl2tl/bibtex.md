# BibTeX — NL2TL

Citation key used across this repo: `chen2023nl2tl`
(matches `papers/README.md` and the `% VERIFY` entry in `docs/paper/references.bib`).

## Entry

```bibtex
@inproceedings{chen2023nl2tl,
  title     = {{NL2TL}: Transforming Natural Languages to Temporal Logics using
               Large Language Models},
  author    = {Chen, Yongchao and Gandhi, Rujul and Zhang, Yang and Fan, Chuchu},
  booktitle = {Proceedings of the 2023 Conference on Empirical Methods in
               Natural Language Processing (EMNLP)},
  year      = {2023},
  note      = {arXiv:2305.07766}
}
```

If the venue cannot be confirmed before submission, fall back to the arXiv-only form,
which is fully verified:

```bibtex
@misc{chen2023nl2tl,
  title         = {{NL2TL}: Transforming Natural Languages to Temporal Logics using
                   Large Language Models},
  author        = {Chen, Yongchao and Gandhi, Rujul and Zhang, Yang and Fan, Chuchu},
  year          = {2024},
  eprint        = {2305.07766},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  note          = {arXiv:2305.07766v2, 22 Mar 2024}
}
```

## What was confirmed, and how

Source: the arXiv v2 PDF of 2305.07766, read via `mcp__alphaXiv__answer_pdf_queries`.

**Confirmed from page 1 of the PDF (the title block, verbatim):**

| field | value | affiliation as printed |
|---|---|---|
| title | NL2TL: Transforming Natural Languages to Temporal Logics using Large Language Models | — |
| author 1 | Yongchao Chen | MIT / Harvard (`ycchen98@mit.edu`) |
| author 2 | Rujul Gandhi | MIT (`rujul@mit.edu`) |
| author 3 | Yang Zhang | MIT-IBM Watson AI Lab (`Yang.Zhang2@ibm.com`) |
| author 4 | Chuchu Fan | MIT (`chuchu@mit.edu`) |

The author list is **four authors, in this order**, and matches the reading brief
("Chen, Gandhi, Zhang & Fan"). Given-name/surname split is unambiguous for all four.

**Also confirmed from the PDF:**
- arXiv identifier and version: `arXiv:2305.07766v2 [cs.CL] 22 Mar 2024` (stamped in the
  left margin of page 1). Note the v2 date is 2024, not 2023 — hence `year = {2024}` in
  the `@misc` form and `year = {2023}` in the `@inproceedings` form.
- Primary class: `cs.CL`.
- Artifact URLs stated in footnotes 1–2 on page 1:
  `https://github.com/yongchao98/NL2TL` (datasets and code) and
  `https://yongchao98.github.io/MIT-realm-NL2TL` (project page).
- Funding, from the Acknowledgements (p. 9): "supported by ONR under Award
  N00014-22-1-2478 and MIT-IBM Watson AI Lab."

**NOT verified — do not present as confirmed:**
- **Venue.** The reading brief states EMNLP 2023, and that matches the citation key
  `chen2023nl2tl`, but **the arXiv PDF pages retrieved carry no venue, proceedings, page
  range, DOI or ACL Anthology identifier**. The `@inproceedings` entry above therefore
  carries an unverified `booktitle`. Before submission, confirm against the ACL Anthology
  and add the anthology ID, pages and DOI, or use the `@misc` form.
- **Pages / anthology ID / DOI.** Not present in the source read.
- **Whether the EMNLP version is main conference or Findings.** Not determined.

## Cross-reference note for `docs/paper/references.bib`

The existing `% VERIFY` marker on this entry can be cleared **for the author list only**.
The venue line still needs an external check against the ACL Anthology; leave a narrowed
marker such as `% VERIFY venue/pages` rather than removing the marker outright.

## Numbers safe to quote from this paper

Verified from tables and prose (page numbers refer to the arXiv v2 PDF):
28K lifted NL–TL pairs, of which 15,108 synthesised (§4.1, p. 5); 97.52 ± 0.65% lifted
T5-large accuracy (Table 1, p. 6); 95.13 ± 1.42 / 95.03 ± 1.20 / 96.73 ± 1.03% full
NL→STL on Circuit / Navigation / Office-email (Table 2, p. 7); 38.25 ± 6.51 / 50.51 ±
5.08 / 58.73 ± 4.86% for GPT-3 end-to-end (Table 2); 98.84 ± 0.41 / 99.03 ± 0.53 /
100.00 ± 0.00% GPT-3 AP-detection (Table 3, p. 7); GPT-4 ad-hoc 77.7% over 300 samples
(p. 2); 2.906 APs per formula on average, max 7 (Table 8, p. 22).

Do **not** quote per-point values from Figures 6, 7, 12, 13 or 14 as exact — the figure
images were not read, only their captions and the surrounding prose. The two
figure-derived claims that *are* safe because they are stated in text: "near 95% with
only 200 to 500 full NL-STL examples … one magnitude less than the Seq2Seq baselines"
(p. 8), and "the Seq2Seq model reaches a highest accuracy at 83%, while T5-large model
reaches a highest accuracy at 97.5%" (Appendix I, p. 21).

The reading brief's "23K dataset" figure does not appear in the paper; the paper states
28K throughout (abstract, contribution bullets p. 2, §4.1 p. 5).
