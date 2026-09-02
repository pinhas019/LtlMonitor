# NL2TL: Transforming Natural Languages to Temporal Logics using Large Language Models

Yongchao Chen (MIT / Harvard), Rujul Gandhi (MIT), Yang Zhang (MIT-IBM Watson AI Lab),
Chuchu Fan (MIT). arXiv:2305.07766v2 [cs.CL], 22 Mar 2024.
Venue: the task brief states EMNLP 2023; **the arXiv PDF pages read here carry no venue
line, so the venue is not verified from the paper text itself** (see `bibtex.md`).

All quotations below are exact, with the PDF page number of the arXiv v2 preprint.
Numbers read off *figures* rather than tables are flagged "not verified" — the figure
images were not available, only their captions and the prose describing them.

---

## 1. In one paragraph

NL2TL attacks natural-language-to-temporal-logic translation by refusing to solve the
whole problem at once. It splits the task into (a) recognising which spans of an English
sentence are atomic propositions and replacing them with placeholders `prop_1 … prop_n`
— *lifting* — and (b) translating the resulting placeholder-only sentence into a
placeholder-only Signal Temporal Logic formula. Only stage (b) is learned: T5-base
(220M) and T5-large (770M) are finetuned on a purpose-built corpus of **28K lifted
NL–STL pairs** (15,108 synthesised with GPT-3 assistance plus human annotation, 5K
adapted from a Navigation dataset, 8K from a Circuit dataset). Stage (a) is done at
inference time by prompting GPT-3, or bypassed entirely by further finetuning the lifted
model end-to-end on a handful of full domain pairs. The claim is that the lifted level is
where the *domain-independent* content lives: "the structure of TL itself is not
dependent on the domain and should be generic" (p. 1). Reported results: 97.52% on
held-out synthesised lifted data, and 95.13 / 95.03 / 96.73% on full NL→STL across
Circuit, Navigation and Office-email — against 38.25 / 50.51 / 58.73% for GPT-3
end-to-end and 62 / 87 / 84% for an ad-hoc GPT-4 test.

---

## 2. Key concepts

**Atomic proposition (AP), in NL2TL's sense.** A *surface string* naming an event or
condition, e.g. `create_Slack`, `acquire_v pear_n`, `signal_1_n more 42.4`, `red_room`
(Appendix G, p. 19). Formally the grammar's leaf is "an atomic predicate" π^μ (p. 3), but
operationally an AP is whatever token sequence the domain's convention says goes at a
leaf. It carries **no executable semantics inside the artifact** — see §5.

**Lifting.** Replacing every AP occurrence, in both the English and the formula, with a
positional placeholder: "In our lifted NL and STL, each AP is replaced with a placeholder
prop_i. In this way, we train our model on the general context of the instruction
regardless of the specific APs" (p. 3). Nomenclature is credited to Hsiung et al. (2021).

**Lifted NL / lifted STL.** The paired placeholder-only sentence and formula. Example
from Appendix E (p. 18): lifted STL `((prop_2 imply prop_3) equal finally[55,273]
prop_1)` with lifted NL "If (prop_2) implies (prop_3), then (prop_1) will happen at some
point during the next 55 to 273 time units, and vice versa."

**The modular pipeline (two grounding routes).** After lifted-model finetuning, NL2TL
offers two ways to reach *full* NL→STL. Route 1 — "Lifted Model + GPT-3 AP Recognition"
(§7.1): prompt GPT-3 to find and hide APs, run the lifted T5, substitute the APs back in
formatted form. Route 2 — "Transfer Learning" (§7.2): finetune the lifted-pretrained T5
directly on a few hundred *full* pairs from the target domain, letting it learn that
domain's AP convention.

**Seq2Seq translation (the baseline class).** RNN encoder-decoder with GRU cells (GLTL,
CW) or a from-scratch Transformer (Circuit) trained on full NL–TL pairs of one domain.
NL2TL positions itself against exactly this: the baselines need roughly an order of
magnitude more domain data.

**Dataset construction: Framework1 and Framework2.** Framework1 (p. 4, Fig. 3):
algorithmically synthesise a pre-order STL binary tree (Algorithm 1, max N APs), convert
to in-order word form, ask GPT-3 for a matching English sentence, have a human annotator
repair the sentence. Framework2 (p. 5, Fig. 4) adds "an extra loop between STL and NL …
the initial rule-based STL with unreasonable or complex meanings will be automatically
filtered by GPT-3 itself." Annotation throughput: "about 80 per person per hour with
Framework1, and about 120 per person per hour with Framework2" (p. 5); total 15,108
pairs at "around 150 person-hours."

