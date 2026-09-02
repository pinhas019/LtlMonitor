# Structured Feedback Improves Repair in an LLM Agent Loop (VeriHarness)

Jaideep Ray, Ankit Goyal. arXiv:2607.14167v1 [cs.SE], 15 July 2026.
Read via alphaXiv PDF query; all numbers below are quoted from the paper's own tables and text.

---

## 1. What the paper does

The paper attacks one narrow, under-specified interface in agent loops: after an external
validator rejects a candidate, *what exactly should the validator hand to the next model
call?* The authors build **VeriHarness**, a code-as-control-plane harness in which the LLM
only proposes candidates and external gates alone decide acceptance, enforce a call budget,
and persist every prompt/response/gate-result. They then hold task, model, gate, and call cap
fixed and vary only the failure-feedback payload across four policies, from a bare validator
error message up to a message carrying the failure **location**, the **observed** value, and
the **admissible alternatives**. On 50 paired TextWorld games under a four-call cap, the
three-field feedback raises terminal success by 44 percentage points for Qwen2.5-Coder-14B
and 42 points for Llama-3.1-8B. Ablations localize almost the entire gain in the *admissible
alternatives* field: location + observed value alone performs near the raw-diagnostic
baseline, and rendering the same three values as prose instead of a keyed JSON record loses
essentially nothing. The takeaway is a design rule for validators: return what you know about
the failure -- especially the legal replacements -- not just a rejection.

---

## 2. Key concepts

