"""SensorAdapter for the real TRAV-metric-map G1 -- no Nav2, no lidar.

  /t265/odom/sample      (nav_msgs/Odometry)        odom + IMU-derived base orientation
  /depth_anything/points (sensor_msgs/PointCloud2)  camera-derived range (no lidar)
  /path_manager/status   (std_msgs/String, JSON)    planned-path/mission status (no Nav2)
  /vision/goal_similarity(std_msgs/Float32)          CLIP-based visual goal confirmation

See g1_real_frame.py for the camera-optical-frame axis remap (unit-tested there).
"""

from __future__ import annotations

from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from std_msgs.msg import String, Float32
from rclpy.node import Node

import g1_sensors
from g1_real_frame import remap_optical_to_body
from sensor_adapter import SensorAdapter
from stuck_detector import StuckStreak


class RealG1Adapter(SensorAdapter):
    def __init__(self, stuck_ticks: int = 10):
        self.odom_data: dict = {}
        self.scan_data: dict = {}
        self.nav_data: dict = {}
        self.vision_data: dict = {}
        self._streak = StuckStreak(threshold=stuck_ticks)

    def register_subscriptions(self, node: Node) -> None:
        node.create_subscription(Odometry, "/t265/odom/sample", self._odom_cb, 10)
        node.create_subscription(PointCloud2, "/depth_anything/points", self._points_cb, 10)
        node.create_subscription(String, "/path_manager/status", self._status_cb, 10)
        node.create_subscription(Float32, "/vision/goal_similarity", self._vision_cb, 10)

    def _odom_cb(self, msg: Odometry):
        x, y, z = msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z
        q = msg.pose.pose.orientation
        roll, pitch, _yaw = g1_sensors.quat_to_euler(q.x, q.y, q.z, q.w)
        upright = g1_sensors.base_upright(roll, pitch, z)
        self.odom_data = {
            "position": {"x": round(x, 2), "y": round(y, 2)},
            "linear_vel": round(msg.twist.twist.linear.x, 2),
            "angular_vel": round(msg.twist.twist.angular.z, 2),
            "base_roll": round(roll, 3),
            "base_pitch": round(pitch, 3),
            "base_height": round(z, 3),
            "upright_flag": 1.0 if upright else 0.0,
        }

    def _points_cb(self, msg: PointCloud2):
        raw = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
        min_range = g1_sensors.min_range_from_points(
            remap_optical_to_body(raw), z_lo=0.1, z_hi=1.5, default=10.0
        )
        self.scan_data = {"min_range": round(min_range, 2)}

    def _status_cb(self, msg: String):
        import json

        try:
            data = json.loads(msg.data)
        except Exception:
            return

        state = data.get("state", "waiting_inputs")
        self._streak.update(state)

        self.nav_data = {
            "mode": data.get("mode", "MANUAL"),
            "state": state,
            "finished": bool(data.get("finished", False)),
            "num_waypoints": int(data.get("num_waypoints", 0)),
            "current_target_idx": int(data.get("current_target_idx", 0)),
        }

    def _vision_cb(self, msg: Float32):
        self.vision_data = {"image_similarity_to_goal": round(float(msg.data), 3)}

    def get_sensor_eval(self) -> dict:
        return {
            "min_range": self.scan_data.get("min_range", 10.0),
            "base_roll": self.odom_data.get("base_roll", 0.0),
            "base_pitch": self.odom_data.get("base_pitch", 0.0),
            "base_height": self.odom_data.get("base_height", 1.0),
            "upright_flag": self.odom_data.get("upright_flag", 1.0),
            "linear_vel": self.odom_data.get("linear_vel", 0.0),
            "angular_vel": self.odom_data.get("angular_vel", 0.0),
            "nav_mode": self.nav_data.get("mode", "MANUAL"),
            "nav_state": self.nav_data.get("state", "waiting_inputs"),
            "num_waypoints": self.nav_data.get("num_waypoints", 0),
            "current_target_idx": self.nav_data.get("current_target_idx", 0),
            "mission_finished": self.nav_data.get("finished", False),
            "nav_stuck": self._streak.is_stuck,
            "image_similarity_to_goal": self.vision_data.get("image_similarity_to_goal", 0.0),
        }

    def describe(self) -> dict:
        pos = self.odom_data.get("position", {})
        return {
            "pos": f"({pos.get('x', 'N/A')}, {pos.get('y', 'N/A')})",
            "min_range": self.scan_data.get("min_range", "N/A"),
            "nav_mode": self.nav_data.get("mode", "N/A"),
            "nav_state": self.nav_data.get("state", "N/A"),
            "blocked_streak": f"{self._streak.count}/{self._streak.threshold}",
            "goal_similarity": self.vision_data.get("image_similarity_to_goal", "N/A"),
        }
