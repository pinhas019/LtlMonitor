# nl2spec — Interactively Translating Unstructured Natural Language to Temporal Logics with Large Language Models

Cosler, Hahn, Mendoza, Schmitt & Trippel. CAV 2023, LNCS 13965, pp. 383–396. doi:10.1007/978-3-031-37703-7_18

**Source read.** The arXiv preprint, `arXiv:2303.04864v1 [cs.LO] 8 Mar 2023`, retrieved via
`mcp__alphaXiv__answer_pdf_queries` (title resolution worked; it resolved to `2303.04864v1` and
returned pages 1–11 plus appendices 16, 17, 19). `link.springer.com`, `dl.acm.org`, `dblp.org`,
`arxiv.org`, Crossref and Semantic Scholar are all blocked by this environment's egress proxy, so the
camera-ready LNCS text was **not** read. **Every page number below refers to the arXiv v1
preprint, not to the Springer pagination 383–396.** The two paginations differ (the preprint runs
to ≥19 pages with appendices; the LNCS chapter is 14). Bibliographic details were confirmed
independently — see `bibtex.md`.

---

## 1. In one paragraph

nl2spec is a framework and open-source web tool that uses a large language model to translate
one sentence of unstructured English into an LTL formula, and — this is the actual contribution —
makes the translation *auditable and repairable* by having the same LLM emit **sub-translations**:
a dictionary mapping fragments of the input sentence to the formula fragments they produced
("do not hold at the same time" → `!(g0 & g1)`). Because natural-language requirements are
inherently ambiguous, the authors argue you cannot fully automate this; instead you decompose the
problem so that a human can inspect and fix one small mapping rather than redraft a whole formula.
The user adds, edits or deletes sub-translations; these are fed back into the prompt as "Given
translations" and the model re-translates, looping until the user approves. On a deliberately hard
36-instance benchmark elicited from five experts, a single automatic pass with Codex got 16/36
(44.4%) correct; with the interactive loop the authors reached 31/36 (86.11%) at an average of 1.4
loops per instance. The framework is model-agnostic and prompt-agnostic (a proof-of-concept STL
prompt and a smart-home prompt are in the appendix).

---

## 2. Key concepts

**Sub-translation.** A pair `(s, φ)` where `s` is a fragment of the natural-language input and `φ`
is the formula fragment it maps to. The paper defines them as "mappings of formula fragments to
relevant parts of the natural language input" (p. 11). Crucially the paper does not claim these
form a parse: "Note that sub-translations provided in the prompt are neither unique nor exhaustive,
but provide the context for the language model to generate the correct formalization" (p. 7). They
are an *explanatory and steering* artefact, not a compositional semantics.

**Interactive few-shot prompting.** The prompting scheme (Algorithm 1, p. 7) that makes
sub-translations both an output and an input. Each few-shot example in the prompt has five parts:
the NL input, a `Given translations: {}` dictionary, a chain-of-thought explanation in prose, an
`Explanation dictionary` summarising the sub-translations, and the final formula, terminated by a
`FINISH` stop token. On the next loop the user's edited sub-translations are injected into the
`Given translations` slot.

**Ambiguity (their two classes).** From p. 10: "We especially observed two classes of ambiguity:
1) ambiguity due to the limits of natural language, e.g., operator precedence, and 2) ambiguity in
the semantics of natural language". Class 1 is a *parse* problem — the sentence admits two bracketings.
Class 2 is a *meaning* problem — the phrase is well-parsed but its intended semantics is
underdetermined. Both are properties of the English, not defects of the model. At least 9 of the 36
benchmark instances contain ambiguous natural language.

**Erroneous translation.** Distinct from ambiguity: the input is unambiguous, the model simply got
it wrong. Their running example is "whenever a holds, b holds as well" translated to `G(a & b)` —
a conjunction where an implication was meant (p. 10). The same interactive loop fixes both classes,
which is why the paper's evaluation reports them separately.

**Confidence score.** Computed as "votes over multiple queries to M, where the (sub) translation
with the highest consensus score is displayed" (p. 7) — i.e. self-consistency sampling, not a
calibrated probability. Runs = 3, temperature = 0.2 in all experiments. Alternatives are offered in
a drop-down.

