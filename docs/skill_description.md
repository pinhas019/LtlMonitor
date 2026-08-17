# Skill Monitor Documentation: AutonomousNavigation

> This skill manages autonomous navigation from a given target location to the goal while ensuring collision avoidance. It monitors the robot's progress towards the target and the status of the navigation system. The mission succeeds upon successful navigation completion, otherwise, it remains in progress until a definitive failure or success state is reached.

---

## LTL Formulas (Mission Specification)

| Name | Formula | Automaton milestone chain |
|---|---|---|
| `full_navigation_sequence` | `F(target_received && F(path_planned && F(moving_towards_target && F(target_reached))))` | `target_received` → `path_planned` → `moving_towards_target` → `target_reached` |

---

## Named Failure Modes

> LTL formulas whose **VIOLATED** status triggers an immediate named halt.

| Fault Category | Name | Formula | Description |
|---|---|---|---|
| `SAFETY` | `collision_imminent` | `G(!collision_risk)` | The robot must never enter a state where an obstacle is too close. |

---

## Terminal Conditions

**✅ SUCCESS** — `navigation_succeeded`
> The mission is accomplished when the navigation status explicitly reports success.

**❌ FAILURE** — `navigation_failed`
> The mission is considered failed if the navigation process is aborted or canceled.

---

## Atomic Propositions

| Name | Eval | Rule / Description |
|---|---|---|
| `target_received` | ⚡ Rule | True when distance_to_target > 100.0. A target location has been set for navigation. |
| `path_planned` | ⚡ Rule | True when nav_status == 'accepted'. The navigation system has accepted the path plan. |
| `moving_towards_target` | ⚡ Rule | True when nav_status == 'executing'. The robot is actively executing the planned path. |
| `collision_risk` | ⚡ Rule | True when min_range < 0.25. An obstacle is detected too close to the robot. |
| `target_reached` | ⚡ Rule | True when distance_to_target < 0.5. The robot is within close proximity of the target location. |
| `navigation_succeeded` | ⚡ Rule | True when nav_status == 'succeeded'. The navigation goal was successfully achieved. |
| `navigation_failed` | ⚡ Rule | True when nav_status in ['aborted', 'canceled']. The navigation process was interrupted or failed. |

---

## Automaton States

> Images are generated to `output/` when the monitor starts.
> The tables below describe the **expected** state structure inferred from the formula.

### `full_navigation_sequence`

**Formula:** `F(target_received && F(path_planned && F(moving_towards_target && F(target_reached))))`

![full_navigation_sequence](output/full_navigation_sequence.png)

| State | Labels | Phase | Waits for | Advance condition |
|---|---|---|---|---|
| **0** | initial | PlanningAndInitiation | `target_received` | `target_received` = True → State 1 |
| **1** | — | ExecutionAndTracking | `path_planned` | `path_planned` = True → State 2 |
| **2** | — | — | `moving_towards_target` | `moving_towards_target` = True → State 3 |
| **3** | — | — | `target_reached` | `target_reached` = True → State 4 |
| **4** | accepting | Done | — | self-loop on any input |

> Every non-accepting state self-loops while its advance condition is False.

---

### Named Failure-Mode Automata

> Each named failure mode compiles to a **2-state safety automaton**.
> State 0 is the accepting sink (property holds); State 1 is the permanent VIOLATED sink.

#### `collision_imminent` — `[SAFETY]`

**Formula:** `G(!collision_risk)`
> The robot must never enter a state where an obstacle is too close.

![collision_imminent](output/collision_imminent.png)

| State | Labels | Semantic | Transition |
|---|---|---|---|
| **0** | initial, accepting | Property holds — `collision_risk` is False | `collision_risk` = True → State 1 (**VIOLATED**) |
| **1** | sink / trap | **VIOLATED** — `[SAFETY]` halt | self-loop (any input) |


---

## Phase 1/2 — PlanningAndInitiation

> The robot receives the target and initiates the path planning process.

### Entry

- **From:** Idle
- **Condition:** `target_received`

### In Progress

#### Invariant *(every step — immediate halt if violated)*

```
not collision_risk
```
> **`[SAFETY]`** halt on violation

#### Progress *(counted soft violations)*

```
not path_planned
```
> **`[PROGRESS]`** enter IDLE after **5** consecutive violations

#### Timing

- **`max_steps`: 30** — `[TIMEOUT]` halt if exceeded

### Exit

- **To:** ExecutionAndTracking
- **Condition:** `path_planned`

### Atomic Propositions Used in This Phase

| Name | Eval | Rule / Description |
|---|---|---|
| `collision_risk` | ⚡ Rule | True when min_range < 0.25. An obstacle is detected too close to the robot. |
| `path_planned` | ⚡ Rule | True when nav_status == 'accepted'. The navigation system has accepted the path plan. |
| `target_received` | ⚡ Rule | True when distance_to_target > 100.0. A target location has been set for navigation. |

### Related Formulas

**LTL:** `full_navigation_sequence`

```
F(target_received && F(path_planned && F(moving_towards_target && F(target_reached))))
```

> Automaton **state 0**: waiting for `target_received` to advance to state 1

**Named failure modes active in this phase:**

| Fault Category | Name | Formula |
|---|---|---|
| `SAFETY` | `collision_imminent` | `G(!collision_risk)` |


---

## Phase 2/2 — ExecutionAndTracking

> The robot moves towards the target while continuously monitoring for obstacles and progress.

### Entry

- **From:** PlanningAndInitiation
- **Condition:** `path_planned`

### In Progress

#### Invariant *(every step — immediate halt if violated)*

```
not collision_risk
```
> **`[SAFETY]`** halt on violation

#### Progress *(counted soft violations)*

```
moving_towards_target
```
> **`[PROGRESS]`** enter IDLE after **5** consecutive violations

#### Timing

- **`max_steps`: 120** — `[TIMEOUT]` halt if exceeded

### Exit

- **To:** Done
- **Condition:** `target_reached or navigation_failed`

### Atomic Propositions Used in This Phase

| Name | Eval | Rule / Description |
|---|---|---|
| `collision_risk` | ⚡ Rule | True when min_range < 0.25. An obstacle is detected too close to the robot. |
| `moving_towards_target` | ⚡ Rule | True when nav_status == 'executing'. The robot is actively executing the planned path. |
| `navigation_failed` | ⚡ Rule | True when nav_status in ['aborted', 'canceled']. The navigation process was interrupted or failed. |
| `path_planned` | ⚡ Rule | True when nav_status == 'accepted'. The navigation system has accepted the path plan. |
| `target_reached` | ⚡ Rule | True when distance_to_target < 0.5. The robot is within close proximity of the target location. |

### Related Formulas

**LTL:** `full_navigation_sequence`

```
F(target_received && F(path_planned && F(moving_towards_target && F(target_reached))))
```

> Automaton **state 1**: waiting for `path_planned` to advance to state 2

**Named failure modes active in this phase:**

| Fault Category | Name | Formula |
|---|---|---|
| `SAFETY` | `collision_imminent` | `G(!collision_risk)` |
