# Skill progress monitoring: phone notes

13 slides, about 50 seconds each, 10–12 minutes. Numbers match the PDF pages.

## Before you start

### When they attack
- Agree with the small point.
- Say what you claim, and give one number.
- Name the gap yourself.

### Numbers
- Drop: **1 s** vs 14 s. Failed grasp: **4 s** vs 19 s.
- Earlier in **all 20** paired runs.
- Deadline: **64%** vs 36%. No deadline: 82% vs 84%.
- Unplanned failures: **40 of 40** missed by hand-written checks, 0 of 40 with the monitor.
- False alarms: 3 of 40, from the 0.3 m rule.

## 1 · Title
- Robots fail mid-task and don't know it. I catch it when it happens.

## 2 · The problem
- Real run: box slipped, robot walked on, reported success.
- The robot knows what it commanded, not what happened.

## 3 · Research question
- Do stages catch failures earlier, and does that improve success?
- H1 earlier. H2 more success with a deadline. H3 beats hand-written checks.
- H0, said in advance: falls, no change.

## 4 · Related work
- Two streams: how to describe a skill, how to watch it run.
- Most work improves one. Ours: words → LLM writes stages + rules → monitor on sensors.
> Time check: about 3 minutes here.

## 5 · Background
- LTL: G always, F eventually. Each rule becomes a small automaton.
- "Eventually deliver" can never fail early. That's the gap.

## 6 · Our idea: stages
- Each stage: must-hold rules, a time limit, progress.
- Carry: "holding" must stay true, so a drop is caught next second.
- Written by the LLM from plain words.

## 7 · Formal model
- Each second: sensors → facts → every rule steps.
- Stage fails if must-hold breaks, time runs out, or no progress.

## 8 · POMDP
- The stage is hidden state: "not holding" means different things per stage.
- Early detection helps only with a deadline. Predicted, then measured.
- Say: today the belief is a single point.
> Time check: about 6 minutes here.

## 9 · Method
- LLM writes the spec once; checked, frozen before any run.
- Monitor reads only sensors, never the planner.

## 10 · Experiment
- G1 in MuJoCo, ROS 2, failures caused on purpose.
- Drop: 1 s vs 14 s. Grasp: 4 s vs 19 s. Earlier in all 20 runs.

## 11 · Does early matter?
- No deadline: all ~83%. Deadline: **64% vs 36%**.
- Hand-written checks 81%, but only for failures someone foresaw.

## 12 · Results
- H1, H2, H3 supported. H0 as predicted.
- Missed: slowness, detours. I report them.
> Time check: about 9 minutes here.

## 13 · To be done
- MiniGrid + MAAOS (done) → MuJoCo (now) → Isaac Sim → real G1.
- Calibrate limits; specs from several LLMs; full POMDP with a camera.
- Stop. "Thank you, questions?"

## Backup slides (PDF pages)
- 15–16 Related work in detail
- 17 Model predictions P1–P5
- 18 Failures nobody planned for (40 → 0)
- 19 One run, second by second
- 20 Experiment 1: walking
- 21 MuJoCo test bed
- 22 MiniGrid + MAAOS
- 23 Demo
- 24 References

# Committee questions

## Q1 · "P1 is a tautology"
- Yes, by design. The point is the rule exists only with stages.
- LTL alone: 14 s. Stages: 1 s. Deadline: 64% vs 36%.

## Q2 · "Flat is a straw man"
- True, an expert could write it in LTL. Flat is an ablation.
- The claim is who writes it: hand-written checks missed 40 of 40.
> Avoid: "replace the engineer".

## Q3 · "The POMDP is decorative"
- I don't solve it. It predicted the deadline effect: 64/36 with, 82/84 without.

## Q4 · "Why trust the LLM?"
- Checked, readable, frozen. Gap: rules that run but are wrong (3 false alarms of 40).
- Fix: accept a spec only after clean runs.

## Q5 · "Circular experiment?"
- Spec came from words, not the faults. Unplanned failures: 40 → 0.
- I report misses: slowness, detours.

## Q6 · "Statistics?"
- The claim comes from the model. The runs confirm it: 20 of 20.
> If pushed: "Clearly significant; it's in my backup notes."

## Q7 · "Nothing new"
- New: an LLM-generated monitor with stages, on the robot's sensors.
- nl2spec stops at a formula; ROSMonitoring needs hand-written rules.

## Q8 · "Who chose 0.3 / 0.5?"
- Not the LLM: "holding" is in the robot dictionary, once per robot.
- The LLM's own thresholds aren't calibrated yet.

## Q9 · "1 Hz is too slow"
- Not reflex safety: the balance controller handles falls.
- Task decisions take seconds.

## Q10 · "Weakest part?"
- One spec per skill from one LLM. Next: several LLMs.
- Stages work even if written by hand.
