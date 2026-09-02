# GinSign: Grounding Natural Language Into System Signatures for Temporal Logic Translation

William English, Chase Walker, Dominic Simon, Rickard Ewetz — University of Florida.
arXiv:2512.16770v1 [cs.CL], 18 Dec 2025. Header on every page reads "Preprint." (no venue stated).

All page numbers below refer to the arXiv PDF as paginated by the retrieval tool.

---

## 1. In one paragraph

GinSign attacks the step that almost every NL→LTL paper skips: turning the placeholder
atomic propositions (`prop_1`, `prop_2`) that a lifted translator emits into atoms that
actually mean something in a specific system. Its claim is that the field has been
scoring itself on a metric that cannot fail — a formula like `◇(prop_1 ∧ ◇prop_2)` is
"logically coherent but semantically useless" (p.2) because the APs are never defined,
so it can never be run against a trace or a model checker. GinSign fixes the target: it
assumes the system exposes a **many-sorted system signature** `S = ⟨T, P, C⟩` (types,
predicate symbols, constant symbols) and defines grounding as a total function mapping
each placeholder to a fully instantiated atom `p(c₁,…,c_m)` from that signature. The
mechanism is deliberately small: a single `bert-base-uncased` token classifier that reads
the lifted NL span plus a **prefix** — a literal enumeration of the candidate symbols
built from the signature at input time — and points at one entry. It runs hierarchically
(predicate first, then arity/type filtering, then each argument), which shrinks the label
budget from `Θ(∏_r |C_τr|)` to `Θ(|P| + Σ_r |C_τr|)` (p.6) and makes an ill-typed atom
impossible by construction. On VLTL-Bench (three domains) this gives 100% predicate-grounding
F1 in all three domains and grounded logical equivalence of 98.3 / 93.4 / 95.0 (mean ≈95.5),
against 73.6 / 59.0 / 38.8 for Lang2LTL, the only prior system that grounds at all.

## 2. Key concepts

**System signature `S = ⟨T, P, C⟩`** — "a many-sorted system signature" where "T is a set of
type symbols, P is a set of predicate symbols, and C is a set of constant symbols" (p.3).
Motivated as a generalization of PDDL / action vocabularies: "these languages are
realizations of many-sorted logical systems" (p.3). Note what is *absent*: no function
symbols, no interpreted sorts, no theory. It is three finite sets of **symbols**.

**Grounded AP vocabulary `P_S`** — the induced set of legal atoms:
`P_S = {p | p ∈ P} ∪ {p(c₁,…,c_m) | p ∈ P, cᵢ ∈ C}` (p.4, restated p.14). Either a nullary
predicate or a predicate fully instantiated with typed constants. `P_S` is **finite and
enumerable**. This single fact drives everything else in the paper, and is the crux of §6 below.

**Lifting** — token-level classification `λ : S → {0, n}` marking each token as not-part-of-any-AP
(0) or part of AP number *n* (p.3). "Eventually pick up the package from room A" → "Eventually
prop_1", with `prop_1 = "pick up the package from room A"`.

**Translation** — lifted NL → lifted LTL, `f : s → φ`. Done by a T5 model reused from prior
work (Chen et al. 2023; English et al. 2025a), p.5. GinSign contributes nothing here and
does not claim to.

**Grounding** — "a total function `g_S : {prop_1,…,prop_k} → P_S`" (p.4). *Total* is
load-bearing and under-discussed: every placeholder is assigned something. There is no
"unrepresentable on this system" outcome.

**Predicate grounding vs. argument grounding** — the hierarchical split (p.5). Stage 1 picks
`p ∈ P` (a 4–7-way choice). Stage 2, after **arity + type filtering**, picks each constant
from `C_t = {c ∈ C | type(c) = t}` (a 44–175-way choice). "type filtering eliminates invalid
atoms by construction, ensuring any predicted `p(c₁,…,c_m)` lies in `P_S`" (p.6).

**Prefix / prefix construction** — instead of a fixed softmax head with one neuron per symbol,
"we prepend a rigid, pseudo-natural prefix that enumerates the target signature and let the
encoder attend over it" (p.6). Consequence: "the class set is no longer baked into the model
parameters: supplying a different prefix instantly defines a new label universe" (p.6).
Algorithm 1 (p.16) is the whole construction — a for-loop appending every `p ∈ P`, or every
`c ∈ C` of the requested type.

