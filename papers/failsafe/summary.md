# FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models

Zijun Lin, Jiafei Duan, Haoquan Fang, Dieter Fox, Ranjay Krishna, Cheston Tan, Bihan Wen.
Nanyang Technological University; Centre for Frontier AI Research, A*STAR; Allen Institute for AI;
University of Washington.
arXiv:2510.01642 [cs.RO]. **The version retrieved and summarised here is v4, dated 7 Jul 2026**
(the header on p.1 of the retrieved PDF reads `arXiv:2510.01642v4 [cs.RO] 7 Jul 2026`), not the
Oct 2025 v1 named in the reading brief. Anything below could in principle differ from v1; I did not
diff the versions. Project page: `https://jimntu.github.io/FailSafe/` (not reachable from this
environment — egress blocked — so the page's own claims are unverified).

Page numbers below refer to the arXiv PDF as paginated by the retrieval tool (pp. 1–7 retrieved).

---

## 1. In one paragraph

FailSafe is a **data-generation pipeline** plus the **model it trains**, aimed at the fact that VLA
policies are trained only on clean, successful trajectories and therefore have no idea what to do
once they are off-distribution. The pipeline runs inside a simulator that supports motion planning
(ManiSkill), takes a ground-truth trajectory, and deliberately **injects a perturbation** at one
stage — a translation offset, a rotation offset, or a "no-ops" freeze — until the task actually
fails. It then searches for a **corrective 7-DoF end-effector delta `ΔA`** that maps the deviated
pose back onto the correct trajectory, and *verifies* that delta by replaying the whole rollout in
simulation and checking that the previously-failing task now succeeds (p.4–5). Verified
(failure, ΔA) pairs — 131k of them across three cube tasks, plus ~56k clean trajectories — become
the FailSafe dataset, which is used to fully fine-tune LLaVA-OneVision-7B into **FailSafe-VLM**
(p.5). At deployment FailSafe-VLM sits beside a base VLA: **every 10 steps it takes control**, looks
at the recent observation window, answers "is a failure likely here, yes/no", and if yes emits a
failure type and an executable `ΔA` that the robot runs directly, after which control returns to the
VLA (Fig. 3, p.5). The headline claim is that this raises the success rate of three VLAs (π₀-FAST,
OpenVLA, OpenVLA-OFT) on three ManiSkill tasks by up to 22.6% on average, and that FailSafe-VLM
generalises to unseen viewpoints, objects and embodiments. The paper's explicit positioning is
against AHA and RoboFAC: those detect failures but emit only *natural-language* corrections
("the gripper should move left"), which are "inherently ambiguous about magnitudes, scales and
endpoints" (p.2) and cannot be fed to a VLA. FailSafe's whole contribution is making the correction
**numeric and executable**.

## 2. Key concepts

**VLA (Vision-Language-Action) model** — a VLM extended to emit low-level robot actions directly
from image observations plus a language instruction (p.1–2). The three used here as base policies:
OpenVLA (discrete action tokens over a Prismatic-7B backbone, trained on Open-X-Embodiment),
OpenVLA-OFT (adds action chunking and a regression loss instead of next-token prediction),
π₀-FAST (a separate expert action head with flow matching / diffusion for continuous high-frequency
actions) (p.2).

**Failure mode taxonomy** — *three basic modes*, expanded across axes into seven labelled types
(p.3, Table I p.4):
- **Translation failure** — Cartesian perturbation on x, y or z. Noise range ±0.1.
- **Rotation failure** — angular deviation in roll, pitch or yaw. Noise range ±1 radian.
- **No-ops failure** — "the robotic arm becoming stuck for a certain period without any movement."

This is a **closed, fixed, motion-level** taxonomy. It is defined *by the generator* — a failure
exists in the dataset because the pipeline injected it, not because it was observed. The paper's
defence is that it is generative of more complex failures: "Many multi-step failures, such as an
object slipping during transport, can be traced back to initial improper grasps caused by basic
translation or rotation deviation" (p.3), and it claims these modes "collectively offer a concise
and comprehensive representation of most motion-level failures in VLA control."

**Failure injection** — the modes, noise ranges, and the stages at which they may be introduced are
declared in a **YAML configuration file**, consumed by a custom ManiSkill environment wrapper (p.3).
Each failure trajectory contains exactly one deviated stage (B → B′), so the rollout becomes
A → B′ → C → D.

**Recovery action `ΔA`** — the 7-DoF pose difference between a **deviated pose `P_d`** on the failure
trajectory and a **corrective pose `P_c`** on the correct trajectory (p.3–4). Crucially it is *not*
the negation of the injected perturbation — naively replaying the perturbation as a delta "could
cause collisions between the gripper and the object" (p.3). Search windows are hand-set: `P_d`
candidates start at step 10 of the failure trajectory; `P_c` is restricted to a window from 10 steps
after the start to 3 steps before the end of the correct trajectory; for no-ops, `P_c` is sampled
3–10 steps after `P_d`. Many `(P_d, P_c)` pairs are generated per trajectory, so a failure has
**many valid recoveries**, not one.

**Systematic verification** — the gate that separates FailSafe from a naive perturbation dataset.
Each candidate is checked by replaying A → `P_d` → `P_c` → B → C → D in the simulator; the pair
enters the dataset **only if the previously-failing task now succeeds** (p.5). Note where this
happens: at *dataset construction time*. There is no verification at inference.

**Failure type is diagnostic, not prescriptive** — stated outright: "The purpose of defining a
failure type is to identify the dominant source of error, rather than to restrict `ΔA` to correcting
only a single dimension" (p.4). `ΔA` is not 1-sparse; it adjusts all seven dimensions regardless of
the label. This matters a great deal for §6 below.

## 3. Method

### 3.1 Detection

- **Model**: LLaVA-OneVision-7B (Qwen2-7B-Instruct language backbone, SigLIP vision tower, two-layer
  GELU MLP projector at 2× hidden expansion, penultimate-layer visual features), **fully fine-tuned**
  — vision tower, adapter and LLM jointly — for one epoch on 32 H100 GPUs with DeepSpeed ZeRO-3,
  base LR 1e-5 (2e-6 for the vision tower), cosine decay, 3% warmup, zero weight decay, bf16/TF32.
  Co-trained with a RoboPoint VQA mixture for generalisation (p.5).
- **Inputs**: a task instruction plus **10 consecutive image observations** of the trajectory. The
  dataset holds three camera perspectives (front, side, hand); at evaluation a **novel view aligned
  with the VLA's training camera** is rendered instead, to test viewpoint generalisation and because
  "an additional camera dedicated to FailSafe-VLM may not be available" in the real world (p.5–6).
- **Prompt / output format** (Fig. 2 (IV), p.4). Question: identify the current sub-task, then choose
  from `['yes','no']` whether a failure is likely, and if yes output a corrective action. Answer:
  `Sub-task: <…>. <No>.` or `Sub-task: <…>. <Yes>, <Failure Type>. <ΔA>.` So detection is a
  **binary token**, with the failure type and the 7-vector as further generated tokens.

### 3.2 Recovery

- **Mechanism**: fixed-period preemption. "Every 10 steps, FailSafe-VLM takes over the base VLA
  model's control of the robotic arm to detect potential failures and outputs actions that the robot
  can execute directly if a failure is identified. After that, control is returned to the base VLA
  model until the next 10 steps complete" (p.5, Fig. 3). Window length = 10.
- **What is executed**: the emitted `ΔA` — a single 7-DoF end-effector delta, applied directly. The
  paper describes the effect as "helpful nudges when the robotic arm becomes stuck or is about to
  fail" (p.6), and the qualitative analysis shows the corrections as short green segments that pull
  the end-effector back toward the ground-truth trajectory before OpenVLA resumes (Fig. 4, p.7).
- **The recovery is learned, not planned and not prompted.** The motion planner is used only inside
  the *offline* pipeline to synthesise and verify `ΔA`; at deployment there is no planner in the
  loop, no search, no constraint check. FailSafe-VLM regresses a delta from pixels.
- **There is exactly one response.** No severity grading, no escalation, no de-escalation, no
  halt, no abort, no slow-down, no human hand-off, no replan request. The only branch in the whole
  runtime is `yes` (apply `ΔA`) vs `no` (return control unchanged).

### 3.3 Dataset

131k verified failure–action pairs over three ManiSkill tasks (pick cube, push cube, stack cube),
plus ~56k ground-truth no-failure entries so the model can tell failure from success; failure-to-
success ratio 2.3:1 (p.5, Table I p.4). Per-type totals: no-ops 26,235; trans_x 24,480;
trans_y 29,034; trans_z 2,385; rot_x 27,807; rot_y 17,736; rot_z 3,363; GT 55,961. The distribution
is severely uneven — e.g. Pick Cube contributes 0 trans_z entries and only 60/69/60 rot_x/y/z
entries, while Push Cube contributes 15,690 rot_x. The paper does not comment on this imbalance.

## 4. Results

All results are **in ManiSkill simulation**. Franka Emika Panda unless stated. Success-rate values
are multiples of 4%, consistent with 25 trials per task per condition (the paper does not state the
trial count explicitly — *not verified*).

**Table II (p.6) — VLA success rate with and without FailSafe-VLM**, on test seeds (spatial
configuration unseen), camera view matching the VLA's training view but novel to FailSafe-VLM:

| VLA | Pick Cube | Push Cube | Stack Cube | Average |
|---|---|---|---|---|
| π₀-FAST | 88.0 → 88.0 | 52.0 → 64.0 | 96.0 → 96.0 | 78.7 → 82.7 (**+4.0**) |
| OpenVLA | 28.0 → 48.0 | 4.0 → 24.0 | 12.0 → 40.0 | 14.7 → 37.3 (**+22.6**) |
| OpenVLA-OFT | 84.0 → 96.0 | 88.0 → 100.0 | 100.0 → 100.0 | 90.7 → 98.7 (**+8.0**) |

Read the headline number carefully: **+22.6% is the gain on the weakest baseline**, OpenVLA at 14.7%
— a policy that fails ~85% of the time. On the two competent baselines the gains are +4.0 and +8.0,
and five of the nine per-task cells move by 0.0 (four of those are already at 96–100%, i.e. no
headroom). The abstract's "up to 22.6%" is accurate but is the maximum over three averages.

**Table III (p.6) — unseen object categories** (sphere, charger), OpenVLA-OFT:
53.3 → 70.7 average (**+17.4**); Pick Sphere 44→68, Place Sphere 36→52, Pick Charger 80→92.

**Table IV (p.6) — unseen embodiment**, xArm 6, OpenVLA-OFT re-fine-tuned on 1,000 xArm trajectories
per task while **reusing the Panda-trained FailSafe-VLM checkpoint unchanged**:
85.3 → 92.0 average (**+6.7**), all of it from Stack Cube 56→76; the other two tasks were already
at 100%.

**Table V (p.7) — failure-reasoning quality vs. other VLMs.** 20 held-out test seeds → 1,712 test
entries with unseen spatial configurations. Three metrics: **binary success** (two-class, does it
tell failure from success), **accuracy** (correct *only if* the predicted failure type **and axis**
match ground truth), **cosine similarity** between predicted and ground-truth `ΔA`. Competing VLMs
were prompted with a detailed template including a ground-truth example and the legal delta ranges.

| Model | Binary success ↑ | Accuracy ↑ | Cosine sim ↑ |
|---|---|---|---|
| Qwen2.5-VL | 0.2401 | 0.2401 | 0.0000 |
| Gemini-2.5-flash | 0.6229 | 0.1412 | −0.0121 |
| GPT-4o | 0.7007 | 0.1960 | 0.0117 |
| **FailSafe-VLM** | **0.9094** | **0.8368** | **0.6522** |

The paper notes Qwen2.5-VL "consistently outputs 'no failure' and an all-zero recovery action"
(p.6) — so its 0.2401 is presumably just the fraction of true-success entries in the test set,
i.e. the test set is ~24% success / ~76% failure. (That reading is mine; the paper does not state
the class balance — *not verified*.) The paper also concedes the cosine target is soft: "strong
failure reasoning in a VLM does not require near-perfect cosine similarity with the ground-truth
action, since multiple corrective `ΔA` can enable recovery… a cosine similarity of approximately
65% already yields meaningful improvements" (p.7).

**Table VI (p.7) — inference overhead**, averaged over 75 runs:
π₀-FAST 43.3s → 47.2s (+3.9s); OpenVLA 112.1s → 121.2s (+9.1s); OpenVLA-OFT 28.8s → 32.6s (+3.8s).
The paper attributes most of the delay to "simulator replanning after receiving corrective actions."

**Qualitative (Fig. 4, p.7)**: with OpenVLA on "pick up the red cube," the arm starts nearly frozen;
FailSafe-VLM detects the no-ops condition and nudges the end-effector back toward the ground-truth
x/z trajectory, after which OpenVLA resumes and completes the task.

## 5. Limitations

**Admitted** (Conclusions, p.7):
- "The current FailSafe pipeline primarily focuses on **motion-level recovery** and does not yet
  support the correction of **object-level errors**."
- VLA/VLM synergy "can be further improved in efficiency and flexibility," e.g. via real-time action
  chunking; the current replanning overhead is left as future work.
- Framed modestly overall: "an early attempt."

**Not admitted, and load-bearing for anyone comparing against it:**

1. **The failure distribution is closed by construction.** Train and test failures come from the
   *same injector* with the *same seven types* and the *same noise ranges*. "Unseen failure
   trajectories" means unseen **seeds and spatial configurations**, not unseen **failure kinds**.
   Nothing in the paper tests a failure the YAML did not describe. FailSafe is emphatically **not
   open-set** — this contradicts a natural assumption about learned failure reasoning and matters
   directly for §6.
2. **Three tasks, all cube manipulation on a tabletop.** Pick / push / stack cube, plus sphere and
   charger for the generalisation table.
3. **No real-robot experiment is reported in the retrieved text.** Section IV opens on "Framka Emika
   Panda robot arm" [sic] in ManiSkill; all tables are simulation. There is a reference to "the
   supplementary video for robot demo" (p.7) which I could not retrieve — *whether any hardware
   result exists is not verified*.
4. **False positives are never costed.** FailSafe-VLM seizes control every 10 steps regardless of
   whether anything is wrong. At 0.9094 binary success it is wrong roughly 9% of the time, and a
   false positive means injecting a spurious 7-DoF delta into a *healthy* trajectory. No precision,
   no recall, no per-class breakdown, no ablation of the false-positive rate is reported.
5. **Nothing is verified at run time.** `ΔA` is verified in simulation during *dataset construction*.
   The deployed system emits a regressed vector with no feasibility, collision or safety check —
   the very collision concern that motivated the elaborate `P_c` search windows offline (p.3–4) has
   no analogue online.
6. **Fixed 10-step polling gives no latency bound.** A failure occurring just after a poll is not
   examined for 10 steps. There is no notion of time-to-violation, urgency, or worst-case reaction
   time anywhere in the system.
7. **The VLM comparison is a fine-tuned specialist versus prompted generalists** on the specialist's
   own output format and its own generator's label set. GPT-4o scoring 0.196 on "predict which of
   seven injected perturbation types this is, with the correct axis" is a weak result to beat.
8. **Severe class imbalance** in the dataset (Table I) is neither discussed nor ablated.
9. **No safety semantics exist at all.** The system's only available action is to *move the arm*.
   There is no representation of hazard, no stop, no abstention. "Failure" here means "the task will
   not succeed," never "something dangerous is about to happen."

---

## 6. For skill_monitor

### 6.1 How FailSafe decides what to do after detection — vs. the intervention ladder

**Learned, single-rung, ungraded.** Concretely:

| | FailSafe | skill_monitor |
|---|---|---|
| Source of the response | Supervised regression over 131k sim-verified examples | Pure function of (fault category × steps-to-violation × sensor confidence) |
| Response space | One: apply a 7-DoF `ΔA` | Six: CONTINUE < WARN < SLOW < REPLAN < HALT < ABORT |
| Graded by severity | No | Yes |
| Trigger | Fixed 10-step poll | Formula violation / proximity to violation |
| Enforcement | Preemption — takes control from the VLA | Preemption — out-publishes the planner at zero velocity |
| Auditable reason | A type label the model generated, post hoc | The named failure mode that fired, by construction |

Two findings worth carrying into the paper:

**(a) The failure type does not select the response.** FailSafe *has* a taxonomy, so it looks at
first glance like it has fault categories. It does not, in the sense that matters. The paper states
plainly that the type exists "to identify the dominant source of error, rather than to restrict
`ΔA`" (p.4) — every type produces the same kind of response, a dense 7-vector nudge. Nothing
downstream branches on the label. So the answer to "does anything play the role of `fault_category`?"
is: **a label with the shape of one, but with no control authority.** That is a genuinely clean
contrast and you can state it without straw-manning, because the paper says it itself.

**(b) The preemption architecture converges with yours, and you should cite that as support rather
than contrast.** FailSafe does not *ask* the VLA to correct itself; it takes the control channel
away for a step. Your out-publishing-with-zero-velocity design rests on the same premise — that a
policy which is already failing cannot be relied on to act on a request. Prior work independently
arriving at enforcement-over-request strengthens your design choice. The difference is that
FailSafe's takeover is on a **fixed timer**, so it is unconditional and ungraded; yours is
**conditional on the fault**, which is what lets it have more than one rung.

### 6.2 Does FailSafe gate on confidence or uncertainty? — **No. Your contribution is not threatened.**

I searched the retrieved text (pp.1–7, covering the full method, all experiments and the conclusion)
for any confidence, uncertainty, calibration, threshold, abstention, staleness or sensor-quality
mechanism. **There is none.**

- Detection is a **hard binary token** — the model generates `<Yes>` or `<No>`. No probability is
  read out, no threshold is tuned, no abstain option exists.
- **Cosine similarity is an offline evaluation metric** (Table V), not a runtime gate. Nothing
  computes it during execution, and nothing could — the ground-truth `ΔA` is unavailable at
  deployment by definition.
- **No sensor model at all.** The input is a 10-frame image window from one camera. There is no
  representation of how good, how fresh, or how trustworthy that input is. Viewpoint change is
  treated as a *generalisation* challenge to be absorbed by training, not as a signal quality to be
  reasoned about.
- **The response cannot be de-escalated even in principle**, because there is only one rung. A
  system with a single response has nowhere to de-escalate *to*. Confidence gating is not merely
  absent — it is architecturally unavailable.

**Verdict: this paper does not weaken the confidence-gating claim; if anything it sharpens it.** The
strongest form of your claim survives contact with FailSafe: *the response should be a function of
how much you trust the evidence, not only of what the evidence says.* Be careful to claim it at the
right altitude, though — "confidence-gated graded response" is a well-established idea in runtime
verification and fault-tolerant control generally, so the novelty is in **the specific coupling**
(fault category × time-to-violation × sensor staleness → one of six named rungs, computed by a pure
function you can unit-test), not in the abstract idea of degrading gracefully. Frame it that way and
FailSafe is no threat at all. One caveat to state honestly in the paper: I verified absence in the
retrieved pages of **v4**; I did not read v1, and I did not obtain any appendix beyond p.7.

### 6.3 What FailSafe requires

- **A simulator with motion planning.** Non-negotiable and structural: failure injection needs a
  stage-decomposed planner to perturb, and systematic verification needs to *replay* the corrected
  rollout to check it works. There is no path to generating this data on hardware.
- **Ground-truth trajectories** for every task, to perturb and to map corrections back onto.
- **A per-task YAML** declaring failure modes, noise ranges and injectable stages. Note this is a
  *specification* too — so FailSafe is not free of hand-authored intent, it just hides it in the
  data generator instead of exposing it at runtime. Worth saying in the related-work paragraph.
- **131k verified failure–action pairs + ~56k clean trajectories**, per task family.
- **32 H100 GPUs for one epoch** of full fine-tuning of a 7B VLM, plus a RoboPoint VQA co-training
  mixture.
- **A VLA backbone**, itself fine-tuned on 1,000 ground-truth trajectories per task.
- **+3.8s to +9.1s of wall-clock overhead** per episode.

Against skill_monitor's requirements: an LLM call to author the spec once, and a monitor that runs
on the robot. **Zero training data, zero GPUs, zero simulator.** That is a real and defensible axis.

- **Taxonomy**: fixed, closed, seven motion-level types (three basic modes). **Not open-set.** This
  is the single most important correction to the brief's framing.

### 6.4 Draft contrast paragraph

> The closest recent work that both detects and recovers is FailSafe (Lin et al., 2025), which
> injects translation, rotation and no-ops perturbations into simulated ground-truth trajectories,
> searches for a 7-DoF corrective delta that provably restores task success under replay, and
> distils 131k such verified pairs into a fine-tuned 7B VLM that preempts the base policy every ten
> steps. FailSafe is stronger than our system on exactly the axis it was built for: it produces a
> *quantitative* correction. It does not merely determine that the arm is off-course, it says by how
> much and in which direction, and it does so for objects, viewpoints and embodiments it was never
> trained on, without any per-task re-specification. Our monitor can stop, slow, or demand a replan;
> it cannot tell the planner where to go. We take a different position on what a runtime safety
> layer should be. In our system every failure mode is named, carries a declared fault category, and
> is checked by a formula whose violation is a decidable fact about the trace rather than the output
> of a 7B network — so when an intervention fires, the reason is the specification, available before
> deployment and inspectable after the incident. The response is likewise specified rather than
> learned: a pure function from (fault category, steps to violation, confidence in the triggering
> sensors) onto a six-rung ladder, which lets a SAFETY mode firing on stale sensors de-escalate to a
> warning instead of a halt — a distinction FailSafe cannot express, since its single response is
> emitted from a hard yes/no token with no uncertainty anywhere in the pipeline. And we require no
> training data, no simulator with motion-planning support, and no GPU. The honest cost is scope. A
> hand-authored failure-mode list is bounded by what its author thought of; FailSafe's failure
> taxonomy is bounded too — it is a fixed seven-class motion-level set defined by its own injector,
> and neither system is genuinely open-set — but FailSafe's learned corrections interpolate over a
> continuous perturbation space in a way that an enumerated specification does not, and its
> recoveries improve a weak policy far more than any amount of stopping could. The two are
> complementary rather than competing: FailSafe corrects *task* failure, we constrain *behaviour*,
> and a deployed humanoid arguably wants both.

*Note on the brief's framing:* the brief asked me to "concede plainly what FailSafe does better,
especially on open-set failures a hand-specified failure-mode list would never enumerate." I have
not written that concession, because it is not true of this paper — FailSafe's taxonomy is closed
and generator-defined, and narrower in *kind* than your five fault categories (it has nothing
corresponding to SAFETY, TIMEOUT or NAVIGATION; it is entirely about geometric deviation of an end
effector). Conceding open-set generality to it would be a factual error a reviewer who knows the
paper would catch. The concession I substituted — quantitative correction and cross-embodiment
transfer without re-specification — is the one FailSafe actually earns.

---

## 7. Check yourself

**Q1. FailSafe has a seven-type failure taxonomy. Why is that *not* an instance of a fault
category in your sense?**
Because it has no control authority. A fault category in skill_monitor is an *input to the response
function*: SAFETY and PROGRESS route to different rungs of the ladder. FailSafe's type label routes
to nothing — every type yields the same kind of output, a dense 7-DoF delta, and the paper says so
explicitly ("The purpose of defining a failure type is to identify the dominant source of error,
rather than to restrict `ΔA`," p.4). The label is a diagnosis printed alongside the action, not a
selector for it. The test to apply to any competing system: *if I change the category, does the
response change?* For FailSafe the answer is no.

**Q2. Which single number in this paper is most likely to be quoted against you, and what is the
fair response?**
"+22.6% average improvement." The fair response is not to dispute it but to locate it: it is the gain
on OpenVLA, whose unaided success rate is 14.7% — a policy failing five times out of six. On the two
competent baselines the gains are +8.0 (OpenVLA-OFT) and +4.0 (π₀-FAST), and five of nine per-task
cells move by exactly 0.0, four of them because the baseline was already at 96–100%. Also note the
comparison is a success-rate delta on three cube tasks in simulation — it is not a safety metric,
and skill_monitor is not competing on it. Do not argue accuracy; argue that you are measuring
something else.

**Q3. Suppose a reviewer says "FailSafe already does confidence-aware recovery, since its cosine
similarity to the ground-truth action is only 0.65 and it still works." Is that a valid objection?**
No, and the confusion is worth naming precisely. Cosine similarity is an **offline evaluation
metric** computed against a ground-truth `ΔA` that does not exist at deployment. The paper's remark
that ~65% "already yields meaningful improvements" (p.7) is an observation about *tolerance* — many
different deltas can recover the same failure, because the `P_c` sampling generated many valid ones
— not a runtime confidence estimate. Nothing in FailSafe's execution loop reads a probability,
compares it to a threshold, or changes behaviour based on how sure it is. The system's only runtime
signal is a generated `<Yes>`/`<No>` token.

**Q4. What does FailSafe's design imply about the honest scope of your own zero-training-data
claim?**
That it should be stated as "no training data" and not as "no authored artefacts." FailSafe also has
hand-authored intent: a per-task YAML declaring which failure modes exist, their noise ranges, and
which stages may be perturbed (p.3), plus hand-tuned search windows (start at step 10; `P_c` from
+10 to −3; no-ops sampled 3–10 steps ahead, p.4). The difference is *where the specification lives
and whether it survives to run time*. FailSafe's spec is consumed once, offline, by a data generator,
and is then unrecoverable from the deployed model's weights. Yours is the deployed artefact: the
same named formula that a human wrote is the thing that fires and the thing that appears in the log.
That is the auditability argument, and it is stronger and more precise than "we don't train
anything."