| Term | Definition (as used in the paper) |
|---|---|
| **VeriHarness** | The authors' code-as-harness prototype. A principal orchestrator builds a compact state pack, dispatches bounded LLM workers, and runs external gates (schema, artifact, environment). "Only gates accept a candidate; a worker's self-assessment cannot do so." Every prompt, raw response, parsed output, gate result, model setting, and elapsed time is persisted before the next call. |
| **Model / validator / agent loop** | Their three defined terms. *Model* = the LLM called to produce one candidate. *Validator* = external code returning pass-or-failure-description. *Agent loop* = the bounded sequence model -> validator -> feedback, repeated until pass or budget exhaustion. |
| **Repair** | A new model candidate produced *after* a validator rejects an earlier one. The new candidate receives the failure feedback but must still pass the external validator -- the model never accepts its own answer. |
| **Failure encoder** | The component that maps gate-specific details onto a common interface: a stable failure label, the location, the observed value, and the admissible alternatives. This is the paper's real contribution as a piece of engineering. |
| **"Structured"** (their definition) | Explicitly: *"structured means explicit repair components -- location, expected alternatives, and observation -- whether rendered as prose or a keyed record."* Structure is **semantic content**, not syntax. This is the paper's central terminological move. |
| **The three repair fields** | **location** (where in the candidate the failure sits, e.g. `LeafOutput.answer.commands[1]`), **observed** (the rejected value, e.g. `open chest`), **expected** (the enumerated admissible alternatives). |
| **Feedback policies** | `RawDiag` (validator's original error, no repair fields); `SameNL` (all three values, in prose, no keys/labels); `LocObs` (keyed label + location + observed, **no** alternatives); `TypedFields` (keyed label + all three fields). |
| **Oracle-blind evaluation** | Hidden post-hoc outcomes are excluded from repair feedback -- the repair loop may only see what the visible validator exposes. |
| **Repair opportunity** | A run in which the first candidate actually fails the *visible* validator, so feedback has something to act on. Their HumanEval lane produced zero of these, which is the point of that lane. |

---

## 3. Method

**Harness.** Generation is separated from acceptance (their Fig. 1): task + compact state ->
LLM worker -> candidate -> external gates; on failure the failure encoder produces repair
feedback that becomes the next call's input; code (not the prompt) holds durable state,
counts calls, and enforces the budget. Their justification: a prompt-only loop makes the
model remember workflow state, count its own calls, and judge its own completion, and those
duties compete with candidate generation.

**Primary task.** 50 generated TextWorld games, seeds 20261051-20261100, each with three
rooms, four objects, and a two-step quest. A candidate is a JSON plan of at most four
commands, executed from fresh state; success requires a terminal win. On an invalid action
the environment returns the action's index and **up to the first 12 admissible commands in
the environment's deterministic order** -- deliberately neither ranked nor randomized.
Primary matrix: 50 games x 4 policies x 2 models = 400 rows.

**Models and decoding.** Qwen2.5-Coder-14B-Instruct-AWQ on an NVIDIA L4 and
Meta-Llama-3.1-8B-Instruct-AWQ-INT4 on a T4, both served by vLLM. Primary decoding greedy,
512 output tokens, four-call cap. Model conditions never mixed across serving backends.

**Ablation logic** (this is the part worth copying):
- `RawDiag` vs `SameNL` -- measures adding all three repair values to the raw message.
- `SameNL` vs `TypedFields` -- repair values held identical, so this isolates *keyed
  presentation + stable label*.
- `LocObs` vs `TypedFields` -- keyed format held identical, so this isolates *the alternatives*.

**Robustness lanes.** (a) budget sweep at B = 2, 4, 6, 8 on a 15-game subset, both models,
RawDiag vs TypedFields; (b) sampled decoding -- Qwen, 20 games, temperature 0.3, top-p 0.9,
three inference seeds (3101-3103), comparing RawDiag/SameNL/TypedFields; (c) a 15-task
HumanEval scope check exposing one deterministically selected public assertion to the repair
gate while the full official tests score the final answer only. Totals: 880 rows,
2,652 realized LLM calls.

**Statistics.** Games paired by seed; 10,000 paired bootstrap samples; two-sided exact
McNemar; Holm correction over four planned contrasts per model. Sampled-decoding intervals
resample 20 game clusters; p-values from 100,000 game-level sign flips.

---

## 4. Results

**Primary (50 paired games, budget 4) -- terminal success and total calls:**

| Policy | Qwen-14B solved | Qwen calls | Llama-8B solved | Llama calls |
|---|---|---|---|---|
| RawDiag | 14 (28%) | 164 | 8 (16%) | 179 |
| LocObs | 18 (36%) | 155 | 9 (18%) | 174 |
| SameNL | 35 (70%) | 147 | 29 (58%) | 161 |
| TypedFields | 36 (72%) | 130 | 29 (58%) | 149 |

**Headline.** TypedFields over RawDiag: **+44 points** for Qwen (95% CI 28-60, Holm-adjusted
exact p = 3.15e-5) and **+42 points** for Llama (28-56, p = 3.81e-6).

**Paired contrasts (Table 3):**

| Model | Contrast | Delta (points) | 95% CI | p (Holm) |
|---|---|---|---|---|
| Qwen | SameNL vs raw | +42 | [28, 56] | 3.8e-6 |
| Qwen | Typed vs SameNL | **+2** | [-8, 12] | 1.0 |
| Qwen | Typed vs LocObs | +36 | [20, 52] | 2.4e-4 |
| Llama | SameNL vs raw | +42 | [28, 56] | 3.8e-6 |
| Llama | Typed vs SameNL | **0** | [-12, 12] | 1.0 |
| Llama | Typed vs LocObs | +40 | [26, 54] | 2.2e-5 |

So: **the alternatives carry the gain; the JSON keys do not.** Adding alternatives to LocObs
is worth +36/+40 points. Switching prose -> keyed record with identical values is worth +2/0.

**Mechanism check.** Final invalid-action episodes fall from 35 -> 2 (Qwen) and 41 -> 4 (Llama)
going from RawDiag to SameNL. The gain is not a first-call artifact: first-call terminal wins
across RawDiag/LocObs/SameNL/TypedFields are 8, 11, 9, 9 (Qwen) and 6, 8, 6, 7 (Llama) --
typed and raw differ by one first-call win per model against final gaps of 22 and 21 wins.

**Efficiency.** TypedFields uses 17 fewer calls than SameNL for Qwen (paired mean -0.34
calls/game, CI -0.60 to -0.06) and 12 fewer for Llama (-0.24, -0.44 to -0.04). Per-retry
prompts are about the same size (701 vs 716 words Qwen; 706 vs 722 Llama); total realized
prompt words are 14% and 10% lower for typed because it makes fewer calls.

**Budget sensitivity (15 games, raw/typed wins):**

| Model | B = 2 | B = 4 | B = 6 | B = 8 |
|---|---|---|---|---|
| Qwen | 5/8 | 4/11 | 4/11 | 4/12 |
| Llama | 1/5 | 2/9 | 2/11 | 2/11 |

Typed-minus-raw gains rise from 20 and 27 points at B=2 to 47 points for both models at B=4;
Llama reaches 60 points at B=6 and B=8. **RawDiag is flat from budget 4 through 8** (4/15
Qwen, 2/15 Llama). Extra calls only pay off when the retry receives new information.

**Sampled decoding.** Seeds 3101-3103, 20 games: RawDiag 6/6/5, SameNL 14/13/14,
TypedFields 14/16/14. Clustered: typed vs raw +45 points (CI 23-67, Holm p = .0053); typed vs
repair-value-matched prose +5 points (-3 to 15, p = .499). Same ordering.

**HumanEval scope check.** For Qwen the first answer passed the visible test on all 15 tasks,
so **no repair opportunity ever arose** and every policy stopped after one call, finishing
14/15 (the one failure passes the visible test but fails a hidden test, so no feedback policy
could detect it). The authors explicitly refuse to read this as evidence about code repair.

---

## 5. Limitations

Stated by the authors:
- 50 generated TextWorld games, two quantized models, one serving stack. No repository-scale
  repair, no production agent system.
- Sampled decoding covers Qwen only, three seeds. HumanEval lane is 15 tasks.
- Alternatives capped at 12 in TextWorld's own order. **Longer, ranked, and randomized lists
  were not tested** -- so the paper says nothing about how to *order* or *truncate* an
  alternatives list.
- The `TypedFields` vs `SameNL` contrast is not a pure punctuation-only contrast: the keyed
  policy also carries a stable failure label and different framing text.
- The first-call context names the policy, so a byte-identical pre-repair prompt was impossible.
- Prompt size measured in transcript words, not model tokens. One serving error was rerun and
  only the replacement run is included.
- Feedback cannot help when the visible validator does not expose the real failure (the
  HumanEval finding).

**Transfer to spec repair -- read this carefully, because the paper's framing is misleading.**
The title says "repair" and the CCS concepts say software engineering, but **the paper has
essentially no code-repair evidence**. Its one code lane produced zero repair opportunities.
The positive result is *text-game action-plan repair*: a JSON plan whose elements are drawn
from a small enumerable set of legal values, checked by a complete deterministic oracle.

That is actually a *closer* analogue to `skill_monitor` than code repair is:

- `spec_contract` is a deterministic, complete oracle **for the property it checks** --
  schema conformance and AP declaration are fully decidable, and the failure is fully exposed.
- The legal alternatives are genuinely enumerable: `schema_keys` for `unknown_keys`, and
  `set(spec["atomic_propositions"])` for `undeclared_aps`. That is exactly the condition the
  paper says makes the `expected` field possible.
- The candidate is a JSON object with addressable paths, so `location` at
  `LeafOutput.answer.commands[1]` granularity is directly reproducible as
  `ltl_formulas[0].formula` or `execution_phases[2].invariant`.

The honest caveat runs the other way: `spec_contract.validate` only certifies that the spec is
*executable*, never that it is a *faithful* monitor for the skill description. Semantic
wrongness is exactly the paper's HumanEval hidden-test case -- no feedback format repairs it,
and a spec that passes `validate` is not thereby correct. Do not let a 0-problem repair loop
read as a correctness claim in the ICRA paper.

Two further caveats specific to the port: the paper's models are a 14B and an 8B quantized
open model, and gains of this size are typically smaller on a stronger model; and their
candidates are <=4-command plans, far smaller than a full monitoring spec, so nothing here
speaks to repairing a large artifact where the model must also preserve unmentioned content.

---

## 6. For skill_monitor -- PROMPT AUDIT

### 6.0 What is being audited

`REPAIR_PROMPT`, `/home/user/LtlMonitor/skill_monitor/describer/generate_formulas.py:570`,
verbatim:

```python
REPAIR_PROMPT = """The specification you produced cannot run on this robot. Each
problem below was found by a mechanical check, not an opinion:

{problems}

{schema}

Return the SAME specification with only those problems fixed, as a single valid JSON
object. Keep every atomic proposition, formula and phase that was not named above
exactly as it was. Respond ONLY with the JSON object."""
```

and its call site (`generate_formulas.py:599-605`):

```python
prompt = (
    formulas_prompt(skill_desc, schema) if attempt == 0 else
    REPAIR_PROMPT.format(problems="\n".join(f"  - {p}" for p in problems),
                         schema=schema_prompt(schema))
    + "\n\nThe specification:\n" + json.dumps(spec, indent=2)
)
```

The `{problems}` strings come from `spec_contract.validate`
(`/home/user/LtlMonitor/skill_monitor/core/spec_contract.py:117-130`), and there are exactly
three shapes:

```python
# A -- spec_contract.py:124
f"atomic proposition '{ap}' references sensor field(s) "
f"{sorted(missing)} which this robot does not provide; "
f"available fields are: {sorted(schema_keys)}"

# B -- spec_contract.py:106
f"'{ap}' is used in a formula/phase/terminal condition but is not declared "
f"in atomic_propositions"

# C -- spec_contract.py:112
"spec declares no atomic propositions"
```

### 6.1 What the paper actually recommends

| Dimension | Paper's finding | Strength of evidence |
|---|---|---|
| **Granularity -- location** | Report *where* the failure is, at element granularity (`commands[1]`, not "the plan"). | Necessary but far from sufficient: `LocObs` has location and sits at 36%/18% vs raw's 28%/16%. |
| **Granularity -- observed** | Report the rejected value verbatim. | Same bucket as location; the two together are near-baseline. |
| **Granularity -- expected** | **Enumerate the admissible alternatives whenever they can be enumerated.** This is the finding. | Strongest result in the paper: +36 (Qwen) / +40 (Llama) points for adding alternatives to an otherwise identical keyed message. |
| **Ordering of alternatives** | **Untested.** They used the environment's deterministic order, capped at 12, and list "longer, ranked, or randomized lists" as untested. | No evidence either way. |
| **Include the failing artifact?** | Held constant, not manipulated: "All four retries also include the rejected plan and common output instructions." | Not evidence *for* including it; evidence that the +42 gain is *on top of* already including it. |
| **Say which check produced the problem?** | The stable failure label (`textworld.action_invalid`) exists only in the keyed policies, and `TypedFields` vs `SameNL` is +2 / 0 with p = 1.0. | No demonstrated success benefit. The authors recommend keys/labels for *logging, routing, cross-gate tooling*, and note a modest call-count saving -- not for model reasoning. |
| **Suggest a fix?** | Not tested. The paper supplies *the set of legal values*, which is not the same as recommending one. Their own framing: feedback helps by "turning a general rejection into a specific change that the model can make and the validator can check." | Enumeration is supported; a *ranked recommendation* is not evaluated. |
| **JSON vs prose** | No evidence that JSON syntax improves repair. Prose with the same values reaches nearly the same success. | Two null contrasts with tight CIs ([-8,12], [-12,12]). |
| **Call budget** | Extra calls only pay when the retry gets new information. RawDiag flat from B=4 to B=8; typed keeps climbing. Typed-minus-raw gain is smallest at B=2 (20/27 points) and doubles at B=4 (47 points). | Small subset (15 games), reported as counts. |

### 6.2 Audit of `REPAIR_PROMPT`

**What it already does right -- more than the paper's baseline, and in several places already
at the paper's best policy.**

1. **Problem A is already a full three-field message in prose -- i.e. `SameNL`.** It names the
   location (`atomic proposition 'X'`), the observed value (`references sensor field(s)
   ['distance_to_target']`), and the enumerated admissible alternatives (`available fields
   are: [...]`). This is precisely the payload the paper measures at +42 points over a raw
   diagnostic. Given `Typed vs SameNL = +2/0`, the prose rendering costs essentially nothing.
   **No change needed here.**
2. **The failing artifact is included** (`+ "\n\nThe specification:\n" + json.dumps(spec, ...)`),
   matching the constant held across all four of the paper's policies.
3. **The schema block is re-sent on every repair call** via `schema_prompt(schema)`, so the
   global vocabulary of legal sensor fields is always present, and the concrete
   `"True when ..."` examples give the model the target shape.
4. **The preservation instruction** ("Keep every atomic proposition, formula and phase that
   was not named above exactly as it was") has no analogue in the paper -- their candidates are
   <=4-command plans -- but it is the right defensive move for a large artifact and nothing in
   the paper argues against it.
5. **Problems are deterministically ordered** (`sorted(...)` in both `unknown_keys` and
   `undeclared_aps` iteration), which is reproducible. The paper has no ordering evidence, so
   this is neither endorsed nor criticized -- keep it for determinism's sake.

**What is missing -- one real gap, and it is the exact gap the paper's ablation isolates.**

6. **Problem B (`undeclared_aps`) is a `LocObs`-shaped message: location + observed, no
   `expected` field.** It says an AP is used but not declared, and stops. It never enumerates
   what the model could legally use instead. The paper's `LocObs` policy solved 18/50 and 9/50
   -- within noise of the raw baseline -- and adding the alternatives to it was worth +36/+40
   points. This is the highest-value change available, and the information is free: the legal
   alternatives are `sorted(spec["atomic_propositions"])`, already computed as `declared` at
   `spec_contract.py:75`. It is also arguably the *more* important failure of the two, since
   an undeclared AP is "silently always-false at runtime" per the module's own docstring.
7. **Problem B's location is coarse.** "used in a formula/phase/terminal condition" names the
   AP but not *which* formula, phase, or field. The paper's location granularity is
   `LeafOutput.answer.commands[1]`. The `scan()` walk at `spec_contract.py:84-93` already
   visits every site by name and could record it at no cost.
8. **Problem C is a `RawDiag`-shaped message** -- no location, no observed value, no
   alternatives. It is rare (it only fires on a near-empty spec) so the expected value of
   fixing it is low, but it is a one-line fix.
9. **`attempts: int = 2` (`generate_formulas.py:583`) means exactly one repair call -- the
   paper's budget-2 point, where the structured-feedback advantage is at its smallest
   (20/27 points vs 47 at budget 4).** If the feedback is upgraded per (6), the paper's budget
   lane predicts that raising `attempts` to 3-4 buys more than it would have with the current
   feedback. Worth an ablation in the ICRA paper: it is cheap and it is a plot.

**Verdict: the prompt wrapper is fine; one of the two problem messages is a full `SameNL`
payload and needs nothing, and the other is `LocObs` and is leaving the paper's entire effect
size on the table.** The fix belongs mostly in `spec_contract.validate`, not in `REPAIR_PROMPT`.

### 6.3 Proposed text (NOT applied -- decide for yourself)

**(a) The high-value change: give problem B an `expected` field. In `spec_contract.py`,
`validate_structure`.** Current lines 105-109 become:

```python
declared = set(spec.get("atomic_propositions") or {})
for ap, sites in sorted(undeclared_ap_sites(spec).items()):
    problems.append(
        f"'{ap}' is used at {', '.join(sorted(sites))} but is not declared in "
        f"atomic_propositions; either declare '{ap}' with a "
        f'"True when <sensor rule>. <meaning>." description, or replace it with '
        f"one of the declared propositions: {sorted(declared)}"
    )
```

This requires `undeclared_aps` to return AP -> site paths instead of a bare set; the existing
`scan()` walk already visits each site, so it only needs to pass a path label such as
`ltl_formulas[0].formula`, `named_failure_modes[1].formula`,
`execution_phases[2].invariant`, or `terminal_success.condition`. Keep the current
`undeclared_aps()` returning a set as a thin wrapper so
`test_adapter_sensor_eval_contract.py` and any other caller do not break.

**(b) Problem C, one line, same three-field shape:**

```python
problems.append(
    "spec declares no atomic propositions; atomic_propositions is empty, but every "
    "formula, phase condition and terminal condition must reference a declared "
    f"proposition. Declare at least one using these sensor fields: {sorted(schema_keys)}"
)
```

(This moves the check into `validate` where `schema_keys` is in scope, or passes the keys in.)

**(c) `REPAIR_PROMPT` itself -- a light edit, low expected value, offered for completeness.**
The only substantive change is telling the model that each problem carries alternatives and
that it should pick from them, which is the behaviour the paper's `expected` field induces:

```python
REPAIR_PROMPT = """The specification you produced cannot run on this robot. A mechanical
checker rejected it. Each problem below names where the failure is, what the checker
observed there, and what it will accept instead:

{problems}

{schema}

Return the SAME specification with only those problems fixed, as a single valid JSON
object. For each problem, replace the value the checker observed with one of the
alternatives that problem lists. Keep every atomic proposition, formula and phase that
was not named above exactly as it was. Respond ONLY with the JSON object."""
```

Note this drops "not an opinion" -- see 6.4 for why that is a judgement call and not an
evidence-backed one. If you keep the original sentence, you lose nothing the paper measures.

**Do not** convert the problem list to JSON records on the strength of this paper. Two paired
contrasts (+2 and 0, CIs [-8,12] and [-12,12], p = 1.0) say the keys buy no success. The
authors' own recommendation for keys is logging and routing -- which, if you want it, argues
for `spec_contract` returning structured problem objects internally and *rendering* them as
the prose above, giving you machine-readable traces for the ICRA evaluation without changing
what the model sees.

### 6.4 Is "found by a mechanical check, not an opinion" supported?

**Unaddressed by the paper's evidence -- neither supported nor contradicted.** Be precise about
this in the paper if you cite it.

- No feedback policy in the study adds or removes a provenance sentence, so there is no
  contrast that isolates the claim. It was never a manipulated variable.
- The claim is *architecturally* aligned with VeriHarness: their whole premise is that "only
  gates accept a candidate; a worker's self-assessment cannot do so", and they position
  themselves against Self-Refine's model-generated critique. Your sentence is a true
  description of `spec_contract`, and the paper's architecture section is a fair citation for
  *why building the loop that way is right*.
- The nearest available evidence points mildly the other way for the *sentence itself*: the
  stable failure label -- the closest thing to "here is which check fired" -- appears only in
  `TypedFields`, and `TypedFields` vs `SameNL` is +2 / 0 with adjusted p = 1.0. Provenance
  framing is not where the gain lives. And even that is confounded: the authors flag that the
  keyed policy "also includes a stable failure label and different framing text", so their
  design cannot separate label from framing at all.

**Recommended citation posture:** cite Ray & Goyal for *what the feedback should contain*
(location, observed, alternatives) and for *code, not prose, as the control plane*. Do **not**
cite them as support for the "mechanical check, not an opinion" phrasing. If you want that
claim in the ICRA paper, it needs your own one-line ablation -- trivially cheap here, since
`generate()` already takes an injected `llm`, so a scripted-model A/B over the sentence costs
nothing but a test fixture.

---

## 7. Check yourself

**Q1. The paper is called "Structured Feedback...". What does "structured" mean in it, and what
does it *not* mean?**
It means the feedback carries the three explicit repair components -- location, observed value,
and expected alternatives -- regardless of rendering. It explicitly does **not** mean JSON or
keyed syntax: `SameNL` (prose, same three values) matches `TypedFields` to within +2 and 0
points, both CIs spanning zero, both adjusted p = 1.0.

**Q2. Which single field carries the effect, and what is the number that proves it?**
The *expected* / admissible-alternatives field. `LocObs` (keyed, with location and observed
but no alternatives) solves 18/50 and 9/50, barely above `RawDiag`'s 14/50 and 8/50. Adding
only the alternatives to it -- `TypedFields` -- is worth +36 points for Qwen (CI 20-52,
p = 2.4e-4) and +40 for Llama (26-54, p = 2.2e-5).

**Q3. `spec_contract.validate` emits two main problem shapes. Which policy in the paper does
each correspond to?**
The `unknown_keys` message ("references sensor field(s) [...]; available fields are: [...]")
is a full `SameNL` payload -- location, observed, and enumerated alternatives, in prose. The
`undeclared_aps` message ("used in a formula/phase/terminal condition but is not declared") is
`LocObs` -- location and observed with no alternatives, which is the policy that performs near
baseline.

**Q4. Does this paper give evidence that structured feedback improves *code* repair?**
No, and the authors say so. Their only code lane (15 HumanEval tasks) produced zero repair
opportunities -- Qwen's first answer passed the visible test on all 15 -- so every policy
finished identically at 14/15. They label it a scope check, not a benchmark. All positive
evidence is TextWorld action-plan repair. Anyone citing this paper for code repair is
overclaiming.

**Q5. `generate()` uses `attempts=2`. What does the paper predict about that, and under what
condition?**
`attempts=2` is one generate plus one repair -- the paper's budget-2 point, where the
structured-vs-raw gap is smallest (20 and 27 points, versus 47 for both models at budget 4).
Their budget lane shows raw feedback flat from four to eight calls while structured feedback
keeps improving, i.e. extra calls only pay when the retry receives *new information*. So
raising `attempts` is predicted to help **only if** the feedback actually carries alternatives
-- which today it does for `unknown_keys` and does not for `undeclared_aps`. Fix the message
first, then raise the budget, then ablate both.

---

*Every figure above is quoted from arXiv:2607.14167v1. Nothing in the audit section is
attributed to the paper beyond what its tables and stated limitations support; where the paper
is silent (alternative ordering, list truncation, batching many problems into one message,
provenance framing, artifact inclusion as a manipulated variable), this document says
"untested" or "unaddressed" rather than extrapolating.*