**Minimal prompt vs in-distribution (ID) prompt.** `minimal.txt` (Fig. 3, p. 6) carries only a
two-sentence tutorial of LTL and two few-shot examples, and "has intentionally been written before
conducting the expert user study" (p. 8) — a genuine pre-registration-flavoured control. The ID
prompt adds four examples drawn at random from the benchmark itself, i.e. a deliberately leaky
condition used to measure how much prompt fit matters.

**Human-in-the-loop.** Their explicit architectural commitment (Fig. 2, p. 5: "Overview of the
nl2spec framework with a human-in-the-loop"). The stated design goal is not to eliminate the human
but to ration them: "The central goal of nl2spec is to keep the human supervision minimal and
efficient" (p. 2).

**Teacher–student transfer.** An experiment where sub-translations generated by a strong model
(Codex) are fed as `Given translations` to a weak model (Bloom). This is the paper's only
*human-free* demonstration that sub-translations carry real information.

---

## 3. Method

**Architecture** (Fig. 2, p. 5). Python 3 + flask, frontend/backend split. Frontend has three views:
"Prompt", "Sub-translations", "Final Result". Inputs: a natural-language sentence, optional
sub-translations, model temperature, number of runs. Outputs: sub-translations, a confidence score,
alternative sub-translations, and the final formula. LTL output is parsed with a standard LTL
parser. Runs as a CLI or a web app. Code: `https://github.com/realChrisHahn2/nl2spec` (p. 3, fn. 3).

**The loop** (Algorithm 1, p. 7), verbatim in structure:

```
ψ, (s,φ), C = empty
while user not approves LTL formula ψ:
    interactive_prompt = compute_prompt(S, F, (s,φ))
    ψ, (s,φ), C     = query(M, P, interactive_prompt)
    (s,φ)           = user_interaction((s,φ), C)
return ψ
```

Read the termination condition carefully: **`while user not approves`**. The loop has no
mechanical exit criterion at all. There is no checker, no type check, no satisfiability test, no
consistency oracle. A human eyeballing the formula is the *only* thing that stops it. This is the
precise structural difference from `skill_monitor`, where `spec_contract.validate()` supplies a
decidable exit condition and the bound is `attempts=2`.

**What the model emits per query.** A prose explanation ("chain-of-thought"), an explanation
dictionary of sub-translations, then the final formula. The prompt's language-specific preamble is
four lines of LTL tutorial; swapping it (and the examples) is how you retarget the tool — the
appendix gives an STL prompt (Fig. 5, p. 19) and a smart-home LTL prompt (Fig. 6, p. 19).

**Models.** Codex `code-davinci-002` (the commercial 2022 version, "likely larger (in the 176B
range)" than vanilla Codex — p. 5) and Bloom 176B via the HuggingFace inference API. "Currently
implemented in the framework and used in the expert-user study are Codex and Bloom, which showed
the best performance during testing" (p. 4).

**Variable naming** is handled *through* the same mechanism rather than by a schema: the user seeds
a sub-translation ("process 0 terminates" → `t_p0`) and "the model adjusts the variable for
'process 1 will start' automatically as `s_p1`" (Appendix E, p. 17). There is no declared set of
atomic propositions anywhere in the system — this matters for §6.

---

## 4. Results

**The benchmark, and how it was built.** Five experts were asked for examples "that the experts
thought are challenging for a neural translation approach" (p. 8). No grammatical or syntactic
restrictions, unlike existing datasets. One sentence each, at most five APs `a,b,c,d,e`. Experts
worked in a shared document to avoid duplicates. Result: **36 instances**. This is adversarial by
construction — the authors say so: "The poor performance of existing methods (cf. Table 1)
exemplify the difficulty of this data set" (p. 8).

**Table 1** (p. 9), initial-translation accuracy, reproduced exactly (percentages as printed;
several are rounded down rather than to nearest):

| system | correct |
|---|---|
| nl2ltl [14] + rasa | 1/36 (2.7%) |
| T-5 [20] fine-tuned | 2/36 (5.5%) |
| nl2spec + Bloom, initial | 5/36 (13.8%) |
| nl2spec + Codex, initial | 16/36 (44.4%) |
| nl2spec + Codex, initial + ID prompt | 21/36 (58.3%) |
| nl2spec + Codex, **interactive** | 31/36 (86.11%) |

Grading is strict: "We only count an instance as correctly translated if it matches the intended
meaning of the expert, no alternative translation to ambiguous input was accepted" (p. 9).

**In-distribution prompting barely helps.** 44.4% → 58.3%, and the authors read this *against*
prompt engineering and *for* their own contribution: "drawing the few-shot examples in distribution
only slightly increased translation quality for this data set; making the key contributions of
nl2spec, i.e., ambiguity detection and effortless debugging of erroneous formalizations, valuable"
(p. 9).

**Teacher–student.** Of the instances Codex solved and Bloom did not (11 of them), Bloom solved 4
more when handed Codex's sub-translations — 36.4%. The four are listed by name on p. 9. The
authors' conclusion is the load-bearing one for anyone building an automated loop: "This
demonstrates that our sub-translation methodology is a valid appraoch: improving the quality of the
sub-translations indeed has a positive effect on the quality of the final formalization... **Note
that no supervision by a human was needed in this experiment to improve the formalization
quality**" (p. 9, emphasis added).

**The interactive repair result.** Twenty instances were wrong on the first Codex+minimal pass.
Fifteen were fixed "by performing at most three translation loops (i.e., adding, editing, and
removing sub-translations)", at **1.86 loops on average** for those fifteen; over the whole set the
average is **1.4 loops**. The remaining five "contain highly complex natural language requirements"
and "were need to be translated by hand" (p. 10). Appendix D (p. 16) lists all five, including
"Once a happened, b won't happen again" (`G (a -> X G ! b)`) and "a releases b".