**STL expression format (in-order + words).** The linearisation of the target matters a
lot. In-order traversal with operators spelled as English words (`finally`, `globally`,
`imply`) beat pre-order and symbol forms — see §4, Table 1.

**Binary accuracy.** The only metric: "we apply the binary accuracy as the metric, i.e.,
100% right or not" (p. 6). No partial credit, no semantic-equivalence check.

---

## 3. Method, concretely

**Logic.** Signal Temporal Logic, chosen because it subsumes LTL when time is discrete
(p. 3). Grammar (Eq. 1, p. 3):
`φ ::= π^μ | ¬φ | φ ∧ ψ | φ ∨ ψ | F[a,b] φ | G[a,b] φ | φ U[a,b] ψ`, plus ⇒ and ⇔ as
derived logical operators.

**Corpus.** 15,108 GPT-3-assisted + human-annotated lifted pairs; 5K lifted pairs cleaned
out of Wang et al. (2021) Navigation; 8K out of He et al. (2022) Circuit (down from the
original 120K — "we find including 8K examples into our dataset is informative enough to
cover the whole corpus richness", p. 5). For the two collected datasets, "the APs in both
two datasets are detected and hidden by combining hard-coded algorithms with entity
recognition package SpaCy" (p. 5). Total ≈ 28K.
Statistics (Tables 8–9, p. 22): **2.906 APs per formula on average, median 3, max 7**;
3.206 operators per formula, median 3, max 8; 28,466 sentences, 2,296 vocabulary items,
18.358 words per sentence on average.
*Note on the number:* the reading brief calls this "the 23K dataset." The paper says 28K
in the abstract, in the contribution bullets ("we publish a dataset of 28K lifted NL-STL
pairs", p. 2) and in §4.1; 15K + 5K + 8K = 28K. **23K is not a figure this paper states.**

**Training.** T5-base and T5-large finetuned on lifted pairs only; lr 2e-5, batch 16,
weight decay 0.01, 20 epochs, single Nvidia RTX 8000, 3 h (base) / 10 h (large); 90/10
train/test split; means and standard deviations over 3 seeds (10 seeds for CW transfer)
(Appendix L, p. 21).

**How the GPT lifting stage and the seq2seq translation stage interact — the actual
handshake.** They do *not* interact during training. The T5 is trained purely on
`prop_i`-only data; GPT-3 never touches it. They meet only at inference in Route 1, and
the coupling is a positional substitution table:

1. GPT-3 is prompted (Appendix M) to identify AP spans in the full sentence and rewrite
   the sentence with each span replaced by `prop_i`. This produces the lift map
   `{prop_1 ↦ "a response is created in Slack", …}`.
2. The finetuned T5 consumes the lifted sentence and emits a lifted STL over the same
   `prop_i` symbols.
3. "the hidden APs will be swapped into formatted form to generate the full STL" (p. 7)
   — the map is applied in reverse, and the AP is re-rendered in whatever convention the
   downstream controller expects: "we have to formulate how the APs are presented in STL
   (like 'verb_noun') so that the specified APs can directly connect with controllers"
   (p. 7).

Two consequences worth holding onto. First, the *only* thing shared between the stages is
the index `i`; nothing checks that the AP is meaningful, satisfiable, or refers to
anything that exists. Second, the AP-to-`verb_noun` reformatting is described but not
learned or evaluated — it is assumed to be a hard-coded rule the deployer supplies.

**Route 2** removes GPT-3 from the loop: take the lifted-pretrained T5 and finetune it on
full (unlifted) domain pairs, so it learns both structure and that domain's AP surface
convention in one model.

---

## 4. Results

**Target-format ablation (Table 1, p. 6) — accuracy on GPT-3-assisted lifted test data:**

| format | T5-base | T5-large |
|---|---|---|
| Pre-order + words | 70.00 ± 1.42% | 73.10 ± 1.05% |
| **In-order + words** | **96.43 ± 0.72%** | **97.52 ± 0.65%** |
| Pre-order + operators | 72.35 ± 1.54% | 71.95 ± 1.23% |
| In-order + operators | 89.94 ± 0.89% | 88.17 ± 1.02% |

Roughly **+26 points** from linearisation and operator-spelling alone. NL2TL flags this
as a reversal of prior practice: "This result is different from former conclusions when
training Seq2Seq model for NL to STL/LTL tasks, where the pre-order format is better"
(p. 6).

**Lifted-model headline (Fig. 5, p. 6):** "the highest accuracy 97.52% and 90.12% of
GPT-3 assisted data and Manual data testing, respectively." The 7-point gap between
in-distribution synthetic test and the 100 held-out volunteer-written sentences is the
paper's own cleanest generalisation signal.

**Full NL→STL, Route 1 (Table 2, p. 7):**

| model | Circuit | Navigation | Office email |
|---|---|---|---|
| GPT-4 end-to-end (ad-hoc, 100 samples/domain) | 62% | 87% | 84% |
| GPT-3 end-to-end | 38.25 ± 6.51% | 50.51 ± 5.08% | 58.73 ± 4.86% |
| T5-large + GPT-3 AP detect | 95.13 ± 1.42% | 95.03 ± 1.20% | 96.73 ± 1.03% |
| T5-base + GPT-3 AP detect | 94.61 ± 0.74% | 94.73 ± 1.02% | 96.08 ± 0.97% |

Aggregate GPT-4 figure: "GPT-4 achieves an accuracy of 77.7% over 300 samples" (p. 2).

**AP recognition in isolation (Table 3, p. 7) — this is the load-bearing number for the
decomposition argument:**

| | Circuit | Navigation | Office email |
|---|---|---|---|
| GPT-3 AP detect accuracy | 98.84 ± 0.41% | 99.03 ± 0.53% | 100.00 ± 0.00% |

The same model that scores 38–59% end-to-end scores 98.8–100% when asked only to find the
APs. "Compared to the direct NL to STL task, AP detection task is much easier to GPT-3.
Hence, dividing the whole task into AP recognition and semantic parsing are more
data-efficient and flexible than pure end-to-end method" (p. 7).

**The ablation that is meant to isolate lifting (§7.2, Fig. 6, p. 8).** This is the one
the reader is asking about, so read the caption literally: "The blue curve represents the
accuracy where T5 model first pre-trained on 28K lifted NL-STL pairs, and then finetuned
on full NL-STL examples in that domain. The orange curve represents the condition when T5
model is not pre-trained by lifted NL-STL pairs, but directly finetuned based on initial
released weights." Domains: Circuit, Navigation, GLTL. The prose result: "the pre-training
on lifted NL-STL pairs also displays a great saving on training data requirements … In
all the three domains, the T5-large model with lifted NL-STL pre-training can achieve an
accuracy near 95% with only 200 to 500 full NL-STL examples. This amount of example
requirement is one magnitude less than the Seq2Seq baselines" (p. 8).
**Per-point blue-vs-orange gaps are not verified** — Fig. 6 is a plot and the numeric
series is not stated in text or any table. The only extractable quantities are: blue
T5-large reaches ≈95% at 200–500 full pairs, and the Seq2Seq baseline needs about 10×
that. The orange (no-lifted-pretraining) curve's values are not reported numerically.

**CW held-out-formula generalisation (Fig. 7, p. 8).** CW has only 36 distinct LTL
formulas, ~50 English sentences each; Gopalan et al. train on some formula *types* and
test on unseen types. "the LLM with finetuning is apparently better than the original
baseline" — **magnitude not verified** (figure only).

**Other ablations (§6, p. 6; Appendices H–I):**
- *Human annotation*: raw GPT-3 output alone still reaches 87.3% / 79.4% (GPT-3-assisted
  / Manual test) with T5-large, but "models trained on annotated data achieves accuracy
  about 10% higher than models trained on raw data" (Appendix H.1, p. 20).
- *Framework2* (Table 7, p. 20): 3K budget — 1.5K F1 + 1.5K F2 gives 80.57 ± 0.86% vs
  3K F1 at 79.76 ± 0.88% (annotated). 4.5K budget — 3K F1 + 1.5K F2 gives 88.32 ± 0.84%
  vs 4.5K F1 at 86.51 ± 0.77%. About +2 points.
- *Model capacity* (Fig. 13, p. 21): "the Seq2Seq model reaches a highest accuracy at
  83%, while T5-large model reaches a highest accuracy at 97.5%" on the *same lifted*
  data — about +14.5 points. Lifting alone does not rescue a small Seq2Seq.
- *Complexity* (Fig. 14, p. 23): GPT-3 end-to-end accuracy "decreases rapidly with
  increasing AP number", finetuned T5-large stays flat. **Per-bin values not verified.**

---

## 5. Limitations

**Admitted (§8, p. 9).** Four, stated plainly:
1. *Coreference.* "In spoken language, coreference is quite common, such as 'pick up the
   apple and then bring it to me'. … For further work, the NER models specialized in
   resolving coreferences and converting them into normal APs are needed."
2. *Unnatural formula distribution.* STL trees are synthesised by rule; "another
   intuitive way is to fit the probable distribution of operators to be close to human
   spoken language. For instance, the probability of two continued 'negation' operators
   is nearly zero. In this work we only set some hard rules."
3. *The metric.* "The evaluation metric here is pure binary accuracy (fully correct or
   not). Actually, it is quite difficult to judge the similarity or distance of two TLs.
   Simply calculating token matching or computing truth values both own drawbacks. A more
   effective metric is needed."
4. *Malformed output.* "The output of LLMs may sometimes generate incorrect TLs. We build
   up rule-based methods to check syntactic correctness and correct errors like
   parentheses matching."

**Unadmitted, and the big one: NL2TL never grounds its APs.** The paper's own framing
gives it away — the AP `"a response is created in Slack"` becomes the token
`create_Slack` (p. 2), and that is the end of the story. There is no denotation, no
predicate, no variable binding, no check that `create_Slack` is a thing the target system
can evaluate. In Appendix G (p. 19) the Circuit APs go furthest toward semantics
(`signal_1_n more equal 11.5`) but even there `signal_1_n` is an opaque name and nothing
verifies that such a signal exists. What this costs:

- **The reported accuracy is upper-bounded on the wrong axis.** Table 2's 95% is
  *string-level* agreement with a reference formula. A formula can be 100% "correct" by
  this metric and be unexecutable — referencing a sensor the platform does not publish, a
  threshold in the wrong unit, or a room that is not in the map. NL2TL cannot detect any
  of these, because there is nothing in the artifact to check against.
- **The lift map is unvalidated and positional.** The GPT-3 lifting stage is scored at
  98.84–100% on *span identification*, not on whether the identified span means anything.
  The only invariant maintained across the pipeline is the integer `i`.
- **The "swap into formatted form" step is out of scope.** Turning
  `"a response is created in Slack"` into a symbol a controller can subscribe to — the
  step that actually connects language to a robot — is assumed, unevaluated, and left to
  the deployer's hard-coded rules (p. 7).
- **Route 2 quietly gives up on generality.** Transfer learning re-couples the model to
  one domain's AP convention. So the paper's own preferred deployment for "when we cannot
  acquire the specific hard-coded rules" (p. 7) discards the domain-independence that
  motivated lifting.

Two further unadmitted issues:

- **No ablation isolates lifting at fixed data.** Fig. 6's blue-vs-orange comparison
  confounds *lifting as a representation* with *28K extra pre-training pairs*. Blue sees
  ~28K lifted pairs plus 200–500 full pairs; orange sees 200–500 full pairs. A clean
  lifting ablation would pre-train on the *same* 28K rendered in *unlifted* form and
  compare. That experiment is not in the paper. What Fig. 6 actually establishes is that
  cheap-to-collect cross-domain structural pre-training buys data efficiency — a strong
  and useful result, but not "lifting > direct."
- **Complexity ceiling.** Max 7 APs and 8 operators per formula (Table 8), mean 2.906.
  Behaviour beyond that is untested, and the CW/GLTL test formulas are simpler still.

---

## 6. For `skill_monitor`

### The question: is lifting worth adopting in the generator?

**Recommendation: adopt partially — and note that you have already adopted the part that
matters. Do not add a `prop_i` placeholder stage.**

The honest reading of NL2TL is that "lifting" bundles two separable ideas, and only one
of them transfers.

**Idea A — decompose AP identification from structure parsing.** This is real, and
Table 3 is the evidence: the same GPT-3 that scores 38.25% translating Circuit sentences
end-to-end scores 98.84% when asked only to find the APs. Splitting a hard joint task
into an easy extraction task and a structure task is a genuine, model-agnostic win, and
it is the finding later work (GinSign included) builds on.

**Idea B — make the intermediate representation *anonymous*, i.e. `prop_1 … prop_n`.**
This is the part specific to NL2TL's predicament, and its two justifications are both
about problems `skill_monitor` does not have:

1. *Open, inconsistent AP vocabulary across domains.* "each work has to regularize its
   own content and style of APs, affecting generalization" (p. 2). `skill_monitor` has
   exactly one AP convention, and it is fixed by the robot's adapter schema, statically
   checked by `skill_monitor/core/spec_contract.py` (`unknown_keys`, `validate`). There
   is no cross-domain style drift to normalise away.
2. *A small finetuned model with a large output vocabulary.* Lifting collapses the T5's
   target vocabulary to operators plus a handful of placeholders, which is precisely what
   a 220M/770M model needs. `skill_monitor` prompts a frozen large model and never
   finetunes; the output vocabulary problem does not arise.

Add to that: `skill_monitor`'s AP set is **7–8 names** (`specs/formulas.json` has 7,
`specs/formulas_g1.json` has 8), it is enumerated *before* formula generation, and each
name is bound to an executable predicate in the same string —
`"collision_risk": "True when min_range < 0.25. An obstacle is detected too close."`.
Anonymising `collision_risk` to `prop_4` would strip the one signal that makes the
formula checkable, in exchange for a normalisation benefit that a fixed 8-symbol
vocabulary does not need. NL2TL lifts because it cannot ground; `skill_monitor` grounds,
so it does not need to lift.

