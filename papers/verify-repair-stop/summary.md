# Verify, Repair, Repeat, or Stop? Robust Stopping for Noisy Verify-Repair Loops in LLM Agents

arXiv:2607.17641v1 [cs.AI], 20 Jul 2026.
Yitao Wu, Si Shen, Rui Yang (corresponding), Hong Peng, Bin Hu.
Read via alphaXiv full-text query on 2026-09-02. arxiv.org itself was blocked by the network
egress proxy, so all facts below are taken from the PDF body. Venue: **not verified** (formatting
is AAAI-like and the code link is anonymised for review, but no venue is stated in v1).

---

## 1. In one paragraph

The paper attacks the question of *when an LLM agent should stop iterating a verify-repair loop*.
Its premise is that the standard loop silently assumes two things -- that more repair rounds improve
true quality, and that verifier acceptance reflects true validity -- and that **both assumptions break
at once when the verifier and the repairer are simultaneously noisy**. It introduces a four-parameter
noise model that separates verifier false acceptance (rho0) and false rejection (rho1) from the
repairer's fix probability (alpha) and damage probability (beta), shows that the resulting population
dynamics `Q_{t+1} = Q_t(1-beta) + (1-Q_t)alpha` has a fixed point `b* = alpha/(alpha+beta)` beyond
which further repair is expected to *destroy* validity, and derives a stopping rule that commits when
the one-step marginal gain `G_k = (1-b_k)alpha - b_k beta` drops to zero. The method, **VRR-Stop**,
estimates `b_k` by Bayesian belief filtering over M repeated verifier votes per round and calibrates
rho0, rho1 by a binomial-mixture EM plus <=300 labelled repair transitions for alpha, beta. Because
that estimator collapses when the verifier has near-zero discrimination, they pair it with
**VRR-Guard**, an estimation-free keep-best fallback. On a deliberately stressed GSM8K setting,
VRR-Stop reaches 0.722 true validity at 0.72 average repair rounds against 0.116 for fixed 5-round
repair (+60.6 pp).

---

## 2. Key concepts

| Term | Definition (as given in the paper) |
|---|---|
| **VRR loop** | Verify-Repair-Repeat. Round `k`: issue M independent verification queries on plan `p_k`, collect acceptance count `S_k` in `{0..M}`, then Commit or Repair. Observable history `H_k = (p_0, S_0, ..., p_k, S_k)`. True validity `y_k` in `{0,1}` is **never** observable at deployment. |
| **Four-parameter noise model** | `rho0 = Pr(accept given y=0)` false acceptance; `rho1 = Pr(reject given y=1)` false rejection; `alpha = Pr(y_{k+1}=1 given y_k=0, repair)` repair probability; `beta = Pr(y_{k+1}=0 given y_k=1, repair)` **damage** probability. The first two describe the verifier, the last two the repairer. |
| **Youden's J** | `J = 1 - rho0 - rho1`, verifier *discrimination*. J -> 0 means acceptance counts carry no information about true validity and calibration itself fails. |
| **Committed validity `b_k`** | `Pr(y_k = 1 given H_k)` -- the posterior that the current plan is worth committing. Explicitly **not** the verification pass rate, which can rise purely through false acceptance. Updated by a binomial observation step (Eq. 5) and an alpha/beta predict step `b-_{k+1} = (1-beta)b_k + alpha(1-b_k)`. |
| **True marginal gain `G_k`** | `G_k = b-_{k+1} - b_k = (1-b_k)alpha - b_k beta`. First term = expected benefit of fixing an invalid plan; second = expected loss from damaging a valid one. Stopping rule: Repair if `G_k > tau`, else Commit. All experiments use tau = 0. This is a **one-step (myopic)** criterion -- it compares commit-now against exactly one more round, with no multi-round look-ahead. |
| **Stopping boundary `b*`** | `b* = alpha/(alpha+beta)`. The fixed point of the population dynamics. `b_k < b*` = repair-beneficial regime; `b_k >= b*` = repair-harmful regime. **Crucially: `b*` depends only on alpha and beta. Verifier noise does not move the boundary; it only determines, through `b_k`, whether the comparison is reliable.** |
| **Sign identifiability** | The decision only needs the *sign* of `G_k - tau`, not accurate parameter recovery. With error radius `B_k` such that `Pr(|G_k_hat - G_k| <= B_k) >= 1-eta`, the condition is `G_k_hat - B_k > tau` **or** `G_k_hat + B_k <= tau` (Eq. 8). Proposition 1: if this holds, the estimated action matches the true action w.p. at least 1-eta. |
| **Decision margin `Delta_k`** | `Delta_k = |G_k - tau|`. Reliability is governed jointly by `J` and `Delta`, *not* by the absolute size of parameter error. |
| **VRR-Guard** | Estimation-free fallback for the unidentifiable regime. Keeps an incumbent `c_k`, replaces it only when `S(p_k) >= S(c_{k-1}) + delta` (retention margin delta), and commits the incumbent, not the last plan. Lemma 1 bounds per-round erroneous replacement by `exp(-(M*J+delta)^2 / (2M))`. |
| **TPM reference** | True-Parameter Myopic: the same stopping rule run with ground-truth (rho0, rho1, alpha, beta, pi). A *diagnostic* that isolates calibration error -- explicitly **not** a hindsight upper bound (on Mistral, TPM 0.467 < no-repair 0.507). |

