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
| `skill_monitor/backend/adapters/` | One per **embodiment**. Each declares the sensor schema that robot provides. | core |
| `skill_monitor/frontend/` | **Operator surface.** Skill Center control panel. | core (via ROS topics only) |
| `skill_monitor/describer/` | Free-language description → validated spec. | core |
| `skill_monitor/specs/` | The specs. Reach them with `skill_monitor.spec_path("g1")`. | — |
| `tests/` | Pure-python, no ROS, no hardware. | all |
| `deploy/` | Dockerfiles for the two images. | — |
| `sim/` | MuJoCo + Nav2 verification harness. | — |

The split that matters: **adapter = per embodiment, spec = per skill.** Two skills
on one robot share an adapter and differ only in `formulas_<skill>.json`. That is
what keeps the engine unchanged across skills.

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
python3 -m pytest                                   # 66 tests, no ROS needed
python3 -m skill_monitor.frontend.skill_center      # control panel
python3 -m skill_monitor.frontend.skill_center --demo      # with a fake monitor
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