**Where `skill_monitor` already implements Idea A.** The `atomic_propositions` dict *is*
the lift table — it plays exactly the role of NL2TL's `{prop_i ↦ span}` map. The
`ltl_formulas`, `named_failure_modes` and phase guards are the "lifted" formulas: they are
written over symbol names, not over raw English. The difference is that the symbols are
*named and denoted* rather than positional and empty, and that the `True when` clause
carries the denotation into the same artifact the oracle reads. So the accurate framing
for the ICRA paper is not "we skip lifting" — it is **"we replace anonymous lifting with
grounded naming: the AP table is retained as the decomposition NL2TL showed is necessary,
but each entry carries its own executable predicate, which makes it statically
checkable."** That is a stronger and more defensible claim than skipping the stage.

**The one place partial adoption could pay off.** NL2TL's Fig. 14 and Table 2 both say
that end-to-end translation degrades with AP count. `skill_monitor`'s *specs* carry 7–8
APs — at or past the top of NL2TL's range (max 7, mean 2.906) — even though individual
formulas use only 2–4. If generation quality is found to degrade on skills with larger AP
sets, the cheap mitigation borrowed from NL2TL is to make the two stages two *prompts*:
(1) emit the `atomic_propositions` table with its `True when` predicates, validate it
against the adapter schema, then (2) generate formulas in a second call whose context
contains only the validated AP names. That is Idea A made explicit, with grounding intact
and no placeholders anywhere. It is a prompt-decomposition change, not a lifting change.

