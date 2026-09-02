# Spot — study guide for `skill_monitor`

**Subject:** Spot, the C++/Python library for LTL and ω-automata (Alexandre Duret-Lutz et al., EPITA Research Laboratory / LRE, formerly LRDE).
**Why this file exists:** Spot is the only non-stdlib dependency in `skill_monitor/core/automata.py` and it produces every automaton in the system. This guide answers three things: which paper to cite, whether the `translate()` call is the right one, and what determinism + completeness actually guarantee.

> **Provenance note — read this first.**
> `spot.lre.epita.fr`, `spot.lrde.epita.fr`, `arxiv.org`, `dblp.org` and `lrde.epita.fr` are all blocked by this host's egress proxy, so the live citing page could not be fetched directly. Everything below is instead verified against **Spot's own source tree** — the file `doc/org/citing.org` *is* the source that generates `citing.html` — together with `doc/org/ltl2tgba.org`, `doc/org/tut11.org`, `doc/org/hierarchy.org`, `spot/twaalgos/postproc.hh`, `spot/twa/twa.hh`, `spot/twa/twagraph.hh`, `spot/twaalgos/isdet.hh`, `spot/twaalgos/sccinfo.hh` and `python/spot/__init__.py`, read from a public mirror pinned at **Spot 2.12.1.dev** (`configure.ac`: `AC_INIT([spot], [2.12.1.dev], ...)`). The citation conclusion is independently corroborated by arXiv:2607.05907 (July 2026), read in full. Where a claim could not be verified it is marked **[unverified]**. Spot is not installed on this host, so nothing here was executed.

---

## 1. What Spot is, in one paragraph

Spot is a mature, open-source (GPL v3) C++ library — C++17, with command-line tools and Python bindings — for manipulating linear temporal logic formulas and ω-automata. It parses LTL and a subset of PSL in several syntaxes; it simplifies formulas, decides equivalence and implication, and classifies formulas in the Manna–Pnueli temporal hierarchy; it translates formulas into ω-automata with arbitrary (Emerson–Lei) acceptance conditions and converts between them (generalised Büchi, Büchi, co-Büchi, Rabin, Streett, parity, monitors); and it post-processes automata with simulation-based reduction, SAT-based minimisation, determinisation and completion. It reads and writes five automaton exchange formats, chief among them HOA. Around that core sit tools for model checking, reactive synthesis (`ltlsynt`), stutter-invariance checking, and random formula generation. For `skill_monitor` only one entry point matters: `spot.translate()`, which runs the whole LTL-to-automaton pipeline in a single call and hands back a `twa_graph` with BDD-labelled edges.

---

## 2. Key concepts

**ω-automaton.** A finite automaton read over *infinite* words. States and edges are finite; the acceptance condition talks about what happens infinitely often along a run. This is the right model for LTL, because LTL formulas are properties of infinite traces.

**Büchi acceptance.** A run is accepting iff it visits an accepting mark *infinitely often*. One acceptance set.

**Generalised Büchi (GBA/TGBA).** *Several* acceptance sets; a run is accepting iff it visits **each** of them infinitely often. Strictly more succinct than Büchi, not more expressive — degeneralisation converts GBA to BA at a cost in states. This is Spot's native output: `spot.translate()`'s default type is generalised Büchi (`postprocessor::GeneralizedBuchi`, historically spelled `TGBA`).

**State-based vs transition-based acceptance (`sbacc`).** Spot's automata carry acceptance marks on *edges* by default (the "T" in TGBA). With state-based acceptance, every outgoing edge of a state carries the same marks, so "is this state accepting?" is a well-formed question. This is not cosmetic for `skill_monitor`: `twa_graph::state_is_accepting()` in `spot/twa/twagraph.hh` begins with

```cpp
if (SPOT_UNLIKELY(!(bool)prop_state_acc()))
  throw std::runtime_error
    ("state_is_accepting() should only be called on "
     "automata with state-based acceptance");
```

so dropping `"sbacc"` would make `_compute_status()`, `_find_sink_states()` and `format_automaton()` throw. Note that `"Buchi"` alone does *not* imply state-based acceptance — the header comment is explicit: `Buchi = 256, // introduced in Spot 2.10, does not imply SBAcc`. Only the historical `"BA"` type implies it. (In `python/spot/__init__.py`, `'ba'` sets `type_ = postprocessor.Buchi; sbac_ = postprocessor.SBAcc` — so `"Buchi", "sbacc"` and `"ba"` request exactly the same thing.)

