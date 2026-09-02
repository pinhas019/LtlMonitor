# Temporal Logics and Formal Synthesis for Robot Planning and Control

**Tumova, Verhagen & Vahs, KTH Royal Institute of Technology** — arXiv:2606.21438v1
[cs.RO], 19 June 2026. Key: `tlsynthesis2026survey`. Read #16, Day 3 (framing).

**Role in our paper.** One paragraph of the introduction, plus a boundary. This is the
contrast class for the *synthesis* reviewer, exactly as `fm-robots-survey` is the
contrast class for the *formal methods* reviewer and `foresight` / `failsafe` are the
contrast class for the *VLM* reviewer.

---

## 1. In one paragraph

This is a tutorial-style manuscript (the authors call it a "manuscript" throughout, not
a survey) on two things: temporal logic as a **specification language** for robot
behaviour, and **formal synthesis** as the machinery that turns such a specification
into robot behaviour with provable guarantees. Section 2 introduces LTL and STL with
full syntax and semantics definitions, plus a short tour of MTL/MITL, TWTL, GDTL, risk
and probabilistic variants, and branching-time CTL/PCTL. Section 3 — the bulk — lays out
four synthesis paradigms: graph- and game-based (automata-theoretic) synthesis,
sampling-based motion planning, trajectory optimization, and control-certificate-based
synthesis via CLFs and CBFs. Sections 4 and 5 are about deployment: uncertainty from
noisy perception, external disturbances and unmodelled physical interaction (with worked
case studies including a light-dark-domain belief-space example, an AUV disturbance
example, and a space object-transportation experiment on the ATMOS platform), then
dynamic environments, model unavailability, multi-robot systems, and human-robot
interaction. It is a principles document, not a tools or empirical survey: it reports no
benchmark, and names **no software tool at all** — Spot, TuLiP, NuSMV, Breach, S-TaLiRo
and RTAMT appear zero times in the text. ~42 pages, ~130 references, WASP / Wenner-Gren
funded.

## 2. Key concepts and definitions

**Formal synthesis** (their §3, verbatim): *"the automated generation of a system or a
system behavior from a formal specification, such as a temporal logic formula. Typical
for formal synthesis are provable guarantees on whether or how well the synthesized
system or system behavior satisfies the specification."* Immediately after, they scope
themselves: *"In this section, we focus on the **offline** model-based formal synthesis
of a single agent behavior."*

**Their three problems** — this is the manuscript's core taxonomy and the cleanest thing
to cite:

| | Problem | Given | Find |
|---|---|---|---|
| P1 | **Feasibility** (a.k.a. correct-by-design) | robot model + φ | a behaviour guaranteeing satisfaction of φ |
| P2 | **Constrained optimization** | robot model + φ + objective | a behaviour guaranteeing φ *and* optimizing the objective |
| P3 | **Optimal satisfaction** | robot model + φ | a behaviour maximizing the *degree* of satisfaction of φ |

Note what all three share: a **robot model** is an input, and the output is a
**behaviour**. That shared structure is the boundary we need (§4.1 below).

**Their synthesis taxonomy** (§3.1–3.4), roughly following the planning hierarchy from
abstract-discrete down to continuous:

- **Graph/game-based** — abstract to a labelled deterministic transition system (DTS),
  translate φ to a Büchi automaton, build the product automaton, find a **lasso** (finite
  prefix + accepting cycle) by graph search, project back to a prefix-suffix control
  strategy. Explicitly *"heavily inspired by LTL model checking"* (Baier & Katoen 2008).
  Extends to NDTS/MDP/POMDP, where non-determinism becomes an adversarial player and
  stochasticity a 1/2-player, and one seeks a *winning strategy*.
- **Sampling-based** — RRT*/PRM variants with the specification woven into rewiring (STL
  robustness as the rewiring criterion) or into sampling bias; multi-layered planning
  stacks a discrete automaton layer on a continuous geometric/kinodynamic layer.
- **Trajectory optimization** — encode STL into constraints/objective; MILP with binary
  variables (sound and complete under convexity, combinatorially expensive) or smooth
  non-convex approximations (sound, not complete, needs a good initial guess, scales).
- **Control certificates** — CLFs certify `F` (eventually), CBFs certify `G` (always),
  time-varying CBFs unify the two for richer STL.

**Fragments and scalability levers they name:** syntactically co-safe LTL (sc-LTL), whose
satisfaction is decided by a *deterministic finite automaton*, turning an infinite-horizon
problem into a finite-horizon one; **GR(1)**, where the system is not explicitly modelled
and one instead discharges `φ_e ⟹ φ_g`, avoiding Büchi construction entirely; receding
horizon planning (Wongpiromsarn et al. 2012).

