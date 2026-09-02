# RTAMT — Runtime Robustness Monitors with Application to CPS and Robotics

**Yamaguchi, Hoxha, Ničković.** arXiv:2501.18608v1 [cs.LO], 22 Jan 2025.
Version of Record: *Int. J. Softw. Tools Technol. Transf.* (STTT), DOI
[10.1007/s10009-023-00720-3](https://doi.org/10.1007/s10009-023-00720-3). See `bibtex.md`.

Read for: **the "why LTL and not STL" paragraph**, and one row of Paper B's tool table.

---

## 1. In one paragraph

RTAMT (Real-Time Analog Monitoring Tool) is a Python library, with an optional C++
back-end, that turns a written **Signal Temporal Logic** specification into a monitor and
reports, at each evaluation point, a **real-valued robustness degree** saying how far the
observed signal is from satisfying or violating the spec — not just satisfied/violated. Its
selling point is coverage of the design space rather than a new algorithm: one API spans
{offline, online} × {discrete-time, dense-time} × {STL, past-STL, interface-aware STL}, and
the library is deliberately layered (ANTLR4 lexer/parser/AST in Python; an interchangeable
semantics layer in Python or C++) so a practitioner can bolt on their own operator or their
own robustness notion. The paper's contribution over the 2020 ATVA conference version is
integration and evaluation: **RTAMT4ROS** for the Robot Operating System, a Simulink block,
a fault-localisation case study on Toyota's Human Support Robot in Gazebo, and a
falsification/sensitivity study on an Aircraft Elevator Control System. It is a monitoring
*engine* paper: there is no specification-authoring story, no natural language, no LLM, and
no learning anywhere in it.

---

## 2. Key concepts

**Signal Temporal Logic (STL).** LTL extended with (a) numerical predicates `f(Y) > c` over
real-valued signals and (b) real-time intervals bounding the temporal operators. Grammar
(Def. 1): `φ ::= f(Y) > c | ¬φ | φ₁ ∨ φ₂ | φ₁ U_I φ₂ | φ₁ S_I φ₂`, with `I = [a,b]` or
`[a,∞)`, `a ≤ b` rational. Derived: future `F_I`, `G_I`, `X`; past `O_I` (once), `H_I`
(historically), `Y` (previous), `↑` (rise), `↓` (fall). `X`, `Y`, `↑`, `↓` are meaningful
**only** under the discrete-time interpretation.

**A signal**, in this paper, is a finite sequence of (timestamp, valuation) pairs, `t₀ = 0`,
strictly increasing timestamps, `tₙ = d`. That is the same shape as an observation stream —
but with real-valued, not Boolean, valuations.

**Robustness semantics (space).** `ρ(φ, w, t) ∈ ℝ` (Def. 2), the *spatial* robustness:

```
ρ(f(Y) > c, w, t) = f(w_Y(t)) − c
ρ(¬φ)             = −ρ(φ)
ρ(φ₁ ∨ φ₂)        = max(ρ(φ₁), ρ(φ₂))
ρ(φ₁ U_I φ₂, w, t)= sup_{t'∈t⊕I∩T} min( ρ(φ₂,w,t'), inf_{t''∈[t,t')} ρ(φ₁,w,t'') )
```

Intuition: **how much the signal would have to be moved, in signal units, to flip the
verdict** — an approximation of the distance from the observed behaviour to the boundary of
the satisfying set. Sign carries the qualitative verdict; magnitude carries the margin.
Worked example (Fig. 1): a PID output against `G(f(t) ≤ 1.1)` scores **+0.048** when
satisfied (closest approach to the threshold) and **−0.198** when violated (largest
excursion above it).

**Robustness semantics (time) — note carefully.** The paper *defines and implements only
spatial robustness*. **Time robustness** — how far a signal would have to be shifted *in
time* to flip the verdict — is credited in the related-work section to Donzé and Maler, and
a combined space/time notion to a further reference; RTAMT is described as implementing
"STL with infinity-norm quantitative semantics". **Do not cite RTAMT for time robustness.**
This matters for us: see §6, Q1.

**Discrete-time vs dense-time interpretation.**

| | discrete-time | dense-time |
|---|---|---|
| time domain | integers; sample `i` ↔ time `i·Δ` | reals in `[0,d]`, `d ∈ ℚ_{>0}` |
| sampling | assumed **periodic with period Δ** | samples at arbitrary instants, finite variability, no bound on changes per unit time |
| between samples | undefined; the logic only evaluates at sampled instants | **piecewise-constant interpolation** — the last value holds |
| execution model | **time-triggered**: sense and emit at a periodic rate | **event-driven**: samples arrive when they arrive |
| resources | admits an *upper bound* on computation resources | unbounded in general |
| justification | Henzinger–Manna–Pnueli, *What good are digital clocks?* — weakening/strengthening a real-time spec lets discrete-time evaluation preserve important properties of the dense-time reading | Donzé–Ferrère–Maler efficient robust monitoring, adapted to piecewise-constant signals |

**Online vs offline.** Offline (`evaluate`) expects the whole trace at once. Online
(`update`) is fed prefixes and returns the robustness of the formula at the current index
relative to the prefix observed so far; it must manage memory to hold incomplete signal
segments until the next update. **Only past-STL may be given to an online monitor**
directly.

**Bounded-future STL (bfSTL) and past-STL (pSTL).** bfSTL forbids unbounded intervals;
pSTL admits only past operators. Past operators are "more suitable for online monitoring"
because the robustness at the current step depends only on current and past values.

**Pastification** — the bridge between the two. A bfSTL formula has a syntactically
computable **temporal depth** `H(φ)` (Def. 3: `H(p)=0`, `H(Xφ)=H(φ)+1`,
`H(φ₁ U_[a,b] φ₂) = b + max{H(φ₁),H(φ₂)}`, …). The pastification operator `Π` (Def. 4)
rewrites `φ` into an equi-satisfiable pSTL formula evaluated `H(φ)` steps later, when every
input it needs has arrived: `ρ(φ,w,t) = ρ(Π(φ), w, h(φ))`. A new auxiliary operator
`P_[a,b]` ("precedes") implements bounded-until read backwards from the end of the horizon.
Worked example from the paper: `(req ≥ 3) → F_[0,5](gnt ≥ 3)` pastifies to
`O_[5,5](req ≥ 3) → O_[0,5](gnt ≥ 3)`. **This is the trick that makes a future-time spec
monitorable online: not prediction, but a fixed-latency delay of the verdict.**

**Interface-aware STL (IA-STL).** A spec is a tuple `(X_U, X_V, φ)` partitioning variables
into inputs `X_U` and outputs `X_V`. Built on *relative* robustness `ρ^V_U`, it yields two
derived measures:

- **Output robustness (μ)** — the `X_V`-robustness relative to `X\X_V`: how much the
  *outputs* could be perturbed with the inputs held fixed. `±∞` means the spec is
  *vacuously* (dis)satisfied by this input.
- **Input vacuity (ν)** — the `X_U`-robustness relative to `∅`: how hard this input actually
  exercises the spec. `ν = 0` means non-vacuous — the input genuinely drives the property.

The paper's Fig. 3 walks four request–grant traces against `G(req≥3 → F_[0,5] gnt≥3)`
showing cases where plain robustness and output robustness disagree (e.g. `−1` vs `−2`,
because plain robustness finds the cheapest fix by *shrinking the input* until the property
is vacuously satisfied — a fix an engineer cannot use). **IA-STL exists because a single
robustness scalar is a bad fault localiser.** That is directly relevant to us (§6, Q1).

---

## 3. Method / architecture

```
                spec text (STL / IA-STL)
                        │
  ┌─────────────────── SYNTAX LAYER (Python, runs once at parse) ──────────────────┐
  │  ANTLR4 lexer + parser (grammar file)  →  StlAst  ←  StlAstVisitor             │
  │  syntactic tree manipulation, incl. StlPastifier :: bfSTL φ ⟼ pSTL ψ           │
  └────────────────────────────────┬──────────────────────────────────────────────┘
                                   │  AST
  ┌──────────────── SEMANTICS LAYER (called on EVERY update) ─────────────────────┐
  │  TimeInterpreter ─┬─ DiscreteTimeInterpreter   (time-triggered, period Δ)      │
  │                   └─ DenseTimeInterpreter      (event-driven, pw-constant)     │
  │  mode ────────────┬─ AbstractOfflineInterpreter → evaluate(...)                │
  │                   └─ AbstractOnlineInterpreter  → update(...)                  │
  │  back-end: Python (prototyping)  |  C++ via Boost.Python (speed)               │
  └────────────────────────────────┬──────────────────────────────────────────────┘
                                   │
                          robustness degree (float)
                                   │
        ┌──────────────────────────┼──────────────────────────┐
     CSV/Excel/SQL            RTAMT4ROS                MATLAB/Simulink block
                          (ROS node wrapper)       (parse+pastify at init;
                                                    read input port → update()
                                                    → robustness output port)
```

**Why Python at the top.** The authors state five reasons: common data formats (CSV/Excel/
SQL), easy ROS integration, Simulink connectivity, PyPI distribution, and user base. Both
Python 2.x and 3.x are supported (ROS 1 legacy).

**Why the layer split.** The syntax layer runs once, so flexibility beats speed and it stays
in Python. The semantics layer runs per update, so it is duplicated in C++ and bridged with
Boost.Python.

**Algorithmic lineage.** Discrete-time monitors implement the Jakšić et al. *STL-to-FPGA*
algorithm adapted to robustness semantics. Dense-time monitors implement Donzé–Ferrère–Maler
adapted to piecewise-constant signals; the key ingredient is an **optimal streaming
sliding-window min/max** algorithm, which is what makes `G_I`, `F_I`, `H_I`, `O_I` cheap and
is then generalised to `U_I`/`S_I`. Online dense-time is the incremental application of the
offline procedure (the AMT approach) to the partial input received so far.

**The API is three calls.** `declare_var(name, type)` · `spec.spec = "<formula>"` +
`spec.parse()` · `evaluate(...)` / `update(...)`, each taking `[name, [[t, v], …]]` lists
and returning a float. Verbatim from the paper:

```python
import rtamt
spec = rtamt.StlDenseTimeOfflineSpecification()
spec.declare_var('req', 'float')
spec.declare_var('gnt', 'float')
spec.spec = 'G((req>=3)->(F[0,5](gnt>=3)))'
spec.parse()
req = [[0.0,0.0],[2.0,6.0],[4.0,0.0],[10.0,0.0]]
gnt = [[0.0,0.0],[6.0,6.0],[8.0,0.0],[10.0,0.0]]
rob = spec.evaluate(['req', req], ['gnt', gnt])
```

Online differs in two ways only: the class is `StlDenseTimeOnlineSpecification`, and the
spec must be pSTL — either written that way (`H[0,10]((O[5,5](req>=3))->(O[0,5](gnt>=3)))`)
or produced by inserting `spec.pastify()` after `spec.parse()`. Extending the language means
touching the lexer (reserved word), the parser (rule), and adding a visitor case with the
evaluation algorithm; abstract base classes carry the boilerplate.

**Extension mechanism.** The paper presents the library as a *toolkit for building your own
temporal logic*, not only as a fixed STL monitor — IA-STL is the demonstration that the
extension path works.

---

## 4. Results / evaluation

All experiments: Intel i9-10900K, 3.7 GHz, 10 cores, 128 GB RAM, Ubuntu 18.04.

**(a) Computational efficiency.**
- Offline, Python back-end: scaling measured against input trace size and formula length,
  comparing average calculation time of discrete-time vs dense-time monitors (Fig. 9). *The
  concrete numbers in that figure were not extracted — not verified.*
- Online, C++ vs Python back-end (Fig. 10), on `G[0,k](a + b ≥ −2)` with `k` swept from
  **100 to 1,000,000**: the C++ back-end is **roughly 10× faster**, with the gap widening at
  large temporal-modality bounds.
- Headline number: **the slowest configuration (dense-time, Python back-end) costs about
  0.5 ms per sample**, which the authors call good enough for real time.

**(b) HSR in ROS/Gazebo — fault localisation, not just safety.** RTAMT4ROS applied to
Toyota's Human Support Robot (8 DoF: 3 mobile base + 4 arm + 1 torso lift; LiDARs, stereo
and monocular cameras) in Gazebo, over a perception → planner → controller architecture. The
claim demonstrated is that monitors placed at component interfaces, in an
**assume–guarantee** style (following the authors' earlier MEMOCODE 2020 fault-localisation
work), localise a fault to a *component* rather than only flagging a system-level violation.

