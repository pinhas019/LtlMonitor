# Foresight: Failure Detection for Long-Horizon Robotic Manipulation with Action-Conditioned World Model Latents

Haoran Zhang¹\*, Yifu Lu²\*, Boyang Wang³, Xuhui Kang³, Yen-Ling Kuo³, Zezhou Cheng³,
Mengdi Wang², Odest Chadwicke Jenkins¹†
¹ University of Michigan · ² Princeton University · ³ University of Virginia
\* equal contribution · † corresponding author

arXiv:2606.23085v1 [cs.RO], 22 June 2026. Project page printed on the title page as
`Foresight.github.io`.
**Venue: not verified.** The PDF uses the "Abstract: … Keywords:" title-page template
associated with CoRL, but no venue line appears anywhere in the pages read. Cite as an
arXiv preprint until confirmed (see `bibtex.md`).

All quotations below are exact, with the PDF page number of the arXiv v1 preprint.
Anything read off a figure rather than a table or the prose is flagged "not verified".

---

## 1. In one paragraph

Foresight is a runtime failure detector for long-horizon robot manipulation that watches a
policy's rollout from the outside. At each replanning step it feeds the recent camera
frames *and the policy's next predicted action chunk* into a frozen V-JEPA 2 visual
encoder plus a trained action-conditioned predictor, takes the predicted future latent
`z^p_t` (1408-d), and streams the sequence of those latents through a small causal
Transformer that emits a per-timestep failure score `s_t ∈ [0,1]`. Functional conformal
prediction on held-out *successful* rollouts turns the score into a time-varying band
`δ_t = μ_t + q̂σ_t`; the first step where `s_t ≥ δ_t` raises a binary alarm. The design
premise is that a still image is not enough — "the meaning of a visual state depends on
the action history and task stage… The same object resting on a table may be expected
before a grasp, evidence of a missed grasp after a lift command, or correct after a
placement action" (p. 1) — so the detector should judge whether the observed trajectory is
consistent with the progress implied by the robot's own commanded actions. Training needs
only trajectory-level success/failure labels, no per-timestep failure annotation and no
access to policy internals (no logits, hidden states, or uncertainty head). Evaluated on
LIBERO-Long, ManiSkill-Long, BEHAVIOR-1K (rollouts averaging 8,557 simulator steps) and
four real-robot settings, the Transformer variant gets the best balanced accuracy on all
three simulation benchmarks and the best ROC-AUC in three of four real settings.

---

## 2. Key concepts

**World-model latent.** A vector produced by a video model trained to predict future
*representations* rather than future pixels. Foresight uses V-JEPA 2-AC (Assran et al.,
arXiv:2506.09985), checkpoint `vjepa2-ac-vitg.pt`, ViT-Giant encoder. Images at 256×256,
patch 16×16, tubelet 2 → 256 spatial patch tokens per frame; tokens mean-pooled to a
**1408-dimensional** vector per frame (Appendix 7, p. 13).

**Action-conditioning.** The distinction the paper's whole argument rests on. Two latents
exist at every step (§4.2, p. 4):

- `z^h_t = Pool(f_φ(c_t))` — the **hidden latent**, "what is currently observed".
- `z^p_t = Pool(g_ψ(z^h_t, A_t))` — the **predicted latent**, "what the world model expects
  to happen under the policy's next action chunk".

Foresight feeds `z^p_t`. The justification is explicitly about mismatch, not anomaly:
"many robot failures are not visually anomalous in isolation; they are mismatches between
the intended action and the observed state transition" (Appendix 12.2, p. 23).

**Failure-detection formulation (§3, p. 3).** Not classification and not anomaly scoring —
a **scoring function** over prefixes:

> `D_θ : {(c_i, A_i)}^t_{i=1} = s_t`, with `s_t ∈ [0,1]` the predicted failure score at
> timestep t (Eq. 3), and `ŷ_t = 1` iff `s_t ≥ δ_t` (Eq. 4).

Labels are trajectory-level binary only: `y = 1` if the robot fails to complete the task
(Eq. 2). "We assume access only to trajectory-level success or failure labels, without
annotations of the precise timestep at which a failure occurs" (p. 3). The target is the
*eventual* outcome: "predict whether the ongoing rollout will eventually fail using only
information available before executing the next action chunk" (p. 3).

