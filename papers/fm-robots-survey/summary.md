# Revisiting Formal Methods for Autonomous Robots: A Structured Survey

Atef Azaiez¹, David A. Anisi¹, Marie Farrell², Matt Luckcuck³ — ¹Norwegian University of
Life Sciences (NMBU), Ås; ²University of Manchester; ³University of Nottingham.
arXiv:2509.20488v1 [cs.RO], 24 Sep 2025. **Peer-reviewed version exists**: TAROS 2025
(26th Annual Conference Towards Autonomous Robotic Systems), York, UK, 20–22 Aug 2025,
Springer LNCS/LNAI vol. 16045, pp. 338–352 — cite that, not the preprint. See `bibtex.md`.

Author list **resolved and verified** from the PDF title block (p. 1) and independently
from the Springer chapter record. The `TODO` at `docs/paper/references.bib:395` is now
answerable.

All quotations below are exact, with the arXiv v1 page number.

> **Read this before you cite anything from here.** This is *initial results* from an
> in-progress survey — the authors say so twice ("initial results", p. 1 and p. 12) and
> promise "a journal version of this work" (p. 12). It is a 12-page conference paper
> with 27 references, not a 100-page survey. Three things you might hope to find are
> **not in it**: (a) no dedicated gaps/open-challenges section, (b) no
> hardware-vs-simulation count of any kind, (c) not a single cited work on
> LLM-generated or automatically-acquired specifications. Sections 4 and 5 say exactly
> what you can and cannot take. Its real value to you is one taxonomy label, two hard
> ratios, and a 181-paper dataset you can mine yourself.

---

## 1. In one paragraph

This is a structured (systematic-review-methodology) literature survey of how Formal
Methods (FM) have been applied to Robotic Autonomous Systems (RAS), extending Luckcuck
et al.'s 2019 ACM Computing Surveys survey from the period 2007–2018 to **2007–2024**
with broader search terms and a different workflow. Three databases that permit boolean
search and bulk export — IEEE Xplore, ACM Digital Library, and Google Scholar (via the
Publish or Perish tool, capped at 999 results) — were queried with a
formal-methods-term AND autonomy-term AND robot-platform-term conjunction, returning
**20,764 papers**; Scopus and SpringerLink were "discounted... as they did not support
these features" (p. 4). Screening was done collaboratively in Rayyan, a systematic-review
platform, first on Title/Abstract/Keywords and then on full text, leaving **181 in-scope
papers** whose complete list is published as a Zenodo dataset. Three research questions
are answered by counting: RQ1 which formal approaches and formalisms are used, RQ2
whether machine learning ("Sub-Symbolic AI", SSAI) has changed the picture, RQ3 how the
field has evolved over time. The headline results: Model Checking dominates (130/181),
Runtime Verification is a distant but fast-growing second (24/181, "increased
substantially from 2013", p. 8), State-Transition systems and Temporal Logic are by far
the most common system and property formalisms, heterogeneous (multi-approach) work has
risen from 13% to 17%, and FM applied to SSAI-enabled RAS is "still limited (at most 6 in
2024)" but rising since 2018 (p. 11).

---

## 2. Key concepts — the taxonomy and its dimensions

The taxonomy is **five orthogonal dimensions**, three of them enumerated in tables. There
is no single tree; a paper gets a label on each axis independently.

### Dimension 1 — Formal *Approach* (Table 1, p. 8)

The unit of classification for "what kind of FM did this paper do". Defined implicitly by
the search string and by §2 (p. 4): "Formal Methods are mathematically rigorous
approaches to developing software and systems. They support Specification, Modelling,
Design, Synthesis, and Verification. As reflected in our search queries, formal
verification approaches include theorem proving, Model Checking (MC), and Runtime
Verification (RV)."

| Approach | № papers (of 181) |
|---|---|
| Model Checking (MC) | 130 |
| **Runtime Verification (RV)** | **24** |
| Theorem Proving | 18 |
| Formal Plan Synthesis | 17 |
| Formal Control Synthesis | 15 |
| Formal Specification (alone) | 6 |
| Heterogeneous Formal Methods | 31 |

*(The column sums to 241 because papers can carry more than one label. An eighth label,
**Realisability Checking**, appears only in the Fig. 7b pie chart at 1% and never in
Table 1 — an internal inconsistency; do not cite Table 1 as exhaustive.)*

- **Runtime Verification** is never given a formal definition in this paper. It is used
  in its standard sense — checking, at run time, that an execution satisfies a property —
  and is contrasted with "offline verification at early specification and design phases"
  (p. 11). That contrast sentence is the one you want; see §4.
