"""ROS 2 shell around G1Sim: a Unitree G1 walking under real MuJoCo physics.

Everything that can be tested without ROS lives in `sim/g1sim/` and is tested in
`sim/tests/`; this file only moves data between that core and the ROS graph.

Subscribes
    /cmd_vel        geometry_msgs/Twist     velocity command; zeroed after CMD_TIMEOUT_S
    /goal_pose      geometry_msgs/PoseStamped  moves the goal marker
    /g1/reset       std_msgs/String         a scenario as JSON (sim/g1sim/scenario.py)
Publishes
    /odom           nav_msgs/Odometry       true pose, MEASURED twist (base frame)
    /scan           sensor_msgs/LaserScan   planar scan of walls and obstacles
    /target_pose    geometry_msgs/PoseStamped
    /visualization_marker  visualization_msgs/Marker
    /g1/reset_done  std_msgs/Bool           true once the scenario is running; false if
                                            it was rejected
    TF odom -> base_link

On reset the bridge rewrites the Nav2 map from the same scenario into --map-dir and
asks map_server to reload it, so the planner and the scan always agree.

    python3 mujoco_ros_bridge.py --scenario scenarios/clear.json --map-dir /maps
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from tf2_ros import TransformBroadcaster
from visualization_msgs.msg import Marker

from g1sim import G1Sim, ScenarioError, from_dict, load
from g1sim.occupancy import write_map

CMD_TIMEOUT_S = 0.5
SCAN_RAYS = 360
SCAN_HEIGHT_M = 0.3
SCAN_MAX_M = 10.0
MAP_RESOLUTION_M = 0.05


class MujocoRosBridge(Node):
    def __init__(self, scenario_path: str, map_dir: str, publish_hz: float,
                 realtime: float, assets: str | None):
        super().__init__("mujoco_ros_bridge")
        self.map_dir = Path(map_dir)
        self.realtime = realtime
        self.sim = G1Sim(assets)
        self.lock = threading.Lock()

        self._cmd = (0.0, 0.0, 0.0)
        self._cmd_at = 0.0
        self._pending_reset: str | None = None

        scenario = load(scenario_path)
        self.sim.reset(scenario)
        self._write_map(scenario)

        self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, 10)
        self.create_subscription(PoseStamped, "/goal_pose", self._on_goal, 10)
        self.create_subscription(String, "/g1/reset", self._on_reset, 10)
        self.odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self.scan_pub = self.create_publisher(LaserScan, "/scan", 10)
        self.target_pub = self.create_publisher(PoseStamped, "/target_pose", 10)
        self.marker_pub = self.create_publisher(Marker, "/visualization_marker", 10)
        self.reset_done_pub = self.create_publisher(Bool, "/g1/reset_done", 10)
        self.tf = TransformBroadcaster(self)
        self._load_map_client = self._make_load_map_client()

        self.create_timer(1.0 / publish_hz, self._publish)
        self._thread = threading.Thread(target=self._sim_loop, daemon=True)
        self._thread.start()
        self.get_logger().info(
            f"G1 walking in scenario {scenario.name!r} (real-time x{realtime})")

    # ------------------------------------------------------------------ inputs

    def _on_cmd_vel(self, msg: Twist) -> None:
        self._cmd = (msg.linear.x, msg.linear.y, msg.angular.z)
        self._cmd_at = time.monotonic()

    def _on_goal(self, msg: PoseStamped) -> None:
        with self.lock:
            self.sim.set_goal(msg.pose.position.x, msg.pose.position.y)

    def _on_reset(self, msg: String) -> None:
        # Applied by the sim thread between control steps, never mid-step.
        self._pending_reset = msg.data

    # ------------------------------------------------------------------ sim loop

    def _sim_loop(self) -> None:
        period = self.sim.config.control_dt / self.realtime
        next_at = time.monotonic()
        while rclpy.ok():
            request, self._pending_reset = self._pending_reset, None
            if request is not None:
                self._apply_reset(request)
                next_at = time.monotonic()
            fresh = time.monotonic() - self._cmd_at <= CMD_TIMEOUT_S
            with self.lock:
                self.sim.set_command(*(self._cmd if fresh else (0.0, 0.0, 0.0)))
                self.sim.step(control_steps=1)
            next_at += period
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_at = time.monotonic()      # running behind: do not try to catch up

    def _apply_reset(self, request: str) -> None:
        try:
            scenario = from_dict(json.loads(request))
        except (ValueError, ScenarioError) as e:
            self.get_logger().error(f"Rejected reset: {e}")
            self.reset_done_pub.publish(Bool(data=False))
            return
        with self.lock:
            self.sim.reset(scenario)
        self._cmd = (0.0, 0.0, 0.0)
        self._write_map(scenario)
        self._reload_map()
        self.get_logger().info(f"Reset to scenario {scenario.name!r} (seed {scenario.seed})")
        self.reset_done_pub.publish(Bool(data=True))

    # ------------------------------------------------------------------ map

    def _write_map(self, scenario) -> None:
        write_map(scenario, self.map_dir, resolution=MAP_RESOLUTION_M)

    def _make_load_map_client(self):
        try:
            from nav2_msgs.srv import LoadMap
        except ImportError:
            self.get_logger().warn("nav2_msgs missing: layouts cannot change at run time")
            return None
        return self.create_client(LoadMap, "/map_server/load_map")

    def _reload_map(self) -> None:
        """Ask map_server for the new map. Best effort: a layout that never changes
        needs no reload, and map_server loads the startup map itself."""
        if self._load_map_client is None or not self._load_map_client.service_is_ready():
            self.get_logger().warn("map_server load_map unavailable; map not reloaded")
            return
        from nav2_msgs.srv import LoadMap
        request = LoadMap.Request()
        request.map_url = str(self.map_dir / "map.yaml")
        self._load_map_client.call_async(request)

    # ------------------------------------------------------------------ outputs

    def _publish(self) -> None:
        with self.lock:
            x, y, z, _yaw = self.sim.base_pose()
            qw, qx, qy, qz = self.sim.base_quat()
            linear = self.sim.linear_velocity_body()
            angular = self.sim.angular_velocity_body()
            ranges = self.sim.ranges(count=SCAN_RAYS, scan_height=SCAN_HEIGHT_M,
                                     max_range=SCAN_MAX_M)
            goal = self.sim.data.mocap_pos[0].copy()
        now = self.get_clock().now().to_msg()

        transform = TransformStamped()
        transform.header.stamp = now
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_link"
        transform.transform.translation.x = x
        transform.transform.translation.y = y
        transform.transform.translation.z = z
        transform.transform.rotation.w = float(qw)
        transform.transform.rotation.x = float(qx)
        transform.transform.rotation.y = float(qy)
        transform.transform.rotation.z = float(qz)
        self.tf.sendTransform(transform)

        odom = Odometry()
        odom.header.stamp = now
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.position.z = z
        odom.pose.pose.orientation = transform.transform.rotation
        odom.twist.twist.linear.x = float(linear[0])
        odom.twist.twist.linear.y = float(linear[1])
        odom.twist.twist.linear.z = float(linear[2])
        odom.twist.twist.angular.x = float(angular[0])
        odom.twist.twist.angular.y = float(angular[1])
        odom.twist.twist.angular.z = float(angular[2])
        self.odom_pub.publish(odom)

        scan = LaserScan()
        scan.header.stamp = now
        scan.header.frame_id = "base_link"
        scan.angle_min = -math.pi
        scan.angle_max = math.pi - 2.0 * math.pi / SCAN_RAYS
        scan.angle_increment = 2.0 * math.pi / SCAN_RAYS
        scan.range_min = 0.05
        scan.range_max = SCAN_MAX_M
        scan.ranges = [float(r) for r in ranges]
        self.scan_pub.publish(scan)

        target = PoseStamped()
        target.header.stamp = now
        target.header.frame_id = "map"
        target.pose.position.x = float(goal[0])
        target.pose.position.y = float(goal[1])
        target.pose.orientation.w = 1.0
        self.target_pub.publish(target)

        marker = Marker()
        marker.header = target.header
        marker.ns, marker.id = "target", 0
        marker.type, marker.action = Marker.CYLINDER, Marker.ADD
        marker.pose = target.pose
        marker.scale.x = marker.scale.y = 0.3
        marker.scale.z = 0.05
        marker.color.g, marker.color.a = 0.8, 0.7
        self.marker_pub.publish(marker)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scenario", default="scenarios/clear.json",
                        help="scenario to start in; /g1/reset switches at run time")
    parser.add_argument("--map-dir", default="/maps",
                        help="where the Nav2 map is written (shared with the nav2 container)")
    parser.add_argument("--publish-hz", type=float, default=20.0)
    parser.add_argument("--realtime", type=float, default=1.0,
                        help="simulated seconds per wall second")
    parser.add_argument("--assets", default=None, help="Unitree assets (else $G1SIM_ASSETS)")
    args, ros_args = parser.parse_known_args(argv)

    rclpy.init(args=ros_args)
    bridge = MujocoRosBridge(args.scenario, args.map_dir, args.publish_hz,
                             args.realtime, args.assets)
    try:
        rclpy.spin(bridge)
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
