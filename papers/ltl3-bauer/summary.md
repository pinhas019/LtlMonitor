# Runtime Verification for LTL and TLTL — Bauer, Leucker & Schallhart (TOSEM 2011)

## Document actually read

I read the authors' ACM-format manuscript version of the paper, hosted on Martin Leucker's
group page at Universität zu Lübeck:

    https://www.isp.uni-luebeck.de/sites/default/files/publications/tosem09_prelim_1.pdf

Front matter of that PDF: title "Runtime Verification for LTL and TLTL"; ANDREAS BAUER
(NICTA and Australian National University), MARTIN LEUCKER (Technische Universität München),
CHRISTIAN SCHALLHART (Technische Universität Darmstadt); running footer "ACM Transactions on
Software Engineering and Methodology, Vol. x, No. y, mm 20yy, Pages 1–68"; and the note "This
is a revised and extended version of [Bauer et al. 2006b] appeared at FSTTCS 2006 in Kolkata,
India."

**This is the accepted-manuscript / preprint version, not the final ACM-typeset article.**
`dl.acm.org`, `dblp.org`, `link.springer.com`, `semanticscholar.org` and `arxiv.org` are all
blocked by this environment's network egress proxy, so the final typeset PDF could not be
opened. All definition, lemma, theorem and figure numbers below, and all page references, are
from that manuscript. They are very likely — but **not verified** — to be identical in the
published version.

The published venue record (volume/number/pages) was confirmed independently, see
`bibtex.md`.

The earlier RV-era line of work by the same authors, which the paper itself cites and which I
did **not** read in full (only its bibliographic records and the TOSEM paper's own
descriptions of it):

