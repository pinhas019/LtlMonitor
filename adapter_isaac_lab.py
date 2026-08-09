"""SensorAdapter for the Isaac Lab G1 sim (sim2real_isaac/g1_ros2_bridge.py) + Nav2.

Per g1_bridges.md, Isaac Lab publishes base pose only as a TF `odom -> pelvis` and
lidar as `/g1/lidar/points` (PointCloud2) -- run sim/odom_from_tf.py alongside this
adapter to republish that TF as /odom (nav_msgs/Odometry); once that's running, this
adapter is otherwise identical to MujocoAdapter (inherited from Nav2BackedAdapter),
differing only in the range topic.

Frame-convention assumption (verify before trusting on real Isaac Lab data, same
spirit as g1_bridges.md's own "tune on the live G1" notes): /g1/lidar/points is
assumed already Z-up / body-planar, like an upright-mounted 3D lidar's native sensor
frame -- NOT the camera-optical convention g1_real_frame.py remaps for the real
robot's camera-derived cloud. If Isaac Lab's actual lidar frame turns out to need a
remap too, add one here (not in g1_sensors.py, which stays generic).
"""

from __future__ import annotations

from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from rclpy.node import Node

import g1_sensors
from adapter_nav2_common import Nav2BackedAdapter


class IsaacLabAdapter(Nav2BackedAdapter):
    def _register_range_subscription(self, node: Node) -> None:
        node.create_subscription(PointCloud2, "/g1/lidar/points", self._points_cb, 10)

    def _points_cb(self, msg: PointCloud2):
        points = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
        self._set_min_range(g1_sensors.min_range_from_points(points, z_lo=0.1, z_hi=1.5, default=10.0))
