#!/usr/bin/env python3
"""Publish nav_msgs/Odometry on /odom from the Isaac Lab G1 TF (odom -> pelvis).

The Isaac Lab bridge (sim2real_isaac/g1_ros2_bridge.py) publishes the base pose only as a
TF (odom -> pelvis); Nav2 and the LtlMonitor evaluator want an /odom topic. This thin node
looks up that transform on a timer and republishes it as Odometry (orientation carries the
base roll/pitch the evaluator uses for fall detection). Twist is left zero — Nav2's local
costmap + the monitor's fall/collision APs don't need it; add finite-difference velocity if a
consumer requires it.

Run alongside the sim (needs ROS 2 + tf2_ros): python3 odom_from_tf.py
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from tf2_ros import Buffer, TransformListener, LookupException, ExtrapolationException


class OdomFromTf(Node):
    def __init__(self):
        super().__init__("odom_from_tf")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "pelvis")
        self.declare_parameter("rate_hz", 30.0)
        self.odom_frame = self.get_parameter("odom_frame").value
        self.base_frame = self.get_parameter("base_frame").value

        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.pub = self.create_publisher(Odometry, "/odom", 10)
        self.create_timer(1.0 / float(self.get_parameter("rate_hz").value), self._tick)

    def _tick(self):
        try:
            tf = self.buffer.lookup_transform(
                self.odom_frame, self.base_frame, rclpy.time.Time()
            )
        except (LookupException, ExtrapolationException):
            return  # transform not available yet — skip this tick
        t, r = tf.transform.translation, tf.transform.rotation
        odom = Odometry()
        odom.header.stamp = self.get_clock().now().to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = t.x
        odom.pose.pose.position.y = t.y
        odom.pose.pose.position.z = t.z
        odom.pose.pose.orientation = r
        self.pub.publish(odom)


def main():
    rclpy.init()
    node = OdomFromTf()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
