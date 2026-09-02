# Lang2LTL — Grounding Complex Natural Language Commands for Temporal Tasks in Unseen Environments

Liu, Yang, Idrees, Liang, Schornstein, Tellex & Shah. CoRL 2023, PMLR v229, pp. 1084–1110.
arXiv:2302.11649v2 (17 Oct 2023). Page numbers below are **arXiv v2** unless stated; PMLR pagination differs.

---

## 1. In one paragraph

Lang2LTL translates a free-form English navigational command into a **grounded LTL formula** whose atomic
propositions are real landmarks in a specific environment, without any training data from that environment.
It does this by refusing to solve the problem end-to-end. Instead it splits the task into three modules:
(i) a prompted GPT-4 extracts the *referring expressions* — the substrings that name things — from the
command; (ii) each referring expression is matched by **cosine similarity of LLM embeddings** against a
semantic map database `D = {k : (z, f)}`, picking the landmark whose serialised semantic record `z` is
nearest; (iii) the referring expressions are replaced by placeholder symbols `A, B, …`, yielding a **lifted
utterance**, which a finetuned T5-Base translates into a **lifted LTL formula**; the placeholders are then
substituted back by the grounded landmark keys. Because only the lifted translator is learned, and its
vocabulary is five symbols and ten operators rather than every landmark in the world, the system transfers
to a new city by swapping the semantic map. The paper defines five generalization behaviours (paraphrasing,
substitution, vocabulary shift, unseen formulas, unseen template instances), builds a 49,655-utterance lifted
corpus covering 47 formula skeletons, reports **81.83% grounding accuracy across 21 unseen OpenStreetMap
cities** (§9, p. 8), and demonstrates a Boston Dynamics Spot following 52 commands in two indoor
environments.

---

## 2. Key concepts

| Term | Definition (as the paper uses it) |
|---|---|
| **Referring expression (RE)** | "noun phrases, pronouns, and proper names that refer to some individual objects" (§5.1, p. 4). REs are *whole substrings* and are a **superset of named entities**: "the store on Main Street" is one RE containing two named entities, "store" and "Main Street". Pronouns are explicitly out of scope. |
| **Referring expression recognition (RER)** | Sub-problem 1: identify the set of substrings `{r_i}` in the command `u` that refer to Boolean propositions (§5, p. 3). Solved by prompting GPT-4 with in-context examples (§5.1, p. 4). |
| **Semantic map / proposition database** | `D = {k : (z, f)}`. `k` is a unique string identifier for a proposition; `z` is serialised semantic information (JSON — street, amenity, opening hours, phone, postcode; example at Appendix B, p. 13); `f : S → {0,1}` is the Boolean-valued function that evaluates the proposition in a robot state (§4, p. 3). Note `f` is assumed given, never synthesised. |
| **Referring expression grounding (REG)** | Sub-problem 2: map each `r_i` to exactly one `k ∈ D`, then bijectively to a placeholder `β ∈ {"A","B",…}` (§5, p. 4). |
| **Embedding-similarity grounding** | The mechanism of REG. Eq. 2, p. 5: `k* = argmax_{k:(z,f) ∈ D} [ g_embed(r_i)ᵀ g_embed(z) ] / (‖g_embed(r_i)‖‖g_embed(z)‖)` — cosine similarity between the embedding of the referring expression and the embedding of the landmark's semantic record. Following Berg et al. **This is an argmax over `D`, so it is total and closed by construction** (see §6 below — this is the load-bearing fact for `skill_monitor`). The specific embedding model is **not verified** from the extracted text. |
| **Lifted utterance / lifted LTL formula** | The command with REs replaced by placeholders ("Go to A, but only after visiting B") and its translation `φ_β = F(A) ∧ (¬A U B)` (§5, p. 4). Output is in **prefix notation**, so it parses without parenthesis matching (§5.3, p. 5). Rationale: (a) the output vocabulary shrinks to ≤10 operators + 5 symbols; (b) lifted training data can be pooled across domains. |
| **Formula skeleton** | A formula with propositions substituted in a canonical order — `F chase` and `F walmart` both become `F a` (§6.1, p. 6). Used to define holdout splits. Equivalence checked with the **Spot** library's built-in equivalence checker. |
| **Utterance / formula / type holdout** | The three test splits. *Utterance holdout* = paraphrase test (train/test split only). *Formula holdout* = no semantically equivalent formula skeleton shared with training, but skeletons instantiate templates seen in training. *Type holdout* = the test formulas do not correspond to any training pattern at all. (§6.1, pp. 5–6.) |
| **Type-constrained decoding (TCD)** | Constrained decoding added to T5-Base at inference to prevent syntactically invalid LTL. "only marginally improved Utterance Holdout, but significantly improved Formula and Type Holdout" (Appendix I, p. 20). |

