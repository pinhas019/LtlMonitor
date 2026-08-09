"""Shared base for sim adapters that sit behind Nav2 + a /odom-publishing bridge
(MuJoCo's mujoco_ros_bridge.py; Isaac Lab's odom_from_tf.py republishing its
odom->pelvis TF, per g1_bridges.md) -- both environments expose position/orientation
identically (nav_msgs/Odometry) and both need Nav2's GoalStatusArray translated into
the canonical mode/state/finished vocabulary via nav2_status_map.py (the same
in-process translation nav2_status_to_path_manager_status.py used to do as a separate
ROS shim node -- no shim needed now, it's just a method call here).

Only how range/obstacle distance is obtained differs between environments (LaserScan
vs PointCloud2), left to subclasses via _register_range_subscription/_set_min_range.
"""

from __future__ import annotations

from abc import abstractmethod

from action_msgs.msg import GoalStatusArray
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_action_status_default

import g1_sensors
from sensor_adapter import SensorAdapter
from stuck_detector import StuckStreak
from nav2_status_map import nav2_status_to_state
from vision_mixin import VisionScoreMixin


class Nav2BackedAdapter(SensorAdapter, VisionScoreMixin):
    def __init__(self, stuck_ticks: int = 10):
        VisionScoreMixin.__init__(self)
        self.odom_data: dict = {}
        self.range_data: dict = {}
        self._streak = StuckStreak(threshold=stuck_ticks)
        self._nav_state = "waiting_inputs"
        self._started = False

    def register_subscriptions(self, node: Node) -> None:
        node.create_subscription(Odometry, "/odom", self._odom_cb, 10)
        # Action status topics publish TRANSIENT_LOCAL by convention (so a subscriber
        # that connects after a status was already published still gets it) -- a bare
        # int here defaults to VOLATILE, which can silently miss every status update
        # depending on subscribe/publish timing. qos_profile_action_status_default is
        # the same profile rclpy's own ActionClient uses internally to query status.
        node.create_subscription(
            GoalStatusArray, "/navigate_to_pose/_action/status", self._nav2_status_cb,
            qos_profile_action_status_default,
        )
        self._register_range_subscription(node)
        self._register_vision_subscription(node)

    @abstractmethod
    def _register_range_subscription(self, node: Node) -> None:
        """Subscribe to this environment's range topic; the callback must call
        self._set_min_range(value)."""

    def _set_min_range(self, min_range: float) -> None:
        self.range_data = {"min_range": round(min_range, 2)}

    def _odom_cb(self, msg: Odometry):
        z = msg.pose.pose.position.z
        q = msg.pose.pose.orientation
        roll, pitch, _yaw = g1_sensors.quat_to_euler(q.x, q.y, q.z, q.w)
        upright = g1_sensors.base_upright(roll, pitch, z)
        self.odom_data = {
            "linear_vel": round(msg.twist.twist.linear.x, 2),
            "angular_vel": round(msg.twist.twist.angular.z, 2),
            "base_roll": round(roll, 3),
            "base_pitch": round(pitch, 3),
            "base_height": round(z, 3),
            "upright_flag": 1.0 if upright else 0.0,
        }

    def _nav2_status_cb(self, msg: GoalStatusArray):
        if not msg.status_list:
            return
        self._started = True
        self._nav_state = nav2_status_to_state(msg.status_list[-1].status)
        self._streak.update(self._nav_state)

    def get_sensor_eval(self) -> dict:
        return self.validate_sensor_eval({
            "min_range": self.range_data.get("min_range", 10.0),
            "base_roll": self.odom_data.get("base_roll", 0.0),
            "base_pitch": self.odom_data.get("base_pitch", 0.0),
            "base_height": self.odom_data.get("base_height", 1.0),
            "upright_flag": self.odom_data.get("upright_flag", 1.0),
            "linear_vel": self.odom_data.get("linear_vel", 0.0),
            "angular_vel": self.odom_data.get("angular_vel", 0.0),
            "nav_mode": "AUTOMATIC" if self._started else "MANUAL",
            "nav_state": self._nav_state,
            # Sim missions here are single-goal (send_goal.py sends one /goal_pose),
            # so there's no real waypoint list to report.
            "num_waypoints": 1,
            "current_target_idx": 0,
            "mission_finished": self._nav_state == "finished",
            "nav_stuck": self._streak.is_stuck,
            "image_similarity_to_goal": self.vision_score,
        })

    def describe(self) -> dict:
        return {
            "min_range": self.range_data.get("min_range", "N/A"),
            "nav_state": self._nav_state,
            "blocked_streak": f"{self._streak.count}/{self._streak.threshold}",
            "goal_similarity": self.vision_score,
        }
