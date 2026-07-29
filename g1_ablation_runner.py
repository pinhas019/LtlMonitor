#!/usr/bin/env python3
"""G1 nav episodic driver — the ablation's per-cell episode runner (ROS 2 orchestration).

For one cell it: resets the sim to a scenario, sends the goal, spins until a terminal
signal, and returns a flat outcome record. Terminal classification is the pure, unit-tested
``episode_outcome.classify_outcome`` (Nav2 status + monitor SAFETY fault + timeout).

Validate on the live stack (needs ROS 2 + the Isaac G1 + Nav2 + monitor running).

**Sim reset boundary (must be provided by the Isaac side):** this node requests a scenario
reset by publishing the scenario JSON on ``/g1/reset``; the Isaac sim (sim2real_isaac) must
subscribe it and respawn the G1 to the start pose + place the scenario's obstacles/disturbance,
then publish ``/g1/reset_done`` (std_msgs/Bool). Reset is the one capability that does not
exist yet — see plan M4.
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseStamped

from episode_outcome import classify_outcome, safety_fault_from_state


class G1EpisodeDriver(Node):
    def __init__(self):
        super().__init__("g1_episode_driver")
        self.nav_status = ""
        self.state_desc: dict = {}
        self.reset_done = False

        self.reset_pub = self.create_publisher(String, "/g1/reset", 10)
        self.goal_pub = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.create_subscription(String, "/ltl/state_description", self._on_state, 10)
        self.create_subscription(Bool, "/g1/reset_done", self._on_reset_done, 10)
        # Nav2 action status (GoalStatusArray) — imported lazily so this module parses
        # without the action_msgs dependency during offline inspection.
        from action_msgs.msg import GoalStatusArray

        self.create_subscription(
            GoalStatusArray, "/navigate_to_pose/_action/status", self._on_nav_status, 10
        )

    # ---- callbacks ----
    def _on_state(self, msg: String):
        try:
            self.state_desc = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def _on_reset_done(self, msg: Bool):
        self.reset_done = bool(msg.data)

    def _on_nav_status(self, msg):
        if msg.status_list:
            code = msg.status_list[-1].status
            self.nav_status = {4: "succeeded", 5: "canceled", 6: "aborted"}.get(
                code, {1: "accepted", 2: "executing", 3: "canceling"}.get(code, "")
            )

    # ---- one episode ----
    def run_episode(self, scenario: dict, goal_xy, timeout_s: float = 120.0) -> dict:
        """Reset to ``scenario``, drive to ``goal_xy``, return an outcome record."""
        self.nav_status, self.state_desc, self.reset_done = "", {}, False

        self.reset_pub.publish(String(data=json.dumps(scenario)))
        self._spin_until(lambda: self.reset_done, timeout_s=20.0)

        goal = PoseStamped()
        goal.header.frame_id = "map"
        goal.header.stamp = self.get_clock().now().to_msg()
        goal.pose.position.x, goal.pose.position.y = (
            float(goal_xy[0]),
            float(goal_xy[1]),
        )
        goal.pose.orientation.w = 1.0
        self.goal_pub.publish(goal)

        start = time.monotonic()
        outcome = classify_outcome("", None, False)
        while rclpy.ok() and not outcome.terminal:
            rclpy.spin_once(self, timeout_sec=0.1)
            timed_out = (time.monotonic() - start) > timeout_s
            fault = safety_fault_from_state(self.state_desc)
            outcome = classify_outcome(self.nav_status, fault, timed_out)

        return {
            "scenario": scenario.get("name"),
            "success": outcome.success,
            "cause": outcome.cause,
            "elapsed_s": round(time.monotonic() - start, 1),
        }

    def _spin_until(self, pred, timeout_s: float):
        start = time.monotonic()
        while rclpy.ok() and not pred() and (time.monotonic() - start) < timeout_s:
            rclpy.spin_once(self, timeout_sec=0.1)


def main():
    rclpy.init()
    node = G1EpisodeDriver()
    try:
        # example single episode; the ablation adapter (M5) calls run_episode per cell
        rec = node.run_episode({"name": "clear"}, goal_xy=(3.0, 0.0))
        node.get_logger().info(f"episode outcome: {rec}")
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