**Long-horizon.** Defined by subgoal count, not wall time: "we define long-horizon tasks
as those requiring multiple subgoals, typically involving multiple symbolic manipulation
actions such as pick, place, open, and close" (§3, p. 3). Empirically: 253 average
simulator steps (LIBERO-Long) → 1,484 (ManiSkill-Long) → 8,557 (BEHAVIOR-1K), with the
longest BEHAVIOR-1K task, `setting_mousetraps`, at 13,657 steps (Tables 1 and 10).

**Functional conformal prediction (FCP).** A distribution-free calibration that produces a
*time-varying* threshold band rather than one constant. Construction (Appendix 9, p. 14):
`μ_t` is the mean score trajectory over `n` successful calibration rollouts, `σ_t` a
time-varying modulation term, `R_i = sup_t (s^(i)_t − μ_t)/σ_t` the normalised
nonconformity score, `q̂` the (1−α)-quantile of `{R_i}`, and `δ_t = μ_t + q̂σ_t`. Under
exchangeability this "guarantees that the false positive rate, i.e., the probability of
flagging a truly successful rollout as a failure at any point during execution, is
controlled at level α" (p. 5).

**Policy-interface-agnostic.** Foresight "does not require policy logits, hidden states,
token probabilities, or access to a policy-specific uncertainty head; it only uses the
rollout interface of visual observations and the corresponding action chunks" (p. 2). Note
the scope of the claim carefully — it is agnostic to the *policy*, not to the dataset:
"the same framework can be applied to different vision-language-action (VLA) and
visuomotor policies **once the dataset-specific AC predictor and detector are trained**"
(p. 2, emphasis added).

---

## 3. Method, concretely

Three stages (Fig. 1, p. 4).

**Stage 1 — fine-tune the action-conditioned world model.** The V-JEPA 2 visual encoder is
**frozen throughout**; the action-conditioned predictor is **trained from scratch** on the
rollouts of the benchmark in question. Predictor: 24 transformer layers, embedding dim
1024, 16 attention heads, `pred_is_frame_causal=True`. Observation context is a sliding
window of 8 non-overlapping frames. Action dimensionality is per-embodiment: 7D (LIBERO,
real ACT/π₀.₅), 8D (ManiSkill-Long), 10D (real Franka), 23D (BEHAVIOR-1K R1Pro). Loss is
V-JEPA 2-AC's combined teacher-forcing plus 2-step autoregressive-rollout L1 on
LayerNorm-normalised representations, `L = L_TF + L_AR`. AdamW, weight decay 0.04, 10-epoch
linear warmup, cosine to 0, **200 epochs**, on 1–2 H200 GPUs (Appendix 7, p. 13).

**Stage 2 — train the failure scorer.** Token `u_t = W z^p_t + p_t` with fixed sinusoidal
positional encoding (Eq. 7). The causal Transformer: linear projection to 256, 2 pre-norm
`TransformerEncoder` layers, 4 heads, feedforward 1024, dropout 0.1, causal attention mask
so "the score at timestep t depends only on features up to and including t", then
`Linear → Sigmoid`. 300 epochs, batch 512, Adam lr 1e-4, ℓ₂ 1e-2. MLP and LSTM variants
share the hyperparameters (Appendix 7, p. 13).

Supervision detail worth holding onto: "Since failure timestamps are not annotated, each
timestep inherits the rollout-level label, with early-detection weighting applied to
encourage high scores before or during failure events" (§4.3, p. 5). **The
early-detection weighting scheme is named but never defined in the pages read** — no
formula, no hyperparameter, no ablation on it. Not verified.

**Stage 3 — calibrate and deploy.** FCP as above. α is *selected*, not fixed a priori:
swept over `{0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70,
0.80, 0.90}` and "selected per method and benchmark by maximizing balanced accuracy
aggregated across three cross-validation folds" (Appendix 9, p. 14).

**Splits.** 3-fold CV over *rollouts*. Within each round the two non-test folds split
6:1:1 into train / validation / calibration for the detector. "For the AC predictor,
however, we use all non-test data available in each round… We assume the AC predictor has
full access to all data except the held-out test set" (Appendix 8, p. 13).

**Data volume** (Appendix 11):

