"""Dev-PC half of the camera bridge: TCP frames back onto a real ROS Image topic.

    python3 tools/bridge_rx.py --host 192.168.0.198 --topic /depth_anything/color_image

What it publishes is an ordinary `sensor_msgs/Image` carrying the robot's own
`frame_id` and stamp, so an adapter descriptor points at a topic name and nothing in
`skill_monitor` knows a bridge exists. That is the whole design constraint: when the
monitor eventually runs where the camera is, this process goes away and no descriptor,
no test and no line of the monitor changes.

`rclpy` is imported inside `main` so the framing logic here can be tested on a machine
with no ROS. This half runs on the dev PC and may use 3.10 syntax; its sibling
`bridge_tx.py` runs on the robot's 3.8 container and may not.
"""

from __future__ import annotations

import argparse
import socket
import time

from camera_bridge import read_frame


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bridge_rx", description=__doc__.splitlines()[0])
    p.add_argument("--host", required=True, help="the robot running bridge_tx")
    p.add_argument("--port", type=int, default=8123)
    p.add_argument("--topic", default="/depth_anything/color_image",
                   help="republished here with the SAME name the robot uses, so a "
                        "descriptor written for the robot works unchanged")
    p.add_argument("--retry-s", type=float, default=2.0)
    return p


def to_image(header: dict, payload: bytes, Image):
    """One `sensor_msgs/Image` from a bridged frame.

    The encoding is passed through rather than converted. `bgr8` stays `bgr8`, so the
    single place that knows about channel order is the raw-echo encoder downstream --
    which is tested for it. A bridge that quietly rewrote colour would be a second
    implementation of that, in the one component nobody thinks to look at.
    """
    m = Image()
    m.header.frame_id = header.get("frame_id", "")
    m.header.stamp.sec = int(header.get("sec", 0))
    m.header.stamp.nanosec = int(header.get("nsec", 0))
    m.height = int(header["h"])
    m.width = int(header["w"])
    m.encoding = header["encoding"]
    m.is_bigendian = 0
    m.step = int(header["step"])
    m.data = list(payload)
    return m


def pump(sock: socket.socket, on_frame, keep_going=lambda: True) -> str:
    """Read frames until the stream ends. Returns why it stopped, for the log."""
    while keep_going():
        frame = read_frame(sock.recv)
        if frame is None:
            return "stream ended"
        on_frame(*frame)
    return "asked to stop"


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    import rclpy                       # noqa: PLC0415 -- see the module docstring
    from rclpy.node import Node
    from sensor_msgs.msg import Image

    rclpy.init()
    node = Node("camera_bridge_rx")
    pub = node.create_publisher(Image, args.topic, 1)
    seen = {"n": 0}

    def on_frame(header, payload):
        pub.publish(to_image(header, payload, Image))
        seen["n"] += 1
        if seen["n"] % 20 == 1:
            node.get_logger().info(
                "republished %d frames on %s (%dx%d %s, source %sx%s)"
                % (seen["n"], args.topic, header["w"], header["h"],
                   header["encoding"], header.get("src_w"), header.get("src_h")))

    while rclpy.ok():
        try:
            with socket.create_connection((args.host, args.port), timeout=10) as sock:
                node.get_logger().info("connected to %s:%d" % (args.host, args.port))
                sock.settimeout(15)
                why = pump(sock, on_frame, keep_going=rclpy.ok)
                node.get_logger().warn("%s; reconnecting" % why)
        except OSError as exc:
            node.get_logger().warn(
                "bridge unreachable (%s); retrying in %.1fs" % (exc, args.retry_s))
            time.sleep(args.retry_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
