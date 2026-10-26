# Committee prep sheet: "Skill progress monitoring"

Read this the evening before. Sections 2–3 are the related work in more depth than the
slides; section 6 is the questions a committee is likely to ask, with short, honest answers.
Every number here is from our own result files or from the paper's own summary in
`papers/<slug>/summary.md`; nothing is rounded up.

---

## 1. The 30-second story

Robots fail in the middle of a task and often don't notice. The field attacks this in two
streams: **how to describe a skill** (words, logic, demonstrations, code) and **how to monitor
the skill using that description** (state machines, LLMs, vision models). We connect the two:
a plain-language description is turned by an LLM into LTL rules **plus the stages of the task
(progress states)**, and the monitor runs them as state machines on the robot's own sensors.
The stages are what let it catch a failure *when it happens*: a dropped box is caught in 1 s
instead of 14 s, and with a deadline that is 64% vs 36% of tasks delivered on time.

---

## 2. Stream 1: describing a skill

### Natural language → temporal logic

| Paper | What it does | Result to quote | Its gap / how we differ |
|---|---|---|---|
| **Lang2LTL** (Liu et al., CoRL 2023) | English *navigation* commands → LTL grounded in a map. GPT-4 extracts referring expressions, embeddings match them to landmarks, a fine-tuned T5 translates the "lifted" sentence (placeholders A, B, …) into LTL. | Transfers to new cities with no new data (21 cities in their OSM set). | For **planning** a route; no stages; no runtime monitoring. Admits overfitting to some sentence structures. |
| **nl2spec** (Cosler et al., CAV 2023) | An LLM translates one sentence into LTL and outputs **sub-translations** (which words became which part of the formula) so a human can fix one piece and re-translate. | 16/36 hard expert examples correct in one pass; 31/36 with the human loop (≈1.4 loops each). | A **specification-writing** tool with a human in the loop; no monitoring, no stages. |
| **NL2TL** (Chen et al., EMNLP 2023) | "Lifts" the sentence (replaces atomic propositions with placeholders), then a fine-tuned T5 writes Signal Temporal Logic. | Trained on ≈28k lifted sentence–formula pairs; high accuracy on lifted benchmarks. | Translation only; the placeholders still have to be tied to real sensors. |
| **NL2LTL** (Fuggitti & Chakraborti, AAAI 2023 demo) | A Python package: an LLM (or Rasa) picks one of a few fixed DECLARE-style **pattern templates** and fills in the symbols. | A 3-page demo paper; no benchmark of its own. (A later paper, REQ2LTL, measured it at ≈90% on lifted benchmarks with GPT-4o.) | Fixed small set of patterns; no grounding, no stages. |
| **GinSign** (English et al., 2025, arXiv) | Grounds the placeholder propositions into a real **system signature** (the actual predicates and arguments the system has). | 100% predicate-grounding F1 on its three domains. | Closest in spirit to our "every proposition must be measurable" check; but no monitoring and no stages. |

**What to say:** this whole line of work stops at "here is a formula". We go two steps further:
the formula comes **with stages**, and every proposition is tied to a sensor rule the robot
actually has (the spec is rejected otherwise).

### Formal logic written by experts

| Paper | What it does | Gap |
|---|---|---|
| **Bauer, Leucker, Schallhart** (TOSEM 2011) | The standard theory of LTL runtime monitoring (LTL₃): after each step the verdict is true, false or "?"; constructs the smallest monitor that answers as early as possible. | Flat rules; "eventually" stays "?" until the end. We use this theory; the stages are what we add. |
| **RTAMT** (Yamaguchi, Hoxha, Ničković, STTT 2024) | Signal Temporal Logic monitors that report *how much* a rule is satisfied (robustness); ROS integration; Toyota Human Support Robot case study. | An expert writes every rule; no stages. |

### Videos and demonstrations

