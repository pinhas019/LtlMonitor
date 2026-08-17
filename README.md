# Skill Monitor

Runtime progress monitoring for robot skills. A free-language description of a
skill is compiled into a monitor — progress states, LTL guards, failure modes —
which then watches the skill execute and reports where it is and where it is
going wrong.

The engine is skill-agnostic: navigation and manipulation differ only in their
generated spec, not in any code here.

## Layout

Layers are one-directional — `core` knows nothing about the layers above it.

| directory | what lives here | may import |
|---|---|---|
| `skill_monitor/core/` | **Logic.** Büchi automata, the spec-contract oracle, guard/geometry helpers. No ROS, no Tk, no network. | stdlib, spot |
| `skill_monitor/backend/` | **ROS layer.** Monitor + evaluator nodes. | core |
| `skill_monitor/backend/adapters/` | The declarative adapter (msg lookup + decoders) and the older hand-written ones. | core |
| `skill_monitor/adapters/` | One JSON **descriptor per embodiment**: sensor schema + which topic field feeds which key. Data, not code. | — |
| `skill_monitor/frontend/` | **Operator surface.** Skill Center control panel. | core (via ROS topics only) |
| `skill_monitor/describer/` | Free-language description → validated spec. | core |
| `skill_monitor/specs/` | The specs. Reach them with `skill_monitor.spec_path("g1")`. | — |
| `tests/` | Pure-python, no ROS, no hardware. | all |
| `deploy/` | Dockerfiles for the two images. | — |
| `sim/` | MuJoCo + Nav2 verification harness. | — |

The split that matters: **adapter = per embodiment, spec = per skill.** Two skills
on one robot share an adapter and differ only in `formulas_<skill>.json`. That is
what keeps the engine unchanged across skills.

## The wire contract

Everything a client needs is published as plain JSON, so nothing that watches a
monitor has to import this package, share its filesystem, or know the skill:

| topic | who publishes | what |
|---|---|---|
| `/ltl/manifest` | monitor (latched) | the skill: APs, formulas, phases, failure modes, terminals |
| `/ltl/adapter` | evaluator (latched) | the robot: sensor schema, topic → key map |
| `/ltl/state_description` | monitor, per tick | phase, AP values, sensor values, risk, failure-mode status |
| `/ltl/required_aps` | monitor, per tick | which APs to evaluate this step |
| `/ltl/evaluations` | evaluator | AP booleans + `__confidence__`, `__stale__`, `__sensors__` |
| `/ltl/load_spec` | anyone | a spec to adopt, validated against the adapter schema first |
| `/ltl/spec_status` | monitor (latched) | accepted, or the problems that got it rejected |

The two manifests are TRANSIENT_LOCAL, so a panel that connects mid-mission gets
them immediately rather than waiting for a change that may never come.

## Adding a robot

Write `skill_monitor/adapters/<name>.json`: a schema (or a reference to a shared
one) and one entry per topic saying which field becomes which sensor key. Field
paths and a handful of named extractors (`quat_to_roll_pitch`, `min_range_points`,
`stuck_streak`, …) cover the plumbing; anything needing real math is a named
function in `core/adapter_spec.py`, not more JSON. It is validated on load — a step
writing a key the schema does not declare fails immediately.

## Install

```bash
pip install -e .          # or, on an older setuptools:
echo /home/humanoid/skillMonitor > "$(python3 -c 'import site;print(site.getusersitepackages())')/skill-monitor.pth"
```

`core/` needs only the stdlib, so the tests run anywhere. `backend/` needs a ROS 2
environment, and the monitor engine needs Spot — both supplied by the Docker
images in `deploy/`, not by pip.

## Run

```bash
python3 -m pytest                                   # 105 tests, no ROS needed
python3 -m skill_monitor.frontend.skill_center            # control panel
python3 -m skill_monitor.frontend.skill_center --mock     # simulated monitor, no ROS
python3 -m skill_monitor.frontend.skill_center --mock --mock-llm   # …and no LLM
python3 -m skill_monitor.backend.monitor_node   --formulas-file skill_monitor/specs/formulas_g1.json --passive
python3 -m skill_monitor.backend.evaluator_node --adapter real_g1
```

Build the images from the repo root (build context must be the root, so the whole
package is copied):

```bash
docker build -f deploy/Dockerfile.monitor   -t ltl-monitor:latest .
docker build -f deploy/Dockerfile.evaluator -t ltl-client:latest  .
```

## History

This was `minigrid/envs/cst/ltl_monitor`, a submodule of the MiniGrid repo. It is
now standalone; MiniGrid imports it as an installed package. `docs/README_legacy.md`
is the previous README, written against the flat layout — file names there are
stale, the concepts are not.
