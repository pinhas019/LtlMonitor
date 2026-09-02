# Runtime Monitoring of Perception-Based Autonomous Systems via Embedding Temporal Logic (ETL)

Parv Kapoor\* and Abigail Hammer\* (Software and Societal Systems Department, Carnegie Mellon
University), Ashish Kapoor (Scaled Foundations), Karen Leung (Aeronautics and Astronautics,
University of Washington), Eunsuk Kang (S3D, Carnegie Mellon University). \* = equal contribution.

`arXiv:2605.12651v1 [cs.LG]`, 12 May 2026. Every page header reads "Preprint." — no venue is
stated in the paper. Artifacts URL given in a footnote on p.7:
`https://github.com/ETLMonitoringAuthors/ETLMonitoring` (an anonymised author handle; **not
fetched or verified from this environment**).

Page numbers below refer to the arXiv PDF as paginated by the retrieval tool.

---

## 1. In one paragraph

ETL is LTL with the atomic propositions moved out of the state space and into a pretrained
encoder's embedding space. The authors' complaint is not that runtime monitors produce Boolean
verdicts — it is that getting *to* a Boolean verdict about a perceptual concept ("the gripper is
holding the object", "the robot is near the obstacle") currently requires you to build an extra
detector, classifier or state-estimation pipeline whose only job is to manufacture a
low-dimensional state variable for the predicate to threshold. Those modules are "computationally
expensive, brittle, and semantically misaligned" (abstract, p.1), and the vocabulary problem
compounds: every new concept ("dropping" as well as "holding") means another module (p.2). ETL's
move is to make the *embedding* a first-class object in the specification. A predicate is a tuple
`(Z_target, d, ε, ▷◁, a)` — a set of target embeddings obtained by running **reference images**
through a pretrained encoder, a distance function, a threshold, a comparison, and an aggregator —
and it holds at time `t` iff `a({d(z_t, z_g) : z_g ∈ Z_target}) ▷◁ ε` (Defs. 5–6, p.5). Everything
above the predicate is standard: LTL syntax (`ap | ¬φ | φ₁∧φ₂ | φ₁ U φ₂`, Def. 7), standard LTL
satisfaction over the embedding trace (Def. 8), and an STL-style robustness `ρ` layered on top
(Def. 11, p.14). The paper's real technical contribution beyond the definitions is **threshold
calibration**: an F1-optimal `ε_F1` fit on labelled calibration trajectories, and a split-conformal
`ε_CP` carrying a distribution-free, per-demonstration *recall* guarantee (Thm. 1, p.15). They
evaluate on a Dubins-car navigation task with privileged ground truth, on D3IL/MetaWorld
manipulation against two embedding-based failure detectors, and on real DROID robot data against a
VLM monitor.

**The thing to notice up front, because it changes what this paper means for `skill_monitor`:
ETL still thresholds, and ETL's satisfaction relation is still Boolean.** The abstraction the
authors attack is the *intermediate low-dimensional state variable and the bespoke module that
produces it*, not the act of collapsing a continuous score to a bit. Section 6 works through what
that implies.

---

## 2. Key concepts

**Perception-based system** — a system that "map[s] high-dimensional sensor streams such as images,
video, or lidar to compact latent representations, which are then consumed by downstream policies,
planners, or world models" (p.2). The framing claim is a *mismatch*: "there is a fundamental
mismatch between (i) the latent space over which typical perception systems operate and (ii) the
low-dimensional state space over which specifications in existing temporal logic notations are
expressed" (p.2).

**Embedding Temporal Structure** (Def. 1, p.4) — `M ≡ (S, O, Z, φ_obs, ψ_enc, D_Z, AP_z)`: ground-truth
states, observations, embedding space, an observation function `φ_obs : S → O`, an encoder
`ψ_enc : O → Z`, a set of admissible distance functions `D_Z`, and the set of embedding predicates.

**Representation map** (Def. 3) — `η ≡ ψ_enc ∘ φ_obs : S → Z`. A **trace** (Def. 4) is
`σ = (z_i)`, `z_i = η(s_i)`. Note the state `s_i` is never available to the monitor; it exists in
the formalism only so that "correctness" can be defined against it.

**Embedding predicate** (Def. 5, p.5) — `ap ≡ (Z_target, d, ε, ▷◁, a)` where `Z_target ⊆ Z` is a set
of target embeddings, `d : Z × Z → ℝ≥0` a distance, `ε ∈ ℝ≥0` a threshold, `▷◁ ∈ {≤,<,≥,>}`, and `a`
an aggregation operator (e.g. `min`, `max`).

**Predicate satisfaction** (Def. 6, p.5) — `δ_ap(z) = a({d(z, z_g) | z_g ∈ Z_target})`, and the
predicate holds iff `δ_ap(z) ▷◁ ε`. Their Example 1 instantiates `d = L2`, `a = min`, `▷◁ = ≤`, so
`δ_ap(z_t) = min_{z_g ∈ Z_target} d(z_t, z_g)` — distance to the *nearest* reference image — and the
predicate holds when the current frame "lies sufficiently close to at least one target embedding,
indicating that the desired visual concept is present."

**Where targets come from** (§3.3, App. A.1, p.13) — not from vectors typed by hand. "the targets
would be provided in the same format as the sensor's input, e.g., for a camera, a target would be
provided as a reference image, that is then translated into the target embeddings via the pretrained
encoder." The selling point: "This allows specifications such as 'eventually reach a state similar to
this image' or 'always avoid states resembling fire' without requiring explicit symbolic labels…
[it] removes the need to manually define a finite predicate vocabulary from observations."

**ETL syntax and semantics** (Defs. 7–8, p.5) — syntax is exactly LTL: `φ ::= ap | ¬φ | φ₁ ∧ φ₂ |
φ₁ U φ₂`, with `F φ = True U φ` and `G φ = ¬F¬φ`. Semantics are "defined similarly to those of LTL,
but over embedding traces" — the *only* change from LTL is the base case `σ, i ⊨ ap ⟺ δ_ap(z_i) ▷◁ ε`.
There is no fuzzy, graded or probabilistic satisfaction relation. Boolean satisfaction survives intact.

**Robustness** (Def. 11, App. B, p.14) — the quantitative layer, STL-style:
`ρ(ap, σ, i, b) = ε − δ_ap(z_i)` when `▷◁ ∈ {≤,<}` (and `δ_ap(z_i) − ε` for `{≥,>}`), with
`ρ(¬φ) = −ρ(φ)`, `ρ(φ₁∧φ₂) = min`, `ρ(Gφ) = inf_{k∈[i,b]}`, `ρ(Fφ) = sup_{k∈[i,b]}`. Note the
**bound `b`** — robustness is computed over a *bounded window* `[i, b]`, "determined by, for example,
the planning horizon used by a planner." The `U` case is explicitly omitted "for brevity" (p.14).

**ETL monitor** (Def. 10, p.6) — over a finite trace `σ≤t`, `M_φ(σ≤t) = (r_0, …, r_t) ∈ {−1,+1}^{t+1}`
with `r_i = sgn(ρ(φ, σ≤i, 0, i))` and `sgn(x) = +1` iff `x ≥ 0`. "when the robustness of the system
becomes negative at timestep i, the monitor raises an alert to indicate that the observed execution
violates φ over the prefix [0, i]."

**Semantic correctness** (Defs. 12–15, App. C, pp.14–15) — the correctness criterion is *agreement
with a state-based monitor*, not agreement with a human. A ground-truth monitor `GT_ω(ς≤t)` evaluates
a classical TL formula `ω` over the true state trace; `φ` **semantically corresponds** to `ω` if
`σ≤t ⊨ φ ⟺ ς≤t ⊨ ω` for every prefix; an ETL monitor is **semantically correct** iff
`M_φ(σ≤t) = GT_ω(ς≤t)` for every prefix. In the experiments this is approximated by measuring
frame-level F1 and agreement against simulator-derived labels.

**Conformal prediction** — used only as a threshold-calibration device, not for prediction sets:
"a distribution-free calibration framework that turns a held-out calibration set into a finite-sample
statistical guarantee under only an exchangeability assumption" (p.3).

---

## 3. Method — concretely

### 3.1 The pipeline

1. An engineer supplies, per predicate, a small set of **reference images** of the concept
   (goal reached, object grasped, fire present).
2. A **pretrained encoder** `ψ_enc` embeds them → `Z_target`, and embeds each live frame → `z_t`.
   The encoder is a design choice; see §3.3 below.
3. Pick a **distance** `d`. App. A.2 (p.13) gives the rule of thumb: "cosine distance is a natural
   choice for contrastive embeddings, whereas L2 distance is often more appropriate for
   reconstruction-based latent representations." They also note pretrained image encoders "lack
   temporal context because these encoders are trained on static observations", which motivates
   using a **world-model latent** instead, whose space "evolves as a function of past states and
   actions" while often preserving the geometry of the underlying observation embedding.
4. Pick an **aggregator** `a` over the target set (`min` = distance to nearest reference).
5. **Calibrate `ε`** (§4 — this is the part that is actually new, see below).
6. Compose predicates with LTL operators; run the monitor of Def. 10 online.

### 3.2 What replaces Boolean satisfaction — the honest answer: *nothing*

This is the question the reader most needs answered precisely, so state it plainly.

- **Boolean satisfaction is not replaced.** Def. 8 is LTL. `σ, i ⊨ ap` is a two-valued relation.
- **The Boolean atomic proposition is not replaced either** — it is *re-implemented*. The AP is still
  a bit; what changed is the function that produces the bit. Instead of
  `bit = (low_dim_state_variable ▷◁ threshold)` where the state variable comes from a bespoke
  detector, you get `bit = (distance_to_reference_embeddings ▷◁ threshold)` where the distance comes
  from an off-the-shelf encoder plus example images.
- **What is genuinely new at the semantic layer** is the robustness `ρ` (Def. 11), which surfaces the
  *margin* `ε − δ_ap(z_t)` — how far inside or outside the concept boundary the current frame is —
  and propagates it through `min`/`inf`/`sup`. Example 2 (p.5) is the whole idea in four numbers:
  distances `[0.327, 0.374, 0.403, 0.427]` against `ε = 0.409` give margins
  `[0.082, 0.035, 0.006, −0.019]`, so `ρ(G ap) = min = −0.019` — the specification is violated, and
  you can see it was violated *narrowly*, at the last step, as the object was grasped.
- **What replaces automaton acceptance:** also nothing, in the sense the reader might fear — but
  note that ETL as presented has **no automaton at all**. There is no NBA, no LTL3, no Spot. The
  monitor is a direct evaluation of the robustness expression over the prefix (Def. 10), i.e. an
  STL/RTAMT-shaped monitor, not an automaton-shaped one. That is an implementation choice the paper
  makes, not a consequence of embeddings.

### 3.3 Threshold calibration (§4, App. D, pp.6–7, 14–15)

`ε` is where all the risk lives: "Poorly chosen thresholds can lead to high false negatives (overly
strict predicates) or false positives (overly permissive predicates), making calibration essential"
(p.14). Two procedures, both requiring a labelled calibration set of trajectories:

