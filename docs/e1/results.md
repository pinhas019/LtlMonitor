# E1 results (1800 episodes)

## Detection (policy off: the monitor reports, nothing acts)

Fault families: detected / injected · median ticks (1 tick = 1 s) from injection to the first intervention. Fault-free families: episodes with any intervention.

| family | full spec | flat (keeps terminal failure) | flat strict (no terminal failure) |
|---|---|---|---|
| clear | 0/20 false alarms | 0/20 false alarms | 0/20 false alarms |
| cluttered | 3/20 false alarms | 3/20 false alarms | 3/20 false alarms |
| block_route | 20/20 · 13 ticks | 20/20 · 13 ticks | 20/20 · 13 ticks |
| obstacle | 15/20 · 10 ticks | 15/20 · 10 ticks | 15/20 · 10 ticks |
| odom_drift | 2/20 · 2 ticks | 2/20 · 2 ticks | 2/20 · 2 ticks |
| push | 19/20 · 1 ticks | 19/20 · 1 ticks | 19/20 · 1 ticks |
| scan_dropout | 0/20 | 0/20 | 0/20 |
| slip | 10/20 · 7 ticks | 10/20 · 7 ticks | 10/20 · 7 ticks |
| stall | 16/20 · 11 ticks | 15/20 · 11 ticks | 1/20 · 33 ticks |
| weaken | 19/20 · 2 ticks | 19/20 · 2 ticks | 19/20 · 2 ticks |

## Detection of faults that mattered (policy off)

A fault *mattered* when the episode failed under `off` (judged from ground truth). Alarms on episodes that succeeded anyway are interventions a policy would have acted on for nothing.

| family | failed under off | detected · full spec | detected · flat (keeps terminal failure) | detected · flat strict (no terminal failure) | alarms on episodes that succeeded anyway (full) |
|---|---|---|---|---|---|
| clear | 0/20 | 0/0 | 0/0 | 0/0 | 0 |
| cluttered | 0/20 | 0/0 | 0/0 | 0/0 | 3 |
| block_route | 0/20 | 0/0 | 0/0 | 0/0 | 20 |
| obstacle | 0/20 | 0/0 | 0/0 | 0/0 | 15 |
| odom_drift | 8/20 | 1/8 | 1/8 | 1/8 | 1 |
| push | 20/20 | 19/20 | 19/20 | 19/20 | 0 |
| scan_dropout | 0/20 | 0/0 | 0/0 | 0/0 | 0 |
| slip | 11/20 | 10/11 | 10/11 | 10/11 | 0 |
| stall | 15/20 | 15/15 | 14/15 | 1/15 | 1 |
| weaken | 20/20 | 19/20 | 19/20 | 19/20 | 0 |

## Paired: full spec against each flat arm, scenario by scenario

*detect*: policy `off`, episodes that failed, ticks from injection to the first intervention. *deliver*: policy `recover`, episodes both arms completed, simulated seconds to finish. Lower is better; the sign test counts the pairs where the full spec was lower against those where it was higher.

| family | against | measure | pairs | median full | median other | full lower / tie / higher | sign test p |
|---|---|---|---|---|---|---|---|
| block_route | flat | deliver | 6 | 28.5 | 28.5 | 0 / 6 / 0 | 1 |
| block_route | flat_strict | deliver | 6 | 28.5 | 28.5 | 0 / 6 / 0 | 1 |
| obstacle | flat | deliver | 12 | 20.0 | 20.0 | 0 / 12 / 0 | 1 |
| obstacle | flat_strict | deliver | 12 | 20.0 | 20.0 | 0 / 12 / 0 | 1 |
| odom_drift | flat | detect | 1 | 3.0 | 3.0 | 0 / 1 / 0 | 1 |
| odom_drift | flat | deliver | 12 | 15.5 | 15.5 | 0 / 12 / 0 | 1 |
| odom_drift | flat_strict | detect | 1 | 3.0 | 3.0 | 0 / 1 / 0 | 1 |
| odom_drift | flat_strict | deliver | 12 | 15.5 | 15.5 | 0 / 12 / 0 | 1 |
| push | flat | detect | 19 | 1.0 | 1.0 | 0 / 19 / 0 | 1 |
| push | flat_strict | detect | 19 | 1.0 | 1.0 | 0 / 19 / 0 | 1 |
| scan_dropout | flat | deliver | 20 | 16.0 | 16.0 | 0 / 20 / 0 | 1 |
| scan_dropout | flat_strict | deliver | 20 | 16.0 | 16.0 | 0 / 20 / 0 | 1 |
| slip | flat | detect | 10 | 7.0 | 7.0 | 0 / 10 / 0 | 1 |
| slip | flat | deliver | 9 | 20.0 | 20.0 | 0 / 9 / 0 | 1 |
| slip | flat_strict | detect | 10 | 7.0 | 7.0 | 0 / 10 / 0 | 1 |
| slip | flat_strict | deliver | 9 | 20.0 | 20.0 | 0 / 9 / 0 | 1 |
| stall | flat | detect | 14 | 11.0 | 11.0 | 0 / 14 / 0 | 1 |
| stall | flat | deliver | 5 | 50.0 | 50.0 | 0 / 5 / 0 | 1 |
| stall | flat_strict | detect | 1 | 12.0 | 33.0 | 1 / 0 / 0 | 1 |
| stall | flat_strict | deliver | 5 | 50.0 | 50.0 | 0 / 5 / 0 | 1 |
| weaken | flat | detect | 19 | 2.0 | 2.0 | 0 / 19 / 0 | 1 |
| weaken | flat_strict | detect | 19 | 2.0 | 2.0 | 0 / 19 / 0 | 1 |

