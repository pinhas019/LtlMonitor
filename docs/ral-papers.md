# RA-L paper portfolio

Two papers for IEEE Robotics and Automation Letters, built on the thesis in
`docs/research-roadmap.md`: **progress states are the structure, learning supplies the
grounding.** Paper 1 shows the structure matters; Paper 2 adds learning where the structure is
weak. Paper 2 cannot be argued until Paper 1's result exists.

The engineering that produces the evidence is in `docs/implementation-plan.md`.

## Ground rules

- **Simulator first.** New evidence comes from MuJoCo with real dynamics, then Isaac Sim, then the
  real G1. **The MAAOS / continuous-MiniGrid work is frozen**: no new experiments there. Its pilot
  numbers appear once, in Paper 1, as preliminary motivation credited to the MAAOS collaboration.
- **Every claim has a control.** The flattened specification (Paper 1) and the global detector
  (Paper 2) hold the mechanism fixed and remove only the thing being claimed.
- **Labels never come from the monitor.** Ground truth is the injected fault and its injection
  tick, written outside the monitor's output path.

## Venue notes — verify before relying on them

From a web search; the RAS site was unreachable from here.

- RA-L takes submissions any time, with **no conference-specific deadlines**. Accepted papers can
  transfer to ICRA or IROS within a window after acceptance.
- Final papers are **6 pages, with up to 2 extra pages at a per-page charge** (8 maximum). Plan for
  6 including references.
- IROS 2027's own deadline is listed as 1 March 2027.

The practical consequence: plan by readiness, not by a deadline.

---

## Paper 1 — Structure matters

**Working title:** *Progress-State Monitoring: Language-Derived Temporal Specifications for
Recoverable Humanoid Skill Execution*

### Claim

A monitor that tracks an LTL progress structure derived from a natural-language skill description
enables recovery that observation-based judges do not, catches false successes they miss, at a
fraction of their per-tick cost — and the progress structure, not the monitoring mechanism, is
what is responsible.

### Contributions

1. **Progress-state specifications** — phases with enter, progress and exit guards plus named
   failure modes; drafted by a language model from a natural-language skill description, compiled
   with Spot, and checked against the robot adapter's sensor schema before they run.
2. **An embodiment-agnostic runtime** — declarative adapters, a graded intervention ladder
   (continue → warn → slow → replan → halt → abort), and deterministic record-and-replay.
3. **An evaluation built around controls** — the flattened-specification control, missed-failure
   scenarios and per-tick cost, on a humanoid in physics simulation, validated on hardware.

### Setting

- **Robot:** Unitree G1 in MuJoCo with real dynamics, walking under a learned locomotion policy.
  Navigation commands come from Nav2 in simulation and from TRAV on the robot — neither written for
  the monitor.
- **Skills:** waypoint navigation, and visual-goal approach (the `visually_at_goal` proposition).
  Both reuse the phases in `skill_monitor/specs/formulas_g1.json`.
- **Hardware:** recorded G1 episodes as validation, not as the main volume.

A useful side effect: the walking controller is itself a learned RL policy, so the monitored stack
already contains a learned skill. That partly answers the claim's requirement to hold for learned
policies, not only hand-written ones.

### Arms

| arm | what it is | why it is there |
|---|---|---|
| off | no monitor | baseline difficulty |
| **full** | the progress-state specification | the claim |
| **flattened** | one phase: safety invariants, failure modes, terminal success; no intermediate progress — derived automatically from the full spec | the same monitor without progress states |
| LLM judge | language model given the **full observation history**, not a single frame | the strongest unstructured baseline — a single-frame judge would be a straw man |
| VLM judge | vision–language model on MuJoCo renders | the contrast class from `papers/` |
| heuristic | distance/progress heuristic, no LTL | a non-learned, non-LTL baseline |

All arms run with recovery. Detection-only is kept for one comparison, to carry the pilot finding
that detection alone is worth +0.00.

### Scenarios and faults

**Procedurally generated**: randomised layouts, goals, fault type and fault onset time. Every pilot
result was exactly 0.00 or 1.00, which means the seeds produced no variance. A reviewer reads that
as a toy, so randomisation is the single largest credibility fix.

With real physics the fault library becomes realistic:

| fault | how it is injected | what it should trip |
|---|---|---|
| fall | external push perturbation | `upright`, `fell_over` |
| slip | lowered floor friction | progress stall |
| actuator weakening | torque scaling on leg joints | progress stall, possibly fall |
| sudden obstacle | spawned body in the path | `collision_risk` |
| blocked route | corridor closed mid-episode | stuck / deadlock |
| odometry drift | biased odometry | progress against the wrong target |
| sensor dropout | topic silenced | freshness / confidence |
| **false success** | goal image spoofed, or arrival reported without the path | the observation judge accepts; the progress monitor should not |

Every injection records its tick, so detection can be scored per tick.

### Metrics and statistics

- Task success with recovery.
- Detection precision and recall; **false-success rate**.
- Time-to-detection from the injection tick.
- Cost: milliseconds and tokens per tick.
- Specification generation: share of LLM-drafted specs passing the schema check, and edits needed.
- At least 20 seeds per cell over randomised scenarios; Wilson intervals; Fisher exact or bootstrap
  tests for differences between arms.

### Figures and tables

