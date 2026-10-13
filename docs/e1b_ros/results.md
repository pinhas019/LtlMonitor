# E1b over ROS 2: fetch and deliver (2080 episodes)

## Detection (policy off: the monitor reports, nothing acts)

Fault families: detected / injected · median ticks (1 tick = 1 s) from injection to the first intervention. Fault-free families: episodes with any intervention.

| family | full spec | flat (keeps terminal failure) | flat strict (no terminal failure) | LTL only (no phase machine) |
|---|---|---|---|---|
| carry_clear | 0/20 false alarms | 0/20 false alarms | 0/20 false alarms | 0/20 false alarms |
| carry_cluttered | 3/20 false alarms | 3/20 false alarms | 3/20 false alarms | 5/20 false alarms |
| carry_drop | 20/20 · 1 ticks | 20/20 · 14 ticks | 20/20 · 14 ticks | 20/20 · 14 ticks |
| carry_grasp_fail | 20/20 · 4 ticks | 20/20 · 19 ticks | 20/20 · 19 ticks | 20/20 · 19 ticks |
| carry_object_moved | 20/20 · 31 ticks | 20/20 · 32 ticks | 20/20 · 32 ticks | 20/20 · 32 ticks |
| carry_push | 13/13 · 1 ticks | 13/13 · 1 ticks | 13/13 · 1 ticks | 13/13 · 1 ticks |
| carry_skip_pickup | 20/20 · 21 ticks | 20/20 · 21 ticks | 20/20 · 21 ticks | 20/20 · 21 ticks |
| carry_stall | 14/17 · 11 ticks | 10/17 · 12 ticks | 11/17 · 106 ticks | 12/17 · 11 ticks |

## Detection of faults that mattered (policy off)

A fault *mattered* when the episode failed under `off` (judged from ground truth). Alarms on episodes that succeeded anyway are interventions a policy would have acted on for nothing.

| family | failed under off | detected · full spec | detected · flat (keeps terminal failure) | detected · flat strict (no terminal failure) | detected · LTL only (no phase machine) | alarms on episodes that succeeded anyway (full) |
|---|---|---|---|---|---|---|
| carry_clear | 0/20 | 0/0 | 0/0 | 0/0 | 0/0 | 0 |
| carry_cluttered | 0/20 | 0/0 | 0/0 | 0/0 | 0/0 | 3 |
| carry_drop | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_grasp_fail | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_object_moved | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_push | 13/20 | 13/13 | 13/13 | 13/13 | 13/13 | 0 |
| carry_skip_pickup | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_stall | 11/20 | 11/11 | 9/11 | 11/11 | 11/11 | 3 |

### …of which caught during the task, before the executor claimed success

The rest were caught only by the completion check (`completion_unverified`), when it is too late to save the attempt.

| family | failed | full spec | flat (keeps terminal failure) | flat strict (no terminal failure) | LTL only (no phase machine) |
|---|---|---|---|---|---|
| carry_drop | 20 | 20/20 | 0/20 | 0/20 | 0/20 |
| carry_grasp_fail | 20 | 20/20 | 0/20 | 0/20 | 0/20 |
| carry_object_moved | 20 | 7/20 | 0/20 | 0/20 | 0/20 |
| carry_push | 13 | 13/13 | 13/13 | 13/13 | 13/13 |
| carry_skip_pickup | 20 | 0/20 | 0/20 | 0/20 | 0/20 |
| carry_stall | 11 | 11/11 | 9/11 | 11/11 | 11/11 |

## The monitor's own conclusion against ground truth (policy off)

The monitor's last verdict, from the ROS messages alone: *success* (SATISFIED or terminal success), *failure* (VIOLATED or terminal failure) or *undecided*. Truth is the simulator's (object at the drop-off, not held, no fall). Agreement: the monitor said success exactly when the task succeeded.

