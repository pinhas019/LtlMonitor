# BibTeX — Foresight

Key: `foresight2026` (as assigned in `papers/README.md`, item 17).

## Verification status

| Field | Status | Source |
|---|---|---|
| Title | **Verified** | Title page of arXiv:2606.23085v1 |
| Author list (all 8, in order) | **Verified** | Title page of arXiv:2606.23085v1 |
| Affiliations | **Verified** | Title page: ¹ University of Michigan, ² Princeton University, ³ University of Virginia |
| arXiv ID | **Verified** | `arXiv:2606.23085v1 [cs.RO]` stamped in the left margin of p. 1 |
| Date | **Verified** | `22 Jun 2026`, same margin stamp |
| Primary class | **Verified** | `cs.RO` |
| Venue | **NOT VERIFIED** | The PDF uses the "Abstract: … Keywords:" title-page template associated with CoRL, but no venue, proceedings, or acceptance line appears anywhere in the pages read. Cite as a preprint. |
| DOI | **NOT VERIFIED** | None printed in the paper. |
| Project page | Printed as `Foresight.github.io` on the title page. Reachability **not verified** (no browser check performed). Left out of the entry below; add a `note` field only if you confirm the URL resolves. |

Author-list note: the title page marks Haoran Zhang and Yifu Lu with `*` ("Equal
contribution") and Odest Chadwicke Jenkins with `†` ("Corresponding author"). Neither
marking changes the citation order, which is as given.

## Entry

```bibtex
@misc{foresight2026,
  title         = {Foresight: Failure Detection for Long-Horizon Robotic Manipulation
                   with Action-Conditioned World Model Latents},
  author        = {Zhang, Haoran and Lu, Yifu and Wang, Boyang and Kang, Xuhui and
                   Kuo, Yen-Ling and Cheng, Zezhou and Wang, Mengdi and
                   Jenkins, Odest Chadwicke},
  year          = {2026},
  eprint        = {2606.23085},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO},
  url           = {https://arxiv.org/abs/2606.23085}
}
```

Equivalent `@article` form, if `references.bib` prefers that shape for preprints:

```bibtex
@article{foresight2026,
  title   = {Foresight: Failure Detection for Long-Horizon Robotic Manipulation
             with Action-Conditioned World Model Latents},
  author  = {Zhang, Haoran and Lu, Yifu and Wang, Boyang and Kang, Xuhui and
             Kuo, Yen-Ling and Cheng, Zezhou and Wang, Mengdi and
             Jenkins, Odest Chadwicke},
  journal = {arXiv preprint arXiv:2606.23085},
  year    = {2026}
}
```

Use one or the other, not both. Remove the `% VERIFY` marker on this entry in
`docs/paper/references.bib` when folding it back — the author list is now confirmed
against the PDF title page. **Do not** add a `booktitle`/`venue` field without first
confirming acceptance; nothing in the paper states one.

## Related keys this paper supplies, if you need them

These are read off Foresight's reference list (pp. 9–11) and are useful if the contrast
paragraph or related-work section cites the neighbours. Titles and arXiv IDs are as
printed by Foresight; **author lists below are Foresight's own abbreviated renderings and
should be re-verified against the source papers before use.**

- SAFE — Gu, Ju, Sun, Gilitschenski, Nishimura, Itkina, Shkurti, "SAFE: Multitask failure
  detection for vision-language-action models", arXiv:2506.09937, 2025. [ref 2]
- FAIL-Detect — Xu et al., "Can we detect failures without failure data?
  Uncertainty-aware runtime failure detection for imitation learning policies",
  arXiv:2503.08558, 2025. [ref 1]
- V-JEPA 2 (the backbone) — Assran et al., "V-JEPA 2: Self-supervised video models enable
  understanding, prediction and planning", arXiv:2506.09985, 2025. [ref 8]
- Gauge — Ho, Ginting, Ward, Reinke, Kochenderfer, Agha-Mohammadi, Omidshafiei, "World
  model failure classification and anomaly detection for autonomous inspection",
  arXiv:2602.16182, 2026. [ref 7]
- **Code-as-Monitor** — Zhou, Su, Chi, Zhang, Wang, Huang, Sheng, Wang, "Code-as-Monitor:
  Constraint-aware visual programming for reactive and proactive robotic failure
  detection", arXiv:2412.04455, 2025. [ref 25] — *constraint-based rather than
  distribution-based; the closest competitor to `skill_monitor` that this paper surfaces,
  and the strongest candidate for promotion to its own reading folder.*
- I-FailSense — Grislain, Rahimi, Sigaud, Chetouani, "I-FailSense: Towards general robotic
  failure detection with vision-language models", ICRA 2026, arXiv:2509.16072. [ref 26]