---

## 3. Method

Four stages, run per instance (Algorithm 1):

1. **Mode selection (offline).** A held-out labelled separation test estimates `J_hat`. If
   `J_hat >= J_min`, run VRR-Stop; else run VRR-Guard. This test compares acceptance rates of valid vs
   invalid plans directly on labels -- deliberately *not* using the EM estimator, to avoid diagnosing a
   broken estimator with its own output. Scenarios are partitioned offline; there is no online
   threshold switch.
2. **Belief filtering.** Prior `b-_0 = pi_hat` (the true-validity rate of *initial* plans, from
   calibration folds). Each round issues M verifier queries; assuming conditional independence given
   `y_k`, `S_k` is binomial and Eq. (5) gives the posterior `b_k`. If repair fires, the predict step
   pushes the belief through the alpha/beta transition.
3. **Stopping criterion.** Form `G_k_hat = (1-b_k_hat)alpha_hat - b_k_hat beta_hat` and act on its sign
   against tau. Commit on `G_k_hat <= tau`, or when `K_max` is exhausted.
4. **Guarded fallback.** Under sign-unidentifiability, switch to keep-best with margin delta.

**Calibration** is a one-off cost using two kinds of weak supervision: (a) a binomial-mixture EM over
per-plan acceptance counts recovers `rho0_hat, rho1_hat` and the mixture weight **without labels**;
(b) `alpha_hat, beta_hat` are frequency estimates from **at most 300 labelled before/after repair
pairs**, collected from frozen trajectories where repair fired *every* round without verifier gating
(so the transition samples carry no acceptance-driven selection bias). Five-fold cross-fitting: no
instance's stopping decision touches its own label.

**Sample complexity** (idealised single-query loop only): `N >~ C1 log(1/delta_c) / (M J^2 Delta^2)`.
The authors explicitly decline to claim a corresponding bound for the deployed rule.

**Per-round cost:** M verifier calls + one constant-time belief update, plus at most one repair call.
Hyperparameters: M, tau, delta, K_max. Only delta (swept 0..8, chose 5) and N_calib
(50/100/200/300, chose 300) were tuned; M=8, K_max=5, tau=0 were fixed a priori.

---

## 4. Results

**Setup.** GSM8K, MATH-500, MBPP, BFCL. Ground-truth validity from answer matching, symbolic
verification, unit tests, and an executor respectively. Generators/verifiers from Qwen2.5, Mistral,
Llama families; MATH-500 uses a Qwen2.5-Math-PRM-7B process reward model. M=8, K_max=5, tau=0,
delta=5, 95% CIs from B=10,000 bootstrap resamples, paired comparisons by exact McNemar. (Note: MBPP
appears in the task/verifier table with N=150 but **no MBPP row appears in the seven-setting result
tables I retrieved** -- its role is *not verified*.)

**RQ1 -- is repair monotone? No.** Across eight settings, **six exhibit monotone decline**, with
damage probability beta between **0.615 and 0.938**, typically several times alpha, pushing `b*` below
0.29. BFCL multi-turn is flat under a near-inert repairer (alpha = 0.02, beta = 0.04) -- the paper's
own counterexample that repair is not *inherently* harmful. **Only the favorable setting improves.**
In the non-stationary diagnostic (256-token initial budget, prompt mismatch injected from round 3)
validity runs 0.45 -> 0.87 at round 2 -> 0.12 at round 6, an interior optimum at K* = 2; peak-vs-final
paired gap +74.7 pp [+69.3, +79.7]. An independent-resampling control at the same budget stays
0.47-0.85, so the collapse is path-dependent rewriting, not sampling noise. On the N=500 stress
traces, **55% of instances see a correct plan repaired into an incorrect one, and 24% of those
damaging repairs win majority acceptance** -- raw label statistics independent of any stopping rule. A
strong verifier does not save you: with a PRM verifier at J = 0.805 on GSM8K, fixed-5 still drives
validity 0.727 -> 0.097.

