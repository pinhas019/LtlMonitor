# Skill progress monitoring: phone notes

Slide numbers match the PDF pages. Short bullets: say them in your own words.

## Before you start

### When they attack
- 1. Agree with the small point.
- 2. Say what you actually claim.
- 3. Give one number.
- 4. Name the gap yourself, before they do.

### Never say
- p-values. Say counts: "20 of 20 runs".
- "I replace the engineer". Say "less expertise needed".
- "safety monitor". Say "task rules" or "must-hold rules".
- "one automaton". Say "one monitor".

### Numbers
- Drop caught: **1 s** with stages, 14 s without.
- Failed grasp: **4 s** vs 19 s.
- Earlier in **all 20** paired runs, later in none.
- Deadline: **64%** with stages, 36% without (LTL only 36%, hand-written checks 81%).
- No deadline: 82% vs 84%, no difference (as predicted).
- Unplanned failures: hand-written checks missed **40 of 40**; with the monitor, 0 of 40.
- False alarms: 3 of 40 clean runs, all from the 0.3 m "too close" rule.
- Falls: 1 s in every version (H0, as predicted).
- Experiment 1: 1800 runs. Experiment 2: 3360 runs.

## 1 · Title
- "Skill progress monitoring: catching robot failures while they happen."
- Supervisor: Prof. Ronen Brafman.
- One sentence: a robot often fails in the middle of a task and does not know it. I build a watcher that catches it at that moment.

## 2 · The problem
- The picture is a real run: the box slipped while carrying, and the robot walked on and reported success.
- The robot's program knows what it commanded, not what really happened.
- Finding out at the end is late: the time is gone, and some failures can't be undone.
- So we want an independent watcher that sees the failure when it happens.

## 3 · Research question
- RQ: if the monitor knows the stages of a skill, does it catch failures earlier, and does that improve success?
- H1: caught earlier.
- H2: more success with a deadline; no change without one.
- H3: catches what hand-written checks miss.
- H0, said in advance: falls show no change, because every stage checks "upright".
- Picture: with stages the alarm comes right after the fault; without, at the end, after the deadline.