**F1-optimal `ε_F1`** (Def. 16, p.15). Over calibration set `D_cal = {(d_t, y_t)}` with ground-truth
per-timestep labels `y_t`, predict `ŷ_t(ε) = 1[d_t ≤ ε]`, and take
`ε_F1 ∈ argmax_{ε ∈ {d_1,…,d_N}} F1(ε)`. Ties broken arbitrarily.

**Conformal `ε_CP` with a recall guarantee** (Def. 17 + Thm. 1, p.15). Two-stage, and the two stages
matter:
- *Within* each calibration demonstration `ς_i`, take the **hardest positive**:
  `score_i = max_t { d(z_t^{(i)}, z_g) : GT_ω(s_t^{(i)}) = 1 }`. "any threshold below `score_i` would
  fail to classify at least one ground-truth positive frame in that demonstration."
- *Across* demonstrations, sort the scores, set `k = ⌈(1−α)(n_cal + 1)⌉`, take `ε_CP = score_(k)`.

**Theorem 1 (Conformal Recall Guarantee).** Under exchangeability of calibration and test
demonstrations,
`P( ∀t : GT_ω(s_t) = 1 ⇒ d(z_t, z_ω) ≤ ε_CP ) ≥ 1 − α`.
"with probability at least 1 − α over a newly drawn test demonstration, the embedding predicate
achieves **perfect per-demonstration recall**, i.e., it detects every ground-truth positive timestep."
Proof is the standard split-conformal order-statistic argument. Note carefully what the guarantee is
*not*: it says nothing about precision, nothing about a single frame, and it holds per-demonstration
under exchangeability — a distribution shift breaks it.