| Benchmark | Tasks | Rollouts | Embodiment | Avg. sim steps |
|---|---|---|---|---|
| LIBERO-Long | 10 | 50/task = **500 per policy**, ×2 policies | Franka | 253 |
| ManiSkill-Long | 4 | **319** total | Franka | 1,484 |
| BEHAVIOR-1K | 4 | 100/task = **400** | R1Pro | 8,557 |
| Real ReactorX / ACT | 3 | 40/task = **120** | ReactorX-200 | ~1,155 |
| Real ReactorX / π₀.₅ | 3 | 40/task = **120** | ReactorX-200 | ~1,189 |
| Real ReactorX / SmolVLA | 3 | 40/task = **120** | ReactorX-200 | ~1,191 |
| Real Franka / GR00T N1.5 | 1 | **44** | Franka | ~1,727 |

Summing these gives ≈2,120 rollouts across the paper — *my arithmetic, not a figure the
paper states*. BEHAVIOR-1K collection is deliberately balanced: "Rollouts were collected
targeting 50 successes and 50 failures per task for Foresight training" (p. 20).

---

## 4. Results

**Metrics (§5.3, p. 6).** Both are **rollout-level**, not per-step.
*ROC-AUC*: the per-step scores are collapsed by `s̄ = max_t s_t` (Eq. 11) and AUC computed
on that single number per rollout — threshold-independent separability.
*Balanced accuracy*: `½(TPR + TNR)` after calibration at the tuned α — threshold-dependent
classification. Both answer "was this rollout a failure?", **neither answers "when?" or
"why?"**.

**Table 2 (p. 8) — simulation, mean ± std over 3 folds.**

| Method | LIBERO AUC | LIBERO BalAcc | ManiSkill AUC | ManiSkill BalAcc | BEHAVIOR AUC | BEHAVIOR BalAcc |
|---|---|---|---|---|---|---|
| FAIL-Detect | 0.90 ± 0.02 | 0.82 ± 0.06 | 0.71 ± 0.02 | 0.50 ± 0.01 | 0.54 ± 0.06 | 0.52 ± 0.01 |
| SAFE-MLP | 0.52 ± 0.01 | 0.50 ± 0.01 | 0.61 ± 0.02 | 0.53 ± 0.02 | 0.50 ± 0.00 | 0.50 ± 0.00 |
| SAFE-LSTM | **0.91 ± 0.02** | 0.88 ± 0.02 | 0.82 ± 0.01 | 0.74 ± 0.01 | 0.72 ± 0.02 | 0.64 ± 0.05 |
| RND | 0.90 ± 0.02 | 0.83 ± 0.04 | 0.83 ± 0.02 | 0.68 ± 0.18 | 0.65 ± 0.01 | 0.54 ± 0.04 |
| Gauge | 0.88 ± 0.01 | 0.81 ± 0.06 | 0.80 ± 0.02 | 0.77 ± 0.03 | 0.61 ± 0.03 | 0.60 ± 0.03 |
| Foresight-MLP | 0.88 ± 0.01 | 0.80 ± 0.02 | 0.70 ± 0.03 | 0.71 ± 0.18 | 0.73 ± 0.02 | 0.56 ± 0.03 |
| Foresight-LSTM | 0.86 ± 0.02 | 0.89 ± 0.03 | 0.76 ± 0.00 | 0.79 ± 0.16 | 0.75 ± 0.04 | 0.75 ± 0.09 |
| **Foresight-Transformer** | 0.89 ± 0.02 | **0.94 ± 0.06** | **0.84 ± 0.03** | **0.80 ± 0.10** | **0.76 ± 0.02** | **0.78 ± 0.02** |

Read honestly: Foresight-Transformer wins balanced accuracy everywhere, but on
LIBERO-Long **SAFE-LSTM has the higher ROC-AUC** (0.91 vs 0.89). The paper's own headline
is about the hardest benchmark: on BEHAVIOR-1K "the best non-Foresight baseline reaches
0.72 ± 0.02 ROC-AUC and 0.64 ± 0.05 balanced accuracy, whereas Foresight-Transformer
reaches 0.76 ± 0.02 and 0.78 ± 0.02" — a stated 0.14 BalAcc and 0.04 AUC improvement
(p. 7). Absolute numbers there are modest: 0.76 AUC on the flagship benchmark.

**Table 3 (p. 8) — real robots, ROC-AUC.**