---

## 3. Method — the pipeline, concretely

Input: command `u`; environment `M = ⟨S, A, T⟩`; semantic database `D = {k : (z, f)}`.
Output: a grounded LTL formula, handed to the **AP-MDP** planner (Oh et al.), which plans over the semantic map.

1. **RER.** Prompted GPT-4, task description + in-context examples, output is a `|`-separated list of exact
   substrings copied from the utterance. Prompt shown at Appendix D, p. 15. Example from that prompt:
   > `Utterance: make sure you never visit St. James Church, a Christian place of worship on Harrison Avenue, Dunkin' Donuts, Thai restaurant Montien, New Saigon Sandwich, or Stuart St @ Tremont St`
   > `Propositions: St. James Church, a Christian place of worship on Harrison Avenue | Dunkin' Donuts | Thai restaurant Montien | New Saigon Sandwich | Stuart St @ Tremont St`

2. **REG.** Embed each `r_i`; embed each landmark's `z`; take the cosine argmax (Eq. 2, p. 5). Assign a
   placeholder letter per distinct grounded key, keeping the bijection `{k ↔ β}`.
   In the indoor robot demo this step is done differently — by a **Python-style landmark-resolution prompt**
   that gives the LLM an explicit `locations = [...]` list plus a `semantic_info` dict and asks for
   `ret_val = '<key>'` (Appendix F, p. 18). That variant is *also* closed over the declared location list.

3. **Lifted translation.** Substitute `{r_i → β}` to get the lifted utterance; translate to prefix-notation
   lifted LTL. Six model classes were compared: finetuned T5-Base, finetuned T5-Base + TCD, finetuned GPT-3
   (`text-davinci-003`), prompted GPT-3, prompted GPT-4, and a from-scratch seq2seq transformer.
   **Finetuned T5-Base (with TCD) was chosen for the full system** — cheaper inference, and TCD is
   implementable on it (§6.4, p. 7).

4. **Symbol substitution.** Replace `β` by `k` using the stored bijection. Result is a grounded LTL formula.

5. **Planning.** AP-MDP compiles the formula to a Büchi automaton and plans on the product MDP. Because
   satisfiability is decided formally, **unsatisfiable commands are detected and execution is aborted** rather
   than attempted (§7, p. 8).

Grammar and operator set: base `¬, ∨, X, U`, plus derived `∧, F, G`, plus `W` (weak until) and
`M` (strong release), defined in Appendix A, p. 13. 15 navigation-relevant templates adopted from Menghi
et al.'s catalog of robotic mission patterns.

**Datasets built.**
- *Lifted corpus*: 1,156 hand-collected English/LTL pairs → permuted over proposition orderings → **49,655
  utterances, 2,125 unique LTL formulas, 47 unique lifted formula skeletons** (§6.2, p. 7).
  Propositions per formula (min, max, mean) = (1, 5, 3.79); formula length (2, 67, 18.89); self-BLEU 0.85;
  grounded vocabulary size 1,757 (Appendix H, p. 19).
- *Grounded OSM corpus*: GPT-4 paraphrases OSM landmark names into three diverse REs each; symbols in 100
  randomly sampled lifted utterances are substituted with those REs, **for each of 21 cities** → 2,100
  utterances (§6.3–6.4, p. 7).
- For scale comparison (Appendix H Table 1, p. 19): CleanUp World has 3,382 datapoints / **4** unique
  skeletons; NL2TL 39,367 / 605; Wang et al. 6,556 / 45.

---

## 4. Results