- **Heterogeneous Formal Methods**: papers combining several formal approaches, either
  "tight integration between the approaches within a specific component of the RAS" or
  "separately in different phases of development or components" (p. 8). 31 papers (17%),
  "up from 13%" in the 2019 survey.
- **Formal Specification (alone)** means the paper "focused on formally specifying
  properties but their mode of verification may have been non-formal, e.g., testing
  approaches" (p. 8). Only 6 papers.

### Dimension 2 — *System* specification formalism (Table 2, p. 9)

State-Transition 117 · Differential Equations 12 · Process Algebra 5 · Temporal Logic 4 ·
Set-Based 4 · Dynamic Logic 3 · Formal Ontology 3 · Other 10.

### Dimension 3 — *Property* specification formalism (Table 3, p. 9)

Logics total 132, of which **Temporal Logic 90**, Probabilistic Temporal Logic 21,
Dynamic Logic 4, Other Logics 17. Then Set-Based 15 · Other 17 · Process Algebra 5 ·
Formal Ontology 3.

Note the taxonomic change from the 2019 survey, stated explicitly on p. 10: "our survey
categorises Probabilistic Temporal Logic and Temporal-Epistemic Logic separately to
Temporal Logic, whereas in the previous survey these three types of formalism were
collected in one single category." If you compare a number across the two surveys, this
is the trap.

### Dimension 4 — Sub-Symbolic AI (SSAI) present or absent (RQ2, §3.3)

31 of 181 papers "use FM on at least one SSAI component". Note the direction carefully:
this axis is about **FM applied *to* a learned component**, not about learned components
producing FM artifacts. See §5.1 — that distinction is your positioning.

### Dimension 5 — Publication year, 2007–2024 (RQ3)

### Scope predicate — what counts as a RAS (p. 3)

Three descriptive criteria, quoted: RAS "are fitted to a physical platform that gives it
the capability of navigating in the environment (space/air, ground or water)"; "have a
certain degree of autonomy, intelligence or adaptability... independent of human
interaction"; "can consist of multiple agents acting independently or in coordination."

A Unitree G1 humanoid running skills under ROS 2 satisfies all three (the first
comfortably — it walks). **skill_monitor is in scope for this survey.**

---

## 3. Findings — what the survey concludes about the state of the field

1. **Model Checking still owns the field.** 130/181. "This concurs with the findings of
   the previous survey" (p. 8).
2. **RV is the number-two approach and the fastest-moving one.** "the number of papers
   using RV has increased substantially from 2013" (p. 8). But it is 24 papers over 18
   years — a 13% share.
3. **One formalism pair dominates, and it is almost always model-checked.** p. 9: 65
   papers "used state-transition to model the system and Temporal Logic to model the
   properties"; **58 among those papers used Model Checking as an Approach**. p. 10:
   "76% of papers that used a Temporal Logic to specify properties, also used a
   State-Transition formalism to specify the system."
4. **Heterogeneous FM is growing**: 31 papers (17%), up from 13%.
5. **FM for SSAI-enabled RAS is small but rising**: 31 papers, from ~2018, "at most 6 in
   2024" (p. 11). The approach mix inside SSAI papers is "a very similar distribution" to
   non-SSAI papers (p. 9), with one exception: Formal Control Synthesis is roughly double
   (12% vs 6%, Fig. 7). RV is essentially flat across the split (12% vs 11%) — i.e. **the
   survey found no evidence that learned components are being met with more runtime
   verification than classical ones.** That is a finding you can use.