| Method | ReactorX/ACT | ReactorX/π₀.₅ | ReactorX/SmolVLA | Franka/GR00T N1.5 |
|---|---|---|---|---|
| FAIL-Detect | 0.85 ± 0.07 | 0.64 ± 0.06 | 0.71 ± 0.05 | 0.88 ± 0.05 |
| SAFE-MLP | 0.89 ± 0.05 | 0.66 ± 0.36 | 0.64 ± 0.19 | 0.50 ± 0.10 |
| SAFE-LSTM | 0.70 ± 0.07 | 0.75 ± 0.14 | 0.43 ± 0.10 | 0.79 ± 0.10 |
| RND | 0.86 ± 0.04 | 0.78 ± 0.06 | **0.82 ± 0.03** | 0.64 ± 0.15 |
| Foresight-MLP | 0.50 ± 0.00 | 0.55 ± 0.05 | 0.53 ± 0.22 | 0.59 ± 0.20 |
| Foresight-LSTM | 0.85 ± 0.05 | 0.85 ± 0.03 | 0.64 ± 0.08 | 0.66 ± 0.08 |
| **Foresight-Transformer** | **0.93 ± 0.01** | **0.87 ± 0.03** | 0.79 ± 0.09 | **0.89 ± 0.10** |

RND beats Foresight on ReactorX/SmolVLA. Foresight-MLP is at chance (0.50–0.59)
everywhere in the real world — the paper's own conclusion is that "robust rollout
monitoring requires sequence-level detectors rather than independent frame-level
classification" (p. 7).

**Table 4 (p. 8) — cross-policy transfer.** The only generalisation experiment in the
paper, and it is *across policies*, not across tasks:

| Benchmark | Train → Test | ROC-AUC | BalAcc |
|---|---|---|---|
| LIBERO-Long | π₀-FAST → OpenVLA | 0.64 ± 0.02 | 0.90 ± 0.01 |
| Real | π₀.₅ → ACT | 0.94 ± 0.02 | 0.82 ± 0.08 |
| Real | ACT → π₀.₅ | **0.56 ± 0.07** | **0.52 ± 0.03** |
| Real | SmolVLA → ACT | 0.92 ± 0.04 | 0.73 ± 0.07 |
| Real | π₀.₅ → SmolVLA | 0.67 ± 0.02 | 0.62 ± 0.01 |

Transfer is "policy-dependent and can be asymmetric": ACT → π₀.₅ collapses to chance
(0.56 / 0.52). The offered explanation is behavioural coverage — π₀.₅ produces recovery
trajectories that an ACT-trained detector has never seen and "may misclassify… as failure"
(p. 8). That is an important admission: the detector's notion of failure is a learned
description of one policy's rollout distribution, so a *legitimate recovery* can read as a
failure.

**Table 12 (p. 22) — backbone ablation, LIBERO-Long ROC-AUC.** Cosmos-Predict2.5-2B
robot-AC 0.85 / 0.85 / 0.84 vs V-JEPA 2-AC 0.88 / 0.86 / 0.89 (MLP / LSTM / Transformer).
The explanation: "failure detection does not require pixel-level details which are hard to
predict, but requires representations for predictable aspects of a scene" (p. 22).

**Table 13 (p. 23) — the action-conditioning ablation, `z^h` vs `z^p`, ROC-AUC.**

| Benchmark | `z^h` MLP / LSTM / Trans. | `z^p` MLP / LSTM / Trans. |
|---|---|---|
| LIBERO-Long | 0.77 / 0.83 / 0.85 | 0.88 / 0.86 / **0.89** |
| ManiSkill-Long | 0.74 / **0.78** / 0.81 | **0.70** / 0.76 / **0.83** |

Worth noticing and the paper does not comment on it: on ManiSkill-Long the *hidden* latent
beats the predicted latent for both MLP (0.74 vs 0.70) and LSTM (0.78 vs 0.76). Action
conditioning wins cleanly on LIBERO-Long and only via the Transformer on ManiSkill-Long.
The ablation supports the paper's central claim but not unconditionally.

**Table 5 (p. 14) — selected α.** The Foresight-Transformer operating points are α = 0.02
(LIBERO), 0.02 (ManiSkill), **0.20** (BEHAVIOR-1K). Gauge's best BEHAVIOR-1K α is also
0.20. So the flagship BEHAVIOR-1K number is obtained at a nominal 20% false-alarm level.

