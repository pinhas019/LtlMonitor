# Semantics for Linear-time Temporal Logic with Finite Observations

**Rayhana Amjad** (University of Edinburgh) · **Rob van Glabbeek** (University of Edinburgh) ·
**Liam O'Connor** (Australian National University).

arXiv:2411.14581v1 [cs.LO]. **Peer-reviewed venue exists**: EXPRESS/SOS 2024 (Calgary, 9 Sep 2024),
EPTCS 412, pp. 35–50, `doi:10.4204/EPTCS.412.4`. The masthead is printed on page 1 of the PDF.
**Cite the EPTCS version, not the preprint.**

There is also a **substantially extended journal-style successor**, arXiv:2608.23096
["The Infinite, in Finite Time"](https://arxiv.org/abs/2608.23096) (same three authors, 24 Aug 2026),
which contains this paper as a proper part and adds the monitorability theory you actually need.
See §7 below — for `skill_monitor` it is arguably the more useful of the two.

All page numbers below refer to the **arXiv PDF** as paginated by the retrieval tool
(PDF p.1 = printed p.35, so printed page = PDF page + 34).

---

## 1. In one paragraph

Bauer, Leucker & Schallhart's LTL₃ is the three-valued logic that every runtime monitor in the
LTL world is secretly implementing: read a finite prefix, return ⊤ if *every* infinite extension
satisfies the formula, ⊥ if every extension refutes it, and `?` otherwise. The problem this paper
identifies is that LTL₃ has **never been given a semantics of its own**. Its semantic descriptions
"are given only in terms of the relationship to conventional LTL" (abstract, p.1) — the definition
of `[t ⊧₃ φ]` literally quantifies over infinite extensions and calls out to `⊧`, the ordinary
infinite-trace satisfaction relation. Worse, Bauer et al. [BLS10] *claim* that LTL₃ cannot be given
an inductive (compositional) semantics at all, "a claim that is refuted by the present paper" (p.1).
What Amjad, van Glabbeek & O'Connor provide instead is a **full model-based inductive accounting**:
each formula is assigned an *answer-indexed family of definitive prefix sets* — a function from the
answer `{T, F}` to the set of all (finite or infinite) traces that settle the formula that way.
They prove these definitive sets form a complete lattice that is **isomorphic** to ordinary
linear-time temporal properties (sets of infinite traces), and hence that LTL₃'s semantics
*is* conventional LTL's semantics, merely re-presented — "LTL₃ is more accurately described as a
more detailed presentation of conventional LTL, rather than a distinct logic in its own right"
(p.14). They then formalise **formula progression** (the Brzozowski-derivative-style stepwise
evaluation used by real monitors) and prove it sound and complete-up-to-finite-traces against that
semantics, closing a gap that Bauer & Falcone had asserted without proof. Everything is mechanised
in Isabelle/HOL (>1700 lines; AFP entry `LTL3_Semantics`).

**The answer to the question you were sent to resolve:** previous LTL₃ semantics were given only
in terms of the relationship to **conventional (infinite-trace) LTL**. What this paper provides
instead is a **compositional, inductive, model-based semantics in terms of answer-indexed families
of definitive prefix sets**, plus an isomorphism theorem showing the two agree.

---

## 2. Key concepts — definitions you must be able to state

### 2.1 Traces

- `A` — atomic propositions. A **state** is `σ ∈ Σ = P(A)`, i.e. *a state just is the set of APs
  that hold in it* (p.2). This is important later: the model has **no notion of an AP whose value
  is unavailable**. Every state is total.
- `Σ*` finite traces, `Σ^ω` infinite traces, `Σ^∞ = Σ* ∪ Σ^ω` all traces. `ε` is the empty trace.
- Concatenation `tu`; **if `t` is infinite then `tu = t`** (p.2). `t₀` is the first state, `t|n` is
  `t` with the first `n` states dropped (`ε` if `n` exceeds the length).
- Primitives are `⊤, a, ¬, ∧, ○ (next), U (until)`. Everything else is derived:
  `◇φ ≜ ⊤ U φ`, `φ R ψ ≜ ¬(¬φ U ¬ψ)`, `□φ ≜ ⊥ R φ` (Figure 1, p.2).
  **`U` is strong** — `φ U ψ` requires `ψ` to actually occur.

### 2.2 Prefixes, extensions, definitive prefixes

    ↓t ≜ {u | ∃v ∈ Σ^∞. t = uv}          prefixes of t          (p.3)
    ↑t ≜ {tu | u ∈ Σ^∞}                   extensions of t        (p.3)
    ☇X ≜ {t | ↑t ⊆ ↓X}                    definitive prefixes of X   (p.4)

Equivalently and more usefully: **`☇X = {t | ↑t ∩ Σ^ω ⊆ X}`** — `t` is a definitive prefix of `X`
iff `X` contains *every* infinite extension of `t` (p.4). "Intuitively, this means that `☇X`
contains all those traces for which reaching `X ∩ Σ^ω` is in some way inevitable, even if it hasn't
happened yet" (p.4).

A set `X ⊆ Σ^∞` is **definitive** iff `X = ☇X`. `D` is the set of all definitive sets.

Facts stated on p.4, all "straightforwardly from the definitions":
- `☇X ⊆ ↓X` — all definitive prefixes are prefixes.
- `☇☇X = ☇X` — `☇X` is itself definitive (`☇` is a closure operator).
- **`∀t ∈ ☇X. ↑t ⊆ ☇X`** — *any extension of a definitive prefix is a definitive prefix.*
  This is the irrevocability property, and it is the one you will cite most.
- `☇` distributes over arbitrary intersection.

`∅` and `Σ^∞` are definitive. Definitive sets are **closed under intersection but NOT under union**
(p.4) — counterexample given: with `Σ = {A,B}`, `X_A` (traces starting with A) and `X_B` are both
definitive, but `ε ∉ X_A ∪ X_B` while `ε ∈ ☇(X_A ∪ X_B)`, since every non-empty trace starts with
one or the other. Definitive sets are **not closed under complement** either (p.7).

**Definitive union**: `⋃☇ S ≜ ☇(⋃S)` (p.4). With this, `(D, ⊆)` is a **complete lattice**:
supremum = definitive union, infimum = intersection, top = `Σ^∞`, bottom = `∅` (Theorem 1, p.4).

### 2.3 Good, bad, ugly prefixes (§6.1, p.12)

Kupferman & Vardi's definitions, restated in this paper's notation:
- **bad prefix** of `P ⊆ Σ^ω`: a finite prefix that *cannot* be extended to a trace in `P`.
- **good prefix** of `P`: a finite prefix *all* of whose infinite extensions are in `P`.
- Then: **`☇P` = `P` together with all its good prefixes**, and **the bad prefixes of `P` are
  `☇(Σ^ω \ P)`** (p.12). So an answer-indexed family `B → D` "can be thought of as tracking both
  the good and bad prefixes of a property simultaneously, along with the infinite traces that they
  approximate" (p.12).
- **ugly prefix** (Bauer et al. [BLS10]): a finite prefix that cannot be *finitely extended* into
  either a good or a bad prefix. **"The presence of ugly prefixes means that the formula is
  non-monitorable"** (p.12).

⚠️ **The trap the paper points out explicitly**: good, bad and ugly do **not** partition the finite
prefixes. `ppp…` is neither in `⟦p U q⟧₃ T` nor `⟦p U q⟧₃ F`, "but it is not ugly either, as it can
be extended with `q` giving a good prefix, or with `∅` giving a bad prefix" (p.12). Do not write
"every prefix is good, bad or ugly" in your paper.

### 2.4 LTL₃ itself (p.3) — memorise this

    [t ⊧₃ φ] = T   if ∀u ∈ Σ^ω. tu ⊧ φ
             = F   if ∀u ∈ Σ^ω. tu ⊭ φ
             = ?   otherwise

The paper's reading of `?` is the thing to steal:

> "Because the truth value `?` indicates merely that neither `T` nor `F` apply, LTL₃ can be better
> understood as a **two-valued partial logic** [Bla02], where `?` indicates the **absence of a truth
> value**. In this view, LTL₃ only gives truth values when the trace is definitive, i.e., when the
> answer given will not change regardless of how the trace is extended." (p.3)

**Why LTL₃ looks non-inductive** (p.3, the argument you should be able to reproduce):
take `φ = ○a ∨ ○¬a`. Then `[ε ⊧₃ φ] = T` (it is a tautology), but `[ε ⊧₃ ○a] = [ε ⊧₃ ○¬a] = ?`.
Take `ψ = ○b ∨ ○¬c`: components again both `?`, yet `[ε ⊧₃ ψ] = ?`. So no truth-function on `B₃`
can compute `∨` correctly for both. The paper's diagnosis: **"this claim applies only to the
multi-valued semantics defined above"** (p.3) — the obstruction is to a *truth-value-functional*
semantics, not to a *model-based* one.

### 2.5 LTLf / Pnueli's finite LTL — and why it is the wrong tool

Named in the introduction (p.1) and §6.3 (p.14) but **not** developed. The paper's position is
sharp and worth quoting in your related work:

> "The oldest such variant, commonly attributed to Pnueli, concerns finite **or infinite completed**
> traces, but this is also not suitable for the context of runtime monitoring, as our finite
> observations are not completed traces, but **finite prefixes of infinite behaviours: partial
> traces**." (p.1)

The successor paper puts it in one line: "the behaviour of the system is still infinite, it is only
our observation of the behaviour that is finite" (2608.23096 p.2). Footnote 1 (p.1) adds a
bibliographic caution: the attribution to Pnueli is loose — Manna & Pnueli (1995), "which is usually
cited, does not mention finite traces at all"; the actual source is closer to Lichtenstein, Pnueli &
Zuck (1985).

### 2.6 The paper's own contributed vocabulary

- **definitive prefix set / definitive set** — §2.2 above.
- **answer-indexed family** — "a function that, given an answer (e.g. a value in `B = {T,F}`),
  produces a set of models" (p.5). The presentational inversion: **`a = [σ ⊧ φ]` becomes
  `σ ∈ ⟦φ⟧ a`**. For conventional LTL, `Φ ∈ B → P(Σ^ω)`; for LTL₃, `Φ ∈ B → D`.
- **prepend** `▷X ≜ {t | t|1 ∈ X}` (p.7) — "all traces whose tails are in `X`". Theorem 5: closed
  for definitive sets.
- **formula progression** `φ --σ--> ψ` (Figure 5, p.9) — "to prove `φ`, it suffices to prove `ψ`
  for the tail of our trace if the head of our trace is `σ`". The rules are **total and
  syntax-directed on `φ`**, so they define a total function. Generalised to `φ --t--> ψ` for finite
  `t`. The only interesting rule: `φ U ψ --σ--> ψ' ∨ (φ' ∧ (φ U ψ))`.

---

## 3. The semantics they give, and how it differs from prior characterisations

### 3.1 The move

Prior work: `[t ⊧₃ φ]` is a **function taking a formula and a prefix to a truth value**, defined by
quantifying over infinite extensions and deferring to `⊧`. That is *extensional* and *external* —
it explains LTL₃ by pointing at LTL.

This paper: `⟦φ⟧₃ ∈ B → D`, defined by **structural recursion on `φ`**, with each connective given
its own operator on answer-indexed families. Nothing in the LTL₃ clauses mentions `⊧`.

### 3.2 The isomorphism (the technical core, §3.2, p.4–5)

    Pr : D → P(Σ^ω),   Pr(X) = X ∩ Σ^ω          (lower adjoint)
    Df : P(Σ^ω) → D,   Df(P) = ☇P               (upper adjoint)

**Theorem 2** — for any definitive `X` and any linear-time property `P`:
`Pr(X) = P` **iff** `X = Df(P)`.
**Theorem 3** — `Pr` (and `Df`) is monotone and preserves least upper and greatest lower bounds:
`Pr(⋂ᵢ Xᵢ) = ⋂ᵢ Pr(Xᵢ)` and `Pr(⋃☇ᵢ Xᵢ) = ⋃ᵢ Pr(Xᵢ)`.
Together: **`(Pr, Df)` is a lattice isomorphism between definitive sets and linear-time temporal
properties** (p.5). *A definitive set is uniquely determined by its infinite traces; the finite
definitive prefixes are recoverable, not extra information.*

### 3.3 The clauses (§4.3, p.7–8)

For conventional LTL (Figure 3, p.6), the `F` operators are exactly dual to the `T` ones, so
`⟦φ⟧ F = Σ^ω \ ⟦φ⟧ T` always, and `¬` is just a swap — "akin to performing a conversion to negation
normal form 'just-in-time'" (p.6).

For LTL₃ (p.7), the same shape, but over `D`, and **the duality breaks**:

    ⊤₃ T = Σ^∞                    ⊤₃ F = ∅
    (Φ ∧₃ Ψ) T = Φ T ∩ Ψ T        (Φ ∧₃ Ψ) F = Φ F ∪☇ Ψ F
    (Φ ∨₃ Ψ) T = Φ T ∪☇ Ψ T       (Φ ∨₃ Ψ) F = Φ F ∩ Ψ F
    (¬₃ Φ) T = Φ F                (¬₃ Φ) F = Φ T

    ⟨a⟩₃ T = ☇{t | t ≠ ε ∧ a ∈ t₀}
    ⟨a⟩₃ F = ☇{t | t ≠ ε ∧ a ∉ t₀}

    (○₃ Φ) T = ▷(Φ T)             (○₃ Φ) F = ▷(Φ F)

    (Φ U₃ Ψ) T = ⋃☇_{k∈ℕ} f^k(Ψ T),  f(X) = ▷X ∩ Φ T
    (Φ U₃ Ψ) F = ⋂_{k∈ℕ}  f^k(Ψ F),  f(X) = ▷X ∪☇ Φ F

Two details worth understanding rather than copying:
- **Why `☇` wraps the atomic clauses.** If `a` is trivial (satisfied by all states, or by none),
  then `{t | t ≠ ε ∧ a ∈ t₀}` is *not* definitive, because `ε` would then also be definitive for it.
  Taking `☇` repairs this (p.7).
- **Why `∨` needs definitive union but `∧` does not.** `D` is closed under `∩` but not `∪` (§2.2),
  so the join must be `☇(·∪·)`. This is precisely the machinery that makes `○a ∨ ○¬a` come out `T`
  at `ε` compositionally — the counterexample that was supposed to prove inductive semantics
  impossible.

### 3.4 The three equivalence theorems

- **Theorem 6 (equivalence to original LTL₃)** — for finite `t`:
  `t ∈ ⟦φ⟧₃ T ⟺ ∀u ∈ Σ^ω. tu ∈ ⟦φ⟧ T`, and dually for `F` (p.8). *Proof: "follows directly from the
  definition of definitive sets."*
- **Theorem 7 (equivalence to conventional LTL)** — `Pr(⟦φ⟧₃ T) = ⟦φ⟧ T` and `Pr(⟦φ⟧₃ F) = ⟦φ⟧ F`
  (p.8). Proof by induction on `φ`; the `U` case is the work.
- **Theorem 8 (Excluded Middle)** — `⟦φ⟧₃ T = ☇(Σ^ω \ ⟦φ⟧₃ F)` and `⟦φ⟧₃ F = ☇(Σ^ω \ ⟦φ⟧₃ T)`
  (p.9). The two sets **do not overlap** but are **not complements**; the `F` set is the definitive
  set corresponding to the property of all infinite traces not in the `T` set.

---

## 4. Results — what is actually proved

| # | Statement | Where |
|---|---|---|
| Thm 1 | Definitive union gives least upper bounds; `(D, ⊆)` is a complete lattice | p.4 |
| Thm 2 | `Pr(X) = P ⟺ X = Df(P)` — definitive sets ≅ linear-time properties | p.4 |
| Thm 3 | `Pr`/`Df` monotone, preserve lubs and glbs ⟹ lattice isomorphism | p.5 |
| Thm 4 | Answer-indexed-family LTL ≡ conventional LTL: `(t ⊧ φ) ⟺ t ∈ ⟦φ⟧ T` | p.6 |
| Thm 5 | Prepend `▷` is closed for definitive sets | p.7 |
| Thm 6 | The inductive LTL₃ semantics ≡ Bauer et al.'s original LTL₃ definition | p.8 |
| Thm 7 | `Pr(⟦φ⟧₃ T) = ⟦φ⟧ T`, `Pr(⟦φ⟧₃ F) = ⟦φ⟧ F` — LTL₃ ≡ conventional LTL | p.8 |
| Thm 8 | Excluded Middle: `⟦φ⟧₃ T = ☇(Σ^ω \ ⟦φ⟧₃ F)` and conversely | p.9 |
| Thm 9 | One progression step, soundness direction: `▷(⟦φ'⟧₃ a) ∩ {t \| t₀=σ} ⊆ ⟦φ⟧₃ a` | p.10 |
| Thm 10 | One progression step, completeness direction: `⟦φ⟧₃ a ∩ {t \| t₀=σ} ⊆ ▷(⟦φ'⟧₃ a)` | p.11 |
| Thm 11 | **Progression sound & complete up to finite traces**: for `φ --t--> φ'`, `t ∈ ⟦φ⟧₃ T ⟺ ⟦φ'⟧₃ T = Σ^∞` (dually for `F`) | p.11 |

Mechanisation: "over 1700 lines of Isabelle/HOL proof script" (p.14), AFP entry
[`LTL3_Semantics`](https://isa-afp.org/entries/LTL3_Semantics.html).

### 4.1 The simplifier result — the practically important one

Bauer & Falcone proposed progression *as* a semantics for LTL₃: `φ` is definitively true for `t`
iff `φ --t--> ⊤`, false iff `φ --t--> ⊥`. This paper shows that framing is **incomplete without a
tautology-checking simplifier**, and that this is not a performance detail:

- `◇a` progressed by a state satisfying `a` yields `⊤ ∨ (⊤ ∧ ◇a)` — right answer only after
  propositional simplification (p.10).
- Worse: `(○a) ∨ (○¬a)` "should be considered definitively true for the empty trace, as it is a
  tautology", but "temporally local simplifications … would not be able to determine that this
  formula is a tautology until after one state has been observed" (p.10).
- Hence: "in order for formula progression to align correctly with the semantics of LTL₃, the
  simplification must transform **all** tautologies into `⊤` and **all** absurdities into `⊥`"
  (p.10). Their suggested (slow) implementation: "convert both the formula and its negation into
  Büchi automata, and perform cycle detection to check for emptiness" (p.10).

Theorem 11 sidesteps syntax entirely by replacing "is literally `⊤`" with "**has trivial
semantics**" (`⟦φ'⟧₃ T = Σ^∞`). Rœu & Havelund's warning about pathological exponential blow-up
in progression is acknowledged (p.10).

---

## 5. Limitations and scope

1. **This is a semantics paper, not an algorithm paper.** No complexity results, no monitor
   construction, no benchmarks, no implementation beyond the Isabelle development. It gives you
   vocabulary and theorems, not code.
2. **`Σ = P(A)` is total.** Every state completely determines every AP. There is **no model of a
   missing, stale, or unobservable atomic proposition anywhere in the paper.** (See §6.2 — this is
   the single most important gap for you.)
3. **No time.** No `Δ`, no sampling, no continuous time, no timed logics. TLTL appears only inside
   a reference title. **Discretisation is not discussed at all** — this paper cannot answer your
   question 3 directly, and saying it does would be inventing a claim.
4. **Future/past.** "As we only include future temporal operators, we can advance to the future by
   dropping initial prefixes" (p.2). Past-time LTL is out of scope.
5. **Safety/liveness is a conjecture here, not a theorem.** §6.2 (p.13) gives characterisations —
   `X` is liveness iff `Σ* ⊆ ↓X`; `X` is co-safety iff `X = ↑(X ∩ Σ*)` — but says only that these
   are "an alternative characterisation that we **conjecture** is equivalent to that of Alpern and
   Schneider". **The successor paper 2608.23096 proves it** and should be cited instead if you rely
   on it.
6. **Monitorability is discussed, not formalised.** §6.1 notes that ugly prefixes ⟹
   non-monitorable, and *conjectures* that Bauer et al.'s and Aceto et al.'s notions of
   monitorability coincide. Again: **the successor paper formalises this into a hierarchy.**
7. **RV-LTL is critiqued, not fixed.** §6.3 says an inductive semantics for RV-LTL "can be designed
   along similar principles … where our answer-indexed families instead produce four sets, two of
   which are definitive" — stated as belief and future work, not done.
8. **No decidability/finite-state claim about `⟦φ⟧₃`.** The `U` clauses are infinite unions and
   intersections over `ℕ`. Turning them into automata is not attempted.

---

## 6. For `skill_monitor`

Read this section against `skill_monitor/core/automata.py` and `docs/clocking.md`.

### 6.0 Summary of the verdict

Your informal semantics is **defensible in outline and wrong in one specific place**. The
`VIOLATED` and `INCONCLUSIVE` verdicts line up with LTL₃ exactly. **`ACCEPTED`, as implemented,
does not.** Fixing it is a ~20-line change plus a paragraph, and not fixing it is the kind of thing
a TACAS/NFM reviewer finds in the first ten minutes.

---

### 6.1 Question 1 — is the informal semantics defensible, and what is the correct vocabulary?

**Yes, and the vocabulary is: infinite-trace LTL, finite prefixes, good/bad prefixes,
definitive prefixes, LTL₃.** You are not doing LTLf and you must not say you are — your traces are
*partial traces*, "finite prefixes of infinite behaviours", not *completed* finite traces (p.1).
That distinction is the paper's opening move and it is exactly your situation.

Here is the semantics section, in the form you should write it. Everything below is either a
definition from this paper or a straightforward instantiation of one; nothing is invented.

> **Definition (observed trace).** Let `AP` be the atomic propositions of the specification and
> `Σ = 2^AP`. Fix `t₀ ∈ ℝ` and `Δ > 0`, with tick boundaries `B_k = t₀ + kΔ`. Tick `k` is the
> half-open interval `(B_{k-1}, B_k]`. The monitor's fold maps the samples arriving in tick `k`
> to a single state `σ_k ∈ Σ` by the declared per-key policy. After `n` ticks the **observed
> trace** is `u = σ₁σ₂…σ_n ∈ Σ*`.
>
> **Definition (specification).** A property `φ` is a future-time LTL formula over `AP`,
> interpreted over `Σ^ω` by the standard satisfaction relation `⊧` (Amjad et al., Fig. 2).
> The property it denotes is `⟦φ⟧ = {t ∈ Σ^ω | t ⊧ φ}`.
>
> **Definition (verdict).** For an observed trace `u ∈ Σ*`:
>
>     V(u, φ) = VIOLATED       if ∀w ∈ Σ^ω. uw ⊭ φ        (u is a bad prefix of ⟦φ⟧)
>             = ACCEPTED       if ∀w ∈ Σ^ω. uw ⊧ φ        (u is a good prefix of ⟦φ⟧)
>             = INCONCLUSIVE   otherwise
>
> This is exactly Bauer, Leucker & Schallhart's `[u ⊧₃ φ]` under the renaming
> `F ↦ VIOLATED, T ↦ ACCEPTED, ? ↦ INCONCLUSIVE`. Equivalently, by Amjad, van Glabbeek &
> O'Connor's Theorem 6, `V(u,φ) = VIOLATED ⟺ u ∈ ⟦φ⟧₃ F` and `V(u,φ) = ACCEPTED ⟺ u ∈ ⟦φ⟧₃ T`,
> where `⟦·⟧₃` is their inductive definitive-set semantics.
>
> **Proposition (irrevocability).** If `V(u,φ) ≠ INCONCLUSIVE` then `V(uv,φ) = V(u,φ)` for every
> `v ∈ Σ^∞`. *Proof:* `⟦φ⟧₃ T` and `⟦φ⟧₃ F` are definitive sets, and any extension of a definitive
> prefix is a definitive prefix (Amjad et al., p.4). ∎
>
> **Proposition (the two verdicts never conflict).** `⟦φ⟧₃ T ∩ ⟦φ⟧₃ F = ∅`, and
> `⟦φ⟧₃ T = ☇(Σ^ω ∖ ⟦φ⟧₃ F)` (Amjad et al., Theorem 8). `INCONCLUSIVE` is therefore the **absence
> of a truth value**, not a third one: LTL₃ "can be better understood as a two-valued partial
> logic … where `?` indicates the absence of a truth value" (Amjad et al., p.3, after Blamey).
>
> **Proposition (observation-independence — the companion paper's claim, correctly scoped).**
> `V` is a function of `(u, φ)` alone. The observed trace `u` is determined by `Δ`, `t₀`, the
> declared fold policy, and the sample stream, and by nothing else. Hence at fixed `Δ`, `t₀` and
> fold policy, `V` is invariant under transport rate, publication rate, replay speed, process
> placement, and embodiment.

Note the last proposition is what your claim actually is, and it is *weaker and more honest* than
"the verdict is a function of the observed data alone" stated unqualified. `Δ` and the fold policy
are part of the definition of the data. Say so.

**Formula progression as a second characterisation.** If you ever want to justify a
non-automaton implementation, or to cross-check the automaton one, Theorem 11 is your lever:
`t ∈ ⟦φ⟧₃ T ⟺ ⟦φ'⟧₃ T = Σ^∞` where `φ --t--> φ'`. Practically it also tells you the standard
progression shortcut is **incomplete** unless your simplifier decides tautology — which is the
same completeness gap that shows up in §6.1.2 below in automaton form.

#### 6.1.1 `VIOLATED` — correct, with one caveat to check

Your `VIOLATED` = "entered a non-accepting sink". The right formal statement:

> **Lemma.** Let `A` be a deterministic complete Büchi automaton with `L(A) = ⟦φ⟧`, and let
> `q = δ*(q₀, u)`. Then `u` is a bad prefix of `⟦φ⟧` **iff** `L(A_q) = ∅`, i.e. iff no accepting
> cycle is reachable from `q`.

`_find_sink_states` (`automata.py:387`) tests something strictly stronger: *non-accepting, with
exactly one outgoing edge, a `bddtrue` self-loop*. That condition **implies** `L(A_q) = ∅` (only `q`
is reachable and `q` is not accepting), so your `VIOLATED` is **sound**. It is not obviously
**complete**: a reachable rejecting SCC with more than one state, or a trap reached by several
edges, satisfies `L(A_q) = ∅` but fails your syntactic test, and the monitor would sit in
`INCONCLUSIVE` forever instead of reporting `VIOLATED`. In practice Spot's `complete` postprocessing
usually emits a single `true`-self-loop trap, so this may never bite — **but that is an assumption
about Spot's output, not a theorem, and it is untested in this tree** (the `graph()` docstring at
`automata.py:191` already records that Spot is not installed here). Either prove it, or replace the
test with the semantic one: mark `q` a rejecting state iff no accepting state lies on a cycle
reachable from `q` — a plain SCC computation over `self.aut`, no new Spot API needed.

#### 6.1.2 `ACCEPTED` — this is the bug

`_compute_status` (`automata.py:404`) returns `ACCEPTED` iff `self.aut.state_is_accepting(q)`.
The docstring at `automata.py:57` says this "means the property holds over the finite prefix
observed so far."

**It does not.** Being in a Büchi-accepting state at step `k` is a statement about *one* state on
*one* run; a good prefix requires that **every** infinite continuation be accepted. The right
condition is the mirror of the sink test:

> **Lemma.** With `A`, `q` as above, `u` is a good prefix of `⟦φ⟧` **iff** `L(A_q) = Σ^ω`, i.e. iff
> **no rejecting cycle is reachable from `q`** (equivalently, every cycle reachable from `q` visits
> an accepting state).

`state_is_accepting(q)` is neither necessary nor sufficient for that. A counterexample you can
state without running Spot, using only your own `G(!collision_risk)`:

> Let `φ = □¬p`. `⟦φ⟧` is a safety property with **no good prefixes at all** (any prefix can be
> extended by a state satisfying `p`), so `[u ⊧₃ φ] = ?` for every finite `u`. But any Büchi
> automaton with `L(A) = ⟦φ⟧` accepts `(¬p)^ω`, so along that run it must visit accepting states
> infinitely often; hence for infinitely many `n`, reading `u = (¬p)^n` leaves the automaton in a
> `state_is_accepting` state and `LTLMonitor` reports `ACCEPTED`. The verdict is `ACCEPTED` where
> LTL₃ says `?`.

So today, `ACCEPTED` is an **automaton-internal fact**, not a semantic one. It is *not* LTL₃'s `T`,
and it is *not* reliably RV-LTL's presumptive `⊤_p` either — do not relabel it that without proof.

Three ways out, in increasing order of work:

- **(a) Compute the real thing.** Replace the accepting-state test with "no rejecting cycle
  reachable from `q`", precomputed once per automaton exactly like `_sink_states`. Then
  `ACCEPTED = good prefix` and the whole §6.1 semantics is literally what the code does. This is
  the option to take.
- **(b) Rename and re-scope.** Keep the current behaviour, call it something that is not a verdict
  (`state_accepting: bool` on the wire), and let `MonitorStatus` be `{INCONCLUSIVE, ACCEPTED,
  VIOLATED}` with `ACCEPTED` computed as in (a).
- **(c) Do nothing and document.** Not viable for a semantics paper.

A useful side effect of (a): you get a **static per-formula classification** for free, which you
should put in the paper as a table. For each spec formula, ask whether a good prefix and/or a bad
prefix can exist at all:

| formula shape | class | can ever be `ACCEPTED`? | can ever be `VIOLATED`? |
|---|---|---|---|
| `G(!collision_risk)` | safety | **no** | yes |
| `F(goal)` | guarantee / co-safety | yes | **no** |
| `F(a && F(b))` | guarantee | yes | **no** |
| `G(r -> F a)` | neither | **no** | **no** — *non-monitorable*, see p.13 |
| `GF(on)` | neither | **no** | **no** |

Row 4 is the paper's own worked example (p.13): for `□(r ⇒ ◇a)`, "for every finite prefix `u`, we
have `ur^ω ∈ ⟦φ⟧₃ F` and `ua^ω ∈ ⟦φ⟧₃ T`. As the F and T answers are non-overlapping (Theorem 8),
`u` must not be a definitive prefix. Therefore, all finite prefixes are not definitive." If a
formula of that shape is in your spec set, your monitor is *structurally incapable* of ever
deciding it, and a reviewer will find it. Generating this table is a concrete, cheap contribution.

**One consequence to notice.** If `F(goal)` can never be `VIOLATED`, then whatever produces a
timeout fault for it is not the LTL semantics — it is the `max_steps` / `TIMEOUT` machinery in the
phase state annotations (`automata.py:291`). That is fine and standard, but it means you are
monitoring **bounded** liveness `F_{≤n}(goal)`, which is a safety property, while the paper says
`F(goal)`. Say which one you mean, and say where the bound lives. *(This reading of the timeout
machinery is inferred from the annotation strings in `format_automaton`; verify against the phase
machine before writing it down.)*

---

### 6.2 Question 2 — does the literature back the observation/trace distinction?

**Partly — and the part that is missing is missing from this paper by construction.**

**What the paper gives you, and it is worth a lot:**

1. **`?` is the absence of a truth value, not a truth value.** Cited verbatim above (p.3, after
   Blamey's *Partial Logic*). This is direct, quotable backing for `docs/clocking.md` lines 195–197:
   `INCONCLUSIVE` is not making a claim about the trace. Cite it exactly there.
2. **The semantics is entirely observer-free.** `⟦φ⟧₃ T` and `⟦φ⟧₃ F` are sets of traces. No clock,
   no machine, no monitor appears anywhere in the definition. That is the formal shape of "the
   verdict is a function of the observed data alone" — a monitor is *correct* iff it computes
   membership in these two sets, and any two implementations that do so agree by construction.
   This is a better foundation for your companion paper's claim than an operational argument.
3. **A published argument against fourth verdicts that depend on where you stopped looking.**
   §6.3 (p.14) is the paper's critique of RV-LTL's presumptive values, and it is the best thing in
   the paper for you. A light alternating On/Off, monitored for `□◇On`: "the presumptive answer
   given in RV-LTL depends only on the very last observed status of the light … this formula would
   be considered presumptively false if our observation happens to end in a state where the light
   is off. Thus, the truth value obtained for this formula is **overly sensitive to the point at
   which our finite observation ceases**." That is precisely your hardware-agnosticism failure mode,
   stated by someone else, about someone else's logic. **Use it as the citation for why you refuse
   a fourth verdict.** It also earns the related-work sentence: RV-LTL is "more accurately an ad-hoc
   layering of LTL₃ on top of Pnueli's LTL for finite traces" (p.13).

**What the paper does not give you, and you must not pretend it does:**

The paper's `Σ = P(A)` means **a state is, by definition, a complete valuation of every AP**
(p.2). There is no unavailable AP, no stale source, no partial state. **The paper's `?` is about
the observation being too *short*, never about it having *holes*.** Nothing in this paper — or in
its successor — formalises unobservability of an AP as orthogonal to the property's truth value.
Searched for and **not found**: any treatment of missing data, sensor failure, partial valuations,
or epistemic modality. Write "not addressed by this paper", not "supported by".

**So what *is* your freeze rule, formally?** The honest reading, and the one you should write down:

> Freezing on an UNDECIDED tick means **no state is appended to the observed trace for that tick**.
> The observed trace `u` is therefore the sequence of *decided* ticks only. This keeps the automaton
> two-valued and keeps `u ∈ Σ*`, so the entire LTL₃ semantics of §6.1 applies to `u` unchanged.

That framing is clean, it is what the code does, and it costs you exactly one thing, which the
docs currently do not acknowledge:

> ⚠️ **`u` is a subsequence of the tick-indexed trace, not a prefix of it.** Every guarantee in
> §6.1 is a guarantee about `u`. Theorem 6 says `u ∈ ⟦φ⟧₃ F ⟺ ∀w. uw ⊭ φ` — a statement about
> extensions **of `u`**. It says nothing about the true behaviour `σ₁σ₂…σ_n` when some `σ_i` were
> dropped. `VIOLATED` on a subsequence is not, by itself, a soundness claim about the run.

This does **not** sink the design; it scopes it. Two clean repairs, pick one and state it:

- **(i) Restrict to stutter-tolerant / suffix-closed reasoning.** If the dropped ticks are treated
  as "the system was somewhere in `Σ`", then a `VIOLATED` verdict on `u` is sound for the real run
  only if the formula's violation is witnessed by `u` alone regardless of what was interleaved.
  For a pure safety formula whose bad prefix is witnessed by a single state (`G(!p)` violated by
  one `p`-state), this holds trivially, because dropping states can only *lose* violations, never
  create them. **State it as: freezing is sound-but-incomplete for safety formulas — it can miss a
  violation, it cannot fabricate one.** That is exactly what `docs/clocking.md` line 186 already
  claims informally ("`G(!collision_risk)` cannot be violated during a data outage"), and it is
  correct; it just needs to be stated as a *soundness/completeness trade*, with the coverage count
  as the completeness report. Your episode-fold coverage count (`docs/clocking.md` §"The episode
  fold") is then not a nicety, it is the quantity that bounds the completeness loss. Lead with that.
- **(ii) Do not drop the tick — over-approximate it.** Instead of freezing, step on *every*
  consistent valuation of the unknown APs and keep the set of reachable automaton states (a subset
  construction over the det automaton). Then `VIOLATED` iff *all* states in the set are rejecting,
  `ACCEPTED` iff all are good. This keeps `u` a genuine prefix, so §6.1 applies verbatim and no
  fourth verdict is needed either. It is more code and it is what a determined reviewer will
  suggest — mention it as considered-and-deferred with the cost stated.

Either way, the design bet survives. The framing must change from "UNKNOWN is a third AP value we
refuse to promote to a verdict" (true but not a theorem) to "the observed trace omits undecided
ticks; the verdict is LTL₃ over that trace; coverage reports the omission" (a theorem-shaped claim).

**Backing you may find useful and this paper only points at:** Aceto et al.'s monitor framework
(p.12) defines monitors as extension-closed `acc`/`rej` predicates on `Σ^∞` — "highly reminiscent
of the two sets we use for our LTL₃ semantics" (2608.23096 p.30). That is the closest thing in the
cited literature to a monitor-as-observer formalism. The paper explicitly says finfinite semantics
"does not align with our LTL₃ semantics" (p.12), so do not merge the two casually.

---

### 6.3 Question 3 — what does it cost to read `X` as "one tick later"?

**This paper says nothing about it.** No sampling, no discretisation, no continuous time, no `Δ`.
Verified across the retrieved text of both 2411.14581 and 2608.23096: **not discussed.** Anything
below is therefore *your* burden of proof, not a result you can cite from here. But yes — a
formal-methods reviewer will flag it, and here is what they will say.

**Flag 1 — `Σ` is an abstract alphabet, and you owe the sampling map.** The semantics is over
*sequences of states*. Nothing licenses the map from a continuous-time robot to such a sequence.
You must define it explicitly (the `obs`/fold definition in §6.1 above does this) and then be
clear that your verdict is a verdict **about the sampled trace**, not about the continuous
behaviour. `docs/clocking.md` already has the right instinct — "this is the only place the trace's
time base is defined" — it just needs to be a definition in the paper rather than a note in a
design doc.

**Flag 2 — the fold policy decides whether an AP over-approximates or under-approximates the
interval, and it differs per key.** This is the sharpest concrete thing in your favour and you
should lead with it:

- `last` = a **point sample** at the interval's end. Unsound in both directions: a transient `p`
  inside `(B_{k-1}, B_k]` is invisible, so `G(!p)` can pass over a real violation.
- `min` on `min_range` = an **∃ over the interval** for that key. Sound for *detecting* the bad
  event (it cannot miss one), unsound for *not* detecting it (one spurious near-pixel trips it).
- `max`, `any`, `all`, `mean` sit at various points on that axis.

So the honest statement is: **the sampled trace is neither an under- nor an over-approximation of
the continuous behaviour uniformly; it is per-key, determined by the declared fold.** `clocking.md`
§"Why `min` on `min_range`, and what it costs" already understands this operationally — promote it
to a semantic statement: *for keys folded by `min`/`any`, `σ_k ⊨ p` iff `p` held at some instant in
tick `k`; for keys folded by `last`, `σ_k ⊨ p` iff `p` held at the sampling instant.* Then `G(!p)`
means two different things depending on which key `p` reads, and you must say which.

**Flag 3 — formulas containing `X` are not `Δ`-invariant, so state the invariance claim at fixed
`Δ`.** Because exactly one automaton step happens per tick, `X φ` means "φ holds of the fold of the
next `Δ`-window". Halving `tick_hz` changes the denotation of every formula containing `X`, and of
every step budget (`max_steps`, `progress_violation_limit`) measured in ticks. Your P9 acceptance
test ("two replays of one episode must produce the same verdict") is true and worth proving, but the
theorem is: *invariant under transport rate, publication rate and replay speed, **at fixed `Δ`, `t₀`
and fold policy***. Anyone who reads "hardware-agnostic" as "`Δ`-agnostic" will be disappointed, so
pre-empt it. A stronger claim is available for the `X`-free fragment if you want it: for formulas
using only `G`, `F`, `U`, `R`, `W`, `M` over `min`/`any`-folded keys, refining `Δ` refines the trace
and safety verdicts are monotone. That would need proving; **do not assert it unproved.**

**Flag 4 — the freeze rule and the `Δ` reading of `X` are in direct conflict, and only one can
survive.** This is the finding to act on:

> `docs/clocking.md` line 70 says "Exactly one automaton step per tick. `X` … therefore means
> 'Δ seconds later'." `docs/clocking.md` line 183 says an UNDECIDED tick does **not** step the
> automaton. Both cannot hold. Under the freeze rule, `X` means "**the next decided tick**", which
> may be `1Δ`, `5Δ`, or arbitrarily far later.

Choose and write it down:
- **(A) `X` = next *decided* tick.** Keeps the freeze. Then delete or heavily qualify the
  "Δ seconds later" sentence, and note that during an outage the temporal operators' real-time
  meaning degrades gracefully but is no longer pinned. Combined with the coverage count this is
  perfectly defensible.
- **(B) `X` = `Δ`.** Then every tick must step, and an undecided tick must be handled by
  over-approximation (§6.2 option (ii)) rather than by freezing.

(A) is less work and matches the code. (B) is more faithful to the doc's stated claim. Either is
publishable; the current pair of sentences is not.

---

### 6.4 Concrete to-do list

1. Fix `_compute_status`'s `ACCEPTED` (§6.1.2 option (a)) — or at minimum stop claiming in the
   docstring that it means the property holds over the prefix.
2. Replace the syntactic sink test with the semantic one, or prove the syntactic one complete for
   Spot's output (§6.1.1).
3. Write the semantics section from the block quote in §6.1; cite `bauer2011runtime` for LTL₃ and
   this paper for the model-theoretic account and Theorem 8.
4. Add the per-formula monitorability table (§6.1.2). Any `G(r -> F a)`-shaped formula in your spec
   set is dead weight — report that as a finding, not a bug.
5. Reframe the freeze rule as "undecided ticks are omitted from the observed trace; coverage counts
   the omissions; freezing is sound-but-incomplete for safety" (§6.2).
6. Resolve the `X`/freeze contradiction in `docs/clocking.md` (§6.3 flag 4).
7. Scope the invariance proposition to fixed `Δ`, `t₀` and fold policy (§6.3 flag 3).

---

## 7. The successor paper — arXiv:2608.23096, "The Infinite, in Finite Time"

Same three authors (van Glabbeek now also credited to UNSW Sydney; supported by Royal Society
Wolfson Fellowship RSWF\R1\221008), arXiv stamp `arXiv:2608.23096v1 [cs.LO] 24 Aug 2026`. Its own
reference [12] identifies 2411.14581 as "an extended abstract of (part of) this paper", and it
states: "The present paper contains significant additional work expanding on monitorability for
linear-time properties, providing topological characterisations for various monitorability classes
and demonstrating a hierarchy between them" (p.3–4). ~2900 lines of Isabelle (vs 1700).

**It is relevant to you, and probably more so than the EXPRESS/SOS paper**, because it turns
§6.1–6.2 of the conference version from conjectures into theorems:

- **Guarantee kernel** `P⁻ ≜ ↑(☇P ∩ Σ*) ∩ Σ^ω` (Def. 6.1) — "the set of all infinite traces that
  are extensions of finite definitive prefixes of `P`"; "the largest subset of `P` that is a
  guarantee property"; `P` is a guarantee property iff `P⁻ = P`. It is a kernel (interior) operator:
  monotone, idempotent, deflationary. Theorem 6.1: distributes over binary intersection.
  Counterexample 6.1: does **not** distribute over union (`◇a` and `◇¬a` each have empty kernel,
  their union is trivially true).
- **Re-proof of Alpern & Schneider**: every property is the intersection of a safety and a liveness
  property, obtained here by first showing every property is the union of a guarantee and a
  morbidity property, then complementing (p.23).
- **A monitorability hierarchy** (Figure 6), with these classes defined in the paper's notation:
  *good monitorable* (a good finite prefix exists, or `P = ∅`), *bad monitorable* (a bad finite
  prefix exists, or `P = Σ^ω`), *weak monitorable* (the guarantee kernel of `P` or of its complement
  is non-empty — i.e. **some** finite prefix is definitive one way or the other), Bauer et al.'s
  BLS-monitorability, Pnueli & Zaks monitorability, and *strong monitorable*. Theorem: **strong
  monitorable ⟺ both a safety and a guarantee property**; strong monitorable properties are closed
  under complement, intersection and union. Theorem 6.4: **all safety properties are bad
  monitorable**, strictly.
  *(The exact symbolic forms of these definitions use overline/underline closure and kernel
  operators that the PDF extraction mangles — check the symbols against the paper before
  transcribing. The prose characterisations above are verbatim-supported.)*
- **Unmonitorable traces** = the *frontier* `closure(P) ∖ P⁻`: "precisely those infinite traces for
  which definitive answers cannot be given after observing only a finite prefix." Weak
  monitorability is closed under negation but **not** under union or intersection — worked
  counterexample: `P = ◇□b ∨ ◇a` and `Q = ◇□b ∨ ◇(¬a)` are each weak monitorable, `P ∧ Q` is not.
  **That is a live hazard for `MultiMonitor`:** running two monitorable formulas in parallel and
  reading their conjunction as a verdict is not automatically monitorable.
- **Figure 7** draws the connection between Kupferman & Vardi's / Bauer's good, bad and ugly
  prefixes and the kernel/closure operators — this is the figure to redraw for your semantics
  section if you want one picture that explains the whole verdict lattice.
- A useful scoping remark for §6.2 above: under *finfinite* semantics (Aceto et al.), "the only
  strong monitorable properties … are `∅` and `Σ^∞`, but in infinite semantics there are non-trivial
  strong monitorable properties" (p.30). Concretely: **the choice of infinite-trace semantics is
  what makes your `ACCEPTED`/`VIOLATED` verdicts non-vacuous.** That is a one-sentence
  justification for why you are not using LTLf, and it is citable.
- Also new: an explicit softening of the tautology-simplifier point — "any practical implementation
  must therefore balance completeness … against efficiency", either "complete but potentially
  expensive procedures" or "tractable but incomplete syntactic simplification" (p.19).

**Recommendation:** cite the EXPRESS/SOS paper for the LTL₃ semantics and Theorems 2/6/7/8; cite
2608.23096 for anything about monitorability classes, safety/liveness, or the guarantee kernel.
Note in your bibliography that they overlap, so a reviewer does not think you are padding.

---

## 8. Check yourself

**Q1. Bauer et al. claim LTL₃ cannot be given an inductive semantics, and give `○a ∨ ○¬a` as the
reason. This paper gives an inductive semantics. Where exactly does the argument fail?**

The argument shows there is no **truth-function** on `B₃ = {T,F,?}` computing `∨`: `[ε ⊧₃ ○a] =
[ε ⊧₃ ○¬a] = ?` and `[ε ⊧₃ ○a ∨ ○¬a] = T`, while `[ε ⊧₃ ○b] = [ε ⊧₃ ○¬c] = ?` and
`[ε ⊧₃ ○b ∨ ○¬c] = ?`. Same inputs, different outputs. But that only rules out semantics whose
*compositional carrier* is the truth value. This paper's carrier is a **set of traces** — an
answer-indexed family `B → D` — and disjunction is the **definitive union** `∪☇ = ☇(·∪·)`, whose
`☇` is exactly what recovers `ε` for the tautology and does not for the non-tautology (p.3, p.7).
"This claim applies only to the multi-valued semantics defined above" (p.3).

**Q2. Definitive sets contain both finite and infinite traces. Theorem 2 says they are isomorphic
to sets of infinite traces. Is the finite information redundant, then?**

Yes — *determined*, not redundant-in-use. `Pr(X) = X ∩ Σ^ω` and `Df(P) = ☇P` are mutually inverse
(Theorem 2), so a definitive set is uniquely recoverable from its infinite traces. The finite
definitive prefixes carry no information the infinite traces do not already determine. What they
*do* is make that information **directly addressable**: `⟦φ⟧₃ T` and `⟦φ⟧₃ F` are the good and bad
prefixes, sitting there as set membership, so a monitor's job is literally "test membership".
That, plus the fact that `☇` is a closure operator, is what makes the semantics compositional.

**Q3. Are good, bad and ugly prefixes a partition of the finite prefixes? Give the counterexample.**

No. `ppp…` (a finite run of `p`-states) for `p U q`: it is not a good prefix (extend with a state
satisfying neither and it fails), not a bad prefix (extend with `q` and it succeeds), and not ugly
either — ugly means it cannot be *finitely extended* into a good or a bad prefix, and this one can
be extended both ways (p.12). Ugly prefixes are the ones that mark non-monitorability; the
in-between prefixes that are merely undecided-so-far are the normal case.

**Q4. Your monitor reports `ACCEPTED` when the Büchi automaton for `G(!collision_risk)` sits in an
accepting state after 200 clean ticks. What does LTL₃ say, and why do they differ?**

LTL₃ says `?`. `G(!p)` is a safety property: it has **no** good prefixes, because every finite
prefix can be extended by a `p`-state and refuted. So `∀u ∈ Σ*. [u ⊧₃ G(!p)] ≠ T`. The mismatch is
that `state_is_accepting(q)` is a fact about one state on one run, while a good prefix requires
`L(A_q) = Σ^ω` — no rejecting cycle reachable from `q`. Any automaton for `G(!p)` accepts `(¬p)^ω`,
so it must sit in accepting states infinitely often along that run, and the code reports `ACCEPTED`
there. The fix is to precompute "no reachable rejecting cycle" the way `_sink_states` precomputes
"no reachable accepting state".

**Q5. Your design records an undecided tick and does not step the automaton. Name the one formal
guarantee this breaks, and the one it preserves.**

**Breaks:** the observed trace stops being a **prefix** of the tick-indexed trace and becomes a
**subsequence**. Every LTL₃ guarantee (Theorem 6: `u ∈ ⟦φ⟧₃ F ⟺ ∀w ∈ Σ^ω. uw ⊭ φ`) is a statement
about extensions *of the observed trace*, so a `VIOLATED` verdict is not, by itself, a soundness
claim about the real run.
**Preserves:** two-valuedness and irrevocability. `⟦φ⟧₃ T` and `⟦φ⟧₃ F` are definitive, so any
extension of a definitive prefix stays definitive (p.4) — a verdict once given never flips, and
`INCONCLUSIVE` remains the *absence* of a truth value rather than a third one, exactly as LTL₃'s
partial-logic reading requires (p.3). For safety formulas there is also a usable one-sided claim:
dropping states can lose a violation but cannot fabricate one, so freezing is **sound but
incomplete**, and the coverage count is the completeness report.

---

## 9. Sources

- [arXiv:2411.14581 — Semantics for Linear-time Temporal Logic with Finite Observations](https://arxiv.org/abs/2411.14581)
- [arXiv:2608.23096 — The Infinite, in Finite Time](https://arxiv.org/abs/2608.23096)
- [AFP: Definitive Set Semantics for LTL3](https://isa-afp.org/entries/LTL3_Semantics.html)
- [Edinburgh Research Explorer record](https://www.research.ed.ac.uk/en/publications/semantics-for-linear-time-temporal-logic-with-finite-observations/)
- Formal proof repository named in 2608.23096 ref [10]: `https://github.com/rayhanayasmin/the_infinite_in_finite_time` (**link read off the PDF; not visited from this environment**)
