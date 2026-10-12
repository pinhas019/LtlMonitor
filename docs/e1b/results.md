# E1b results: fetch and deliver (1440 episodes)

## Detection (policy off: the monitor reports, nothing acts)

Fault families: detected / injected · median ticks (1 tick = 1 s) from injection to the first intervention. Fault-free families: episodes with any intervention.

| family | full spec | flat (keeps terminal failure) | flat strict (no terminal failure) |
|---|---|---|---|
| carry_clear | 0/20 false alarms | 0/20 false alarms | 0/20 false alarms |
| carry_cluttered | 3/20 false alarms | 3/20 false alarms | 3/20 false alarms |
| carry_drop | 20/20 · 1 ticks | 20/20 · 14 ticks | 20/20 · 14 ticks |
| carry_grasp_fail | 20/20 · 4 ticks | 20/20 · 19 ticks | 20/20 · 19 ticks |
| carry_object_moved | 20/20 · 31 ticks | 20/20 · 32 ticks | 20/20 · 32 ticks |
| carry_push | 13/13 · 1 ticks | 13/13 · 1 ticks | 13/13 · 1 ticks |
| carry_skip_pickup | 20/20 · 21 ticks | 20/20 · 21 ticks | 20/20 · 21 ticks |
| carry_stall | 14/17 · 11 ticks | 12/17 · 11 ticks | 11/17 · 105 ticks |

## Detection of faults that mattered (policy off)

A fault *mattered* when the episode failed under `off` (judged from ground truth). Alarms on episodes that succeeded anyway are interventions a policy would have acted on for nothing.

| family | failed under off | detected · full spec | detected · flat (keeps terminal failure) | detected · flat strict (no terminal failure) | alarms on episodes that succeeded anyway (full) |
|---|---|---|---|---|---|
| carry_clear | 0/20 | 0/0 | 0/0 | 0/0 | 0 |
| carry_cluttered | 0/20 | 0/0 | 0/0 | 0/0 | 3 |
| carry_drop | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_grasp_fail | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_object_moved | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_push | 13/20 | 13/13 | 13/13 | 13/13 | 0 |
| carry_skip_pickup | 20/20 | 20/20 | 20/20 | 20/20 | 0 |
| carry_stall | 11/20 | 11/11 | 11/11 | 11/11 | 3 |

### …of which caught during the task, before the executor claimed success

The rest were caught only by the completion check (`completion_unverified`), when it is too late to save the attempt.

| family | failed | full spec | flat (keeps terminal failure) | flat strict (no terminal failure) |
|---|---|---|---|---|
| carry_drop | 20 | 20/20 | 0/20 | 0/20 |
| carry_grasp_fail | 20 | 20/20 | 0/20 | 0/20 |
| carry_object_moved | 20 | 8/20 | 0/20 | 0/20 |
| carry_push | 13 | 13/13 | 13/13 | 13/13 |
| carry_skip_pickup | 20 | 0/20 | 0/20 | 0/20 |
| carry_stall | 11 | 11/11 | 11/11 | 11/11 |

## Paired: full spec against each flat arm, scenario by scenario

*detect*: policy `off`, episodes that failed, ticks from injection to the first intervention. *deliver*: policy `recover`, episodes both arms completed, simulated seconds to finish. Lower is better; the sign test counts the pairs where the full spec was lower against those where it was higher.

| family | against | measure | pairs | median full | median other | full lower / tie / higher | sign test p |
|---|---|---|---|---|---|---|---|
| carry_drop | flat | detect | 20 | 1.0 | 14.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat | deliver | 20 | 34.5 | 63.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat_strict | detect | 20 | 1.0 | 14.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_drop | flat_strict | deliver | 20 | 34.5 | 63.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat | detect | 20 | 4.0 | 19.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat | deliver | 20 | 37.0 | 72.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat_strict | detect | 20 | 4.0 | 19.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_grasp_fail | flat_strict | deliver | 20 | 37.0 | 72.0 | 20 / 0 / 0 | 1.9e-06 |
| carry_object_moved | flat | detect | 20 | 31.0 | 32.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | flat | deliver | 20 | 70.0 | 75.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | flat_strict | detect | 20 | 31.0 | 32.0 | 7 / 13 / 0 | 0.016 |
| carry_object_moved | flat_strict | deliver | 20 | 70.0 | 75.0 | 7 / 13 / 0 | 0.016 |
| carry_push | flat | detect | 13 | 1.0 | 1.0 | 0 / 13 / 0 | 1 |
| carry_push | flat | deliver | 7 | 31.0 | 31.0 | 0 / 7 / 0 | 1 |
| carry_push | flat_strict | detect | 13 | 1.0 | 1.0 | 0 / 13 / 0 | 1 |
| carry_push | flat_strict | deliver | 7 | 31.0 | 31.0 | 0 / 7 / 0 | 1 |
| carry_skip_pickup | flat | detect | 20 | 21.0 | 21.0 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat | deliver | 20 | 57.5 | 57.5 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat_strict | detect | 20 | 21.0 | 21.0 | 0 / 20 / 0 | 1 |
| carry_skip_pickup | flat_strict | deliver | 20 | 57.5 | 57.5 | 0 / 20 / 0 | 1 |
| carry_stall | flat | detect | 11 | 11.0 | 11.0 | 0 / 11 / 0 | 1 |
| carry_stall | flat | deliver | 6 | 32.5 | 32.5 | 0 / 6 / 0 | 1 |
| carry_stall | flat_strict | detect | 11 | 11.0 | 105.0 | 11 / 0 / 0 | 0.00098 |
| carry_stall | flat_strict | deliver | 6 | 32.5 | 32.5 | 0 / 6 / 0 | 1 |

