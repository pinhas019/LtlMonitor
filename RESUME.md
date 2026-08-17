# Resume — session of 2026-08-17

Handoff for continuing in a new chat. Plan of record: `THESIS_PLAN.md` on TRAV
branch `ltl-skill-monitor` (revision 4).

---

## 1. Where everything lives now

| path | what | tip | pushed? |
|---|---|---|---|
| `~/skillMonitor` | **the monitor** — standalone layered package (was the MiniGrid submodule) | `e550c3b` | **NO** — 6 ahead of `origin/dev` |
| `~/TRAV-metric-map` @ `pinhas-remote-control` | robot's branch; TRAV nav stack + the passive logger | `1573498` | **NO** — 1 ahead |
| `~/TRAV-metric-map` @ `ltl-skill-monitor` | LTL launch scripts, THESIS_PLAN.md, CLIP goal matcher | `35b80a4` | **diverged** — rebased after the last push |
| `~/TRAV-metric-map` @ `image-fusion` | 1 unmerged commit | `a40055b` | yes |
| `~/Minigrid` | submodule removed, imports repointed at the package | `80b3f1b` | **NO** |
| `~/LtlMonitor` | **deleted** — was a dead pre-adapter clone | — | artifacts archived in `~/skillMonitor` |

`~/skillMonitor` is installed via a `.pth` in the user site-packages (this
machine's setuptools predates PEP 660, so `pip install -e .` fails).

**Nothing from this session is pushed.** `image-fusion` and the earlier
`ltl-skill-monitor` force-push were the last things to reach a remote.

## 2. Robot state

- `unitree@192.168.123.164:/home/unitree/TRAV`, branch `pinhas-remote-control`,
  synced to `4c413d7` and **clean, 24/24 tests passing**.
- The logger commit `1573498` is NOT yet on the robot — it landed after the sync.
  Re-run `./sync_to_g1.sh --go` from the `pinhas-remote-control` checkout.
- **The robot went offline mid-session** and stayed unreachable.
- The dev host **cannot see the robot's ROS graph**: route is via
  `192.168.140.254` (different subnet) and the DDS config uses spdp multicast on
  `eth0`. Any online monitoring must run ON the robot.
- Robot-side docker state was never verified — ssh timed out twice.

## 3. Fixed this session

| bug | where | commit |
|---|---|---|
| **Rule regex truncated at decimal points** — `min_range < 0.25` evaluated as `min_range < 0`, so `collision_risk` could NEVER fire and `G(!collision_risk)` was dead; `visually_at_goal` fired at similarity > 0 | 3 copies of the regex | `c2dd324` |
| Monitor `rclpy.shutdown()` on first fault | `--passive` → IDLE instead | `3739079` |
| Dead sensor read as safe (`min_range` default 10.0) | per-source `Freshness` | `3739079` |
| `trigger_confidence` hardcoded 1.0, gate inert | fed by freshness via `__confidence__` | `3739079` |
| Label vocabularies disjoint from `named_failure_modes` | `fell_over` from odometry | `035936c` |
| Terrain never captured ⇒ no sim re-execution | bag recording default-ON | `72595b7` |
| Docker `sudo` fallback never tried | `skill_center` | `d1e7577` |
| `rclpy.init()` unguarded, discovery thread died silently | `skill_center` | `d1e7577` |

## 4. Built this session

- **`src/main/monitor_logger.py`** (on `pinhas-remote-control`) — read-only episode
  logger. JSONL per episode + hand-correctable `episodes.csv`, `fell_over` from
  odometry, per-episode bag (terrain + tf + cmd_vel), `--preflight`, disk guard.
- **`skill_monitor/core/spec_contract.py`** — the validation oracle for generated
  specs, shared by runtime, contract test and (soon) the generator.
- **Per-adapter `SCHEMA`** — replaced the global `CANONICAL_SENSOR_EVAL_KEYS`.
  Adapter = per embodiment, spec = per skill.
- **`skill_monitor/frontend/skill_center.py`** — standalone control panel.
  Discovers monitors by ROS graph scan (`<ns>/ltl/state_description`), shows
  status/health, controls container lifecycle + arm/reset.
- **Package restructure** — `core/` (pure logic, no ROS/Tk) → `backend/` (ROS) →
  `frontend/`, plus `describer/`, `specs/`, `tests/`, `deploy/`.

66 tests pass, `skill_center --selftest` passes, logger `--selftest` passes.

## 5. Decisions taken (do not re-litigate)

1. **The claim is skill-agnostic monitor synthesis**: free-language description →
   monitor, engine unchanged. Navigation is the first instance, not the subject.
2. `formulas_g1.json` is hand-authored ⇒ **evaluation reference only**, not the
   product. Shipping it would falsify the claim.
3. **Isaac Sim = re-execute counterfactuals**, not just visualise. Gated on
   fidelity validation: reproduce known outcomes first, report the exclusion count.
   `adapter_isaac_lab` is NOT the vehicle (it monitors Nav2; the G1 runs
   `path_manager`) — the sim must run the same stack.
4. Passive mode = **stay alive, manual reset** (not auto re-arm).
5. Staleness feeds `trigger_confidence` (no new sensor_eval keys).
6. Skill Center is **standalone**, must detect any skill, no TRAV dependency.
7. Toggle = **both** container lifecycle and pause.
8. Robot carries **no LTL code**; the logger is stack instrumentation, not monitor
   code, so it lives on `pinhas-remote-control`.
9. MiniGrid depends on the monitor **as an installed package**.
10. LLM endpoint is **192.168.140.101** (was wrong as .111 in 4 places).

## 6. Blockers

- **arm64 Spot image not built.** Gates all online monitoring on the Jetson.
  Offline replay is gated on nothing.
- **`nvcr.io/nvidia/isaac-sim:4.5.0` was deleted** during disk cleanup. Blocks 5–6
  need it; recovering means NGC credentials + a 15GB pull. Start that early.
- Robot offline; robot-side docker state unverified.

## 7. Next actions

**Tomorrow's capture run** (does not depend on anything blocked):
```bash
# host, from the pinhas-remote-control checkout
./sync_to_g1.sh && ./sync_to_g1.sh --go
# robot, with the stack running
python3 src/main/monitor_logger.py --config src/main/path_manager.yaml --preflight
python3 src/main/monitor_logger.py --config src/main/path_manager.yaml --out ~/nav_episodes
```
Induce failures via the planner's own terminal states (dead end → `no_path` /
`unreachable` / `no_traversable`); the 15s hold distinguishes real from transient.
**`fell_over`'s height threshold is UNCALIBRATED** — check `base_height` on a
standing G1 first.

**Block 1, remaining** (was in progress when the session ended):
- Point `generate_formulas.py` at the adapter schema instead of its hardcoded
  `SENSOR_SCHEMA` (7 canonical keys short today).
- Fold `spec_contract.validate()` into generation as generate→validate→repair.
  **Build against a mocked LLM** — no live runs (user's instruction).
- Add an `/active_skill` publisher (Skill Center is the natural home).

**Housekeeping:** push everything (4 repos/branches unpushed); optionally
`sudo rm -rf ~/Minigrid/minigrid/envs/cst/ltl_monitor` (root-owned `output/`
renders are all that survive there).
