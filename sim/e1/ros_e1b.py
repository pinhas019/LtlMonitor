"""E1b over real ROS 2: the evaluator and the monitor run as their own processes, as
deployed, and learn everything from DDS topics.

    python sim/e1/ros_e1b.py --seeds 0-19 --workers 4 --out e1b_ros.jsonl

Needs a ROS 2 Humble Python (RoboStack works: see sim/e1/README.md) with Spot and MuJoCo.

Per worker, three processes on their own ROS_DOMAIN_ID:

  evaluator   python -m skill_monitor.backend.evaluator_node
                  --adapter sim/e1/carry/mujoco_carry.json --clock ros  (use_sim_time)
  monitor     python -m skill_monitor.backend.monitor_node
                  --formulas-file <the arm's spec> --passive
  driver      this file: G1Sim, the navigator, the open-loop task executor, and the
              perception stand-in. Publishes /clock, /odom (nav_msgs/Odometry), /scan
              (sensor_msgs/LaserScan), /object/pose (geometry_msgs/PointStamped), /goal_pose
              (geometry_msgs/PoseStamped), /task and /task/status (std_msgs/String),
              /monitor/tick and /monitor/command; subscribes to /monitor/verdict and
              /monitor/status only.

The episode logic is run_e1b.play_episode, unchanged: only the transport differs
(`RosLink` here, `run_e1b.InProcess` there). Ground truth -- the simulator's own state --
never leaves the driver; it is written to the record and nowhere else.

**Lockstep, faster than real time.** Simulated time is published on /clock and the
evaluator measures freshness on it. After each tick the driver waits for the monitor's
verdict for that tick before simulating the next second, so a run is as fast as the
nodes answer and the order of events is the simulated one. A verdict that does not come
within `--verdict-timeout` wall seconds is counted in the record (`verdict_timeouts`), never
silently skipped; while the monitor reports itself idle (it went quiet after a terminal
state, --passive) no verdict is expected.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, HERE / "carry", ROOT / "sim", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

POLICIES = ("off", "detect", "recover")
SENSOR_SETTLE_S = 0.01           # wall time for the acknowledged batch to be folded
DOMAIN_BASE = 20


# ============================================================================ the link

class RosLink:
    """run_e1b.play_episode's transport over real rclpy publishers and subscribers."""

    def __init__(self, node, *, verdict_timeout: float = 2.0, episode: int = 0):
        from builtin_interfaces.msg import Time
        from geometry_msgs.msg import PointStamped, PoseStamped
        from nav_msgs.msg import Odometry
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import LaserScan
        from std_msgs.msg import String

        self.node = node
        self.Time, self.String = Time, String
        self.Odometry, self.LaserScan = Odometry, LaserScan
        self.PointStamped, self.PoseStamped, self.Clock = PointStamped, PoseStamped, Clock
        self.verdict_timeout = verdict_timeout
        self.t0 = float(episode + 1)            # a new clock epoch per episode
        self.t = 0.0
        self.stats = {"transport": "ros2", "verdict_timeouts": 0, "verdict_wait_s": 0.0,
                      "stale_verdicts_dropped": 0}

    # -- plumbing
    def _stamp(self, t: float):
        sec = int(t)
        return self.Time(sec=sec, nanosec=int(round((t - sec) * 1e9)) % 1_000_000_000)

    def _spin(self, wall_s: float) -> None:
        end = time.monotonic() + wall_s
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            self.node.exe.spin_once(timeout_sec=left)

    # -- the interface play_episode uses
    def begin(self, task_json: str) -> None:
        self.node.verdicts.clear()
        self.clock(0.0)
        self.command("reset")
        self.task(task_json)

    def clock(self, t: float) -> None:
        self.t = t
        self.node.pub["/clock"].publish(self.Clock(clock=self._stamp(t)))

    def goal(self, x: float, y: float) -> None:
        msg = self.PoseStamped()
        msg.header.frame_id, msg.header.stamp = "odom", self._stamp(self.t)
        msg.pose.position.x, msg.pose.position.y = float(x), float(y)
        msg.pose.orientation.w = 1.0
        self.node.pub["/goal_pose"].publish(msg)

    def odom(self, sim) -> None:
        x, y, z, _ = sim.reported_pose()
        qw, qx, qy, qz = sim.base_quat()
        v, w = sim.linear_velocity_body(), sim.angular_velocity_body()
        msg = self.Odometry()
        msg.header.frame_id, msg.child_frame_id = "odom", "base_link"
        msg.header.stamp = self._stamp(self.t)
        p, o = msg.pose.pose.position, msg.pose.pose.orientation
        p.x, p.y, p.z = float(x), float(y), float(z)
        o.x, o.y, o.z, o.w = float(qx), float(qy), float(qz), float(qw)
        lin, ang = msg.twist.twist.linear, msg.twist.twist.angular
        lin.x, lin.y, lin.z = (float(c) for c in v)
        ang.x, ang.y, ang.z = (float(c) for c in w)
        self.node.pub["/odom"].publish(msg)

    def object(self, x: float, y: float, z: float) -> None:
        msg = self.PointStamped()
        msg.header.frame_id, msg.header.stamp = "odom", self._stamp(self.t)
        msg.point.x, msg.point.y, msg.point.z = float(x), float(y), float(z)
        self.node.pub["/object/pose"].publish(msg)

    def scan(self, ranges) -> None:
        import math
        n = len(ranges)
        msg = self.LaserScan()
        msg.header.frame_id, msg.header.stamp = "base_link", self._stamp(self.t)
        msg.angle_min, msg.angle_increment = -math.pi, 2.0 * math.pi / n
        msg.angle_max = msg.angle_min + msg.angle_increment * (n - 1)
        msg.range_min, msg.range_max = 0.05, 10.0
        msg.ranges = [float(r) for r in ranges]
        self.node.pub["/scan"].publish(msg)

    def task(self, task_json: str) -> None:
        self.node.pub["/task"].publish(self.String(data=task_json))

    def task_status(self, status: str) -> None:
        self.node.pub["/task/status"].publish(self.String(data=status))

    def command(self, name: str) -> None:
        from skill_monitor.core import api
        self.node.pub[api.COMMAND].publish(
            self.String(data=json.dumps(api.build_command(command=name))))
        self._spin(0.05)                  # both nodes act on it before the next message

    def tick(self, seq: int, t: float):
        from skill_monitor.core import api
        # The tick closes the evaluator's window, so this second's sensor messages should
        # be in it: give its executor a moment to take them first. Topics are not ordered
        # with respect to one another -- on the robot either -- so under load a message
        # published just before the tick can still be folded into the next one. Waiting
        # for DDS acknowledgements would close that gap but costs a heartbeat period per
        # tick; the parity check against the in-process run measures what is left.
        self._spin(SENSOR_SETTLE_S)
        payload = api.build_tick(seq=seq, t=round(t, 3), tick_hz=1.0, t0=self.t0,
                                 mode="replay")
        # Nothing received before this tick can be its verdict. What is pending is a
        # late duplicate of an earlier one -- possibly the previous episode's, whose
        # `seq` this episode reuses -- and must not be read as this tick's answer.
        self.stats["stale_verdicts_dropped"] += len(self.node.verdicts)
        self.node.verdicts.clear()
        self.node.pub[api.TICK].publish(self.String(data=json.dumps(payload)))
        start = time.monotonic()
        while seq not in self.node.verdicts:
            waited = time.monotonic() - start
            if self.node.monitor_state == "idle" and waited > 0.02:
                break                     # a passive monitor after a terminal says nothing
            if waited > self.verdict_timeout:
                self.stats["verdict_timeouts"] += 1
                break
            self.node.exe.spin_once(timeout_sec=0.005)
        self.stats["verdict_wait_s"] = round(
            self.stats["verdict_wait_s"] + time.monotonic() - start, 3)
        return self.node.verdicts.pop(seq, None)

    def end(self) -> None:
        pass