## Outcomes (all families pooled; success judged from simulator ground truth)

| arm | policy | n | success (95% CI) | Δ vs off | mean recoveries |
|---|---|---|---|---|---|
| full | off | 200 | 63% (56–69) | — | 0.00 |
| full | detect | 200 | 43% (36–50) | -20 pp (p=8.9e-05) | 0.00 |
| full | recover | 200 | 52% (45–59) | -11 pp (p=0.034) | 0.53 |
| flat | off | 200 | 63% (56–69) | — | 0.00 |
| flat | detect | 200 | 43% (36–50) | -20 pp (p=8.9e-05) | 0.00 |
| flat | recover | 200 | 52% (45–59) | -11 pp (p=0.034) | 0.52 |
| flat_strict | off | 200 | 63% (56–69) | — | 0.00 |
| flat_strict | detect | 200 | 44% (37–50) | -20 pp (p=0.00013) | 0.00 |
| flat_strict | recover | 200 | 52% (45–59) | -11 pp (p=0.034) | 0.39 |

## Causes of failure

| arm | policy | causes |
|---|---|---|
| flat | detect | fell 50, monitor:collision_imminent 41, monitor:terminal_failure 15, false_arrival 6, timeout 1, nav_failed 1 |
| flat | off | fell 51, timeout 15, false_arrival 7, nav_failed 1 |
| flat | recover | fell 51, monitor:collision_imminent 23, monitor:terminal_failure 14, false_arrival 6, timeout 1, nav_failed 1 |
| flat_strict | detect | fell 50, monitor:collision_imminent 42, timeout 14, false_arrival 6, nav_failed 1 |
| flat_strict | off | fell 51, timeout 15, false_arrival 7, nav_failed 1 |
| flat_strict | recover | fell 51, monitor:collision_imminent 24, timeout 14, false_arrival 6, nav_failed 1 |
| full | detect | fell 50, monitor:collision_imminent 41, monitor:terminal_failure 15, false_arrival 6, monitor:TIMEOUT 1, nav_failed 1 |
| full | off | fell 51, timeout 15, false_arrival 7, nav_failed 1 |
| full | recover | fell 51, monitor:collision_imminent 23, monitor:terminal_failure 14, false_arrival 6, timeout 1, nav_failed 1 |

## Full table (arm × policy × family)