### What evidence would settle it

A single ablation inside `skill_monitor`'s own generator, since NL2TL's does not answer
the question (its Fig. 6 confounds lifting with pre-training data volume):

- **Arm A (current):** one call, description → full spec.
- **Arm B (staged, grounded):** call 1 → AP table + predicates, validated by
  `spec_contract.validate` against the adapter schema; call 2 → formulas over validated
  names only.
- **Arm C (staged, anonymised — the literal NL2TL transfer):** call 1 → AP table; call 2
  → formulas over `prop_i`; substitute back.
- **Population:** ≥ 50 skill descriptions spanning the AP-count range 3–12, ≥ 3 seeds per
  description (NL2TL uses 3; Appendix L, p. 21).
- **Metrics:** (i) `unknown_keys` rate from the oracle — the grounding metric NL2TL has
  no equivalent of; (ii) semantic equivalence of the formula against a gold spec via
  Spot, not binary string match — NL2TL itself calls its binary metric inadequate (§8);
  (iii) accuracy stratified by AP count, replicating Fig. 14's axis.
- **Decision rule:** adopt staging only if B beats A by a margin exceeding across-seed
  variance, and adopt anonymisation only if C beats B. The prediction from this reading
  is that B ≥ A modestly at high AP counts and that C < B, because anonymisation removes
  the semantic cue (`collision_risk` vs `prop_4`) that lets the model place the symbol
  correctly and removes the oracle's ability to check it.