- FSTTCS 2006, "Monitoring of Real-Time Properties" — the conference precursor this article
  revises and extends (stated in the manuscript's front matter).
- RV 2007, "The good, the bad, and the ugly, but how ugly is ugly?" — introduces the
  four-valued RV-LTL that refines LTL₃'s `?`. Cited in the manuscript at p. 21 as
  "[Bauer et al. 2007]", explicitly "beyond the scope of this paper".
- J. Log. Comput. 20(3), 2010, "Comparing LTL Semantics for Runtime Verification" — cited in
  the manuscript as "[Bauer et al. 2008]".

I also read, in full, the reference list and §3.2 of Esparza & Fischer, "Runtime Verification
for LTL in Stochastic Systems" (arXiv:2508.07963), which restates this paper's monitor in a
form that is directly useful below.

---

## 1. What the paper does — one paragraph

The paper is the foundational, definitive treatment of monitoring LTL properties over the
finite, incrementally-growing prefixes that a running system actually produces. Its central
move is to refuse the two-valued finite-trace semantics that preceded it and to define
**LTL₃**: same syntax as Pnueli's LTL, but a finite word `u` is assigned `⊤` if *every*
infinite continuation of `u` satisfies the formula, `⊥` if *every* continuation violates it,
and `?` otherwise. It then gives a monitor-synthesis procedure — Büchi automaton for `φ` and
for `¬φ`, per-state emptiness, conversion to NFAs, determinisation, product, Moore-machine
output, minimisation — which is provably correct, produces the *unique state-minimal*
deterministic monitor, and reports `⊤`/`⊥` at the *minimal* good/bad prefix ("as early as
possible"). Around that construction it builds the vocabulary the field still uses: good, bad
and **ugly** prefixes; **monitorability** as the absence of ugly prefixes; the proof that the
monitorable properties strictly contain safety ∪ co-safety; and a structural picture of every
monitor as "an `?` region plus at most three traps (`⊤`, `⊥`, ugly `?`)". The second half
transfers the whole programme to the real-time logic TLTL, where the difficulty is that TLTL's
event-*predicting* clocks refer to a future the monitor has not seen; the authors solve this
with symbolic clock valuations and symbolic timed runs over event-clock automata.

---

## 2. Key concepts — definitions you must be able to state

### LTL₃ semantics (Definition 2.4)

Let `u ∈ Σ*` be a finite word, `Σ = 2^AP`, `B₃ = {⊥, ?, ⊤}`.

```
             ⎧ ⊤   if ∀σ ∈ Σ^ω : uσ ⊨ φ
[u ⊨ φ]  =   ⎨ ⊥   if ∀σ ∈ Σ^ω : uσ ⊭ φ
             ⎩ ?   otherwise
```

Note the shape of the quantifier. `u` is **fully known**; the uncertainty is entirely about
`σ`, the unseen future. Note also the notation: `[u ⊨ φ]` is a three-valued *semantic
function* on finite words; `uσ ⊨ φ` is ordinary two-valued LTL on infinite words.

### Good and bad prefixes (Definition 3.1, quoted from Kupferman & Vardi 2001)

For a language `L ⊆ Σ^ω` and a finite `u ∈ Σ*`:

- `u` is a **bad prefix** for `L` if for all `w ∈ Σ^ω`, `uw ∉ L`.
- `u` is a **good prefix** for `L` if for all `w ∈ Σ^ω`, `uw ∈ L`.

Both are closed under finite extension: any `uv` extending a bad (good) prefix is again bad
(good). A bad (good) prefix is **minimal** if no strict prefix of it is already bad (good).

**Remark 3.2** — LTL₃ *is* the good/bad-prefix classification: `[u ⊨ φ] = ⊤` iff `u` is a good
prefix for `L(φ)`, `⊥` iff `u` is a bad prefix, `?` otherwise. This is the sentence to
memorise; everything else is machinery for computing it.

### Ugly prefixes (Definition 3.3)

`u ∈ Σ*` is an **ugly prefix** for `L ⊆ Σ^ω` if there is **no** `v ∈ Σ*` such that `uv` is
either good or bad. Once you have read an ugly prefix, no future observation can ever produce
a verdict. Canonical example: any prefix of `GFp` — every finite word extends both to a model
and to a non-model, forever.

### Monitorability (Definition 3.4, following Pnueli & Zaks 2006)

- `φ` is **non-monitorable after `u`** if `u` is an ugly prefix of `L(φ)`.
- `φ` is **monitorable** if `L(φ)` has no ugly prefix — equivalently, if there is no `u` after
  which `φ` is non-monitorable.

### Safety / co-safety (Definitions 3.5–3.6, after Kupferman & Vardi, Alpern & Schneider)

- `L` is a **safety language** if every `w ∉ L` has a bad prefix.
- `L` is a **co-safety language** if every `w ∈ L` has a good prefix.
- An LTL formula is a safety (co-safety) property if `L(φ)` is a safety (co-safety) language.

The paper's own worked table: `Gp` safety; `Fq` co-safety; `Xp` both; `GFp` neither;
`Xp ∨ GFp` neither; `p U q` co-safety.

### Traps and the shape of every monitor (Figure 6)

A **trap** is a monitor state whose only transitions loop back to itself. The minimal monitor
`M_φ` has an `?`-emitting region and **at most three traps**: a `⊤` trap (good prefix read), a
`⊥` trap (bad prefix read), and an **ugly** trap that emits `?` forever. Reaching any trap
means monitoring can stop — the ugly trap means it stops *without ever having a verdict*.

### FSM (Moore machine)

`(Σ, Q, Q₀, δ, Δ, λ)` where `λ : Q → Δ` — **output is determined by the current state alone**,
not by the input symbol. Here `Δ = B₃`.

### TLTL and TLTL₃ (§4)

TLTL (Raskin 1999; called `LTL_ec` by D'Souza, who showed it is to timed traces what LTL is to
words — expressively equivalent to first-order logic, the timed analogue of Kamp's theorem)
adds two atomic forms to LTL over an alphabet of *events* with real time stamps:

```
φ ::= true | a | ◁a ∈ I | ▷a ∈ I | ¬φ | φ ∨ φ | φ U φ | X φ
```

- `◁a ∈ I` — an **event-recording** clock: the time *since* `a` last occurred lies in `I`.
- `▷a ∈ I` — an **event-predicting** clock: the time *until* `a` next occurs lies in `I`.

`I` ranges over intervals that may be open/half-open/closed, may be `[⊥,⊥]` (the event never
occurred / will never occur), or may extend to `∞`.

**TLTL₃ (Definition 4.14)** is LTL₃'s definition transplanted: `⊤` if every continuation `σ`
with `uσ ∈ TΣ^ω` satisfies `φ`, `⊥` if none does, `?` otherwise.

Why TLTL and not step-counting LTL: the paper's own motivating remark (p. 26) is that "event
`a` occurs within three time units" is *not* `XXXa`. `XXXa` presumes a fixed correspondence
between discrete delay and word position. TLTL deliberately decouples event frequency from
time stamps, which is what makes it usable for asynchronous systems.

**Event-clock automaton (Definition 4.16, Alur/Fix/Henzinger)**: `A_ec = (Σ, Q, Q₀, E, F)`
with `E ⊆ Q × Σ × Ψ_Σ × Q` — edges carry both an input event and a clock constraint — and `F`
a *generalised* Büchi acceptance condition (forced by the Raskin–Schobbens translation).

---

## 3. Method — the monitor construction, concretely

### LTL₃ (Figure 1, six steps)

| Step | From → To | Cost |
|---|---|---|
| 1 | `φ` → `φ`, `¬φ` | linear (just negate the *formula*, never complement the automaton) |
| 2 | `φ`, `¬φ` → NBAs `A_φ`, `A_¬φ` | exponential (Vardi–Wolper) |
| 3 | emptiness per state: `F_φ(q) = ⊤ iff L(A_φ(q)) ≠ ∅` | linear, via SCC decomposition (Tarjan) |
| 4 | → NFAs `Â_φ`, `Â_¬φ` with `F̂_φ = {q | F_φ(q) = ⊤}` | free (same graph, new accepting set) |
| 5 | → DFAs `Ã_φ`, `Ã_¬φ` by power-set | exponential again |
| 6 | product FSM, then minimise | Hopcroft |

Step 1 is the trick that makes the whole thing cheap: to get the automaton for the complement
language you complement the *formula*, not the Büchi automaton.

Step 3–4 is the trick that makes it *possible*: `Â_φ` is a finite-word automaton whose
accepting states are the states of the Büchi automaton from which some infinite accepted
continuation still exists. So `u ∈ L(Â_φ)` says exactly "`u` can still be extended into a
model of `φ`". This is why step 5's determinisation is safe — you determinise NFAs, where
subset construction always works, never Büchi automata, where it does not.

**Lemma 2.5 (LTL₃ evaluation).**

```
             ⎧ ⊤   if u ∉ L(Â_¬φ)                 (u cannot be extended to violate φ)
[u ⊨ φ]  =   ⎨ ⊥   if u ∉ L(Â_φ)                  (u cannot be extended to satisfy φ)
             ⎩ ?   if u ∈ L(Â_φ) ∩ L(Â_¬φ)
```

**Definition 2.6 (the monitor).** `Ā_φ = Ã_φ × Ã_¬φ = (Σ, Q̄, q̄₀, δ̄, λ̄)` with
`Q̄ = Q^φ × Q^¬φ`, `q̄₀ = (q₀^φ, q₀^¬φ)`, `δ̄((q,q'),a) = (δ^φ(q,a), δ^¬φ(q',a))`, and

```
                ⎧ ⊤   if q' ∉ F̃_¬φ
λ̄((q, q'))  =   ⎨ ⊥   if q  ∉ F̃_φ
                ⎩ ?   if q ∈ F̃_φ and q' ∈ F̃_¬φ
```

`M_φ` is the unique FSM obtained by minimising `Ā_φ`.

**Two automata, not one.** This is the structural point that matters most for anyone
reimplementing it: a single automaton for `φ` can tell you `⊥` (nothing left to accept) but it
*cannot* tell you `⊤`. Deciding "every continuation satisfies `φ`" is a universality question,
and universality of `φ` at a state is emptiness of `¬φ` at the corresponding state. Hence the
product.

### TLTL₃ (§4.3–4.6)

Same skeleton, much harder. Build event-clock automata `A_ec^φ` and `A_ec^¬φ` (Theorem 4.18,
Raskin & Schobbens: constructible, exponential in `|φ|`) and run both in parallel. The obstacle
is event-*predicting* clocks: a guard `γ(y_a) ∈ I` constrains the future, which online you have
not seen.

The fix: never evaluate a predicting clock; carry it symbolically.

- **Symbolic clock valuation (Definition 4.20)**: a pair `(q, Γ)` where `Γ` pins each
  event-*recording* clock to a point interval `[l,l]` (you know the past) but leaves each
  event-*predicting* clock as an interval of values still consistent with everything promised
  so far. Promises are accumulated by *conjunction* into one constraint, not a list. A
  transition is enabled only if the resulting future constraints are still consistent and
  satisfiable.
- **Incremental timed runs (Definition 4.24)** replace ordinary timed runs, because ordinary
  timed runs consume more than one event per transition and so cannot be executed
  incrementally; Proposition 4.25 shows the two are equivalent.
- **Symbolic timed runs (Definition 4.28)** require no information beyond the observed prefix
  (Remark 4.30) — the property that makes them usable online.
- Every timed run is abstracted by a symbolic one (Lemma 4.31). The converse *fails*: there
  are spurious symbolic runs (Proposition 4.32). Recovered by a backward-simulation argument
  (Lemmas 4.33, 4.34), yielding **Theorem 4.35** and the runtime-verification criterion
  **Corollary 4.36**: a prefix extends to an accepted word iff some symbolic timed run reaches
  a `(state, symbolic valuation)` pair with non-empty language.
- **Emptiness for symbolic states (§4.5)**: quotient automata over a *time-abstract
  bisimulation*, giving a look-up table over `(state, equivalence class)`. Instantiated with
  **region** equivalence. The paper flags explicitly that **zones** — what UPPAAL uses — are
  *not* a bisimulation and are therefore inapplicable here.

---

## 4. Results / what is proved

1. **Theorem 2.7 (correctness).** For the monitor `M_φ = (Σ, Q, q₀, δ, λ)` and all `u ∈ Σ*`:
   `[u ⊨ φ] = λ(δ(q₀, u))`. Proof is immediate from Definition 2.6 plus Lemma 2.5.
2. **Minimality.** The FSM is minimised by standard algorithms (Hopcroft 1971), giving the
   unique state-minimal machine: any smaller machine must be nondeterministic or check a
   different property.
3. **Earliest detection.** Because good/bad prefixes are closed under extension, every good
   (bad) prefix has a minimal good (bad) prefix, and the monitor emits `⊤`/`⊥` already at that
   minimal prefix. "As early as possible" is a theorem about the semantics, not a heuristic.
4. **Complexity.** The final FSM is in `O(2^(2^n))` in `|φ|`; a matching lower bound of
   `2^(2^Ω(n))` states holds, cited to Kupferman & Vardi 2001. The paper argues that any
   cheaper published construction is buying its speed either by restricting to a weaker LTL
   fragment or by using a variant of LTL that needs longer formulas for the same properties.
5. **Remark 3.7.** Every safety and every co-safety LTL formula is monitorable (no ugly
   prefixes, no ugly trap).
6. **Lemma 3.8 — the headline theoretical result.** The class of monitorable LTL₃ properties
   is **strictly larger** than safety ∪ co-safety. Witness: `φ = ((p ∨ q) U r) ∨ Gp`.
   `ppp…` satisfies `φ` with no good finite prefix, so `φ` is not co-safety; `qqq…` violates
   `φ` with no bad finite prefix, so `φ` is not safety; yet any prefix extends to a good one
   (append a letter containing `r`) or a bad one (append `{¬p, ¬q, ¬r}`), so `M_φ` has no ugly
   state. This kills the folk claim that "runtime verification only works for safety".
7. **The sharp caveat attached to Lemma 3.8.** For a *safety* property, never reaching the bad
   trap does mean the infinite word satisfies it — so an infinite output `???…` could in
   principle be read as "satisfied". For general monitorable properties that reasoning is
   invalid: both `ppp…` and `qqq…` produce the output stream `???…` for the formula above, yet
   one satisfies `φ` and the other does not. `?` forever is not evidence of satisfaction.
8. **Empirical evaluation (§2.5).** Dwyer et al.'s specification pattern collection: 447 specs,
   108 tagged LTL, 97 syntactically well-formed LTL. Monitors generated with the authors'
   "LTL₃ tools" on top of LTL2BA 1.1 (Gastin & Oddoux). **The manuscript is internally
   inconsistent here**: §2.5 (p. 16) reports **43** formulas whose monitor was a single
   `?`-state with a universal self-loop, while §3.1 (p. 20) says **44 out of 97**. Esparza &
   Fischer cite the published article as saying 43. Which number the *published* version
   carries is **not verified** — do not quote a figure without checking the ACM version. Either
   way: roughly 45% of a standard industrial pattern collection is not monitorable at all, and
   for the remainder no ugly trap appeared and monitor sizes were mostly under 100
   states/transitions, in the same range as the formula length despite the double-exponential
   worst case.
9. **Positioning against neighbours.**
   - d'Amorim & Roşu's "never-violate states" collapse *good* and *ugly* into one class. The
     paper argues they must be kept apart: in one case the property is *satisfied*, in the
     other *nothing can ever be shown*. This is the paper's own version of the argument you
     will want for `skill_monitor` (see §6).
   - Against Kupferman & Vardi's **informative prefixes** (and Geilen's tableau monitors built
     on them): informativeness is *syntax-dependent*. `Gp`, `G(p ∨ X false)` and
     `G(p ∨ F false)` are logically equivalent but are respectively *intentional*, *accidental*
     and *pathological* safety — the last has a bad prefix with no informative continuation.
     Monitoring should therefore be based on good/bad prefixes, which are semantic, and which
     honour the "as early as possible" maxim.

---

## 5. Limitations and scope

- **`?` is overloaded, by design.** LTL₃ cannot distinguish "keep watching, a verdict is still
  reachable" from "you are in the ugly trap, no verdict will ever come". The paper detects the
  difference *structurally* (an `?` trap in `M_φ`) but the *logic* does not express it. The
  authors say so and point at their own RV'07 four-valued **RV-LTL** (weak/strong next,
  "presumably true"/"presumably false") as the refinement, explicitly out of scope here (p. 21).
- **Double-exponential worst case**, with a matching lower bound. Unavoidable for full LTL.
- **Liveness is out of reach.** `GFp` and `G(r → Fa)` have no good and no bad prefixes at all.
  This is not a defect of the construction; it is what the semantics says. It is also why
  ~45% of the Dwyer patterns produce a trivial monitor.
- **No implementation for the timed case.** §5 states the discrete-time prototype exists but
  the real-time monitor "remains to be done as part of future work".
- **Propositional, finite, unparameterised.** Alphabet `2^AP` with `AP` finite; no data values,
  no quantification over parameters, no first-order or parametric monitoring. One monitor per
  formula.
- **The trace is assumed perfectly observed.** This is the limitation that matters most for
  `skill_monitor` and it is worth stating flatly: every letter of `u` is a *complete, known*
  element of `2^AP`. There is no notion in this paper of an observation that is missing,
  delayed, sampled away, out of order, or partially known. LTL₃'s entire uncertainty budget is
  spent on the *future* (`σ`), never on the *present*. See §6, question 2.
- **Untimed monitors are step-indexed, not clock-indexed.** In the LTL half, "next" means "next
  observation", and the paper itself uses this to motivate TLTL: `XXXa` is *not* "within three
  time units". Any deadline expressed as a step count is a claim about the observation
  sequence, not about wall time.

---

## 6. For `skill_monitor`

### Question 1 — Is `MonitorStatus` exactly LTL₃?

**The three-way split is exactly LTL₃'s idea, and should be cited as such. But of the two
non-`?` verdicts, one is a sound approximation and the other is a genuine mismatch.**

#### `VIOLATED` vs `⊥` — right idea, structurally narrower test

LTL₃'s `⊥` is "`u` is a bad prefix", which on a deterministic complete automaton is exactly
"the language from the current state is empty" — no accepting run is reachable any more.
That is Bauer et al.'s step (3): mark `q` iff `L(A(q)) = ∅`, computed in linear time by SCC
decomposition (Tarjan).

`_find_sink_states` (`automata.py:387`) tests something strictly narrower:

```python
if self.aut.state_is_accepting(s):  continue
edges = list(self.aut.out(s))
if len(edges) == 1:
    e = edges[0]
    if e.dst == s and e.cond == spot.buddy.bddtrue:
        sinks.add(s)
```

— non-accepting **and** exactly one outgoing edge **and** that edge a `bddtrue` self-loop.
This catches the canonical single rejecting trap, which is what Spot's simplification usually
emits for the formulas you are writing, so in practice it will often agree with `⊥`. It is not
the same predicate. It misses:

- a rejecting **bottom SCC with more than one state** (two mutually-reachable dead states);
- a dead state that kept two or more outgoing edges rather than being merged into one
  `bddtrue` self-loop;
- and, symmetrically, it is never *wrong* in the other direction — a `bddtrue` self-loop on a
  non-accepting state really is dead — so the current test is **sound but incomplete**: it can
  only report `VIOLATED` late or never, not early or spuriously.

The exact fix is small and is the paper's own step (3): compute the accepting SCCs once at
construction, then `state is ⊥ iff no accepting SCC is reachable from it`. That set is a strict
superset of the current `_sink_states` and coincides with LTL₃'s `⊥`. It also removes the
dependence on a Spot simplification detail that could change between Spot versions — which
matters given the `graph()` docstring's warning that this tree has never run against a real
Spot.

#### `ACCEPTED` vs `⊤` — this is the real divergence

`_compute_status` (`automata.py:404`) returns `ACCEPTED` whenever
`self.aut.state_is_accepting(self.current_state)`. **That is not LTL₃'s `⊤`.**

Büchi acceptance is a condition on *infinite* runs — accepting states must be visited
infinitely often. Being in an accepting state after a finite prefix carries no information
about whether every continuation satisfies `φ`. Take the system's own headline formula:

> `G(!collision_risk)`.

Its deterministic complete Büchi automaton is two states: an accepting state with a self-loop
on `!collision_risk`, and a rejecting sink reached on `collision_risk`. After *every* clean
tick the automaton sits in the accepting state, so `_compute_status` reports **`ACCEPTED`**.
LTL₃ says `[u ⊨ G(!c)] = ?` for **every** finite `u`, because `G φ` has no good prefix at
all — any prefix can still be continued into a violation. So on the safety properties that
dominate this codebase, `ACCEPTED` fires on every tick where LTL₃ is silent.

`ACCEPTED` does coincide with `⊤` on the co-safety-shaped formulas: for `F(goal)`, once `goal`
occurs the automaton is in an accepting state that is a *universal* trap, and there `ACCEPTED`
= `⊤` legitimately. So the relationship is: **`ACCEPTED` ⊇ `⊤`, and the extra cases are exactly
the accepting states that are not universal traps.** The current docstring — "For a Büchi
automaton this means the property holds over the finite prefix observed so far" — describes a
finite-word (Manna–Pnueli-style) two-valued reading, which is precisely the reading LTL₃ was
introduced to replace (Definition 2.4's note, and the `¬spawn U init` motivation on p. 5).

#### The exact test, if you want real LTL₃

Esparza & Fischer restate this paper's monitor for a deterministic automaton in one paragraph
(arXiv:2508.07963, §3.2), and it is the cleanest statement of what to implement. Partition the
states of the deterministic automaton `A` by the language `L(q)` from that state:

- `q` **empty** (`L(q) = ∅`) → `⊥`
- `q` **universal** (`L(q) = Σ^ω`) → `⊤`
- otherwise → `?`

and they note the partition is computable in polynomial time. Emptiness is the SCC test.
Universality on a deterministic automaton is emptiness of the complement — and the cheap way
to get it is exactly Bauer et al.'s: build a **second** automaton for `¬φ` and run it in
lockstep, applying Lemma 2.5. Your `LTLMonitor` currently builds one automaton, which is
structurally incapable of distinguishing `⊤` from `?`.

Minimal faithful change: in `LTLMonitor.__init__`, translate `formula` **and**
`"!(" + formula + ")"`, keep two current states, step both, and compute status by Lemma 2.5.
`_find_sink_states` is then replaced on both automata by the SCC-reachability test, and
`VIOLATED`/`ACCEPTED`/`INCONCLUSIVE` become literally `⊥`/`⊤`/`?`.

#### Two Spot facts worth checking before ICRA

Both verified from Spot's own documentation (`spot.lre.epita.fr`):

1. **`"det"` in `spot.translate` is a preference, not a guarantee.** Spot's docs state the
   Deterministic preference "expresses just a preference that may not be satisfied". Not every
   LTL property has a deterministic Büchi automaton — `FGp` is the standard counterexample. For
   such a formula `spot.translate(f, "Buchi", "det", "complete", "sbacc")` returns a
   **nondeterministic** BA, and `_find_successor` (`automata.py:380`) returns the *first*
   matching edge, so the monitor silently follows one arbitrary branch and its verdicts are
   unsound. Add a hard check at construction — assert `self.aut.prop_universal()` (Spot's
   property flag for deterministic) or `spot.is_deterministic(self.aut)` — and fail loudly
   rather than monitoring garbage. Note that Bauer et al.'s construction has no such hazard,
   *because* it determinises the NFAs (steps 4→5), never the Büchi automata; that is the whole
   reason for the NBA→NFA detour.
2. **Spot already ships a monitor construction.** `ltl2tgba -M` (with `-D` for deterministic)
   builds a finite automaton that rejects exactly the finite words that cannot be extended to a
   model — i.e. it recognises the bad prefixes, the `⊥` half of LTL₃ — following Tabakov &
   Vardi (RV'10). If you only need `⊥`, that is a ready-made and better-tested path than the
   `bddtrue`-self-loop heuristic.

#### The sentence to write in the ICRA paper

Use this, verbatim:

> We monitor each LTL property under the three-valued semantics LTL₃ of Bauer, Leucker and
> Schallhart [Bauer et al. 2011], which assigns a finite prefix ⊤ when every infinite
> continuation satisfies the formula (a *good prefix*), ⊥ when every continuation violates it
> (a *bad prefix*), and ? otherwise.

And, as long as `ACCEPTED` keeps its current meaning, immediately follow it with:

> Our VIOLATED verdict is LTL₃'s ⊥. Our ACCEPTED verdict is weaker than LTL₃'s ⊤: it reports
> that the automaton for φ currently occupies a Büchi-accepting state, not that the observed
> prefix is a good prefix.

**Stop presenting three-valued monitoring as a contribution.** It is 2011 in TOSEM and 2006 at
FSTTCS. The contribution of `skill_monitor` is elsewhere — the robot-side AP evaluation, the
freshness/clocking model, the spec contract, the record-replay determinism claim. Claiming the
semantics is new invites a reviewer to reject the whole paper on a single citation.

---

### Question 2 — Does monitorability justify the `UNDECIDED` design?

**Short answer: this paper does not justify it, because this paper's `?` is about the future,
not about missing data. But the distinction `docs/clocking.md` draws is entirely standard, and
there is established terminology to adopt instead of inventing some.**

#### Why the paper cannot be cited for it

Look again at Definition 2.4. `[u ⊨ φ]` quantifies over `σ ∈ Σ^ω`, continuations of a prefix
`u` that is **given and complete**. Each letter of `u` is a total element of `2^AP`. Nowhere in
the paper is there a letter that is unknown, a position that was not sampled, an AP whose value
the monitor failed to obtain, or a delayed/out-of-order arrival. The uncertainty axis is time
*forward*; `docs/clocking.md`'s axis is knowledge *now*. `docs/clocking.md:191–197` is
therefore correct on the substance: `MonitorStatus.INCONCLUSIVE` and `UNDECIDED` are different
axes, and citing Bauer et al. for the second would be a misattribution a reviewer could catch.

#### The distinction is standard — and so is the vocabulary

1. **At the AP level: Kleene's strong three-valued logic (K3).** An AP that is `TRUE`, `FALSE`
   or `UNKNOWN`, where `UNKNOWN` must never be silently read as `FALSE`, is Kleene's third
   value, standardly read as "unknown". Say "three-valued (Kleene) atomic propositions" rather
   than inventing a name. The `clocking.md` observation that `None` is falsy and `"UNKNOWN"` is
   truthy in `eval` — so *both* fabricate a SAFETY halt out of a dropout — is exactly the
   failure mode K3 exists to prevent, and is worth one sentence in the paper because it is a
   concrete engineering instance of a well-known semantic trap.

2. **At the tick level: "knowledge gap".** Basin, Klaedtke & Zălinescu, *Failure-aware Runtime
   Verification of Distributed Systems* (FSTTCS 2015), give MTL a three-valued semantics whose
   third value **models knowledge gaps** arising from crashes and lost or out-of-order
   messages, and resolve those gaps by propagating Boolean values through the formula structure
   as information later arrives. This is the closest published match to `UNDECIDED`: a value
   that is about what the monitor *knows*, not about what the trace *is*. **Adopt the term
   "knowledge gap" for an `UNDECIDED` tick.** (I located this via search and read the abstract;
   I could not fetch the full paper — the DROPS/Dagstuhl host is blocked here — so treat the
   detail beyond "three-valued semantics, third value models knowledge gaps, gaps resolved as
   values propagate" as **not verified**.)

3. **When the gaps come from sampling: "runtime verification with state estimation" (RVSE).**
   Stoller, Bartocci, Seyster, Grosu, Havelund, Smolka & Zadok, RV 2011, pp. 193–207. When
   monitoring overhead is reduced by sampling there are *gaps in the observed execution*; they
   treat the event sequence as the observation sequence of a Hidden Markov Model and estimate
   the probability that the property holds across the gap. This is the named alternative to
   freezing, and citing it lets you position "freeze" as a deliberate, conservative choice
   rather than the only option. (Abstract read via search; full text not fetched — **not
   verified** beyond that.)

4. **The general framing: monitoring under partial observability / imperfect information**, in
   which the verdict is explicitly about the monitor's *knowledge* rather than the trace. This
   is the phrase to use in the related-work sentence. I saw this framing in recent RV lecture
   notes (Bollig et al., "Runtime Verification: Monitoring, Knowledge, and Uncertainty",
   arXiv:2604.26753) surfaced by search but **could not fetch the document** — arXiv is blocked
   here — so **do not cite that one without opening it yourself.**

#### Is "not enough data is a statement about observation, not about the trace" standard?

Yes, and you can make it sharper than the doc currently does, using this paper.

The paper itself runs the identical argument one level down. It criticises d'Amorim & Roşu for
merging *good* and *ugly* into a single "never-violate" state (p. 20): both are states from
which no violation is reachable, so they are operationally identical, and merging them is
tempting — but the paper insists they must stay apart, because in one case the property has
been *satisfied* and in the other *nothing can ever be shown by monitoring*. That is precisely
your argument, transposed: two conditions that produce the same immediate behaviour but mean
different things must not share a slot. **Cite that passage.** It converts your design decision
from an assertion into a principle with a precedent.

There is a second, sharper reason to keep `UNDECIDED` out of `MonitorStatus`, and it is a
citation trap. **The RV literature already has a fourth truth value, and it means something
else.** Bauer, Leucker & Schallhart's own RV-LTL (RV 2007; and the JLC 2010 comparison paper)
extends LTL₃ with *presumably true* and *presumably false*, splitting LTL₃'s `?` using weak and
strong next operators. That fourth value is still a statement about the *trace*. If you add
`UNDECIDED` as a fourth member of `MonitorStatus`, a reader who knows the field will read it as
RV-LTL's fourth value and get your semantics exactly backwards. Keeping it on a separate
`DECIDED | UNDECIDED` axis is not just tidier; it avoids a live terminological collision with
the same authors' follow-up work.

#### On "`G(!collision_risk)` cannot be violated during a data outage"

That concession is correct under this paper's semantics, and you can state *why* rather than
just conceding it. `⊥` is defined by quantification over continuations of the **observed word**
`u`. If a tick is not appended to `u`, then `u` is unchanged, so `[u ⊨ φ]` is unchanged. Freeze
is the *semantics-preserving* choice, not merely a safe engineering hack. Phrase the trade-off
in standard terms:

> Freezing is **sound** — it never reports a bad prefix that is not one — but **incomplete**
> under knowledge gaps: a violation that occurred while unobserved is not detected.

And note the alternatives exist (RVSE estimates across the gap; Basin et al. resolve gaps
retroactively once the missing observation arrives). If your recorder can back-fill a late
message, gap *resolution* rather than permanent freeze is the principled upgrade — and
`core/recording.py`'s replay discipline is exactly the machinery that would make it testable.

#### One consequence `clocking.md` has not written down

Freezing the automaton also freezes the **step index**, and this paper is the reason that
matters. The LTL monitor is step-indexed: `X` means "next observation", not "next 100 ms". The
paper's own motivation for TLTL is that `XXXa` is *not* "`a` within three time units" (p. 26).
`format_automaton` already renders per-state `Timing: min N / max N steps [TIMEOUT on exceed]`.
If any such bound is counted in monitor steps, then every `UNDECIDED` tick silently *extends*
that deadline in wall-clock terms — a data outage buys the robot more time to reach the goal.
If deadlines are meant to be wall-clock, they must be measured against the tick clock, not the
automaton's step count, and the UNDECIDED design must be stated as applying to the LTL
transition only. This is a one-sentence limitation in the paper and a real bug if left
implicit.

---

## 7. Check yourself

**Q1. State the LTL₃ semantics, and say precisely which part of the trace the uncertainty
lives in.**

`[u ⊨ φ] = ⊤` if `∀σ ∈ Σ^ω : uσ ⊨ φ`; `⊥` if `∀σ ∈ Σ^ω : uσ ⊭ φ`; `?` otherwise. The prefix
`u` is given and completely known; the quantifier ranges only over the unobserved *future* `σ`.
LTL₃ has no way to express uncertainty about `u` itself.

**Q2. Why does the construction need automata for both `φ` and `¬φ`, and what goes wrong with
only one?**

A single automaton for `φ` can decide `⊥` — "no accepting continuation remains" is emptiness of
the language from the current state. It cannot decide `⊤`, because `⊤` asks whether the
language from the current state is *universal*, and universality of `φ` is emptiness of `¬φ`.
Bauer et al. get it by running `Ã_¬φ` in parallel (Lemma 2.5, Definition 2.6). A monitor built
from one automaton can only distinguish `⊥` from not-`⊥`; if it also reports "accepted" it is
reporting something other than `⊤`. That is exactly the `skill_monitor` situation.

**Q3. Give a monitorable property that is neither safety nor co-safety, and explain why the
monitor for it has no ugly trap.**

`φ = ((p ∨ q) U r) ∨ Gp` (Lemma 3.8). `ppp…` satisfies `φ` but has no good finite prefix → not
co-safety. `qqq…` violates `φ` but has no bad finite prefix → not safety. Yet from any prefix,
appending a letter containing `r` yields a good prefix and appending `{¬p,¬q,¬r}` yields a bad
one — so no prefix is ugly, and `M_φ` has no `?` trap. Corollary you must also remember: for
this `φ`, the output stream `???…` is produced by both `ppp…` (satisfying) and `qqq…`
(violating), so an eternal `?` is *not* evidence of satisfaction, even though for a pure safety
property it would be.

**Q4. In one sentence each, what are a bad prefix, a good prefix, an ugly prefix, and a
monitorable property?**

Bad prefix for `L`: a finite `u` such that `uw ∉ L` for all `w ∈ Σ^ω`. Good prefix: `uw ∈ L`
for all `w`. Ugly prefix: a finite `u` for which no finite `v` makes `uv` good or bad. `φ` is
monitorable iff `L(φ)` has no ugly prefix (equivalently: `M_φ` has no `?` trap); `φ` is
non-monitorable *after* `u` iff `u` is ugly.

**Q5. Your monitor reports `ACCEPTED` on every tick while running `G(!collision_risk)` cleanly.
Is that LTL₃'s `⊤`? What is the correct LTL₃ verdict, and what would you have to compute to get
it?**

No. `G ψ` has no good prefix, so LTL₃ says `?` for every finite prefix — the property can still
be violated at any later step. The code reports `ACCEPTED` because it tests
`state_is_accepting`, which is a Büchi condition about *infinite* runs, not a good-prefix test.
To get `⊤` correctly you must test whether the language from the current state is *universal* —
either via the empty/universal/other partition on a deterministic automaton, or, as Bauer et
al. do, by running a second automaton for `¬φ` and applying Lemma 2.5 (`⊤` iff `u ∉ L(Â_¬φ)`).
For `G(!collision_risk)` no reachable state is universal, so the correct verdict is `?` forever
until the sink is hit.