| Paper | What it does | Gap |
|---|---|---|
| **Learning Task Specifications from Demonstrations** (Vazquez-Chanlatte, Jha, Tiwari, Ho, Seshia, NeurIPS 2018) | Infers a logical specification (a Boolean, non-Markovian property) from demonstrations: maximum-entropy likelihood, search over a candidate pool. | Needs good demonstrations; the candidate pool limits what can be learned. |
| **RoboCLIP** (Sontakke et al., NeurIPS 2023) | One video (or a text description) + a pretrained video-language model → a reward for reinforcement learning. | 2–3× better zero-shot than other imitation-learning methods; but the "description" is a black-box similarity score, not a readable rule. |

### Hand-written code
Our own baseline in Experiment 2: the executor checks "still holding it?" while carrying and
"is it at the drop-off?" before reporting success. Strong where the failure was foreseen
(81% on time with a 1.5× deadline), silent where it was not (40/40 unplanned failures missed).

---

## 3. Stream 2: monitoring a skill

### State machines (formal runtime verification)

| Paper | What it does | Gap / relation |
|---|---|---|
| **Bauer et al.** (TOSEM 2011) | LTL₃ monitors (see above). | Our `MonitorStatus` is this paper's LTL₃. |
| **ROSMonitoring** (Ferrando et al., TAROS 2020) | Turns a list of ROS topics into monitor nodes that send events to a separate checker ("oracle"); any logic can be the oracle; can also block messages. Simulated Mars rover case study. | Rules written by hand; no task progress. |
| **RTAMT** (STTT 2024) | STL robustness monitors, ROS integration. | Same. |
| **Reelay** (Ulus, 2026, arXiv) | Fast online monitoring of past-time temporal logics; benchmarks of ≈1 million messages per log. | Engineering speed; rules by hand; no stages. |
| **Runtime Verification with State Estimation** (Stoller et al., RV 2011) | When some events are not observed, a **Hidden Markov Model** fills the gaps and the monitor computes the **probability** that the property holds. Mars rover software case study. | Closest to our POMDP view. Needs a probability model of the system; no stages. |

### LLM reasoning

| Paper | What it does | Gap |
|---|---|---|
| **REFLECT** (Liu, Bahety, Song, CoRL 2023) | Turns multi-sensor robot data into a hierarchical text summary of what happened; an LLM explains *why* a task failed and a planner corrects it. RoboFail dataset (sim + real). | Explains after the fact; slow; can be wrong; no guarantee. |
| **Our own MiniGrid pilot** | A free-text LLM judge as the monitor. | Gave **+0.00** where the LTL monitor gave **+1.00** on the same scenarios: it says "something is wrong" without saying *where* in the task, so the re-planner has nothing to act on. This is our first evidence for stages. |

### Vision-language models and learned detectors

| Paper | What it does | Gap |
|---|---|---|
| **AHA** (Duan et al., ICLR 2025) | A VLM fine-tuned on failures generated by perturbing successful demonstrations (FailGen); answers "did it fail, and why" in words. | Beats GPT-4o in-context by 10.3%; but needs a failure dataset and the reasoning is not checkable. |
| **FailSafe** (Lin et al., 2025, arXiv) | Generates failures in simulation (ManiSkill), finds a corrective action for each, fine-tunes a VLM to detect and correct. | Up to +22.6 points success for one policy, in simulation; needs data; motion-level fixes only (their own limitation). |
| **Foresight** (Zhang et al., 2026, arXiv) | Predicts future latent states from camera frames and the planned actions (world model), a transformer scores failure, conformal prediction sets the alarm threshold. | Needs training and calibration data; heavy models; scores rollouts, not stages. Note: its own premise ("the same object on the table means different things before and after a grasp") **is** the stage argument, learned instead of written. |

### Hybrid

| Paper | What it does | Gap |
|---|---|---|
| **Embedding Temporal Logic** (Kapoor et al., 2026, arXiv) | LTL whose atomic facts are distances in a pretrained image-embedding space ("close to these reference images"). | The authors say the facts are not yet human-readable; depends on the encoder separating the concepts. |

---

## 4. Platforms: MiniGrid → MuJoCo → Isaac Sim → real G1