**Prefix sharding + tournament** — the candidate list `L` is cut into contiguous windows of
fixed shard size `m` (m = 20, p.20). The model classifies within each shard; winners are
re-assembled into a new prefix and the process repeats "until a single element remains" (p.6).
"requires at most 5 tournaments in the case of the largest constant set (Traffic Light street
names)" (p.20). This is what lets a fixed-size head address an arbitrarily long symbol list.

**LE vs. GLE (Logical Equivalence vs. Grounded Logical Equivalence)** — LE "does not account
for AP grounding … resulting in high scores for an expression such as `prop_1 → ◇(prop_2)`,
while grounded logical equivalence demands that prop_1 and prop_2 are properly defined in
order to be scored as correct" (p.7). GLE is computed by parsing the grounded formula with
pyModelChecking (Casagrande 2024), extracting APs, and comparing against ground truth. **This
metric is arguably the paper's most durable contribution.**

**VLTL-Bench** (English et al. 2025b) — three domains (Search and Rescue, Traffic Light,
Warehouse), each with lifted NL specs, grounded LTL formulas, and reference traces. Chosen
because it is "the only resource we found that grounds natural language specifications in a
concrete state space" (p.7). Navigation, Cleanup World and GLTL are explicitly excluded as
inapplicable. **By the same first author.**

## 3. Method — concretely

Input: (a) an NL specification, (b) a system signature `S`.

1. **Lift** with a BERT token classifier (reused from prior work) → lifted NL + lifted AP spans.
2. **Translate** the lifted NL with a T5 model → lifted LTL, e.g. `◇(prop_1 ∧ ◇prop_2)`.
3. **Predicate grounding.** Build prefix `L_p = enum(P)` via Algorithm 1. Serialize
   `(x_AP, x_prefix)`. `bert-base-uncased` points at one index of the shard window. For all
   three domains `|P| ∈ {4,5,7}`, so one shard suffices and the list is `<pad>`-padded to m=20.
4. **Arity + type filtering.** Look up `arity(p̂)` and its type signature `(τ₁,…,τ_a)` in `S`.
   Argument *r*'s candidate set becomes `L_c^(r) = enum({c ∈ C | type(c) = τ_r})`.
5. **Argument grounding.** Same BERT weights, different prefix, once per argument slot,
   resolved independently. Because arity comes from the signature, "the final output always
   contains the correct number of arguments, with no need for an additional constraint or
   stopping criterion" (p.6). If `|L_c^(r)| > 20`, run the sharded tournament.
6. **Expression grounding.** Substitute the grounded atoms back into the lifted LTL →
   `◇(search(backpack) ∧ ◇deliver(backpack, loading_dock))` (Fig. 1, p.2).

Training: single-label cross-entropy over shard positions, with gold-in shards constructed
so `ℓ* ∈ W_j`. Hyperparameters (p.20): `bert-base-uncased`, LR 5e-5, 3 epochs, batch 16,
weight decay 0.01, early-stopping threshold 1e-6, patience 3, shard size m = 20. Three model
variants trained: predicate-only, argument-only, joint.

There is **no repair loop, no retry, no feedback, and no LLM at inference time** for grounding.
LLMs appear only as prompted baselines (prompt template, p.19).

## 4. Results

**Signature sizes** (Table 2, p.7): Search and Rescue |T|=2, |P|=7, |C|=44; Traffic Light
|T|=5, |P|=4, |C|=175; Warehouse |T|=2, |P|=5, |C|=82.

**Isolated grounding, F1 per AP** (Table 3, p.8) — columns Traffic Light / S&R / Warehouse:

| Method | Predicate F1 | Argument F1 |
|---|---|---|
| GPT-3.5 Turbo | 73.5 / 95.0 / 71.1 | 93.9 / 94.0 / 47.7 |
| GPT-4.1 Mini | 76.4 / 87.7 / 98.4 | 94.8 / 90.9 / 51.6 |
| GPT-4o | 85.9 / 94.9 / 82.4 | 87.0 / 95.1 / 70.3 |
| Lang2LTL † | — | 86.2 / 77.6 / 61.8 |
| **GinSign** | **100.0 / 100.0 / 100.0** | **97.9 / 91.1 / 94.2** |