6. **Where this work gets published** (Fig. 4, top-5 venues; number-to-label pairing read
   off the OCR'd bar chart in legend order, so treat as approximate): IROS 27, AAMAS 11,
   SEAMS 7, ICRA 6, FormaliSE 5. The authors' own reading (p. 12) is that this reflects
   their choice of the IEEE and ACM databases. **ICRA at 6 papers over 18 years** is a
   fair indication of how thin FM-at-ICRA is — relevant to an ICRA 2027 submission, and to
   how much formal-methods background you must supply for that audience.
7. **Honest self-criticism worth knowing about** (§4, Threats to Validity, pp. 11–12):
   the counts in Table 1 are "a result of having prompted for these three approaches in
   our searches... we cannot say anything about their relative use against other methods
   that we did not prompt for explicitly." So MC:RV:TP proportions are defensible; claims
   about approaches *absent* from the search string are not.

**Internal inconsistency to avoid citing.** p. 8 claims heterogeneous FM appears "in at
least one paper per year from 2009 to 2024", but the per-year bars in Fig. 5b cover only
2009, 2010, 2013–2019 and 2021–2024 (summing correctly to 31), with 2011, 2012 and 2020
absent. Cite the 17%/13% figures, not the per-year claim.

---

## 4. Named gaps — quoted, with locations

**Be warned: this survey has no gaps section.** It has a Threats to Validity section and
a two-paragraph conclusion. Everything below is a gap-adjacent statement you can quote
honestly; nothing below is the survey saying "X is under-explored" in those words. Do not
paraphrase any of it into a stronger claim than the quote supports.

**G1 — the design-time / run-time framing. This is the quote to build on.** p. 11:

> "The interest in RV took some time to appear, but quickly became second. This increase
> could be explained by the time needed for the technology to mature, and the focus was
> more on the offline verification at early specification and design phases. As RAS
> become more complex and used in more challenging environments, then RV became a
> valuable framework to ensure that specified properties are met at run-time."

Paired with Table 1 (RV 24 vs MC 130) this is a survey-backed statement that the field's
attention has been on design time, and that RV is the newer and smaller half.

**G2 — the quantified imbalance itself.** Table 1, p. 8: RV 24 papers out of 181 (13%)
against MC's 130 (72%). And p. 9's 65/58 split. These are the two numbers most worth
citing verbatim.

**G3 — FM for learned components is thin.** p. 11:

> "Although the number of papers demonstrating the use of FM in verifying a SSAI
> component of RAS is still limited (at most 6 in 2024), we notice an increasing trend
> from 2018."

and, in the same paragraph, the motivation:

> "Most of RAS, if not all, inherently contain one or multiple components that apply an
> aspect of AI. However, it seems those components start to be more and more critical or
> involving safety of the assets or humans... Thus, formally verifying these components
> becomes of greater importance and attracts more research."

**G4 — the standing challenges, from the Introduction (p. 2).** Not survey results, but
the authors' framing of why FM-for-RAS is hard:

> "the complexity of the this kind of systems as they usually combine discrete software
> logic with continuous physical dynamics and that can lead to scalability issues.
> Moreover, the dynamic nature of the environment where RAS operate makes it difficult to
> capture all interactions and uncertainties. last but not least, there can be a gap
> between the trustworthiness of formal verification results and the expectations of
> regulatory acquirements"

*(sic — the preprint has several typos; quote as-is with [sic] or paraphrase.)*

**G5 — "Requirements and Specifications" as a grand-challenge category.** p. 3, relayed
from Leahy et al. 2024, **not** this survey's own finding — attribute it correctly:

> "Leahy et al. [15] define three categories of grand challenge for verification of
> autonomous systems: (1) Requirements and Specifications, (2) Models and Abstractions,
> and (3) Tools, Techniques and Algorithms."

This is the closest thing in the paper to naming specification acquisition as an open
problem, and the citation you actually want for that claim is Leahy et al., which you do
not currently have. See §5.3.

**G6 — what the authors say is still to come** (p. 12): "we have identified and currently
work on other relevant facets of FM, namely common tools, engineering representations,
application domain and multi-agent RAS. A more thorough evaluation of the tools used
might also offer more detailed insight." Note what is *not* on that list: hardware
deployment, and specification acquisition.

### Gaps this survey does **not** name — do not cite it for these

- Specification acquisition / spec-writing burden — **not verified**, absent. (G5 is
  Leahy et al.'s category, relayed.)
- Sim-to-real gap for monitors — **not verified**; the phrase and the concept do not
  appear.
- Real-hardware validation being rare — **not verified**, see §5.4.
- Natural-language or LLM-generated specifications — **not verified**, absent entirely.

---

## 5. For skill_monitor

### 5.1 Where skill_monitor sits in this taxonomy

Use these labels verbatim; they are the accepted vocabulary this community reviews with.

| Axis | Label the survey would assign | Company it keeps |
|---|---|---|
| Formal Approach | **Runtime Verification (RV)** | 24 of 181 papers (13%) |
| System formalism | **State-Transition** (your Spot-built deterministic Büchi automata) | 117 of 181 |
| Property formalism | **Temporal Logic** | 90 of 181 |
| SSAI axis | see the caveat below | 31 of 181 |
| Platform (scope criteria, p. 3) | RAS: physical, navigating, autonomous | in scope |

The one-sentence positioning this buys you: *skill_monitor is a Runtime Verification
approach pairing a state-transition system model with temporal-logic properties — the
single most common formalism pairing in the RAS literature (65 papers), but one that 58
of those 65 papers verify by model checking at design time rather than at run time.* That
sentence is entirely supported by pp. 8–9 and it does the work of a paragraph.

**The SSAI caveat, and why it is actually your opening.** The survey's SSAI dimension
counts papers that apply FM *to* a sub-symbolic component. skill_monitor inverts this: a
sub-symbolic component (an LLM) *produces* the formal artifact, which is then applied to
the robot. The survey has **no category for this** — no axis, no label, no cited example.
Say so plainly, and note the survey's own finding that RV's share is identical inside and
outside the SSAI subset (12% vs 11%, Fig. 7). Claiming a category the field's most recent
structured survey does not yet have a name for is a stronger and more checkable framing
move than claiming novelty in the abstract. Be precise that this is an *absence you
observed in a 27-reference conference paper*, not a claim the survey makes.

Two further honesty notes. (i) Do not label skill_monitor "Heterogeneous Formal Methods";
the survey means a combination of *formal approaches* from Table 1, and your static schema
oracle is a soundness check on predicate grounding, not a second formal approach. (ii) Do
not claim RV was found to be under-used *for learned components* — Fig. 7 says the
opposite (flat share).

### 5.2 The four highest-value citable numbers

1. **RV 24 / MC 130 out of 181 papers, 2007–2024** (Table 1, p. 8) — the design-time bias
   of the field, in one ratio.
2. **65 papers pair state-transition + temporal logic; 58 of them model-check** (p. 9) —
   the sharper version, targeted at exactly your formalism pair.
3. **RV share is 12% in SSAI-enabled papers vs 11% in non-SSAI papers** (Fig. 7) — learned
   autonomy has not pulled runtime verification along with it.
4. **31 SSAI papers total, "at most 6 in 2024"** (p. 11) — the absolute scale of
   FM-meets-learning work.

### 5.3 Cited works you are probably missing

Checked against the 30 keys in `docs/paper/references.bib`: **none** of the survey's 27
references appears there. Eight worth adding, most-valuable first.

1. **Luckcuck, Farrell, Dennis, Dixon, Fisher (2019), "Formal Specification and
   Verification of Autonomous Robotic Systems: A Survey", ACM Comput. Surv. 52(5),
   doi:10.1145/3342355.** — [17]. The canonical survey this paper revisits. If you cite
   only one item from this list, cite this one; a formal-methods reviewer will notice its
   absence immediately, and it is the reference for "the field's FM effort is concentrated
   at design time."
2. **Adam, Hartmark, Andersen, Anisi, Cavalcanti (2024), "Safety Assurance of Autonomous
   Agricultural Robots: From Offline Model-Checking to Runtime Verification", IEEE CASE
   2024, pp. 2511–2516, doi:10.1109/CASE59546.2024.10711810.** — [3]. Closest thing in
   this reference list to your contribution: an explicit design-time→run-time transition
   for a real field robot. Direct comparison target for the "we monitor on hardware" claim.
3. **Leahy, Asgari, Dennis, Feather, Fisher, Ibanez-Guzman, Logan, Olszewska, Redfield
   (2024), "Grand Challenges in the Verification of Autonomous Systems",
   arXiv:2411.14155.** — [15]. The correct citation for "requirements and specification
   acquisition is an open grand challenge". This, not the survey, is what your
   specification-acquisition motivation sentence should hang on.
4. **Redfield, Olszewska, Leahy, Murahwi, Araiza-Illan, Fisher (2024), "Verification of
   Autonomous Systems: The Road Ahead", ICRA@40, IEEE.** — [22]. A roadmap paper at an
   **ICRA** anniversary venue; an ICRA-audience-legible citation for open challenges.
5. **Farrell, Luckcuck, Fisher (2018), "Robotics and Integrated Formal Methods: Necessity
   Meets Opportunity", IFM 2018, Springer, pp. 161–171.** — [7]. The argument that RAS
   modularity and middleware make robots a good venue for FM. Supports the ROS 2
   integration half of your story.
6. **Gleirscher, van de Pol, Woodcock (2023), "A Manifesto for Applicable Formal Methods",
   Software and Systems Modeling 22(6), 1737–1749.** — [9]. Ten principles for FM that
   practitioners will actually use. The natural citation for "usability of the
   specification interface is a first-class concern", which is what your LLM front end is.
7. **Azaiez, Anisi, Farrell, Luckcuck (2025), "Revisiting Formal Methods for Autonomous
   Robots — Surveyed Literature Set", Zenodo, doi:10.5281/zenodo.15199605.** — [5]. The
   full list of all 181 in-scope papers. Not a citation so much as a **tool**: this is
   where you go to answer §5.4 yourself. See below.
8. **Fisher, Cardoso, Collins, Dadswell, Dennis, Dixon, Farrell, Ferrando, Huang, Jump et
   al. (2021), "An Overview of Verification and Validation Challenges for Inspection
   Robots", Robotics 10(2), 67.** — [8]. Challenges paper for a deployed-robot domain;
   useful if you want a second, domain-grounded challenges citation alongside [15].

**The finding you should not soften: there is no prior art for LLM-generated robot monitor
specifications anywhere in this survey's 27 references.** Not one paper on
natural-language-to-temporal-logic, LLM specification synthesis, or automatic
specification acquisition. The survey's own SSAI section (§3.3) is exclusively about
verifying learned components. Since the survey's search string contains no language, LLM,
or specification-acquisition term (the full strings are printed on pp. 4–5 — check them
yourself), work like Lang2LTL, NL2TL and nl2spec was **structurally unable to be
retrieved**, so this absence is evidence about the survey's search design as much as about
the field. State it that way in the introduction, precisely, and you are unimpeachable;
state it as "the recent survey found no such work" and you are overclaiming.

### 5.4 Real-hardware deployment — the survey does not answer this

**Not verified. The survey contains no hardware-versus-simulation count, percentage, or
discussion.** "Hardware", "physical deployment", "sim-to-real" and "simulation" are not
survey dimensions; the word "physical" appears only in the RAS scope criteria (p. 3) and
in the phrase "continuous physical dynamics" (p. 2). Deployment is not among the facets
the authors say are still in progress (p. 12), either. **Do not cite this paper for a
hardware-rarity claim.** If a draft sentence of yours currently does, that sentence is
unsupported.

The path to getting the number anyway, and it is a good one: reference [5] is a Zenodo
dataset (doi:10.5281/zenodo.15199605) listing all **181** in-scope papers. Filter it to
the **24 RV papers**, check each for a physical-platform evaluation, and you can report a
count that is yours, defensible, and derived from a published, citable corpus — e.g. "of
the N runtime-verification papers in the 181-paper corpus of Azaiez et al., k report
evaluation on physical hardware." A reviewer will accept that far more readily than an
unsourced "most work is in simulation." Budget a couple of hours; it is probably the
highest-yield two hours available for the introduction. The 2019 Luckcuck et al. survey
(item 1 above) is the other place to look for a hardware-validation statement.

---

## 6. Check yourself

**Q1. Which of the survey's taxonomy dimensions gives skill_monitor its category label,
and what fraction of the corpus shares it?**
Dimension 1, Formal Approach: **Runtime Verification**, 24 of 181 papers (13%), against
Model Checking's 130 (72%) — Table 1, p. 8. On the two formalism axes it is
State-Transition (117/181) for the system and Temporal Logic (90/181) for the properties.

**Q2. A co-author drafts: "A recent structured survey of formal methods for autonomous
robots finds that runtime verification is rarely validated on physical hardware." Ship
it?**
No. Cut it. The survey makes no hardware-versus-simulation claim anywhere and does not
count deployment at all (§5.4). The supportable substitute is the design-time/run-time
imbalance: "of the 65 surveyed papers pairing a state-transition system model with
temporal-logic properties, 58 verify by model checking" (p. 9). If you want the hardware
number, derive it yourself from the Zenodo corpus [5] and cite that.

**Q3. Where do you put skill_monitor's LLM on the SSAI axis, and what is the honest
phrasing?**
Nowhere — and that is the point. The survey's SSAI dimension counts FM applied *to* a
learned component (31 papers); skill_monitor has a learned component *producing* the
formal artifact, for which the survey has no category. Phrase it as an absence you
observed in a 27-reference conference paper whose search strings (pp. 4–5) contain no
language or specification-acquisition terms — not as a finding the survey reports.

**Q4. You want to write "specification acquisition is a recognised open challenge." Which
reference carries that, and which does not?**
Leahy et al. 2024, "Grand Challenges in the Verification of Autonomous Systems"
(arXiv:2411.14155), whose category (1) is "Requirements and Specifications" — you do not
currently cite it. This survey only *relays* that taxonomy on p. 3 and names no such gap
of its own. Cite Leahy directly; optionally cite Azaiez et al. alongside for the
quantified RV/MC imbalance.
