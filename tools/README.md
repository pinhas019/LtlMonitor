# tools

Deployment glue, not part of `skill_monitor`. Nothing here is imported by the package,
and nothing in the package imports it.

## `camera_bridge.py` / `bridge_tx.py` / `bridge_rx.py`

Carries one `sensor_msgs/Image` topic from a robot the monitor cannot reach onto the
monitor's own ROS graph.

It exists because of a version wall, not a design preference. On the G1: the ROS graph
is humble inside containers, DDS is bound to `eth0`, and the host and every container
are Python 3.8 — while `skill_monitor` declares `requires-python = ">=3.10"`. So the
monitor runs on the dev PC, the camera is on the robot, and DDS does not cross the wifi
between them.

    # on the robot, inside the container that has the camera
    python3 tools/bridge_tx.py --topic /depth_anything/color_image --rate 2

    # on the machine running the monitor
    python3 tools/bridge_rx.py --host 192.168.0.198

The receiver republishes an ordinary `sensor_msgs/Image` under the **same topic name**,
carrying the robot's own `frame_id` and stamp. An adapter descriptor names a topic and
nothing in `skill_monitor` learns a bridge was involved — which is the point: when the
monitor runs where the camera is, delete these three files and change nothing else.

**`bridge_tx.py` and `camera_bridge.py` must stay Python 3.8-clean.** They run on the
robot. `bridge_rx.py` runs beside the monitor and may use 3.10.

Carries `rgb8` and `bgr8` only, and passes the encoding through rather than converting
it — a depth frame needs a colourisation decision that a transport has no business
making. Downscales at source, because shipping 230 KB frames over wifi to prove DDS
could not is its own kind of silly.

## `rviz/`

The monitor's input as geometry. The console shows the numbers; this shows the shapes —
the depth cloud `min_range` is computed from, the terrain the planner planned on, the
path, and the commanded waypoint.

    tools/rviz/run.sh

There is no 3D viewport in the console and there should not be: `docs/packages/P7-frontend.md`
lists one as a non-goal because rviz2 exists and is better at it. This is that decision,
made runnable.

`run.sh` publishes the `map -> camera_color_optical_frame` static transform before
starting, because nothing else in the stack does and rviz2's failure without it is an
empty scene rather than a message naming the missing frame.

The `filtered_map` display needs `grid_map_rviz_plugin`, which on the G1's own host had
to be built natively — see `g1_gridmap_navigation_refinement.md` in the TRAV repo. Every
other display is a stock `rviz_default_plugins` one.