def make_driver_node():
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from geometry_msgs.msg import PointStamped, PoseStamped
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import String

    from skill_monitor.core import api

    node = Node("e1b_driver")
    reliable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
    node.pub = {
        "/clock": node.create_publisher(Clock, "/clock", reliable),
        "/odom": node.create_publisher(Odometry, "/odom", reliable),
        "/scan": node.create_publisher(LaserScan, "/scan", reliable),
        "/object/pose": node.create_publisher(PointStamped, "/object/pose", reliable),
        "/goal_pose": node.create_publisher(PoseStamped, "/goal_pose", reliable),
        "/task": node.create_publisher(String, "/task", reliable),
        "/task/status": node.create_publisher(String, "/task/status", reliable),
        api.TICK: node.create_publisher(String, api.TICK, reliable),
        api.COMMAND: node.create_publisher(String, api.COMMAND, reliable),
    }
    node.verdicts, node.monitor_state = {}, None

    def on_verdict(msg):
        try:
            v = json.loads(msg.data)
        except ValueError:
            return
        if isinstance(v.get("seq"), int):
            node.verdicts[v["seq"]] = v

    def on_status(msg):
        try:
            node.monitor_state = json.loads(msg.data).get("state")
        except ValueError:
            pass

    node.create_subscription(String, api.VERDICT, on_verdict, reliable)
    latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(String, api.MONITOR_STATUS, on_status, latched)
    node.exe = SingleThreadedExecutor()
    node.exe.add_node(node)
    return node


