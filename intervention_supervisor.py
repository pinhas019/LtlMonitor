#!/usr/bin/env python3
"""G1 safety intervention supervisor (the ablation's *recovery* arm).

Subscribes the monitor's ``/ltl/state_description``; when a SAFETY failure mode is VIOLATED
(fell_over / collision_imminent — see supervisor_logic.decide_intervention) it overrides
Nav2 by publishing zero ``/cmd_vel`` at a fixed rate until the fault clears (episode reset).

The ``enabled`` parameter is the recovery toggle used by the ablation:
  - OFF / shadow arms  -> run with enabled:=false (or don't launch this node) -> detection only.
  - recovery arm       -> enabled:=true -> the monitor actually intervenes.

Decision logic is pure and unit-tested in test_supervisor_logic.py; this node is the thin
ROS wrapper (validate on the live stack). Run: python3 intervention_supervisor.py
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist

from supervisor_logic import decide_intervention


class InterventionSupervisor(Node):
    def __init__(self):
        super().__init__("g1_intervention_supervisor")
        self.declare_parameter("enabled", True)
        self.declare_parameter("rate_hz", 10.0)
        self.enabled = bool(self.get_parameter("enabled").value)
        self.halting = False

        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.create_subscription(String, "/ltl/state_description", self._on_state, 10)
        self.create_timer(
            1.0 / float(self.get_parameter("rate_hz").value), self._enforce
        )
        self.get_logger().info(
            f"Intervention supervisor started (enabled={self.enabled})."
        )

    def _on_state(self, msg: String):
        try:
            state = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        decision = decide_intervention(state)
        if decision.halt and not self.halting:
            self.get_logger().warn(
                f"SAFETY fault '{decision.reason}' — overriding /cmd_vel with zero velocity"
            )
        self.halting = decision.halt

    def _enforce(self):
        # While a safety fault is active, keep publishing zero velocity to override Nav2.
        if self.enabled and self.halting:
            self.cmd_pub.publish(Twist())


def main():
    rclpy.init()
    node = InterventionSupervisor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
