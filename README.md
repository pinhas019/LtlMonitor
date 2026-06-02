# LTL Büchi Monitor

A runtime monitoring tool that verifies **Linear Temporal Logic (LTL)** properties over a stream of observations using **ROS 2 topics**. Built on the [Spot](https://spot.lrde.epita.fr/) library and containerized with Docker.

The monitor **publishes which atomic propositions to evaluate** to a ROS 2 topic, and an LLM evaluator node **subscribes, evaluates them against live sensor data, and publishes boolean results back**. This separates **state progression monitoring** (monitor side) from **observation evaluation** (LLM/robot side).

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [ROS 2 Topics Protocol](#ros-2-topics-protocol)
- [Project Structure](#project-structure)
- [Formulas Specification](#formulas-specification)
- [LLM-Based Predicate Evaluation](#llm-based-predicate-evaluation)
- [CLI Reference](#cli-reference)
- [Monitor Status Model](#monitor-status-model)
- [Examples](#examples)
  - [Full Simulation Stack](#example-1-full-simulation-stack)
  - [Inline Formulas](#example-2-inline-formulas)
- [How It Works Internally](#how-it-works-internally)
- [API Reference](#api-reference)

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20+) with Compose
- [Ollama](https://ollama.ai/) running locally (for the LLM evaluator)

### 🚀 Running the Integrated Pipeline (Recommended)

You can run the entire pipeline—from natural language skill specification to execution monitoring—using the `run_pipeline.py` script:

```bash
# Run with a natural language skill description
python3 run_pipeline.py -d "An autonomous navigation skill where the robot receives a target location, plans a collision-free path, moves to the target while avoiding obstacles, and terminates when close to the target."

# The script will:
# 1. Query Ollama (default model llama3.2:3b) to generate formulas.json and skill_description.txt
# 2. Restart the Docker Compose simulation stack in the background
# 3. Stream the live monitor logs to your terminal
# 4. Prompt you on Ctrl+C to clean up and stop the containers
```

### Manual Build & Run (Full Stack)

```bash
# 1. Start the full simulation stack (first build takes ~12 min for Spot compilation)
cd sim/
docker compose -f docker-compose.sim.yml up -d --build

# 2. Check the monitor is running
docker logs ltl-monitor --tail 20

# 3. View all container logs via Dozzle
# Open browser → http://localhost:8080/dozzle

# 4. Visualize in Foxglove Studio
# Open Foxglove → Connect via WebSocket to ws://localhost:8765
```

The stack starts multiple containers (all named with the `ltl-` prefix for easy identification in Dozzle):
- **`ltl-mujoco-sim`** — MuJoCo physics sim with Unitree G1 (floating base)
- **`ltl-nav2`** — ROS 2 Navigation2 for path planning
- **`ltl-monitor`** — Büchi automaton monitor (publishes `/ltl/required_aps`, `/ltl/state_description`)
- **`ltl-llm-client`** — LLM evaluator (subscribes to APs, publishes `/ltl/evaluations`)
- **`ltl-foxglove-bridge`** — WebSocket bridge for Foxglove visualization
- **`ltl-dozzle`** — Real-time container log viewer at [http://localhost:8080/dozzle](http://localhost:8080/dozzle)

---

## Architecture

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                    Docker Compose Stack                         │
 │                                                                 │
 │  ┌──────────────┐     /cmd_vel      ┌──────────────┐           │
 │  │  MuJoCo Sim  │ ◀──────────────── │    Nav2      │           │
 │  │  (G1 robot)  │ ──────────────▶   │  Navigation  │           │
 │  └──────┬───────┘  /odom, /scan     └──────────────┘           │
 │         │                                                       │
 │    /odom, /scan                                                 │
 │         │                                                       │
 │         ▼                                                       │
 │  ┌──────────────┐  /ltl/required_aps  ┌──────────────────────┐ │
 │  │  LLM Client  │ ◀───────────────── │   LTL Monitor Node   │ │
 │  │  (Ollama)    │  /ltl/state_desc    │   (Büchi Automaton)  │ │
 │  │              │ ──────────────────▶ │                      │ │
 │  └──────────────┘  /ltl/evaluations   │  formulas.json       │ │
 │                                        │  monitor.py (Spot)   │ │
 │                                        └──────────────────────┘ │
 │                                                                 │
 │  ┌──────────────────┐                                          │
 │  │ Foxglove Bridge  │ ── ws://localhost:8765                   │
 │  └──────────────────┘                                          │
 │  ┌──────────────────┐                                          │
 │  │     Dozzle       │ ── http://localhost:8080/dozzle          │
 │  └──────────────────┘                                          │
 └─────────────────────────────────────────────────────────────────┘
```

### Separation of Concerns

| Concern | Component | Where |
|---|---|---|
| **State progression monitoring** | `main.py` / `monitor.py` | Docker — tracks Büchi automaton states, publishes required APs and state description |
| **Observation evaluation** | `llm_client.py` | Docker — subscribes to APs and sensor topics, queries Ollama, publishes boolean evaluations |
| **Terminal state detection** | `main.py` + `llm_client.py` | APs for success/failure conditions are always included in the LLM query with explicit terminal context |
| **Physics simulation** | `mujoco_ros_bridge.py` | Docker — MuJoCo sim, publishes `/odom`, `/scan`, accepts `/cmd_vel` |
| **Visualization** | Foxglove Bridge | Docker — exposes all ROS 2 topics via WebSocket |
| **Log aggregation** | Dozzle | Docker — aggregates all `ltl-*` container logs at `/dozzle` |

---

## Two-Way Protocol

Each monitoring step follows a request/response cycle:

## ROS 2 Topics Protocol

Communication between the monitor and the LLM evaluator uses three ROS 2 topics with `std_msgs/msg/String` carrying JSON payloads:

| Topic | Direction | Payload |
|---|---|---|
| `/ltl/required_aps` | Monitor → LLM | JSON array of AP names to evaluate: `["moving", "collision", "nav_status_success", ...]` |
| `/ltl/state_description` | Monitor → LLM | JSON with phase, skill name, description, AP descriptions, and terminal success/failure context |
| `/ltl/evaluations` | LLM → Monitor | JSON object of AP evaluations: `{"moving": true, "collision": false, "nav_status_success": false}` |

```
 Monitor Node                          LLM Client Node
     │                                      │
     │  1. /ltl/required_aps               │
     │  ["moving", "collision",            │
     │   "nav_status_success", ...]        │
     ├─────────────────────────────────────▶│
     │                                      │ 2. Query Ollama
     │  2. /ltl/state_description          │    with sensor data
     │  {"phase": "Navigation",            │    (/odom, /scan)
     │   "terminal_success": {...},        │    + terminal context
     │   "terminal_failure": {...}, ...}   │
     ├─────────────────────────────────────▶│
     │                                      │
     │  3. /ltl/evaluations                │
     │  {"moving": true,                   │
     │   "collision": false,               │
     │   "nav_status_success": false}      │
     │◀─────────────────────────────────────┤
     │                                      │
     │  4. Advance Büchi automaton          │
     │  5. Check terminal conditions        │
     │  6. Publish new required_aps        │
     │                                      │
```

### Termination

Send `{"__done__": true}` on `/ltl/evaluations` to end the monitoring session.

---

## Project Structure

```
LtlMonitor/
├── Dockerfile                 # Monitor container: ros:humble + Spot (compiled)
├── Dockerfile.llm             # LLM evaluator container: ros:humble
├── sim/
│   ├── docker-compose.sim.yml # Full stack orchestration
│   ├── Dockerfile.sim         # MuJoCo simulation
│   ├── Dockerfile.nav2        # ROS 2 Navigation2
│   └── Dockerfile.foxglove    # Foxglove WebSocket bridge
│
├── monitor.py                 # Core: Büchi automata + BDD introspection
├── main.py                    # ROS 2 Node: LtlMonitorNode
├── llm_client.py              # ROS 2 Node: LLM evaluator (Ollama)
├── generate_formulas.py       # LLM formulas and state descriptions generator
├── run_pipeline.py            # Master script to run generation, simulation, and monitoring
│
├── formulas.json              # ◀── EDIT: your LTL skill specification
├── skill_description.txt      # Generated state descriptions
└── README.md
```

### Files You Edit

| File | Purpose | Where it runs | Rebuild needed? |
|---|---|---|---|
| `formulas.json` | LTL formulas, atomic propositions, execution phases | Monitor (Docker volume) | No |
| `llm_client.py` | LLM-based AP evaluator using Ollama + sensor data | LLM container | Yes (`docker compose build llm-client`) |
| `run_pipeline.py` | Configure and run pipeline (natural language prompt) | Host | No |

---

## Formulas Specification

### Simple Format

```json
["F(goal)", "G(!obstacle)", "G(moving -> F(stopped))"]
```

### Rich Skill-Spec Format

```json
{
  "skill_name": "GoToTarget",
  "description": "Autonomous navigation to a target location.",
  "atomic_propositions": {
    "skill_active":    "The GoToTarget skill is currently executing",
    "target_received": "A valid target position was received",
    "collision":       "The robot is in collision",
    "near_target":     "Within acceptable distance to the target",
    "terminated":      "The skill has terminated"
  },
  "ltl_formulas": [
    {"name": "collision_avoidance", "formula": "G(!collision)"},
    {"name": "eventually_reach",   "formula": "G(skill_active -> F(near_target))"}
  ],
  "execution_phases": [
    {"phase": "Initialization", "condition": "skill_active && target_received"},
    {"phase": "Navigation",     "condition": "moving"},
    {"phase": "GoalReached",    "condition": "near_target"},
    {"phase": "Termination",    "condition": "terminated"}
  ],
  "terminal_success": {
    "condition": "near_target && terminated",
    "description": "The robot successfully arrives at the target and terminates the navigation skill."
  },
  "terminal_failure": {
    "condition": "collision || (skill_active && !target_received)",
    "description": "The robot collides or attempts to navigate without a valid target."
  }
}
```

> **Terminal states:** The APs used in `terminal_success.condition` and `terminal_failure.condition` are automatically extracted and **always included** in the `/ltl/required_aps` request to the LLM. The LLM also receives the terminal success and failure descriptions in `/ltl/state_description`, so it can evaluate them with full context at every step.

### 🤖 LLM-Based Formulas Generation (Natural Language)

Instead of writing `formulas.json` manually, you can generate it from a natural language description using `generate_formulas.py`:

```bash
python3 generate_formulas.py -d "Your natural language description of the robot skill..."
```

This will automatically call local Ollama to write the JSON specification to `formulas.json` and generate a human-readable text file `skill_description.txt` detailing the execution phases and properties.

### LTL Syntax

| Operator | Meaning | Example |
|---|---|---|
| `G(φ)` | **Globally** | `G(!collision)` |
| `F(φ)` | **Finally** | `F(goal)` |
| `X(φ)` | **Next** | `G(terminated -> X(!moving))` |
| `φ U ψ` | **Until** | `moving U near_target` |
| `->` | **Implies** | `G(skill_active -> target_received)` |
| `&&` | **And** | `moving && !collision` |
| `\|\|` | **Or** | `path_planned \|\| goal_unreachable` |
| `!` | **Not** | `!collision` |

---

## LLM-Based Predicate Evaluation

The `llm_client.py` node acts as a bridge between the physical/simulated robot state and the LTL monitor. It replaces hand-coded evaluators with a **local Ollama LLM** that reasons over raw sensor data.

```
 ┌─────────────────┐
 │   /odom topic   │ ──────┐
 └─────────────────┘       │
 ┌─────────────────┐       │   /ltl/required_aps
 │   /scan topic   │ ──────┼───────────────────────┐
 └─────────────────┘       │                       │
 ┌─────────────────┐       ▼                       ▼
 │  /tf, nav2, etc.│ ──▶ [ llm_client.py Node ] ◀── [ LTL Monitor Node ]
 └─────────────────┘       │
                           ▼ Prompt
                     ┌──────────┐
                     │  Ollama  │
                     └────┬─────┘
                          │ Response
                          ▼
                 /ltl/evaluations JSON
```

### Config & Usage

When running via `docker compose`, the LLM client automatically connects to the monitor node and local Ollama instance on the host (`host.docker.internal` or `localhost`).

To run it manually:

```bash
# Run with default settings (llama3.2:3b model)
python3 llm_client.py --model llama3.2:3b

# Run with a different Ollama URL or model
python3 llm_client.py --ollama-url http://192.168.1.50:11434 --model llama3.1:8b
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `llama3.2:3b` | Ollama model name |
| `--ollama-url` | `http://localhost:11434` | Ollama API endpoint |

### How It Works

For each monitoring step:
1. The monitor publishes `/ltl/required_aps` (automaton APs ∪ terminal APs) and `/ltl/state_description`.
2. The client fetches the current sensor snapshot (caches `/odom`, `/scan`, TF, etc.).
3. The client constructs a structured prompt describing the current robot state, the propositions to evaluate, and the **terminal success/failure descriptions** so the LLM has full context.
4. It calls Ollama via HTTP POST with `format: "json"` and `temperature: 0`.
5. It parses the resulting JSON and publishes the evaluated booleans to `/ltl/evaluations`.

### Example LLM Prompt

```
You are evaluating atomic propositions for a robot skill monitor.

Skill: GoToTarget — Autonomous navigation to a target location.
Phase: Navigation

Terminal conditions (evaluate these APs precisely):
  SUCCESS when: True when nav_status == 'succeeded' and distance_to_target < 0.5. Robot reached the target.
  FAILURE when: True when nav_status in ['aborted', 'canceled'] or min_range < 0.25. Navigation failed or collision.

Current sensor readings:
  position_x         = 2.0 m
  position_y         = 1.2 m
  linear_vel         = 0.31 m/s
  angular_vel        = 0.05 rad/s
  distance_to_target = 3.74 m
  min_range          = 0.62 m
  mean_range         = 2.10 m
  close_objects      = 1
  nav_status         = "executing"

Evaluate each proposition below to true or false.
Each description contains the exact rule to apply — follow it literally using the sensor values above.

  "moving_to_target": True when linear_vel > 0.05 and nav_status in ['accepted', 'executing']. Robot is driving toward the goal.
  "near_target": True when distance_to_target < 0.5. Robot is within acceptance radius of the target.
  "nav_status_success": True when nav_status == 'succeeded'. Nav2 confirmed goal reached.
  "nav_status_failure": True when nav_status in ['aborted', 'canceled']. Nav2 reported failure.
  "collision": True when min_range < 0.25. Imminent collision with obstacle.

Reply with ONLY a JSON object: keys are proposition names, values are booleans (true/false).
No markdown, no explanation.
```

### Supported ROS 2 Topics

| Topic | Message Type | Extracted Data |
|---|---|---|
| `/odom` | `nav_msgs/msg/Odometry` | position, linear/angular velocity |
| `/scan` | `sensor_msgs/msg/LaserScan` | min/max/mean range, close objects count |
| `/tf` | `tf2_msgs/msg/TFMessage` | transform data (used to determine distance to targets) |

### Performance Considerations

- **Latency**: ~0.5s - 2s per step with `llama3.2:3b` depending on GPU acceleration.
- **Robustness**: LLM evaluations are probabilistic. For safety-critical systems, rule-based fallbacks should be combined with the LLM evaluations.

## CLI Reference

```
Usage: ltl-monitor [-f FORMULA ...] | [--formulas-file FILE] [OPTIONS]
```

| Flag | Description |
|---|---|
| `-f FORMULA` | Inline LTL formula (repeat for multiple) |
| `--formulas-file FILE` | JSON file (flat array or rich skill-spec) |
| `--changes-only` | Only show formulas whose status changed at each step |
| `--stop-on-violation` | Halt on first permanent violation |
| `--output-dir DIR` | Directory for automaton image exports (default: `./output/`) |

---

## Monitor Status Model

Each formula tracks one of three states:

| Status | Symbol | Meaning | Permanent? | Can transition to |
|---|---|---|---|---|
| **INCONCLUSIVE** | `●` (yellow) | Neither proven nor refuted — more observations needed | No | ACCEPTED or VIOLATED |
| **ACCEPTED** | `✔` (green) | Automaton is in an accepting state — property holds over the trace so far | No | Can revert to INCONCLUSIVE |
| **VIOLATED** | `✘` (red) | Sink/trap state reached — property is permanently falsified | **Yes** | Terminal — no recovery |

In addition, the overall task has two **terminal states** evaluated at every step by the LLM:

| Terminal State | Condition source | Behavior |
|---|---|---|
| **SUCCESS** | `terminal_success.condition` in `formulas.json` | Monitor halts and prints final summary |
| **FAILURE** | `terminal_failure.condition` in `formulas.json` | Monitor halts and prints final summary |

The APs required to evaluate these conditions are always included in `/ltl/required_aps`, and their descriptions are sent in `/ltl/state_description` so the LLM can evaluate them with context at every step.

**Exit codes:** `0` = no violations, `1` = one or more formulas violated.

> **Why INCONCLUSIVE?** Liveness properties like `F(goal)` can only be fully verified on infinite traces. On finite traces, if the goal hasn't been reached yet, it's neither violated nor accepted — it's inconclusive.

---

## Visualization

The monitor prints the **full Büchi automaton structure** for every individual formula plus the **combined product automaton** (conjunction of all formulas) at startup. Example for two formulas:

```
Formulas & Büchi Automata Structure:

  Büchi Automaton for 'collision_avoidance' (Formula: G(!collision)):
    State 0 [initial, accepting]:
      ──► State 0 on: !collision
      ──► State 1 on: collision
    State 1 [sink/trap]:
      ──► State 1 on: 1

  Büchi Automaton for 'eventually_reach' (Formula: G(skill_active -> F(near_target))):
    State 0 [initial, accepting]:
      ──► State 0 on: !skill_active || near_target
      ──► State 1 on: skill_active && !near_target
    ...

Combined/Product Büchi Automaton — Whole Skill Specification:
  Büchi Automaton for 'CombinedSkillSpec' (Formula: (G(!collision)) && (G(skill_active -> F(near_target)))):
    State 0 [initial, accepting]:
      ...
```

Automaton images (DOT, SVG, PNG) are saved to `output/` for every formula and for the combined product automaton.

Use `--output-dir DIR` to change the output directory:

```bash
docker run --rm \
  -v ./formulas.json:/app/formulas.json \
  -v ./output:/app/output \
  ltl-monitor:latest --formulas-file formulas.json --output-dir /app/output
```

---

## Examples

### Example 1: High-Fidelity ROS 2 Simulation Demo (GoToTarget Skill)

This example runs a full dockerized robotics stack featuring the **Unitree G1 humanoid** modeled as a floating base in **MuJoCo**, autonomous path planning via **ROS 2 Nav2**, and real-time visualization via **Foxglove**.

```bash
# 1. Start the simulation, navigation, and monitoring stack
cd sim/
docker compose -f docker-compose.sim.yml up -d --build

# 2. Run the LLM-based predicate evaluator (on host)
# This uses local Ollama to evaluate Nav2 status, odometry, and lidar data
python3 llm_client.py --host localhost --port 5555 --mode ros2 --model llama3.2:3b

# 3. Visualize in Foxglove
# Open Foxglove Studio (web or desktop)
# Connect via "Foxglove WebSocket" to ws://localhost:8765

# 4. View all container logs at http://localhost:8080/dozzle
```

**Architecture of this Demo:**
1. **`ltl-mujoco-sim`**: Runs a custom ROS 2 Python bridge `mujoco_ros_bridge.py`. Simulates the G1's physics, publishes `/odom` and `/scan`, and executes `/cmd_vel` instructions.
2. **`ltl-nav2`**: The ROS 2 Navigation stack. Plans paths to a target on an empty map, avoiding obstacles (like the cylinder in `arena.xml`). Sends `/cmd_vel` back to MuJoCo.
3. **`ltl-monitor`**: The LTL runtime monitor. Prints the full Büchi automaton structure at startup, then monitors observations step by step.
4. **`ltl-foxglove-bridge`**: Exposes ROS 2 topics via WebSockets for visual debugging.
5. **`ltl-llm-client`**: Interrogates `llama3.2` using real-time ROS 2 `/odom` and Nav2 action status to yield boolean responses for predicates — including terminal success/failure APs — and sends them to the LTL monitor.
6. **`ltl-dozzle`**: Aggregates all container logs; accessible at http://localhost:8080/dozzle.

### Example 2: Inline LTL formulas via CLI

You can run the monitor with inline formulas instead of a config file:

```bash
docker run --rm -it ltl-monitor -f "G(!collision)" -f "F(near_target)"
```

### Sample Monitor Output

```
════════════════════════════════════════════════════════════════
  Skill : GoToTarget
  Autonomous navigation to a target location while avoiding obstacles.
════════════════════════════════════════════════════════════════

Formulas & Büchi Automata Structure:

  Büchi Automaton for 'collision_avoidance' (Formula: G(!collision)):
    State 0 [initial, accepting]:
      ──► State 0 on: !collision
      ──► State 1 on: collision
    State 1 [sink/trap]:
      ──► State 1 on: 1

  Büchi Automaton for 'eventually_reach' (Formula: G(skill_active -> F(near_target))):
    State 0 [initial, accepting]:
      ──► State 0 on: !skill_active || near_target
      ──► State 1 on: skill_active && !near_target
    State 1 [accepting]:
      ──► State 0 on: near_target
      ──► State 1 on: !near_target

Combined/Product Büchi Automaton — Whole Skill Specification:
  Büchi Automaton for 'CombinedSkillSpec' (Formula: (G(!collision)) && (G(skill_active -> F(near_target)))):
    State 0 [initial, accepting]:
      ──► State 0 on: !collision && (!skill_active || near_target)
      ...

[INFO] [ltl_monitor_node]: LTL Monitor ROS 2 Node started.

──────────────────────────────────────────────────────────────
  Monitoring Trace
──────────────────────────────────────────────────────────────
  ┌── Step init ──────────────────────────────────────────────
  │ ✔ collision_avoidance            S0 [initial, accepting]
  │ ✔ eventually_reach               S0 [initial, accepting]
  └──────────────────────────────────────────────────────────

  ┌── Step 0 [Navigation] ──────────────────────────────────
  │ TRUE :  moving_to_target  skill_active
  │ FALSE:  collision  near_target  nav_status_success  nav_status_failure
  │ ────────────────────────────────────────────────────────
  │ ✔ collision_avoidance            S0 [initial, accepting]
  │ ● eventually_reach               S0 [initial, accepting] → S1  ← INCONCLUSIVE
  └──────────────────────────────────────────────────────────

  ┌── Step 5 [Navigation] ──────────────────────────────────
  │ TRUE :  moving_to_target  skill_active  near_target  nav_status_success
  │ FALSE:  collision  nav_status_failure
  │ ────────────────────────────────────────────────────────
  │ ✔ collision_avoidance            S0 [initial, accepting]
  │ ✔ eventually_reach               S1 → S0 [initial, accepting]  ← ACCEPTED
  └──────────────────────────────────────────────────────────

════════════════════════════════════════════════════════════════
  ◉  MONITOR IDLE
  Reason   : Terminal state reached (success or failure)
  Awaiting : new skill execution
  Resume   : send {"__reset__": true} on /ltl/evaluations
           : or update formulas.json to reload automatically
════════════════════════════════════════════════════════════════
```

---

## How It Works Internally

### Overview

The system verifies robot behavior against LTL (Linear Temporal Logic) safety and liveness properties **at runtime**, one observation at a time. It converts each LTL formula into a finite-state machine (Büchi automaton) and steps it forward with each new evaluation published by the LLM client.

The key insight: **the monitor doesn't check everything — it tells the LLM what to check.** Before each step, it inspects its automaton states to determine exactly which atomic propositions (APs) matter for the next transition, then **adds the APs from the terminal success/failure conditions** on top, and publishes the full list to `/ltl/required_aps`.

### Step-by-Step Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STARTUP (once)                                                        │
│                                                                        │
│  1. Parse formulas.json                                                │
│     ↓                                                                  │
│  2. For each formula, call:                                            │
│     spot.translate(formula, "Buchi", "det", "complete", "sbacc")       │
│     → produces a deterministic, complete Büchi automaton               │
│     ↓                                                                  │
│  3. Build combined product automaton (conjunction of all formulas)     │
│     → print full structure (all states + transitions) to stdout        │
│     → save DOT/SVG/PNG images to output/                               │
│     ↓                                                                  │
│  4. Extract terminal APs from terminal_success/failure conditions      │
│     ↓                                                                  │
│  5. Initialize ROS 2 Node (LtlMonitorNode), subscribe to               │
│     /ltl/evaluations and publish /ltl/required_aps                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  MONITORING LOOP (repeats on evaluations callback)                     │
│                                                                        │
│  6. required_aps = automaton_aps ∪ terminal_aps                        │
│     ↓                                                                  │
│  7. Publish required_aps and state_description JSON (includes          │
│     terminal_success / terminal_failure context) to topics             │
│     ↓                                                                  │
│  8. LLM Node evaluates ALL required APs from sensors/topics,           │
│     using terminal context descriptions from state_description         │
│     ↓                                                                  │
│  9. LLM Node publishes evaluation results to /ltl/evaluations          │
│     ↓                                                                  │
│  10. Convert evaluation → BDD cube                                     │
│     ↓                                                                  │
│  11. For each automaton, find the matching outgoing edge               │
│      (BDD-AND of edge condition and evaluation ≠ false)                │
│     ↓                                                                  │
│  12. Move to successor state, compute new status:                      │
│      • Accepting state?  → ACCEPTED                                    │
│      • Sink state?       → VIOLATED (permanent)                        │
│      • Otherwise?        → INCONCLUSIVE                                │
│     ↓                                                                  │
│  13. Check terminal conditions (success / failure) using same          │
│      observation — halt and print summary if terminal reached          │
│     ↓                                                                  │
│  14. Print status changes, goto step 6                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Worked Example: `G(!collision)`

Let's trace exactly what happens for the formula `G(!collision)` ("globally, no collision"). This formula produces a **2-state Büchi automaton**:

```
         [Büchi automaton for G(!collision)]

        !collision              1 (any)
      ┌───────────┐         ┌──────────┐
      ▼           │         ▼          │
  ┌────────┐      │    ┌────────┐      │
→ │ State 0│ ─────┘    │ State 1│ ─────┘
  │  (acc) │ ─────────▶│ (sink) │
  └────────┘ collision  └────────┘
   ACCEPTED              VIOLATED
```

- **State 0** (accepting): The automaton starts here. Self-loop on `!collision` (stays accepted). Transitions to state 1 on `collision`.
- **State 1** (sink): Self-loop on `bddtrue` (any input). Non-accepting. Once entered, never leaves → **permanently VIOLATED**.

#### Step 0: Monitor asks, LLM responds

**Monitor inspects state 0's outgoing edges:**
- Edge 1: condition = `!collision`, destination = state 0
- Edge 2: condition = `collision`, destination = state 1

The BDD support contains one variable: `collision`. Terminal APs (e.g., `nav_status_success`, `nav_status_failure`) are added on top. So `/ltl/required_aps` publishes:

```json
["collision", "nav_status_success", "nav_status_failure"]
```

**`/ltl/state_description` includes:**
```json
{
  "phase": "Navigation",
  "terminal_success": {"description": "Robot successfully reached target and terminated.", "aps": ["nav_status_success"]},
  "terminal_failure": {"description": "Navigation failed or collision detected.", "aps": ["nav_status_failure"]}
}
```

**LLM evaluates all APs with terminal context and returns:**
```json
{"collision": false, "nav_status_success": false, "nav_status_failure": false}
```

**Monitor processes:**
1. Transitions to **state 0** (self-loop on `!collision`) → **ACCEPTED** ✔
2. Terminal check: neither condition met → continue monitoring

#### Step 1: Collision detected

**LLM publishes:**
```json
{"collision": true, "nav_status_success": false, "nav_status_failure": false}
```

**Monitor processes:**
1. Transitions to **state 1** (sink) → **VIOLATED** ✘
2. Terminal check: `terminal_failure_condition` is evaluated → halt if true

---

## API Reference

### `monitor.py`

#### `MonitorStatus` (Enum)
- `INCONCLUSIVE`, `ACCEPTED`, `VIOLATED`

#### `LTLMonitor(formula, name=None)`
- `step(observation) → MonitorStatus`
- `get_required_aps() → set[str]` — APs in outgoing edges of current state
- `format_automaton() → str` — human-readable full automaton structure (all states + transitions)
- `reset()` / `export_dot()` / `num_states()`

#### `MultiMonitor(formulas, names=None)`
- `step(observation) → dict[str, MonitorStatus]`
- `get_required_aps() → set[str]` — union across all monitors
- `statuses()` / `reset()` / `all_accepted()` / `any_violated()`

### `main.py`

#### `LtlMonitorNode` (ROS 2 Node)
- Subscribes to `/ltl/evaluations` (`std_msgs/msg/String`)
- Publishes `/ltl/required_aps` and `/ltl/state_description` (`std_msgs/msg/String`)
- Steps the `MultiMonitor` state on incoming evaluations
- Always includes terminal APs (extracted from `terminal_success/failure.condition`) in required APs
- Includes terminal success/failure descriptions in state description

#### `_extract_aps_from_condition(condition: str) → set[str]`
- Parses a boolean condition string and returns all identifier names (AP names).

### `llm_client.py`

#### `LlmClientNode` (ROS 2 Node)
- Subscribes to `/ltl/required_aps`, `/ltl/state_description`, `/odom`, `/scan`
- Publishes `/ltl/evaluations` (`std_msgs/msg/String`)
- Formulates prompts for Ollama to evaluate required APs (including terminal APs) based on cached sensor data and terminal context descriptions

---

## License

This project uses the [Spot](https://spot.lrde.epita.fr/) library (GNU GPL v3).