| arm | n | succeeded: said success / undecided / failure | failed: said success / undecided / failure | agreement |
|---|---|---|---|---|
| full | 160 | 52 / 0 / 4 | 0 / 33 / 71 | 156/160 (98%) |
| flat | 160 | 52 / 0 / 4 | 0 / 82 / 22 | 156/160 (98%) |
| flat_strict | 160 | 53 / 0 / 3 | 0 / 80 / 24 | 157/160 (98%) |
| ltl_only | 160 | 49 / 3 / 4 | 0 / 80 / 24 | 153/160 (96%) |

## Paired: full spec against each flat arm, scenario by scenario

*detect*: policy `off`, episodes that failed, ticks from injection to the first intervention. *deliver*: policy `recover`, episodes both arms completed, simulated seconds to finish. Lower is better; the sign test counts the pairs where the full spec was lower against those where it was higher.

| family | against | measure | pairs | median full | median other | full lower / tie / higher | sign test p |
|---|---|---|---|---|---|---|---|
| carry_drop | flat | detect | 20 | 1.0 | 14.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat | deliver | 20 | 34.5 | 63.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat_strict | detect | 20 | 1.0 | 14.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat_strict | deliver | 20 | 34.5 | 63.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | ltl_only | detect | 20 | 1.0 | 14.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | ltl_only | deliver | 20 | 34.5 | 63.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat | detect | 20 | 4.0 | 19.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat | deliver | 20 | 36.5 | 72.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat_strict | detect | 20 | 4.0 | 19.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat_strict | deliver | 20 | 36.5 | 72.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | ltl_only | detect | 20 | 4.0 | 19.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | ltl_only | deliver | 19 | 37.0 | 74.0 | 19 / 0 / 0 | 3.8e-06 |
| carry_object_moved | flat | detect | 20 | 31.0 | 32.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | flat | deliver | 20 | 70.0 | 75.0 | 7 / 12 / 1 | 0.07 |
| carry_object_moved | flat_strict | detect | 20 | 31.0 | 32.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | flat_strict | deliver | 20 | 70.0 | 75.0 | 7 / 12 / 1 | 0.07 |
| carry_object_moved | ltl_only | detect | 20 | 31.0 | 32.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | ltl_only | deliver | 20 | 70.0 | 76.5 | 9 / 10 / 1 | 0.021 |
| carry_push | flat | detect | 13 | 1.0 | 1.0 | 0 / 13 / 0 | 1 |
| carry_push | flat | deliver | 7 | 31.0 | 31.0 | 0 / 7 / 0 | 1 |
| carry_push | flat_strict | detect | 13 | 1.0 | 1.0 | 0 / 13 / 0 | 1 |
| carry_push | flat_strict | deliver | 7 | 31.0 | 31.0 | 0 / 7 / 0 | 1 |
| carry_push | ltl_only | detect | 13 | 1.0 | 1.0 | 0 / 13 / 0 | 1 |
| carry_push | ltl_only | deliver | 7 | 31.0 | 31.0 | 0 / 7 / 0 | 1 |
| carry_skip_pickup | flat | detect | 20 | 21.0 | 21.0 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat | deliver | 20 | 57.5 | 57.5 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat_strict | detect | 20 | 21.0 | 21.0 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat_strict | deliver | 20 | 57.5 | 57.5 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | ltl_only | detect | 20 | 21.0 | 21.0 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | ltl_only | deliver | 20 | 57.5 | 57.5 | 1 / 19 / 0 | 1 |
| carry_stall | flat | detect | 9 | 11.0 | 11.0 | 0 / 9 / 0 | 1 |
| carry_stall | flat | deliver | 6 | 32.5 | 32.5 | 0 / 6 / 0 | 1 |
| carry_stall | flat_strict | detect | 11 | 11.0 | 106.0 | 11 / 0 / 0 | 0.00098 |
| carry_stall | flat_strict | deliver | 6 | 32.5 | 32.5 | 0 / 6 / 0 | 1 |
| carry_stall | ltl_only | detect | 11 | 11.0 | 11.0 | 0 / 11 / 0 | 1 |
| carry_stall | ltl_only | deliver | 6 | 32.5 | 32.5 | 0 / 6 / 0 | 1 |

## Outcomes (all families pooled; success judged from simulator ground truth)

