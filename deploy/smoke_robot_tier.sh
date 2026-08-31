#!/usr/bin/env bash
# Bring the robot tier up, drive it, and refuse to pass unless the observation MOVED.
#
#   deploy/smoke_robot_tier.sh                      # mujoco, on this machine
#   ADAPTER=real_g1 DDS_INTERFACE=wlan0 deploy/smoke_robot_tier.sh
#   COMPOSE="sudo docker-compose" deploy/smoke_robot_tier.sh
#
# Runs where the robot tier runs -- on the robot -- so it takes no address of any kind.
# The dev PC drives it over ssh; that is the operator's business, not this script's.
#
# WHY THE CRITERION IS "MOVED" AND NOT "PUBLISHED". Until P3 landed, nothing called
# SensorState.tick(), and since tick() is the sole writer of the held values,
# sensor_eval() returned the schema defaults for the life of the process -- a full,
# plausible, entirely constant dict. Every liveness check you would naturally write
# (the topic exists, the payload validates, seq advances) passes against that. So the
# assertion here is that a sensor value CHANGED between two ticks while the stimulus
# was driving it, which is the one thing the broken state could not fake.
#
# The check reads the RECORDING rather than the live topic, so a pass also proves the
# recorder wrote a replayable episode -- which is the whole reason the robot tier
# carries one.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

COMPOSE="${COMPOSE:-docker compose}"
STACK="deploy/docker-compose.robot.yml"
ADAPTER="${ADAPTER:-mujoco}"
SECONDS_RUNNING="${SECONDS_RUNNING:-25}"
RUN="${RUN:-smoke}"
DATA_HOST="${SKILL_MONITOR_DATA_HOST:-$PWD/data}"
RECORD="$DATA_HOST/${RUN}.jsonl"

export ADAPTER RUN

mkdir -p "$DATA_HOST"
# A previous smoke run's episode would satisfy every assertion below without this
# process ever having worked. The recorder appends on purpose; the smoke test is the
# one caller that must not inherit.
rm -f "$RECORD"

cleanup() { $COMPOSE -f "$STACK" down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "[smoke] adapter=$ADAPTER interface=${DDS_INTERFACE:-eth0} rmw=${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
$COMPOSE -f "$STACK" up -d clock evaluator recorder

echo "[smoke] driving for ${SECONDS_RUNNING}s"
# In the evaluator image, on the same graph: it already has rclpy, the message types
# and the DDS settings, so the stimulus cannot accidentally be testing a different
# transport from the thing it is stimulating.
#
# Mounted, not COPYed: the images take in skill_monitor/ and nothing else, which is
# correct -- a test fixture baked into the deployed image is a test fixture that ships
# to the robot. The mount is what keeps deploy/ out of the artifact.
$COMPOSE -f "$STACK" run --rm --no-deps -v "$PWD/deploy:/smoke:ro" \
    --entrypoint /bin/bash evaluator -c \
    "source /opt/ros/humble/setup.bash && python3 /smoke/smoke_stimulus.py \
     --adapter '$ADAPTER' --seconds '$SECONDS_RUNNING'"

# Let the last tick land before the recorder is torn down by the trap.
$COMPOSE -f "$STACK" stop recorder >/dev/null 2>&1 || true

echo "[smoke] checking $RECORD"
RECORD="$RECORD" ADAPTER="$ADAPTER" python3 - <<'PY'
import json, os, sys

path, adapter = os.environ["RECORD"], os.environ["ADAPTER"]
KEY = {"mujoco": "pos_x", "isaac_lab": "pos_x", "real_g1": "pos_x"}[adapter]

if not os.path.exists(path):
    sys.exit(f"FAIL: no recording at {path} -- did the recorder start?")

obs, ticks = [], 0
with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        frame = json.loads(line)
        if frame["topic"] == "/monitor/observation":
            obs.append(frame["payload"])
        elif frame["topic"] == "/monitor/tick":
            ticks += 1

print(f"  ticks recorded        : {ticks}")
print(f"  observations recorded : {len(obs)}")
if ticks == 0:
    sys.exit("FAIL: no ticks recorded -- the clock is not publishing")
if len(obs) < 2:
    sys.exit("FAIL: fewer than two observations; nothing to compare. The evaluator "
             "publishes only while armed -- did /ltl/required_aps arrive?")

seqs = [o["seq"] for o in obs]
if len(set(seqs)) < 2 or seqs != sorted(seqs):
    sys.exit(f"FAIL: seq did not advance monotonically: {seqs[:8]}")

values = [o["sensors"].get(KEY) for o in obs]
distinct = {v for v in values if v is not None}
print(f"  {KEY:<21} : {values[0]} -> {values[-1]}  ({len(distinct)} distinct)")
if len(distinct) < 2:
    sys.exit(f"FAIL: {KEY} never changed across {len(obs)} observations. This is the "
             f"pre-P3 signature exactly: the window is not being closed, so "
             f"sensor_eval() is returning schema defaults.")

health = obs[-1].get("data_health") or {}
refreshed = [s for s, e in health.items() if e.get("refreshed")]
print(f"  sources refreshed     : {refreshed or 'NONE'}")
if not refreshed:
    sys.exit("FAIL: no source reported refreshed; data_health says nothing arrived")

print("PASS: the observation advanced and the episode is on disk")
PY
