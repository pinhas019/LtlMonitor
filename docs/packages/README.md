# Work packages

Ten packages. **P0 lands first and alone**; P1–P9 then run concurrently, one agent each.
File ownership is disjoint by construction, so two agents never edit the same file.

Read [../architecture.md](../architecture.md) for what the system is, [../api.md](../api.md)
for the contract, [../clocking.md](../clocking.md) for the tick. Then your package file.

## Why P0 is blocking

Every package publishes or consumes `/monitor/*` payloads. If each agent invents its own
topic names and JSON keys, reconciliation is a rewrite. P0 is one pure module — topic
constants plus a builder and validator per payload — that every other package imports. The
`/ltl/*` → `/monitor/*` rename then happens *because* a package imported the constant, not
as a nine-branch sweep someone forgets.

## Ownership matrix

| package | branch | owns | depends on |
|---|---|---|---|
| [P0 contracts](P0-contracts.md) | `core/feat-wire-contract` | `core/api.py`, `tests/test_api.py` | — |
| [P1 clock](P1-clock.md) | `core/feat-clock-service` | `core/clock.py`, `backend/clock_node.py`, `deploy/Dockerfile.clock`, `tests/test_clock.py` | P0 |
| [P2 observation](P2-observation.md) | `core/feat-observation-window` | `core/adapter_spec.py`, `core/stuck_detector.py`, `adapters/*.json`, `tests/test_adapter_spec.py`, `tests/test_stuck_detector.py` | P0 |
| [P3 evaluator](P3-evaluator.md) | `backend/feat-evaluator-tick` | `backend/adapters/*`, `backend/evaluator_node.py` | P0, P2 |
| [P4 monitor](P4-monitor.md) | `backend/feat-verdict-topic` | `backend/monitor_node.py`, `core/manifest.py`, `tests/test_manifest.py` | P0 |
| [P5 supervisor](P5-supervisor.md) | `backend/refactor-supervisor-token` | `backend/intervention_supervisor.py`, `core/supervisor_logic.py`, `core/monitor_action.py`, their tests | P0, P4's verdict shape |
| [P6 gateway](P6-gateway.md) | `backend/feat-gateway` | `backend/gateway.py`, `deploy/Dockerfile.gateway`, `tests/test_gateway.py` | P0 |
| [P7 operator surface](P7-frontend.md) | `docs/feat-p7-operator-surface` | `frontend/*`, `deploy/Dockerfile.skill_center`, `tests/test_skill_center.py` | P0, **P6 (merged)** |
| [P8 deploy](P8-deploy.md) | `deploy/feat-container-split` | `skill_monitor/__init__.py`, `deploy/*`, `sim/docker-compose.sim.yml`, `tests/test_config_resolution.py` | — |
| [P12 planner-independent schema](P12-planner-independent-schema.md) | `core/feat-planner-independent-schema` | `adapters/nav_schema.json`, `adapters/real_g1.json`, the new extractors in `core/adapter_spec.py`, the regenerated spec, `tests/test_planner_independence.py` | **P2, P3** |
| [P9 docs](P9-docs.md) | `docs/feat-architecture-map` | `docs/*`, `README.md`, `CONTRIBUTING.md` | — |

Concatenate the "files owned" column and check for duplicates — that check is the guarantee
that the packages are concurrent rather than merely parallel.

## Merge order

1. **P0 alone** to `dev`. Every other agent branches from that commit.
2. Data path in order, each rebased on `dev`: **P2 → P3 → P4 → P5**.
3. **P1, P6, P7, P8, P9** merge whenever green.
4. A final pass reconciles the interface boundaries and runs the whole suite once.

## What P7 asks of its neighbours

The operator surface is the one package that can only show what somebody else publishes, so
[P7](P7-frontend.md) names six payload fields and six routes or topic constants it wants —
from **P0, P3, P4, P6 and P12**, not from P3 and P4 alone. They are listed in that document
with their owners and their reasons. Three rules keep this from becoming P7 editing other
packages' files:

- **A payload field is P0's before it is the producer's.** `api._check_fields` is closed by
  default, so a field emitted before `core/api.py` admits it makes the payload *invalid*
  rather than merely unrendered. Only the manifest validates with `closed=False`, which is
  why the two manifest fields are the only ones a single package can add alone.
- **A route is P6's, whoever owns the payload.** Topic names are P0's constants and routes
  are `gateway.py`, so "the package that owns the payload adds it" is not true of a topic
  pair. P7 asks in a PR comment; it does not reach across.
- **P7 must render without any of the fields.** Each pane degrades to "not reported by this
  build" and names the gap. A frontend that cannot start until four other packages land is a
  frontend that gets built last and rushed. The *routes* are the exception, and P7 says which
  panes ship visibly disabled instead.

`skill_monitor/core/automata.py` — the only file importing `spot`, and the one that would
have to emit an automaton graph — appears in **no row of the matrix above**. P7 names the gap
rather than filling it.

## Rules for every package

- Fully mocked tests. No ROS, no sockets, no hardware, no live LLM — see
  [../../CONTRIBUTING.md](../../CONTRIBUTING.md#tests).
- One logical unit per commit; the body says **why**, not what.
- Touch nothing outside your "files owned" list. If you need a change elsewhere, say so in
  your PR body and let the owning package make it.
- Schemas live in [../api.md](../api.md). Link, never restate.
- This host has no `rclpy` and no `spot`, so nothing in `backend/` can be executed here. Say
  so in the commit rather than implying it was tested.

## Deferred — not parallel packages

**P10 — three-valued verdict.** UNKNOWN travels as a sibling `unknown_aps` list, never
inside the observation dict; the automaton freezes rather than guesses. Must follow P4. The
design is settled in [../clocking.md](../clocking.md#three-valued-aps).

**P11 — spec bounds in seconds.** `max_steps` → `max_duration_s`. Also the gate on `tick_hz`
ever being anything other than 1.0: raising it earlier silently rescales every timeout in
every spec.
