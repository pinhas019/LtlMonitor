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

## 5. Record the episode

Two recordings, and they are not alternatives. In this order, in two more terminals.

```bash
# terminal A -- the monitor's own stream, what a replay needs. Foreground, and
# Ctrl-C at the end of the episode: that is what closes the file cleanly and
# prints the frames-written count.
docker compose -f deploy/docker-compose.robot.yml \
               run --rm recorder record /data/g1_run1.jsonl
```

```bash
# terminal B -- the sensor topics, what rviz2, Isaac and P12's calibration need.
# The topic list is generated off the adapter THE RUN DECLARED, not hardcoded, so
# terminal A must already be running: `topics` reads the recording's own
# /monitor/adapter frame and says so rather than guessing if it is not there yet.
# The frame is latched, so it lands within a second of the recorder starting.
ros2 bag record -o g1_run1.bag $(docker compose -f deploy/docker-compose.robot.yml \
                                run --rm recorder topics /data/g1_run1.jsonl)
```

The first records `/monitor/*` — the inputs to replay and the outputs to compare, per
the one rule that makes a replay meaningful: **replay the monitor's inputs, compare its
outputs.** The second records the geometry, which is not on `/monitor/*` at all.

Afterwards, on any machine:

```bash
docker compose -f deploy/docker-compose.robot.yml run --rm recorder info /data/g1_run1.jsonl
docker compose -f deploy/docker-compose.robot.yml run --rm recorder play /data/g1_run1.jsonl --diff
```

`play` exits 1 on any difference, **including `t`** — a `t` that moved means the replay
invented a clock, which is the bug the comparison exists to catch. Stop the clock and
the evaluator before replaying: `play` publishes the recorded ticks itself, counts the
publishers it is competing with, and warns.

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
| **the recorder is the sender** | stop the pipe and you stop the recording. Ctrl-C ends both ends. |

## If the monitor image is not ready

The Spot build not finishing does **not** cost the day. The evaluator image has no Spot
in it, so the graph and the recording still happen:

```bash
docker compose -f deploy/docker-compose.robot.yml up clock evaluator
docker compose -f deploy/docker-compose.robot.yml run --rm recorder record /data/g1_run1.jsonl
ros2 bag record -o g1_run1.bag $(docker compose -f deploy/docker-compose.robot.yml \
                                run --rm recorder topics /data/g1_run1.jsonl)
```

That is a complete `/monitor/observation` stream plus the raw sensors. Replay it into
the monitor on the dev PC afterwards — which is the server tier's whole purpose, and the
verdict of record is meant to be produced there anyway.