---

## 4. Results

Compute: "two NVIDIA GeForce RTX 5090 GPUs, each with 34.2 GB of memory" (p.7).

### 4.1 Dubins car navigation, with privileged ground truth (§5.1, App. E)

Setup (p.7, p.16): discrete-time Dubins car, `s = [p_x, p_y, θ]`, `v = 1 m/s`,
`a_max = 1.25 rad/s`, `Δt = 0.05 s`; `N = 100` trajectories from a feedback controller with obstacle
avoidance; 40/60 calibration/test split; `α = 0.10`. Encoder: **the world-model encoder from
Agrawal et al. 2025 (AnySafe), based on Dreamer with a Recurrent State Space Model** — i.e. *not*
CLIP and *not* DINOv2 in this experiment. Goals: `A` top-right (`|p−(0.8,0.8)| < 0.25`), `B` top-left,
`C` obstacle proximity zone (`|p−(0.8,−0.8)| < 0.5`). Four patterns: Reach `FA`, Avoid `G¬C`,
Reach-Avoid `FA ∧ G¬C`, Sequential `F(A ∧ FB)`.

Table 1 (p.16):

| Spec | Scope | F1 (ε\*) | Prec (ε\*) | Rec (ε\*) | Agree (ε\*) | Prec (ε_CP) | Rec (ε_CP) | Agree (ε_CP) |
|---|---|---|---|---|---|---|---|---|
| Reach A | frames | 0.85 | 0.87 | 0.83 | 98.6% | 0.79 | 0.93 | 98.5% |
| Avoid C | frames | 0.80 | 0.69 | 0.94 | 96.5% | 0.70 | 0.92 | 96.5% |
| RA `A ∧ ¬C` | frames | 0.85 | 0.87 | 0.83 | 98.6% | 0.79 | 0.93 | 98.5% |
| Seq `A → B` | episodes | 1.00 | 1.00 | 1.00 | 100% | 1.00 | 1.00 | 100% |

