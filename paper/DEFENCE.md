# Defence preparation: adversarial read of the scientific claims

Written as a hostile reviewer. Each item: the attack, whether it lands, and
the best available answer. "Fixed" means the paper was wrong and has been
corrected; "Standing" means the attack is legitimate and you need the answer
ready.

## A. Claims that were wrong and are now corrected in `ral.tex`

1. **"The monitor's three verdicts are exactly LTL3's."** False. Only
   VIOLATED is LTL3's ⊥ (non-accepting sink). ACCEPTED means "current state
   is accepting": it is reported for `G(!collision_risk)` from tick 1 and can
   revert, so it is not ⊤. §II-B now says so.
2. **"On the wedged trace the ladder raises a progress fault within m
   ticks."** False for the shipped spec. Its progress conditions are
   `not nav_stuck` and `moving_towards_target or not nav_stuck` — planner
   self-report. A planner that says `following` keeps them true. Only the
   deadline (120 ticks) fires. §I and Fig. 1 corrected.
3. **"A behaviour tree does not denote a language of traces."** False. BTs
   have formal semantics; a condition-only tree denotes a state invariant.
   Reworded to "executable, not a declared property".
4. **"Per-tick cost is independent of formula size."** False: it grows with
   the proposition count and the automaton, which can be exponential.
5. **"Deterministic Büchi automata."** Determinism is requested of Spot, not
   guaranteed; not every LTL formula has one, and the code takes the first
   matching edge. Now stated, with the missing contract check named.
6. **"Ambiguity surfaces as a rejected proposal."** False. Gates catch
   malformed specs; an ambiguous description can yield a well-formed wrong
   one.
7. **"Spurious phase switching is structurally impossible."** Misleading. The
   ladder cannot flicker, but a one-tick glitch in an exit condition advances
   it irreversibly.
8. **"None of them attaches a horizon to a stage."** Overclaim. Nav2's
   progress checker (move 0.5 m within 10 s, or fail) is a progress budget
   inside the controller. The claim is now placement, not mechanism.
9. **"DynSTEER is our thesis with numbers."** Overreach: it measures
   discriminability between agents, not failure detection.

## B. Standing attacks

| # | Attack | Lands? | Best answer |
|---|---|---|---|
| 1 | Proposition 1 is a tautology: a timeout times out. | Yes | Agree. Its content is that the horizon comes from the specification and is independent of sensing. The paper's empirical claim is cost, not detection. |
| 2 | "A fault within the bound" is not "a correct detection". A timeout on a slow healthy run is a false alarm, so ρ = 1 is hollow. | Yes | ρ = 1 means only "non-success always yields a verdict". Correctness is the false-alarm side, which is measured. Say this before the reviewer does. |
| 3 | H2's curve for the deadline is analytic: false-alarm(k) = P(nominal phase duration > k), delay = k − time already spent. You are measuring how long healthy runs take. | Yes | Concede for the deadline: choosing k is picking a quantile of nominal duration. The non-trivial curve is the progress budget's, which depends on noise in the progress signal. Lead H2 with that one. |
| 4 | The CUSUM/Lorden analogy is decoration: no stochastic model, no optimality. | Partly | Only the form of the criterion is borrowed (delay at fixed false-alarm level); the paper already disclaims optimality. Do not lean on it further. |
| 5 | Title and abstract say phases make failure detectable; §IV concedes deadlines do, and bounded LTL can too. | Yes | The title overclaims relative to the body. Either retitle around "bounded per-stage obligations" or be ready to say the title names the design, not the theorem. |
| 6 | Table I is rigged. LTL expresses bounded eventualities with nested X; DFAs/reward machines have sink states, hence permanence; STL allows unbounded intervals. | Partly | Columns mean "forces/gives by default", not "can express". Weakest artifact in the paper; consider rewording column heads or dropping contested cells. |
| 7 | This is a watchdog timer with formal vocabulary. BT timeout decorators, ROS action timeouts and Nav2's progress checker already exist. | Partly | All of those are the component timing itself out. The contribution is an independent, declared, per-stage bound with a categorised verdict. If that sounds small, it is the honest size of the mechanism claim. |
| 8 | A safety monitor that cannot report a violation during a sensor outage is unsafe; loss of sensing should halt. And as built, a missing proposition fabricates or hides a fault depending on its polarity. | Yes | No good answer today. The design relies on a data-health alarm that is not evaluated. Expect this to be pressed. |
| 9 | Schema-name parity is not semantic parity: `min_range` from lidar and from depth are different quantities. Verdict equality across sim and real needs physical fidelity, not key names. | Yes | Portability is of the monitor, not of the thresholds. H6 tests replay of one stream, which does not exercise this. Claim less. |
| 10 | The authorship gates check well-formedness, not meaning; the only spec shown is hand-written; there is no evidence a generated ladder works. | Yes | Nothing until H7 is run. |
| 11 | The headline scenario is caught only by the deadline, the weakest mechanism; the progress budget reads the planner. | Yes | True until the planner-independent schema lands. This is the strongest reason to land it before collecting data. |
| 12 | "AHA has no stall class, which is why the gap went unremarked" is speculation, and Guardian does have a no-progress class. | Yes | Present it as an observation about one dataset, not an explanation. |
| 13 | No experiment, one robot, one skill, total-order phases. | Yes | Known; §VIII. |

## C. What holds under attack

- The nested-F goal formula has no bad prefix, so an LTL3 monitor never
  refutes it. Textbook, correctly applied.
- `F≤k p` is decided within k+1 positions.
- RV-LTL's "presumably false" holds on every prefix of a successful run until
  the last tick, so it cannot separate stalled from healthy.
- LTLf gives a verdict only at the trace end and does not say when that is.
- Proposition 1, as now stated (Σ(kᵢ+1), from first phase entry, deadlines
  declared), matches the code.

## D. Three questions to rehearse

1. "What does your paper show that a per-phase timeout in the planner does
   not?" — independence from the component being judged.
2. "What is your empirical result?" — today, none; planned: the progress
   budget's delay/false-alarm curve against B2 and B3.
3. "Why is the progress condition in your own spec written over the
   planner's status?" — it should not be; that is the redesign.