**(c) AECS in Simulink — robustness as an optimisation signal.** An Aircraft Elevator
Control System, with two uses of the robustness scalar that a Boolean verdict cannot serve:
a **sensitivity heat-map** of robustness over input parameters (Fig. 16a), and
**falsification testing** (Fig. 16b), where a global optimiser drives robustness downward
until the requirement is violated.

**What is *not* measured.** No end-to-end ROS overhead figure per tick, no accuracy/false-
alarm rates, no comparison against another monitoring tool, no spec-authoring effort study,
no multi-embodiment portability experiment.

---

## 5. Limitations

**Stated by the authors (future work section):**
- Dense time is assumed to be a *perfect continuous clock* — a "realistic assumption in many
  applications", but an assumption. Handling genuinely event-driven arrival is listed as an
  extension (event-driven online bfSTL monitoring where measurements may arrive at any point
  on the dense-time axis).
- Monitors are not yet decentralised/distributed; the infrastructure can already publish
  robustness continuously, and distribution is future work.
- Only STL-family semantics are shipped; other languages and other semantic extensions
  (e.g. weighted edit distance) are planned.
- Evaluation is simulation-only for robotics; in-field physical testing is future work.
- Integration with search-based testing (S-TaLiRo/Breach-style, VerifAI) is proposed, not
  done.