1. Concept: a false success the observation judge accepts and the progress monitor rejects.
2. Architecture: description → specification → automata → runtime → intervention.
3. Main results: arms × skills × fault classes.
4. Time-to-detection distribution per arm.
5. Cost per tick per arm.
6. A phase-timeline trace — the explanation the monitor gives.

### Page budget (6 pages)

Introduction 0.75 · related work 0.5 · method 1.5 · experimental setup 0.75 · results 1.75 ·
limitations 0.5 · references 0.25–0.5.

### Positioning

- **Natural language to temporal logic** (nl2spec, Lang2LTL, NL2TL, GinSign): these translate a
  command into a formula. This work derives a *progress structure* and monitors execution against
  it.
- **Runtime-verification tools** (ROSMonitoring, RTAMT, Reelay): they monitor hand-written
  specifications and have no notion of progress.
- **Vision–language failure detection** (Foresight, FailSafe): learned and unstructured. Argue on
  interpretability, auditability and zero training data — not raw accuracy.

### Reviewer objections, answered in the design

| objection | answer |
|---|---|
| "simulation only" | physics simulation with a learned controller, plus hardware episodes |
| "the specifications were written to match the skills" | Nav2 and TRAV were not written for the monitor; specifications are LLM-drafted |
| "the LLM judge is a straw man" | full history, the best prompt found, and a VLM judge alongside |
| "LTL monitoring is not new" | the contribution is the progress structure, its derivation from language, and the recovery-centred evaluation |
| "you claim three-valued semantics" | resolve `core/automata.py` first (unmerged branch `claude/lucid-shamir-440151`), or drop the claim |

### Kill or narrow

If the flattened arm matches the full arm on every scenario, narrow the claim to the scenario class
where a gap appears. If there is none, rethink the thesis before starting Paper 2.

### Before submission

- [ ] Simulator work packages SIM.1–SIM.5 done.
- [ ] E1 (flattened), E2 (missed failures), E3 (cost) run in MuJoCo.
- [ ] P12 enforced: simulation runs Nav2 and the robot runs TRAV, so if the monitor reads planner
      status the simulation results do not transfer.
- [ ] Three-valued semantics resolved or the claim removed.
- [ ] Hardware episodes recorded and replayed.
- [ ] Authorship settled with Elias (TRAV) and Fouzi (the MAAOS pilot paragraph).

---

## Paper 2 — Learned grounding under symbolic structure

**Working title:** *Symbolic Structure, Learned Grounding: Phase-Conditioned Anomaly Detection for
Humanoid Skill Monitoring*

### Claim

Conditioning learned execution models on the LTL progress phase improves anomaly detection over
unconditioned learned detectors, and learned propositions cut the false alarms of hand-written
thresholds — while keeping the monitor's explanations and running within budget on a Jetson AGX
Orin.

### Contributions

1. **Learned soft propositions** with debounce, a drop-in behind the `{name: bool}` interface and
   independent of the planner by construction (roadmap D1).
2. **A phase-conditioned nominal model** plus a phase-prediction head whose disagreement with the
   symbolic phase names the anomaly (roadmap D2).
3. **Evaluation on faults no predicate covers**, with timing measured on the robot's computer.

### Arms

| arm | what it isolates |
|---|---|
| symbolic only | the Paper 1 monitor |
| global learned detector | learning without structure |
| per-phase Mahalanobis, no encoder | the baseline the deep model must beat |
| per-phase GRU encoder | the conditioning claim |
| hand thresholds vs learned propositions | the grounding claim |
| full hybrid | both together |

### Faults

The Paper 1 library, plus a **held-out "unspecified" set** — faults with no predicate written for
them, such as slow actuator degradation, gradual odometry drift and a wrong target. That set is
where the learned layer has to earn its place. Detectors train on nominal episodes only.

### Vision

MuJoCo renders first: with real physics, a fall or a slip now looks like one. Isaac Sim second, for
photorealistic transfer. If the Isaac port is not ready, Paper 2 ships schema-only with vision as
stated future work.

### Metrics

Per-tick F1, AUPRC, time-to-detection, false alarms per nominal hour, milliseconds per tick and
memory on the AGX.

### Kill or narrow

| result | consequence |
|---|---|
| per-phase ≈ global | try raw automaton states or sub-phases; if it still holds, report the negative result |
| Mahalanobis ≈ GRU | publish the simple model |
| the learned layer only re-finds what the guards catch, and no earlier | keep learned propositions, drop the anomaly-detection contribution |
| labels obtainable only from monitor output | stop |

---

## Optional Paper 3

**Monitor transfer across embodiments:** the same specification on the real G1, MuJoCo and Isaac
Sim — a sim-to-sim-to-real study of whether verdicts and detection survive the change of
embodiment. Worth writing only if the Isaac port is done and Papers 1 and 2 cannot hold it. A
released dataset of labelled episodes with injection ticks is a by-product of both papers, not a
paper of its own.

---

## Open decisions

- **Can TRAV run against MuJoCo?** If it can, simulation and hardware share the same skill, which
  makes the transfer argument much stronger. Ask Elias.
- **Which GPU host runs Isaac Sim, and from when?** The Isaac image was deleted during a disk
  cleanup.
- **Second skill for Paper 1:** visual-goal approach is cheap and reuses the specification;
  pick-and-place is stronger but needs arm control and probably Isaac.
