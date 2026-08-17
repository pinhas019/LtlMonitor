# Contributing

One person works on this repo at a time, from more than one machine and across
sessions that end abruptly. Everything below exists to survive that, not to satisfy
a process.

## Branches

**One branch per coherent change**, cut from `dev`, merged within days. Layers are a
property of the *commit*, not of the branch.

```
<layer>/<type>-<topic>

frontend/feat-manifest-driven-panel
core/refactor-adapter-as-data
backend/fix-latched-manifest-qos
describer/feat-schema-prompt
stack/feat-<topic>                  # genuinely no owning layer
```

layers — `core`, `backend`, `adapters`, `frontend`, `describer`, `sim`, `deploy`, `docs`
types  — `feat`, `fix`, `refactor`, `docs`, `test`, `build`, `chore`

The topic is not optional: `frontend/feat` collides with the next frontend feature.

### The rule that keeps the prefix honest

The layer prefix names the layer whose **behaviour changes for the user**, not every
layer the diff touches. Most real changes here cut vertically through three or four
layers — the rest ride along in the commit scopes:

```
core/refactor-adapter-as-data
  feat(core): adapter descriptors + pure interpreter
  feat(backend): declarative adapter, msg lookup + decoders
  test(core): mapping tested with plain objects
```

The manifest work is the worked example: it touched `core/`, `backend/`,
`describer/`, `frontend/` and `tests/`, but its *purpose* was the operator panel, so
it was one branch, `frontend/feat-manifest-driven-panel`. Split by layer it would
have been four branches in a forced order, three of which cannot be run or reviewed
alone — a manifest nobody reads is dead code.

### Non-negotiable

1. **Never two live branches touching the same layer.** That is the merge conflict.
2. **Rebase on `dev` before merging.** History here is linear; keep it that way.
3. **Push at the end of every session.** An unpushed branch exists on one disk.
   `~/TRAV-metric-map` is the cautionary tale: its long-lived branches reached
   *ahead 10, behind 8* of their remotes, in the repo the robot pulls from.
4. **A branch you cannot name in one `<type>-<topic>` phrase is two branches.**

### Not doing

Long-lived per-layer integration branches (`frontend`, `backend` as permanent lines).
They pay off with one team per layer and a frozen API between them. Here one person
changes an interface and both sides of it in the same hour.

## Commits

Conventional commits, scope optional but preferred: `feat(core):`, `fix(g1):`,
`test(g1-real):`, `docs:`. The body says **why** — what was wrong before, what would
have broken. A message that only restates the diff is noise; `git log -p` already
shows the diff.

## Tests

`python3 -m pytest` must pass before a merge. Everything under `tests/` is pure
Python: no ROS, no sockets, no hardware, no live LLM. A change that can only be
checked on the robot still gets its logic extracted into `core/` and tested there —
that is why `core/` exists.

The GUI has two headless checks that need no display:

```bash
python3 -m pytest
python3 -m skill_monitor.frontend.skill_center --selftest
python3 -m skill_monitor.frontend.skill_center --mock --mock-llm   # on a display
```

## Sessions

Long work is broken into milestones, each ending in a commit. If a session is about
to end mid-task, update `RESUME.md` first: where the code is, what is verified, what
is *not* verified, and what to do next. The next session starts by reading it.
