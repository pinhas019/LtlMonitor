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

**This is live for us.** Both named failure modes in `specs/formulas_g1.json` are
that shape: `collision_imminent = G(!collision_risk)` and `fell_over = G(upright)`.
Whenever currently satisfied they read as `ACCEPTED` — "this safety property has
been established" — when the truth is "nothing has gone wrong yet."

Deciding ⊤ is a universality question and one automaton cannot answer it. Bauer et
al. use the product `Ã_φ × Ã_¬φ` (Lemma 2.5 / Def. 2.6). Esparza & Fischer's
restatement is the cleanest target: empty state → ⊥, universal state → ⊤, else `?`.

Cheapest honest fix if the product is too much for now: rename the member, and
correct the docstring to say what it actually tests.

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

Add the assertion. Also worth knowing before building anything: Spot already ships
`ltl2tgba -M -D`, a bad-prefix monitor (Tabakov & Vardi, RV'10).

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