**RQ2 -- stopping performance** (GSM8K / Qwen2.5-3B prompt-mismatch stress, N=500, Table 6):

| Method | True validity V [95% CI] | mean K |
|---|---|---|
| No repair | 0.700 [.658,.740] | 0.00 |
| Majority stopping | 0.690 [.648,.730] | 0.92 |
| ConfStop-0.85 | 0.562 [.518,.604] | 1.92 |
| Fixed repair K=1 | 0.246 [.208,.284] | 1.00 |
| Fixed repair K=3 | 0.122 [.094,.152] | 3.00 |
| Fixed repair K=5 | 0.116 [.088,.144] | 5.00 |
| Verifier-best-of-trajectory | 0.696 [.654,.736] | 0.73 |
| **VRR-Stop** | **0.722 [.682,.760]** | **0.72** |
| TPM reference | 0.694 [.652,.734] | 0.89 |

VRR-Stop beats fixed-5 by +60.6 pp (p < 2e-85), majority stopping by +3.2 pp, and the TPM reference by
+2.8 pp; its gap over **no-repair is only +2.2 pp with a CI crossing zero**. Under fixed-budget
deployment, Reflexion and Self-Refine end at 0.095 and 0.080 on this setting.

**RQ3 -- identifiability.** Sign-flip probability is 0.183 for `J <= 0.15 and Delta <= 0.10` versus
0.014 for `J >= 0.4 or Delta >= 0.30` (~13x). Calibrated stopping stays within 2.8 pp of TPM for
Qwen-3B, Qwen-7B and Mistral (all J >= 0.18). Llama-3-8B has J = 0.03: despite a *large* decision
margin (~0.74) its validity collapses 0.803 -> 0.223 (-58.0 pp, p < 2e-48), because the EM likelihood
surface flattens as J -> 0 (rho1_hat = 0.27 at N=120, *worsening* to 0.077 at N=300 against a true
0.609). Conversely Mistral has a huge parameter error (Delta_rho0 = -0.66) and still lands within
0.3 pp of TPM -- **error magnitude does not predict decision damage; sign flips do.**

**RQ4 -- guarded fallback under shift** (Table 9): VRR-Guard stays near no-repair in all seven
settings and never collapses (Llama 0.793 vs failed VRR-Stop 0.223, +57.0 pp). Its honest cost:
-2.0 pp vs no-repair on Mistral, -0.3 pp on BFCL (CI contains zero), and 0.810 vs fixed-5's 0.875 in
the *favorable* setting.

---

## 5. Limitations

Stated by the authors, plus ones visible from the tables:

- **Local stationarity.** rho0, rho1, alpha, beta are assumed stable within a decision window. Their
  own data contradicts this: in the favorable setting the repair success rate falls from 0.415
  (round 1) to 0.032 (round 5). First-round estimates are a *local* approximation only.
- **Myopic, one-step.** VRR-Stop does not search a trajectory for the post-hoc best round. On the
  interior-peak diagnostic, VRR-Stop and TPM reach 0.693 and 0.720 against 0.867 for post-hoc
  selection of round 2. It cannot anticipate an abrupt mid-loop change in repair dynamics.
- **Binary validity.** `y` in `{0,1}`; no partial credit, no notion of "3 of 4 problems fixed".
- **Conditional independence of repeated queries** and no instance-level difficulty heterogeneity. A
  beta-binomial diagnostic is offered but was unstable across seeds at N=300.
- **The stress settings are adversarially constructed.** The prompt-mismatch setting *injects*
  numeric/condition perturbations into the repairer's copy of the problem while the verifier and the
  ground truth use the original, and raises repair temperature to 1.0. The catastrophic
  beta ~ 0.6-0.94 numbers come largely from this construction. They are an existence proof, **not a
  base rate**.
- **Proposition 1 presupposes `B_k` attains nominal coverage**; the sample-complexity bound is derived
  only for an idealised single-query loop.
- Guard implicitly assumes within-trajectory stationarity of verifier noise (it compares vote counts
  across rounds), and does not dominate no-repair.
- Every result is on a **stochastic LLM verifier or PRM**. No setting in the paper uses a
  deterministic/sound checker. (See section 6.)