### What to cite NL2TL for, and where

| Claim | Cite for | Section |
|---|---|---|
| The lift-then-translate decomposition, and the name "lifted" (crediting Hsiung et al. 2021 through it) | origin of the design the field standardised on | Related Work |
| AP extraction is far easier for an LLM than joint translation — 98.84–100% vs 38.25–58.73% (Tables 2–3, p. 7) | the empirical case *for* decomposing at all, which justifies `skill_monitor`'s AP table | Related Work / Method motivation |
| APs remain ungrounded surface strings; grounding is "swapped into formatted form" by deployer rules (p. 7) | the gap `skill_monitor`'s `True when` + schema oracle closes — your positioning contrast | Introduction, and the delta paragraph |
| Binary exact-match is the metric and the authors call it inadequate (§8, p. 9) | justifying a semantic-equivalence / executability metric instead | Evaluation design |
| Cross-domain lifted pre-training reaches ~95% with 200–500 domain pairs, ~10× less than Seq2Seq (p. 8) | why finetuning-based baselines need data that a prompted pipeline does not | Related Work (contrast class) |
| 2.906 APs per formula on average, max 7 (Table 8, p. 22) | scale context — `skill_monitor` specs sit at/above the top of NL2TL's complexity range | Experimental setup |

Do **not** cite NL2TL for grounding, for validation, or for any executability claim; it
makes none. For grounding, the neighbours in this reading list (`ginsign/`, `lang2ltl/`)
are the right citations.

