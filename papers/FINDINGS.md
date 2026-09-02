# Findings that touch the code

Distilled from the study guides in this directory. Everything here is a claim
about `skill_monitor`, not about a paper — the papers are cited so the reasoning
can be checked. Nothing here has been implemented.

Ordered by severity.

---

## 1. `ACCEPTED` does not mean what `automata.py:56` says it means

**Found independently by two agents** (`ltl3-bauer/`, `ltl-finite-observations/`).

`_compute_status` (`core/automata.py:404`) returns `ACCEPTED` iff
`aut.state_is_accepting(current_state)`. The docstring claims this means "the
property holds over the finite prefix observed so far." It does not. A *good
prefix* requires that **every** infinite continuation satisfies the formula —
`L(A_q) = Σ^ω`, no rejecting cycle reachable from `q`. Sitting in an accepting
state is much weaker: `state_is_accepting` is a Büchi condition about infinite
runs.

The counterexample needs no Spot. `G(!p)` is a safety property with **no good
prefixes at all** — no finite observation can establish that `p` will never hold —
yet any Büchi automaton for it sits in accepting states infinitely often along
`(¬p)^ω`. The monitor reports `ACCEPTED` where LTL3 says `?`.

**This is live for us, and the demonstration is one line.**
`LTLMonitor("G(!obstacle)")` reports `ACCEPTED` **before a single observation**,
and `MultiMonitor.all_accepted()` returns `True` on tick 0 for an all-safety spec.
Both named failure modes in `specs/formulas_g1.json` are that shape:
`collision_imminent = G(!collision_risk)` and `fell_over = G(upright)`.

It has stayed invisible because the guarantee formulas — the nested-`F` family —
translate to *terminal* automata, where an accepting state really is irreversible
and `ACCEPTED` really does mean what the docstring says. The safety modes are the
ones it is wrong for, and they are the ones that matter.

Deciding ⊤ is a universality question and one automaton cannot answer it. Bauer et
al. use the product `Ã_φ × Ã_¬φ` (Lemma 2.5 / Def. 2.6). Esparza & Fischer's
restatement is the cleanest target: empty state → ⊥, universal state → ⊤, else `?`.

Cheapest honest fix if the product is too much for now: rename the member, and
correct the docstring to say what it actually tests.