**Table 6 (p. 15) — what each method is allowed to use.** The row that matters:

| Method | Input signal | Uses failures for training? | Uses policy internals? |
|---|---|---|---|
| Gauge | World-model video latents | No | No |
| **Foresight** | Action-conditioned world-model latents | **Yes** | No |

Foresight needs *labelled failure rollouts*. FAIL-Detect, RND and Gauge do not.

---

## 5. Limitations

**Admitted (p. 9), two:**
1. "A key limitation is the computational cost and latency of pretrained world models,
   which makes on-device deployment challenging and may limit applicability to highly
   reactive or agile tasks requiring fast closed-loop control."
2. "while conformal calibration helps control false alarms under held-out successful
   rollouts, its guarantees depend on the calibration distribution matching deployment
   conditions."

**Unadmitted, each checked against the text rather than assumed:**

- **There is no held-out-*task* experiment anywhere in the paper.** BEHAVIOR-1K Table 10
  states plainly "All 4 tasks are seen (3-fold cross-validation)", and the split protocol
  (Appendix 8) shuffles *rollouts*, not tasks. LIBERO-Long, ManiSkill-Long and the
  real-world benchmarks use the same rollout-level 3-fold protocol. Table 4 generalises
  across *policies*; nothing generalises across tasks. So the paper's evidence for
  transfer to an unseen task is: **none**.
- **"Cross-embodiment generalization" is retraining, not zero-shot.** The Franka /
  GR00T N1.5 setting is described as assessing cross-embodiment generalisation (p. 6), but
  the AC predictor's action dimensionality is embodiment-specific (7/8/10/23-D, Appendix
  7) and is trained per benchmark. The honest reading is "the method works on a second
  embodiment after retraining on that embodiment's rollouts," not "a detector trained on
  ReactorX transfers to Franka."
- **No detection-time or lead-time metric is reported.** The paper motivates itself by
  "recognize… when an ongoing execution has drifted toward failure" (p. 1) and adds
  "early-detection weighting" to the loss (p. 5), but both metrics collapse the trajectory
  — ROC-AUC on `max_t s_t`, balanced accuracy on the resulting rollout label. How many
  steps before failure the alarm fires is not measured in any table in the pages read.
  Not verified either way; simply absent.
- **The early-detection weighting is never specified.** Named once (p. 5), no formula, no
  ablation.
- **Label noise from timestep inheritance is unmeasured.** Every step of a failed rollout
  is labelled failure, including the steps before anything went wrong. The paper states
  the design but does not quantify what it costs.
- **α is tuned on outcome data, which softens the conformal story.** FCP's appeal is a
  distribution-free FPR guarantee at level α; here α is chosen by maximising balanced
  accuracy across CV folds (Appendix 9, p. 14). The guarantee still holds conditional on a
  given α, but the reported operating point is selected using failure labels, so the
  headline balanced accuracies are not free of threshold tuning.
- **No runtime numbers.** Latency is named as *the* key limitation, yet no ms/step, FPS,
  or memory figure appears in the pages read — despite a ViT-Giant encoder plus a 24-layer
  predictor running at every replanning step. Not verified.
- **Real-world variance is large.** ±0.10 (ManiSkill BalAcc), ±0.16 (ManiSkill
  Foresight-LSTM BalAcc), ±0.18 (Foresight-MLP), ±0.10 on the Franka AUC over 44 episodes.
  Several of the head-to-head wins are inside one standard deviation of the runner-up.
- **The output space was deliberately narrowed.** Gauge, the world-model baseline,
  natively classifies into success / known failure / OOD anomaly; Foresight's protocol
  adapts it "by collapsing all non-success outputs into failures" (p. 6). Foresight itself
  has no multi-class output to collapse.

---

## 6. For `skill_monitor` — the contrast paragraph

### 6.1 What exactly does Foresight detect, and what does it need?

**Detects:** that the *current rollout will eventually fail*. Nothing more specific. The
formulation (§3) is a scoring function over prefixes producing a scalar, and the decision
rule is a single binary alarm at the first threshold crossing.

**Output:** a scalar `s_t ∈ [0,1]` per timestep, plus a binary `ŷ_t`. Not a class, not a
failure name, not a phase, not a time-to-failure estimate. For evaluation even the
per-step scores are discarded: `s̄ = max_t s_t`.

