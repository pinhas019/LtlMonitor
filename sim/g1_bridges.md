# Isaac Lab G1 → Nav2 / monitor sensor bridges

The Isaac Lab G1 (`sim2real_isaac/g1_ros2_bridge.py`) publishes base pose only as a
**TF `odom → pelvis`** and lidar as **`/g1/lidar/points` (`PointCloud2`)**. Nav2 and the
LtlMonitor evaluator (`llm_client.py`) expect **`/odom`** (`Odometry`) and **`/scan`**
(`LaserScan`). Two bridges close that gap.

## 1. `/odom` ← TF (custom, `odom_from_tf.py`)

```bash
python3 odom_from_tf.py --ros-args -p base_frame:=pelvis -p odom_frame:=odom -p rate_hz:=30.0
```

Republishes the `odom → pelvis` transform as `Odometry`. The pose **orientation** carries the
base roll/pitch the evaluator turns into `upright`/`fell_over` (see `g1_sensors.quat_to_euler`).

## 2. `/scan` ← PointCloud2 (stock `pointcloud_to_laserscan`)

Do **not** reinvent this — use the maintained package. The pure projection math the evaluator
also needs is in `g1_sensors.min_range_from_points` (height-band filter), unit-tested.

```bash
ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node --ros-args \
  -r cloud_in:=/g1/lidar/points -r scan:=/scan \
  -p target_frame:=pelvis -p min_height:=0.1 -p max_height:=1.5 \
  -p range_min:=0.2 -p range_max:=15.0 -p angle_increment:=0.0087
```

`min_height`/`max_height` mirror `min_range_from_points`'s `z_lo`/`z_hi` — tune to the G1's
body band so the floor/ceiling aren't seen as obstacles.

## Calibration knobs (sim-specific — tune on the live G1)

- Fall: `g1_sensors.base_upright(tilt_max=0.5 rad, height_min=0.5 m)`.
- Collision: `collision_risk` fires at `min_range < 0.25` (`formulas_g1.json`) — set to the G1 footprint.
- Nav2 footprint/inflation in `nav2_params.yaml` must match the humanoid, not the default base.