**Not stated by the authors, but load-bearing for us:**
- **No account of missing, stale, or out-of-order samples.** Discrete-time *assumes*
  periodic sampling with period Δ and indexes samples by `i·Δ`; a dropped sample therefore
  silently shifts every subsequent index. Dense-time holds the last value indefinitely
  (piecewise-constant), so a dead publisher yields a confident robustness number computed
  from stale data. Neither mode has a "no data" value.
- **No three-valued or unknown verdict.** `ρ` is total: it always returns a float. The only
  three-valued semantics discussed anywhere in the paper is in *related work*, describing
  R2U2/MLTL (Reinbacher et al.), not RTAMT.
- **Robustness is min/max-dominated**, so one worst sample determines the value and masks
  everything else. The authors implicitly concede this by needing IA-STL and
  assume–guarantee decomposition to do fault localisation.
- **Units are not normalised.** `min`/`max` in Def. 2 compare predicate margins directly, so
  a formula mixing metres, radians and joint counts produces a number whose magnitude is
  meaningless without a normalisation choice the paper does not discuss.
- **Time robustness is not implemented** (see §2).
- **Specifications are hand-written.** Nothing in the paper produces a spec from anything.

---

## 6. For `skill_monitor`

### Q1 — Why LTL and not STL? *(the important one)*

