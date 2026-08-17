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
from std_msgs.msg import String
from rclpy.node import Node

import g1_sensors
from g1_real_frame import remap_optical_to_body
from sensor_adapter import Freshness, SensorAdapter
from stuck_detector import StuckStreak
from vision_mixin import VisionScoreMixin

# Sources whose silence is unsafe. /vision/goal_similarity is deliberately NOT
# here: run_visual_goal_matcher.py is optional, so counting it would peg
# confidence below 1.0 on every run that does not use visual goal confirmation.
_TRACKED_SOURCES = ("odom", "points", "status")


class RealG1Adapter(SensorAdapter, VisionScoreMixin):
    def __init__(
        self,
        stuck_ticks: int = 10,
        stale_after: float = 2.0,
        upright_tilt_max: float = 0.5,
        upright_height_min: float = 0.5,
        clock=None,
    ):
        VisionScoreMixin.__init__(self)
        self.odom_data: dict = {}
        self.scan_data: dict = {}
        self.nav_data: dict = {}
        self._streak = StuckStreak(threshold=stuck_ticks)
        # Hardware knobs -- both defaults are the pre-existing hardcoded values and
        # NEITHER has been checked against the real robot. upright_height_min in
        # particular is a guess at the G1's standing pelvis height; calibrate from a
        # recorded run before trusting `upright`/`fell_over`.
        self.upright_tilt_max = float(upright_tilt_max)
        self.upright_height_min = float(upright_height_min)
        self._fresh = Freshness(
            _TRACKED_SOURCES,
            stale_after=stale_after,
            **({"clock": clock} if clock is not None else {}),
        )

    def register_subscriptions(self, node: Node) -> None:
        node.create_subscription(Odometry, "/t265/odom/sample", self._odom_cb, 10)
        node.create_subscription(PointCloud2, "/depth_anything/points", self._points_cb, 10)
        node.create_subscription(String, "/path_manager/status", self._status_cb, 10)
        self._register_vision_subscription(node)

    def _odom_cb(self, msg: Odometry):
        x, y, z = msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z
        q = msg.pose.pose.orientation
        roll, pitch, _yaw = g1_sensors.quat_to_euler(q.x, q.y, q.z, q.w)
        upright = g1_sensors.base_upright(
            roll, pitch, z,
            tilt_max=self.upright_tilt_max, height_min=self.upright_height_min,
        )
        self._fresh.stamp("odom")
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
        self._fresh.stamp("points")
        self.scan_data = {"min_range": round(min_range, 2)}

    def _status_cb(self, msg: String):
        import json

        try:
            data = json.loads(msg.data)
        except Exception:
            return

        state = data.get("state", "waiting_inputs")
        self._streak.update(state)
        self._fresh.stamp("status")

        self.nav_data = {
            "mode": data.get("mode", "MANUAL"),
            "state": state,
            "finished": bool(data.get("finished", False)),
            "num_waypoints": int(data.get("num_waypoints", 0)),
            "current_target_idx": int(data.get("current_target_idx", 0)),
        }

    def get_sensor_eval(self) -> dict:
        return self.validate_sensor_eval({
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
            "image_similarity_to_goal": self.vision_score,
        })

    def stale_sources(self) -> tuple[str, ...]:
        return self._fresh.stale_sources()

    def confidence(self) -> float:
        return self._fresh.confidence()

    def describe(self) -> dict:
        pos = self.odom_data.get("position", {})
        stale = self.stale_sources()
        return {
            "pos": f"({pos.get('x', 'N/A')}, {pos.get('y', 'N/A')})",
            "min_range": self.scan_data.get("min_range", "N/A"),
            "nav_mode": self.nav_data.get("mode", "N/A"),
            "nav_state": self.nav_data.get("state", "N/A"),
            "blocked_streak": f"{self._streak.count}/{self._streak.threshold}",
            "goal_similarity": self.vision_score,
            "stale": ",".join(stale) if stale else "—",
        }
