# Resume

**Newest session first.** Sessions 1–4 below are kept for the decisions they record,
not for their status lines — every "unpushed", test count, `/ltl/*` topic name and git
rule in them is out of date. **Session 5 is the current state.** The one part of
session 4 that is not superseded is its closing section on the G1 run; that is still
the plan.

---

# Session 5 — the suite got a machine of its own, and the git rules got teeth (2026-08-27)

Everything is pushed. `git clone https://github.com/pinhas019/LtlMonitor.git` is still
the whole handoff; nothing that matters lives on one disk.

```
origin  https://github.com/pinhas019/LtlMonitor.git
dev     72d7b4f       ← PRs #34 #35 #36 #37 #38 #39 all landed here today. This entry
                        was corrected twice after that SHA was written, so dev is a few
                        commits past it by the time you read this. `git log --oneline`
                        is the only current answer; treat the SHA as "roughly here"
main    a50ae2d       ← PROMOTED today, PR #40, sixteen commits, merged with the merge
                        commit button. `git rev-list main..dev` was empty immediately
                        after, which is how you know the right button was pressed
branch  none outstanding. `git ls-remote --heads origin` is dev and main

docker compose -f deploy/docker-compose.test.yml run --rm tests
      → 1231 passed, 0 skipped,  79 s   ← this is the contract
python -m pytest                (this host, no PYTHONUTF8)
      → 1227 passed, 4 skipped, 347 s   ← the fast path, and green here too now. The
                                          four skips are not the four old failures
```

## First thing to do

**Nothing about the toolchain. Go and run the robot.** `main` is promoted and both ways
of running the suite are green. Everything this session built was in service of the G1
navigation experiment at the bottom of this entry, and nothing stands in front of it any
more. Session 4's *Tomorrow: the G1 navigation experiment* is where the runnable commands
and the robot-side gotchas are; the short version is *run as-is, record it, calibrate P12
off the recording*.

If you are picking this up on a new machine, the whole setup is: install Docker, clone,
and run the compose line above. There is no third step.

## The dev loop is in a container, and that is the contract