**Component-wise, on the 2,100-utterance grounded OSM set across 21 cities (Table 1, p. 6).**
Metric = per-module accuracy, averaged over cities, ± standard error across cities.

| Component | Accuracy |
|---|---|
| RE Recognition | **98.01 ± 2.08 %** |
| RE Grounding | **98.20 ± 2.30 %** |

"The accuracy of RER decreased slightly, and REG performed uniformly well as we varied the complexity of
commands and REs, respectively" (§6.4, p. 7).

**Lifted translation (Fig. 3a, p. 6).** Six models × three holdouts × five-fold cross-validation.
The exact bar values are **not stated in the text and are therefore not verified here.** What the text does
assert (§6.4, p. 7; Appendix I, pp. 19–21):
- The two finetuned LLMs (T5-Base, GPT-3) are best on **utterance holdout**.
- All models degrade on formula holdout and degrade most on **type holdout**; the finetuned models suffer the
  worst degradation.
- "only the prompt GPT models achieve meaningful accuracies in the Type Holdout scenarios. However, even in
  Type Holdout, the accuracies are concentrated on formula types that only had short lengths or shared
  subformulas with types seen during training" (p. 20).
- Prompt GPT-4 > Prompt GPT-3 everywhere.
- Verdict: "Formula and Type Holdout remain challenging paradigms of generation and an open problem" (p. 20).

**Full system on grounded OSM (Fig. 3b, p. 6; §6.5, p. 7).** Lang2LTL vs. CopyNet (Berg et al., retrained on
an identical data budget) vs. end-to-end Prompt GPT-4 (with ≥1 example of every formula skeleton in the
prompt). The text says Lang2LTL "outperform[s] both the baselines by a significant margin"; **exact bar
values not in text — not verified.** The headline number appears only in the conclusion:
> "Lang2LTL achieves a grounding accuracy of **81.83%** in 21 unseen cities and outperforms the previous SoTA
> and an end-to-end prompt GPT-4 baseline." (§9, p. 8)

Caveat: Prompt GPT-4 "was only evaluated on a smaller subset of the test set" due to inference cost.

**Cross-domain, zero-shot (Table 2, p. 6).** Metric = translation accuracy; `*` = zero-shot.

| Model | OSM (Berg et al.) | CleanUp (Gopalan et al.) |
|---|---|---|
| **Lang2LTL** | **49.40 ± 15.49 %** \* | **78.28 ± 1.73 %** \* |
| CopyNet (Berg et al.) | 45.91 ± 12.70 % | 2.57 % \* |
| RNN-Attn (Gopalan et al.) | NA \* | 95.51 ± 0.11 % |

Read this honestly: zero-shot Lang2LTL beats zero-shot CopyNet by a wide margin on CleanUp, but the
**in-domain-trained RNN-Attn still beats Lang2LTL by 17 points on CleanUp**, and 49.40% on OSM with a ±15.49
standard error is a weak absolute result. The paper's own explanation: "the CleanUp World dataset contains 6
unique formula skeletons, out of which some were not a part of our lifted dataset. The degraded performance
is expected when the model needs to generalize to unseen formulas" (§6.6, p. 8).

**Robot demonstration (§7, pp. 7–8; command-by-command tables at Appendix J, pp. 24–25).**
Spot quadruped + AP-MDP, two indoor environments, eight landmarks each, deliberately containing multiple
objects of the same type with different attributes. The lifted translator was further finetuned on 120,000
compositional lifted pairs for this demo.

| | Lang2LTL | Code-as-Policies |
|---|---|---|
| Correctly handled | **52 / 58** (40 satisfiable + 12 unsatisfiable) | **23 / 58** acceptable executions |
| Unsatisfiable commands | detected, execution aborted by AP-MDP's formal guarantee | not explicitly recognised |

The 6 Lang2LTL failures are rows 28–30 of Appendix Table 2 (p. 24) and 26–28 of Appendix Table 3 (p. 25),
each labelled **"incorrect grounding. OOD"** — but §7 (p. 8) says "The failure cases were due to **incorrect
lifted translations**." Note also the fairness caveat the authors volunteer: CaP was given a navigate-between-
nodes helper, i.e. "actions at a much higher level of abstraction than our system", while AP-MDP only had
primitive edge-traversal actions. And: "CaP demonstrated more robustness to paraphrasing than our system".

