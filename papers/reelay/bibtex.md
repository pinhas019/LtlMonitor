# BibTeX — Reelay

## Verified entry (use this key: `reelay2026`)

Author list **resolved**: a single author, **Dogan Ulus**. The `% VERIFY` marker on this
entry in `docs/paper/references.bib` can be removed.

```bibtex
@misc{reelay2026,
  title         = {Reelay: Online Temporal Logic Monitoring Framework},
  author        = {Ulus, Dogan},
  year          = {2026},
  month         = apr,
  eprint        = {2604.22384},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LO},
  url           = {https://arxiv.org/abs/2604.22384},
  note          = {arXiv:2604.22384v1, 24 April 2026}
}
```

### What is verified, and how

| field | status | source |
|---|---|---|
| title | verified | title block of the PDF, and the arXiv listing |
| author | **verified — single author, Dogan Ulus** | byline of the PDF; no co-authors; no author footnote |
| arXiv id / version / date | verified | stamp on page 1: `arXiv:2604.22384v1 [cs.LO] 24 Apr 2026` |
| primary class | verified | `cs.LO`, from the same stamp |
| affiliation | **not verified** | the preprint uses the Springer "Noname manuscript No." template with the address block unfilled, so no affiliation appears in the text. Public sources list Doğan Ulus at Boğaziçi University — do **not** put this in the entry. |
| journal / venue | **not verified** | see below |
| DOI | **none** — no DOI is present in the preprint |

### Name spelling

The PDF byline is ASCII **"Dogan Ulus"**, and that is what the entry uses. The author's
name in Turkish orthography is **Doğan Ulus**. If the rest of `references.bib` preserves
diacritics, use `Ulus, Do{\u{g}}an` — but the paper itself does not, so ASCII is defensible
and consistent with how the tool's own repository (`github.com/doganulus/reelay`) spells it.

---

## Which one to cite — the Reelay lineage

Reelay does have an earlier lineage, and the 2026 preprint **restates and extends it rather
than superseding a prior Reelay *tool* paper — because no prior standalone Reelay tool paper
exists.** The three related items, and what each is for:

**1. arXiv:2604.22384 (this paper) — the tool/framework paper.**
Cite this for: the Reelay *framework* itself, its specification language, its C++/Python
architecture, the discrete/dense unification claim, the delta-encoded behaviour model, and
the benchmark comparisons against RTAMT and DejaVu. This is the citation you want in a tool
comparison table. It is the first paper whose subject is Reelay-the-tool.

**2. Ulus, "Online Monitoring of Metric Temporal Logic using Sequential Networks" — the
algorithmic foundation.**
This paper's own reference [17], and the thing it defers to for all formal content: §4
states it is "building upon the formal foundations and algorithmic analyses presented in
[17]", and §3.3 and §6.1 both refer there for the formal definitions of the past operators
and for why timed monitoring is constant-time in the bound magnitude. Cite this instead if
you need the *sequential-network construction* or the *semantics*, not the tool.

Its publication state is awkward and needs care:

- The 2026 preprint's reference list gives it as *Logical Methods in Computer Science*,
  **2026, "(To appear)"** — so at the time of writing it was accepted but unpublished.
  **Volume, issue and page numbers are not verified**, and neither is whether it has since
  appeared.
- The long-standing preprint is **arXiv:1901.00175** (CoRR, 2019), same title, same single
  author. This is verified as existing and matching in title and author, but I have **not
  verified** that the LMCS version and arXiv:1901.00175 are the same document (they almost
  certainly are — same title, same author, same subject — but that is inference, not
  confirmation).

If you cite it, the low-risk form is the arXiv preprint with a note about the journal
version:

```bibtex
@misc{ulus2019sequentialnetworks,
  title         = {Online Monitoring of Metric Temporal Logic using Sequential Networks},
  author        = {Ulus, Dogan},
  year          = {2019},
  eprint        = {1901.00175},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LO},
  url           = {https://arxiv.org/abs/1901.00175},
  note          = {A journal version is cited as \emph{Logical Methods in
                   Computer Science}, 2026 (to appear), in arXiv:2604.22384;
                   volume and pages not verified}
}
```

**3. Ulus, "Timescales: A Benchmark Generator for MTL Monitoring Tools", RV 2019,
Springer, pp. 402–412** — reference [16] of this paper. Not Reelay; it is the benchmark
suite used in §6. Cite only if you report or reuse those benchmark numbers. Bibliographic
details here are transcribed from this paper's reference list and are **not independently
verified**.

---

## Recommendation for `docs/paper/references.bib`

For the tool comparison table, **cite `reelay2026` alone**. It is the correct and current
citation for the tool, it is the only paper about the tool, and nothing in the table's
columns depends on the sequential-networks algorithm. Add `ulus2019sequentialnetworks`
only if the companion paper's text ends up making a claim about *how* Reelay evaluates
timed operators (e.g. the symbolic-interval argument for constant-time behaviour in the
bound magnitude), since that result lives there and not in the 2026 preprint.

Do **not** add a `journal` or `booktitle` field to `reelay2026`. The preprint is typeset in
a Springer journal template ("Noname manuscript No. (will be inserted by the editor)",
"Received: date / Accepted: date"), which indicates a journal submission in review — but
the target venue is nowhere stated in the document, and guessing it would be an invented
claim. Recheck for a published version before camera-ready.