**STL robustness** — Definition 6, space robustness. Used as an optimization objective
(P3), a rewiring criterion, and a guidance signal. Also temporal robustness (Rodionova
et al. 2023) and disturbance robustness (Verhagen et al. 2024).

**Specification design** (§2.4) — only ~15 lines, and it recognises exactly two routes:
(a) **explicit input**, either the formula directly or a user-friendly front-end that maps
onto one — LTLMoP structured English (Finucane et al. 2010), a graphical LTL interface
(Srinivas et al. 2013), and *"translating input in natural language into LTL or STL [which]
has recently gained popularity due to advances in LLMs including works that consider
guarantees on the correctness of the translation (Wang et al., 2025)"*; and (b) **learning
from examples** of good and bad behaviour (Shah et al. 2018; Chou et al. 2022 for LTL;
Bombara & Belta 2021, Linard et al. 2022, Aasi et al. 2023 for STL).

**What they do *not* define.** They never define verification, model checking, or
monitoring as activities distinct from synthesis. "Verification" appears three times in
the whole document — once in the introduction's definition of formal methods, twice in a
decidability remark contrasting LTL and STL. There is no verification section.

## 3. Findings — the state of the field as they see it

- **Synthesis works, in the lab.** The four paradigms are mature and increasingly
  combined: *"Many state-of-the-art solutions combine multiple of the above paradigms
  into hierarchical frameworks."*
- **The binding constraint is deployment, not theory.** Their conclusion: *"bridging the
  gap between formal synthesis and practical deployment remains challenging: uncertainty,
  model inaccuracy, and computational scalability continue to limit applicability in
  real-world systems."*
- **Scalability is the recurring tax.** Büchi construction is exponential in formula
  length; deterministic Rabin automata are doubly exponential; the product automaton
  compounds it with the model. Hence the flight to fragments (sc-LTL, GR(1)) and to
  abstraction-free and sampling-based methods, *"the price paid for efficiency [being]
  weaker (probabilistic) completeness guarantees."*
- **Guarantees are traded, not obtained.** Repeatedly: strong guarantees rest on
  conservative formulations or strong assumptions, or cost too much to compute.
- **Specifications fail, and the field repairs them.** §3.1.3 "Strategy non-existence" is
  a small but well-developed literature: revise the specification until realizable
  (Fainekos 2011), fall back to **least-violation / minimum-violation** semantics (Tumova
  et al. 2013; Maly et al. 2013; Reyes Castro et al. 2013), mine additional assumptions
  (Li et al. 2011), or change the robot by adding skills (Pacheck & Kress-Gazit 2023).
- **Everything happens offline, then gets patched online.** Online behaviour is framed
  purely as *re*-synthesis: plan patching (Livingston et al. 2012), reconfiguration (Guo
  & Dimarogonas 2015), online learning + synthesis (Grover et al. 2021), real-time RRT*
  (Linard et al. 2023), online control synthesis (Yu et al. 2024a), resilient synthesis
  under robot failures (Kalluraya et al. 2023), and MPC-style *"online tracking"* to close
  the gap left by unmodelled physical interaction.
- **Model availability is the open frontier** (§5.2). Learning-based synthesis — RL with
  TL rewards, neural controllers, TL-conditioned diffusion, TL-constrained LLM agents —
  *"often lack[s] provable correctness, interpretability, and reliable behavior under
  distributional shifts."* That sentence is worth having: it is a synthesis paper making
  our interpretability argument for us.

## 4. For skill_monitor

### 4.1 The boundary, and the paragraph

The manuscript's own framing draws the line for us in one move. Every one of their three
problems takes **a robot model as an input** and returns **a behaviour as an output**, and
they scope §3 to *offline* synthesis. The specification is upstream of the controller: it
constrains what gets built. `skill_monitor` inverts both arrows. We take no model of the
robot's dynamics, we produce no behaviour, and our specification is downstream of a
controller that already exists and that we did not constrain. The right word for what we
consume is not "model" but **executed prefix**: a finite, growing word over the robot's
declared sensor schema.

Three consequences worth stating explicitly, because they are what a synthesis reviewer
will check:

1. **We inherit none of their guarantees.** No correct-by-design claim is available to us
   and we should never imply one. Our soundness claim is about the *oracle* (a spec
   referencing an undeclared or ill-typed sensor is rejected before deployment) and about
   the *automaton* (the Spot-built DBA decides the three-valued verdict of the prefix
   exactly). Neither is a claim about the robot's behaviour.
