# BibTeX for Spot

**Provenance.** `spot.lre.epita.fr` and `lrde.epita.fr` are blocked by this host's egress proxy, so the BibTeX behind the `bib` link on the citing page could not be downloaded. The entries below are assembled from three sources that were read directly and agree field-for-field:

1. **Spot's citing page source** — `doc/org/citing.org` in the Spot tree (the file that generates `citing.html`), read at Spot 2.12.1.dev. This is authoritative for *which* paper to cite and for author order, venue, volume and pages.
2. **The Springer-exported BibTeX** for the CAV'22 chapter, reproduced verbatim below.
3. **The reference list of arXiv:2607.05907** (Duret-Lutz, July 2026), read in full, which independently confirms volume, pages and DOI for entries 1, 3 and 4.

No field below was invented. Fields added on top of the Springer export are marked where they occur.

---

## 1. THE ONE TO CITE — Spot, generic reference

Spot's citing page, section **"Generic reference"**: *"If you need to cite the Spot project, the latest tool paper about it is the following reference."*

### 1a. Springer's own export, verbatim

Reproduced exactly as Springer emits it (retrieved from a public `.bib` maintained by Henrich Lauko, an author of the paper). Note that Springer's export omits `series` and `volume`.

```bibtex
@InProceedings{Spot2022,
author="Duret-Lutz, Alexandre
and Renault, Etienne
and Colange, Maximilien
and Renkin, Florian
and Gbaguidi Aisse, Alexandre
and Schlehuber-Caissier, Philipp
and Medioni, Thomas
and Martin, Antoine
and Dubois, J{\'e}r{\^o}me
and Gillard, Cl{\'e}ment
and Lauko, Henrich",
editor="Shoham, Sharon
and Vizel, Yakir",
title="From Spot 2.0 to Spot 2.10: What's New?",
booktitle="Computer Aided Verification",
year="2022",
publisher="Springer International Publishing",
address="Cham",
pages="174--187",
isbn="978-3-031-13188-2",
url = {https://link.springer.com/chapter/10.1007/978-3-031-13188-2_9},
}
```

### 1b. Recommended entry (use this one)

Same paper, with the LNCS `series`/`volume` and the `doi` restored, and the title brace-protected so BibTeX styles do not lowercase "Spot". Every added field is cross-verified: `series`/`volume`/`pages` from Spot's citing page ("In Proc. of CAV'22, LNCS 13372, pp. 174--187. Haifa, Israel, Aug. 2022"), and `volume`/`pages`/`doi` again from reference [9] of arXiv:2607.05907.

```bibtex
@InProceedings{duret.22.cav,
  author    = {Duret-Lutz, Alexandre and Renault, Etienne and Colange, Maximilien
               and Renkin, Florian and Gbaguidi Aisse, Alexandre
               and Schlehuber-Caissier, Philipp and Medioni, Thomas
               and Martin, Antoine and Dubois, J{\'e}r{\^o}me
               and Gillard, Cl{\'e}ment and Lauko, Henrich},
  editor    = {Shoham, Sharon and Vizel, Yakir},
  title     = {From {Spot} 2.0 to {Spot} 2.10: What's New?},
  booktitle = {Proceedings of the 34th International Conference on
               Computer Aided Verification (CAV'22)},
  series    = {Lecture Notes in Computer Science},
  volume    = {13372},
  pages     = {174--187},
  publisher = {Springer},
  address   = {Cham},
  month     = aug,
  year      = {2022},
  isbn      = {978-3-031-13188-2},
  doi       = {10.1007/978-3-031-13188-2_9},
}
```

The citation key `duret.22.cav` is the anchor Spot's own citing page links to (`adl_bib.html#duret.22.cav`), so it matches the maintainers' key.

### Mandatory companion to this citation

The citing page attaches a standing note to this reference:

> Tools evolve while published papers don't. Please always specify the version of Spot (or any other tool) you are using when citing it in a paper. Future versions might have different behaviors.

So the prose must name the version, e.g. *"...translated to Büchi automata using Spot 2.12.1 \cite{duret.22.cav}"*. Read the actual version off the machine that produced the results.

---

## 2. Teaching / demo paper — cite only if discussing the web app or notebooks

*Teaching LTL and ω-Automata with Spot*, arXiv:2607.05907. Single-authored by Alexandre Duret-Lutz (EPITA Research Laboratory (LRE), Paris, France), submitted 7 July 2026, cs.LO, CC-BY. The PDF is typeset for LIPIcs with `Category: Demo` and a placeholder DOI (`10.4230/LIPIcs...`), so no final volume, page range or DOI exists yet — cite the preprint.

```bibtex
@misc{duret.26.teaching,
  author       = {Duret-Lutz, Alexandre},
  title        = {Teaching {LTL} and $\omega$-Automata with {Spot}},
  year         = {2026},
  month        = jul,
  eprint       = {2607.05907},
  archivePrefix = {arXiv},
  primaryClass = {cs.LO},
  url          = {https://arxiv.org/abs/2607.05907},
}
```

This does **not** replace entry 1. The paper itself cites Spot as "[8, 9]" — ATVA'16 and CAV'22 — confirming CAV'22 was still the current tool paper as of July 2026.

---

## 3. DO NOT use as the primary Spot citation — filed under "Obsolete references"

Spot's citing page lists the ATVA'16 "Spot 2.0" paper in its **"Obsolete references"** section, alongside the 2004 MASCOTS paper. It is what most robotics and RV papers still cite. Included here only so it is recognisable, and for the case where the 2016-era feature set is specifically what is being discussed.

```bibtex
@InProceedings{duret.16.atva2,
  author    = {Duret-Lutz, Alexandre and Lewkowicz, Alexandre and Fauchille, Amaury
               and Michaud, Thibaud and Renault, Etienne and Xu, Laurent},
  title     = {{Spot} 2.0 --- a framework for {LTL} and
               $\omega$-automata manipulation},
  booktitle = {Proceedings of the 14th International Symposium on Automated
               Technology for Verification and Analysis (ATVA'16)},
  series    = {Lecture Notes in Computer Science},
  volume    = {9938},
  pages     = {122--129},
  publisher = {Springer},
  month     = oct,
  year      = {2016},
  doi       = {10.1007/978-3-319-46520-3_8},
}
```

Venue, volume and pages from Spot's citing page ("In Proc. of ATVA'16, LNCS 9938, pp. 122--129. Chiba, Japan, Oct. 2016"); DOI from reference [8] of arXiv:2607.05907.

---

## 4. Optional companion — the HOA format

Cite this if the paper describes, ships or exchanges automata in HOA. Listed under "Other, more specific, references" on Spot's citing page; all fields verified against reference [4] of arXiv:2607.05907.

```bibtex
@InProceedings{babiak.15.cav,
  author    = {Babiak, Tom{\'a}{\v s} and Blahoudek, Franti{\v s}ek
               and Duret-Lutz, Alexandre and Klein, Joachim
               and K{\v r}et{\'i}nsk{\'y}, Jan and M{\"u}ller, David
               and Parker, David and Strej{\v c}ek, Jan},
  title     = {The {H}anoi Omega-Automata Format},
  booktitle = {Proceedings of the 27th International Conference on
               Computer Aided Verification (CAV'15)},
  series    = {Lecture Notes in Computer Science},
  volume    = {9206},
  pages     = {479--486},
  publisher = {Springer},
  month     = jul,
  year      = {2015},
  doi       = {10.1007/978-3-319-21690-4_31},
}
```

---

## Quick answer

Cite **§1b** (`duret.22.cav`), and name the Spot version in the prose. Do not cite §3 as the primary reference.