## Outcomes (all families pooled; success judged from simulator ground truth)

| arm | policy | n | success (95% CI) | Δ vs off | mean recoveries |
|---|---|---|---|---|---|
| full | off | 160 | 35% (28–43) | — | 0.00 |
| full | detect | 160 | 31% (25–39) | -4 pp (p=0.55) | 0.00 |
| full | recover | 160 | 82% (76–88) | +48 pp (p=2.9e-18) | 0.72 |
| flat | off | 160 | 35% (28–43) | — | 0.00 |
| flat | detect | 160 | 32% (26–40) | -2 pp (p=0.72) | 0.00 |
| flat | recover | 160 | 84% (78–89) | +49 pp (p=7e-20) | 0.68 |
| flat_strict | off | 160 | 35% (28–43) | — | 0.00 |
| flat_strict | detect | 160 | 33% (26–41) | -2 pp (p=0.81) | 0.00 |
| flat_strict | recover | 160 | 84% (78–89) | +49 pp (p=7e-20) | 0.61 |

## Causes of failure

| arm | policy | causes |
|---|---|---|
| flat | detect | monitor:completion_unverified 80, fell 13, monitor:terminal_failure 12, monitor:collision_imminent 3 |
| flat | off | false_arrival 80, fell 13, timeout 11 |
| flat | recover | fell 13, monitor:terminal_failure 11, monitor:collision_imminent 1 |
| flat_strict | detect | monitor:completion_unverified 80, fell 13, monitor:TIMEOUT 11, monitor:collision_imminent 3 |
| flat_strict | off | false_arrival 80, fell 13, timeout 11 |
| flat_strict | recover | fell 13, timeout 11, monitor:collision_imminent 1 |
| full | detect | monitor:completion_unverified 32, monitor:TIMEOUT 31, monitor:phase:Carry:invariant 20, fell 13, monitor:terminal_failure 11, monitor:collision_imminent 3 |
| full | off | false_arrival 80, fell 13, timeout 11 |
| full | recover | fell 13, monitor:terminal_failure 9, monitor:TIMEOUT 3, timeout 2, monitor:collision_imminent 1 |

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
| flat | detect | carry_stall | 20 | 40% (22%–61%) | -5 pp [-35, +25] (p=1) | 100% | 71% | 0.83 | 11.8 | 0.00 |
| flat | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat | off | carry_push | 20 | 35% (18%–57%) | — | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 71% | 0.83 | 11.8 | 0.00 |
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
| flat_strict | detect | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 65% | 0.79 | 103.9 | 0.00 |
| flat_strict | off | carry_clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat_strict | off | carry_cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat_strict | off | carry_drop | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 14.5 | 0.00 |
| flat_strict | off | carry_grasp_fail | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 19.7 | 0.00 |
| flat_strict | off | carry_object_moved | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 32.6 | 0.00 |
| flat_strict | off | carry_push | 20 | 35% (18%–57%) | — | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat_strict | off | carry_skip_pickup | 20 | 0% (0%–16%) | — | 100% | 100% | 1.00 | 21.3 | 0.00 |
| flat_strict | off | carry_stall | 20 | 45% (26%–66%) | — | 100% | 65% | 0.79 | 103.9 | 0.00 |
| flat_strict | recover | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat_strict | recover | carry_cluttered | 20 | 95% (76%–99%) | -5 pp [-15, +0] (p=1) | 0% | — | — | — | 0.30 |
| flat_strict | recover | carry_drop | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 14.5 | 1.00 |
| flat_strict | recover | carry_grasp_fail | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 19.7 | 1.00 |
| flat_strict | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 32.6 | 1.00 |
| flat_strict | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| flat_strict | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.00 |
| flat_strict | recover | carry_stall | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 65% | 0.79 | 103.9 | 0.55 |
| full | detect | carry_clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| full | detect | carry_cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| full | detect | carry_drop | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 1.0 | 0.00 |
| full | detect | carry_grasp_fail | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 4.0 | 0.00 |
| full | detect | carry_object_moved | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 25.9 | 0.00 |
| full | detect | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| full | detect | carry_skip_pickup | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 100% | 1.00 | 21.3 | 0.00 |
| full | detect | carry_stall | 20 | 30% (15%–52%) | -15 pp [-45, +15] (p=0.514) | 100% | 82% | 0.90 | 12.4 | 0.00 |
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
| full | recover | carry_grasp_fail | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 4.0 | 1.10 |
| full | recover | carry_object_moved | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 25.9 | 1.00 |
| full | recover | carry_push | 20 | 35% (18%–57%) | +0 pp [-30, +30] (p=1) | 100% | 100% | 1.00 | 1.2 | 0.00 |
| full | recover | carry_skip_pickup | 20 | 100% (84%–100%) | +100 pp [+100, +100] (p=1.45e-11) | 100% | 100% | 1.00 | 21.3 | 1.00 |
| full | recover | carry_stall | 20 | 30% (15%–52%) | -15 pp [-45, +15] (p=0.514) | 100% | 82% | 0.90 | 12.4 | 1.40 |
