# NL2LTL — A Python Package for Converting Natural Language (NL) Instructions to Linear Temporal Logic (LTL) Formulas

Francesco Fuggitti, Tathagata Chakraborti (IBM Research).
*Proceedings of the AAAI Conference on Artificial Intelligence* **37**(13): 16428–16430, 2023.
DOI `10.1609/aaai.v37i13.27068`. Demonstration track. **No arXiv preprint found** — see
`bibtex.md` for what was and was not verified.

Code: <https://github.com/IBM/nl2ltl> (MIT). PyPI: `nl2ltl`, latest **0.0.6**, released
**2024-02-15**.

---

## 0. Sources actually used — read this first

The claims below are graded. I could not open the AAAI PDF: `ojs.aaai.org` is blocked by
this session's network egress proxy, as are `dl.acm.org`, `semanticscholar.org`,
`research.ibm.com`, `bibbase.org`, `aaai-23.aaai.org`, `proceedings.com` and
`icaps23.icaps-conference.org` (the ICAPS-23 companion demo PDF). **I have therefore not
read the paper's own text.**

What I *did* read, in full and verbatim:

| Source | Tool | Status |
|---|---|---|
| `github.com/IBM/nl2ltl` README, `pyproject.toml`, `tox.ini`, `CHANGES.md`, `AUTHORS.md`, `LICENSE` | `read_files_from_github_repository` | read in full |
| `nl2ltl/declare/base.py`, `declare/declare.py` | same | read in full |
| `nl2ltl/engines/gpt/core.py`, `gpt/output.py`, `gpt/data/prompt.json` | same | read in full |
| `nl2ltl/engines/grounding.py`, `engines/utils.py`, `filters/simple_filters.py` | same | read in full |
| PyPI JSON metadata for `nl2ltl` | WebFetch `pypi.org/pypi/nl2ltl/json` | read |
| GitHub commit list, `main` branch | WebFetch `github.com/IBM/nl2ltl/commits/main` | read |
| Paper abstract, venue, pages | WebSearch result snippets only | **snippet-level, not the PDF** |

`mcp__alphaXiv__answer_pdf_queries` **failed for this paper**: queried by full title, it
resolved to a *different* paper — REQ2LTL, arXiv:2512.17334 — because NL2LTL is not on
arXiv. That mis-resolution turned out to be useful (§4.1), but it returned nothing from the
NL2LTL paper itself. `mcp__github__list_commits` / `list_issues` were denied: this
session's GitHub access is scoped to `pinhas019/ltlmonitor` only.

**I did not install the package.** Every statement in §6.1 about installability is derived
from declared metadata and source code, not from a run. Where that distinction matters I
say so explicitly.

Consequence: §§1–3 and §§5–6 are reliable (the source code *is* the ground truth for a tool
paper, and the abstract is corroborated by two independent snippets). §4 (Results) is the
weak section — I cannot confirm what evaluation, if any, is in the 3-page PDF.

---

## 1. In one paragraph

NL2LTL is a small open-source Python library that turns one short English sentence into
one LTL formula, by asking an LLM (or a Rasa intent classifier) to pick a **pattern name**
and a **list of symbols** from fixed menus, and then instantiating a hard-coded LTL
template with those symbols as atomic propositions. It is not a parser and not a
translator in the general sense: the entire formula vocabulary is eight DECLARE templates
implemented as Python classes, and the LLM's only job is classification plus entity
extraction. The abstract, per search snippets, describes it as a package that "leverages
natural language understanding (NLU) and large language models (LLMs) to translate natural
language instructions to linear temporal logic (LTL) formulas … comes with support for a
set of default LTL patterns corresponding to popular DECLARE templates, but is also fully
extensible to new formulas and user inputs," released under MIT "for the AI community."
The demo's motivating domain is business/workflow automation — the shipped prompt's symbol
vocabulary is Slack, Salesforce, Gmail, Jira, Trello, ServiceNow and friends. It is a
three-page demonstration paper; the engineering artifact, not an experiment, is the
contribution.

---

## 2. Key concepts

### 2.1 "Conversion" here means *pattern classification*, not parsing

This is the single most important thing to understand about NL2LTL, and it is easy to
misread from the abstract. The pipeline is:

```
utterance (str)
  → LLM emits two lines:   PATTERN: response
                           SYMBOLS: Slack, SurveyMonkey
  → regex-scrape both lines
  → fuzzy-match PATTERN against 8 template names
  → call ground_<template>(symbols) → Template object over Atomic(...)
  → optional filter
  → Dict[Formula, float]
```

The LLM never writes a formula. It writes a *label* and a *symbol list*. The formula is
produced deterministically by Python. That is a genuine design strength — the output is
syntactically valid LTL by construction, always — and simultaneously the hard ceiling on
what the tool can express.

### 2.2 The pattern library: eight DECLARE templates, closed set

`nl2ltl/declare/base.py` defines a `@unique` enum, and this enum *is* the output space:

```python
class TemplateEnum(Enum):
    EXISTENCE = "Existence";              EXISTENCE_TWO = "ExistenceTwo"
    ABSENCE = "Absence";                  RESPONDED_EXISTENCE = "RespondedExistence"
    RESPONSE = "Response";                PRECEDENCE = "Precedence"
    CHAIN_RESPONSE = "ChainResponse";     NOT_CO_EXISTENCE = "NotCoExistence"
```

Each has a class in `declare/declare.py` with three methods — `to_ltlf()`, `to_ppltl()`,
`to_english()`. The LTLf semantics, verbatim from source:

| Template | Arity | `to_ltlf()` |
|---|---|---|
| `Existence(a)` | 1 | `F a` |
| `ExistenceTwo(a)` | 1 | `F(a & X F a)` |
| `Absence(a)` | 1 | `!F a` |
| `RespondedExistence(a,b)` | 2 | `F a -> F b` |
| `Response(a,b)` | 2 | `G(a -> F b)` |
| `Precedence(a,b)` | 2 | `(!b U a) \| G !b` |
| `ChainResponse(a,b)` | 2 | `G(a -> X b)` |
| `NotCoExistence(a,b)` | 2 | `F a -> !F b` |

Every template is unary or binary over bare atoms. There is no nesting, no conjunction of
requirements, no scope, no bounded time, no comparison operator. `to_ppltl()` additionally
gives a pure-past version of each (`Once`, `Historically`, `Since`, `Before`), which is a
real and underrated feature — pure-past LTL is what you want for online monitoring.

### 2.3 The few-shot part: a single prompt string in a JSON file

`nl2ltl/engines/gpt/data/prompt.json` is one key, `"prompt"`, holding one long string. Its
structure is exactly:

```
Translate natural language sentences into patterns.

ALLOWED_PATTERNS: existence, existenceTwo, response, chainResponse, respondedExistence
ALLOWED_SYMBOLS: Slack, Salesforce, Eventbrite, SurveyMonkey, Amazon S3, Microsoft Teams,
  ServiceNow, SAP and Salesforce, Acoustic Campaign, Trello, Microsoft Dynamics 365,
  Marketo, Email, Sales, Hotmail, Insightly, Asana, Gmail, Jira

NL: Send a Slack message whenever a response is created in SurveyMonkey
PATTERN: response
SYMBOLS: Slack, SurveyMonkey

… (≈45 such triples total)
```

At call time the code does `messages = [{"role":"user","content": prompt + f"NL: {utterance}\n"}]`
— the whole prompt is one user message, and the model completes with `PATTERN:`/`SYMBOLS:`
lines. So the "few-shot, template-based, user-supplies-templates" description in the task
brief is **half right**: users supply *examples* trivially, but *templates* only by writing
Python. §6.2 pins this down.

Note the shipped prompt's `ALLOWED_PATTERNS` lists only **five** of the eight — `absence`,
`precedence` and `notCoExistence` are implemented but never demonstrated to the model.

### 2.4 Atomic propositions = decapitalised surface strings

`grounding.py` is the whole story:

```python
def ground_response(connectors):
    if len(list(connectors)) >= 2:
        return {Response(Atomic(decapitalize(list(connectors)[0])),
                         Atomic(decapitalize(list(connectors)[1])))}
```

`decapitalize("Slack")` → `"slack"`. That string becomes the atom. There is no type, no
schema, no arity, no arguments, no lookup — an AP is a lowercased fragment of the LLM's
output text. Ordering is positional: the first symbol in the `SYMBOLS:` line is operand 0.

**Bug worth knowing about** (`grounding.py`, `ground_notcoexistence`):

```python
return {NotCoExistence(Atomic(decapitalize(list(connectors)[1])),
                       Atomic(decapitalize(list(connectors)[1])))}
```