---

## 7. Check yourself

**Q1. In NL2TL's pipeline, what is the only piece of information shared between the GPT-3
lifting stage and the finetuned T5 translation stage?**
The placeholder index. GPT-3 produces a map `prop_i ↦ span`; T5 emits a formula over the
same `prop_i` symbols; the map is applied in reverse — "the hidden APs will be swapped
into formatted form to generate the full STL" (p. 7). The stages share no training, no
loss, and no semantic contract. Nothing checks the span means anything.

**Q2. Does NL2TL contain an ablation that isolates lifting from everything else? What
does Fig. 6 actually measure?**
No. Fig. 6 (p. 8) compares a T5 pre-trained on 28K *lifted* pairs then finetuned on
domain pairs (blue) against a T5 finetuned on domain pairs from released weights
(orange). The blue arm gets both a lifted representation *and* 28K extra examples, so the
comparison confounds representation with data volume. What it establishes is data
efficiency: "near 95% with only 200 to 500 full NL-STL examples … one magnitude less than
the Seq2Seq baselines" (p. 8). A clean lifting ablation would pre-train on the same 28K
in unlifted form; that run does not exist in the paper.

**Q3. Which single table best supports decomposing the task, and why is it stronger
evidence than the headline accuracy?**
Table 3 (p. 7): GPT-3 AP-detection accuracy 98.84 / 99.03 / 100.00% on Circuit /
Navigation / Office-email, against the same model's 38.25 / 50.51 / 58.73% end-to-end
(Table 2). It is a within-model comparison — one model, two task formulations — so it
isolates the effect of the split rather than confounding it with model choice or extra
training data, which the headline 95% figures do.

**Q4. What does NL2TL's ungrounded AP representation cost, in terms `skill_monitor`'s
validation oracle makes concrete?**
NL2TL's outputs cannot be statically checked for executability. `create_Slack` or
`signal_1_n` is a token with no denotation, so a formula can score 100% on binary
accuracy while referencing a signal the platform never publishes. `skill_monitor`'s
`spec_contract.unknown_keys` performs precisely the check NL2TL cannot: it extracts the
sensor keys from each AP's `True when` clause and diffs them against the adapter's
declared schema. NL2TL has no artifact to run such a check on, because the grounding
lives outside the spec in deployer-supplied formatting rules.

**Q5. Give the recommendation for `skill_monitor` in one sentence, plus the experiment
that would overturn it.**
Keep the grounded AP table (which already realises NL2TL's decomposition) and do not
introduce `prop_i` anonymisation, because NL2TL's two reasons for anonymity — open
cross-domain AP vocabularies and a small finetuned model's output-vocabulary burden — do
not apply to a frozen prompted model emitting over an 8-symbol schema-fixed set; the
result would be overturned if a three-arm ablation (single-call vs staged-grounded vs
staged-anonymised, ≥ 50 skills, ≥ 3 seeds, scored by Spot-based semantic equivalence and
by `unknown_keys` rate) showed the anonymised arm beating the grounded staged arm by more
than seed variance.