Read this the way the numbers actually read: **frame-level F1 is 0.80–0.85 — not great — while
agreement is 96–99% and episode-level sequential accuracy is perfect.** Agreement is high mostly
because the predicate is false for most frames; the F1 column is the honest one. The calibration
trade-off works as advertised: `ε_CP` moves Reach recall 0.83 → 0.93 for precision 0.87 → 0.79.

### 4.2 Simulated manipulation (§5.2, Fig. 2b, pp.8–9)

Environments: D3IL `SORTING` and `STACKING` (Franka), MetaWorld `pick-place-wall` with sequential
grasp/place subgoals. Baselines are embedding-based failure detectors, not logic monitors:
**PCA-kmeans** (Liu et al. 2024) and **logpZO** (Xu et al. 2025, flow-matching density over
observation embeddings). Labels derived from simulator rewards and state variables. F1:

| Environment | ETL | PCA-kmeans | logpZO |
|---|---|---|---|
| STACKING | **0.897** | 0.852 | 0.844 |
| SORTING | **0.593** | 0.585 | 0.534 |
| MW-Pick-Place (grasp/place) | 0.961 | 0.815 | **0.992** |
| mean (paper's figure) | **0.817** | 0.751 | 0.790 |

ETL wins on average by ~0.03 over logpZO. `SORTING` is bad for everybody (0.53–0.59); the paper's
explanation is that "its OOD shifts induce more ambiguous changes in the embedding space." logpZO
beats ETL outright on MetaWorld. This is a competitive-not-dominant result and the paper says so.

### 4.3 Real-world DROID (§5.3, Fig. 2c, App. G)

Data: DROID manipulation episodes with multi-phase structure; ETL predicates instantiated per phase.
Baseline: **Qwen2-VL-2B**, prompted with the ground-truth desired behaviour and the phase frame,
answer distilled to a Boolean.

| Metric | ETL | Qwen2-VL-2B |
|---|---|---|
| Phase F1 | 0.780 | 0.390 |
| Phase agreement | 0.932 | 0.567 |
| Sequential correct | 0.800 (4/5 episodes) | 0.400 |

The body text on p.9 instead states "mean F1 score of 0.813 and mean agreement of 0.940" for ETL —
slightly different from the figure's 0.780 / 0.932. **I cannot reconcile the two from the retrieved
pages; treat ~0.78–0.81 as the figure and cite the figure, not the prose.**

Encoder here (App. G.3, p.18) is again **not** CLIP: the **SVD VAE from Ctrl-World**, a video
diffusion model trained on DROID, frames encoded to a `4×24×40` latent flattened to **3,840
dimensions**, with **cosine similarity** as the distance. The authors are explicit about why:
"This encoder is domain-matched to DROID and provides stronger geometric separation than
general-purpose encoders such as DINOv2."

**The appendix table the abstract does not mention.** Table 5 (App. G.4, p.18), "Sequential predicate
evaluation on DROID (SVD VAE, wrist camera)", 25 episodes with valid grasp-then-release, 10
calibration / 15 evaluation:

| Predicate | F1 | Precision | Recall | Agreement | Seq. Agreement |
|---|---|---|---|---|---|
| `π_hold` | 0.666 | 0.721 | 0.750 | 0.701 | 1.000 |
| `π_release` | 0.258 | 0.162 | 1.000 | 0.163 | — |

`π_release` has **precision 0.162**. The stated cause (p.19): "The release predicate exhibits low
precision due to visual ambiguity: the approach phase with an open gripper is visually similar to the
post-release phase." Sequential *ordering* is still correct in all episodes. This is the single most
useful number in the paper for anyone who wants to know how an embedding predicate fails: it fires
constantly, on frames that look right and are semantically wrong, while the *order* of events stays
recoverable. Whether Table 5 evaluates the same episode set as Fig. 2c is not stated in the retrieved
text — plausibly a different (harder) subset, but **not verified**.

---

## 5. Limitations

The authors' own list (§6, p.10) is two items:

1. "latent predicates are not yet fully interpretable in human-understandable terms";
2. "monitoring performance depends on whether task-relevant semantic concepts are well separated in
   the encoder's representation."

Failure-mode discussion (App. G.5, p.19): "Failure modes arise when embeddings corresponding to
different semantic states overlap in the latent space, which can result in delayed or premature
predicate activation near decision boundaries." Future work: transparent predicate explanations,
encoder selection/adaptation (they cite Concept Embedding Models), temporal abstraction over subtask
boundaries, adaptive online thresholding.

Limitations they do **not** foreground, which a careful reader should add:

3. **Calibration needs labelled ground truth.** `ε_F1` needs per-timestep labels; `ε_CP` needs
   demonstrations with known positive timesteps. The pitch is "no bespoke perception module", but
   the price is a labelled calibration set per predicate — the engineering did not vanish, it moved.
4. **`ε` is per-predicate, per-encoder, per-distance, per-environment.** Change the camera, the
   lighting, or the encoder checkpoint and every threshold is stale. There is no drift detection.
5. **Thm. 1 assumes exchangeability**, i.e. it guarantees nothing under exactly the distribution
   shift that runtime monitoring exists to catch.
6. **The `U` operator's robustness semantics is omitted** (p.14, "for brevity"), and the monitor is
   defined only over finite traces with a bound `b`. Anything genuinely infinite-horizon is out of scope.
7. **No latency or throughput numbers.** An encoder forward pass per frame per predicate is the cost
   model, and it is never measured — a notable gap for a paper whose complaint about the alternative
   is that it is "computationally expensive."
8. **Correctness is defined relative to a state-based monitor** (Def. 15). The evaluation therefore
   presupposes exactly the low-dimensional ground truth the method claims to make unnecessary. That
   is fine as a validation strategy but it is not evidence that ETL works where no ground truth exists.

---

## 6. For `skill_monitor`

### 6.1 Is `visually_at_goal` an instance of what this paper criticises?

**No — and the reason is more useful than a yes would have been. `visually_at_goal` is already an
ETL embedding predicate. It just has an uncalibrated threshold.**

Line up the definitions. `skill_monitor/specs/formulas_g1.json:12` defines

> `"visually_at_goal": "True when image_similarity_to_goal > 0.75. The current camera frame's embedding closely matches the curated reference photos of the goal location."`

and the score is a CLIP cosine similarity between the live frame and curated reference photographs.
Now Def. 5: `ap ≡ (Z_target, d, ε, ▷◁, a)`. The instantiation is exact, not analogical:

| ETL component | `visually_at_goal` |
|---|---|
| `Z_target` | CLIP embeddings of the curated goal reference photographs |
| `ψ_enc` | CLIP image encoder |
| `d` | cosine distance (App. A.2 recommends exactly this for contrastive encoders) |
| `a` | `max` over similarities ≡ `min` over distances — the paper's own Example 1 aggregator |
| `▷◁, ε` | `≤ 0.25` in distance, i.e. `> 0.75` in similarity |

So the paper's critique lands *elsewhere in the spec*. What it targets — "mapping continuous sensor
observations to discrete logical propositions defined over low-dimensional state variables" that
"require additional learned modules" — is `collision_risk` (`min_range < 0.25`, a lidar reduction),
and much more sharply the five APs that `RESUME.md:259` flags as reading the planner's self-report
(`mission_started`, `path_active`, `moving_towards_target`, `nav_stuck`, `mission_finished`). Those
are propositions over a low-dimensional variable produced by another module, and their brittleness
is exactly the brittleness this paper describes. `visually_at_goal` is the one AP in the spec that is
already doing what this paper recommends.

**So what *is* lost by thresholding the CLIP similarity into a bit? Three specific things, all of
which this paper names, and none of which is "you shouldn't have thresholded."**

1. **The margin.** `δ_ap(z_t) = 0.24` and `δ_ap(z_t) = 0.001` are the same bit and completely
   different situations. Def. 11's `ρ(ap) = ε − δ_ap(z_t)` is precisely this quantity, and Example 2
   on p.5 is a worked case where the violation is `−0.019` — a hair outside the boundary. A monitor
   that reports only the bit cannot distinguish "arrived" from "barely arrived", and cannot tell an
   operator that a verdict was a coin flip.
2. **Which reference matched.** With `a = min`, `argmin` is free and is the single most auditable
   artefact available — "the monitor called goal-reached because the frame was 0.19 from reference
   photo #3 (the one taken from the north approach)". Collapsing to a bit throws away the `argmin`.
3. **Any principled basis for `0.75`.** This is the exposed one. `0.75` is a hand-picked constant.
   §4 exists because these authors think that is not good enough: `ε_F1` is fit to maximise F1
   against labelled data, and `ε_CP` buys a distribution-free per-demonstration recall guarantee
   (Thm. 1). The reader has no calibration set, no labels, no guarantee, and — per `RESUME.md:593`
   — has already been bitten once by this exact threshold, when a truncating regex turned
   `image_similarity_to_goal > 0.75` into `> 0` and the AP fired almost immediately. The bug is
   fixed and regression-tested (`tests/test_spec_contract.py:35`), but the deeper point stands:
   there is currently nothing in the system that would notice if `0.75` were simply the wrong number.

**Write this limitation yourself. Suggested wording, in the reader's own voice:**

> `visually_at_goal` thresholds a CLIP cosine similarity at a hand-chosen 0.75. This is an
> embedding-space predicate in the sense of Kapoor et al. [embeddingtl2026], but without their
> calibration: we neither fit the threshold against labelled trajectories nor derive it with a
> conformal recall guarantee, and the monitor consumes only the resulting bit, discarding the margin
> `0.75 − s_t` and the identity of the nearest reference image. We report the scalar and the nearest
> reference in the audit log, but the automaton does not see them. Calibrating this threshold on
> recorded G1 episodes is the obvious next step and we have not done it.

A reviewer who knows this paper will otherwise write that paragraph for you, and less kindly.

### 6.2 What do they do instead, and can it be retrofitted?

**Retrofit cost: low for the Boolean part; the automaton does not change at all.**

ETL's syntax is LTL, its satisfaction relation is LTL's, and its APs are Boolean atoms. Nothing about
`spot.translate()` or the `MonitorStatus`/LTL3 machinery in `core/automata.py` is disturbed. Adopting
ETL's *predicate discipline* means changing the AP evaluator and adding an offline calibration step:

- **Free today.** Log `δ_ap(z_t)`, the threshold, the margin, and `argmin` over the reference set
  alongside the bit. Zero change to the automaton; large change to what an operator can see. This is
  the highest-value, lowest-risk thing in this entire summary.
- **Cheap, and it needs the recording you were already going to make.** `RESUME.md:250–265` says the
  next real work is "run as-is, record it with `replay_node record`, calibrate P12 off the
  recording." That recording is also a calibration set for `ε`. If you label goal-reached frames in
  the recorded G1 episodes, `ε_F1` (Def. 16) is a one-line grid search over observed distances, and
  `ε_CP` (Def. 17) is a sort and an order statistic — `k = ⌈(1−α)(n+1)⌉` with `α = 0.10` as in the
  paper. That converts "0.75 because it looked right" into "0.79, calibrated on 40 recorded episodes,
  with ≥90% per-episode recall under exchangeability." This is a real, citable, cheap methodological
  upgrade and it is the strongest thing to take from this paper.
- **Not retrofittable into a Büchi/LTL3 monitor: the robustness semantics.** Def. 11 is STL-shaped —
  `inf`/`sup` over a bounded window `[i, b]`, evaluated as an expression, not consumed by an
  automaton. Quantitative ETL is a different monitoring substrate, and the reader already has the
  right tool queued for it: `papers/rtamt/` (RTAMT). Do **not** try to push real-valued robustness
  through Spot. If quantitative verdicts are ever wanted, that is a second monitor running beside the
  automaton, not a modification of it.
- **Genuinely out of scope.** Replacing curated reference photos with a general "specify by example"
  workflow, or swapping CLIP for a domain-matched world-model latent. Note that the paper's two
  strongest results used **neither CLIP nor DINOv2** — the Dubins experiment used a Dreamer/RSSM
  world-model encoder, and DROID used a domain-matched SVD VAE that the authors say beats DINOv2 on
  geometric separation. Off-the-shelf CLIP is the weakest instantiation of their own recipe. That is
  a limitation to concede, not a reason to change encoders before ICRA.

### 6.3 Is there a defensible middle position?

**Yes, and this paper hands it to you — including from its own limitations section.**

Auditability is the reader's stated requirement: an operator must be able to see why the monitor
decided the robot was at the goal. ETL does *not* trade that away, but it does not fully deliver it
either. On the plus side, ETL's targets are **reference images**, so the specification artefact an
operator inspects is a picture, not a vector (App. A.1), and the paper's own figures (Fig. 1 bottom
right, Fig. 3 on p.18) are distance-to-target time series with the threshold drawn on them — a
directly auditable object. App. G.5 even claims "embedding distances provide a reliable and
interpretable signal." On the minus side, the authors' own first limitation is that "latent
predicates are not yet fully interpretable in human-understandable terms" (p.10), and Table 5's
`π_release` precision of 0.162 shows what that costs: the predicate fires on frames a human would
call wrong, and nothing in the embedding distance explains why.