---

## 5. Limitations

**Admitted (§8, p. 8).**
1. **Utterance-structure overfitting.** "Lang2LTL fails at grounding language commands with certain utterance
   structures, which suggests that the lifted translation model overfits some training utterances."
   Proposed fix: a larger model, e.g. T5-Large. This is the failure mode behind the six robot-demo failures.
2. **No coreference resolution.** Only noun phrases and proper names are recognised; pronouns are not.
3. **Referential ambiguity is resolved by coin flip.** "If there are multiple landmarks of the same semantic
   features present in the environment, e.g., two Starbucks, Lang2LTL cannot distinguish the two and selects
   one at random. To resolve this ambiguity, the robot needs to actively query the human user via dialog."
4. **Unseen formulas remain unsolved** (§6.1, p. 6; Appendix I, p. 20).

**Also documented but not framed as a limitation.**
5. **Spatial relations break RER.** Appendix Table 6 (p. 27) tests 10 commands whose REs contain spatial
   relations; **5 of 10 are marked incorrect**. E.g. #9 "go pass right of Dairy Queen to left of Harris Teeter,
   end up at entrance of Wells Fargo" → RER returned `Dairy Queen | Harris Teeter | Wells Fargo`, silently
   stripping "right of", "left of", "entrance of". #6 "go around big blue box" → `big blue box`, incorrect.
   This is a 50% failure rate on a whole linguistic category, reported only in an appendix table with no
   discussion in the main text.

**Unadmitted.**
6. **The truth-evaluation functions `f` are assumed, never produced.** §4 (p. 3) posits `f : S → {0,1}` as
   given in `D`. Lang2LTL never has to *synthesise* an executable predicate; it only has to *select* one.
   Everything downstream of the argmax is guaranteed executable because it was already executable.
7. **REG is never stress-tested against a missing referent.** Eq. 2 has no threshold and no reject option:
   an argmax always returns something. There is no experiment in which the user names a landmark absent from
   the map. The 98.20% is measured on a benchmark constructed by *paraphrasing landmarks that are in the map*
   (§6.3, p. 7) — the ground truth is guaranteed present by construction. So the number is an upper bound on
   in-vocabulary matching, and says nothing about out-of-vocabulary behaviour.
8. **REG evaluation is entangled with its own data generator.** The diverse REs were produced by GPT-4 from
   the same `z` records that REG then embeds. A high score is partly a measure of GPT-4 agreeing with itself.
9. **81.83% appears only once, in the conclusion**, with no confidence interval and no table row.
10. **Fig. 3a / 3b values live only in bar charts**, which makes third-party comparison against the paper's
    numbers difficult — see the GinSign discussion below.

### The GinSign characterisation — does Lang2LTL's own data support it?

GinSign (English, Walker, Simon & Ewetz, arXiv:2512.16770, p. 2) writes:
> "In our setting, Lang2LTL (Liu et al., 2023) employs an embedding-similarity approach to align lifted APs
> with semantic maps. However, this method **undershoots state-of-the-art lifted translation accuracy by more
> than 20%**, highlighting the challenge of achieving both accurate lifting and precise grounding
> simultaneously."

