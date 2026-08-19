# Clocking: the tick, the window, and what "not enough data" means

The monitor's trace must be a function of the **data**, not of the machine processing it.
Otherwise the same episode replayed at a different speed, or streamed over a slower link,
yields a different verdict — and the planned Isaac Sim re-execution of counterfactuals
compares two things that were never comparable.

Three rates, named once so they are never conflated again:

| rate | what it is | may affect the verdict? |
|---|---|---|
| **observation rate** | the tick — defines the trace | **it *is* the trace** |
| **transport rate** | how fast samples reach a service | never |
| **publication rate** | how often a GUI refreshes | never |

## The tick, defined

**Frequency is declared; the period is in seconds.**

| symbol | meaning | unit |
|---|---|---|
| `tick_hz` | declared tick frequency | Hz |
| `Δ = 1 / tick_hz` | **tick period** | **seconds** |
| `seq` | tick index since the clock started | count |
| `step` | tick index within the episode, reset by `arm`/`reset` | count |
| `max_age_s`, `debounce_s`, `emit_delay_s` | durations | seconds |
| `max_steps`, `progress_violation_limit` | legacy spec budgets | **ticks** — see P11 |

**Tick *k* is the half-open interval `(B_k−1, B_k]` where `B_k = t₀ + k·Δ`**, measured on
the active clock — wall clock live, replay clock offline. **A tick is named by the boundary
that closes it**, so the pulse, the observation and the verdict carrying `seq=k` all describe
the same interval: the one that just ended. Naming it by its opening boundary instead would
put a permanent off-by-one between the pulse and everything downstream.

Half-open is the other half of the point: every instant belongs to exactly one tick, so no
sample is counted twice and none falls between ticks.

**`seq` counts closed intervals, so it starts at 1.** `seq = 0` means no interval has closed
yet — it is the value `GET /api/clock` returns before the first pulse, and it is not an
interval anyone can describe. Interval 0 would have to end at `t₀`, before the clock existed.

```
        B_k                         B_k+1                       B_k+2
         │◀────────── Δ seconds ──────▶│◀────────── Δ ──────────▶│
    ─────┼───●──●────────●─────●───────┼──●──────────●───────────┼──▶ active clock
         │   samples arriving async,   │                          │
         │   each source at its own    │                          │
         │   rate, into window k       │                          │
      open k                     close k / open k+1          close k+1
                                       │
                                       └─▶ fold → tick-steps → publish
                                           (all-or-nothing)
                                           → emit observation(seq=k)
                                           → automaton steps once
                                           → emit verdict(seq=k)
```

- **Opens** at `B_k` with an empty window.
- **Closes** at `B_k+1`, on the clock's next pulse. At that single instant, atomically:
  fold the window by each key's declared policy → commit the held values → run the
  tick-steps → emit the observation for tick *k* → open window *k+1*. **The close of *k*
  and the open of *k+1* are the same event**; there is no gap between them.
- **Input is event-driven, the tick is autonomous.** No source is polled or sampled;
  messages land in the current window whenever they arrive, at whatever rate that sensor
  runs. The tick **never waits for data**.
- **A tick fires even when nothing arrived.** That is precisely the tick that must report
  *not enough data*.
- **No catch-up merging.** A service that misses a pulse records `missed_ticks` and
  continues; it must never fold two windows into one.
- **Exactly one automaton step per tick.** `X` in an LTL formula therefore means "Δ seconds
  later", and this is the only place the trace's time base is defined.
- **Membership** is by *arrival* today, by *stamp* once the robot stamps its messages. The
  observation records which rule produced it, so a recording is never ambiguous.

### Clock modes

`wall` (live) · `replay` (advanced by a replayer, so replay speed cannot change the tick
count and therefore cannot change the verdict) · `manual` (single-step, for debugging —
`POST /api/clock/step` advances the entire system by one tick).

A service that sees no pulse for N periods falls back to its own timer and marks its output
`clock: internal`. "The clock schedules everything" and "each part runs standalone" are
both true, and which one you got is recorded rather than inferred.

### What timestamps are for

Once the robot stamps its messages — `/path_manager/status` is `std_msgs/String` and
`/vision/goal_similarity` is `Float32`, neither has a header, so this touches
`~/TRAV-metric-map` — stamps do exactly two things: decide **which window a sample belongs
to**, and **measure its age** for data health. They never gate when a tick fires. There is
no watermark and no adaptive wait; that was considered and dropped.