| arm | policy | n | success (95% CI) | Δ vs off | mean recoveries |
|---|---|---|---|---|---|
| full | off | 160 | 35% (28–43) | — | 0.00 |
| full | detect | 160 | 31% (25–39) | -4 pp (p=0.55) | 0.00 |
| full | recover | 160 | 82% (76–88) | +48 pp (p=2.9e-18) | 0.70 |
| flat | off | 160 | 35% (28–43) | — | 0.00 |
| flat | detect | 160 | 32% (26–40) | -2 pp (p=0.72) | 0.00 |
| flat | recover | 160 | 84% (78–89) | +49 pp (p=7e-20) | 0.68 |
| flat_strict | off | 160 | 35% (28–43) | — | 0.00 |
| flat_strict | detect | 160 | 33% (26–41) | -2 pp (p=0.81) | 0.00 |
| flat_strict | recover | 160 | 84% (78–89) | +49 pp (p=7e-20) | 0.61 |
| ltl_only | off | 160 | 35% (28–43) | — | 0.00 |
| ltl_only | detect | 160 | 31% (24–38) | -4 pp (p=0.48) | 0.00 |
| ltl_only | recover | 160 | 83% (77–88) | +48 pp (p=8.6e-19) | 0.72 |

## Against a hand-coded closed-loop executor

The closed-loop executor checks its own work from the same perception ("still holding it?", "is it at the drop-off?") and re-plans on its own; no monitor acts. Success, and median simulated seconds to deliver over the episodes that delivered.

| family | hand-coded checks, no monitor | full spec + re-plan | no monitor (open loop) |
|---|---|---|---|
| carry_clear | 20/20 · 34.0 s | 20/20 · 34.0 s | 20/20 · 34.0 s |
| carry_cluttered | 20/20 · 35.0 s | 19/20 · 34.0 s | 20/20 · 35.0 s |
| carry_drop | 20/20 · 34.5 s | 20/20 · 34.5 s | 0/20 |
| carry_grasp_fail | 20/20 · 36.0 s | 20/20 · 36.5 s | 0/20 |
| carry_object_moved | 20/20 · 46.0 s | 20/20 · 70.0 s | 0/20 |
| carry_push | 7/20 · 32.0 s | 7/20 · 31.0 s | 7/20 · 31.0 s |
| carry_skip_pickup | 20/20 · 32.5 s | 20/20 · 57.5 s | 0/20 |
| carry_stall | 9/20 · 33.0 s | 6/20 · 32.5 s | 9/20 · 33.0 s |
| **all** | 136/160 · 35.0 s | 132/160 · 36.0 s | 56/160 · 34.0 s |

Pooled success, hand-coded checks vs full spec + re-plan: Fisher p = 0.65.

## Delivered by a deadline

Deadline = k × the scenario's nominal time to deliver (straight-line walk start → object → drop-off at 0.22 m/s, the median effective speed of the fault-free `clear` runs, plus 4 s of grasp and release). A deadline only judges an episode, so it is computed from the same records; k = ∞ is plain success. All 160 episodes of each way of running the task, every family pooled.

| way of running the task | 1× | 1.25× | 1.5× | 2× | 3× | no deadline |
|---|---|---|---|---|---|---|
| full spec + re-plan | 18% | 58% | 64% | 73% | 82% | 82% |
| flat (keeps terminal failure) + re-plan | 16% | 34% | 36% | 54% | 84% | 84% |
| flat strict (no terminal failure) + re-plan | 16% | 34% | 36% | 54% | 84% | 84% |
| LTL only (no phase machine) + re-plan | 15% | 32% | 36% | 51% | 83% | 83% |
| hand-coded checks, no monitor | 22% | 74% | 81% | 84% | 85% | 85% |
| no monitor (open-loop executor) | 15% | 34% | 34% | 34% | 35% | 35% |

Fisher p, full spec + re-plan against each, per deadline:

| against | 1× | 1.25× | 1.5× | 2× | 3× | ∞ |
|---|---|---|---|---|---|---|
| flat (keeps terminal failure) + re-plan | 0.76 | 3e-05 | 1.3e-06 | 0.00047 | 0.76 | 0.76 |
| flat strict (no terminal failure) + re-plan | 0.76 | 3e-05 | 1.3e-06 | 0.00047 | 0.76 | 0.76 |
| LTL only (no phase machine) + re-plan | 0.65 | 1.1e-05 | 7.4e-07 | 8.2e-05 | 1 | 1 |
| hand-coded checks, no monitor | 0.33 | 0.0021 | 0.0011 | 0.02 | 0.65 | 0.65 |
| no monitor (open-loop executor) | 0.65 | 3e-05 | 1.2e-07 | 4.3e-12 | 2.9e-18 | 2.9e-18 |

## Causes of failure

| arm | policy | causes |
|---|---|---|
| closed_loop | off | fell 13, timeout 11 |
| flat | detect | monitor:completion_unverified 80, fell 13, monitor:terminal_failure 11, monitor:collision_imminent 3, timeout 1 |
| flat | off | false_arrival 80, fell 13, timeout 11 |
| flat | recover | fell 13, monitor:terminal_failure 11, monitor:collision_imminent 1 |
| flat_strict | detect | monitor:completion_unverified 80, fell 13, monitor:TIMEOUT 11, monitor:collision_imminent 3 |
| flat_strict | off | false_arrival 80, fell 13, timeout 11 |
| flat_strict | recover | fell 13, timeout 11, monitor:collision_imminent 1 |
| full | detect | monitor:completion_unverified 33, monitor:TIMEOUT 30, monitor:phase:Carry:invariant 20, fell 13, monitor:terminal_failure 9, monitor:collision_imminent 3, timeout 2 |
| full | off | false_arrival 80, fell 13, timeout 11 |
| full | recover | fell 13, monitor:terminal_failure 6, timeout 5, monitor:TIMEOUT 3, monitor:collision_imminent 1 |
| ltl_only | detect | monitor:completion_unverified 83, fell 13, monitor:terminal_failure 12, monitor:collision_imminent 3 |
| ltl_only | off | false_arrival 80, fell 13, timeout 11 |
| ltl_only | recover | fell 13, monitor:terminal_failure 8, timeout 3, monitor:completion_unverified 2, monitor:collision_imminent 1 |

## Full table (arm × policy × family)