`1da681e` (PR #35) added `deploy/Dockerfile.test`, `deploy/docker-compose.test.yml`,
`.dockerignore` and `.github/workflows/tests.yml`. The one line that decides whether a
branch is mergeable:

```bash
docker compose -f deploy/docker-compose.test.yml run --rm tests
docker compose -f deploy/docker-compose.test.yml run --rm tests -m pytest -q tests/test_api.py
docker compose -f deploy/docker-compose.test.yml up console      # http://127.0.0.1:8799
```

`.github/workflows/tests.yml` runs that identical command on every push and every pull
request, as the job `suite`. Nothing in it is a re-spelling — a CI command that differs
from the local one is a third environment, and having two is what caused this.

The image is `python:3.10-slim` plus `nodejs` plus `pytest`, and it contains **no `COPY`
of the source**. That is deliberate and it is the one place `deploy/` contradicts itself:
a deployed image *is* a version, so it copies; the test image runs the **working tree**,
which is not a version yet, so the repo arrives on a bind mount — `..:/app`, with
`PYTHONPATH=/app` because there is nothing to `pip install -e` at build time. The
consequence, stated so nobody "fixes" it: the image is not runnable on its own. Without
the mount `/app` is empty and pytest collects nothing.

Three things worth not rediscovering:

- **The container is more than four times faster than this Windows host, not slower.**
  79 s against 347 s, both measured on this machine against `3e09872`. That is the
  opposite of the bind-mount penalty everyone expects, so there is no performance
  argument left for running the suite on the host. Run it in the box.
- **`node` is in the image, so the page-syntax guard executed for the first time in this
  project's history.** `skill_monitor/frontend/web.py:page_syntax_problems()` shells to
  `node --check` and *returns* a problem string when node is missing rather than raising,
  so the three tests in `tests/test_web_ui.py` that use it (`test_the_page_parses`,
  `test_a_page_that_does_not_parse_is_reported_with_its_own_name`,
  `test_check_exits_non_zero_without_binding_anything`) called `pytest.skip` on every
  machine this project has ever run on. They now run, and `index.html` parses.
- **Zero skipped is the new normal, and the gap between 0 and 4 is the whole argument
  for the container.** Both runs are green now, so the only thing separating them is
  what each one declines to run. The host skips exactly four, and **they are not the
  four tests that used to fail** — those were encoding failures and they are fixed. The
  four skips are the three page-syntax tests above, plus
  `test_a_symlink_out_of_the_directory_is_not_a_way_in`, which needs a filesystem that
  can make symlinks and gives up quietly on Windows. That last one is a path-traversal
  check on the gateway's static file server: a *security* test that has never once
  executed on this laptop. In the container all 1231 run. A skip appearing in the
  container's summary is an environment regression, not noise.

## This machine

Windows 11 Pro, **Python 3.13.12**, and `locale.getpreferredencoding(False)` resolves
to **cp1255** — the Hebrew ANSI codepage. Check it rather than assume it, because it is
the fact everything else in this section hangs off:

```bash
python -c "import locale; print(locale.getpreferredencoding(False))"
```

**What that does, because it is the transferable part.** A `Path.read_text()` or an
`open()` with no `encoding=` does not read UTF-8. It reads whatever that call returns on
the machine the process started on — UTF-8 in the Linux container, cp1255 here. The same
bytes on disk decode to two different strings depending on where you ran, and nothing in
the source says so. Here it showed up as `UnicodeDecodeError: 'charmap' codec can't
decode byte 0x9a` on the em-dashes in `docs/api.md`, and four tests in
`tests/test_api.py` were red on a tree that was green on Linux.

**That is fixed** — `3e09872` (PR #38), 41 call sites given an explicit
`encoding="utf-8"`. The site that mattered was not any of the failing tests: it was
`skill_monitor/backend/replay_node.py:98`, which opened the **episode recording** for
writing with the platform default. P9 makes verdict equality between two replays of one
episode the acceptance test for the whole hardware-agnosticism claim, so a run recorded
on this laptop and replayed on the robot would have decoded as something else. The
comparison meant to prove the monitor does not depend on the machine was deciding its
answer from the machine. The red tests were the symptom that exposed it; this was never
"Windows support".

`tests/test_portability.py` keeps it fixed: an AST walk over every `.py` under
`skill_monitor/`, `tests/`, `tools/` and `sim/` that fails on a text-mode read or write
with no encoding, so the next one fails for whoever writes it. It carries its own
`test_the_scan_can_tell_the_cases_apart`, which runs the matcher over a 19-line probe
and asserts the exact offending line numbers — without that, a scanner that silently
stopped matching would pass forever, which is how a guard like this dies. Two things it
does not cover, stated in PR #38 rather than hidden: `codecs.open` / `gzip.open` /
`tarfile.open` are unhandled, because the repo imports none of them; `NOT_A_FILE_OPEN`
and the mode logic are where to extend it.

**Do not put `PYTHONUTF8=1` in your environment.** It makes an unencoded read work, so
it would have hidden all of the above, and this host is the only one the project has
that can surface the class of bug at all — the container is UTF-8 by default and could
never have demonstrated the fix. The AST guard catches new sites either way; the point
is not to lose the runtime signal too.

`skill_monitor` imports straight off the repo root here — `python -m pytest` from the
checkout puts the cwd on `sys.path`, and the container sets `PYTHONPATH=/app`. **The
`.pth`-in-user-site-packages instruction in sessions 3 and 4 is Linux-only and is not
needed on this machine**; there is no `skill-monitor.pth` here and nothing wants one.

Docker Desktop 4.88.1, engine 29.7.2, Compose v5.4.0, on the WSL2 backend, already
configured before this session.

**The robot, server and sim stacks do not run on Docker Desktop for Windows, and that is
correct rather than a gap.** `deploy/docker-compose.robot.yml`,
`deploy/docker-compose.server.yml` and `sim/docker-compose.sim.yml` all use
`network_mode: host` + `ipc: host`, because their services have to share one DDS domain
and one loopback. On Docker Desktop the daemon runs inside a WSL2 VM, so "host" is the
VM and not the laptop. Those stacks stay Linux/robot-tier. `docker-compose.test.yml` is
deliberately the exception — default bridge network, `127.0.0.1:8799:8080` published —
so that the one stack a developer needs everywhere works everywhere.

## Git rules — and two of the documented ones were not true

`dev` and `main` are **protected branches** now, so rule 1 is enforced rather than
remembered. Measured, not assumed — `gh api repos/pinhas019/LtlMonitor/branches/dev/protection`:

| | `dev` | `main` |
|---|---|---|
| pull request required | yes, **0 approvals** | yes, **0 approvals** |
| required status check | `suite` | `suite` |
| branch must be up to date (`strict`) | yes | yes |
| linear history required | **yes** | **no** |
| force push / deletion | refused | refused |
| applies to admins (`enforce_admins`) | yes | yes |

Zero required approvals is what keeps a one-person repo workable: the PR is mandatory,
the green `suite` is mandatory, and the same person can then press the button. The
`required_linear_history` row is the interesting one and it is not an oversight — see
promotion below.

Two rules `CONTRIBUTING.md` stated were **not literally true**. Both are corrected there
in `82fd267` (PR #36); session 4's copy of them is superseded.

**"The merge is fast-forward" was never literally true.** GitHub has no fast-forward
merge button. What this repo has always actually done is a **rebase** merge, which
replays the commits onto the tip — linear, which is what "fast-forward" meant in
practice, but every commit gets a new SHA. The evidence is on `dev` right now:
`frontend/feat-wall-content` (PR #29) went in as `2a82921` and sits on `dev` as
`fc33c5e` — same subject, same author date `Tue Aug 25 11:29:36 2026 +0300`, different
hash.

That has a consequence that will waste your time if you do not know it:

```bash
git merge-base --is-ancestor 2a82921 origin/dev   # exit 1 — "not merged", and it is wrong
git cherry -v origin/dev 2a82921                  # "- 2a82921 …" — the leading - means merged
```

**Use `git cherry origin/dev origin/<branch>` to ask whether a branch is merged.** `-`
means the patch is already upstream under another hash; `+` means it genuinely is not.

**`git push origin dev:main` is refused now**, so promotion is a pull request from `dev`
into `main` — and it must be merged with a **merge commit**, which is a deliberate
exception to the rebase rule. Rebase-merging a promotion would rewrite every commit under
a new hash, leaving `main` holding duplicates of commits that still exist on `dev` under
different SHAs, and the two branches would diverge permanently from that release onward.
A merge commit keeps `dev`'s commits as literal ancestors, which is what makes
`git log main..dev` mean "not yet released" rather than "renamed". So `main` alone permits
merge commits — that is exactly why `required_linear_history` is off on `main` and on for
`dev`. Session 4's "dev fast-forwards to main" is wrong twice over.

**A trap that was found and closed today, worth knowing existed.** The protection above
was set before anyone checked the repo's merge-button settings, which were
`allow_merge_commit: false`, `allow_rebase_merge: true`. So the rule said promotion must
be a merge commit while the only button GitHub would offer on that PR was *Rebase and
merge* — the one thing that must never happen. `allow_merge_commit` is **on** now, and
`dev`'s `required_linear_history` still refuses merge commits there, so enabling it
repo-wide did not loosen `dev`. Confirm before promoting rather than trusting this line:

```bash
gh api repos/pinhas019/LtlMonitor --jq '{allow_merge_commit,allow_rebase_merge,allow_squash_merge}'
```

Then merge the promotion with `gh pr merge --merge --delete-branch=false`, and check
afterwards that `git rev-list main..dev` is empty — if it is not, the wrong button was
pressed and `main` now carries duplicates.

This ran once, on PR #40, and the procedure holds: `main` is `a50ae2d`, a merge commit
whose second parent is `72d7b4f`, `git rev-list main..dev` returns nothing, `dev` still
exists and the default branch is still `dev`. Those last two are checked on purpose, for
the reason the parenthetical below gives. (`delete_branch_on_merge` is still off,
deliberately: it once deleted `dev` when a `dev → main` PR auto-closed, and GitHub
flipped the default branch to `main`.)

## Housekeeping already done, so nobody repeats it

- The stale console branches left over from the wall work — `frontend/feat-wall-content`
  (PR #29) among them — are **deleted**, each confirmed merged with `git cherry` first,
  because `git merge-base` says they are not, for the reason above.
  `git ls-remote --heads origin` now returns `dev` and `main` and nothing else. Do not go
  looking for a branch behind an already-merged panel commit; there isn't one.
- `stack/fix-explicit-encoding` **merged** as `3e09872` (PR #38) — described under
  *This machine*. Two sites the original survey of 39 missed are worth knowing about,
  because both say something about where this repo's blind spots are: **`sim/` was never
  counted at all** (`sim/generate_map.py:10,58`, `sim/mujoco_ros_bridge.py:27` — while
  `generate_map.py:86` writes a `.pgm` with `"wb"` and is correctly left alone), and
  **`tests/test_api.py:987`, the `_topic_literals` scanner itself**, which was reading
  the whole codebase through the host codepage. That is why two of the four baseline
  failures were scanner tests rather than doc tests.
- `tools/console_snapshot.py` **did not run on Windows at all** — a
  `__file__.rsplit("/", 2)` path split that finds no `/` in a backslash path, `open()`s
  with no `encoding=` on a cp1255 host, and a module-scope import of the gateway that
  killed the fully-offline `build` subcommand from any checkout not already on
  `sys.path`. Fixed in `ea6810f`. Session 4 tells the next session to run exactly that
  command; it works now, `build` included, verified end to end on this host.

## Still the next real work: the G1 navigation experiment

**Unchanged. Session 4 is directly below and its plan stands — read it, do not restate
it here.** In one line: [P12](docs/packages/P12-planner-independent-schema.md) is designed
and not implemented, `skill_monitor/adapters/real_g1.json` still declares a `status`
source on `/path_manager/status` (line 136), and in
`skill_monitor/specs/formulas_g1.json` **five** of the eight atomic propositions —
`mission_started`, `path_active`, `moving_towards_target`, `nav_stuck`,
`mission_finished` — read the planner's self-report, plus the phase `exit_condition`s
built on them. Only `collision_risk`, `upright` and `visually_at_goal` are independent of
it. (Session 4 says "six of eight"; it was counting the exit conditions as a proposition.
The gap is the same size either way.) Four knobs remain uncalibrated.

The answer is still session 4's: **run as-is, record it with `replay_node record`,
calibrate P12 off the recording.** Nothing here changed that. What this session changed is
everything around it: the environment the recording gets analysed in is reproducible, the
tool that shows somebody the result runs on this laptop, and — the one that would have
bitten tomorrow — `replay_node` now writes the recording as UTF-8 instead of as whatever
the recording host's codepage happened to be, so a run captured on the robot and read back
here is the same episode.

---

# Session 4 — replay, and the console cut to five panels (2026-08-25)

Everything is pushed. `git clone git@github.com:pinhas019/LtlMonitor.git` is the whole
handoff; nothing that matters lives on one disk.

```
origin  git@github.com:pinhas019/LtlMonitor.git
dev     cd23f4b       ← PR #33 merged here
main    fa9796a       ← NOT promoted. dev is 3 commits ahead
branch  frontend/fix-five-panels   f4c4661   ← PR #34 OPEN against dev
        python3 -m pytest  →  1228 passed, ~115 s
        python3 -m skill_monitor.frontend.web --check   (needs node; parses the page)
```

Fresh machine: Python 3.10 and `pytest`, nothing else. `rclpy` and `spot` are **not**
installed and are not needed — `tests/ros_stub.py` fakes the ROS layer, so everything in
`skill_monitor/backend/` is *unrun* code on a dev host. Say so in commits rather than
implying it was tested. `pip install -e .` fails (setuptools predates PEP 660); the
package is on `sys.path` via a `.pth` in user site-packages.

## First thing to do

**Merge or close PR #34**, then decide about `main`. `main` has not been promoted since
session 3; `dev` carries replay and the console work. Promotion is a fast-forward push,
never a local merge — see *Git rules* below.

## What landed

**Replay** — `skill_monitor/core/recording.py` and `skill_monitor/backend/replay_node.py`,
with 23 pure tests in `tests/test_recording.py`. P9 names verdict equality between two
replays of one episode as *the* acceptance test for the agnosticism claim, and nothing
recorded the episode. The rule is one line and it is a constant, not a judgement:

> **Replay the monitor's inputs (`INPUTS`). Compare its outputs (`OUTPUTS`).**

```bash
python3 -m skill_monitor.backend.replay_node record run.jsonl        # while it runs
python3 -m skill_monitor.backend.replay_node play   run.jsonl --diff # exits 1 on a diff
python3 -m skill_monitor.backend.replay_node info   run.jsonl
ros2 bag record -o run.bag $(python3 -m skill_monitor.backend.replay_node topics run.jsonl)
```

Four things about it worth not rediscovering: **no clock runs during a replay** (the
player publishes the recorded ticks, which is what keeps the tick count independent of
replay speed — so the clock *and* the evaluator must be stopped, and `play` counts the
publishers it is competing with and warns); **nothing is ignored in a diff by default,
including `t`** (a `t` that moved means the replay invented a clock, which is the bug the
comparison exists to catch); **a missing verdict is not a differing verdict**; and
`topics` reads the sensor list off the adapter *the run declared*, so the bag line is
generated per robot and TRAV's topics are hardcoded nowhere.

Docs: [docs/clocking.md](docs/clocking.md#recording-an-episode-and-replaying-it).

**The console is five panels**, after three rounds of the operator saying it was noisy,
then "super bad". Panels 1–2 are the band (automaton, verdict), 3–5 the grid under it
(propositions, input, clock). Everything else — the **phase machine included** — is
behind one fold that starts shut.

| | panel | |
|---|---|---|
| 1 | automaton | the spec as a machine, current state lit |
| 2 | verdict | and why |
| 3 | propositions | rule → keys → value |
| 4 | input | per source, with age |
| 5 | clock | the tick (+ a shut `replay` line) |
| 6–12 | behind the fold | phases · warnings · config · schema · spec · plots · timing |

Rules that are now pinned by tests, so do not undo them casually:

- **One numbering, three places.** The badge on screen, `/* == 3 · atomic propositions */`
  in `index.html`, and `**3 —**` in `docs/packages/P7-frontend.md`. Renumber all three or
  the suite fails. This caught two panels I would have missed.
- **Three or four words of subtitle, the sentence on `title`.** Capped at eight words per
  panel. A long-form line on every panel measured 181 words on a 1349-word page.
- **No fact appears twice.** The header used to repeat verdict/intervention/phase/step
  from panel 2; it carries `skill` and `tick` only.
- Panels 1 and 2 are `<section class="pane">` with an `<h2>`, styled by the same rule as
  a pane's `<summary>`, so the band cannot drift back into unboxed text.

## Traps, measured not guessed

- **The preview tool's screenshot times out on this page** — five attempts, every one.
  Audit the layout through the DOM instead: walk sibling `getBoundingClientRect()`s and
  assert no pair intersects. That is what found the real defects (`✖ VIOLATED` at 51px
  needing 258px of a 213px column and running out over the cell beside it).
- **`grid-row: 1 / span 99` makes the grid HAVE 99 rows.** 98 empty ones at a 4px gap
  added 392px of nothing to every cell. Mine, same session.
- **`pkill -f "port 8799"` kills your own shell** (exit 144) — the pattern matches the
  shell's own command line. Kill by PID.
- `getBBox()` on SVG text inside a `<g transform>` is *local*; `getBoundingClientRect()`
  is absolute. Collision-checking with the first gives false positives on every node.

## Showing somebody the console

```bash
python3 -m skill_monitor.frontend.web --mock --port 8799        # http://127.0.0.1:8799
python3 tools/console_snapshot.py capture http://127.0.0.1:8799 run.json 45
python3 tools/console_snapshot.py build   run.json console.html   # one self-contained file
```

`tools/console_snapshot.py` records what the *page* was shown and replays it in the
browser with no server. It is **not** `replay_node.py`, which records ROS topics and
re-runs the *monitor* — one is a moving screenshot, the other a correctness check.

## Tomorrow: the G1 navigation experiment

**The blocker, stated plainly: [P12](docs/packages/P12-planner-independent-schema.md) is
designed and not implemented.** `skill_monitor/adapters/real_g1.json` still declares a
`status` source on `/path_manager/status`, and six of the eight atomic propositions in
`skill_monitor/specs/formulas_g1.json` (`mission_started`, `path_active`,
`moving_towards_target`, `nav_stuck`, `mission_finished`, and the phase `exit_condition`s
built on them) read the planner's self-report. That is the opposite of the standing
constraint — the monitor is meant to be transparent to the navigation algorithm.

Implementing P12 first is not a morning's work: it needs P2's tick-steps, three new
extractors, a regenerated spec, and **four uncalibrated knobs** (`arrival_radius`,
`closing_speed` epsilon, `no_progress` `debounce_s`, the `min_range` height band) that
P12 itself says need a recorded run before they can be trusted.

So the order is: **run tomorrow as-is, record it, and calibrate P12 off the recording.**
That is exactly what the recorder was built for, and it turns a compromised run into the
input P12 is blocked on.

```bash
# on the robot, alongside perception + the bridge
python3 -m skill_monitor.backend.replay_node record g1_run1.jsonl
ros2 bag record -o g1_run1.bag $(python3 -m skill_monitor.backend.replay_node topics g1_run1.jsonl)
```

Known robot-side facts from session 3, still true:

- **foxy's CycloneDDS cannot parse `SharedMemory` / `Interfaces`** schema elements — the
  symptom is `rmw_create_node` failing and a subscriber that silently never exists.
- **Wifi DDS never worked** despite UDP flowing both ways and unicast peers; the fallback
  is the TCP camera bridge in `tools/camera_bridge.py`.
- `min_range` folds `last` where P2's spec says `min` — a **SAFETY** gap, visible in the
  adapter-warnings pane (panel 7), deliberately unchanged on a robot that could not be
  tested against. Check this before trusting `collision_risk`.
- TRAV-side: `monitor_logger.py`'s `--config` remap is dead code (flat YAML read against
  a `path_manager:`-nested file), so `/trav/cmd_vel` is never recorded, and
  `/filtered_map` is hardcoded.
- `tools/rviz/run.sh` publishes the `map → camera_color_optical_frame` static transform
  first. Without it rviz2 shows an empty scene rather than naming the missing frame.

## Git rules (the operator's, and they have bitten before)

- **Merges happen only through a pull request**, then fast-forward. Never `git merge`
  locally.
- **Always `git pull --rebase`.**
- Feature branch → PR into `dev` → `dev` fast-forwards to `main`.
- `delete_branch_on_merge` is **off** on the repo: it once deleted `dev` when a
  `dev → main` PR auto-closed, and GitHub flipped the default branch to `main`. Pass
  `--delete-branch` per merge instead.

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