## 4 · Related work: two streams
- The field moves in two streams: how to describe a skill, and how to watch it run using that description.
- Describe: words, logic, videos, code. Watch: state machines, LLMs, vision models.
- Most papers improve one stream.
- Our path (blue): plain words, then the LLM writes rules and stages, then the monitor runs them on the robot's sensors.
> If asked "nothing new": see [Q7](#q7).

## 5 · Stream 1: describing a skill
- Words to logic (Lang2LTL, nl2spec, NL2TL): they stop at a formula, for planning or writing specs. No stages, nothing running on a robot.
- Logic by experts (LTL, STL / RTAMT): precise, but a person writes every rule, and the rules are flat.
- Videos and demos (Vazquez-Chanlatte 2018, RoboCLIP 2023): need examples; the result is hard to read or edit.
- Code: our hand-written checks. Strong on foreseen failures (81%), silent on unforeseen ones (40 of 40).
> If asked for detail: nl2spec got 16 of 36 alone, 31 of 36 with a human fixing it.

## 6 · Stream 2: monitoring a skill
- State machines: Bauer 2011 (LTL3: true, false, "?"), which we build on. ROSMonitoring and RTAMT are engines for hand-written rules. None knows the task's stages.
- LLM reasoning: REFLECT explains a failure after the fact. In our MiniGrid pilot a free-text LLM judge gave +0.
- Vision models (AHA, FailSafe, Foresight): need failure data, and give no readable reason.
- The gap: nobody generates a stage-aware monitor from a plain description.

## 7 · Background: what is a monitor?
- A monitor is a program that watches the robot and checks rules.
- LTL: G = always, F = eventually.
- The tool Spot turns each rule into a small automaton. Each second it takes one step with the measured facts.
- "Always upright" fails the moment the robot falls.
- "Eventually deliver" can never fail early: delivery could still happen. This is the weakness we fix.

## 8 · Our idea: the stages of the task
- Stages ("progress states"): Walk, Grasp, Carry, Place.
- Each stage has: what must stay true, what ends it, a time limit, and it must keep progressing.
- The LLM wrote these stages from the plain description.
- Key example: in Carry, "holding" must stay true. A drop breaks it the next second.
- Without stages you can't say "must hold", because it is false at the start.

## 9 · Formal model
- Each second, the sensors become true/false facts (the labelling).
- Spec = facts, LTL rules, safety rules, stages, end conditions. The LLM writes all of it.
- Stage = enter, must-hold, progress, exit, time limit T, miss limit k (3).
- Each second: every rule steps. The stage fails if must-hold is false, the time is up, or progress was missed k times. It moves on when its exit holds.
- This is exactly what the code does.
> If asked "show me the automaton": it is one monitor, a stage machine running beside separate small automata, not one product automaton.
> If asked "who chose 0.3 and 0.5?": see [Q8](#q8).

## 10 · Model predictions vs. measurements
- The point: the results follow from the model. They are not luck.
- P1: a broken must-hold rule is caught the same second. Measured: 1 s.
- P2: "eventually" rules have no failing state, so LTL alone misses the drop until the end. Measured: 14 s.
- P3: a stuck stage fails within its time limit. Failed grasp: 4 s vs 19 s.
- P4: the flat spec can't contain "holding", so it sees the drop only at the end.
- P5: shared rules (upright) are the same, so falls show no difference.
- Say it yourself: stages add no expressiveness; G(grasped → (holding U near_dropoff)) is LTL. The point is that the LLM writes it, because each stage asks "what must stay true here?"
> If asked "P1 is a tautology": see [Q1](#q1).

## 11 · The decision view: a POMDP
- POMDP: a hidden state, noisy observations, a belief, actions.
- The stage is part of the hidden state. "Not holding" is normal while walking, and a failure while carrying.
- Say first: today the belief is one point, the update is the monitor step, and the action is a fixed rule.
- Value of information: on time only if detection + recovery fits in the time left.
- It predicts help with a deadline and none without. Measured: 64% vs 36%, and 82% vs 84%.
> If asked "decorative?": see [Q3](#q3).

## 12 · Method
- Task in words, then the LLM (Claude) writes the whole spec in one try; it is checked and saved before any run.
- Checks: the spec loads, and every fact maps to a sensor the robot really has.
- The evaluator turns messages into facts each second, and the monitor checks the rules. They are separate ROS 2 programs, like on a real robot.
- The monitor never reads the planner's status. A test enforces this.
> If asked "why trust the LLM?": see [Q4](#q4).

## 13 · First test bed: MiniGrid + MAAOS
- Pilot: continuous MiniGrid, integrated with MAAOS (Fouzi's multi-agent project).
- Tasks: push a box to a goal; two agents line up and push together.
- Corrupted plan: re-plan fixes every seed (+1.00). Deadlock: LTL + re-plan recovers every seed (about 45 steps).
- Detect only: +0. Free-text LLM judge: +0. Clean runs: no false alarms.
- Say it yourself: the plans were scripted, not the live MAAOS planner. One rule I wrote was too strict, and I fixed it.

## 14 · Test bed: humanoid in MuJoCo
- Unitree G1 in MuJoCo, walking with Unitree's own controller.
- Each failure is injected at a known time, so we measure how fast it is caught.
- "Without stages" = the same spec with all stages merged into one: same facts, same rules.
- Success is judged by the simulator's truth, which the monitor never sees.
> If asked "flat is a straw man": see [Q2](#q2).

## 15 · Experiment 1: a short walk
- 1800 runs: 10 failure types × 20 seeds × 3 versions × 3 reactions.
- Walking: stages add little. Falls are caught in 1–7 s by every version.
- The difference is stalls: with the progress check 15 of 15, flat 14 of 15, without progress 1 of 15.
- Figure: the planner still commands 0.5 m/s, but the robot has stopped. A monitor trusting the planner sees nothing.

## 16 · Experiment 2: fetch and deliver
- Walk, grasp, carry 2.5–4 m, place. Separate ROS 2 programs, and a noisy box detector (2 cm noise, 5% missed).
- Drop: caught 1 s after, because Carry requires holding. Without stages: 14 s, when the robot claims success.
- Failed grasp: 4 s vs 19 s, from the Grasp time limit.
- Earlier in all 20 paired runs, later in none.
> If asked about statistics: see [Q6](#q6). No p-values.

## 17 · One run, second by second
- Seed 0, from the live demo page.
- 21.6 s: the box drops. 22 s: the Carry stage fails.
- Bottom: the LTL automaton stays in state 3. It has no failing state.
- The whole idea in one picture: the stage catches what LTL alone can't.

## 18 · Does catching early matter?
- On an alarm, the robot re-plans.
- No deadline: every monitor gets 82–84%, because a late re-plan still works.
- Deadline 1.5×: 64% with stages, 36% without. LTL alone: 36%.
- Hand-written checks: 81%, but someone had to foresee each failure (next slide).
> If asked "hand-written checks beat you": they win only on failures someone foresaw. On the others they missed 40 of 40.

## 19 · Failures nobody planned for
- New failures, not covered by the hand-written checks: wrong drop-off, and too close to a wall.
- Hand-written checks: 40 of 40 missed. With our monitor: 0 of 40, with no cost elsewhere.
- Missed by everyone: too slow, and detours. My prediction for "slow" was wrong: say so.
> If asked "isn't this circular?": see [Q5](#q5).

## 20 · Hypotheses and results
- Each hypothesis was written down before the run.
- H1, H2 and H3 supported; H0 as predicted.
- Misses reported: slow, detours, skipped pick-up. Fix: progress toward each stage's own target, and calibrated limits.
- How sure: counts. 20 of 20 runs; 64% vs 36% over 160 runs per version.

## 21 · What we learned
- Read the four lines on the slide.
- Demo if there is time: open localhost:8080, click "Dropped object: full spec", press Pause at 22 s.

## 22 · To be done
- Platforms: MiniGrid + MAAOS (done), then MuJoCo G1 (now), then Isaac Sim, then the real G1 with Elias's TRAV app.
- Same engine everywhere; only the robot adapter changes.
- Fixes: calibrate limits from normal runs; progress toward each stage's target; restart at the current stage.
- Specs from several LLMs, to test reliability.
- Paper 2, the full POMDP: camera facts with probabilities, a real belief, and actions chosen by cost.
- Limits: the legs-only G1 can't grasp (the box is attached), and the detector is simulated.
> If asked "weakest part?": see [Q10](#q10).

## 23 · References
- Every entry is a link. Don't read them out.
- Stop here and invite questions.

# Committee questions

## Q1 · "P1 is a tautology"
- Yes, by design. The point is that the rule exists at all.
- "Holding while carrying" only exists with stages.
- LTL alone can't fail early (P2): 14 s vs 1 s.
- It changes outcomes: 64% vs 36% with a deadline.

## Q2 · "Your flat spec is a straw man"
- True: an expert can write G(grasped → (holding U near_dropoff)). Stages add no expressiveness.
- Flat is an ablation: it removes one thing, the stages.
- The claim is who writes the rule. Hand-written checks missed 40 of 40.
- Next test: ask an LLM for flat LTL with no stages.
> Avoid: "I replace the engineer". Say "less expertise needed".

## Q3 · "The POMDP is decorative"
- I don't solve it. It is the model of the problem.
- It explains why stages matter: the same observation means different things in different stages.
- It predicted the deadline effect, including no effect without one: 64/36 vs 82/84.
- It states my assumption: correct facts make the single-point belief exact. With a noisy camera I need a real belief (Paper 2).
> Avoid: "because the robot has partial observability".

## Q4 · "Why trust a monitor written by an LLM?"
- Checked: the spec must load, and every fact must map to a real sensor. It passed on the first of 3 tries.
- Readable, and frozen before any run.
- Gap: a rule that runs but means the wrong thing. The 0.3 m rule gave 3 false alarms in 40.
- Fix: accept a spec only after clean runs raise no alarms. Actions are a ladder, so a doubtful rule can just warn.
> Follow-up "same Claude built it and wrote the spec?": a real risk. The spec was frozen first. Next: specs from several LLMs.

## Q5 · "Isn't the experiment circular?"
- The spec came from the description, not the fault list, and was frozen before the runs.
- Unplanned failures: 40 of 40 missed by hand-written checks, 0 of 40 with the monitor.
- I report misses: slowness still missed in 19 of 20 runs, plus detours. Falls showed no change, as predicted.
- Two skills, two test beds. Still simulation, so Isaac Sim and the real G1 come next.
- It covers what the description says, not everything.

## Q6 · "What do p-values mean on seeded runs?"
- I don't rest the claim on a statistical test.
- The claim comes from the model (P1), stated before running anything.
- The runs confirm it: earlier in all 20 paired runs. Success: 160 runs per version, 64% vs 36%.
> If pushed: "It is clearly significant. The test is in my backup notes; happy to show it after." Then stop.

## Q7 · "Nothing here is new"
- One sentence: "What's new is generating a stage-structured monitor from plain words, grounded in the robot's sensors, and showing that the stages are what catch failures in time."
- nl2spec and Lang2LTL stop at a formula.
- ROSMonitoring is an engine for hand-written rules.
- Behaviour trees are the executor, written by hand. Mine is an independent observer.
- Evidence: the same rules without stages got 36%, with stages 64%.
> Avoid: "one automaton". It is one monitor.

## Q8 · "Who chose 0.3 m and 0.5 m?"
- Not the LLM. "Holding" is defined in the robot's dictionary (the adapter), once per robot.
- The LLM only writes "holding must stay true in Carry".
- On the real G1 I update how holding is measured (camera). The task rules stay the same.
- The LLM's own numbers (too close = 0.3 m) are uncalibrated: 3 false alarms in 40. Calibration is next.
> Be ready: why 0.3 and 0.5? (box clearly off the floor; about the arm's reach).

## Q9 · "1 Hz is useless for safety"
- Agree: it is not a reflex safety layer. The title says skill progress.
- The balance controller (hundreds of Hz) handles falls.
- The monitor answers "is the task on track, and which stage broke?" Those decisions take seconds.
- The rate is a parameter. The slow detections come from the rules (a 10 s stall window), not the rate.
> Avoid: "safety monitor". Don't claim a rate you never tested.

## Q10 · "What is the weakest part?"
- Weakest: LLM reliability. One spec per skill, from one model, in one try.
- Next: several specs from several models, plus a clean-run acceptance test.
- What survives: "eventually can't fail early" is math. Stages catch failures earlier and help under deadlines, even if a person writes them.
- Close with: "The LLM makes it cheaper; the stages make it work."
> Avoid: "simulation". Every robotics thesis has it, so it sounds like a dodge.