**What STL robustness would actually buy a progress-and-failure-mode monitor.** Three
concrete things, and they are real:

1. **A continuously degrading margin on thresholded APs.** `collision_risk` is
   `min_range < 0.25`. Booleanised, it is false, false, false, *true*. As an STL predicate,
   `ρ = 0.25 − min_range` shrinks smoothly as the robot closes on an obstacle. Thresholding
   *that* below the AP boundary is genuine early warning: you fire at 0.30 m instead of
   0.25 m without editing the spec.
2. **A graded severity number, per formula, for free** — the thing our ladder computes from
   three separate inputs.
3. **Robustness as an optimisation signal.** The AECS experiment (Fig. 16) is the honest
   demonstration: sensitivity heat-maps and falsification by a global optimiser. If we ever
   wanted to *search* for failure-inducing episodes rather than detect them, robustness is
   the cost function and Boolean LTL is not.

**What it would cost, and why the ladder does not come out of it for free.** The reviewer's
question is "wouldn't STL robustness have given you the intervention ladder?" The answer is
no, and the reason is specific rather than rhetorical. Our ladder is
`grade_action(fault_category, imminence, confidence)`. **`imminence` is steps-to-violation —
a *temporal* quantity. RTAMT implements *spatial* robustness only** (§2); time robustness is
cited to Donzé–Maler in related work and is not in the tool. So the single input the ladder
most depends on is exactly the one STL-as-implemented does not provide. And `confidence` is
a property of the *sensor*, not of the margin — a stale LiDAR frame reading 0.9 m has a
large positive robustness and near-zero confidence, and collapsing those two into one scalar
is precisely the error our three-valued AP design exists to avoid.

