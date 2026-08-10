# Isaac Lab G1 → Nav2 / monitor sensor bridges

The Isaac Lab G1 (`sim2real_isaac/g1_ros2_bridge.py`) publishes base pose only as a
**TF `odom → pelvis`** and lidar as **`/g1/lidar/points` (`PointCloud2`)**. Nav2 expects
**`/odom`** (`Odometry`) and **`/scan`** (`LaserScan`); the LTL evaluator's
`adapter_isaac_lab.py` (see `../README.md`'s adapter section) expects **`/odom`** too, but
reads `/g1/lidar/points` **directly** — no `/scan` bridge needed for the evaluator's sake
anymore (that used to go through the now-retired `llm_client.py`, which did need `/scan`).
One bridge is still required either way (`/odom`); the second (`/scan`) is now purely for
Nav2's own costmap building.

## 1. `/odom` ← TF (custom, `odom_from_tf.py`) — needed by both Nav2 and the evaluator

```bash
python3 odom_from_tf.py --ros-args -p base_frame:=pelvis -p odom_frame:=odom -p rate_hz:=30.0
```

Republishes the `odom → pelvis` transform as `Odometry`. The pose **orientation** carries the
base roll/pitch the evaluator turns into `upright`/`fell_over` (see `g1_sensors.quat_to_euler`,
used identically by `adapter_isaac_lab.py` via `adapter_nav2_common.py`).

## 2. `/scan` ← PointCloud2 (stock `pointcloud_to_laserscan`) — needed by Nav2 only

Do **not** reinvent this — use the maintained package. Run it for Nav2's costmap regardless;
the evaluator itself no longer needs it (`adapter_isaac_lab.py` calls
`g1_sensors.min_range_from_points` on `/g1/lidar/points` directly, same height-band filter,
unit-tested, no `LaserScan` intermediate).

```bash
ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node --ros-args \
  -r cloud_in:=/g1/lidar/points -r scan:=/scan \
  -p target_frame:=pelvis -p min_height:=0.1 -p max_height:=1.5 \
  -p range_min:=0.2 -p range_max:=15.0 -p angle_increment:=0.0087
```

`min_height`/`max_height` mirror `min_range_from_points`'s `z_lo`/`z_hi` (passed identically
in `adapter_isaac_lab.py`) — tune both to the G1's body band so the floor/ceiling aren't seen
as obstacles.

## Calibration knobs (sim-specific — tune on the live G1)

- Fall: `g1_sensors.base_upright(tilt_max=0.5 rad, height_min=0.5 m)`.
- Collision: `collision_risk` fires at `min_range < 0.25` (`formulas_g1.json`) — set to the G1 footprint.
- Nav2 footprint/inflation in `nav2_params.yaml` must match the humanoid, not the default base.
- **Unverified assumption, flag if wrong:** `adapter_isaac_lab.py` assumes `/g1/lidar/points`
  is already Z-up/body-planar (no axis remap, unlike the real robot's camera-optical-frame
  cloud which needs `g1_real_frame.py`'s remap). If Isaac Lab's actual lidar frame turns out
  to need one too, add it in `adapter_isaac_lab.py`, not in `g1_sensors.py`.
