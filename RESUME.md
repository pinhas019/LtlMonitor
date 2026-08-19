# Resume

**Newest session first.** Sessions 1 and 2 below are kept for the decisions they
record, not for their status lines — every "unpushed", test count and `/ltl/*` topic
name in them is out of date. Session 3 is the current state.

---

# Session 3 — package split, waves 1–2 (2026-08-19)

Everything is pushed. `git clone git@github.com:pinhas019/LtlMonitor.git` and
`git checkout dev` is the whole handoff; nothing lives on one disk.

```
origin  git@github.com:pinhas019/LtlMonitor.git
dev     ecd3634    python3 -m pytest  →  704 passed, ~15 s
```

Setup on a fresh machine: Python 3.10 and `pytest`. There is no `requirements.txt`
and the suite needs nothing else. **`rclpy` and `spot` are not installed and are not
needed** — `tests/ros_stub.py` fakes the ROS layer, and everything in
`skill_monitor/backend/` is therefore *unrun* code on a dev host. Say so in commits
rather than implying it was tested. The package is on `sys.path` via a `.pth` in user
site-packages; `pip install -e .` fails here (setuptools predates PEP 660).

## Where the work is

The plan of record is [docs/packages/README.md](docs/packages/README.md) — ownership
matrix, merge order, and the P0–P12 briefs. Read that plus
[docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md) and
[docs/clocking.md](docs/clocking.md) before touching code.