**The defensible middle position, which is what `skill_monitor` should actually implement:**

> Keep the Boolean AP as the automaton's input — an auditable monitor needs a discrete verdict, a
> discrete transition, and a discrete trace to replay. Move everything ETL adds into the *evidence*
> record rather than the *decision* record: log the similarity, the threshold, the signed margin, and
> the nearest reference photograph for every step where `visually_at_goal` is evaluated. Calibrate
> the threshold from recorded episodes instead of choosing it. The operator then sees a picture, a
> number, and a distance to the boundary; the automaton still sees one bit; and the verdict remains
> exactly reproducible from the log.

That position is *stronger* than full ETL on auditability, not weaker, and it should be argued that
way rather than defensively. The strongest honest defence of thresholding is: a Boolean AP makes the
monitor's decision procedure inspectable, deterministic and replayable, and it is the only form in
which an ω-automaton verdict is meaningful; the continuous score is retained as evidence, so nothing
is destroyed, only kept out of the decision path. The strongest honest concession is: the threshold
is uncalibrated, it is encoder- and environment-specific, and this paper shows how to fix that with
data the reader is about to collect anyway.

### 6.4 Where to cite it

**Three places, in priority order. The first is not optional.**

**(1) At the `visually_at_goal` AP** — in the method section where the AP set is introduced. This is
the sentence that pre-empts the reviewer:

> `visually_at_goal` is an embedding-space proposition in the sense of Embedding Temporal Logic
> [embeddingtl2026]: it thresholds the cosine distance between the current frame's CLIP embedding and
> a curated set of goal reference images, which is exactly their predicate form
> `(Z_target, d, ε, ▷◁, a)` with `a = min` — but we fix `ε` by hand rather than calibrating it.

**(2) In limitations** — the paragraph drafted in §6.1 above. The load-bearing clause is the one
naming what they offer and you did not use:

> …unlike Kapoor et al. [embeddingtl2026], we neither fit this threshold to labelled trajectories nor
> derive it via split conformal prediction, so `visually_at_goal` carries no recall guarantee and no
> evidence that 0.75 is the right operating point for this camera and this goal set.

**(3) In related work**, as the closest published system and the sharpest framing of what a monitor
loses when perception is squeezed through a hand-built proposition:

> Kapoor et al. [embeddingtl2026] argue that mapping continuous observations to propositions over
> low-dimensional state variables "requires additional learned modules that are often computationally
> expensive, brittle, and semantically misaligned", and instead define LTL predicates directly as
> thresholded distances to reference-image embeddings, calibrated by split conformal prediction. Their
> monitor is a bounded-horizon robustness evaluator over embedding traces; ours is an automaton over
> Boolean APs, of which one — `visually_at_goal` — is an uncalibrated instance of their predicate form.