**A correction to the obvious fix.** Spot's dedicated monitor construction —
`translate(f, 'monitor', 'det', 'complete', 'sbacc')` — looks like it subsumes
this, and for safety formulas it does: `det` is *always* achievable there
(determinising a finite automaton always works), and `complete` adds exactly the
one rejecting sink `_find_sink_states()` already looks for. But **do not switch
wholesale.** Spot's own docs: a monitor "recognizes the smallest safety property
containing the input", so it "cannot be used to check for eventualities such as
`F(a)`". The entire nested-`F` family — `F(mission_started && F(path_active &&
...))`, which is the heart of the phase-tracking design and what
`format_automaton()`'s state annotation is built around — would collapse to a
single state and never report anything.

So the shape of the fix is **per formula class**, not one construction for all:
Spot monitors for the safety modes, the current Büchi path (with a corrected
`ACCEPTED`) for the nested-`F` progress formulas.

## 2. `_find_sink_states` is sound but incomplete

`core/automata.py:387` tests non-accepting **and** exactly one outgoing edge
**and** a `bddtrue` self-loop. LTL3's ⊥ is weaker: no accepting SCC reachable. So
the test misses **multi-state rejecting bottom SCCs** and `VIOLATED` under-reports
— the monitor stays `INCONCLUSIVE` on a permanently falsified property.

Fix is the paper's own step 3: SCC reachability, linear time.

## 3. `"det"` is a preference, not a guarantee

`spot.translate(formula, "Buchi", "det", "complete", "sbacc")` does not promise a
deterministic automaton — none exists for `FGp`. When Spot returns a
nondeterministic one, `_find_successor` (`:380`) silently takes the first matching
edge and the verdict is unsound. Nothing asserts otherwise.

`spot.translate`'s own docstring: "Keep in mind that 'Deterministic' expresses
just a preference that may not be satisfied." The theory boundary is exact — per
Spot's `hierarchy.org`, a deterministic Büchi automaton exists **iff the formula
is a recurrence property or below**. Every formula in the current specs qualifies,
which is why nothing has broken yet. But the specs are LLM-generated, and one
fairness-shaped formula (`GF a -> GF b`) is enough. Spot then returns a
nondeterministic BA **silently** — no exception, no warning — `_find_successor`
starts picking an arbitrary branch, and the line-149 assert stays quiet because
completeness still holds.

Fix is two lines: `spot.is_deterministic()` and `spot.is_complete()` at
construction, raising with the formula named.

## 3b. Missing APs default to `False`, which is fail-open

From `multi-property/`. `_observation_to_bdd` (`core/automata.py:367`) builds a
full cube over the automaton's AP set and defaults absent APs to `False`. For
`G(!collision_risk)` that is **fail-open**: an unevaluated `collision_risk` reads
as "no obstacle" and the safety property looks satisfied.

That interacts badly with two features working as designed — `get_required_aps()`
prunes aggressively, and an AP with no extractable rule goes to a slow LLM path
that may not have answered yet. This is the same hazard the UNDECIDED design in
`docs/clocking.md:165-198` exists to close, and it is unimplemented.

## 3c. `any_violated()` is sound but not anticipation-complete

From `multi-property/`. `MultiMonitor` runs one automaton per formula, which is
the right call for attribution — and the paper supports it: "one output per
property" is an explicit design requirement of their unified monitor, and the
conjoined-formula strategy is a tie in discrete time and measurably slower in
dense time while producing one undifferentiated verdict.

But the composition is not exact in one direction. ⊤ composes exactly, so
`all_accepted()` is sound and complete. ⊥ does not: **the conjunction can be ⊥
while every component sits at `?`**, so a joint monitor would fire where ours
stays silent.

It bites even when every formula is safety — `G(a→Xb)` and `G(a→X¬b)` after `a`
are each `?`, but their conjunction is `G¬a`, which is ⊥. So "safety formulas are
fine" is not the defence. Our `G(!collision_risk)` / `G(upright)` pair *is*
provably safe, being pure state invariants; the exposure is a liveness, PROGRESS
or TIMEOUT formula against a safety mode over shared APs — e.g. `F g` with
`G(h → G¬g)` after `h`, where both monitors say INCONCLUSIVE forever.

Suggested fix that keeps the hot path: an **offline product-emptiness certificate
at spec load** — look for a reachable product state that is empty while every
component projection is live. Buys the product's completeness at compile time,
keeps *n* parallel automata at runtime.

Do **not** cite that paper for semantic equivalence of the two strategies. It does
not claim it, and in their past-time setting it is false for a different reason.

## 3d. `_get_edge_aps` rebuilds its map per edge, per call, on the hot path

Minor, and performance only. `_get_edge_aps` reconstructs `var_to_ap` for every
edge on every call, and it is called each tick from `get_required_aps()`. Build it
once at construction.

## 4. Unsatisfiable specs pass the oracle

From `lang2ltl/`. `G(!p) & F(p)` passes a free-variable check and is
unmonitorable. Lang2LTL §7 reports AP-MDP rejecting unsatisfiable specs 12/12
where Code-as-Policies caught none; their Appendix Tables 2–3 supply 12 test
cases. Running the compiled formula through Spot's emptiness check is cheap and
sound, and it upgrades the oracle's claim from *executable* to *executable and
satisfiable*.

## 5. `invariant` and `progress_condition` are swappable without detection

From `nl2spec/`. `execution_phases` carries them as separate keys and
`undeclared_aps()` scans both through the same `scan()` call, so swapping them is
invisible to name resolution. An invariant that should have been a progress
condition halts a run that should have degraded. This is the concrete local
instance of the general limitation — the oracle catches *unexecutable*, never
*wrong*.

## 6. `undeclared_aps` gives no alternatives, and `unknown_keys` maybe gives too many

From `structured-feedback/` and `nl2spec/`, which point opposite ways. Both are
right and the tension is real.

- `unknown_keys` already emits location, observed value **and** the full list of
  legal alternatives — the feedback paper's strongest condition (+42 points).
- `undeclared_aps` emits only location and observed — their near-baseline policy.
  The alternatives are free: `declared` is already computed at
  `spec_contract.py:75`.
- But handing over alternatives is exactly what lets the model pick an
  executable-but-wrong one and exit reporting success, converting a loud failure
  into a silent one.

Alternatives improve convergence on *executability* while raising risk on
*semantics* — the repairer-side β the stopping paper warns about. The ~2 h proxy
that measures it: diff each repaired spec against its pre-repair version and count
edits outside the APs named in the problem list.

## 7. `attempts=2` is an unjustified constant

From `verify-repair-stop/`. It cannot cite that paper — the paper's thesis is that
fixed-k is the fragile shape of rule, and its K\*=2 is an artifact of injecting the
perturbation at round 3. Make it E1's independent variable: sweep k ∈ {0,1,2,3,4},
include k=0. A k=4 run replays as all k if the LLM calls are cached. ~5–7 h.

## 8. `0.75` on `visually_at_goal` is uncalibrated

From `embedding-tl/` and `foresight/`. `RESUME.md:593` records this threshold
already causing one incident. Two calibration routes exist and both run on the
`replay_node record` recording that was going to be made anyway: grid search on
labelled trajectories, or split conformal prediction for a nominal false-positive
rate.

Note the framing correction: `visually_at_goal` is **not** an instance of the
embedding paper's critique — it is the one AP already doing what they recommend.
`collision_risk` and the five planner-self-report APs are the instances.

## 9. `docs/clocking.md` contradicts itself

Lines 70 and 183. "Exactly one automaton step per tick, so `X` means Δ seconds
later" cannot hold alongside "an UNDECIDED tick does not step the automaton."
Under freeze, `X` means *next decided tick*. Related: freezing makes the observed
trace a **subsequence, not a prefix**, so a prefix guarantee does not transfer to
the real run. Reframe as "freezing is sound-but-incomplete under knowledge gaps,
and the coverage count is the completeness report."

---

## Terminology to adopt rather than invent

From `ltl3-bauer/` and `tl-synthesis-survey/`.

| ours | the established name | source |
|---|---|---|
| AP-level UNKNOWN | Kleene **K3** | standard |
| an UNDECIDED tick | a **knowledge gap** | Basin, Klaedtke & Zălinescu, FSTTCS 2015 |
| the alternative to freezing | **RVSE** | Stoller et al., RV 2011 |
| the ladder's gradedness | **least-violation / degree of satisfaction** | `tlsynthesis2026survey` Problem 3 |
| the REPLAN rung | **plan repair / patching / reconfiguration** | ibid. |

Two cautions. Do **not** call the ladder a *shield* — a shield sits in the action
path and the ladder does not. And do **not** add a fourth `MonitorStatus` member:
RV-LTL already added *presumably true* / *presumably false*, still about the
trace, so a fourth member would be read as that and invert the meaning.