2. **We inherit none of their costs either.** No state-space abstraction, no product
   automaton over a transition system, no realizability check, no exponential blow-up
   multiplied by model size. Our automaton is built once, from the formula alone, and is
   stepped per observation. The scalability tax that dominates their §3.1.3 does not apply
   to us — and this is the honest reason we can run on a humanoid at rate, not superior
   algorithms.
3. **Unrealizability is our signal, not our failure.** In their §3.1.3, a specification
   the robot cannot satisfy is a synthesis failure to be repaired away. For us it is
   precisely the case worth detecting. This is the sharpest single sentence of the
   contrast and it is worth putting in the paper.

**Draft paragraph for the introduction** (cite `tlsynthesis2026survey` for the definition
and scope; add Kress-Gazit et al. 2018 as a second, peer-reviewed synthesis anchor):

> Temporal logic entered robotics chiefly as a *specification language for synthesis*: the
> automated generation of a plan, policy, trajectory or control strategy from a formula,
> carrying provable guarantees that the generated behaviour satisfies it [Tumova et al.
> 2026]. Every problem in that literature — feasibility, constrained optimization, optimal
> satisfaction — takes a model of the robot as an input and returns a behaviour as an
> output, and the guarantee is a property of that construction. skill_monitor inverts both
> arrows. The controller already exists, we did not write it and cannot re-synthesise it:
> the navigation stack on our platform is a black box, and the monitor is deliberately
> independent of it so that a failure of the stack cannot silently become a failure of the
> monitor. What we consume is not a model but an executed prefix — a finite, growing word
> over the robot's declared sensor schema — and what we produce is not a behaviour but a
> three-valued verdict on it. We therefore claim none of synthesis's correct-by-design
> guarantees, and we pay none of its costs: no state-space abstraction, no product
> automaton, and no requirement that the specification be realizable at all. That last
> point is the substantive difference rather than a concession. Where synthesis treats an
> unsatisfiable specification as a failure to be repaired before deployment [Fainekos
> 2011], we treat it as the case worth detecting during it.

**One-line boundary for the related-work section:** *"We are downstream of synthesis, not
a weak instance of it: we watch a controller we did not constrain, and our verdict is
about the trace, not about the controller."*

### 4.2 Does the manuscript cover runtime verification or monitoring?

**No. Essentially not at all, and the absence is measurable.** Case-insensitive substring
counts over the complete extracted text:

| term | occurrences |
|---|---|
| "runtime" / "run-time" | **0** |
| "monitor" (any case, any inflection) | **1** — and it is in the bibliography, in the *title* of Maler & Nickovic (2004), cited to introduce STL |
| "shield" / "supervisory" / "supervisor" | **0** |
| "LTL3" / "three-valued" / "3-valued" | **0** |
| "LTLf" / "finite trace" | **0** |
| "black box" / "black-box" | **0** |
| "verification" | 3 (intro definition; a decidability remark) |
| "model checking" | 3 (intro; the automata-based recipe; Baier & Katoen in refs) |

There is no monitoring section, no monitoring subsection, and no monitoring entry in any
of the three "Main takeaways" lists. The closest the manuscript comes to online evaluation
is (a) STL robustness computed over a trajectory as an *optimization objective*, and (b)
"online tracking, typically in some form of an MPC" — i.e. re-synthesis, not observation.

**How to use this, and how not to.** It is *not* honest to cite this as evidence that
robotics does not monitor — the manuscript is titled "formal synthesis" and its silence is
scope, not a survey finding. What it *is* good for, and what it is genuinely strong
evidence of, is the shape of the field's default: a 2026 tutorial by a leading synthesis
group, written to introduce temporal logic to roboticists, spends forty-two pages on
turning specifications into controllers and zero on checking whether a controller that
already exists is honouring one. Safe formulations:

- "In the robotics literature, temporal logic is overwhelmingly a *synthesis* language;
  recent tutorial treatments of temporal logic for robot planning and control devote their
  taxonomy entirely to generating behaviour from a specification, and do not treat runtime
  evaluation of an existing controller as a problem class [Tumova et al. 2026]."
- Pair it with `fmras2025survey`, which *is* a structured survey with monitoring in scope,
  to make the point without over-claiming: the structured survey finds monitoring work
  exists; the synthesis tutorial shows where the centre of gravity sits.

Consequence for us: **no competitor lives in this paper.** Nobody here is doing what we do.
The reviewers this paper predicts are reviewers who will mis-file us, not out-scoop us —
which is exactly why the boundary paragraph in §4.1 has to be in the introduction and not
in the related work.