Index `1` twice — operand 0 should be `[0]`. Every `NotCoExistence` this produces is
`F b -> !F b` over a repeated symbol. It does not bite with the shipped prompt (that
pattern isn't in `ALLOWED_PATTERNS`), but it will if you extend the prompt to use it.

### 2.5 Filters

`Filter.enforce(output, entities)` post-processes the formula dict. Two ship:
`BasicFilter`, whose body is literally `return output` (a no-op, despite a docstring
describing an algorithm it does not implement), and `GreedyFilter`, which keeps the
highest-scoring formula and drops formulas that conflict with or subsume it, using tables
in `filters/utils/conflicts.py` and `subsumptions.py`. With the GPT engine the filter is
near-pointless: the engine returns exactly one formula with confidence hard-coded to `1`.

---

## 3. Method, concretely

### 3.1 Input format

The public API is one function:

```python
from nl2ltl import translate
translate(utterance: str, engine: Engine, filter: Filter = None) -> Dict[Formula, float]
```

**The unit of input is a single short sentence.** Not a document, not a paragraph, not a
structured description. One utterance in, one formula out.

### 3.2 Engines

- **`GPTEngine`** — `GPTEngine(model=..., prompt=Path, operation_mode=..., temperature=0.5)`.
  Supported models are a closed enum: `gpt-3.5-turbo-instruct`, `gpt-3.5-turbo`, `gpt-4`.
  Anything else raises. Two modes, `chatCompletion` and `Completion`. Call params:
  `max_tokens=200, top_p=1.0, stop=["\n\n"]`. Needs `OPENAI_API_KEY`.
- **`RasaEngine`** — intent/entity classifier; optional extra (`pip install ".[rasa]"`,
  pinning `rasa==3.6.16`). Requires a trained `.tar.gz` NLU model in `models/`; one
  (22.8 MB, `nlu-20230608-…`) is committed to the repo. A `train(...)` API is provided.
- **Watson Assistant** — listed in the README as *planned*, unimplemented.

You can add your own by subclassing `Engine` and implementing
`translate(utterance, filtering) -> Dict[Formula, float]`.

### 3.3 Output parsing — and its two crash modes

`gpt/output.py` scrapes with `re.search("PATTERN: (.*)\n", ...)` and
`re.search("SYMBOLS: (.*)", ...)`, then `.group(1)`, then `.split(", ")` for symbols. Both
are wrapped in `cast(Match, ...)`, which is a *type* assertion and does nothing at runtime.
If the model's reply lacks either line, `re.search` returns `None` and this raises
`AttributeError`. Note also that the `PATTERN` regex requires a trailing newline, so a
reply ending immediately after the pattern also fails.

`engines/utils._get_formulas` then does:

```python
class_name_match = difflib.get_close_matches(name, [x.value for x in TemplateEnum], n=1)
grounding_func = grounding_map[str(class_name_match[0])]
```

Two consequences that matter for §6:

1. **Any pattern name is fuzzy-snapped to one of the eight.** The output space is closed
   regardless of what the prompt says.
2. **If nothing matches closely enough, `class_name_match` is `[]` and `[0]` raises
   `IndexError`** — an uncaught crash, not a graceful "no translation".

### 3.4 Grounding does not check `ALLOWED_SYMBOLS`

`parse_gpt_result` builds `symbols = {e: 1 for e in output.entities}` straight from the
scraped line, and grounds it. **Nothing anywhere compares the returned symbols against the
`ALLOWED_SYMBOLS` list in the prompt.** A hallucinated symbol becomes an atomic proposition
with no complaint. Hold that thought — it is the crux of §6.3.

---

## 4. Results — what, if anything, is evaluated

**Honest answer: I could not read the paper, and I have no evidence it contains a
quantitative evaluation.** It is a three-page demonstration paper (16428–16430) in the
AAAI-23 demo track. Demo papers of that length in that venue characteristically describe
the system, a use case and the interface, and do not report benchmark tables. No search
snippet I retrieved mentioned an experiment, a dataset, an accuracy figure or a baseline.
The repository contains no evaluation script, no benchmark data and no results file — the
`tests/` directory holds two smoke tests (`test_gpt.py`, `test_rasa.py`, ~1.2 KB each).

**Treat the evaluation as thin-to-absent, and do not cite NL2LTL for a number.** If you
need a number from the paper itself, open the PDF from a machine that can reach
`ojs.aaai.org` and check before writing anything.

### 4.1 Third-party numbers exist, from a paper that benchmarked NL2LTL

The one useful accident of this research session: querying alphaXiv by title mis-resolved
to **REQ2LTL** (Ma, Wen, Su, Liang, Tian, Qin & Yang, arXiv:2512.17334, Dec 2025), which
uses NL2LTL as a baseline and cites it as reference [24] with the correct AAAI DOI. Its
reported figures for NL2LTL:

- **Academic benchmarks (lifted), GPT-4o backend** — binary accuracy / BLEU:
  Circuit 90.5 / 0.93, Navigation 89.9 / 0.93, Office Email 90.8 / 0.93.
  (REQ2LTL 95.3–96.7; NL2TL 96.0–96.5; NL2SPEC ~90.)
- **Industrial aerospace requirements, 112 items** — GPT-4o + NL2LTL: **55.4%** exact
  match, **91.5%** syntax validity, **98.4%** AP recall, BLEU 0.77. GPT-4o zero-shot:
  43.8 / 89.3 / 98.5 / 0.76. REQ2LTL: 88.4 / 100.0 / 99.5 / 0.96.

Two heavy caveats. First, REQ2LTL describes its baselines as *prompting strategies*
("NL2LTL … is a Python package developed by IBM Research"; the table row is labelled
"GPT-4o + NL2LTL"), i.e. they ran NL2LTL's *prompt style* on GPT-4o, which the shipped
package cannot do — its `Models` enum tops out at `gpt-4`. So this is NL2LTL-inspired, not
NL2LTL-as-installed. Second, these are single-sentence requirement benchmarks, not robot
skill descriptions. Cite these numbers as REQ2LTL's measurements of a reimplementation,
never as NL2LTL's own results.

The genuinely load-bearing takeaway for you: **an independent group in 2025 successfully
used NL2LTL as a runnable comparison arm.** That is real evidence for the "it can be a
baseline" side of §6.

---

## 5. Limitations

1. **Eight templates, closed by enum.** No nesting, no conjunction, no scope, no bounded
   time, no `U` exposed to the user, no arithmetic. If a requirement is not one of eight
   DECLARE shapes, NL2LTL cannot express it — and worse, does not say so: `difflib` snaps
   it to the nearest template and returns a confident wrong answer.
2. **One sentence → one formula.** No notion of a multi-formula specification, no
   cross-formula consistency beyond `GreedyFilter`'s conflict/subsumption tables.
3. **APs are surface strings with no semantics.** No grounding to sensors, actuators, state
   variables or an ontology. `slack` is a name, not a proposition you can evaluate.
4. **No validation of the emitted symbols** against the prompt's own `ALLOWED_SYMBOLS`.
5. **Confidence is fake in the GPT path.** Every formula is assigned `1`. Downstream
   filtering that ranks by confidence is therefore inert.
6. **Fragile output handling.** Regex `.group(1)` on a possibly-`None` match;
   `difflib.get_close_matches(...)[0]` on a possibly-empty list. Malformed LLM replies
   crash rather than degrade.
7. **Hard version pins.** `openai==1.12.0`, enforced at runtime by comparing the *private*
   attribute `client._version`. `requires-python = ">=3.8,<3.11"`. `rasa==3.6.16`.
8. **Model list frozen at early 2024.** `gpt-3.5-turbo-instruct`, `gpt-3.5-turbo`, `gpt-4`;
   `__check_model_support` raises for anything newer.
9. **Domain is workflow automation.** Every one of the ~45 shipped exemplars is a SaaS
   integration sentence. Nothing robotics-adjacent.
10. **Unmaintained.** Last commit *and* last release both 2024-02-15 — ~2.5 years cold as of
    2026-09-02. PyPI classifier: `Development Status :: 2 - Pre-Alpha`. `AUTHORS.md` lists
    two maintainers and "Contributors: None yet."
11. **The `NotCoExistence` grounding bug** (§2.4).

---

## 6. For `skill_monitor` — BASELINE VERDICT

### 6.1 Does it install today, on what Python, and is it maintained?

**I did not install it** (the brief forbids it), so this is read off declared metadata and
source, not observed.

- **Python:** `requires-python = ">=3.8,<3.11"`. Effective ceiling **Python 3.10**. `tox.ini`
  tests `py310` only. If your environment is 3.11+, `pip install nl2ltl` will refuse on the
  metadata; you need a dedicated 3.10 venv. This is a *constraint*, not a blocker.
- **Dependencies:** `pylogics` (unpinned) and **`openai==1.12.0`** (pinned exactly, Feb 2024).
  Rasa is optional and pins `rasa==3.6.16` — a heavy, transitively-fussy install; **do not
  install the Rasa extra**, you do not need it.
- **The runtime version gate is the real risk.** `GPTEngine.__check_openai_version` does
  `is_right_version = client._version == "1.12.0"` and raises otherwise. `_version` is a
  private attribute of the OpenAI client; it exists in 1.12.0. So you cannot simply upgrade
  `openai` — but a two-line monkey-patch bypasses the check if the pin ever fails to resolve.
- **The model gate is the other risk, and I cannot resolve it without a live call.**
  `SUPPORTED_MODELS` is `{gpt-3.5-turbo-instruct, gpt-3.5-turbo, gpt-4}`. Whether OpenAI
  still serves those three on 2026-09-02 **I have not verified and will not guess.** If they
  are retired, `__check_model_support` blocks every current model — but this is also a
  two-line patch (`Models` is a plain enum, `SUPPORTED_MODELS` a plain set), and the prompt
  format is model-agnostic.
- **Maintained:** **no.** Last commit 2024-02-15, last release 0.0.6 the same day. Pre-Alpha,
  no outside contributors. Assume zero upstream support.

**Verdict on Q1:** almost certainly installable inside a Python 3.10 venv, with a
non-trivial chance of needing 2–5 lines of monkey-patching to get past the version and
model gates. Nothing here is architecturally blocking. **Treat it as a 2-hour spike with a
real but bounded risk of failure.**

### 6.2 Custom templates and example translations — or a locked pattern library?

**The brief's premise is half-right, and the half that's wrong is the half that matters.**
These are two separate extensibility stories with wildly different costs:

**Custom examples and vocabulary: YES, and it's cheap — a text edit.** `GPTEngine.__init__`
takes `prompt: Path = PROMPT_PATH` and does `json.load(open(prompt))["prompt"]`. Point it at
your own JSON file with your own `ALLOWED_SYMBOLS` (→ your sensor keys) and your own
NL/PATTERN/SYMBOLS exemplars (→ robot skill sentences). No code changes. This is a
first-class, documented-by-signature hook. **This is what makes NL2LTL viable for you at all.**

**Custom LTL templates: NO, not without writing Python in three places.** The abstract's
"fully extensible to new formulas" is true only in the sense that the codebase is open. To
add one template you must:

1. add a member to the `@unique` `TemplateEnum`;
2. write a class in `declare/declare.py` implementing `to_ltlf`, `to_ppltl`, `to_english`,
   subclassing `Template` and `_UnaryOp`/`_BinaryOp`;
3. add a function named **exactly** `ground_<lowercased enum value>` in `grounding.py` —
   `_get_formulas` finds it by `getattr(nl2ltl.engines.grounding, f"ground_{c_name.value.lower()}")`,
   so a naming mismatch is an `AttributeError` at call time.

And even then, `difflib.get_close_matches` still snaps arbitrary LLM output onto the enum,
so the output space stays closed by construction.

**For E1 this is fine**, because you should *not* extend the templates. The eight DECLARE
shapes are a legitimate fixed expressiveness envelope for a baseline, and freezing them is
methodologically cleaner than hand-tuning a competitor.

### 6.3 Can it be pointed at a robot-skill description and a sensor vocabulary?

**Partly — and the mismatch is real but bridgeable in a day, not a week.**

**What bridges easily.** `ALLOWED_SYMBOLS` is *exactly* the structural analogue of your
adapter schema block: a declared vocabulary handed to the model in-context. Dropping your
robot's sensor keys in there is a five-minute edit and gives you a genuinely comparable
setup. Writing 20–40 robot-skill exemplars is straightforward, if tedious.

**What does not bridge — the input granularity.** NL2LTL consumes **one sentence** and emits
**one formula**. `skill_monitor` consumes a free-language skill description and emits a
*spec*: an AP set, multiple LTL formulas, named failure modes, phased guards. There is no
input format that gets NL2LTL to produce a multi-formula spec. You must split the skill
description into requirement sentences yourself and call `translate` once per sentence,
then union. That is ~30 lines of harness code — but **be explicit in the paper that you did
it**, because the segmentation is now your choice and it materially affects NL2LTL's score.
Do the split with a fixed, documented rule (e.g. sentence boundaries), not by hand-curating.

**The one thing that makes this genuinely attractive.** §3.4: *nothing checks the emitted
symbols against `ALLOWED_SYMBOLS`*. NL2LTL will happily ground a hallucinated sensor name
into an atom and return it with confidence 1.0. That is precisely the failure your oracle
catches. So NL2LTL is a **clean, independent, no-validation baseline** — an external tool
that does the schema-free thing, rather than your own system with a flag flipped off. That
is exactly what a same-system ablation cannot give you, and it is the strongest argument in
this whole document for building it.

### 6.4 What would it actually output?

A `Dict[pylogics Formula, float]` — in the GPT path, one entry, value `1`. The key is a
`Template` object; `.to_ltlf()` gives the LTLf formula, `.to_ppltl()` the pure-past
version, `.to_english()` a gloss.

**Not lifted placeholders.** Unlike NL2TL's `prop_1`/`prop_2`, the atoms carry real surface
names taken from the utterance (`slack`, `gmail`) — so with a sensor-key `ALLOWED_SYMBOLS`
you would get atoms like `gripper_force` or `tool_contact`, directly string-comparable
against your adapter schema.

**But ungrounded and structureless.** An AP is a bare lowercased name. No type, no
arguments, no comparison (`gripper.force > 5` is unrepresentable), no predicate structure.
So:

- **For E1(a) — "how many specs reference sensors the robot does not have" — this is
  sufficient.** Walk the returned formula, collect atoms, set-difference against the
  declared schema keys, count. The measurement is well-defined and honest.
- **For E1(b) — "how many the repair loop fixes within k rounds" — this is useless.**
  NL2LTL has no repair loop, no error-feedback interface, no re-prompt path. Any loop would
  be one *you* wrote around it, at which point it is your repair loop with NL2LTL as the
  generator, not an independent system. **Do not report an E1(b) number for NL2LTL.** Report
  it as k=0 / not-applicable and say why — that asymmetry is itself a finding.

### 6.5 VERDICT

> ## **BASELINE — scoped to E1(a) only. Estimated 9–14 hours (1.5–2 working days), gated on a 2-hour install spike today.**

**Why build it.** You are right that a same-system ablation is weak on its own. NL2LTL gives
you the thing that fixes it: an *independent, published, third-party* NL→LTL tool that
performs no schema validation whatsoever, and that an unrelated 2025 group (REQ2LTL) already
demonstrated is runnable as a comparison arm. The extensibility hook you need — a
user-supplied prompt file carrying a declared symbol vocabulary — is a first-class parameter,
not a fork. And the tool's total absence of symbol checking makes it a *fair* no-validation
baseline rather than a strawman.

**Why scope it.** It cannot speak to E1(b) at all, and its one-sentence-in/one-formula-out
granularity is not your system's granularity. Overclaiming a head-to-head would be worse
than not running it.

**The work, itemised:**

| Step | Hours |
|---|---|
| Python 3.10 venv; `pip install nl2ltl`; smoke-call one utterance end-to-end; patch `Models` / `SUPPORTED_MODELS` / `__check_openai_version` if the gates bite | **1–3** (the risk sits here) |
| Author `prompt.json`: `ALLOWED_SYMBOLS` = adapter sensor keys; 20–40 robot-skill NL/PATTERN/SYMBOLS exemplars | **3–5** |
| Harness: fixed-rule sentence split; `translate` per sentence; pylogics atom walk; set-difference vs. schema; wrap the `AttributeError` / `IndexError` crash paths and log them as failures (do not silently drop) | **3–4** |
| Analysis + writing the comparability caveats honestly | **2** |
| **Total** | **9–14** |

**Given E1 starts in three days, do this:** timebox the install spike to **2 hours today**.
If a single utterance round-trips to a formula, commit the remaining day and you get a real
independent arm. If it does not — model gates, a dead `openai==1.12.0` resolution, a
retired 3.5/4 endpoint — **stop immediately and downgrade to CITATION ONLY.** That downgrade
costs you nothing, because you need the citation regardless (it is the canonical
template-based NL→LTL package and reviewers will expect to see it in related work).

**Two things to write down whichever way it goes.** (1) Report NL2LTL as a *template-based
NL→LTL generator with no schema validation*, never as a competing spec compiler — the output
granularities differ. (2) Never cite REQ2LTL's numbers as NL2LTL's own results (§4.1).

---

## 7. Check yourself

**Q1. The abstract says NL2LTL is "fully extensible to new formulas and user inputs." Two
readers take that to mean two different things. Which reading survives contact with the
source, and what is the practical cost of the other?**

*A.* "Extensible to new **user inputs**" survives cheaply: `GPTEngine(prompt=Path(...))`
loads any JSON file with a `"prompt"` key, so new exemplars and a new `ALLOWED_SYMBOLS`
vocabulary cost one text edit and zero code. "Extensible to new **formulas**" survives only
as "the source is open." A new template requires a member added to the `@unique`
`TemplateEnum`, a new class in `declare/declare.py` implementing `to_ltlf` / `to_ppltl` /
`to_english`, and a function named exactly `ground_<lowercase enum value>` in
`grounding.py` (found by `getattr`, so misnaming it fails at call time). And it still would
not fully open the output space: `_get_formulas` runs `difflib.get_close_matches` against
the enum and takes `[0]`, so whatever the LLM emits is snapped onto the closed set anyway.

**Q2. Sketch, precisely, how NL2LTL turns "Send a Slack message whenever a response is
created in SurveyMonkey" into an LTL formula. Where in that chain could a hallucinated
symbol slip through?**

*A.* The full ~45-example prompt plus `NL: <utterance>\n` goes as one user message to the
chat completion. The model replies `PATTERN: response` / `SYMBOLS: Slack, SurveyMonkey`.
`gpt/output.py` regex-scrapes both lines. `_get_formulas` fuzzy-matches `"response"` to
`TemplateEnum.RESPONSE` and dispatches to `ground_response`, which builds
`Response(Atomic("slack"), Atomic("surveyMonkey"))` — positionally, first symbol as operand
0, each `decapitalize`d. `.to_ltlf()` yields `G(slack -> F surveyMonkey)`. Confidence is
hard-coded to `1`; `BasicFilter.enforce` returns the dict untouched. **A hallucinated symbol
slips through at the grounding step: nothing anywhere compares the scraped symbols against
the prompt's own `ALLOWED_SYMBOLS`.** `parse_gpt_result` builds `{e: 1 for e in output.entities}`
straight from the regex and grounds it verbatim. That absence of checking is a defect for a
user, and precisely the property that makes it a fair baseline for you.

**Q3. Why is NL2LTL usable as a baseline for E1(a) but not E1(b), and what should you
report for E1(b)?**

*A.* E1(a) counts specs referencing sensors the robot lacks. NL2LTL's APs are real surface
strings, not lifted placeholders, so with your sensor keys as `ALLOWED_SYMBOLS` you can walk
each returned formula, collect atoms, set-difference against the declared schema and count —
a well-defined measurement, made more meaningful by the fact that NL2LTL performs no such
check itself. E1(b) counts what a repair loop fixes within k rounds. NL2LTL has no repair
loop, no error-feedback channel and no re-prompt path; any loop would be one you wrote,
making it your loop with NL2LTL as generator rather than an independent system. Report E1(b)
for NL2LTL as not-applicable (k = 0) and state the reason — the asymmetry is a finding, not
a gap.

**Q4. You find a reported figure of "55.4% exact match for NL2LTL on industrial aerospace
requirements." Can you cite it as NL2LTL's result? What is the actual provenance?**

*A.* **No.** It is REQ2LTL's measurement (Ma et al., arXiv:2512.17334), from their Table III
row "GPT-4o + NL2LTL," where NL2LTL is used as a *prompting strategy* on a GPT-4o backend.
The shipped package cannot do that — its `SUPPORTED_MODELS` set is
`{gpt-3.5-turbo-instruct, gpt-3.5-turbo, gpt-4}` and `__check_model_support` raises on
anything else — so the number describes a reimplementation, on single-sentence aerospace
requirements, not robot skills. The AAAI demo paper itself, so far as could be established
here, reports no such evaluation at all. Cite it as "REQ2LTL report 55.4% for an
NL2LTL-style prompting baseline," with attribution to Ma et al., or not at all.