**Worked repairs, quoted (p. 10) — these are the concrete cases §6 turns on:**

| input | tool produced | expert intended | the fix |
|---|---|---|---|
| "a holds until b holds or always a holds" | `(a U (b \| G(a)))` | `(a U b) \| G a` | edit sub-translation of "a holds until b holds" to `(a U b)` — explicit parentheses |
| "Whenever a holds, b must hold in the next two steps." | `G((a -> X(X(b))))` | `G (a -> (b \| X b))` | edit sub-translation of "b must hold in the next two steps" to `b \| X b` |
| "whenever a holds, b holds as well" | `G(a & b)` | (implication) | edit sub-translation of "b holds as well" to `-> b` |

**Is there a user-facing study?** *Partly, and less than the abstract implies.* The study reported
is an **elicitation** study — five experts producing a dataset. There is no reported measurement of
participants using the tool: no participant task-completion rate, no time-to-correct-formula, no
control condition, no count of participants in the interactive phase. The §4.2 repair narrative is
written in the authors' first person ("**We** were able to extract correct translations for 15
instances"), which reads as the authors performing the loops themselves — *this is my inference
from the phrasing, not a stated fact in the paper.* The conclusion nonetheless says "We conducted a
user study, showing that nl2spec can be efficiently used to interactively formalize unstructured
and ambigous natural language" (p. 11). Treat 86.11% as *achievable by an LTL-fluent author of the
tool*, not as a measured usability result.

---

## 5. Limitations

**Admitted.** Exactly two sentences, both in the conclusion (p. 10): "A limitation of this approach
is its reliance on computational ressources at inference time. This is a general limitation when
applying deep learning techniques." And: "the quality of initial translations might be influenced
by the amount of training data on logics, code, or math that the underlying neural models have seen
during pre-training." Both are generic LLM caveats. Appendix C admits one concrete prompt defect:
"the combination of temporal operators FG is not explained, leading to failed translations in the
expert user data set" (p. 16).

**Unadmitted, and material:**

- **The loop's only termination condition is a human.** `while user not approves` (Algorithm 1).
  There is no mechanical stopping rule, so the loop has no meaning at all in an unattended setting.
  The paper never discusses running without a user.
- **The human must read and write LTL.** The three published fixes are typing `(a U b)`, `b | X b`
  and `-> b` into a text box. These are formal-methods edits. The tool lowers the *quantity* of
  expert effort (1.4 loops), not the *expertise required*. The paper's framing — that formal
  specification is "typically reserved for experts in the field" (p. 1) — is not actually relaxed
  by the tool; it is rationed.
- **Confidence scores are self-consistency votes, not calibration.** Nothing in the paper measures
  whether high consensus correlates with correctness. A confidently wrong consensus is
  indistinguishable from a confidently right one.
- **Sub-translations are not guaranteed faithful.** They are generated text, sampled from the same
  model that produced the formula. The paper explicitly disclaims that they are unique or
  exhaustive (p. 7). So a sub-translation dictionary can look right while the emitted formula does
  not follow from it — the explanation is not verified against the output.