### 4.3 Cited works we are missing

Verified against `docs/paper/references.bib`: none of the six appears there under any
author name (checked Kress-Gazit, Belta, Maler, Tumova, Fainekos, Kantaros, Lindemann,
Dimarogonas, Wongpiromsarn, Yin — all zero; the Shah/Tellex hits are `lang2ltl` and
`hsiung2022lifted` only).

1. **Wang, Sundarsingh, Deshmukh & Kantaros (2025), "ConformalNL2LTL: Translating natural
   language instructions into temporal logic formulas with conformal correctness
   guarantees", arXiv:2504.21022.** — The single most important omission, and the one work
   in this manuscript's §2.4 on guaranteed NL→LTL translation. It is the direct alternative
   to our LLM-compiles + sound-static-oracle-validates design. We must state why a
   schema-typed sound rejection is preferable to (or complementary with) a conformal
   coverage bound. We already cite `scpnl2tl2026` on selective conformal prediction —
   these belong in the same sentence.
2. **Maler & Nickovic (2004), "Monitoring temporal properties of continuous signals",
   FORMATS.** — The origin of both STL and of temporal-logic monitoring, and the ancestor
   of `rtamt2025` and `reelay2026`, which we already cite without their root. Cheap to add,
   and it is the canonical thing to point at when we say "monitoring temporal properties is
   not new; monitoring *acquired* specifications is."
3. **Yang, Raman, Shah & Tellex (2024), "Plug in the safety chip: Enforcing constraints for
   LLM-driven robot agents", ICRA, pp. 14435–14442.** — The closest work in the manuscript
   to our whole system: LTL constraints attached to an *LLM-driven* robot agent. It
   enforces rather than monitors (constraints shape action selection), which makes it the
   ideal foil for the intervention-ladder discussion — we should say plainly that they gate
   actions and we grade responses to verdicts.
4. **Fainekos (2011), "Revising temporal logic specifications for motion planning", ICRA,
   pp. 40–45.** — The canonical citation for "the specification itself is wrong, repair
   it." Our static oracle rejects; `verifyrepairstop2026` governs how many times we retry.
   This is the fourteen-year-old precedent for the repair loop, and a reviewer who knows it
   will notice its absence.
5. **Shah, Kamath, Shah & Li (2018), "Bayesian inference of temporal task specifications
   from demonstrations", NeurIPS 31.** — Spec acquisition by learning rather than by
   language. Pre-empts "why not just infer the spec from demonstrations?" Answer: we have
   no demonstrations of failure, and we need the spec to be readable by the operator who
   wrote the skill description.
6. **Kress-Gazit, Lahijanian & Raman (2018), "Synthesis for robots: Guarantees and feedback
   for robot behavior", Annual Review of Control, Robotics, and Autonomous Systems
   1:211–236.** — The standard synthesis anchor, and better than this arXiv manuscript for
   the introduction's boundary sentence because it is peer-reviewed, highly cited and
   explicitly about *guarantees and feedback*. Cite it alongside `tlsynthesis2026survey`,
   which supplies the current-state framing.

*Deliberately not promoted:* Wongpiromsarn et al. 2012 (receding horizon), Tumova et al.
2013 (least-violation), Pacheck & Kress-Gazit 2023 (physically feasible repair), Yin, Gao
& Yu 2024 (Annual Reviews in Control survey of controller synthesis for safety-critical
autonomous systems). All defensible; none earns space in a six-page ICRA submission unless
a reviewer asks. Yin et al. 2024 is the one to promote first if a reviewer wants a second
survey-level synthesis citation.

### 4.4 Vocabulary for the intervention ladder

**Bad news: the manuscript gives us none of the four terms we hoped for.** "Shielding" — 0
occurrences. "Runtime enforcement" — 0. "Supervisory control" / "supervisor" — 0. "Safety
filter" — not present. "Enforce" appears four times and never means runtime enforcement:
three times it means a CLF/CBF *certificate* enforcing an STL formula in closed loop, once
it means a hard constraint in an optimization, plus once in the title of Yang et al. 2024.

So the established names for *shielding* and *runtime enforcement* are not sourceable from
this paper, and we should take them from the RV literature (Bloem/Könighofer-style
shielding, Falcone-style runtime enforcement) rather than invent or borrow loosely. **Do
not call our ladder a shield** — a shield sits in the action path and overrides the
controller; ours emits a recommendation about a controller it does not sit inside. That
distinction is worth one sentence in the paper.

**Good news: two pieces of the manuscript's vocabulary do transfer, and both are
load-bearing.**