**Determinism / universality.** Spot separates two notions (`spot/twa/twa.hh`):
- *universal*: "the conjunction between the labels of two transitions leaving a state is always false" — i.e. **at most one** outgoing edge matches any given letter;
- *deterministic* (`spot/twaalgos/isdet.hh`): "An automaton is called deterministic if it is both universal and existential" — universal, plus a single initial state.

**Completeness.** From `spot/twa/twa.hh`: "An automaton is complete if for each state the union of the labels of its outgoing transitions is always true" — i.e. **at least one** outgoing edge matches any given letter. Completion is always achievable: you add a rejecting sink.

**BDD-labelled edges.** An edge is not labelled by a single letter but by a Boolean *formula over the atomic propositions*, stored as a BDD (via the BuDDy library that Spot bundles). One edge labelled `!obstacle` stands for the whole set of AP-assignments in which `obstacle` is false. A `bdd_dict` maps each AP `formula` to a BDD variable number (`bdd_dict::varnum(formula)`). This is why `_observation_to_bdd()` builds a full *cube* — a conjunction fixing every AP of the automaton to true or false — and then tests `bdd_and(edge.cond, cube) != bddfalse`: for a full cube that test is exactly "this letter satisfies this edge's condition".

**HOA (Hanoi Omega-Automata) format.** The text interchange format for ω-automata with arbitrary acceptance, designed jointly across the Spot, ltl3ba, Rabinizer, PRISM and Owl communities (Babiak et al., CAV'15). `aut.to_str("hoa")` emits it; it is the format to paste into a paper's artifact appendix. The `properties:` line of a HOA file records exactly the flags this guide is about — `deterministic`, `complete`, `state-acc`, `weak`, `terminal`, `stutter-invariant`.

**Manna–Pnueli hierarchy.** The classification that decides what kind of automaton a formula *can* have. From Spot's `doc/org/hierarchy.org`, verbatim:
- "The *reactivity* class represents all possible omega-regular languages, i.e., all languages that can be recognized by a non-deterministic Büchi automaton."
- "The *recurrence* subclass contains all properties that can be recognized by a **deterministic Büchi automaton**."
- "*Safety* properties … can be recognized by ω-automata that accept all their runs (i.e., the acceptance condition is "true"). … If we interpret the ω-automata with "true" acceptance as finite automata with all states marked as final, we obtain **monitors**, i.e., finite automata that recognize all finite prefixes that can be extended into valid ω-words."
- "*Guarantee* properties are a subclass of *obligation* properties that can be recognized by terminal Büchi automata (i.e., upon reaching an accepting state, any suffix will be accepted)."

Hold onto those last two: they are the whole of sections 4 and 5.

---

## 3. The API surface `skill_monitor` uses

| Call (in `automata.py`) | Declared in | What it guarantees |
|---|---|---|
| `spot.translate(f, "Buchi", "det", "complete", "sbacc")` (~line 108) | `python/spot/__init__.py` | Returns a `twa_graph`. Büchi acceptance: **guaranteed**. State-based: **guaranteed**. Complete: **guaranteed**. Deterministic: **preference only — see §5.** |
| `aut.get_dict()` (line 111) | `spot/twa/twa.hh` | The `bdd_dict` mapping AP `formula`s to BDD variable numbers. Shared across automata built with the same dict. |
| `aut.get_init_state_number()` (112, 202) | `spot/twa/twagraph.hh` | The initial state index. Single-valued only because the automaton is not alternating and (if `det` held) existential. |
| `aut.num_states()` (206, 251, 325, 394) | `spot/twa/twagraph.hh` | State count; states are `0 .. num_states()-1`. |
| `aut.out(s)` → `edge.dst`, `edge.cond` (218, 301, 339, 382, 397) | `spot/twa/twagraph.hh` | Iterates outgoing edges. `cond` is a BDD, not a letter. |
| `aut.state_is_accepting(s)` (206, 255, 307, 395, 407) | `spot/twa/twagraph.hh` | **Throws** unless `prop_state_acc()`. Hence `"sbacc"` is load-bearing. Returns `false` for a state with no outgoing edges. |
| `aut.ap()` (349, 370) | `spot/twa/twa.hh` | `const std::vector<formula>&` — the automaton's atomic propositions *after* translation, so possibly a subset of the formula's APs if some were simplified away. |
| `bdict.varnum(ap)` (349, 373) | `spot/twa/bdddict.hh` | BDD variable number for an AP. |
| `spot.bdd_format_formula(dict, bdd)` (215, 302) | `spot/twa/bddprint.hh` | Pretty-prints a BDD as a Boolean formula over AP names. Used by `graph()` and `format_automaton()`. |
| `spot.buddy.{bddtrue, bddfalse, bdd_ithvar, bdd_not, bdd_and, bdd_support, bdd_var, bdd_high}` (312, 340, 352–360, 369–377, 383, 400) | BuDDy, wrapped by `buddy.i` | Cube construction and support walking. |
| `aut.to_str("dot")` (166) | `spot/twa/twa.hh` + printers | DOT rendering. `"hoa"` is the one to use for anything a reviewer will read. |

Five notes on this surface.

**(a) The `translate()` option strings are parsed loosely.** `_postproc_translate_options` lowercases each argument and, if it is not an exact key, accepts it as an *unambiguous prefix* of one. `"det"` is a prefix only of `'deterministic'`, so it resolves. `"Buchi"` lowercases to `'buchi'`. This works, but a prefix that later becomes ambiguous when Spot adds an option would raise `ValueError: ambiguous option`. Spelling the options out (`"deterministic"`) removes that class of breakage for free.

**(b) `_observation_to_bdd` + `_find_successor` are correct — given the preconditions.** The cube fixes *every* AP of the automaton (missing keys default to `False`, a deliberate closed-world choice worth stating in the ICRA paper: an unobserved proposition is treated as false, not as unknown). Because the cube is total, `bdd_and(cond, cube) != bddfalse` holds iff the cube *implies* `cond`, so "first matching edge" is the right test. Whether it is the *only* matching edge is §5.

**(c) `_get_edge_aps` is right, and slightly wasteful.** `bdd_support()` returns a conjunction of positive variables, so walking `bdd_high` enumerates the cube correctly, and Spot's own `__init__.py` uses the identical `bdd_support`/`bdd_var`/`bdd_high` walk. But `var_to_ap` is rebuilt from `aut.ap()` on *every* edge, on every call — it is invariant per automaton and belongs in `__init__`. `get_required_aps()` runs per tick, so this is on the hot path.

**(d) On `spot.buddy` vs `buddy`.** Spot's own Python code (`python/spot/__init__.py`) uses the **bare** module name — `buddy.bddtrue`, `buddy.bdd_support(cond)` — and `python/spot/impl.i` contains `%import "buddy.i"`, which makes `buddy` a name inside `spot.impl`; `spot/__init__.py` then does `from spot.impl import *`. So `spot.buddy` works by re-export. It is not the spelling used anywhere in Spot's own sources or tutorials, and it is not documented API. **[unverified — could not run against a live Spot here.]** Low risk, but `import buddy` is the form Spot itself maintains.

**(e) The `graph()` warning at line 191 is well-reasoned.** Every idiom it names — `num_states()`, `get_init_state_number()`, `state_is_accepting()`, `out()` with `.dst`/`.cond`, `bdd_format_formula` — was checked against the Spot 2.12 headers above and all exist with the arities used. The argument in the docstring holds. The one thing a fake `aut` cannot exercise is the `state_is_accepting()` precondition throw, which is a property of `translate()`'s options rather than of `graph()`.

---

## 4. Question 2 — is `"Buchi", "det", "complete", "sbacc"` the right request?

**Short answer.** The *call* is reasonable and idiomatic, and given the formula population in this repo it is probably the right one to keep. But (i) Spot does have a dedicated monitor construction, it is not what you are using, and a formal-methods reviewer will ask why; and (ii) the way the resulting automaton is *interpreted* — `ACCEPTED = state_is_accepting(current)` — is unsound for the safety formulas in your spec set. That second point is the finding that matters.

### 4.1 Yes, Spot has a dedicated monitor construction

`postprocessor::Monitor` is a first-class output type (`spot/twaalgos/postproc.hh`), reachable as `spot.translate(f, 'monitor', 'det')`. From Spot's own tutorial `doc/org/tut11.org`, verbatim:

```python
import spot
print(spot.translate('!F(red & X(yellow))', 'monitor', 'det').to_str('HOA'))
```

and from `doc/org/ltl2tgba.org`: "These are finite automata that accept all prefixes of a formula. The idea is that you can use these automata to monitor a system as it is running, and report a violation **as soon as no compatible outgoing transition exist**." That is precisely the discipline `LTLMonitor.step()` is reaching for.

What it changes, all verified from `postproc.hh` and `tut11.org`:

1. **Acceptance becomes `t`** ("all"). Every run is accepting; the automaton is a DFA-with-all-states-final in disguise. Verdicts come from *stuckness*, not from acceptance marks.
2. **`det` is always achievable.** The construction is: translate to TGBA → `scc_filter` away SCCs that cannot reach an accepting cycle → `strip_acceptance_here` → determinise by classical powerset → minimise by standard DFA minimisation. `doc/org/ltl2tgba.org`: "`ltl2tgba -MD` … will output the **minimal deterministic monitor** for the given formula." Determinising a finite automaton always works; determinising a Büchi automaton does not (§5).
3. **`complete` behaves specially.** `postproc.hh`, Note 3: "while setting the output type to `Monitor` requests automata with `t` as acceptance condition, combining `Monitor` with `Complete` may produce Büchi automata in case a sink state (which should be rejecting) is added." So `translate(f, 'monitor', 'det', 'complete', 'sbacc')` gives exactly the shape `automata.py` already assumes: deterministic, complete, state-based, with one rejecting sink meaning *violation*. `_find_sink_states()` would work unchanged.
4. **It over-approximates non-safety formulas.** `postproc.hh`: Monitor "may output automata that recognize a larger language than the input (the output recognizes the **smallest safety property containing the input**)". `tut11.org` works the example: the monitor for `G(press -> red U green)` actually represents `G(press -> red W green)` — it will never complain that `green` failed to arrive.

### 4.2 Why you should *not* simply switch to `'monitor'`

Because of what that over-approximation does to your formulas. Grepping this repo, the monitored specs fall into two families:

- **Safety:** `G(!collision)`, `G(!obstacle)`, `G(!navigation_failed)`, `G(upright)`, …
- **Guarantee / nested-eventuality:** `F(goal)`, `F(mission_started && F(path_active))`, `F(target_received && F(path_planned && F(moving_towards_target && F(target_reached))))`, …

`doc/org/ltl2tgba.org` states the consequence flatly: "Because they accept all finite executions that could be extended to match the formula, **monitor cannot be used to check for eventualities such as `F(a)`**: indeed, any finite execution can be extended to match `F(a)`."

So for the entire nested-`F` family — the heart of the phase-tracking design, and what the state-annotation machinery in `format_automaton()` is built around — a Spot monitor collapses to a single state and never reports anything. Switching wholesale to `'monitor'` would be a regression.

### 4.3 The actual defect: `ACCEPTED` is unsound for safety formulas

This is the thing to fix before submission.

```python
def _compute_status(self) -> MonitorStatus:
    if self.current_state in self._sink_states:
        return MonitorStatus.VIOLATED
    if self.aut.state_is_accepting(self.current_state):
        return MonitorStatus.ACCEPTED
    return MonitorStatus.INCONCLUSIVE
```

and the docstring on `MonitorStatus.ACCEPTED` claims: "For a Büchi automaton this means the property holds over the finite prefix observed so far."

That is not what Büchi acceptance means. A Büchi run is accepting iff it visits an accepting state **infinitely often**. Visiting an accepting state once, after a finite prefix, settles nothing.

Concretely, for `G(!obstacle)` the minimal deterministic complete BA has an accepting initial state with an `!obstacle` self-loop, plus a rejecting sink. Therefore:

- `LTLMonitor("G(!obstacle)")` reports **`ACCEPTED` at construction time**, before a single observation.
- It keeps reporting `ACCEPTED` for as long as nothing goes wrong.
- `MultiMonitor.all_accepted()` therefore returns `True` for an all-safety spec on tick 0.

Same for `G(F(moving))`: accepting whenever `moving` holds, though `GF(moving)` can never be settled by any finite prefix.

The reason the bug has not bitten is that it is *invisible* on the guarantee family. `F(goal)` translates to a **terminal** Büchi automaton (see the hierarchy quote in §2: guarantee ⇒ terminal, "upon reaching an accepting state, any suffix will be accepted"), so its accepting state genuinely is a point of no return and `ACCEPTED` genuinely means "satisfied forever". The verdict function is accidentally right for guarantee formulas and wrong for everything else.

The standard framing is **LTL₃** (Bauer, Leucker, Schallhart — and note `papers/ltl3-bauer/` already exists in this tree): a finite prefix `u` gets verdict ⊤ if *every* infinite continuation of `u` satisfies φ, ⊥ if *none* does, and ? otherwise. `VIOLATED` in `automata.py` is already the ⊥ case done right. `ACCEPTED` is not the ⊤ case.

### 4.4 Recommendation

**Keep `spot.translate(formula, "Buchi", "det", "complete", "sbacc")`.** It is the only one of the three candidates that supports the whole system: it gives a *single* automaton per formula, with real states you can annotate with phases, walk for required APs, and ship in `manifest.automata`. A monitor cannot express your eventualities; a `'generic', 'det'` automaton would give guaranteed determinism but a parity or generalised-Büchi acceptance condition, which breaks `state_is_accepting()` outright (it throws unless `prop_state_acc()`).

Then make three changes, in decreasing order of importance:

1. **Fix the ⊤ verdict.** ⊤ is reachable on a finite prefix only when no continuation can escape the accepting region — i.e. when the current state is accepting *and* every state reachable from it is accepting. On a deterministic complete BA that is exactly "the current state sits in an accepting terminal component". Compute it once at construction, as the dual of `_find_sink_states()`. For safety formulas the set will correctly come out **empty**, and `G(!obstacle)` will read `INCONCLUSIVE` forever, which is the honest LTL₃ answer. If you want a genuinely settled ⊤ for safety properties you cannot get it from one automaton at all — the textbook LTL₃ construction needs a second automaton for `¬φ`, and ⊤ is reported when *that* one hits *its* rejecting sink.
2. **Assert the preconditions you rely on** (§5.5).
3. **Make `_find_sink_states()` complete.** It only recognises a *single-state* trap whose one edge is a `bddtrue` self-loop. A rejecting trap made of two or more states — or one whose self-loop Spot did not merge into a single `bddtrue` edge — is missed, and the monitor silently never reports `VIOLATED`. The robust predicate is "no accepting cycle is reachable from this state", which Spot exposes: `spot.scc_info(aut)` provides `is_useful_scc(scc)` / `is_useful_state(st)`, and `sccinfo.hh` is `%include`d by `python/spot/impl.i`, so it is available from Python. Spot's own monitor construction uses exactly this notion at step 2 ("remove SCCs that cannot reach an accepting cycle", `tut11.org`). **[unverified: I read the declarations of `is_useful_scc`/`is_useful_state` in `spot/twaalgos/sccinfo.hh`, not a doc comment defining "useful"; confirm the semantics against a live Spot before relying on it.]** Keeping the current cheap check as a fast path and the SCC computation as the source of truth is fine.

**What to say in the paper.** One sentence disarms the reviewer: *"Specifications are translated with Spot into deterministic, complete, state-based Büchi automata; we do not use Spot's monitor construction because it recognises the smallest safety property containing the specification and would therefore be vacuous for our nested-eventuality mission formulas. Verdicts follow LTL₃ semantics: ⊥ when no accepting cycle is reachable, ⊤ when no continuation leaves the accepting region, ? otherwise."*

---

## 5. Question 3 — what determinism + completeness actually buy

### 5.1 The guarantee, stated precisely

Let `A` be the automaton, `s` a state, and `σ` a total assignment of every AP in `A.ap()` (which is what `_observation_to_bdd` builds).

- **Complete** ⇒ *at least one* outgoing edge of `s` has `σ ⊨ cond`. Definition (`twa.hh`): "for each state the union of the labels of its outgoing transitions is always true."
- **Universal** ⇒ *at most one* outgoing edge of `s` has `σ ⊨ cond`. Definition (`twa.hh`): "the conjunction between the labels of two transitions leaving a state is always false."
- **Deterministic** = universal + existential (single initial state) (`isdet.hh`).

Together: **for every state and every total AP assignment there is exactly one outgoing edge.** So `_find_successor()` returning the *first* match returns *the* successor; the iteration order of `aut.out(s)` is irrelevant; `step()` is a total deterministic function of the observation; the automaton is a Mealy-style state machine you can index by an integer; and the `assert next_state is not None` at line 149 cannot fire. It also means the `state` integer shipped on each tick, indexed against the latched `manifest.automata` graph, is a faithful description of the monitor — which is the whole basis of the wire contract in `graph()`.

That is a real and useful guarantee. The caveat is that **you only get half of it for free.**

### 5.2 Caveat: `"det"` is a preference, not a guarantee

Two independent statements from Spot, both verbatim.

From `spot.translate`'s own docstring in `python/spot/__init__.py`:

> Keep in mind that 'Deterministic' expresses just a **preference** that may not be satisfied.

From `spot/twaalgos/postproc.hh`, on `set_pref()`:

> `Small` and `Deterministic` are exclusive choices … These are preferences. … The `Deterministic` option **may not manage to produce a deterministic automaton if the target acceptance set with set_type() is TGBA or BA** (and even if such automaton exists).
>
> Use
> ```
> set_type(postprocessor::Generic);
> set_pref(postprocessor::Deterministic);
> ```
> if you absolutely want a deterministic automaton. The resulting deterministic automaton may have generalized Büchi acceptance or parity acceptance.

`"Buchi", "sbacc"` is byte-for-byte what the historical `"BA"` type expands to in Spot's own option parser, so that sentence applies to your call.

By contrast, **`"complete"` is a genuine guarantee** — completion just adds a sink and always succeeds. `"sbacc"` is likewise honoured for Büchi output. So of the four options you pass, exactly one is best-effort, and it is the one the code depends on structurally.

### 5.3 Why it can fail: the LTL fragment matters

This is not a Spot limitation, it is a theorem. Deterministic Büchi automata are strictly weaker than nondeterministic ones. Spot's `doc/org/hierarchy.org` gives the exact boundary:

> The *recurrence* subclass contains all properties that can be recognized by a **deterministic Büchi automaton**.
>
> The *reactivity* class represents all possible omega-regular languages, i.e., all languages that can be recognized by a **non-deterministic** Büchi automaton.

So: **a deterministic Büchi automaton for φ exists iff φ is a recurrence property (or below: obligation, safety, guarantee).** For a strictly-reactivity formula — canonically a fairness implication such as `GF(a) -> GF(b)` — no DBA exists, and no amount of asking will produce one.

Your current formula population is safe on this axis. `G(!collision)` is safety; `F(a && F(b && F(c)))` is guarantee; `F(mission_finished) || G(upright)` is a Boolean combination of obligations, hence obligation; `G(F(moving))` is recurrence. All lie at or below recurrence, so a DBA exists for each. But nothing in `LTLMonitor.__init__` *enforces* that, and the spec formulas are generated (the LLM-translation pipeline in this repo) rather than hand-written. One fairness-shaped formula reaching `spot.translate` is enough.

### 5.4 What Spot does when it cannot

**It silently returns a nondeterministic automaton.** No exception, no warning, no flag in the return value that the code inspects. The automaton's `prop_universal()` is simply set to false (or `maybe`).

The failure is then *silent all the way down*, which is the worst property a monitoring core can have:

- `_find_successor()` finds several matching edges and returns whichever comes first in `aut.out()`. The monitor follows one arbitrary branch of a nondeterministic run.
- Both directions of error follow. The chosen branch can wander into a rejecting trap while another branch stays alive → **false `VIOLATED`**, i.e. the robot reports a fault that did not occur. Or it can stay in a live region while the property is in fact already dead → **missed `VIOLATED`**.
- The `assert` at line 149 never fires, because completeness still holds — it guards the wrong half of the invariant.
- `_find_sink_states()` still returns something plausible, and `graph()` still emits a well-formed graph. Nothing looks wrong.

### 5.5 The fix: two lines

Turn the silent assumption into a loud failure at construction time:

```python
self.aut = spot.translate(formula, "Buchi", "deterministic", "complete", "sbacc")
if not spot.is_deterministic(self.aut):
    raise ValueError(
        f"Spot could not produce a deterministic Büchi automaton for {formula!r}; "
        "the formula is not a recurrence property. Monitoring it would be unsound."
    )
assert spot.is_complete(self.aut)
```

Both functions are declared in `spot/twaalgos/isdet.hh` ("Return true iff `aut` is deterministic" / "Return true iff `aut` is complete"), and that header is `%include`d by `python/spot/impl.i`, so both are reachable from Python; `is_deterministic` is additionally bound as a `twa_graph` method in `python/spot/__init__.py`, so `self.aut.is_deterministic()` also works. Cost is one linear scan per formula, once, at construction — irrelevant next to translation itself. The cheaper `self.aut.prop_universal()` / `prop_complete()` read cached flags but return a *trival* (`true`/`false`/`maybe`), so they are not a substitute for a yes/no answer; `twa.hh` says as much: "If you need a true/false answer, prefer the `is_complete()` function."

If you would rather screen formulas before translating, Spot classifies them directly: `f.mp_class()` is bound as a `formula` method in `python/spot/__init__.py`, and the CLI equivalent is `ltlfilt --recurrence` (used in `hierarchy.org` for exactly this purpose). **[unverified: the exact return encoding of `mp_class()` — Spot uses single-letter class keys — was not confirmed here.]**

If you ever *must* monitor a non-recurrence formula, Spot's documented escape hatch is `spot.translate(f, 'generic', 'deterministic', 'complete')`, which will determinise at the cost of a parity or generalised-Büchi acceptance condition. Be aware that this breaks the rest of `automata.py`: `state_is_accepting()` throws on non-state-based acceptance and is meaningless for parity, so the verdict logic would have to be rewritten against `aut.acc()`.

### 5.6 Summary table

| Option | Status | If unmet |
|---|---|---|
| `"Buchi"` | Guaranteed | — |
| `"sbacc"` | Guaranteed for Büchi output | `state_is_accepting()` throws |
| `"complete"` | Guaranteed (a sink is always addable) | `assert` at line 149 fires (correctly) |
| `"det"` | **Preference only.** Achievable iff φ is a recurrence property or below | **Silent nondeterminism.** Arbitrary branch chosen; verdicts unsound in both directions; nothing raises |

---

## 6. Citation

### Which paper, and why

**Cite the CAV'22 paper: *From Spot 2.0 to Spot 2.10: What's New?***

Spot's citing page (`doc/org/citing.org`, the source of `citing.html`) opens its **"Generic reference"** section with:

> If you need to cite the Spot project, the latest tool paper about it is the following reference:
>
> ***From Spot 2.0 to Spot 2.10: What's new?***, *Alexandre Duret-Lutz*, *Etienne Renault*, *Maximilien Colange*, *Florian Renkin*, *Alexandre Gbaguidi Aisse*, *Philipp Schlehuber-Caissier*, *Thomas Medioni*, *Antoine Martin*, *Jérôme Dubois*, *Clément Gillard*, and *Henrich Lauko*. In Proc. of CAV'22, LNCS 13372, pp. 174–187. Haifa, Israel, Aug. 2022.

**The ATVA'16 "Spot 2.0" paper is listed under "Obsolete references."** This is the trap. Spot 2.0 (Duret-Lutz, Lewkowicz, Fauchille, Michaud, Renault, Xu, ATVA'16, LNCS 9938, pp. 122–129) is what most robotics and RV papers still cite, because for six years it was the right answer and it is what search engines surface first. It now sits in the same section of the citing page as the 2004 MASCOTS paper. Citing it as your primary Spot reference in an ICRA 2027 submission is a small but real signal to a formal-methods reviewer that the tooling was picked up second-hand.