**Bonus, cheap, and it strengthens an argument you already need to make.** `papers/README.md` names
`foresight/` and `failsafe/` as the "contrast class" answering "VLMs detect robot failures now, why do
I need a spec?", and says the answer should argue interpretability and zero training data, "*not*
accuracy, which is not a fight worth picking." This paper picks that fight and wins it: §5.3 reports
ETL at 0.780 phase F1 / 0.932 agreement against Qwen2-VL-2B at 0.390 / 0.567, with ETL "markedly more
reliable overall, especially on phases that are visually similar but semantically distinct" (p.9).
That is a citable third-party data point that a specification-based monitor can beat a VLM monitor on
accuracy — worth one sentence in the contrast-class paragraph, still without staking your own claim
on accuracy.

---

## 7. Check yourself

**Q1. ETL is proposed as an alternative to "mapping continuous sensor observations to discrete
logical propositions." Does an ETL predicate produce a continuous value or a discrete one, and what
exactly is the abstraction being replaced?**

Discrete. `δ_ap(z) ▷◁ ε` is a Boolean (Def. 6), and Def. 8's satisfaction relation is plain LTL. What
ETL replaces is not the Boolean-ization — it is the *intermediate low-dimensional state variable and
the bespoke detector/classifier/estimator that produces it*. The predicate is redefined as a
thresholded distance to reference-image embeddings, so the perception module disappears and the
threshold survives. Anyone who reads the abstract as "stop thresholding" has misread it; the correct
reading is "stop building a detector just so you have something to threshold."

