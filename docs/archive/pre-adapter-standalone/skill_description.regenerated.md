# Skill Monitor Documentation: AutonomousNavigation

> This skill manages autonomous navigation from a target location. It monitors path execution, obstacle avoidance, and progress towards the goal. The skill successfully terminates when the robot is sufficiently close to the target.

---

## LTL Formulas (Mission Specification)

| Name | Formula | Automaton milestone chain |
|---|---|---|
| `navigation_completion_sequence` | `F(target_received && F(path_planning_active && F(close_to_target)))` | `target_received` → `path_planning_active` → `close_to_target` |

---

## Named Failure Modes

> LTL formulas whose **VIOLATED** status triggers an immediate named halt.

| Fault Category | Name | Formula | Description |
|---|---|---|---|
| `SAFETY` | `collision_risk` | `G(!obstacle_detected)` | The robot must never enter a state where a close obstacle is detected. |
| `NAVIGATION` | `navigation_stuck` | `G(path_planning_active -> F(moving_towards_target))` | If navigation is active, the robot must eventually start moving towards the target. |

---

## Terminal Conditions

**✅ SUCCESS** — `close_to_target`
> Success is achieved when the robot's distance to the target is less than 0.5 meters.

**❌ FAILURE** — `obstacle_detected`
> Failure occurs if a close obstacle is detected at any point during navigation.

---

## Atomic Propositions

| Name | Eval | Rule / Description |
|---|---|---|
| `target_received` | ⚡ Rule | True when nav_status == 'accepted'. The navigation goal has been accepted by the planner. |
| `path_planning_active` | ⚡ Rule | True when nav_status in ['accepted', 'executing']. The robot is actively engaged in navigation. |
| `moving_towards_target` | ⚡ Rule | True when linear_vel > 0.05. The robot is currently moving forward. |
| `obstacle_detected` | ⚡ Rule | True when min_range < 0.25. A close obstacle is detected within the safety threshold. |
| `close_to_target` | ⚡ Rule | True when distance_to_target < 0.5. The robot is within the final stopping distance of the target. |

---

## Phase 1/1 — PathPlanningAndExecution

> The robot receives the target and begins executing the collision-free path.

### Entry

- **From:** Idle
- **Condition:** `target_received`

### In Progress

#### Invariant *(every step — immediate halt if violated)*

```
not obstacle_detected
```
> **`[SAFETY]`** halt on violation

#### Progress *(counted soft violations)*

```
path_planning_active and not obstacle_detected
```
> **`[PROGRESS]`** enter IDLE after **5** consecutive violations

#### Timing

- **`max_steps`: 120** — `[TIMEOUT]` halt if exceeded

### Exit

- **To:** Done
- **Condition:** `close_to_target`

### Atomic Propositions Used in This Phase

| Name | Eval | Rule / Description |
|---|---|---|
| `close_to_target` | ⚡ Rule | True when distance_to_target < 0.5. The robot is within the final stopping distance of the target. |
| `obstacle_detected` | ⚡ Rule | True when min_range < 0.25. A close obstacle is detected within the safety threshold. |
| `path_planning_active` | ⚡ Rule | True when nav_status in ['accepted', 'executing']. The robot is actively engaged in navigation. |
| `target_received` | ⚡ Rule | True when nav_status == 'accepted'. The navigation goal has been accepted by the planner. |

### Related Formulas

**LTL:** `navigation_completion_sequence`

```
F(target_received && F(path_planning_active && F(close_to_target)))
```

> Automaton **state 0**: waiting for `target_received` to advance to state 1

**Named failure modes active in this phase:**

| Fault Category | Name | Formula |
|---|---|---|
| `SAFETY` | `collision_risk` | `G(!obstacle_detected)` |
| `NAVIGATION` | `navigation_stuck` | `G(path_planning_active -> F(moving_towards_target))` |
