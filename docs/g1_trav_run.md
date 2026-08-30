# Running the monitor on the real G1, beside TRAV

The order of operations for an experiment day. Everything here is one of: a command to
run, a fact measured on this robot in an earlier session, or a trap someone already fell
into. Nothing is aspirational — where a thing is unbuilt or uncalibrated this says so
and says what to do anyway.

Related: [architecture.md](architecture.md) (what the services are),
[clocking.md](clocking.md) (the tick, and recording an episode),
[api.md](api.md) (the wire contract),
[P12](packages/P12-planner-independent-schema.md) (why this run is a recording first).

## What this run is

**A recording, and a demonstration second.** [P12](packages/P12-planner-independent-schema.md)
is designed and not implemented, so `skill_monitor/adapters/real_g1.json` still declares
a `status` source on `/path_manager/status`, and six of the eight atomic propositions in
`formulas_g1.json` read the planner's self-report. That is the opposite of the standing
constraint — the monitor is meant to be transparent to the navigation algorithm, and
TRAV replacing Nav2 is exactly the thing it should not have noticed.

Implementing P12 first is not a morning's work: it needs P2's tick-steps, three new
extractors, a regenerated spec, and four knobs (`arrival_radius`, the `closing_speed`
epsilon, the `no_progress` `debounce_s`, the `min_range` height band) that P12 itself
says cannot be trusted until a real run has been recorded.

So: **run as-is, record it, calibrate P12 off the recording.** A compromised run that is
written down is the input P12 is blocked on. A perfect run that is not recorded is
nothing.

## Where each piece has to run

**The evaluator on the robot, always.** It is the only service that reads the robot's
sensor topics, and those do not cross the link: the dev PC cannot see the robot's ROS
graph — the route is via a different subnet, DDS discovery is spdp multicast on `eth0`,
and DDS never crossed the wifi even with UDP flowing both ways and unicast peers
configured. `tools/camera_bridge.py` exists because of that wall and carries exactly one
`sensor_msgs/Image` topic over it.