- **n = 36, single sentences, five abstract propositions, one domain.** No grounding, no
  environment, no sensors, no multi-sentence requirements. The instances are `a,b,c,d,e` puzzles.
- **The strongest baseline comparison is weak.** nl2ltl+rasa scores 1/36 in part because it emits a
  restricted set of DECLARE templates and "could not handle most of the instances in the benchmark
  data set" (p. 8) — a coverage mismatch as much as an accuracy result.
- **No inter-rater agreement on "intended meaning".** Grading is against the eliciting expert's
  intent, on a dataset built specifically to contain ambiguity. Who adjudicated is not stated.
- **Cost of the human, unquantified.** No wall-clock time, no expert-minutes per formula, no
  comparison against just writing the LTL by hand. "1.4 loops" is the only cost figure and it counts
  round-trips, not effort.

---

## 6. For `skill_monitor`

### 6.1 The question: what can a human resolve that a free-variable schema check cannot?

Start by naming the two properties precisely, because the whole answer is that they are different
properties and not two strengths of the same one.

`core/spec_contract.py` decides: **is this spec executable against this adapter?** Concretely,
`validate()` returns problems from exactly two sources — `unknown_keys()`, which extracts the
identifiers of each rule AP's `True when <python expr>` body and subtracts the adapter's declared
schema keys, and `validate_structure()`/`undeclared_aps()`, which finds APs referenced in a formula,
phase or terminal condition but never declared. That is a **name-resolution check**. Its soundness
claim is real and worth stating: every key it flags would raise `NameError` under `eval()`, so
every rejection is a genuine runtime failure, not a false alarm.

nl2spec's loop decides: **does this formula mean what the person meant?** Their human is not asked
whether the formula runs. They are asked whether `(a U (b | G a))` is what "a holds until b holds
or always a holds" was supposed to say.

Those are orthogonal. The schema check is not a weak approximation of intent-correctness; it has
**no information about intent at all**. And nl2spec supplies the cleanest possible demonstration,
because *every one of their reported failures uses only atoms that were already in play.*

Walk the three published repairs through `spec_contract.validate()`:

1. **Operator precedence — `(a U (b | G a))` vs `(a U b) | G a`.** Free variables: `{a, b}` in both.
   Both bracketings resolve. The check passes both, and cannot prefer one, because it never
   constructs the parse tree — `_IDENT.findall` returns a *set of names*, deliberately discarding
   structure. This is class-1 ambiguity in the paper's taxonomy and the schema check is blind to
   the entire class by construction.

2. **Quantitative temporal semantics — `G(a -> X X b)` vs `G(a -> (b | X b))`.** Free variables:
   `{a, b}` in both. "b must hold in the next two steps" meaning *within* two steps versus *at
   exactly* step two. Translate this into the reader's domain and it stops being an abstract puzzle:
   *"the gripper must close within two control cycles of the grasp command"* compiled as
   `X X gripper_closed` instead of `gripper_closed | X gripper_closed` is a monitor that reports a
   failure on every correct grasp that happened to complete early. Both versions reference only
   `gripper_closed`, which is a declared adapter key. `validate()` returns `[]`. The spec ships. The
   monitor is wrong in a way that will be blamed on the robot.

3. **Connective substitution — `G(a & b)` for `G(a -> b)`.** This is the one to lead with, because
   it is not even ambiguity — the English "whenever a holds, b holds as well" is not ambiguous; the
   model just produced the wrong connective. Free variables `{a, b}`, both declared, check passes.
   In a runtime monitor the consequence is not "slightly wrong": `G(a & b)` demands that the
   antecedent hold *at every step forever*. A guard that was meant to be conditional becomes a
   permanent obligation, and the monitor fails every trace in which the triggering condition is
   simply absent. A sound executability check waves this through without a murmur.

Now generalise. The class of defects the free-variable check cannot see is everything below the
level of *names*:

- **Wrong constant.** `min_range < 0.25` versus `min_range < 0.55`. Same identifier, same schema
  key, opposite behaviour. (The file's own comment shows the team already knows constants are
  fragile — `TRUE_WHEN_RE`'s terminator was fixed precisely because `min_range < 0.25.` was being
  truncated to `min_range < 0`. That bug was caught by a test, not by the oracle; the oracle would
  have passed `min_range < 0` as perfectly executable.)