**Draft paragraph — "why LTL and not STL":**

> Our monitor interprets discrete-time LTL over Boolean atomic propositions rather than
> Signal Temporal Logic over real-valued signals, and the choice is deliberate. STL's
> quantitative robustness semantics [Fainekos & Pappas; Donzé & Maler], as implemented in
> tools such as RTAMT [Yamaguchi et al., 2024], returns a real-valued margin per formula and
> is the right instrument when every predicate is a threshold on a commensurable continuous
> signal — it yields a graded severity signal directly, and it is the cost function that
> makes falsification and sensitivity analysis possible. Our alphabet is not of that kind.
> A meaningful fraction of our atomic propositions are irreducibly Boolean or categorical —
> a navigation action server reporting SUCCEEDED, a vision–language head answering whether
> the goal object is visible, a grasp reported closed — and spatial robustness over such a
> signal degenerates to a sign with no magnitude. A formula whose robustness is the minimum
> over a mixture of true metric margins and ±1 placeholders is less interpretable than the
> Boolean verdict it replaces, and the min/max structure of the semantics means the reported
> number is that of a single worst sample, which masks the remaining structure rather than
> localising it — the reason RTAMT itself introduces interface-aware STL and
> assume–guarantee decomposition to attribute a violation to a component. Booleanising at
> the atomic-proposition boundary instead keeps the continuous reasoning where the sensor
> model lives and gives the logic a finite, named alphabet: this is what makes the
> specification an automaton-checkable object with a three-valued LTL3 verdict
> [Bauer et al., 2011], what lets the same specification run unchanged across MuJoCo, Isaac
> Lab and the physical G1 — the threshold is a property of the adapter, not of the formula —
> and what gives a language model a closed vocabulary to be evaluated against when
> synthesising a specification. We do not discard graded information; we move it out of the
> logic. Timing is carried per phase as a `max_steps` budget in ticks, severity is graded by
> an explicit ladder over (fault category, steps-to-violation, sensor confidence), and
> sensor health is carried as a per-AP UNKNOWN. That decomposition buys something a single
> robustness scalar cannot express: steps-to-violation is a *temporal* margin, and the
> spatial robustness implemented by RTAMT does not measure it, while sensor confidence is a
> property of the observation rather than of the signal's distance from a threshold —
> collapsing the two into one real number would make a confidently-wrong stale reading
> indistinguishable from a genuinely safe one.

**Concession to make explicitly** (a reviewer who knows STL will spot it otherwise): for the
subset of our APs that *are* thresholded scalars, STL robustness is strictly more
informative than the Boolean AP, and our margin-based early warning currently has to be
rebuilt per-AP outside the logic. The defensible claim is about *where* the gradation lives,
not about whether gradation is useful. Do not claim LTL is more expressive; claim the
alphabet is not metric and the graded channels we need are not spatial.

### Q2 — RTAMT as a tool-table row

| | spec synthesis from NL | schema grounding | embodiment portability | deterministic replay |
|---|---|---|---|---|
| `rtamt2025` | **No** | **Partial** | **Partial** | **Not claimed** |

Cell by cell, with evidence and with what is unsupported:

- **Spec synthesis from natural language — No.** Substantiated by absence and by design:
  specs are strings parsed by an ANTLR4 lexer/parser; nothing in the paper mentions natural
  language, LLMs, or any authoring assistance. Safe to write "n/a" or "—" in the table. This
  is our differentiator against RTAMT and it is uncontested.