**And state the version.** The citing page attaches a standing note to the generic reference:

> Tools evolve while published papers don't. Please always specify the version of Spot (or any other tool) you are using when citing it in a paper. Future versions might have different behaviors.

So the correct form is: *"…using Spot 2.x.y \[cite CAV'22]…"* with the actual version pinned. Take it from the machine that produced the results and put it in the artifact description; given §5, the version also matters because it fixes exactly which translation and determinisation heuristics ran.

### Which paper *not* to cite for this

**arXiv:2607.05907, *Teaching LTL and ω-Automata with Spot*** (Alexandre Duret-Lutz, EPITA Research Laboratory (LRE), 7 Jul 2026) is a **demo/teaching paper**, CC-BY, formatted for the LIPIcs series, with `Category: Demo` and a placeholder DOI (`10.4230/LIPIcs...`). It presents the browser-based LTL toolset at `spot.lre.epita.fr/app/`, the Jupyter notebook gallery at `spot.lre.epita.fr/tut.html`, the `spot-sandbox` Docker image, and `randltl`/`ltlfilt` recipes for generating exercises. It is not a tool-citation paper, and it does not supersede CAV'22 — internally it cites Spot as "[8, 9]", where [8] is ATVA'16 and [9] is CAV'22. Cite it only if you discuss teaching, the web app, or the notebooks; it is also useful corroboration that CAV'22 was still the current tool paper as of July 2026.