- **Wrong comparison direction.** `<` for `>`. Identical free-variable set.
- **Wrong temporal operator.** `G` where `F` was meant, `X` where `F` was meant, a missing `G` in
  front of a persistence property. `undeclared_aps()` explicitly whitelists `{G, F, X, U, R, W, M}`
  out of the used-name set, so the check discards temporal structure by design, not by accident.
- **Wrong slot within a phase.** `execution_phases` in this codebase carries `invariant` and
  `progress_condition` as separate keys — and `undeclared_aps()` scans both with the same `scan()`
  call. A condition placed as an `invariant` when it should have been a `progress_condition`
  (or vice versa) is a different property with different failure semantics, and both placements
  produce an identical set of resolved names. The check cannot tell them apart. This is the reader's
  own data structure exhibiting the paper's class-2 ambiguity.
- **Right rule, wrong prose.** A rule AP is `"True when <expr>. <prose>"`. Only the expression is
  checked. If the prose says "gripper is open" and the expression says `gripper_closed`, the AP is
  executable, its name may be used correctly elsewhere, and every downstream human reading the spec
  is misled. Nothing checks agreement between the two halves.
- **Omission.** The spec is silent about a failure mode the operator cares about. There is no free
  variable to be undeclared; there is nothing at all. A check that examines what is present can
  never report what is absent.
- **A `named_failure_mode` that is correct-but-vacuous.** A formula whose antecedent can never hold
  given the adapter's actual signal ranges is executable, well-named, and monitors nothing.

And one sharper point, which is the part a reviewer will find if the reader does not: **the repair
loop can convert an honest failure into a silent one.** Suppose the model writes
`laser_min_range < 0.3` and the adapter declares `min_range` and `obstacle_distance`. `validate()`
correctly rejects it, and the repair message — by the code's own design, "each message names the
offending AP and the legal alternatives" — hands the model the full list of available fields. The
model picks one. Both candidates are executable. Only one is right. At that moment a spec that was
*unexecutable and loudly diagnosable* has become *executable and possibly wrong*, and the loop
exits reporting success. nl2spec's human, shown the sub-translation for that fragment, is looking
at exactly this decision. The mechanical oracle makes it blind. This is a cost of removing the
human, not merely an absence of a benefit.

Finally, the honest framing of the soundness claim itself. "Sound" invites the question *sound for
what?* — and the answer is: for a property no operator directly cares about. Nobody asks for a spec
that executes. They ask for a spec that is right. Executability is a **necessary condition** the
reader can now discharge automatically and cheaply, and that is a real result — it is what makes
skill-agnostic synthesis possible at all, since the LLM genuinely has no way to know which sensor
fields exist. But it is a necessary condition, not a sufficient one, and the paper's own numbers
size the remaining gap: nl2spec's automatic pass was correct on 44.4% of instances and its
human-supervised pass on 86.11%. Roughly forty points of their result is bought with human
judgement about *meaning*. There is no mechanical oracle in `spec_contract.py` that buys any of it.

**What the reader can still claim, defensibly, using this paper.** Two of nl2spec's own results
were obtained *without* a human, and both are exactly the levers `skill_monitor` pulls:

- The **teacher–student experiment** — Bloom solved 4 of 11 previously-failed instances from
  Codex's sub-translations, with the authors noting explicitly that "no supervision by a human was
  needed in this experiment to improve the formalization quality" (p. 9). This is published
  evidence that *structured feedback injected into the prompt improves formalization quality
  independent of a human*, which is precisely the mechanism of `generate()`'s repair pass.
- The **ID-prompt result** — 44.4% → 58.3% from four in-distribution examples (p. 9). Weak, but it
  is evidence that *context about the target domain* helps. `schema_prompt(schema)` is that context,
  and it is stronger than four examples because it is the ground truth about the target rather than
  a sample of it.

So the argument is not "we replaced the human". It is: the human in nl2spec was doing two jobs —
supplying domain context the model lacked, and adjudicating meaning. The schema check automates the
first completely and soundly. The second is not automated, and this paper is the reader's evidence
for how much it is worth.

### 6.2 Draft limitations paragraph