| arm | policy | family | n | success (95% CI) | Δ vs off [95% CI] (p) | precision | recall | F1 | TTD (ticks) | recoveries |
|---|---|---|---|---|---|---|---|---|---|---|
| flat | detect | block_route | 20 | 0% (0%–16%) | -100 pp [-100, -100] (p=1.45e-11) | 100% | 100% | 1.00 | 13.2 | 0.00 |
| flat | detect | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat | detect | cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| flat | detect | obstacle | 20 | 25% (11%–47%) | -75 pp [-90, -55] (p=7.71e-07) | 100% | 75% | 0.86 | 11.7 | 0.00 |
| flat | detect | odom_drift | 20 | 55% (34%–74%) | -5 pp [-35, +25] (p=1) | 50% | 5% | 0.10 | 3.0 | 0.00 |
| flat | detect | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 100% | 0.97 | 1.2 | 0.00 |
| flat | detect | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| flat | detect | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat | detect | stall | 20 | 20% (8%–42%) | -5 pp [-30, +20] (p=1) | 100% | 75% | 0.86 | 13.0 | 0.00 |
| flat | detect | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
| flat | off | block_route | 20 | 100% (84%–100%) | — | 100% | 100% | 1.00 | 13.2 | 0.00 |
| flat | off | clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat | off | cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat | off | obstacle | 20 | 100% (84%–100%) | — | 100% | 75% | 0.86 | 11.7 | 0.00 |
| flat | off | odom_drift | 20 | 60% (39%–78%) | — | 100% | 10% | 0.18 | 1.5 | 0.00 |
| flat | off | push | 20 | 0% (0%–16%) | — | 95% | 95% | 0.95 | 1.2 | 0.00 |
| flat | off | scan_dropout | 20 | 100% (84%–100%) | — | — | 0% | — | — | 0.00 |
| flat | off | slip | 20 | 45% (26%–66%) | — | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat | off | stall | 20 | 25% (11%–47%) | — | 100% | 75% | 0.86 | 13.0 | 0.00 |
| flat | off | weaken | 20 | 0% (0%–16%) | — | 100% | 95% | 0.97 | 2.2 | 0.00 |
| flat | recover | block_route | 20 | 30% (15%–52%) | -70 pp [-90, -50] (p=3.34e-06) | 100% | 100% | 1.00 | 13.2 | 1.95 |
| flat | recover | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat | recover | cluttered | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | 0% | — | — | — | 0.15 |
| flat | recover | obstacle | 20 | 60% (39%–78%) | -40 pp [-60, -20] (p=0.00328) | 100% | 75% | 0.86 | 11.7 | 1.40 |
| flat | recover | odom_drift | 20 | 60% (39%–78%) | +0 pp [-30, +30] (p=1) | 100% | 10% | 0.18 | 1.5 | 0.20 |
| flat | recover | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 95% | 0.95 | 1.2 | 0.05 |
| flat | recover | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| flat | recover | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat | recover | stall | 20 | 25% (11%–47%) | +0 pp [-25, +25] (p=1) | 100% | 75% | 0.86 | 13.0 | 1.45 |
| flat | recover | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
| flat_strict | detect | block_route | 20 | 0% (0%–16%) | -100 pp [-100, -100] (p=1.45e-11) | 100% | 100% | 1.00 | 13.2 | 0.00 |
| flat_strict | detect | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat_strict | detect | cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| flat_strict | detect | obstacle | 20 | 25% (11%–47%) | -75 pp [-90, -55] (p=7.71e-07) | 100% | 75% | 0.86 | 11.7 | 0.00 |
| flat_strict | detect | odom_drift | 20 | 55% (34%–74%) | -5 pp [-35, +25] (p=1) | 50% | 5% | 0.10 | 3.0 | 0.00 |
| flat_strict | detect | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 100% | 0.97 | 1.2 | 0.00 |
| flat_strict | detect | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| flat_strict | detect | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat_strict | detect | stall | 20 | 25% (11%–47%) | +0 pp [-25, +25] (p=1) | 100% | 5% | 0.10 | 33.0 | 0.00 |
| flat_strict | detect | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
| flat_strict | off | block_route | 20 | 100% (84%–100%) | — | 100% | 100% | 1.00 | 13.2 | 0.00 |
| flat_strict | off | clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| flat_strict | off | cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| flat_strict | off | obstacle | 20 | 100% (84%–100%) | — | 100% | 75% | 0.86 | 11.7 | 0.00 |
| flat_strict | off | odom_drift | 20 | 60% (39%–78%) | — | 100% | 10% | 0.18 | 1.5 | 0.00 |
| flat_strict | off | push | 20 | 0% (0%–16%) | — | 95% | 95% | 0.95 | 1.2 | 0.00 |
| flat_strict | off | scan_dropout | 20 | 100% (84%–100%) | — | — | 0% | — | — | 0.00 |
| flat_strict | off | slip | 20 | 45% (26%–66%) | — | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat_strict | off | stall | 20 | 25% (11%–47%) | — | 100% | 5% | 0.10 | 33.0 | 0.00 |
| flat_strict | off | weaken | 20 | 0% (0%–16%) | — | 100% | 95% | 0.97 | 2.2 | 0.00 |
| flat_strict | recover | block_route | 20 | 30% (15%–52%) | -70 pp [-90, -50] (p=3.34e-06) | 100% | 100% | 1.00 | 13.2 | 1.95 |
| flat_strict | recover | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| flat_strict | recover | cluttered | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | 0% | — | — | — | 0.15 |
| flat_strict | recover | obstacle | 20 | 60% (39%–78%) | -40 pp [-60, -20] (p=0.00328) | 100% | 75% | 0.86 | 11.7 | 1.40 |
| flat_strict | recover | odom_drift | 20 | 60% (39%–78%) | +0 pp [-30, +30] (p=1) | 100% | 10% | 0.18 | 1.5 | 0.20 |
| flat_strict | recover | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 95% | 0.95 | 1.2 | 0.05 |
| flat_strict | recover | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| flat_strict | recover | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| flat_strict | recover | stall | 20 | 25% (11%–47%) | +0 pp [-25, +25] (p=1) | 100% | 5% | 0.10 | 33.0 | 0.10 |
| flat_strict | recover | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
| full | detect | block_route | 20 | 0% (0%–16%) | -100 pp [-100, -100] (p=1.45e-11) | 100% | 100% | 1.00 | 13.2 | 0.00 |
| full | detect | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| full | detect | cluttered | 20 | 85% (64%–95%) | -15 pp [-35, +0] (p=0.231) | 0% | — | — | — | 0.00 |
| full | detect | obstacle | 20 | 25% (11%–47%) | -75 pp [-90, -55] (p=7.71e-07) | 100% | 75% | 0.86 | 11.7 | 0.00 |
| full | detect | odom_drift | 20 | 55% (34%–74%) | -5 pp [-35, +25] (p=1) | 50% | 5% | 0.10 | 3.0 | 0.00 |
| full | detect | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 100% | 0.97 | 1.2 | 0.00 |
| full | detect | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| full | detect | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| full | detect | stall | 20 | 20% (8%–42%) | -5 pp [-30, +20] (p=1) | 100% | 80% | 0.89 | 15.8 | 0.00 |
| full | detect | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
| full | off | block_route | 20 | 100% (84%–100%) | — | 100% | 100% | 1.00 | 13.2 | 0.00 |
| full | off | clear | 20 | 100% (84%–100%) | — | — | — | — | — | 0.00 |
| full | off | cluttered | 20 | 100% (84%–100%) | — | 0% | — | — | — | 0.00 |
| full | off | obstacle | 20 | 100% (84%–100%) | — | 100% | 75% | 0.86 | 11.7 | 0.00 |
| full | off | odom_drift | 20 | 60% (39%–78%) | — | 100% | 10% | 0.18 | 1.5 | 0.00 |
| full | off | push | 20 | 0% (0%–16%) | — | 95% | 95% | 0.95 | 1.2 | 0.00 |
| full | off | scan_dropout | 20 | 100% (84%–100%) | — | — | 0% | — | — | 0.00 |
| full | off | slip | 20 | 45% (26%–66%) | — | 100% | 50% | 0.67 | 9.2 | 0.00 |
| full | off | stall | 20 | 25% (11%–47%) | — | 100% | 80% | 0.89 | 15.8 | 0.00 |
| full | off | weaken | 20 | 0% (0%–16%) | — | 100% | 95% | 0.97 | 2.2 | 0.00 |
| full | recover | block_route | 20 | 30% (15%–52%) | -70 pp [-90, -50] (p=3.34e-06) | 100% | 100% | 1.00 | 13.2 | 1.95 |
| full | recover | clear | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | — | — | — | 0.00 |
| full | recover | cluttered | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | 0% | — | — | — | 0.15 |
| full | recover | obstacle | 20 | 60% (39%–78%) | -40 pp [-60, -20] (p=0.00328) | 100% | 75% | 0.86 | 11.7 | 1.40 |
| full | recover | odom_drift | 20 | 60% (39%–78%) | +0 pp [-30, +30] (p=1) | 100% | 10% | 0.18 | 1.5 | 0.20 |
| full | recover | push | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 95% | 95% | 0.95 | 1.2 | 0.05 |
| full | recover | scan_dropout | 20 | 100% (84%–100%) | +0 pp [+0, +0] (p=1) | — | 0% | — | — | 0.00 |
| full | recover | slip | 20 | 45% (26%–66%) | +0 pp [-30, +30] (p=1) | 100% | 50% | 0.67 | 9.2 | 0.00 |
| full | recover | stall | 20 | 25% (11%–47%) | +0 pp [-25, +25] (p=1) | 100% | 80% | 0.89 | 15.8 | 1.50 |
| full | recover | weaken | 20 | 0% (0%–16%) | +0 pp [+0, +0] (p=1) | 100% | 95% | 0.97 | 2.2 | 0.00 |
