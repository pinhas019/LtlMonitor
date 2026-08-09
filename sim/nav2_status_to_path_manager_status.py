"""Sim-only shim: translates Nav2's /navigate_to_pose/_action/status (GoalStatusArray)
into a /path_manager/status-shaped JSON String, so g1_real_client.py's status_callback
(and formulas_g1_real.json's nav_mode/nav_state/finished-driven APs) can be exercised
against the MuJoCo+Nav2 sim stack, which has no path_manager.py equivalent.

NOT deployed to the real robot. See nav2_status_map.py (unit-tested) for the actual
status-vocabulary mapping. Sim missions are single-goal (send_goal.py sends one
/goal_pose), so num_waypoints is fixed at 1 rather than modeling a real waypoint list.
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from action_msgs.msg import GoalStatusArray

from nav2_status_map import nav2_status_to_state


class Nav2StatusToPathManagerStatus(Node):
    def __init__(self):
        super().__init__("nav2_status_to_path_manager_status_shim")
        self.pub = self.create_publisher(String, "/path_manager/status", 10)
        self.create_subscription(
            GoalStatusArray, "/navigate_to_pose/_action/status", self._on_status, 10
        )
        self._started = False
        self.get_logger().info(
            "nav2-status-to-path_manager-status shim started (sim-only)."
        )

    def _on_status(self, msg: GoalStatusArray):
        if not msg.status_list:
            return
        self._started = True
        state = nav2_status_to_state(msg.status_list[-1].status)
        payload = {
            "mode": "AUTOMATIC" if self._started else "MANUAL",
            "state": state,
            "finished": state == "finished",
            "num_waypoints": 1,
            "current_target_idx": 0,
        }
        out = String()
        out.data = json.dumps(payload)
        self.pub.publish(out)


def main():
    rclpy.init()
    node = Nav2StatusToPathManagerStatus()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