> Our validation oracle is sound but narrow, and it is important to be precise about what it
> establishes. `spec_contract.validate()` decides a name-resolution property: every sensor key
> appearing as a free variable in a generated rule must be declared in the adapter's schema, and
> every atomic proposition used in a formula, phase or terminal condition must be declared. Because
> an undeclared key raises `NameError` under evaluation, every rejection corresponds to a genuine
> runtime failure — the check has no false alarms. What it establishes is therefore that a spec is
> **executable** against a given robot. It does not, and cannot, establish that the spec is
> **correct**. A specification that references only declared sensor keys, in a syntactically valid
> rule, can still mean something the operator did not intend: a threshold set to the wrong constant,
> a comparison in the wrong direction, `G` where `F` was meant, a condition placed as a phase
> invariant when it should have been a progress condition, an atomic proposition whose executable
> rule contradicts its own prose description, or a failure mode the operator cares about that the
> spec simply never mentions. Every one of these produces an identical set of resolved free
> variables to its correct counterpart, so our check accepts them without complaint. Cosler et
> al.'s nl2spec [cosler2023nl2spec] targets exactly this second class, and their examples make the
> gap concrete: their tool rendered "whenever a holds, b holds as well" as `G(a & b)` rather than
> an implication, and "b must hold in the next two steps" as `X X b` rather than `b | X b`. Both
> errors use only atoms already in scope; both would pass our contract; and in a runtime monitor
> the first turns a conditional guard into a permanent obligation and the second rejects every
> correct execution that completes early. They resolve such cases by decomposing the formula into
> sub-translations and asking a human to correct the offending fragment, reporting 44.4% correct on
> a fully automatic pass against 86.11% with that interactive loop — a gap attributable to human
> judgement about meaning, which our loop does not have. Our repair loop can even make this worse
> rather than better: when a rule references an undeclared key we report the adapter's available
> fields back to the model, and the model may substitute a field that is executable but semantically
> wrong, converting a loudly diagnosable failure into a silent one. We accept this trade
> deliberately, because requiring an LTL-fluent operator at spec-compile time — the assumption
> nl2spec's own repairs make, since its published fixes consist of typing `(a U b)` and `-> b` into
> the interface — is precisely the deployment cost we are trying to remove, and because
> executability is a necessary condition that must be discharged before any semantic check is even
> meaningful. We note that two of nl2spec's own results were obtained without human supervision —
> sub-translations produced by a stronger model improved a weaker model's output on 4 of 11
> instances with, in the authors' words, no human supervision needed — which supports the narrower
> claim we do make: that structured, machine-generated feedback improves formalization quality on
> its own. Closing the remaining gap requires an oracle for meaning rather than for names. We regard
> trace-level differential testing — rejecting any candidate specification that flags a recorded
> nominal episode as a failure, or that fails to flag a recorded fault — as the most promising
> direction, since it is orthogonal to the schema contract and, unlike interactive refinement,
> requires no operator at generation time. We leave it to future work.

*(Tighten to venue length; the ICRA 8-page limit will not take this whole. The non-negotiable
sentences are: what property the check decides, the enumerated list of what passes it while being
wrong, at least one nl2spec example, and the differential-testing sentence. The repair-loop-makes-it-
worse admission is the one that most impresses a reviewer if you keep it and most damages you if
they find it themselves.)*

### 6.3 What to cite it for, and where

| Where | Claim | Note |
|---|---|---|
| Related work, NL→TL | The interactive / human-in-the-loop corner of the design space, alongside `lang2ltl`, `chen2023nl2tl`, `fuggitti2023nl2ltl`, `english2025ginsign`. Their own positioning: "all previous tools lack a detection and interactive resolving of the inerherent ambiguity of natural language" (p. 4, *sic*). | The cleanest one-line contrast in the whole bibliography: **their loop's exit condition is a human, ours is a decidable check.** Quote Algorithm 1's `while user not approves` if you have room. |
| Method / design rationale | Structured feedback fed back into the prompt improves formalization quality without a human — the teacher–student result, 4/11, p. 9. | The single most useful citable fact in the paper for this project. Pair with `structuredfeedback2026`. |
| Method, secondary | Domain context in the prompt helps (ID prompt, 44.4% → 58.3%). | Weak effect; the authors themselves downplay it. Use only to motivate putting the schema in the prompt, not to claim a large gain. |
| **Limitations** | **The primary citation.** The two ambiguity classes (p. 10) and the three worked repairs are the concrete evidence that intent-level errors exist and are common. | This is where the paper earns its place. See §6.2. |
| Introduction, optional | "writing formal specifications is an error-prone and time-consuming manual task typically reserved for experts in the field" (p. 1). | Standard framing; several other queued papers say the same, so cite whichever cluster is tidier. |