- **Schema grounding — Partial, and mind the gap.** RTAMT has a *typed variable declaration*
  (`declare_var(name, 'float')`) and IA-STL adds an input/output partition of the variable
  set — both are a form of interface discipline, and IA-STL's input-vacuity check is
  genuinely a "does this spec engage the interface at all" test, which is adjacent to
  grounding. But **grounding in our sense — checking a proposed formula's symbols against a
  discovered system signature — is not what these do**, and the paper does not describe
  automatic binding of spec variables to ROS topics/message fields. *The exact mechanism by
  which RTAMT4ROS binds a declared variable to a topic field was not extracted from the
  paper — flag this cell as partially unverified rather than asserting either way.*
- **Embodiment portability — Partial, and it is *environment* portability, not *embodiment*
  portability.** Strong evidence that the *engine* ports: one API drives ROS/Gazebo and
  MATLAB/Simulink, and two very different domains (service robot, avionics elevator control)
  are demonstrated. No evidence that a *specification* ports: STL predicates hard-code
  variable names and thresholds (`gnt >= 3`), so moving to a different robot means editing
  the formula. The paper never runs one spec on two platforms. Write "engine: yes; spec: not
  demonstrated".
- **Deterministic replay — not claimed, and partly hard to claim.** Offline monitoring over
  a fixed trace is trivially deterministic, and the discrete-time mode is time-triggered
  with a fixed period Δ, which is the right shape. But the paper offers no recording
  infrastructure, no replay mode, no statement that two runs over one episode yield the same
  verdict, and the dense-time online mode is event-driven with piecewise-constant
  interpolation, so the verdict depends on the arrival timestamps as recorded. **Do not put
  a tick in this cell.** Write "not claimed". This is the second differentiator: our
  `replay_node` + the clocking contract in `docs/clocking.md` make replay determinism an
  acceptance test, and RTAMT has no counterpart.

One more column worth adding to the table if space allows, because RTAMT wins it: **graded
output**. RTAMT emits a real-valued robustness; ours emits a rung of an ordered ladder.
Conceding a column you lose makes the columns you win credible.

### Q3 — Discrete vs dense time, and missing/stale samples

**On discrete vs dense**, there is one thing worth taking and one citation worth stealing.

- **Take:** the framing that discrete-time monitoring is *time-triggered* and "admits an
  upper bound on the use of computation resources", while dense-time is *event-driven* and
  suits distributed systems where observations are not periodically triggered. That is
  exactly our tick-vs-transport-rate distinction, stated by an established tool paper — it
  is a citation for the design, not just a description of it.
- **Steal the citation:** RTAMT justifies its discrete-time interpretation with Henzinger,
  Manna and Pnueli, *What good are digital clocks?* (ICALP 1992) — weakening/strengthening a
  real-time specification lets discrete-time evaluation preserve important properties of the
  dense-time reading. **That is the principled defence of our tick that `docs/clocking.md`
  currently argues from first principles.** If a reviewer asks "why is a fixed-period tick
  a sound abstraction of continuous time", this is the answer with a reference attached.
- Also take **pastification** as a framing device even though we do not implement it. It is
  the clean statement of the alternative to prediction: a bounded-future formula of horizon
  `H(φ)` can be monitored online by *delaying the verdict by `H(φ)` steps*. Our
  `max_steps` timing budget is the same idea reached differently — a bounded horizon
  outside the formula rather than inside it — and saying so positions our design rather than
  leaving it looking ad hoc.

**On dropout: no, there is nothing to borrow — and that is a finding, not a gap in the
reading.** RTAMT has no answer to missing or stale samples:

- Discrete-time **assumes** periodic sampling at period Δ and indexes sample `i` at time
  `i·Δ`. A dropped sample is not represented; it shifts the index of everything after it.
- Dense-time uses **piecewise-constant interpolation**: `w(x,t) = w(x,tᵢ)` for
  `t ∈ [tᵢ, tᵢ₊₁)`. A value holds until the next sample arrives — *forever*, if none does.
  This is exactly the hazard `backend/adapters/base.py:41` already names: a stale
  `min_range = 10.0` reads as "nothing nearby" indefinitely after the publisher dies. RTAMT
  would report a large positive robustness for `G(min_range > 0.25)` throughout a total
  LiDAR outage.
- `ρ` is **total** — it always returns a float. There is no `UNKNOWN` value for an
  unobserved predicate and no `UNDECIDED` verdict for a tick.
