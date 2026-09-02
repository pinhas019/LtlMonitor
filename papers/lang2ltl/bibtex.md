# BibTeX — Lang2LTL

Key: `liu2023lang2ltl` (as assigned in `papers/README.md`).

## Verified entry — cite this one

```bibtex
@inproceedings{liu2023lang2ltl,
  title     = {Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments},
  author    = {Liu, Jason Xinyu and Yang, Ziyi and Idrees, Ifrah and Liang, Sam and
               Schornstein, Benjamin and Tellex, Stefanie and Shah, Ankit},
  booktitle = {Proceedings of The 7th Conference on Robot Learning},
  editor    = {Tan, Jie and Toussaint, Marc and Darvish, Kourosh},
  series    = {Proceedings of Machine Learning Research},
  volume    = {229},
  pages     = {1084--1110},
  year      = {2023},
  month     = {06--09 Nov},
  publisher = {PMLR},
  url       = {https://proceedings.mlr.press/v229/liu23d.html}
}
```

## Alternative — arXiv preprint (use only if you deliberately want the preprint)

```bibtex
@misc{liu2023lang2ltl_arxiv,
  title         = {Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments},
  author        = {Liu, Jason Xinyu and Yang, Ziyi and Idrees, Ifrah and Liang, Sam and
                   Schornstein, Benjamin and Tellex, Stefanie and Shah, Ankit},
  year          = {2023},
  eprint        = {2302.11649},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO},
  url           = {https://arxiv.org/abs/2302.11649}
}
```

Prefer the PMLR `@inproceedings` form. CoRL is the venue of record and a formal-methods/robotics reviewer
will expect the proceedings citation, not the preprint.

---

## What was verified, and how

**Author list — VERIFIED, primary source.**
Read directly off the title page of arXiv:2302.11649v2 (p. 1), retrieved via `mcp__alphaXiv__answer_pdf_queries`:

> Jason Xinyu Liu\*¹, Ziyi Yang\*¹, Ifrah Idrees¹, Sam Liang², Benjamin Schornstein¹, Stefanie Tellex¹, Ankit Shah¹
> ¹ Department of Computer Science, Brown University, United States
> ² Department of Computer Science, Princeton University, United States
> \* Equal contribution

Seven authors, in that order. Liu and Yang are joint first authors — worth knowing if you ever refer to the
work by first author in prose. Six of seven are at Brown; **Sam Liang is at Princeton**, not Brown. Ankit Shah
is last author. Note the first author's name is **Jason Xinyu Liu** — some sources render it "Xinyu Liu" or
"J. X. Liu"; the paper itself and PMLR both use the full three-part form. BibTeX `Liu, Jason Xinyu` is correct.

**Title — VERIFIED, primary source.** arXiv v2 title page, p. 1. Exact, including "Unseen Environments".
"Lang2LTL" is the system name, not part of the title; do not put it in the `title` field.

**Venue and year — VERIFIED, primary source.** The arXiv v2 title-page footer reads:
> "7th Conference on Robot Learning (CoRL 2023), Atlanta, USA."
arXiv v2 dated 17 Oct 2023.

**Volume 229, pages 1084–1110, editors, publisher, month, PMLR URL — VERIFIED, secondary source (two
independent agreeing sources, not confirmed at PMLR itself).**
1. The reading assignment for this task supplied "PMLR v229 pp. 1084–1110".
2. Independently, the bibliography of GinSign (arXiv:2512.16770, p. 11) carries the complete PMLR record:
   > Jason Xinyu Liu, Ziyi Yang, Ifrah Idrees, Sam Liang, Benjamin Schornstein, Stefanie Tellex, and Ankit
   > Shah. Grounding complex natural language commands for temporal tasks in unseen environments. In Jie Tan,
   > Marc Toussaint, and Kourosh Darvish (eds.), *Proceedings of The 7th Conference on Robot Learning*,
   > volume 229 of *Proceedings of Machine Learning Research*, pp. 1084–1110. PMLR, 06–09 Nov 2023.
   > URL https://proceedings.mlr.press/v229/liu23d.html

These two agree on volume, page range and author list. The editors (Jie Tan, Marc Toussaint, Kourosh Darvish),
the `06--09 Nov` month string and the `liu23d` PMLR paper ID come from source (2) only.

**NOT verified:** the PMLR landing page itself. `proceedings.mlr.press` and `dblp.org` are both blocked by
this environment's network egress proxy (`EGRESS_BLOCKED`), so the canonical PMLR entry could not be fetched
first-hand. Before submission, open <https://proceedings.mlr.press/v229/liu23d.html> and confirm the page
range and editor list against the entry above. Everything else in the entry is confirmed from the paper itself.

**NOT verified:** a DOI. PMLR volumes generally do not mint per-paper DOIs, and none was found. Omit the
`doi` field rather than guessing one.

**Project resources (from the paper, p. 1, footnote 1):** code, datasets and videos at
<https://lang2ltl.github.io/>. Not independently checked from this environment.

---

## Fold-back note for `docs/paper/references.bib`

This resolves the `% VERIFY` marker on `liu2023lang2ltl`. The author list is now confirmed against the
paper's own title page — replace whatever placeholder is in `references.bib` with the seven-author list
above, exactly as ordered. Keep the `% VERIFY` marker on the **page range** alone until someone loads the
PMLR page in a browser.
