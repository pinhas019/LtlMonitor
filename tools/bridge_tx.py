"""Robot half of the camera bridge: one ROS Image topic out over TCP.

    python3 tools/bridge_tx.py --topic /depth_anything/color_image --rate 2

Runs inside the robot's container, which is **Python 3.8** — so no builtin generics
at runtime and no PEP 604 outside deferred annotations. `rclpy` is imported inside
`main` rather than at module scope so the file can be imported, and its argument
parsing tested, on a machine with no ROS at all.

Listens rather than connects: the robot has the camera and is the stable end, so the
dev PC is the client and either side can restart without the other being told.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import threading

from camera_bridge import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    channels_for,
    header_for,
    pack_frame,
    resample,
)


def build_parser():
    p = argparse.ArgumentParser(prog="bridge_tx", description=__doc__.splitlines()[0])
    p.add_argument("--topic", default="/depth_anything/color_image")
    p.add_argument("--bind", default="0.0.0.0",
                   help="loopback-only by default is wrong here: the point is to be "
                        "reached from another machine on the lab network")
    p.add_argument("--port", type=int, default=8123)
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--rate", type=float, default=2.0,
                   help="frames per second onto the wire; the camera's own rate is "
                        "not changed and unsent frames are dropped, never queued")
    return p


class _Latest(object):
    """The newest frame, and only the newest.

    A queue would be wrong. If the wifi stalls, an operator wants the picture from now,
    not a backlog of what the robot saw while the link was busy — and a bounded queue
    that drops the *oldest* is just this with more moving parts.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None

    def put(self, frame):
        with self._lock:
            self._frame = frame

    def take(self):
        with self._lock:
            frame, self._frame = self._frame, None
            return frame


def frame_from_image(msg, out_width, out_height):
    """``(header, pixels)`` for one `sensor_msgs/Image`, or None if unsupported.

    None rather than an exception: an unsupported encoding on a topic somebody pointed
    the bridge at is a configuration answer, not a crash, and the log line says which
    encoding it was.
    """
    channels = channels_for(msg.encoding)
    if channels is None:
        return None
    pixels, ow, oh = resample(bytes(msg.data), msg.width, msg.height, msg.step,
                              out_width, out_height, channels)
    header = header_for(msg.encoding, ow, oh, channels, msg.width, msg.height,
                        frame_id=msg.header.frame_id,
                        sec=msg.header.stamp.sec, nsec=msg.header.stamp.nanosec)
    return header, pixels


def serve(latest, args, log, should_run=lambda: True):
    """Accept one receiver at a time and feed it the newest frame at `--rate`."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(1)
    log("listening on %s:%d" % (args.bind, args.port))
    period = 1.0 / max(args.rate, 0.1)
    while should_run():
        conn, addr = srv.accept()
        log("receiver connected from %s" % (addr,))
        conn.settimeout(10.0)
        try:
            while should_run():
                frame = latest.take()
                if frame is None:
                    threading.Event().wait(period / 4.0)
                    continue
                conn.sendall(pack_frame(frame[0], frame[1]))
                threading.Event().wait(period)
        except (OSError, socket.timeout) as exc:
            log("receiver gone (%s); waiting for another" % exc)
        finally:
            conn.close()


def main(argv=None):
    args = build_parser().parse_args(argv)

    import rclpy                       # noqa: PLC0415 -- see the module docstring
    from rclpy.node import Node
    from sensor_msgs.msg import Image

    rclpy.init()
    node = Node("camera_bridge_tx")
    log = node.get_logger().info
    latest = _Latest()
    dropped = {"encoding": None}

    def on_image(msg):
        frame = frame_from_image(msg, args.width, args.height)
        if frame is None:
            if dropped["encoding"] != msg.encoding:
                dropped["encoding"] = msg.encoding
                node.get_logger().warn(
                    "not carrying encoding %r; this bridge handles rgb8 and bgr8"
                    % msg.encoding)
            return
        latest.put(frame)

    node.create_subscription(Image, args.topic, on_image, 1)
    log("bridging %s at %.1f Hz, downscaled to %dx%d"
        % (args.topic, args.rate, args.width, args.height))
    threading.Thread(target=serve, args=(latest, args, log), daemon=True).start()
    rclpy.spin(node)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