**The monitor can run wherever you like** — see
[*Running the monitor on a second machine*](#running-the-monitor-on-a-second-machine).
The tier-2 monitor advances on the tick inside each received observation, so all it
needs is the observation stream, which is a few hundred bytes of JSON per tick and
travels over ssh.

Whichever machine it runs on, the robot's host and every TRAV container are **Python
3.8** while `skill_monitor` declares `requires-python = ">=3.10"`. The package therefore
runs only inside the images from `deploy/`, which are `ros:humble` and carry 3.10. The
one exception is `tools/g1_preflight.py`, kept 3.8-clean on purpose so it runs in a bare
robot shell.

The console has no authentication and binds loopback wherever it runs. **ssh is what
stands in front of it** — a tunnel when it runs on the robot, nothing needed when it
runs on your own PC.

Steps 0–7 below are the all-on-the-robot layout, which is the shortest path and the one
to fall back to. The two-machine layout changes steps 3 and 4 only, and is written out
at the end.

---

## 0. Before the robot is even on: start the build

The monitor image builds **Spot 2.12.1 from source** (`deploy/Dockerfile.monitor`) —
about ten minutes on a workstation and considerably more on the Jetson's arm64. Nothing
else in the day is as long, and everything else can happen while it runs.

```bash
# on the robot
cd ~/skillMonitor                      # wherever this repo is checked out
docker compose -f deploy/docker-compose.robot.yml build monitor    # the long pole
docker compose -f deploy/docker-compose.robot.yml build            # the rest
```

The evaluator, clock, supervisor and console images do **not** need Spot and build in
the time it takes to pull `ros:humble`.

> If the Spot build is not going to finish in time, the day is still worth running: see
> [*If the monitor image is not ready*](#if-the-monitor-image-is-not-ready) at the
> bottom. Recording does not need the monitor.

## 1. Bring TRAV up as you always do

The monitor changes nothing about it and must not. Its own launch, its own terminal.

Optional but worth having: the CLIP goal matcher publishing `/vision/goal_similarity`
(TRAV branch `ltl-skill-monitor`). It is an **untracked, not-required** source — without
it `visually_at_goal` reads UNKNOWN and every other proposition is unaffected. A run
without it is still a run worth recording.

## 2. Preflight the graph — before the battery, not after

```bash
# in a plain robot shell, with the TRAV stack running
python3 tools/g1_preflight.py --rates
```

It asks the live graph whether every topic `real_g1.json` declares is there, with the
type it declares, and (with `--rates`) whether anything is actually arriving on it. It
adds no subscriber of its own and needs no ROS Python beyond the `ros2` CLI.

- exit **0** — every required source is live. Warnings name the optional ones that are
  not (`/vision/goal_similarity`, `/next_waypoint`, the camera).
- exit **1** — a required source is missing or carries the wrong type. Fix that first;
  the propositions over its keys would read UNKNOWN for the whole run.
- exit **2** — the descriptor could not be read. A typo, not a robot problem.

If **nothing** is visible, it says so and names the two settings that cause it. Check
those before restarting a single healthy node: `ROS_DOMAIN_ID` must match the TRAV
stack's, and the shell must be on the robot.

Pass `--descriptor /config/adapters/real_g1.json` when the run is reading a mounted
config volume rather than the packaged copy — preflighting a file the evaluator is not
reading tells you nothing.

## 3. Start the monitor stack

```bash
docker compose -f deploy/docker-compose.robot.yml \
               -f deploy/docker-compose.experiment.yml up
```

Robot tier — clock (wall, 1 Hz), evaluator (`real_g1`), monitor tier-1, supervisor —
plus the two things a watched experiment needs, which is all the overlay adds:

- the monitor runs **`--passive`**, so a terminal state or a fault leaves it IDLE
  instead of taking both nodes down. Without it the first `VIOLATED` ends the process,
  `restart: unless-stopped` brings it back with no memory, and the induced failure you
  just spent an episode producing is gone.
- the **console** comes up on the robot at `127.0.0.1:8082`.

Knobs, all environment variables: `ROS_DOMAIN_ID`, `TICK_HZ` (default 1.0), `ADAPTER`
(default `real_g1`), `SPEC` (default `formulas_g1.json`), `CONSOLE_PORT` (8082),
`SKILL_MONITOR_CONFIG_HOST`, `SKILL_MONITOR_DATA_HOST`.

With no `/config` volume the images boot on their packaged descriptors and specs and say
which they used, via `config_report()` — read that line rather than assuming. Mount a
config volume only when the robot is carrying a spec this checkout does not have.

## 4. Watch it

```bash
# on the dev PC
ssh -L 8082:127.0.0.1:8082 unitree@<robot>
```

Then `http://127.0.0.1:8082`. Five panels, and one fold that starts shut.

Read these two before trusting anything:

- **panel 4, input** — every source with its age. A source that is stale here makes
  every proposition over it UNKNOWN, and UNKNOWN is not false.
- **panel 7, adapter warnings** (behind the fold) — `min_range` folds `last` where P2's
  spec says `min`. It is a **SAFETY** gap, left deliberately unchanged on a robot that
  could not be tested against, and it is the one thing to check before believing
  `collision_risk`.

## 5. Record the session — one command, one directory

```bash
docker compose -f deploy/docker-compose.robot.yml run --rm recorder \
               session /data/g1_run1 --note "dead end at the far wall, on purpose"
```

Ctrl-C at the end of the episode. That is the whole recording step. It writes **one
self-describing directory**:

```
g1_run1/
  session.json     what ran, against what, when, how it ended, and what is here
  stream.jsonl     /monitor/* -- the monitor's inputs AND its outputs
  sensors/         a rosbag2 of the adapter's sources AND the descriptor's scene
  notes.md         yours, by hand
```

One thing to name, one thing to copy off the robot, one thing that cannot be
half-carried. `session` launches the `ros2 bag record` itself, off the latched
`/monitor/adapter` frame it just received — so the bag's topic list is read from the
robot the run actually used and TRAV's topic names stay hardcoded nowhere.

**It is self-describing on purpose.** `stream.jsonl` carries the latched adapter and
manifest frames: the robot's whole sensor schema, and the skill spec exactly as
authored. A bundle opened in six months on a machine that never had this repo still
knows which robot it came from, which spec was being monitored, and what every sensor
key meant. Nothing has to be looked up beside it — which is the property that makes one
directory a record instead of a pile.

### Before you walk away from the robot

```bash
docker compose -f deploy/docker-compose.robot.yml run --rm recorder verify /data/g1_run1
```

Exit 0 and it is replayable against the monitor *and* re-executable in sim. Exit 1 and
it names each thing the bundle cannot do and why — a missing adapter frame means the
evaluator was not running and the sensor keys are unlabelled; a bag with no scene topics
means the world the episode happened in was not recorded, so it can be checked and never
re-executed. Every one of those is unfixable the moment you leave, and a second run
costs ten minutes now against a return trip later.

### Afterwards, on any machine

```bash
docker compose -f deploy/docker-compose.server.yml run --rm recorder info /data/g1_run1
docker compose -f deploy/docker-compose.server.yml run --rm recorder play /data/g1_run1 --diff
ros2 bag play /data/g1_run1/sensors        # with tools/rviz/run.sh alongside
```

Every subcommand takes the bundle directory, not a file inside it. `play` exits 1 on any
difference, **including `t`** — a `t` that moved means the replay invented a clock, which
is the bug the comparison exists to catch. Stop the clock and the evaluator first: `play`
publishes the recorded ticks itself, counts the publishers it is competing with, and
warns.

### The lower-level pieces are still there

`record`, `topics` and `relay` are what `session` is made of, and the two-machine layout
still uses `record -` for the live stream. Reach for them when you want one half;
`session` when you want the record.

## 6. While the robot is out there, capture the facts P12 is blocked on

These cost nothing today and unblock the next session:

- **the D435i depth topic's real name** (likely `/camera/camera/depth/color/points` —
  confirm, do not assume). `ros2 topic list -t | grep -i depth`.
- **`base_height` on a standing G1.** `fell_over`'s height threshold is uncalibrated and
  the adapter's `upright` step uses `height_min: 0.5`.
- **`min_range` against a metre stick**, at a known distance, to size the height band.
- **the arrival radius that actually reads as arrived**, from the recorded
  `dist_to_goal` at the moment the operator would call it arrived.

Induce the failures through the planner's own terminal states — a dead end gives
`no_path` / `unreachable` / `no_traversable`. `nav_stuck` debounces at 10 consecutive
ticks, so hold the condition rather than clipping it.

## 7. Afterwards

```bash
docker compose -f deploy/docker-compose.robot.yml -f deploy/docker-compose.experiment.yml down
```

The episode is in `/data` on the host (`SKILL_MONITOR_DATA_HOST`, default `../data`),
alongside `output/` — the verdict records and the automaton renders. Get it off the
robot before anything else: it is the only artifact of the day that cannot be
regenerated.

---

## Traps, measured not guessed

| symptom | cause |
|---|---|
| every proposition `INCONCLUSIVE_NO_DATA` | preflight (step 2) was skipped. A topic is named something else. |
| nothing in the graph at all, from a container | `network_mode: host` **and** `ipc: host` are what let DDS discover across containers. Bridged networking makes the nodes silently not see each other. |
| the console reports unhealthy while serving fine | `CONSOLE_PORT` and `--port` disagree; the image's HEALTHCHECK reads the env var. |
| the console will not bind | 8081 is the clock's HTTP API. The overlay puts the console on 8082 for exactly this reason. |
| a second clock appears | something pulled in `docker-compose.server.yml`. Two clocks driving one trace is what `docs/clocking.md` exists to prevent; the experiment overlay adds the console without it. |
| `rmw_create_node` fails, subscriber silently never exists | foxy's CycloneDDS cannot parse `SharedMemory` / `Interfaces` schema elements in the XML config. |
| rviz2 shows an empty scene | the `map → camera_color_optical_frame` static transform. `tools/rviz/run.sh` publishes it first, which is the whole reason that script exists. |
| the monitor exits on the first violation | `--passive` is missing — the experiment overlay is not applied, or `-f` order put it first. `robot.yml` comes first. |

## Recording for a sim replay

There are **two** replay paths, they prove different things, and they need different
recordings. Capture both today; only one of them can be reconstructed afterwards.

| path | what runs | what in the bundle | what it proves |
|---|---|---|---|
| **stream replay** | recorded `/monitor/observation` → monitor | `stream.jsonl` | the verdict is a function of the observation stream alone |
| **re-execution in a simulator** | sim publishes its own topics → evaluator with `mujoco.json` / `isaac_lab.json` → monitor | `sensors/`, **including the scene** | the whole stack is embodiment-independent |

`session` records both halves, which is the point of it being one command. The rest of
this section is what each half is for and what neither can give you.

Same episode through both must reach the same verdict. That equality is the acceptance
test for the agnosticism claim ([P9](packages/P9-docs.md)), and the exclusion count when
it fails is the fidelity report.

### What the scene adds, and why a run without it is not re-executable

The bag's topic list is read off the adapter the run declared. The **sources** alone —
the topics the evaluator subscribes to — are enough to re-drive the evaluator and not
enough to rebuild a world: an observation carries `min_range`, a *scalar*, where an arena
needs geometry. `session` therefore bags the sources **and** what `real_g1.json` declares
under `scene`:

```
/tf  /tf_static  /filtered_map  /traversable_path  /traversable_path_tg
```

The terrain the planner planned on, the paths it produced, and the transforms that place
any of it. Note what these are: `/filtered_map` and `/traversable_path*` are exactly the
topics [P12](packages/P12-planner-independent-schema.md) names as **forbidden inputs** —
the monitor must be transparent to the navigation algorithm and must never read the
planner's own beliefs. Forbidden as an *input* is not the same as not worth recording.
Beside a verdict they are the best explanation of what the planner thought it was doing;
inside the verdict they would be the thing that invalidates it. The descriptor keeps the
two apart and `adapter_spec` refuses a topic that claims to be both.

### The scenario facts a bag cannot give you

A simulator has to be *set up* before it can be re-executed, and three facts define the
setup. Two are already in the `.jsonl` — every observation carries `pos_x`, `pos_y`,
`yaw`, `goal_x`, `goal_y` — and one is not:

- **start pose** — the first observation's `pos_*`/`yaw`. In `stream.jsonl`.
- **the goal sequence** — `goal_x`/`goal_y` as `/next_waypoint` advanced. In `stream.jsonl`.
- **the obstacle layout** — only in `sensors/`, as the cloud and `/filtered_map`. Rebuilding
  `sim/arena.xml` from it is by hand today; `sim/generate_map.py` goes the other way
  (arena → occupancy grid). Photograph the space and pace out the obstacles while you
  are standing in it. That measurement costs two minutes on the day and is unrecoverable
  afterwards.

### Replaying, later

```bash
# 1. the cheap one -- no sim, no robot, any machine. Start the monitor first, with
#    the clock and evaluator DOWN, then:
docker compose -f deploy/docker-compose.server.yml run --rm recorder play \
               /data/g1_run1 --diff             # exits 1 on any difference

# 2. the sensors, as geometry, to see what the run looked like
ros2 bag play /data/g1_run1/sensors        # with tools/rviz/run.sh alongside

# 3. re-execution: build the arena, then run the sim stack with the SAME spec and a
#    different adapter -- which is the whole claim
docker compose -f sim/docker-compose.sim.yml up --build
```

For (3) the evaluator's `--adapter` changes from `real_g1` to `mujoco` and
`formulas_g1.json` does not change at all. If the verdict differs, the difference is the
finding — and `docs/architecture.md` lists the three things that break agnosticism to
check against first, one of which (`nav_stuck` debouncing in messages rather than ticks)
is known-broken until P2 lands and makes sim and real verdicts **not yet comparable**.
Record now regardless: the recording is what makes the comparison possible the day it is.

### If you are running the two-machine layout

**Run `session` on the robot regardless.** The sensor and scene topics never cross the
link — only `/monitor/*` does — so the bundle has to be written where they are, and the
relay is for *watching*, not for recording. Two commands on the robot, then: `session`
for the record, and `record -` into the ssh pipe for the live view.

That does mean two recorders subscribed to `/monitor/*` at once, which is fine: they are
subscribers, they change nothing, and the bundle on the robot is the authoritative copy.
If you would rather have the record on the PC, `tee` the pipe (below) — but that file is
`stream.jsonl` only, with no sensors and no scene, so `verify` on it will correctly tell
you it cannot be re-executed.

## Running the monitor on a second machine

Only the **evaluator** has to be on the robot. Put the monitor, the gateway and the
console on your own PC and you get a browser page with no tunnel, the Spot build on a
machine that is not a Jetson, and `/data` on a disk you can actually work from.

What has to cross the link is the observation stream — `/monitor/tick`,
`/monitor/observation` and the latched `/monitor/adapter`, a few hundred bytes of JSON
per tick. **Not** the sensor topics, which stay on the robot with the evaluator.

**Do not try to do this with DDS.** It was tried on this robot and it did not work: UDP
flowed both ways, unicast peers were configured, and the graphs never saw each other.
ssh is the transport that does work, and it authenticates and encrypts a control surface
that has no authentication of its own.

### On the robot — sensors and the evaluator, nothing else

```bash
docker compose -f deploy/docker-compose.robot.yml up clock evaluator
```

No monitor tier-1 and no supervisor: with the verdict being computed on the PC, a
tier-1 monitor here would be a second, independent verdict on the same episode. Add them
back only when you want the safety ladder on the robot, and then know you have two.

### The link — one pipe, both ends `-T`

```bash
# on the PC, in one terminal, and leave it running
ssh unitree@<robot> 'docker compose -f ~/skillMonitor/deploy/docker-compose.robot.yml \
                     run --rm -T recorder record -' \
  | docker compose -f deploy/docker-compose.server.yml run --rm -T relay
```

`record -` writes the frames to stdout instead of a file; `relay` reads them on stdin and
publishes the inputs onto the PC's graph. `-T` on **both** ends: without it compose
allocates a TTY and a TTY mangles the stream.

`relay` publishes the inputs only. The robot's verdicts and manifest are dropped —
your monitor is computing its own, and two producers on `/monitor/verdict` would leave
the console showing whichever landed last with nothing saying which.

### On the PC — the monitor, the gateway, the console

```bash
docker compose -f deploy/docker-compose.server.yml up --no-deps monitor gateway frontend
```

Then `http://127.0.0.1:8082`. No tunnel: it is your own machine.

**`--no-deps` is the load-bearing flag.** `monitor` declares `depends_on: [clock]`, so
without it compose starts the server's clock as well. That clock ships `--paused` and
emits no ticks, but it still *creates* a publisher on `/monitor/tick` — which is enough
to make the relay's "another publisher" warning fire on every run, and a warning that
cries wolf is a warning nobody reads on the day it is right. The tick belongs to the
robot and arrives inside the stream; nothing here should be able to produce one.

With no local clock, the gateway's clock proxy (`--clock-url`, default
`http://127.0.0.1:8081`) has nothing to reach and the console's clock *controls* are
inert. The tick itself still shows: it comes off `/monitor/tick`, which the relay is
publishing.