| Platform | Status | What it gave us |
|---|---|---|
| **Continuous MiniGrid + MAAOS** | Done, frozen as a pilot. MAAOS is Fouzi's multi-agent project; I integrated it into the continuous MiniGrid. | Box pushing, one agent and two cooperating agents, lava hazards. Corrupted plan: 0 → every seed with monitor + re-plan (Δ = +1.00). Deadlock: off fails every seed (80-step budget); LTL + re-plan recovers every seed in ≈45 steps. Detect-only: +0.00 everywhere. Free-text LLM judge: +0.00. Clean runs: 1.00 success, 0 false alarms. 10 seeds per cell (rule-based monitors), 5 (LLM-backed). |
| **MuJoCo G1** | Now. | Real humanoid dynamics (Unitree's walking policy). E1: 1800 runs; E1b: 3360 runs over real ROS 2. |
| **Isaac Sim** | Next. | Richer scenes, simulated cameras (for the vision part), more skills. |
| **Real G1 + TRAV** | Goal. | Elias's TRAV navigation app on the robot: monitor on vs. off. |

**What stays the same across all four:** one monitor engine and one sensor vocabulary; only the
robot's adapter (which topics, how to turn them into facts) changes. The real G1, MuJoCo and
Isaac adapters already expose the same schema.

**MiniGrid caveats (say them before you are asked):** scripted reference plans, not the live
MAAOS planner; discrete-mode episodes. One failure there was my own spec error: a rule demanded
the two agents stay continuously aligned, but real pushing interleaves alignment and pushing,
so the monitor flagged correct runs. Relaxing the formula fixed it; a stronger judge model did
not — the fault was in the description, not the monitor.

---

## 5. Our numbers, in one place

**E1, short walk** (1800 runs = 10 failure types × 20 seeds × 3 spec versions × 3 reactions).
Falls caught in 1–7 s by every version. Stalls: full 15/15, flat 14/15, without the progress
check 1/15. Odometry drift: 1 of 8 caught by every version (distances are measured in the frame
that drifts); scan dropout: never seen (no fact checks data freshness). Fault-free runs: 3/40
false alarms. Success: 63% (report only), 43% (stop on alarm, p = 9·10⁻⁵), 52% (re-plan,
p = 0.03) — the drop is the 0.3 m proximity rule firing on safe passes (uncalibrated).

**E1b, fetch and deliver** (ROS 2; 1440 runs in the main table, 3360 in total).
Drop: caught 1 s vs 14 s; failed grasp: 4 s vs 19 s; earlier in 20/20 paired runs, later in
none (sign test p = 1.9·10⁻⁶). Delivered after re-plan: 34.5 s vs 63 s (drop), 36.5 s vs 72 s
(grasp). No deadline: 82% vs 84% (both from 35% with no action). Deadline 1.5×: 64% vs 36%
(p = 7·10⁻⁷); LTL only 36%; hand-written checks 81%; no monitor 34%. Fault-free: 3/40 false
alarms. Unplanned failures (wrong drop-off, too close): hand-written checks 40/40 silent →
0/40 with the monitor added; no measurable cost elsewhere (132 vs 136 of 160, p = 0.65).
Missed by everyone: slowness (19/20 still silent with the monitor) and detours.

**Statistics used:** Fisher's exact test for proportions, the sign test for paired latencies,
Wilson intervals; designs and predictions committed before each run.

---

## 6. Likely committee questions, with short answers

### Novelty

**"How is this different from standard LTL runtime verification (Bauer et al.)?"**
We use their monitor semantics. What we add is the stage structure: each stage has its own
invariant, exit condition, time limit and progress check. Without it, an LTL rule like
"eventually deliver" cannot fail early. We measured that directly: the same automata without the
stages ("LTL only") deliver 36% on time, like the flat spec; with stages 64%.

**"Isn't this just ROSMonitoring / RTAMT?"**
Those are monitoring engines for rules a person writes. Ours generates the rules and the stages
from a plain description, checks that every fact is measurable on this robot, and reads only
sensor data. The engine part is comparable; the description-to-monitor part is the contribution.

**"Why not just use a VLM (AHA, FailSafe, Foresight)?"**
They need failure data for training and give a score or a sentence, not a checkable reason.
Our monitor needs no training data, says exactly which stage and which rule broke, and its
verdict is reproducible. They are complementary: a VLM is the natural way to compute some of our
facts from a camera (that is Paper 2).

**"An LLM judge can also watch the robot. Why logic?"**
We tested it in MiniGrid: a free-text LLM judge gave +0.00 where the LTL monitor gave +1.00 on
the same runs, because "something is wrong" does not tell the re-planner *where*.

**"NL→LTL already exists (Lang2LTL, nl2spec)."**
Yes, and it stops at the formula. Those formulas are for planning or spec writing. We add the
stages and the grounding of every word to a sensor rule, and we run the result on a robot.

### Method

**"Isn't the stage machine just a hand-written state machine?"**
No one hand-wrote it: the LLM generated it from the description, in one attempt, and it was
saved before any experiment ran. What is hand-written is the robot's sensor vocabulary (once
per robot, not per task).