**Do not cite it as an E1 baseline, and say why if a reviewer asks.** Their benchmark is 36
single-sentence instances over five abstract propositions `a,b,c,d,e`, with no environment, no
sensors and no adapter schema. There is no notion of a spec being executable against a robot, so
there is nothing for `spec_contract.py` to check and no shared metric. The comparison is a category
error, not a missing experiment. If a baseline is needed, `fuggitti2023nl2ltl` (item 05) is the
runnable candidate; nl2spec's contribution is a *workflow*, and workflows are compared in the
limitations section, not the results table.

**One cross-check for the reading plan.** Item 06 (`verify-repair-stop`) asks whether
`attempts=2` should become a sweep over *k*. nl2spec is a weak data point in that direction:
15 of their 20 failures were fixed within ≤3 loops, at 1.86 loops average for those fifteen, and
the remaining 5 were never fixed by looping at all. Their loops are human-driven and so not
directly comparable, but the shape — most repairs land early, a hard residue never lands — is the
same shape a *k*-sweep would be looking for.

---

## 7. Check yourself

**Q1. nl2spec's tool translated "whenever a holds, b holds as well" into `G(a & b)`. Would
`spec_contract.validate()` reject the analogous spec, and what happens at runtime if it does not?**

No, it accepts it. `unknown_keys()` extracts the identifiers from each rule AP's `True when`
expression and subtracts the adapter schema; `undeclared_aps()` checks that every AP used in a
formula is declared. `G(a & b)` and `G(a -> b)` have the identical name set `{a, b}`, so if `a` and
`b` are declared APs backed by declared sensor keys, both pass with an empty problem list. At
runtime the difference is severe rather than cosmetic: `G(a & b)` asserts that the antecedent holds
at every step forever, so the monitor reports a violation on every trace where the triggering
condition is merely absent — a conditional guard silently promoted to a permanent obligation.

**Q2. Which of nl2spec's two ambiguity classes could a schema check in principle detect, and which
could it not?**

Neither. Class 1 (operator precedence, "the limits of natural language") is a parse-structure
question, and the check deliberately discards structure — `_IDENT.findall` returns a set of names.
Class 2 (semantics, e.g. "in the next two steps") is a meaning question over a fixed vocabulary.
Both classes by definition operate over atoms already in play, so neither can produce an undeclared
free variable. The check is blind to both classes *by construction*, not by an implementation gap
that could be patched.

**Q3. Their headline numbers are 44.4% and 86.11%. What exactly separates them, and why does that
matter for the reader's framing?**

44.4% is Codex with the minimal prompt on a single automatic pass (16/36). 86.11% is the same
system after human-driven sub-translation edits, at 1.4 loops average (31/36). The separation is
human adjudication of *meaning* — nothing else changed, not the model, not the prompt, not the
temperature. It matters because it is a published, quantified price for the thing
`skill_monitor` gives up. Quoting only 86.11% would misrepresent the paper as a strong automatic
result; quoting only 44.4% would understate what the loop achieves. The reader needs both, and the
gap between them is the size of their own limitation.

**Q4. The paper contains one result obtained with no human at all. What is it, and why is it the
most useful sentence in the paper for this project?**

The teacher–student experiment (p. 9): sub-translations generated by Codex were fed to Bloom as
`Given translations`, and Bloom solved 4 of the 11 instances (36.4%) it had previously failed, with
the authors stating "no supervision by a human was needed in this experiment to improve the
formalization quality." It is the most useful sentence because `skill_monitor`'s repair pass is
structurally the same move — inject structured, machine-generated feedback into the prompt and
re-query — so this is external published evidence that the mechanism works absent a human, which is
otherwise the reader's most exposed assumption.

**Q5. Name a way the mechanical oracle can be actively worse than no check at all, and one concrete
addition that would begin to close the intent gap.**

Worse: the repair message names the adapter's available fields, so when the model's first draft
references an undeclared key, it is handed a menu of executable substitutes. It picks one; the check
now passes; the loop reports success. A failure that was unexecutable and loudly diagnosable has
become executable and possibly wrong. Addition: trace-level differential testing — run the
candidate spec over recorded nominal and faulty episodes and reject any spec that flags a known-good
rollout as a failure or misses a known fault. That makes "wrong" a checkable property rather than a
human judgement, is orthogonal to the schema contract, and — unlike nl2spec's loop — needs no
operator present at generation time. Cheaper partial measures: render the spec back to English and
show it, or check each rule AP's expression against its own prose description.