### Supporting citations you may additionally want

- **HOA format**, if you describe or ship automata in it: Babiak, Blahoudek, Duret-Lutz, Klein, Křetínský, Müller, Parker, Strejček. *The Hanoi Omega-Automata format.* CAV'15, LNCS 9206, pp. 479–486. DOI `10.1007/978-3-319-21690-4_31`.
- **The monitor construction**, only if you adopt §4.1: d'Amorim & Roşu, *Efficient monitoring of ω-languages*, CAV'05, LNCS 3576; as described by Tabakov & Vardi, *Optimized Temporal Monitors for SystemC*, RV'10, LNCS 6418. (Named as the sources of Spot's construction in both `postproc.hh` and `tut11.org`.)
- **LTL₃ semantics**, for §4.3: Bauer, Leucker, Schallhart — already in `papers/ltl3-bauer/`.

The exact BibTeX is in `bibtex.md` next to this file.

---

## 7. Check yourself

**Q1. `spot.translate(f, "Buchi", "det", "complete", "sbacc")` returns. Which of those four adjectives is the automaton not guaranteed to have, and what happens if it doesn't?**

*A.* `det`. It is a *preference*: `spot.translate`'s docstring says "'Deterministic' expresses just a preference that may not be satisfied", and `postproc.hh` adds that it "may not manage to produce a deterministic automaton if the target acceptance … is TGBA or BA (and even if such automaton exists)". If it fails, Spot returns a nondeterministic Büchi automaton with no error. `_find_successor()` then returns the first of several matching edges, i.e. picks one branch of a nondeterministic run arbitrarily — so the monitor can report a violation that did not happen, or miss one that did. The `assert next_state is not None` does not catch it, because completeness still holds. `"complete"` and `"sbacc"` *are* guaranteed.