**Training data:** per benchmark, hundreds of rollouts *including labelled failures* —
500 per policy on LIBERO-Long, 319 on ManiSkill-Long, 400 on BEHAVIOR-1K deliberately
balanced 50/50 success/failure, 404 across the real-robot settings. Plus an
action-conditioned predictor trained from scratch for 200 epochs on 1–2 H200 GPUs per
benchmark, and a detector for 300 more epochs.

**Task specificity:** the framework is policy-agnostic but **dataset-specific** by the
paper's own wording (p. 2). Every reported number comes from a detector trained on
rollouts of the same tasks it is tested on.

**Transfer:** across policies, demonstrated and asymmetric (0.94 one direction, 0.56 the
other). Across tasks, **not evaluated**. Across embodiments, only by retraining.

**Interpretability:** the output is a number. No explanation mechanism, no attention
visualisation, no language rationale, no attribution to a named cause is reported. The
qualitative appendix figures (Figs. 13–15, p. 26) show the score curve crossing the
threshold band with captions like "The robot fails during this task because it did not
grasp the first hot dog" — but that sentence is *the authors' annotation of the video*,
not an output of the detector. The detector emitted a number that went up.

### 6.2 What does it NOT give you? (each candidate checked, not assumed)

| Claim the reader wants to make | Verdict | Evidence |
|---|---|---|
| Does not **name** the failure | **Confirmed.** Binary only. | Eq. 2 is a binary label; Eq. 4 a binary alarm. Gauge's three-way output is explicitly collapsed to binary for comparison (p. 6). |
| Does not report **where in the task** the robot is | **Confirmed.** No phase, subtask, or progress output. | Task stage is an argued *motivation* ("the meaning of a visual state depends on the action history and task stage", p. 1) that the architecture absorbs implicitly into `z^p_t` and the causal attention. Nothing in the output exposes it. |
| A human **cannot audit** why it fired | **Confirmed, with a caveat.** No explanation mechanism is described. The caveat: it is *not* a black box in every sense — the threshold band has a stated statistical meaning (FPR ≤ α under exchangeability), so you can audit the *false-alarm rate*. You cannot audit an *individual* alarm. | §4.4 and Appendix 9 give the calibration; no section gives per-alarm attribution. |
| Needs **per-task / per-robot training** | **Per-dataset and per-embodiment: confirmed. Per-policy: no — that is its selling point.** | "once the dataset-specific AC predictor and detector are trained" (p. 2); action dims 7/8/10/23-D per embodiment (p. 13); no held-out-task experiment exists. |
| Cannot express a **safety invariant** that must hold at all times | **Confirmed, and this is the sharpest distinction.** Foresight's target is *task outcome*, `y = 1` iff the robot fails to complete the task (Eq. 2). A behaviour that is unsafe but succeeds carries label 0 and trains the detector toward silence. There is no place in the formulation to say "regardless of outcome, this must never happen." | Eq. 2; the word "safety" does not appear as a constraint anywhere in the pages read; no formal specification of any kind is used or discussed. |

One further asymmetry, and it is the one a reviewer will find most interesting: because
the detector learns "deviation from the training rollout distribution," a **legitimate
recovery can be scored as a failure**. The paper says so itself, explaining the ACT → π₀.₅
collapse: π₀.₅ "may recover by picking the banana and then returning to pick the lion. A
detector trained only on ACT-like rollouts may not see such recovery behavior and may
misclassify it as failure" (p. 8). A specified monitor has the opposite failure mode — it
will accept any recovery that satisfies the formula, and reject any that does not, for a
stateable reason.

### 6.3 Be fair — what Foresight does better

State these plainly or the paragraph is a strawman:

1. **It sees things no thresholded sensor value can see.** A missed grasp, a slipped
   object, an object placed in the wrong container — these are visual-relational facts.
   `min_range < 0.25` cannot express them; a 1408-d video latent can.
2. **It needs no author.** No one writes anything. Point it at rollouts and outcome
   labels and it produces a monitor. `skill_monitor` needs an LLM, a schema, and a human
   who accepts the generated spec.
3. **It generalises across policies for free**, which a spec written against one policy's
   behaviour would not.
4. **Its false-alarm rate has a distribution-free guarantee** at a chosen α. A hand-set
   threshold like `image_similarity_to_goal > 0.75` has no such property. This is a place
   where the learned side is *more* principled, not less.
