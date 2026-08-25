#!/usr/bin/env bash
# The monitor's input, as geometry. The console shows the numbers; this shows the shapes.
#
#   tools/rviz/run.sh
#
# The console deliberately has no 3D viewport -- P7's own doc lists one as a non-goal,
# because rviz2 exists and is better at it. What the console cannot show is the point
# cloud, the grid map and the planned path in space, which is most of what "is the robot
# seeing the world correctly" means.
#
# The static transform is not optional. The Depth-Anything cloud is published in
# `camera_color_optical_frame` and nothing else in the stack publishes a transform from
# `map` to it, so without this rviz2 shows an empty scene and a TF error rather than
# saying the frame is missing. TRAV's own README.txt carries the same line.
set -euo pipefail

RVIZ_CONFIG="${RVIZ_CONFIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/monitor.rviz}"
FIXED_FRAME="${FIXED_FRAME:-map}"
CAMERA_FRAME="${CAMERA_FRAME:-camera_color_optical_frame}"

source /opt/ros/humble/setup.bash 2>/dev/null || true

# ponytail: killed with this script's process group, not tracked individually. If you
# need the transform to outlive rviz2, publish it from your own launch instead.
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 "$FIXED_FRAME" "$CAMERA_FRAME" \
  >/dev/null 2>&1 &
trap 'kill %1 2>/dev/null || true' EXIT

echo "[rviz] $FIXED_FRAME -> $CAMERA_FRAME, config $RVIZ_CONFIG"
exec rviz2 -d "$RVIZ_CONFIG"