- The nearest thing in the paper is the *future work* item: extending RTAMT with event-driven
  online bfSTL monitoring so measurements may arrive at any point on the dense-time axis.
  That is about arrival *irregularity*, not about *absence*.

**So the honest write-up is:** our UNKNOWN/UNDECIDED scheme is not a reimplementation of
something RTAMT does — it addresses a case the leading STL monitoring tool leaves undefined,
and it does so in a way STL's quantitative semantics structurally cannot (a total real-valued
function has no room for "not observed"). That is a small, specific, defensible contribution
claim, and it is worth one sentence in Paper B's related work. The three-valued machinery to
cite for it is **Bauer et al. LTL3** and, from RTAMT's own related-work section, the R2U2/MLTL
line (Reinbacher et al.), whose synchronous observers yield "a 3-valued instant abstraction
of the satisfaction check" made concrete later — the closest prior art to what we are
building, and reached from an automaton rather than a robustness angle.

**One design warning taken from RTAMT.** If we ever add a margin channel to an AP, do not
aggregate margins with `min`/`max` across APs of different units the way Def. 2 does. RTAMT
gets away with it because a single CPS spec usually talks about one physical quantity;
`min(0.25 − min_range, 0.35 − |base_roll|)` compares metres with radians and is not a
quantity. Normalise per-AP, or keep the margin per-AP and never aggregate.

---

## 7. Check yourself

**1. RTAMT's online monitors accept only past-STL. How does a bounded-future property get
monitored online, and what does it cost?**
By **pastification**: `Π` rewrites a bfSTL formula `φ` into an equi-satisfiable pSTL formula
whose evaluation is shifted to the end of the formula's temporal depth `H(φ)`, so
`ρ(φ,w,t) = ρ(Π(φ),w,h(φ))`. The cost is **latency, not accuracy** — the verdict for time
`t` is emitted at `t + H(φ)`, when every input it needs has arrived. Nothing is predicted.
Example: `(req≥3) → F_[0,5](gnt≥3)` becomes `O_[5,5](req≥3) → O_[0,5](gnt≥3)`.

**2. Does RTAMT implement time robustness? Why does the answer matter to our ladder?**
No. It implements **spatial** robustness (Def. 2, infinity-norm); time robustness is
attributed in related work to Donzé and Maler and is not in the tool. It matters because our
ladder's `imminence` input is steps-to-violation — a *temporal* margin. So the claim "STL
robustness would have given you the ladder for free" is false as stated against RTAMT: the
tool would supply a spatial margin and none of the temporal one.

**3. A LiDAR publisher dies mid-episode. What does an RTAMT dense-time monitor report for
`G(min_range > 0.25)`, and what does ours report?**
RTAMT holds the last sample under piecewise-constant interpolation and keeps reporting a
confident positive robustness computed from a frozen value — indefinitely, since `ρ` is
total and has no "unobserved" value. Ours marks the AP UNKNOWN, the tick UNDECIDED, does not
step the automaton, and raises a data-health alert. Both are choices; only one distinguishes
"safe" from "not looking".

**4. What are IA-STL's output robustness and input vacuity, and what problem do they reveal
about plain robustness?**
Output robustness `μ` is the output-variable robustness with inputs held fixed; input
vacuity `ν` measures how much the input actually exercises the spec (`ν=0` = non-vacuous,
`±∞` output robustness = vacuously (dis)satisfied). They exist because a single robustness
scalar can be minimised by a change no engineer can make — shrinking the *input* until the
property is vacuously satisfied — so plain robustness is a poor localiser of *which*
component is at fault. Same reason we grade by fault category rather than by one number.

**5. Two facts from RTAMT's evaluation you can cite, and one you cannot.**
Can: the worst-case configuration (dense-time, Python back-end) costs **~0.5 ms per sample**
on an i9-10900K; and the C++ back-end is **~10× faster** than Python on
`G[0,k](a+b ≥ −2)` for `k` up to 10⁶. Cannot: any per-tick ROS end-to-end overhead figure,
any accuracy or false-alarm rate, or any comparison against a competing monitoring tool —
none of those are measured in the paper.
