#!/usr/bin/env python3
"""Stand in for the parts of the stack a robot-tier smoke test does not run.

Two of them, and both are normally somebody else's job:

  * `/ltl/required_aps` + `/ltl/state_description` come from the MONITOR, which in the
    split deployment lives on the dev PC. Without them the evaluator stays idle and
    publishes nothing at all, so a smoke test that skipped this would be measuring an
    evaluator that had correctly decided to do nothing.
  * The adapter's odometry topic comes from the robot's own stack. It is published here
    with a MOVING x, because a constant would pass against the exact bug this tier was
    just fixed for -- `sensor_eval()` returning schema defaults forever looks identical
    to a robot that is standing still.

    ros2 run is not involved: this is a plain rclpy script so it can be exec'd inside
    the evaluator image, which already has every dependency it needs.

Usage (inside a container on the robot's graph):

    python3 deploy/smoke_stimulus.py --adapter mujoco --seconds 20
"""

from __future__ import annotations

import argparse
import json


#: Per adapter: the odometry topic to drive, and the sensor key that must move because
#: of it. Keyed by adapter name rather than sniffed, so a descriptor that renames a
#: topic fails loudly here instead of publishing into the void.
ODOM = {
    "mujoco": ("/odom", "pos_x"),
    "isaac_lab": ("/odom", "pos_x"),
    "real_g1": ("/t265/odom/sample", "pos_x"),
}

#: Enough of a state description for the evaluator's rule path. These are the real
#: spellings from the shipped specs -- `_rule_eval` parses "True when <expr>", and a
#: description it cannot parse falls through to the LLM, which is unreachable here.
DESCRIPTIONS = {
    "upright": "True when upright_flag > 0.5. The base is level.",
    "collision_risk": "True when min_range < 0.25. An obstacle is too close.",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--adapter", default="mujoco", choices=sorted(ODOM))
    p.add_argument("--seconds", type=float, default=20.0)
    p.add_argument("--rate", type=float, default=10.0,
                   help="odometry publish rate; the point is to be faster than the "
                        "tick, so a window holds several samples")
    return p


def main() -> None:
    args = build_parser().parse_args()

    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String

    topic, _key = ODOM[args.adapter]

    rclpy.init()
    node = Node("smoke_stimulus")
    aps_pub = node.create_publisher(String, "/ltl/required_aps", 10)
    desc_pub = node.create_publisher(String, "/ltl/state_description", 10)
    odom_pub = node.create_publisher(Odometry, topic, 10)

    required = sorted(DESCRIPTIONS)
    state = {"skill_name": "smoke", "phase": "drive",
             "ap_descriptions": DESCRIPTIONS}

    ticks = 0
    total = int(args.seconds * args.rate)

    def pulse():
        nonlocal ticks
        ticks += 1
        # Republished every cycle rather than once: these are volatile topics and the
        # evaluator may have connected after a one-shot would have gone out. Cheap.
        aps_pub.publish(String(data=json.dumps(required)))
        desc_pub.publish(String(data=json.dumps(state)))

        msg = Odometry()
        # The moving part. 0.1 m per sample at 10 Hz is a metre a second, which is a
        # plausible walk and, more to the point, is visibly different every tick.
        msg.pose.pose.position.x = ticks * 0.1
        msg.pose.pose.position.y = 0.0
        msg.pose.pose.position.z = 0.75          # a standing base, so `upright` is true
        msg.pose.pose.orientation.w = 1.0
        msg.twist.twist.linear.x = 1.0
        odom_pub.publish(msg)

        if ticks >= total:
            raise SystemExit(0)

    node.create_timer(1.0 / args.rate, pulse)
    print(f"[stimulus] {topic} at {args.rate} Hz for {args.seconds}s, "
          f"required_aps={required}", flush=True)
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