† Lang2LTL does not separate predicate from argument grounding; its overall AP grounding is
reported in the argument column.

**End-to-end translation** (Table 4, p.8), LE % / GLE %:

| Baseline | Traffic Light | Search & Rescue | Warehouse |
|---|---|---|---|
| NL2LTL (GPT-4.1) | 43.6 / 38.4 | 41.8 / 35.4 | 42.6 / 26.2 |
| NL2TL | 98.7 / 60.1 | 95.0 / 54.4 | 99.0 / 46.2 |
| Lang2LTL | 100.0 / 73.6 | 100.0 / 59.0 | 100.0 / 38.8 |
| **GinSign** | **100.0 / 98.3** | **100.0 / 93.4** | **100.0 / 95.0** |

**What the metrics actually measure.** LE compares temporal-operator structure over
placeholder atoms — it is saturated (95–100%) for every lifting-based pipeline, so it
discriminates nothing on this benchmark. All the signal is in GLE, which additionally requires
each AP to resolve to the correct element of `P_S`. GLE is *string/symbol identity of the
grounded atoms plus logical equivalence of the formula*, checked via pyModelChecking. It does
**not** measure whether the atom is true on the robot, whether the predicate is computable, or
whether the threshold behind it is right — there is no threshold.

**OOD ablations.** Table 5 (p.9), intra-domain OOD: models trained on *partial* signatures and
tested on held-out predicates/constants. Joint model: predicate Acc/F1 83.1/80.3 (TL),
92.7/85.5 (S&R), 85.1/73.0 (Warehouse); argument 99.9/99.5, 99.1/96.2, 94.2/**66.7**. Table 6
(p.9), cross-domain OOD: train on two domains, test on the third. Diagonal (held-out domain)
argument F1 for the joint model: 68.2 (TL), 61.4 (S&R), 65.4 (Warehouse).

**Read this carefully.** The headline "100.0 predicate grounding" is in-distribution. Under OOD
the same task drops to 73.0–85.5 F1 (Table 5) and constant grounding drops to 61–68 F1
(Table 6 diagonals). The paper describes these as "respectable F1 scores" and "promising
out-of-distribution accuracy — comparable to in-domain performance" (p.6). 66.7 vs 94.2 is not
comparable to in-domain performance. The generalization story is real but considerably weaker
than the abstract implies.

**Error analysis** (p.10): Warehouse is the hard domain — mean argument F1 across all approaches
63.8% there vs >90% on the other two — because "the diverse natural-language references to the
item arguments make them difficult to ground," and LLM baselines "often failed to identify
correct constants on the signature given in the input."

**Arithmetic check on the headline.** The abstract claims "grounded logical-equivalence scores
of 95.5%, a 1.4× improvement over SOTA" (p.1). mean(98.3, 93.4, 95.0) = 95.57, so 95.5 is the
domain mean. But mean Lang2LTL GLE is (73.6+59.0+38.8)/3 = 57.1, giving 1.67×; per-domain
ratios are 1.34×, 1.58×, 2.45×. The intro says "up to 1.4×" (p.2) while §5.3 says Warehouse is
"more than a 2.4× absolute gain" (p.9) — which is a ratio, not an absolute gain. The 1.4×
figure does not correspond to any comparison I can reconstruct. Flag this if you cite the number;
cite the table, not the abstract.

## 5. Limitations

**What the authors admit** (all p.10, verbatim):

> "GinSign was tested only on VLTL-Bench, whose signatures may not reflect larger or evolving systems."

> "The framework handles propositional LTL; extending it to metric or first-order variants will require grounding for numbers, time bounds, and quantifiers."

> "Constant-level grounding remains the accuracy bottleneck, especially when names are ambiguous, and the method assumes the signature is fixed at inference."

Future work they name: richer benchmarks; retrieval- or interaction-based grounding for large
constant sets; "mechanisms that adapt to signature updates without retraining."

**What they don't admit:**

1. **`g_S` is a total function.** Every placeholder is forced onto some element of `P_S`.
   There is no reject, no abstain, no confidence gate, no "this requirement is not expressible
   on this system." For a safety monitor this is the wrong default — an unrepresentable
   requirement is silently coerced onto the nearest available atom and then scored as a
   grounded, model-checkable formula. Nothing downstream can tell the difference.
2. **The constants are a detector's label set.** The Warehouse `Item` type (p.18) is
   recognizably the COCO/PASCAL object-detection vocabulary — `aeroplane, apple, backpack,
   banana, baseball_bat, … , wine_glass, zebra`, 80-ish classes. (My inference from the list,
   not their claim; but the conclusion's phrase "outperforms them on visually oriented domains,"
   p.10, points the same way.) The reason GinSign never needs numbers is that its grounding
   bottoms out where a perception stack *already emits a symbol*. It grounds NL → symbol; it
   does not ground symbol → computation over sensor state.
3. **The Kripke labeling `L` is assumed, never produced.** §2.1 (p.3) is explicit that
   verification needs `M = (S, S₀, R, L)` with `L : S → 2^P`, and that "the syntactic formula
   only becomes semantically testable once its APs are linked to concrete predicates over system
   states." GinSign links APs to *signature symbols*, not to concrete predicates over states.
   Someone else still has to write `L`. This is the same gap the paper accuses others of, moved
   one level down.
4. **Predicates are actions, not observations.** Across all three signatures (pp.17–18) the
   predicate sets are `avoid, communicate, deliver_aid, get_help, go_home, photo, record,
   change, deliver, pickup, search, idle` — imperatives the robot performs. A runtime monitor
   needs observation atoms whose truth is read off the sensor stream. The paper never
   distinguishes the two, and the benchmark contains no examples of the latter.
5. **Self-benchmarking.** The only dataset (VLTL-Bench, English et al. 2025b) and the lifting/
   translation models (English et al. 2025a) are by the same first author. LE saturates at 100%,
   so the benchmark's temporal structure carries no discriminative load.
6. **Reported variance.** §5.1 says "we report the mean, variance, and confidence of each
   metric" (p.7), but Tables 3–6 as rendered show point estimates only. *Not verified* whether
   variance/CIs appear elsewhere; I did not find them in the retrieved pages.
7. **No robot.** *Not verified* — I found no mention of any physical platform, ROS, hardware
   trial, online monitoring, latency, or inference-cost measurement anywhere in the retrieved
   text. Evaluation is offline text→formula against reference traces.

---

## 6. For skill_monitor

### THE question: exactly what can a system signature contain, and could it express a depth-camera predicate?

**Short answer: no, and not by a small margin. The gap is structural, and the authors concede it
in one sentence.**

**Exactly what `S = ⟨T, P, C⟩` can contain.** Three finite sets of *symbols* (p.3, p.14):

- `T` — type symbols. Uninterpreted sort names: `Item`, `Location`, `Person`, `Hazard`, `Light`,
  `Color`, `Road`, `Vehicle`. Sorts only; no sort is a number sort.
- `P` — predicate symbols, each with `arity(p)` and a type signature `(τ₁,…,τ_m) ∈ T^m`.
- `C` — constant symbols, each with `type(c) ∈ T`. Enumerated by name.

And the induced atom vocabulary `P_S = {p} ∪ {p(c₁,…,c_m)}` — nullary predicates, or predicates
saturated with *named constants*. That is the whole expressive universe.

**Now count what is missing, relative to `min_range < 0.25`:**

1. **No function symbols.** A textbook many-sorted signature is `⟨sorts, functions, predicates⟩`.
   GinSign's has no function component at all. So there is no term `min_range` — no way to write
   a symbol whose denotation is a *value read from the state*, as opposed to a fixed named object.
   `min_range` is not a constant like `backpack`; it is a state-dependent quantity, and the
   signature has no slot for one.
2. **No numeric sort and no interpreted theory.** `<` is not in the LTL grammar (p.3:
   `φ ::= π | ¬φ | φ₁∧φ₂ | φ₁∨φ₂ | φ₁⇒φ₂ | ○φ | ◇φ | □φ | φ₁ U φ₂`) and not in `P` unless
   someone declares a predicate named `less_than` — which would then need two arguments drawn
   from `C`, i.e. two *enumerated* numbers.
3. **`C` must be enumerable, because Algorithm 1 enumerates it.** The entire architecture — prefix
   construction (p.16), sharding, the tournament — is a *closed-set pointer over a listed
   inventory*. You cannot list ℝ. `0.25` is not a member of any prefix that Algorithm 1 can build.
4. **Nothing numeric occurs anywhere in the benchmark.** All 301 constants across the three
   signatures (Appendix A.4, pp.17–18) are lexical entity names. Zero numerals, zero units, zero
   thresholds.

**The three encodings you could attempt, and why each is a concession, not a solution:**

- *(a) Collapse to a nullary predicate.* Add `collision_risk()` to `P`. GinSign will happily
  ground "when an obstacle is too close" onto it. But the `0.25` now lives entirely outside the
  signature, hand-coded in whatever implements `L : S → 2^P`. GinSign has grounded the sentence
  to a **symbol**; the semantics remain unwritten. This is precisely the labour skill_monitor
  automates.
- *(b) Discretize into named bands.* Declare type `Proximity` with constants `very_close, close,
  far` and predicate `range_is(Proximity)`. You have replaced a continuum with a hand-chosen
  partition, per task, per sensor, up front — and every retune ("0.25 → 0.30") is a signature
  edit, which their own limitation says the method "assumes is fixed at inference."
- *(c) Enumerate thresholds as constants.* Type `Distance` with `d_0_25, d_0_30, …` and predicate
  `range_below(Distance)`. Combinatorially absurd, and it makes the grounding model choose a
  float by lexical similarity — the exact failure mode their Warehouse results show is weakest
  (argument F1 down to 62.6–66.7 when names don't match surface text, Table 5, p.9).

**The concession, verbatim (p.10) — this is your differentiation paragraph's anchor:**

> "The framework handles propositional LTL; extending it to metric or first-order variants will require grounding for numbers, time bounds, and quantifiers."

That single sentence rules out, on their own account: numeric thresholds, timing bounds, and
quantification. skill_monitor's spec contains all three (`min_range < 0.25`; per-phase timing
bounds; invariants that hold over a phase).

**Concretely, about a depth camera — what a system signature CANNOT express:**

- `min_range < 0.25` — any comparison of a real-valued reading to a literal.
- `depth_valid_fraction > 0.6` — any ratio or derived quantity.
- `abs(goal_dist - prev_goal_dist) < 0.01` — arithmetic between two sensor fields (progress stall).
- "no obstacle within 0.5 m in any direction" — quantification over a field.
- "must hold for 2.0 s", "within 5 s of phase entry" — metric time bounds.
- Any predicate whose truth is a function of a value that is not a pre-listed name.
- Any threshold the operator tunes at deploy time without re-authoring the signature.

**What it CAN express about a depth camera:** `camera_ok()`; `obstacle_detected(front)` where
`front ∈ C`; `photo(nearest_debris)`; `search(backpack)`. In each case only *after* someone has
written the code that turns depth into a boolean symbol. The signature is a vocabulary of
already-symbolic system outputs.

**What would have to change for GinSign to reach `min_range < 0.25`:** a numeric sort in `T`;
function symbols added to the signature (a fourth component `F`); an interpreted theory of linear
arithmetic so `<` and `≤` are available; grounding for numeric literals — which is *span→float
extraction*, a generation/regression problem, not a pointer into an enumerated list. That last
one breaks the paper's central architectural bet. The whole reason a 110M-param BERT can beat
GPT-4o here (Table 3) is that the answer is always one of *N* listed items. Numbers are not.

**Where GinSign is genuinely stronger — do not pretend otherwise:**

1. **By-construction well-typedness beats generate-validate-repair.** "type filtering eliminates
   invalid atoms by construction, ensuring any predicted `p(c₁,…,c_m)` lies in `P_S`" (p.6).
   GinSign *cannot emit* an out-of-vocabulary atom. skill_monitor emits, then checks in
   `skill_monitor/core/spec_contract.py`, then repairs, with max 2 attempts — and can exhaust
   them. A reviewer will say: "they get for free what you get by retry." **Your answer:**
   by-construction is available to them only because `P_S` is finite and enumerated. Over
   arbitrary Python expressions the space is unbounded and by-construction is not on the table;
   a *sound static check over free variables* is the correct tool, and yours is sound (an
   undeclared key would raise `NameError` at runtime, so the check cannot produce a false
   negative). Also note the asymmetry cuts back: their guarantee covers *membership only*, never
   *correctness*. Argument grounding is 91.1–97.9 F1 in-domain, so roughly 1 AP in 20 is grounded
   to the wrong constant, and no oracle in their pipeline can detect it. Your contract checks a
   property that is decidable; theirs guarantees a property that is trivially satisfiable.
2. **Measured compositional generalization.** Tables 5 and 6 (p.9) — same weights, swap the
   prefix, transfer to held-out symbols and held-out domains. Your adapter-schema swap is
   architecturally the same idea (schema as input, not as weights), but you have *no numbers*
   for cross-embodiment transfer. This is the strongest thing they have that you don't. Get an
   analogous ablation into the ICRA paper: same generator, two adapter schemas, report
   contract-pass rate on each.
3. **Cost.** `bert-base-uncased`, 3 epochs, batch 16 (p.20), no LLM at inference. You call an LLM
   at generation with up to 2 repair attempts. Their point that "smaller masked language models"
   suffice and this "eliminates the reliance on expensive LLMs" (p.1) is well made — for their
   task shape.
4. **Evaluation discipline.** GLE via pyModelChecking against reference traces, not string match.
   Reviewers respect this. Adopt it or explain why not.
5. **They own the framing.** "these systems either explicitly assume access to accurate atom
   grounding or suffer from low grounded translation accuracy" (p.1). If you write the same
   sentence in your intro, you are restating GinSign. Position *past* it.

**Where their paper concedes ground to you — cite these:**

- Numbers, time bounds, quantifiers: out of scope, stated (p.10). **Your entire AP language.**
- "the method assumes the signature is fixed at inference" (p.10), with "adapt to signature
  updates without retraining" listed as future work. Your adapter schema is discovered at runtime
  off a latched ROS topic, per embodiment, not authored per task. *Be precise and fair here*: their
  prefix is read at input time (Algorithm 1) and Table 6 shows cross-domain transfer, so the
  claim "GinSign needs retraining for a new signature" is **false** and will be caught. The honest
  claim is: GinSign assumes a signature is *authored and handed to it*; skill_monitor *obtains*
  the schema from the robot itself.
- "tested only on VLTL-Bench" (p.10); no robot, no ROS, no hardware, no latency (*not verified* —
  I found no such content, having queried for it explicitly). You deploy on a Unitree G1 running
  TRAV under ROS 2. That is a category of evidence they have none of.
- `g_S` is total (p.4): no reject path. Your contract can *fail a spec*. For a safety monitor,
  the ability to say "this requirement is not expressible over this robot's sensors" is a
  feature, and GinSign structurally lacks it. **This is your cleanest structural argument and it
  is not in their limitations section.**
- Constant grounding degrades hard under lexical mismatch (Warehouse 94.2 → 66.7 F1 on held-out
  constants). Sensor keys are exactly lexically-arbitrary identifiers (`min_range`,
  `depth_valid_fraction`, `goal_dist`). Their weakest regime is your normal one.

**One reviewer question to pre-answer.** "GinSign shows a 110M-param BERT beating GPT-4o at
grounding — why do you need an LLM?" Answer with their own result: their classifier works
*because* the target is closed-set. Your target — an executable expression over a
runtime-discovered schema, with thresholds — is open-set generation, which is why a sound static
contract plus repair, rather than a classifier plus type filter, is the right architecture. Their
Table 3 is evidence *for* your framing, not against it.

**A second one to prepare for.** `eval` on an LLM-produced string is a soundness and safety
target. GinSign never executes anything. Have the answer ready: no builtins in the eval
namespace, free variables statically checked against the schema, structural validation before
the engine ever sees the spec.

### What to cite it for, and where

- **Related work, "grounding" paragraph.** The closest prior work and the strongest reported
  grounded NL→LTL result. Cite Table 4 for the numbers, not the abstract's 1.4×.
- **Introduction / differentiation paragraph.** Quote the limitation sentence (p.10) directly.
  One sentence: *"The closest work grounds APs into a many-sorted signature ⟨T,P,C⟩ of typed
  predicates over enumerated constants, and states that numbers, time bounds and quantifiers are
  out of scope [GinSign]; skill_monitor's APs are threshold predicates over a runtime-discovered
  real-valued sensor schema, which that formalism cannot represent."*
- **Method section, terminology.** Adopt their lifting / translation / grounding decomposition
  (§2.3, pp.3–4) — it is clean and now standard, and using it makes your contribution legible as
  "a different grounding target."
- **Evaluation section.** Cite GLE as the metric you are extending: they check that an AP resolves
  to a legal *symbol*; you check that an AP resolves to an *executable predicate over declared
  sensor fields*. Frame yours as GLE plus executability.
- **Do NOT** cite it as a baseline you beat. Different task, different data, no shared benchmark;
  a head-to-head number would be indefensible. Frame as complementary points on one axis:
  symbolic-entity grounding (GinSign) vs. numeric-sensor grounding (skill_monitor).

---

## 7. Check yourself

**Q1. Write down `P_S` for the Warehouse signature and say how large it is.**
`P_S = {get_help(), idle()} ∪ {pickup(i), search(i) | i ∈ Item} ∪ {deliver(i,l) | i ∈ Item,
l ∈ Location}`. With |Item| = 80 and |Location| = 2 (`shelf`, `loading_dock`), that is
2 + 160 + 160 = 322 ground atoms. Finite, enumerable, and every element is a symbol — which is
why a classifier can point at one.

**Q2. Why can't `min_range < 0.25` be an element of `P_S`, even if you add a predicate for it?**
Because `P_S` admits only `p` or `p(c₁,…,c_m)` with `cᵢ ∈ C`, and `C` is a finite enumerated list
of named symbols. `min_range` would have to be a function symbol (the signature has no function
component), `<` an interpreted relation (there is no theory), and `0.25` a member of an
enumerated constant set (Algorithm 1 builds the prefix by iterating `C`; ℝ cannot be iterated).
You can only fake it by pre-discretizing into named bands, moving the number outside the signature.

**Q3. GinSign reports 100.0 F1 on predicate grounding. Under what condition does that number
hold, and what is it under the other condition?**
In-distribution — the predicate was seen during training (Table 3, p.8). On held-out predicates
within the same domain it is 73.0–85.5 F1 (Table 5, joint model, p.9), and cross-domain argument
F1 on the held-out domain drops to 61.4–68.2 (Table 6 diagonals). The paper calls this
"comparable to in-domain performance" (p.6); it isn't.

**Q4. `g_S` is defined as a *total* function. Name one safety consequence.**
Every lifted placeholder is mapped to some element of `P_S`, so a requirement that the system
cannot express is silently coerced onto the nearest available atom and then emitted as a
well-typed, model-checkable formula. There is no abstain, no confidence gate, no failure signal.
A monitor built this way cannot distinguish "the robot satisfies this" from "we grounded your
requirement to something else." skill_monitor's contract, by contrast, can reject a spec.

**Q5. A reviewer says: "GinSign guarantees valid atoms by construction; your system only checks
afterwards and retries. Why is yours better?" Give the two-part answer.**
(i) By-construction is only available when the atom space is finite and enumerated. Over
arbitrary threshold expressions the space is unbounded, so the right instrument is a *sound*
static check on free variables against the declared schema — which is what `spec_contract.py`
does, and it cannot produce a false negative because an undeclared key would raise `NameError`
at runtime. (ii) Their guarantee is only about *membership*, never *correctness*: at 91.1–97.9
argument F1 they ground roughly 1 AP in 20 to the wrong constant, and nothing in their pipeline
detects it. Membership-by-construction and soundness-of-check are guarantees about different
properties; theirs is the weaker property, cheaply obtained.
