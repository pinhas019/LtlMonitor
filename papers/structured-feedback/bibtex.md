# BibTeX — Structured Feedback Improves Repair in an LLM Agent Loop

## Verified entry

```bibtex
@misc{ray2026structured,
  title         = {Structured Feedback Improves Repair in an {LLM} Agent Loop},
  author        = {Ray, Jaideep and Goyal, Ankit},
  year          = {2026},
  month         = jul,
  eprint        = {2607.14167},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2607.14167},
  note          = {arXiv:2607.14167v1, 15 July 2026}
}
```

## Author list — resolved

Read directly off page 1 of arXiv:2607.14167v1:

| Author | Email on paper | Affiliation on paper |
|---|---|---|
| Jaideep Ray | jaray@acm.org | Independent Researcher |
| Ankit Goyal | ankit@goyalankit.com | Independent Researcher |

Two authors only. The running head on pages 2 and 4 reads "Jaideep Ray and Ankit Goyal",
confirming both the count and the order. Neither author lists an institutional affiliation.

## What is verified vs. not

**Verified from the PDF:**
- Title, exactly as above.
- Both author names, order, emails, and "Independent Researcher" affiliation.
- arXiv identifier 2607.14167, version v1, primary class cs.SE, dated 15 Jul 2026
  (from the arXiv stamp in the left margin of page 1).

**Not verified:**
- Published venue. The paper is typeset in ACM style and carries CCS Concepts and a Keywords
  block, which suggests a conference or workshop submission, but no venue, proceedings title,
  or conference name appears on the v1 title page. Do **not** add `booktitle`/`publisher`
  fields without checking the arXiv abstract page for a journal-ref or DOI first.
- DOI. None printed on the paper. Not verified.
- Whether a v2 or a camera-ready version exists. Only v1 was read.
- The artifact/repository URL. The paper states that an artifact containing source,
  deterministic task rules, 880 row-level results, 2,652 call traces, model settings, and the
  regeneration script exists, but no URL for it appears in the pages retrieved. Not verified.

## In-text citation for the ICRA submission

Cite as `\cite{ray2026structured}` — "Ray and Goyal" for two-author prose citations.

Two cautions when writing the sentence that cites it:
- Cite it for **what a validator should return** (failure location, observed value, admissible
  alternatives) and for **code-as-control-plane** loop design.
- Its positive evidence is TextWorld action-plan repair, **not** code repair — its 15-task
  HumanEval lane produced no repair opportunities at all. A sentence of the form "structured
  feedback improves code repair [ray2026structured]" would misrepresent the paper.