**As written, about *lifted* translation accuracy, this is not supported — and GinSign's own experiments
contradict it.** GinSign Table 4 (p. 8) reports Logical Equivalence (LE, the lifted metric, which "does not
account for AP grounding"):

| Framework | Traffic Light LE | Search & Rescue LE | Warehouse LE |
|---|---|---|---|
| NL2TL | 98.7 | 95.0 | 99.0 |
| **Lang2LTL** | **100.0** | **100.0** | **100.0** |
| GinSign | 100.0 | 100.0 | 100.0 |

Lang2LTL ties GinSign and beats NL2TL on *lifted* accuracy in all three domains, in GinSign's own table.
The >20% gap is real but it is the **LE-vs-GLE gap**, i.e. the cost of *grounding*, not of lifting:
Lang2LTL's Grounded Logical Equivalence in the same table is 73.6 / 59.0 / 38.8 against LE of 100 / 100 / 100
— gaps of 26.4, 41.0 and 61.2 points. So the sentence is best read as a **mis-stated version of a correct
finding**: Lang2LTL's *grounded* accuracy undershoots its own lifted accuracy by 26–61 points.

From Lang2LTL's side: the paper's Fig. 3a values are not in its text, so a direct numeric rebuttal from the
primary source is **not verified**. What the primary source does show is a 49.40% zero-shot grounded result on
Berg et al.'s OSM set and 78.28% on CleanUp against an in-domain 95.51% — consistent with "grounded accuracy
is the weak link", not with "lifted translation is the weak link".

**Practical note for the reader:** if you cite GinSign's sentence, cite it as a claim about *grounded*
accuracy, or quote it and correct it. Repeating it verbatim as a claim about lifted translation would be
repeating an error that GinSign's own Table 4 refutes, and a CoRL-literate reviewer will notice.

---

## 6. For `skill_monitor`

### THE question: what does embedding-similarity grounding get wrong, and would a mechanical schema check have caught it?

**Answer: no. Not one of them. And the reason is structural, not empirical — which makes it a stronger
finding than a benchmark number.**

Look at Eq. 2 (p. 5):

```
k* = argmax_{k:(z,f) ∈ D}  cos( g_embed(r_i), g_embed(z) )
```

This is an **argmax over the semantic database `D`**. Its codomain *is* `D`. Lang2LTL therefore **cannot
emit a proposition identifier that is not declared in the environment's semantic map** — not "rarely does
not", but *cannot*, as a property of the operator. Every grounded formula it produces is executable against
the map it was grounded in. The exact failure your `core/spec_contract.py` oracle is sound against — a free
variable that would raise `NameError` at runtime — has probability **zero** in Lang2LTL by construction.

Consequently every documented Lang2LTL grounding error is in the **"real but wrong"** category:

| Failure | Where reported | Category | Would a free-variable check catch it? |
|---|---|---|---|
| Two Starbucks in the map; "cannot distinguish the two and selects one at random" | §8, p. 8 | Real but wrong — both keys are declared | **No.** Both pass. |
| Spatial relations stripped by RER: "right of Dairy Queen" → `Dairy Queen`; 5/10 incorrect | Appendix Table 6, p. 27 | Real but wrong — `Dairy Queen` is a declared landmark; the *region* meant is not the one grounded | **No.** Passes cleanly, robot goes to the wrong place. |
| 6/58 robot-demo commands fail; rows labelled "incorrect grounding. OOD" | Appendix Tables 2–3, pp. 24–25 | Attributed by §7 (p. 8) to **incorrect lifted translation** — wrong *operator structure*, not wrong symbols | **No.** The APs are fine; the formula is wrong. |
| Lifted-translation error taxonomy: syntax error / misclassified formula type / incorrect number of propositions / incorrect permutation / unknown template | Appendix I, p. 21 | Structural. Only "syntax error" is mechanically detectable, and TCD already eliminates it | **No** (a syntax checker would; a *schema* checker would not). |
| Third-party measurement: argument-grounding F1 61.8% in the Warehouse domain, attributed to "constants … not lexically consistent with their surface realizations in text" | GinSign Table 3, p. 8, and §5.4, p. 10 | Real but wrong — every wrong answer is a valid constant `c ∈ C` | **No.** |

Quantified from the third-party source: on GinSign's VLTL-Bench, Lang2LTL's argument-grounding F1 is
**86.2 / 77.6 / 61.8%** (Traffic Light / Search-and-Rescue / Warehouse), i.e. roughly **14% / 22% / 38% of APs
grounded wrong** — and *100% of those wrong groundings are to symbols that exist in the signature*, because
GinSign's grounding target set `P_S` is likewise closed. (Caveat: these are a competitor's reimplementation
numbers, not Lang2LTL's own.)

### What this means for your argument — say this part carefully

The naive version of your Related Work argument is: *"embedding grounding produces unexecutable references;
a schema check would catch them."* **Lang2LTL does not support that, and a reviewer who reads Eq. 2 will say
so.** Do not write it.

The version Lang2LTL actually supports is sharper, and it is a claim about *why closure is available to
Lang2LTL and not to you*:

> Lang2LTL achieves executability by **construction**: its grounding target is a *selection* from a finite
> declared set, so an argmax closes the output vocabulary for free. `skill_monitor`'s grounding target is not
> a selection — it is a *compositional Boolean expression* over declared sensor keys
> (`min_range < 0.25`, `battery_pct < 20 and not docked`). That space is not enumerable, so it cannot be
> closed by argmax, and an LLM generating into it has a genuinely **open** output vocabulary. Closure must
> therefore be recovered *post hoc*, by checking the free variables of the generated expression against the
> adapter schema. `spec_contract.py` is the price of expressive APs; Lang2LTL avoids paying it by not having
> them.

And then the honest concession, which you should make yourself rather than let a reviewer make it:

> Neither mechanism helps with *wrongness*. Lang2LTL's argmax is sound-by-construction and still grounds
> 14–38% of APs to the wrong real landmark (GinSign, Table 3). `spec_contract.py` is sound and still cannot
> tell `min_range < 0.25` from `min_range < 0.025`. The soundness claim is **"never unexecutable"**, and
> that is the entire claim. Say so in the Limitations section before someone says it for you.

There is one further gift in the paper for that concession. Lang2LTL's §4 (p. 3) *assumes* `f : S → {0,1}`
is supplied with each map entry — the truth-evaluation function is given, never synthesised. Your system
synthesises `f` (the regex-extracted, `eval`'d predicate) as part of the spec. **That is the actual novelty
gap**, and it is the reason your paper needs a validation oracle at all while Lang2LTL does not. Frame
`spec_contract.py` as the consequence of synthesising `f`, not as a fix for embedding similarity.

### The other transferable lesson: closure ≠ correctness ≠ satisfiability

Lang2LTL gets a *third* guarantee that neither embedding similarity nor a schema check provides:
AP-MDP detects unsatisfiable specifications and aborts, correctly handling 12/12 unsatisfiable commands
where Code-as-Policies "did not explicitly recognize" any of them (§7, p. 8). That is a strong precedent for
a **third contract-check layer** in `spec_contract.py`: alongside the free-variable check, run the compiled
LTL through Spot's emptiness check. `G(¬p) ∧ F(p)` passes your free-variable check and is unmonitorable.
If you do not already do this, it is a cheap, sound, and citable addition — and Appendix Tables 2 and 3
(pp. 24–25) give you 12 concrete unsatisfiable robot commands as test cases.

### What to cite it for, and where

| Section of your ICRA paper | Cite Lang2LTL for | Suggested sentence shape |
|---|---|---|
| **Introduction** | The dominant paradigm: modular NL→LTL with a separate grounding stage, deployed on a real robot | "Modular NL-to-LTL pipelines ground atomic propositions by embedding similarity against a pre-built semantic map [liu2023lang2ltl]." |
| **Related Work — grounding** | The canonical embedding-similarity grounding method, and its argmax-closure property | "Lang2LTL's grounding is an argmax over a declared landmark database (Eq. 2), so it is executable by construction; its residual errors are mis-selections among real landmarks, not references to nonexistent ones." |
| **Related Work — the gap you fill** | `f` is assumed given, not synthesised | "Lang2LTL assumes each map entry carries a Boolean evaluation function `f : S → {0,1}` [liu2023lang2ltl, §4]; `skill_monitor` synthesises `f` from the AP's English description, which is why it requires a validation contract that selection-based grounding does not." |
| **Method — `spec_contract.py`** | Contrast: closed-by-construction vs. closed-by-checking | Use the framing block above verbatim in spirit. |
| **Method — satisfiability check** (if you add one) | Precedent for aborting on unsatisfiable specs, with formal guarantees | "Following Lang2LTL's use of AP-MDP to reject unsatisfiable commands [liu2023lang2ltl, §7], we …" |
| **Experiments — ambiguity** | The two-Starbucks case as a named, cited failure mode you also inherit | "Referential ambiguity is resolved arbitrarily by embedding-similarity grounding [liu2023lang2ltl, §8]; our oracle likewise cannot detect a semantically wrong but well-typed predicate." |
| **Limitations** | Honest bound on what a static check buys | "Like Lang2LTL's argmax, our contract check guarantees executability, not correctness." |
| **Do NOT cite it for** | "Embedding grounding produces undeclared symbols" | It cannot. This is the trap. |

**One thing to steal outright:** the **five generalization behaviours** (§6.1, pp. 5–6) —
paraphrasing / substitution / vocabulary shift / unseen formulas / unseen template instances. That is a
ready-made, citable evaluation axis set. If your E1 evaluates `skill_monitor` only on paraphrases of skill
descriptions it has seen, a reviewer with this paper in hand will say you tested only the weakest of the five.
Adding a **vocabulary-shift** split (new robot adapter schema, new sensor key names) is directly analogous to
Lang2LTL's 21-unseen-cities setup and is exactly where a schema check earns its keep.

---

## 7. Check yourself

**Q1. Lang2LTL grounds referring expressions by cosine-similarity argmax over a semantic database. Could this
ever emit a proposition identifier that does not exist in that database?**
No. Eq. 2 (p. 5) is `argmax` over `{k : (z,f)} ∈ D`; the codomain is `D` itself. The operator is total and
closed. This is the single most important fact in the paper for `skill_monitor`: a free-variable/declared-key
check would catch *zero* of Lang2LTL's grounding errors, because the errors are all mis-*selections*, never
non-existent references.

**Q2. The robot-demo tables label six failures "incorrect grounding. OOD". Are these grounding errors?**
No — or at least the main text says otherwise. §7 (p. 8): "The failure cases were due to incorrect lifted
translations." "OOD" refers to compositional utterance structures outside the augmented lifted training set;
§8 attributes it to the lifted translator overfitting certain utterance structures. The table label is
misleading. If you cite these rows, cite them as *translation* failures.

**Q3. What are the RE Recognition and RE Grounding accuracies, on what data, and what is the catch?**
98.01 ± 2.08% and 98.20 ± 2.30% (Table 1, p. 6), on 2,100 utterances across 21 OSM cities. Two catches:
(a) the referring expressions were generated by GPT-4 *paraphrasing the very landmark records* that REG then
embeds (§6.3, p. 7), so the ground-truth target is present in the map by construction and the metric is
partly GPT-4 agreeing with itself; (b) Appendix Table 6 (p. 27) shows RER failing on 5 of 10 commands
containing spatial relations — a category the 98.01% headline does not cover.

**Q4. GinSign says Lang2LTL "undershoots state-of-the-art lifted translation accuracy by more than 20%".
Is that right?**
Not as written. GinSign's own Table 4 (p. 8) gives Lang2LTL a *lifted* Logical Equivalence of 100.0/100.0/100.0
across its three domains — tying GinSign and beating NL2TL (98.7/95.0/99.0). The >20% gap is between Lang2LTL's
**lifted** LE (100) and its **grounded** GLE (73.6 / 59.0 / 38.8), i.e. gaps of 26.4 / 41.0 / 61.2 points. So it
is a correct observation about *grounded* accuracy, mis-labelled as one about lifted accuracy. Lang2LTL's own
Fig. 3a values are not printed in its text, so a direct rebuttal from the primary source is not verified — but
the primary source's Table 2 (49.40% zero-shot on OSM, 78.28% on CleanUp vs. an in-domain 95.51%) is consistent
with grounding, not lifting, being the weak link.

**Q5. Lang2LTL needs no validation oracle. Why does `skill_monitor`?**
Because the two systems synthesise different things. Lang2LTL *selects* an AP from a finite set whose members
already ship with an executable truth function `f : S → {0,1}` (§4, p. 3). Selection from a declared finite set
is closable by argmax, so executability is free. `skill_monitor` *generates* `f` — a compositional Boolean
expression over sensor keys — into a non-enumerable space with an open output vocabulary. Closure cannot be
obtained by construction there, so it must be recovered by a post-hoc free-variable check against the adapter
schema. `spec_contract.py` is the price of expressive, synthesised APs. That is the defensible framing; "a
schema check would have caught Lang2LTL's errors" is not.