### To also keep the episode

The relay carries the stream; it does not write it down. For a recording on the PC as
well, tee the pipe:

```bash
ssh unitree@<robot> '... record -' \
  | tee ~/episodes/g1_run1.jsonl \
  | docker compose -f deploy/docker-compose.server.yml run --rm -T relay
```

That file is the same format `play --diff` reads, so an episode watched live is an
episode you can replay afterwards. It holds the robot's own verdicts — which, if the
tier-1 monitor was running there, is what makes a two-tier comparison possible.

### What this costs you

| | |
|---|---|
| **the link is a single point of failure** | wifi drops and the stream stops. The monitor's last observation goes stale and every proposition reads UNKNOWN — correct behaviour, and not the same as "nothing is wrong". Watch panel 4. |
| **one torn frame per drop** | a truncated line is counted and skipped, and the stream carries on. The count is printed when the relay exits. |
| **no interventions** | the supervisor is robot-tier only, deliberately: an intervention decided across a wifi link is an intervention that arrives late. A verdict computed on the PC can inform a human, not stop a robot. |
| **the pipe is a view, not a record** | `session` on the robot is the record. Stopping the pipe stops the watching and nothing else. |

## If the monitor image is not ready

The Spot build not finishing does **not** cost the day. The evaluator image has no Spot
in it, so the graph and the recording still happen:

```bash
docker compose -f deploy/docker-compose.robot.yml up clock evaluator
docker compose -f deploy/docker-compose.robot.yml run --rm recorder session /data/g1_run1 \
               --note "no monitor -- Spot build unfinished"
```

That is a complete `/monitor/observation` stream plus the sensors and the scene. `verify`
will report the one thing missing — no verdicts, because no monitor ran — which is
exactly right: replay it into the monitor on the dev PC afterwards and the verdicts are
produced there, which is the server tier's whole purpose. The bundle is complete for
every other use, P12's calibration included.