5. **It scales to 13,657-step rollouts** with only outcome labels — precisely the regime
   where writing dense annotations is infeasible.

### 6.4 Is there a hybrid framing worth noting?

Yes, three things worth borrowing rather than only opposing.

**(a) Functional conformal prediction for the CLIP proposition — the cheapest and most
defensible borrow.** `visually_at_goal` is currently `"True when image_similarity_to_goal >
0.75"` (`skill_monitor/specs/formulas_g1.json`). That 0.75 is a hand-set constant with no
stated error semantics. FCP (Appendix 9, p. 14) turns exactly that kind of constant into a
*time-varying band* `δ_t = μ_t + q̂σ_t` calibrated on nominal runs at a nominal
false-alarm level α. Nothing about the LTL layer changes — the AP still produces a
boolean, the Büchi automata still produce the verdict, the verdict is still traceable to a
named formula — but the boolean now has a calibrated FPR instead of a magic number. This
is a one-paragraph method addition and a real answer to "where does 0.75 come from?",
which a reviewer will ask.

**(b) A learned score can be an atomic proposition.** Foresight's output has exactly the
shape `skill_monitor`'s AP schema consumes: a scalar compared against a threshold, which
is what `spec_contract.rule_of` already parses. An AP
`"drifting_toward_failure": "True when foresight_score > delta_t"` would slot into
`atomic_propositions` unchanged and be usable inside a phased guard. That is the honest
hybrid: **the world model as a sensor, the LTL as the combiner.** It preserves
traceability — the verdict still names a formula and a phase — while importing perceptual
reach the symbolic layer does not have. Worth one sentence in Future Work; it also
pre-empts the reviewer's "why not both?"

**(c) A convergence worth pointing at, not just a contrast.** Foresight's motivating
observation is that failure detection needs task stage, because the same image means
different things at different points in the task (p. 1). Its response is to learn stage
implicitly via action-conditioned latents and causal attention. `skill_monitor`'s
`execution_phases` — `enter_condition`, `invariant`, `progress_condition`,
`exit_condition` — state the same structure explicitly. That is a strong framing: *the
strongest learned detector in this space independently concluded that phase matters, and
then spent 200 GPU-epochs recovering implicitly what a spec states in eight lines.* Say it
without gloating; it is a genuine point of agreement about the problem.

**Caution on borrowing:** Foresight needs labelled failure rollouts and H200-class
hardware, and names its own latency as the blocker for on-device deployment (p. 9). On a
Unitree G1 running a real-time monitor, (a) is adoptable now; (b) is Future Work, not a
claim.

**Citation lead.** Foresight's related work cites Code-as-Monitor (Zhou et al.,
arXiv:2412.04455), "Constraint-aware visual programming for reactive and proactive robotic
failure detection" [25], and I-FailSense (Grislain et al., ICRA 2026, arXiv:2509.16072)
[26]. Code-as-Monitor is *constraint*-based rather than distribution-based and is
therefore a closer competitor to `skill_monitor` than Foresight is. Per the reading list's
"promote one to a folder if a reviewer's likely objection turns out to live there" rule,
Code-as-Monitor is the strongest promotion candidate this paper surfaces.

### 6.5 THE DRAFT PARAGRAPH