**"What if the LLM writes a wrong spec?"**
Automatic checks catch specs that cannot run (unknown facts, unmeasurable propositions), not
specs that are wrong but runnable. That is a real limit. The MiniGrid alignment rule is the
example: a wrong-but-runnable rule caused false alarms, and it was found by running clean
episodes. The fix we propose: run fault-free episodes first and accept a spec only if they
raise no alarms (in E1b, 3 of 40 fault-free runs raised one).

**"Why LTL and not STL?"**
Our facts are true/false at 1 Hz, so LTL is enough and keeps the automata small. Numeric
margins (STL robustness, as in RTAMT) would help with thresholds such as "too close"; that is a
natural extension.

**"Why 1 Hz?"**
Matches the evaluator's tick. The tick is not what limits us: a drop is caught 1 s after it
happens and a failed grasp after 4 s; the slow cases (a moved object, ~31 s; a stall, ~11 s with
its 10 s debounce) are slow because of the rules, not the rate. Faster ticks are possible; the
cost is noisier facts.

### The model

**"Is this really a POMDP?"**
The *problem* is a POMDP: the true stage and whether the box is held are hidden; we see noisy
messages; we choose continue / stop / re-plan. Our monitor today is a deterministic
approximation: the belief is one point (stage + automaton states), the update is one automaton
step, the policy is a fixed rule. No probabilities yet; that is the next step.

**"Where would the probabilities come from?"**
From the sensing layer: a learned or camera-based fact ("holding") with a confidence. Stoller et
al. (RV 2011) is the closest existing method (an HMM over the system); we would put the
probabilities on the facts and keep the stage structure.

### Evaluation

**"It's all simulation."**
Yes: MiniGrid, then MuJoCo with real humanoid dynamics, over real ROS 2 with the monitor as a
separate process, as it would run on the robot. Isaac Sim and the real G1 are next.

**"The grasp is fake and perception is a stand-in."**
True. The legs-only G1 model has no arms, so the box is attached; the box position comes from a
simulated detector with 2 cm noise and 5% missed detections. The monitor never sees the
simulator's truth.

**"Hand-written checks score better (81% vs 64%). Why bother?"**
They win only on failures someone foresaw. On failures nobody wrote a check for, they missed
40/40; adding our monitor made it 0/40 with no measurable cost. The monitor is generated, not
written, so it covers what the description says, not what an engineer remembered.

**"What did you miss?"**
Running slowly and detours that stay within the time limits (slowness: we predicted we would
catch it, and we did not). In E1, odometry drift was caught once in 8 and scan dropout never, because no fact checks
them. Fix: progress toward each stage's own target and limits calibrated from normal runs.

**"How many runs, which statistics?"**
20 seeds per failure type per arm; 1800 (E1) and 3360 (E1b) runs. Fisher's exact test, the sign
test for paired latencies, Wilson intervals. Designs and predictions committed before running.

### Future

**"What would show you are wrong?"**
If on the real robot, with real perception, monitor-on does not beat monitor-off on tasks with
time limits; or if fault-free runs produce frequent false alarms once thresholds meet real noise.

**"Next steps?"**
Isaac Sim (cameras, more skills), then the real G1 with the TRAV navigation app (monitor on vs.
off), and Paper 2: the full POMDP with learned facts, a real belief and decisions by expected
cost.