**Q2. `ε_CP` guarantees what, over what, under what assumption — and what does it not guarantee?**

Theorem 1 (p.15): under exchangeability of calibration and test demonstrations, with probability at
least `1 − α` over a newly drawn test demonstration, *every* ground-truth-positive timestep in that
demonstration satisfies `d(z_t, z_ω) ≤ ε_CP` — i.e. perfect **per-demonstration recall**. It is a
recall guarantee, per demonstration, not per frame. It says **nothing about precision** (empirically
Reach precision drops 0.87 → 0.79 when switching from `ε_F1` to `ε_CP`), and it is void under
distribution shift, which is precisely the regime runtime monitoring is for.

**Q3. Which encoders were actually used in the experiments, and why does that matter for anyone
planning to build ETL predicates on CLIP?**

Not CLIP. The Dubins experiment used the world-model encoder from Agrawal et al. 2025, based on
Dreamer with an RSSM (p.7, p.16); DROID used the SVD VAE from Ctrl-World, a 3,840-dim latent with
cosine distance, which the authors state is "domain-matched to DROID and provides stronger geometric
separation than general-purpose encoders such as DINOv2" (App. G.3, p.18). CLIP and DINOv2 are cited
in related work as motivation for the *idea* (p.3), not used as the evaluated encoders. The
implication: the paper's numbers are evidence for domain-matched or temporally-aware latents, and are
*not* evidence that an off-the-shelf CLIP predicate performs at 0.8 F1. A `visually_at_goal` built on
stock CLIP is running the weakest version of their recipe, and should be described that way.

**Q4. Retrofitting ETL into `skill_monitor`: what would have to change in `core/automata.py`, and
which part of the paper genuinely cannot be retrofitted?**

Nothing in `core/automata.py`. ETL's syntax is LTL and its APs are Boolean atoms, so `spot.translate()`
and the LTL3 `MonitorStatus` machinery are untouched; the change is confined to the AP evaluator
(compute distance to reference embeddings, compare to `ε`) plus a new offline calibration step over
recorded episodes. What cannot be retrofitted is the **robustness semantics** (Def. 11): it is
STL-shaped, with `inf`/`sup` over a bounded window `[i, b]`, evaluated as an expression rather than
consumed by an automaton, and the `U` case is not even given in the paper. Real-valued robustness
needs a second monitoring substrate — RTAMT (`papers/rtamt/`) — running beside the automaton, not a
modification of it.

---

## Verification notes

**Verified from the PDF via `mcp__alphaXiv__answer_pdf_queries` (paper `2605.12651`):** title, the
full author list and affiliations (p.1), the arXiv stamp `arXiv:2605.12651v1 [cs.LG] 12 May 2026`,
the abstract, all definitions and theorem statements quoted above with their numbers, Table 1 (p.16),
Table 5 (p.18), Figure 2b/2c values (p.8), the compute description (p.7), the artifacts URL (p.7
footnote), and the limitations paragraph (p.10).

**Not verified:** the arXiv abstract page was not fetched, so cross-listed categories, the page-count
/ comments field, and any v2 revision are unconfirmed. No venue is stated — every page header reads
"Preprint." The artifacts repository `github.com/ETLMonitoringAuthors/ETLMonitoring` is an anonymised
handle and was not fetched; whether it resolves, and whether it has since been de-anonymised, is
unknown. The `0.780` (Fig. 2c) vs `0.813` (p.9 prose) DROID F1 discrepancy is unreconciled. Whether
Table 5's grasp/release episodes are a subset of, or disjoint from, the five phasic episodes in
Fig. 2c is not stated in the retrieved text. Exact ablation numbers for encoder and distance-function
choices were not located in the retrieved pages, though §5 and App. A.2 say the effect is studied.