**Q2. For which LTL formulas does a deterministic Büchi automaton exist at all, and what is the standard counterexample?**

*A.* Exactly the *recurrence* properties of the Manna–Pnueli hierarchy and everything below them (obligation, safety, guarantee) — verbatim from Spot's `hierarchy.org`: "The recurrence subclass contains all properties that can be recognized by a deterministic Büchi automaton." Strictly-reactivity formulas — canonically a fairness implication like `GF(a) -> GF(b)` — have no DBA. All of `skill_monitor`'s current formulas (`G(!collision)`, the nested-`F` mission sequences, `G(F(moving))`) are recurrence or below, so they are fine; but the spec formulas are machine-generated, so the property should be asserted rather than assumed.

**Q3. What exactly does `spot.translate(f, 'monitor')` build, and why would swapping to it break `F(mission_started && F(path_active))`?**

*A.* A finite automaton with acceptance `t` (all runs accepting) that recognises every finite prefix extendable to a model of `f`; violation is signalled by having no compatible outgoing transition. For non-safety `f` it recognises "the smallest safety property containing the input". Since *any* finite prefix can be extended to satisfy an eventuality, the monitor for a nested-`F` formula is trivial and never reports anything — Spot's own docs: "monitor cannot be used to check for eventualities such as `F(a)`". Its virtues are that `det` is always achievable (powerset + DFA minimisation gives the *minimal* deterministic monitor) and that `Monitor` + `Complete` yields precisely the "rejecting sink = violation" shape `automata.py` already assumes.