> Learned runtime monitors have become strong. Foresight [foresight2026] streams
> action-conditioned V-JEPA 2 latents through a causal Transformer and reaches 0.94
> balanced accuracy on LIBERO-Long and 0.78 on BEHAVIOR-1K rollouts averaging 8,557
> steps, using only trajectory-level success/failure labels, and it transfers across
> policy families without touching policy internals. We do not claim to match that
> accuracy, and on the perceptual failures it targets — a missed grasp, a slipped object —
> a thresholded sensor value cannot compete with a 1408-dimensional video latent. We claim
> something different in kind. Foresight's output is a scalar `s_t` and a binary alarm; it
> names no failure, reports no task phase, and offers no per-alarm attribution, so an
> operator learns that something is wrong but not what, where, or on what grounds. Its
> notion of "wrong" is deviation from a learned rollout distribution rather than violation
> of a stated requirement, which is why the authors report that a detector trained on ACT
> rollouts scores a legitimate π₀.₅ recovery as a failure (ROC-AUC 0.56) [foresight2026].
> Because its label is task outcome, it also has no way to express a safety invariant that
> must hold *regardless* of outcome: an unsafe but successful execution is a negative
> example. And the framework is dataset-specific — hundreds of labelled rollouts including
> failures, an action-conditioned predictor trained per benchmark and per embodiment, and
> no held-out-task evaluation anywhere in the paper. `skill_monitor` inverts every one of
> these. It needs no training data at all; its verdicts are three-valued and traceable to
> a named formula and a named phase (`collision_imminent` violated during
> `ExecutionAndTracking`); its atomic propositions are executable predicates over a
> declared sensor schema, statically validated before deployment, so an unsatisfiable or
> ungrounded specification is rejected rather than silently mis-monitored; and `G(upright)`
> says what must always be true, which no outcome-supervised detector can be asked to
> represent. The two are complementary rather than competing: a calibrated learned score
> is exactly the shape of an atomic proposition, and we treat Foresight-style detectors as
> candidate sensors for the symbolic layer rather than replacements for it.

*(Trim to taste; the load-bearing sentences are 2 — the concession — and the last one.)*

---

## 7. Check yourself

**Q1. Foresight's detector emits `s_t ∈ [0,1]`. Name every piece of information that is
*not* in that output but that a `skill_monitor` verdict carries.**
The failure's identity (`collision_imminent` vs `fell_over` — Foresight's label space is
`{0,1}`, Eq. 2); the execution phase (`ExecutionAndTracking` — no phase output exists,
though phase is the paper's stated motivation on p. 1); the grounds for the verdict (which
proposition went false, and which formula it violated — no attribution mechanism is
described); and the three-valued distinction between "not yet decided" and "refuted"
(`INCONCLUSIVE` vs a violation — Foresight's alarm is binary at the first threshold
crossing, Eq. 4). What it *does* carry that `skill_monitor` does not: a calibrated
false-positive rate at level α.

**Q2. The reader wants to write "Foresight cannot generalise to an unseen task." Is that
claim supported, and what is the precise defensible version?**
The strong version is *unsupported as stated* — the paper does not test unseen tasks and
therefore does not show failure on them. The defensible version is the absence claim: the
paper contains no held-out-task experiment. BEHAVIOR-1K Table 10 says "All 4 tasks are
seen (3-fold cross-validation)", and the split protocol (Appendix 8, p. 13) shuffles
rollouts rather than tasks. The demonstrated generalisation axis is *policy*, and it is
asymmetric (π₀.₅ → ACT 0.94 AUC; ACT → π₀.₅ 0.56). Write "generalisation to unseen tasks
is not evaluated," not "it cannot generalise."

**Q3. Why can Foresight not express `G(!collision_risk)`, and why is that an argument
about kind rather than accuracy?**
Because its supervision signal is task outcome: `y = 1` iff the robot fails to complete
the task (Eq. 2, p. 3). A rollout that brushes an obstacle and still completes the task is
a *negative* example, so training pushes the score down on it. The detector can only learn
"looks unlike a successful rollout," which is a statement about a distribution, not a
requirement. `G(!collision_risk)` is a requirement — it holds or is violated independent of
whether the task succeeded, and the violation is decided by a deterministic automaton over
a named, schema-checked predicate. No amount of extra data or accuracy converts a
distribution-deviation score into an invariant, which is why the contrast paragraph should
not be argued on accuracy.

**Q4. Which single number in this paper is the most useful for the reader's paragraph, and
which is the most dangerous to quote?**
Most useful: **0.56 ± 0.07 ROC-AUC, ACT → π₀.₅** (Table 4, p. 8) with the authors' own
explanation that the detector may score a genuine recovery as a failure (p. 8). It is the
paper's own evidence that "failure" means "unlike my training distribution," and it comes
from the authors, not from a hostile reading.
Most dangerous: **0.94 balanced accuracy on LIBERO-Long** — because it is (i) balanced
accuracy at a *tuned* α = 0.02, not ROC-AUC, and (ii) on the same benchmark SAFE-LSTM has
the *higher* ROC-AUC (0.91 vs Foresight's 0.89). Quoting 0.94 as "Foresight's accuracy"
without those qualifiers overstates the opponent and invites a correction; quote it, as
the draft does, alongside the honest concession rather than as the number to beat.