- **Least-violation / minimum-violation semantics** and **degree of satisfaction** (their
  Problem 3; Tumova et al. 2013; Maly et al. 2013; Reyes Castro et al. 2013; STL robustness,
  Def. 6). This is the field's established name for *the graded part* of what we do — the
  idea that violation is a quantity, not a bit, and that a system should prefer smaller
  violations. It is the right vocabulary for justifying why a ladder exists at all instead
  of a single HALT. We can say our ladder is a **discretisation of graded violation into
  operator responses**, and that framing lands with anyone who knows Problem 3.
- **Plan repair / patching / reconfiguration / resilient synthesis** (their §5.1;
  Livingston et al. 2012; Guo & Dimarogonas 2015; Kalluraya et al. 2023). This is exactly
  the established name for our **REPLAN** rung. Use "replanning" and cite plan
  reconfiguration — that rung is not novel and should not be presented as such.

Concretely, for the ladder as a whole: keep our own rung names (they are operational, not
theoretical), but anchor them once with a sentence like *"the ladder discretises graded
violation — the notion underlying least-violation planning and quantitative satisfaction
semantics [Tumova et al. 2013; Problem 3 in Tumova et al. 2026] — into a fixed set of
operator-facing responses, of which only REPLAN corresponds to a synthesis-side action."*
We keep credit for the mapping; we cede credit for the gradedness. WARN, SLOW, HALT and
ABORT have **no source in this manuscript** — do not pretend otherwise.

## 5. Check yourself

**Q1. A reviewer says: "This is just LTL synthesis with the synthesis part missing."
Answer in two sentences using the manuscript's own taxonomy.**
Every problem in that taxonomy (their Problems 1–3) takes a robot model as an input and
returns a behaviour as an output, with the specification constraining what gets built; we
take a finite executed prefix over a declared sensor schema and return a verdict, with the
specification constraining nothing. The synthesis part is not missing — it is a different
problem, and the clearest evidence is that an *unrealizable* specification is a failure
mode there (their §3.1.3, repaired away by Fainekos 2011) and the target detection here.

**Q2. How many times does the word "monitor" appear in this forty-two-page manuscript, and
where?**
Once, in the bibliography, inside the title of Maler & Nickovic (2004) "Monitoring temporal
properties of continuous signals" — cited as the source of STL, not as monitoring work.
"Runtime" appears zero times.

**Q3. May we write "existing surveys of temporal logic in robotics do not cover runtime
monitoring"?**
No — that overstates it, and `fmras2025survey` (Read #15) would contradict us. This is a
synthesis manuscript; its silence on monitoring is scope, not a finding about the field.
The defensible claim is about the centre of gravity: temporal logic in robotics is
overwhelmingly deployed as a synthesis language, and a 2026 tutorial treatment devotes its
entire taxonomy to generating behaviour from a specification.

**Q4. Can we call the intervention ladder a "shield"?**
No. The manuscript contains no shielding vocabulary at all (0 occurrences), so it is not
sourceable here; more importantly a shield is an enforcement layer in the action path that
overrides the controller, whereas the ladder emits a graded recommendation about a
controller it is deliberately outside of. What *is* sourceable here is the gradedness:
least-violation semantics and degree-of-satisfaction (their Problem 3) are the established
names for treating violation as a quantity, and "plan reconfiguration/repair" is the
established name for the REPLAN rung.

---

## Provenance and caveats

- Author list, affiliation, arXiv ID, version, category and date read directly off page 1
  of the PDF: **Jana Tumova, Joris Verhagen, Matti Vahs**, KTH Royal Institute of
  Technology; `arXiv:2606.21438v1 [cs.RO] 19 Jun 2026`. Emails `tumova@kth.se`,
  `jorisv@kth.se`, `vahs@kth.se`. No author ordering ambiguity — they are listed in this
  order on the title page.
- All term counts in §4.2 and §4.4 come from case-insensitive substring searches over the
  complete extracted text of the manuscript, not from a partial read.
- **Not verified:** whether a peer-reviewed journal or book-chapter version exists. arXiv
  and alphaXiv are blocked from this environment, so the arXiv comments and journal-ref
  fields could not be read. The text describes itself as a "manuscript" (5 times) with a
  tutorial structure, an objectives list, worked examples and per-section "Main takeaways"
  — consistent with a book chapter or an Annual Review-style article — but no venue is
  stated anywhere in the PDF. Treat as arXiv-only until checked.
- **Not verified:** exact page count (~42, inferred from the last numbered reference page)
  and exact reference count (~130, counted from the bibliography listing, not stated by the
  authors).