# ======================================================================= one worker

def _die_with_parent():
    """In the child: SIGTERM when the worker that started it dies, however it dies, so a
    crashed worker cannot leave a monitor answering ticks on its domain."""
    import ctypes
    import signal
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG


def _launch_nodes(arm: str, domain: int, logdir: Path):
    import run_e1b
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain), ROS_LOCALHOST_ONLY="1",
               PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
    py = sys.executable
    spec = ROOT / "skill_monitor" / "specs" / run_e1b.ARMS[arm]
    evaluator = subprocess.Popen(
        [py, "-m", "skill_monitor.backend.evaluator_node",
         "--adapter", str(run_e1b.DESCRIPTOR), "--clock", "ros",
         "--api-url", "http://127.0.0.1:9/unused", "--model", "none",
         "--ros-args", "-p", "use_sim_time:=true", "--log-level", "warn"],
        env=env, cwd=str(ROOT), stdout=open(logdir / "evaluator.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT, preexec_fn=_die_with_parent)
    monitor = subprocess.Popen(
        [py, "-m", "skill_monitor.backend.monitor_node", "--formulas-file", str(spec),
         "--passive", "--changes-only", "--output-dir", str(logdir / "monitor_out")],
        env=env, cwd=str(ROOT), stdout=open(logdir / "monitor.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT, preexec_fn=_die_with_parent)
    return [evaluator, monitor]


def _assert_domain_empty(node, domain: int, settle_s: float = 2.0) -> None:
    """Refuse a domain where a monitor or evaluator is already running: its verdicts
    would be indistinguishable from ours."""
    from skill_monitor.core import api
    end = time.monotonic() + settle_s
    while time.monotonic() < end:
        node.exe.spin_once(timeout_sec=0.1)
    others = node.count_publishers(api.VERDICT) + node.count_subscribers(api.TICK)
    if others:
        raise RuntimeError(f"ROS_DOMAIN_ID {domain} already has {others} monitor-side "
                           f"endpoints; stop them or pick another domain")


def _wait_ready(node, timeout: float = 60.0) -> None:
    """Until the evaluator listens to the sensors and both nodes to the tick -- exactly
    one evaluator and one monitor, nothing else answering on this domain."""
    from skill_monitor.core import api
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        node.exe.spin_once(timeout_sec=0.1)
        if (node.count_subscribers("/odom") >= 1 and node.count_subscribers("/object/pose") >= 1
                and node.count_subscribers(api.TICK) >= 2
                and node.count_publishers(api.VERDICT) >= 1 and node.monitor_state):
            node.exe.spin_once(timeout_sec=1.0)
            if node.count_publishers(api.VERDICT) != 1 or node.count_subscribers(api.TICK) != 2:
                raise RuntimeError("more than one monitor or evaluator on this domain")
            return
    raise RuntimeError("evaluator/monitor did not come up; see the worker's logs")


def worker(items_path: str, out_path: str, domain: int, logdir: str,
           verdict_timeout: float) -> int:
    os.environ["ROS_DOMAIN_ID"], os.environ["ROS_LOCALHOST_ONLY"] = str(domain), "1"
    import spot  # noqa: F401  -- the real one, imported before anything could shadow it
    import rclpy
    import run_e1b
    from g1sim import G1Sim

    items = json.loads(Path(items_path).read_text(encoding="utf-8"))
    arms = {i["arm"] for i in items}
    assert len(arms) == 1, "a worker runs one arm"
    logdir = Path(logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    node = make_driver_node()
    procs = []
    try:
        _assert_domain_empty(node, domain)
        procs = _launch_nodes(arms.pop(), domain, logdir)
        _wait_ready(node)
        sim = G1Sim()
        with open(out_path, "a", encoding="utf-8") as fh:
            for k, item in enumerate(items):
                link = RosLink(node, verdict_timeout=verdict_timeout, episode=k)
                rec = run_e1b.play_episode(item, sim, link)
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                fh.flush()
                print(f"[domain {domain}] {rec['episode_id']} success={rec['success']} "
                      f"wall={rec['timing']['wall_s']}s "
                      f"timeouts={rec['timing']['verdict_timeouts']}", flush=True)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


# ========================================================================= the sweep

def main(argv=None) -> int:
    from task import FAMILIES, generate
    from g1sim.generator import parse_seeds
    import run_e1b

    parser = argparse.ArgumentParser(description="Run E1b over real ROS 2.")
    parser.add_argument("--families", nargs="+", default=list(FAMILIES), choices=FAMILIES)
    parser.add_argument("--seeds", default="0-19")
    parser.add_argument("--arms", nargs="+", default=list(run_e1b.ARMS),
                        choices=list(run_e1b.ARMS))
    parser.add_argument("--policies", nargs="+", default=list(POLICIES), choices=POLICIES)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--perfect-perception", action="store_true")
    parser.add_argument("--verdict-timeout", type=float, default=2.0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--worker", nargs=3, metavar=("ITEMS", "DOMAIN", "LOGDIR"),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker:
        items, domain, logdir = args.worker
        return worker(items, args.out, int(domain), logdir, args.verdict_timeout)

    out = Path(args.out)
    parts = sorted(out.parent.glob(out.name + ".part*"))
    done = set()
    for f in [out, *parts]:
        if f.exists():
            done |= {json.loads(line)["episode_id"]
                     for line in f.read_text(encoding="utf-8").splitlines() if line.strip()}
    perception = {"noise_m": 0.0, "miss": 0.0} if args.perfect_perception else {}
    work = {arm: [] for arm in args.arms}
    for family in args.families:
        for seed in parse_seeds(args.seeds):
            task = generate(family, seed)
            for arm in args.arms:
                for policy in args.policies:
                    if arm in run_e1b.CLOSED_LOOP_ARMS and policy != "off":
                        continue                 # its executor decides; nothing else acts
                    if f"{arm}-{policy}-{task['name']}" not in done:
                        work[arm].append({"task": task, "arm": arm, "policy": policy,
                                          **perception})
    total = sum(map(len, work.values()))
    print(f"{total} episodes to run over ROS 2 ({len(done)} already done)", flush=True)
    tmp = out.parent / f"{out.name}.work"
    tmp.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    for arm, items in work.items():
        if not items:
            continue
        procs = []
        for w in range(min(args.workers, len(items))):
            chunk = items[w::args.workers]
            items_path = tmp / f"{arm}_{w}.json"
            items_path.write_text(json.dumps(chunk), encoding="utf-8")
            part = out.parent / f"{out.name}.part{w}"
            procs.append(subprocess.Popen(
                [sys.executable, __file__, "--out", str(part),
                 "--verdict-timeout", str(args.verdict_timeout),
                 "--worker", str(items_path), str(DOMAIN_BASE + w), str(tmp / f"{arm}_{w}")]))
        codes = [p.wait() for p in procs]
        print(f"{arm}: {len(items)} episodes, exit codes {codes}, "
              f"{(time.monotonic() - t0) / 60:.1f} min so far", flush=True)
        if any(codes):
            print(f"worker logs in {tmp}", flush=True)
            return 1
    with out.open("a", encoding="utf-8") as fh:
        for part in sorted(out.parent.glob(out.name + ".part*")):
            fh.write(part.read_text(encoding="utf-8"))
            part.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
