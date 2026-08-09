"""SensorAdapter for the MuJoCo sim harness (sim/mujoco_ros_bridge.py) + Nav2.

LaserScan gives range directly as a distance-per-angle array -- no PointCloud2 decode
or axis remap needed, unlike the real robot's camera-derived point cloud. This is what
made the M3-era scan_to_pointcloud.py shim unnecessary once adapters exist: there's no
reason to manufacture a fake PointCloud2 just to feed it back through
min_range_from_points when the LaserScan already IS the range reading.
"""

from __future__ import annotations

import math

from sensor_msgs.msg import LaserScan
from rclpy.node import Node

from adapter_nav2_common import Nav2BackedAdapter


class MujocoAdapter(Nav2BackedAdapter):
    def _register_range_subscription(self, node: Node) -> None:
        node.create_subscription(LaserScan, "/scan", self._scan_cb, 10)

    def _scan_cb(self, msg: LaserScan):
        valid = [r for r in msg.ranges if r > 0.0 and math.isfinite(r)]
        self._set_min_range(min(valid) if valid else 10.0)