| package | branch | state |
|---|---|---|
| P0 contracts | `core/feat-wire-contract` | **merged** (PR #1 carried the docs; the module landed with it) |
| P1 clock | `core/feat-clock-service` | **merged** — PR #2 |
| P2 observation | `core/feat-observation-window` | **merged** — PR #3 |
| P6 gateway | `backend/feat-gateway` | **merged** — PR #5 |
| P12 planner-independent schema (doc) | `docs/feat-planner-independent-schema` | **merged** — PR #1. Implementation not started |
| P4 monitor | `backend/feat-verdict-topic` | **PR #4 open**, rebased on `ecd3634`, 773 pass. Wants a re-review |
| P5 supervisor (doc) | `docs/feat-episode-end-stops-actuating` | **PR #6 open**, docs only, rebased, 704 pass |
| P3 evaluator | `backend/feat-evaluator-tick` | not started |
| P5 supervisor (code) | `backend/refactor-supervisor-token` | not started |
| P7 frontend | `frontend/feat-observation-panel` | not started |
| P8 deploy | `deploy/feat-container-split` | not started |
| P9 docs | `docs/feat-architecture-map` | not started |

Open PRs: [#4](https://github.com/pinhas019/LtlMonitor/pull/4),
[#6](https://github.com/pinhas019/LtlMonitor/pull/6).

## What landed, and the bugs it killed

- **`core/api.py`** is now the single wire contract: `/monitor/*` topic constants,
  `SCHEMA_VERSION`, and a builder + validator per payload. JSON in
  `std_msgs/String`, so `core/` keeps its no-ROS property and the gateway stays a
  pass-through.
- **The clock is a service.** `Δ = 1/tick_hz` **seconds**; tick *k* is the half-open
  interval `(B_k−1, B_k]`, named by the boundary that closes it; `seq=0` means nothing
  has closed yet, so the first pulse is `seq=1`. `t0` is the restart discriminator —
  same `t0` with a lower `seq` is a redelivery to drop, a different `t0` is a new clock.
  Without it a restarted clock made the monitor permanently deaf (every re-numbered
  pulse read as stale); that is fixed and tested.
- **The observation window** folds event-driven arrivals and emits on the tick.
  `SensorState.tick()` is the *sole* writer of held values, so they are tick-stable.
- **The gateway** proxies ROS to HTTP/WS with the payload byte-identical on both
  transports. Hardened over real loopback sockets: loopback bind, Host allowlist
  (DNS rebinding), `Transfer-Encoding` and negative `Content-Length` rejected
  (CL.TE smuggling — an earlier body-limit fix answered 413 without draining, and a
  pipelined `POST /api/clock/mode {"paused":true}` executed), `X-Skill-Monitor`
  required (CSRF), body cap, stream cap.

## Next actions, in order

1. **Re-review and merge PR #4.** Four blockers were fixed and pushed. Outstanding
   non-blocking findings: `tests/ros_stub.py` timers never fire and its QoS enums are
   aliased strings; `_mode_sources` is recomputed per call; the `fault_category` alias
   loop in `tests/test_manifest.py` asserts what the fixture already fixed.
2. **After #4 merges**, drop `skill_monitor/backend/ablation_runner.py` and
   `.../monitor_node.py` from `AWAITING_MIGRATION` in `tests/test_api.py:506` —
   `test_the_migration_allowlist_is_still_accurate` fails if an entry no longer has a
   literal, so it will tell you. Branch `chore/prune-migration-allowlist`.
3. **PR #6** carries the episode-end decision (see below) but the agent stalled before
   applying the matching corrections to `architecture.md` and `clocking.md`. Finish
   those, then merge.
4. **Wave 3 — P3, P5, P7** can then run concurrently. P7 must import from
   `core/discovery.py` rather than re-scanning, and must send `X-Skill-Monitor` on
   every gateway call.
5. **P12 implementation** is blocked on two facts only a robot can supply: the D435i
   depth topic name (likely `/camera/camera/depth/color/points`) and calibration of
   `arrival_radius`, the `closing_speed` epsilon, the `no_progress` `debounce_s` and
   the `min_range` height band.

## Decisions taken this session (do not re-litigate)

1. **Merges happen only through a pull request, and the merge is fast-forward.** Never
   `git merge` a feature branch into `dev` locally. Pull with `git pull --rebase`.
   This is rule 1 in [CONTRIBUTING.md](CONTRIBUTING.md#non-negotiable) and it was
   violated once in wave 1; the fix was to leave it and use PRs from then on.
2. **The monitor is planner-independent.** It reads the robot's own sensors and the
   waypoints the robot was *commanded* to reach — never the planner's self-report.
   TRAV replaced Nav2 and the monitor should not have noticed. `/path_manager/status`,
   `/traversable_path*` and `/filtered_map` are forbidden inputs — **the decision is
   recorded but nothing enforces it yet**; `test_no_forbidden_topic_in_any_descriptor`
   ships with P12's implementation, and six of today's fourteen schema keys still come
   from `/path_manager/status`. See
   [docs/packages/P12-planner-independent-schema.md](docs/packages/P12-planner-independent-schema.md).
3. **Episode-end is stop-actuating.** The supervisor treats the end of an episode the
   same as a halt token: it stops actuating. This resolves the TIMEOUT/PROGRESS
   divergence found in the token/halt agreement table. PR #6 specifies it.
4. **Hardware agnosticism is verified, not asserted.** `real_g1`, `mujoco` and
   `isaac_lab` expose an identical 14-key schema over completely different topics:
   ```bash
   python3 -c "from skill_monitor.core import adapter_spec as a; \
     print({n: sorted(a.load(n).keys()) == sorted(a.load('real_g1').keys()) for n in a.available()})"
   ```

## Watch out for

- **Rebasing a wave-1 branch onto today's `dev` breaks quietly.** `t0` became a
  *required* field of `build_tick`, so a fixture that omits it now raises at the call
  site — and, worse, a pulse without `t0` is refused by `validate_tick`, which
  silently stops the clock. Four stall tests on PR #4 were asserting against a
  detector that was never being pulsed. Run the whole suite after every rebase, not
  the package's own file.
- The suite takes ~15 s on `dev` but ~80 s on `backend/feat-verdict-topic`; that is
  the branch's own tests, not a hang.
- Agent worktrees under `.claude/worktrees/` are gitignored and were all pruned. A
  stalled agent can leave a worktree whose index is reset to an *ancestor* commit —
  it looks like 500 deleted lines and is not real work. Diff it against the branch's
  own history before believing it.

---

# Session 1 — 2026-08-17

Plan of record: `THESIS_PLAN.md` on TRAV branch `ltl-skill-monitor` (revision 4).

---

## 1. Where everything lives now

| path | what | tip | pushed? |
|---|---|---|---|
| `~/skillMonitor` | **the monitor** — standalone layered package (was the MiniGrid submodule) | `dev` | **NO** — unpushed, see `git status -sb` |
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

---

# Session 2 — branch `gui-and-manifest` (2026-08-17)

Merged into `dev` (fast-forward) along with `docs: branching and commit
conventions`; both branches deleted. **`dev` is unpushed** — `git status -sb` for
the count. Run `python3 -m pytest` (105 pass, no ROS needed) and
`python3 -m skill_monitor.frontend.skill_center --mock --mock-llm` to see the panel
without a robot.

## What changed

1. **Adapters are data.** `skill_monitor/adapters/{real_g1,mujoco,isaac_lab}.json`
   declare the sensor schema AND which topic field feeds which key;
   `core/adapter_spec.py` interprets them (pure), `backend/adapters/declarative.py`
   is the only ROS part left (message-type lookup + four decoders). Adding a robot is
   a JSON file. Descriptors are validated on load — a step writing an undeclared key,
   an unknown extractor, or a schema key nothing ever produces all fail immediately.
2. **A manifest API.** `/ltl/manifest` (skill) and `/ltl/adapter` (robot) are latched
   JSON; `/ltl/state_description` now also carries `phase_index`, `phases`,
   `ap_values` and `sensors`. `/ltl/load_spec` accepts a spec over the wire, validated
   against the adapter schema, answered on `/ltl/spec_status`. Contract lives in
   `core/manifest.py`.
3. **Generation reads the robot's schema.** `generate_formulas.SENSOR_SCHEMA` was a
   hardcoded list of fields no adapter provides (`distance_to_target`, `nav_status`,
   `mean_range`, `close_objects`) — every spec generated from it was rejected by
   `spec_contract`. Replaced by `schema_prompt(schema)` + a `generate → validate →
   repair` loop with the LLM injected. Tested against a scripted model only.
4. **Skill Center rewritten**: Live / Spec / Timeline tabs, all manifest-driven.
   `--mock` runs the whole panel with no ROS; `--mock-llm` scripts the model;
   `--tab` opens a given tab (for screenshots).

## Verified

- 105 pytest, `skill_center --selftest`, all pure.
- The panel was run on screen (DISPLAY=:1) and screenshotted: Live tab (phase strip,
  AP table with live values, sensors, failure modes), Timeline (phase transitions,
  staleness + recovery, warn onsets), Spec tab.
- **NOT verified against ROS**: this host has no rclpy or spot, so nothing in
  `backend/` has been executed. The manifest topics, the latched QoS and the
  declarative adapter's subscriptions are unrun code.

## Next

- Run monitor + evaluator in the Docker images and confirm `/ltl/manifest` and
  `/ltl/adapter` appear and the panel populates from a real graph.
- The three Python adapters are now duplicates of the JSON descriptors, kept as
  `--adapter real_g1_py` etc. Delete them once the declarative path has run on the
  robot; until then they are the fallback.
- `--adapter` names: `real_g1` is now the JSON descriptor, `real_g1_py` the class.
  Any launch script passing `--adapter real_g1` gets the declarative one.
- Push `dev`. See `CONTRIBUTING.md` for the branching convention
  adopted this session: `<layer>/<type>-<topic>`, one branch per coherent change.