The residual, stated rather than engineered away: a sample delayed in transport past its
boundary lands in the next window, so a live remote trace can differ from a replay of the
same episode. Two fixed, non-adaptive controls bound it — a declared constant
`emit_delay_s` (0 on the robot tier, a fixed pipeline lag on the server tier, which shifts
the tick's *phase* but not its frequency) and a **late-arrival count carried in the
verdict**, so the divergence is visible instead of silent.

## The observation window

Held values are **tick-stable**: only the tick writes them. Messages accumulate into a
per-tick window; the tick folds it by a declared per-key policy.

| policy | use |
|---|---|
| `last` | **default** — state-like values (`nav_state`, `nav_mode`). Byte-identical to today's behaviour |
| `min` | the worst case seen in the interval. Chosen for `min_range` |
| `max`, `mean`, `first`, `any`, `all` | available; declared per key in the adapter descriptor |

A key with no sample this tick **holds its previous value** — zero-order hold is preserved,
and `data_health[source].refreshed` is what says the number is stale rather than steady.

### Why `min` on `min_range`, and what it costs

At 1 Hz over a ~15–30 Hz cloud, last-sample-wins discards 29 of 30 frames and the retained
one need not be the frame that saw 0.2 m — a real obstacle can be missed entirely.

`min` fixes that and opens a second path: the cloud is monocular-depth-derived, so one
spurious near-pixel in one frame per second can trip `collision_risk` → SAFETY → HALT. And
because unrefreshed keys hold, a spurious low sample latched immediately before
`/depth_anything/points` dies pins `collision_risk` true until the topic returns.

Mitigations that ship with it: every failure-mode entry carries `confidence` so the
supervisor can de-escalate a low-confidence VIOLATED, and per-source ages make the dead
topic visible. The residual closes with the three-valued verdict below. **`min_range < 0.25`
is a calibration knob** — measure the depth noise floor on a recorded bag before trusting
it.

## Data health

Per source, declared in the adapter descriptor: `expected_hz` (nominal publish rate),
`max_age_s` (oldest observation still usable for a tick, defaulting to
`max(2/expected_hz, Δ)`), and `required` (whether APs over its keys go UNKNOWN when it is
unhealthy).

`required` is deliberately **not** the same field as `tracked`. `tracked` counts toward the
`confidence` scalar; `required` decides whether a missing source makes an AP unknowable.
They already diverge: `/vision/goal_similarity` is untracked (it is optional, so counting it
would peg confidence below 1.0 on every run that does not use visual goal confirmation) but
its key feeds `visually_at_goal`.

This replaces the single global 2.0 s staleness in
[`Freshness`](../skill_monitor/backend/adapters/base.py#L52), which cannot express that a
30 Hz cloud and a 5 Hz status topic have different notions of "late".

## AP → source dependency

Derived, never authored. `spec_contract.sensor_keys_in_rule()`
([spec_contract.py:46](../skill_monitor/core/spec_contract.py#L46)) gives the sensor keys an
AP's rule references; the adapter descriptor gives key → source. Three gaps that a naive
lookup gets wrong:

1. **It must be the transitive closure over `Step.inputs`.** `upright_flag` is computed from
   `base_roll`/`base_pitch`/`base_height`, which come from odom; a direct-producer lookup
   sees only the derived key.
2. **An LLM-evaluated AP depends on *all* sources.** It has no `"True when"` rule, so
   `sensor_keys_in_rule` returns the empty set — and the evaluator hands it the entire
   `sensor_eval` dict. Mapping it to "no sources" makes it permanently fresh, exactly
   backwards.
3. **Untracked sources have no freshness record today**, so keys from them would report
   fresh unconditionally. `required` is the fix; `tracked` is the wrong knob.

## Three-valued APs

An AP whose required sources are not fresh is **UNKNOWN**, not false. Two rules make that
safe:

### UNKNOWN never travels inside the observation dict

`_update_phase_state` evaluates guards with
`eval(condition, {"__builtins__": {}}, observation)`
([monitor_node.py:829](../skill_monitor/backend/monitor_node.py#L829)). `None` is falsy and
the string `"UNKNOWN"` is truthy — so **both** make an invariant like
`upright and not collision_risk` fail, and both fabricate a SAFETY halt out of a sensor
dropout. UNKNOWN travels as a sibling `unknown_aps` list with an explicit gate in the
callback and in the phase machine.

### Freeze, don't guess — and the consequence

If an AP required by the automaton's current state is UNKNOWN, do not step: record the tick
`UNDECIDED`. The automaton is structurally two-valued —
`LTLMonitor._observation_to_bdd` defaults absent APs to `False` and builds a full BDD cube,
so there is no third value to pass — and freezing preserves it exactly.

Write down what that means: **`G(!collision_risk)` cannot be violated during a data
outage.** That is epistemically correct — you did not observe a collision — and it makes the
data-health alert load-bearing for safety. "Freeze on unknown" without an alert is a way to
make safety monitoring silently stop.

### `MonitorStatus.INCONCLUSIVE` is a different axis

[automata.py:53](../skill_monitor/core/automata.py#L53) — "the prefix seen so far neither
proves nor refutes the property". That is the *normal, expected* state of a healthy run.
"Not enough data" is a statement about observation, not about the trace. **Do not add a
member to that enum and do not rename it**: introduce a separate per-AP `TRUE|FALSE|UNKNOWN`
and a per-tick `DECIDED|UNDECIDED`, and let the verdict carry both.

## The episode fold

An episode verdict folds its ticks and carries a **coverage count**: how many ticks were
UNDECIDED. `core/episode_outcome.py` has no notion of coverage today, so an episode with 40%
undecided ticks classifies as `reached_goal` at full confidence. Coverage is what makes the
sim-vs-real comparison honest — the exclusion count *is* the fidelity report.

## Two bugs this exists to fix

Both are live, both are independent of the remote architecture, and the second breaks the
hardware-agnosticism claim outright.

**`nav_stuck` counts messages, not ticks.** `formulas_g1.json` documents "10+ consecutive
ticks"; `_fn_stuck_streak` ([adapter_spec.py:86](../skill_monitor/core/adapter_spec.py#L86))
advances inside `Step.apply`, i.e. once per incoming message. At a 5 Hz status topic that
debounce is 2 s, not 10 s.

**Superseded by [P12](packages/P12-planner-independent-schema.md):** `nav_stuck` is being
removed altogether, along with every other key sourced from the planner's status stream. It
becomes `no_progress`, derived from odometry against the commanded goal — which also fixes
the deeper problem that a planner reporting `following` while physically wedged was
structurally invisible. The debounce-in-ticks fix below still applies, to the new key.

**In sim it never fires at all.** `mujoco.json` and `isaac_lab.json` attach the streak to
the Nav2 source, whose `GoalStatusArray` publishes on status *transitions*, not periodically.
The same spec on the same trajectory debounces for 10 s on the robot and never triggers in
simulation. Fixing this turns on a signal that has never been on — any recorded sim ablation
number involving `nav_stuck` becomes non-comparable, which is why that change lands as one
identifiable commit.