| arm | policy | family | n | success (95% CI) | Δ vs off [95% CI] (p) | precision | recall | F1 | TTD (ticks) | recoveries |
|---|---|---|---|---|---|---|---|---|---|---|
| flat | detect | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat | detect | carry_cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| flat | detect | carry_drop | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat | detect | carry_grasp_fail | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat | detect | carry_object_moved | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat | detect | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat | detect | carry_skip_pickup | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat | detect | carry_stall | 20 | 40% (22%–61%) | -5 pp [-35, +25] (p=1) | 100% | 65% | 0.79 | 11.7 | 0.00 |
| flat | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat | off | carry_push | 20 | 35% (18%–57%) | — | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 59% | 0.74 | 12.1 | 0.00 |
| flat | recover | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat | recover | carry_cluttered | 20 | 95% (76%–99%) | -5 pp [-15, +0] (p=1) | 0% | — | — | — | 0.30 |
| flat | recover | carry_drop | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 14.5 | 1.00 |
| flat | recover | carry_grasp_fail | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 19.7 | 1.00 |
| flat | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 32.6 | 1.00 |
| flat | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.00 |
| flat | recover | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 71% | 0.83 | 11.8 | 1.15 |
| flat_strict | detect | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat_strict | detect | carry_cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| flat_strict | detect | carry_drop | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat_strict | detect | carry_grasp_fail | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat_strict | detect | carry_object_moved | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat_strict | detect | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat_strict | detect | carry_skip_pickup | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat_strict | detect | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 65% | 0.79 | 104.9 | 0.00 |
| flat_strict | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat_strict | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat_strict | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat_strict | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat_strict | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat_strict | off | carry_push | 20 | 35% (18%–57%) | — | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat_strict | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat_strict | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 65% | 0.79 | 104.9 | 0.00 |
| flat_strict | recover | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat_strict | recover | carry_cluttered | 20 | 95% (76%–99%) | -5 pp [-15, +0] (p=1) | 0% | — | — | — | 0.30 |
| flat_strict | recover | carry_drop | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 14.5 | 1.00 |
| flat_strict | recover | carry_grasp_fail | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 19.7 | 1.00 |
| flat_strict | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 32.6 | 1.00 |
| flat_strict | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat_strict | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.00 |
| flat_strict | recover | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 65% | 0.79 | 104.9 | 0.55 |
| full | detect | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| full | detect | carry_cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| full | detect | carry_drop | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 1.0 | 0.00 |
| full | detect | carry_grasp_fail | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 3.9 | 0.00 |
| full | detect | carry_object_moved | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 25.9 | 0.00 |
| full | detect | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| full | detect | carry_skip_pickup | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 21.3 | 0.00 |
| full | detect | carry_stall | 20 | 30% (15%–52%) | -15 pp [-45, +15] (p=0.514) | 100% | 71% | 0.83 | 12.7 | 0.00 |
| full | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| full | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| full | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 1.0 | 0.00 |
| full | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 4.0 | 0.00 |
| full | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 25.9 | 0.00 |
| full | off | carry_push | 20 | 35% (18%–57%) | — | 100% | 100% | 1.00 | 1.2 | 0.00 |
| full | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| full | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 82% | 0.90 | 12.4 | 0.00 |
| full | recover | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| full | recover | carry_cluttered | 20 | 95% (76%–99%) | -5 pp [-15, +0] (p=1) | 0% | — | — | — | 0.30 |
| full | recover | carry_drop | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 1.0 | 1.00 |
| full | recover | carry_grasp_fail | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 3.9 | 1.10 |
| full | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 25.9 | 1.00 |
| full | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| full | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.00 |
| full | recover | carry_stall | 20 | 30% (15%–52%) | -15 pp [-45, +15] (p=0.514) | 100% | 71% | 0.83 | 12.8 | 1.20 |
| ltl_only | detect | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| ltl_only | detect | carry_cluttered | 20 | 75% (53%–89%) | -25 pp [-45, -10] (p=0.0471) | 0% | — | — | — | 0.00 |
| ltl_only | detect | carry_drop | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 14.5 | 0.00 |
| ltl_only | detect | carry_grasp_fail | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 19.7 | 0.00 |
| ltl_only | detect | carry_object_moved | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 32.6 | 0.00 |
| ltl_only | detect | carry_push | 20 | 30% (15%–52%) | -5 pp [-35, +25] (p=1) | 93% | 100% | 0.96 | 1.2 | 0.00 |
| ltl_only | detect | carry_skip_pickup | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 21.3 | 0.00 |
| ltl_only | detect | carry_stall | 20 | 40% (22%–61%) | -5 pp [-35, +25] (p=1) | 100% | 71% | 0.83 | 11.8 | 0.00 |
| ltl_only | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| ltl_only | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| ltl_only | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 14.5 | 0.00 |
| ltl_only | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 19.7 | 0.00 |
| ltl_only | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 32.6 | 0.00 |
| ltl_only | off | carry_push | 20 | 35% (18%–57%) | — | 93% | 100% | 0.96 | 1.2 | 0.00 |
| ltl_only | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| ltl_only | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 71% | 0.83 | 11.8 | 0.00 |
| ltl_only | recover | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| ltl_only | recover | carry_cluttered | 20 | 90% (70%–97%) | -10 pp [-25, +0] (p=0.487) | 0% | — | — | — | 0.40 |
| ltl_only | recover | carry_drop | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 14.5 | 1.05 |
| ltl_only | recover | carry_grasp_fail | 20 | 95% (76%–99%) | +95 pp [+85, +100] (p=3.05e-10) | 100% | 100% | 1.00 | 19.7 | 1.15 |
| ltl_only | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 32.6 | 1.10 |
| ltl_only | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| ltl_only | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.05 |
| ltl_only | recover | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 71% | 0.83 | 11.8 | 1.05 |