**Q4. `LTLMonitor("G(!obstacle)")` is constructed and `step()` has not been called. What does `.status` report, and is that right?**

*A.* `ACCEPTED` — the initial state of the DBA for `G(!obstacle)` is accepting, and `_compute_status()` maps "accepting state" to `ACCEPTED`. It is **wrong**. Büchi acceptance means visiting an accepting state *infinitely often*; visiting one after a finite prefix settles nothing, and a `G` property can never be settled true by a finite prefix. Under LTL₃ the verdict should be `?` forever. `MultiMonitor.all_accepted()` inherits the bug and will report `True` on tick 0 for an all-safety spec. The verdict happens to be correct for the nested-`F` family only because guarantee properties translate to *terminal* Büchi automata, where reaching an accepting state genuinely is irreversible. Fix: report ⊤ only when no reachable state is non-accepting (the dual of `_find_sink_states()`), or build the second automaton for `¬φ` as in textbook LTL₃.

**Q5. Which Spot paper goes in the ICRA submission, and what must accompany the citation?**

*A.* Duret-Lutz, Renault, Colange, Renkin, Gbaguidi Aisse, Schlehuber-Caissier, Medioni, Martin, Dubois, Gillard, Lauko. *From Spot 2.0 to Spot 2.10: What's New?* CAV'22, LNCS 13372, pp. 174–187 — the "Generic reference" on Spot's citing page. **Not** the ATVA'16 "Spot 2.0" paper, which that page now files under "Obsolete references" despite being what most robotics papers cite. It must be accompanied by the exact Spot version used, per the standing note on the citing page: "Tools evolve while published papers don't. Please always specify the version of Spot … you are using."
