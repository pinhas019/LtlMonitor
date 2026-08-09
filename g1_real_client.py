"""Sensor evaluator for the LTL monitor against the REAL G1 (TRAV-metric-map ROS2 Humble
stack) — no Nav2, no lidar. Sibling to llm_client.py (the Isaac-Lab-sim/Nav2 evaluator);
same /ltl/required_aps -> /ltl/evaluations -> /ltl/state_description protocol, same
rule-eval-first/LLM-fallback mechanism, only the sensor subscriptions differ:

  /t265/odom/sample    (nav_msgs/Odometry)      odom + IMU-derived base orientation
  /depth_anything/points (sensor_msgs/PointCloud2) camera-derived range (no lidar)
  /path_manager/status (std_msgs/String, JSON)  planned-path/mission status (no Nav2)

See formulas_g1_real.json for the atomic propositions this feeds.
"""

import json
import re
import urllib.request
import argparse
import queue
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
import g1_sensors  # base-pose math (quat->euler, upright, min_range) — unchanged, shared with llm_client.py
from g1_real_frame import remap_optical_to_body


class G1RealClientNode(Node):
    def __init__(self, api_url: str, model: str, stuck_ticks: int = 10):
        super().__init__('ltl_g1_real_client')
        self.api_url = api_url
        self.model = model
        self.stuck_ticks = stuck_ticks

        # State storage
        self.required_aps = []
        self.state_desc = {}
        self.odom_data = {}
        self.scan_data = {}
        self.nav_data = {}
        self._blocked_streak = 0
        self.idle = True  # start idle until monitor sends APs

        # Buffer / Queue for asynchronous LLM queries — kept for parity with llm_client.py;
        # expected to stay empty since formulas_g1_real.json is fully rule-based.
        self.query_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()

        # LTL Subscriptions
        self.create_subscription(String, '/ltl/required_aps', self.aps_callback, 10)
        self.create_subscription(String, '/ltl/state_description', self.desc_callback, 10)

        # LTL Publisher
        self.eval_pub = self.create_publisher(String, '/ltl/evaluations', 10)

        # Real-robot sensor subscriptions
        self.create_subscription(Odometry, '/t265/odom/sample', self.odom_callback, 10)
        self.create_subscription(PointCloud2, '/depth_anything/points', self.points_callback, 10)
        self.create_subscription(String, '/path_manager/status', self.status_callback, 10)

        # Evaluation timer
        self.timer = self.create_timer(1.0, self.evaluate_and_publish)

        self.get_logger().info(
            f"G1 real-robot client started (model={self.model} @ {self.api_url}, "
            f"stuck_ticks={self.stuck_ticks})"
        )

    def _drain_queue(self) -> None:
        """Discard all pending evaluation tasks from the work queue."""
        drained = 0
        try:
            while True:
                self.query_queue.get_nowait()
                self.query_queue.task_done()
                drained += 1
        except queue.Empty:
            pass
        if drained:
            self.get_logger().info(f"Drained {drained} stale evaluation(s) from queue.")

    def aps_callback(self, msg: String):
        try:
            new_aps = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse required APs: {e}")
            return

        was_idle = self.idle
        self.idle = not new_aps  # idle when AP list is empty

        if not was_idle and self.idle:
            self._drain_queue()
            self.get_logger().info(
                "Monitor entered IDLE state — evaluation halted. "
                "Waiting for next skill execution."
            )
        elif was_idle and not self.idle:
            self._drain_queue()  # discard any stale items accumulated while idle
            self.get_logger().info(
                f"Monitor resumed — starting evaluation for APs: {new_aps}"
            )

        self.required_aps = new_aps

    def desc_callback(self, msg: String):
        try:
            data = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse state description: {e}")
            return

        if data.get("state") == "halt":
            self.get_logger().info(
                f"Monitor halted ({data.get('reason','')}) — shutting down evaluator."
            )
            self._drain_queue()
            rclpy.shutdown()
            return

        self.state_desc = data

    def odom_callback(self, msg: Odometry):
        """Same math as llm_client.py's odom_callback — sportmode_odom_bridge.py populates
        the same quaternion/twist layout, so quat_to_euler/base_upright carry over unchanged.
        No distance_to_target here: there's no /goal_pose on the real stack; progress comes
        from path_manager's own fields instead (see status_callback).
        """
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        z = msg.pose.pose.position.z
        q = msg.pose.pose.orientation
        roll, pitch, _yaw = g1_sensors.quat_to_euler(q.x, q.y, q.z, q.w)
        upright = g1_sensors.base_upright(roll, pitch, z)
        self.odom_data = {
            "position": {"x": round(x, 2), "y": round(y, 2)},
            "linear_vel": round(msg.twist.twist.linear.x, 2),
            "angular_vel": round(msg.twist.twist.angular.z, 2),
            "base_roll": round(roll, 3),
            "base_pitch": round(pitch, 3),
            "base_height": round(z, 3),
            "upright_flag": 1.0 if upright else 0.0,
        }

    def points_callback(self, msg: PointCloud2):
        """/depth_anything/points is in camera_color_optical_frame — see g1_real_frame.py
        (unit-tested) for the axis remap. g1_sensors.py stays generic/unchanged.
        """
        raw = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
        min_range = g1_sensors.min_range_from_points(
            remap_optical_to_body(raw), z_lo=0.1, z_hi=1.5, default=10.0
        )
        self.scan_data = {"min_range": round(min_range, 2)}

    def status_callback(self, msg: String):
        """/path_manager/status (no Nav2 — see path_manager.py::publish_status for the
        exact schema). Debounce transient blocked states into a sustained nav_stuck flag
        here (not in main.py, which evaluates conditions as instantaneous booleans every
        tick with no built-in debounce) — path_manager's per-tick state can self-recover.
        """
        try:
            data = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse path_manager status: {e}")
            return

        state = data.get("state", "waiting_inputs")
        if state in ("no_traversable", "unreachable", "no_path_found"):
            self._blocked_streak += 1
        else:
            self._blocked_streak = 0

        self.nav_data = {
            "mode": data.get("mode", "MANUAL"),
            "state": state,
            "finished": bool(data.get("finished", False)),
            "num_waypoints": int(data.get("num_waypoints", 0)),
            "current_target_idx": int(data.get("current_target_idx", 0)),
        }

    def _query_llm(self, prompt: str) -> dict:
        is_openai = "/v1" in self.api_url or "openai" in self.api_url
        if is_openai:
            endpoint = self.api_url if self.api_url.endswith("/chat/completions") else f"{self.api_url.rstrip('/')}/chat/completions"
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
        else:
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0}
            }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        req.add_header("Authorization", "Bearer dummy-key")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode('utf-8'))
                if is_openai:
                    content = result['choices'][0]['message']['content'].strip()
                    if content.startswith("```"):
                        first_nl = content.find("\n")
                        if first_nl != -1:
                            content = content[first_nl:].strip()
                        if content.endswith("```"):
                            content = content[:-3].strip()
                    return json.loads(content)
                else:
                    return json.loads(result['response'])
        except Exception as e:
            self.get_logger().error(f"LLM query failed: {e}")
            if hasattr(e, 'read'):
                try:
                    self.get_logger().error(f"Response body: {e.read().decode('utf-8')}")
                except Exception:
                    pass
            return {}

    def evaluate_and_publish(self):
        if self.idle or not self.required_aps:
            return

        snapshot = {
            "required_aps": list(self.required_aps),
            "state_desc": dict(self.state_desc),
            "odom_data": dict(self.odom_data),
            "scan_data": dict(self.scan_data),
            "nav_data": dict(self.nav_data),
            "blocked_streak": self._blocked_streak,
        }
        self.query_queue.put(snapshot)
        phase = self.state_desc.get("phase") or "—"
        self.get_logger().info(
            f"→ queued | phase={phase} | aps={len(self.required_aps)} | depth={self.query_queue.qsize()}"
        )

    def _worker_loop(self):
        while rclpy.ok():
            try:
                task = self.query_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_evaluation(task)
            except Exception as e:
                self.get_logger().error(f"Error in processing evaluation: {e}")
            finally:
                self.query_queue.task_done()

    # ------------------------------------------------------------------
    # ANSI helpers (shared across print calls)
    # ------------------------------------------------------------------
    _BOLD  = "\033[1m"
    _RESET = "\033[0m"
    _DIM   = "\033[2m"
    _CYAN  = "\033[36m"
    _GREEN = "\033[32m"
    _RED   = "\033[31m"

    _TRUE_WHEN_RE = re.compile(r'[Tt]rue when\s+(.+?)(?:\.|$)', re.IGNORECASE)

    def _rule_eval(self, desc: str, sensor_data: dict):
        m = self._TRUE_WHEN_RE.search(desc)
        if not m:
            return None
        rule = m.group(1).strip().rstrip('.')
        try:
            return bool(eval(rule, {"__builtins__": {}}, sensor_data))
        except Exception:
            return None

    def _process_evaluation(self, task):
        required_aps = task["required_aps"]
        state_desc   = task["state_desc"]
        odom_data    = task["odom_data"]
        scan_data    = task["scan_data"]
        nav_data     = task["nav_data"]
        blocked_streak = task["blocked_streak"]

        ap_descriptions  = state_desc.get("ap_descriptions", {})
        terminal_success = state_desc.get("terminal_success", {})
        terminal_failure = state_desc.get("terminal_failure", {})
        phase_info       = state_desc.get("phase_info", {})

        pos = odom_data.get("position", {})
        px  = pos.get("x", "N/A")
        py  = pos.get("y", "N/A")
        vel = odom_data.get("linear_vel", "N/A")
        rng = scan_data.get("min_range", "N/A")
        mode = nav_data.get("mode", "N/A")
        state = nav_data.get("state", "N/A")

        # Numeric dict for Python rule evaluation — safe defaults keep APs false
        # when sensors haven't published yet.
        sensor_eval = {
            "min_range":          scan_data.get("min_range", 10.0),
            "base_roll":          odom_data.get("base_roll", 0.0),
            "base_pitch":         odom_data.get("base_pitch", 0.0),
            "base_height":        odom_data.get("base_height", 1.0),
            "upright_flag":       odom_data.get("upright_flag", 1.0),
            "linear_vel":         odom_data.get("linear_vel", 0.0),
            "angular_vel":        odom_data.get("angular_vel", 0.0),
            "nav_mode":           nav_data.get("mode", "MANUAL"),
            "nav_state":          nav_data.get("state", "waiting_inputs"),
            "num_waypoints":      nav_data.get("num_waypoints", 0),
            "current_target_idx": nav_data.get("current_target_idx", 0),
            "mission_finished":   nav_data.get("finished", False),
            "nav_stuck":          blocked_streak >= self.stuck_ticks,
        }

        skill = state_desc.get("skill_name", "?")
        phase = state_desc.get("phase") or "Idle"
        B, D, R, C = self._BOLD, self._DIM, self._RESET, self._CYAN

        violations = phase_info.get("violation_count", 0)
        vlimit     = phase_info.get("violation_limit", 3)
        viol_str   = f"  {B}\033[33m⚠ {violations}/{vlimit} violations{R}" if violations > 0 else ""

        print(f"  {B}┌── Eval  [{C}{skill}{R}{B}]  phase: {C}{phase}{R}{B}  {'─' * 22}{R}")
        print(f"  │ {D}pos=({px}, {py}) m  vel={vel} m/s  min_range={rng} m{R}")
        print(f"  │ {D}nav_mode={mode}  nav_state={state}  blocked_streak={blocked_streak}/{self.stuck_ticks}{R}")
        if phase_info:
            print(f"  │ {'─' * 52}")
            invariant = phase_info.get("invariant", "")
            if invariant:
                inv_cat = phase_info.get("invariant_fault_category", "INVARIANT")
                print(f"  │ {B}\033[31mInvariant:{R}  {invariant}  {D}[{inv_cat}]{R}")
            print(f"  │ {D}Progress :{R}  {phase_info.get('progress_condition','—')}{viol_str}")
            print(f"  │ {D}Exit  →  :{R}  {phase_info.get('next_phase','?')}  when: {phase_info.get('exit_condition','—')}")
            timing = phase_info.get("timing_bounds", {})
            step_count = phase_info.get("step_count", 0)
            max_steps  = timing.get("max_steps")
            min_steps  = timing.get("min_steps")
            if max_steps is not None:
                pct = int(100 * step_count / max_steps) if max_steps else 0
                bar_filled = pct // 5
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                print(f"  │ {D}Timing   :{R}  step {step_count}/{max_steps}  [{bar}] {pct}%"
                      + (f"  {D}(min {min_steps}){R}" if min_steps else ""))

        # ── Rule-based evaluation (first pass) ──────────────────────────
        rule_evals: dict[str, bool] = {}
        llm_aps:    list[str]       = []

        for ap in required_aps:
            desc   = ap_descriptions.get(ap, "")
            result = self._rule_eval(desc, sensor_eval)
            if result is not None:
                rule_evals[ap] = result
            else:
                llm_aps.append(ap)

        # ── LLM evaluation fallback — kept for parity; expect llm_aps to be
        # empty since formulas_g1_real.json is fully rule-based.
        llm_evals: dict[str, bool] = {}
        if llm_aps:
            terminal_section = ""
            if terminal_success.get("description") or terminal_failure.get("description"):
                terminal_section = (
                    f"\nTerminal conditions:\n"
                    f"  SUCCESS when: {terminal_success.get('description','N/A')}\n"
                    f"  FAILURE when: {terminal_failure.get('description','N/A')}\n"
                )
            ap_lines = "\n".join(
                f'  "{ap}": {ap_descriptions.get(ap,"No description.")}' for ap in llm_aps
            )
            prompt = f"""You are evaluating atomic propositions for a robot skill monitor.

Skill: {skill} — {state_desc.get("description","")}
Phase: {phase}
{terminal_section}
Current sensor readings:
  position_x  = {px} m
  position_y  = {py} m
  linear_vel  = {vel} m/s
  min_range   = {rng} m
  nav_mode    = "{mode}"
  nav_state   = "{state}"

Evaluate each proposition to true or false using the sensor values above.

{ap_lines}

Reply with ONLY a JSON object. No markdown, no explanation.
"""
            raw = self._query_llm(prompt)
            llm_evals = {ap: bool(raw.get(ap, False)) for ap in llm_aps} if raw else {}

        final_evals = {**rule_evals, **llm_evals}
        for ap in required_aps:
            final_evals.setdefault(ap, False)

        print(f"  │ {'─' * 52}")
        G, RE = self._GREEN, self._RED

        def _ap_colored(ap):
            color = G if final_evals.get(ap) else RE
            return f"{color}{ap}{R}"

        rule_true  = [ap for ap in required_aps if ap in rule_evals and rule_evals[ap]]
        rule_false = [ap for ap in required_aps if ap in rule_evals and not rule_evals[ap]]
        if rule_evals:
            print(f"  │ {B}⚡ Rule-based (instant){R}")
            print(f"  │   {D}TRUE :{R}  {'  '.join(_ap_colored(a) for a in rule_true)  or '—'}")
            print(f"  │   {D}FALSE:{R}  {'  '.join(_ap_colored(a) for a in rule_false) or '—'}")

        if llm_aps:
            llm_true  = [ap for ap in llm_aps if final_evals.get(ap)]
            llm_false = [ap for ap in llm_aps if not final_evals.get(ap)]
            print(f"  │ {B}🤖 LLM-evaluated (queried){R}")
            print(f"  │   {D}TRUE :{R}  {'  '.join(_ap_colored(a) for a in llm_true)  or '—'}")
            print(f"  │   {D}FALSE:{R}  {'  '.join(_ap_colored(a) for a in llm_false) or '—'}")

        print(f"  {B}└{'─' * 50}{R}")
        print()

        msg = String()
        msg.data = json.dumps(final_evals)
        self.eval_pub.publish(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', '--ollama-url', dest='api_url', default='http://192.168.140.111/developer-api/v1')
    parser.add_argument('--model', default='Gemma4')
    parser.add_argument('--stuck-ticks', type=int, default=10,
                         help='Consecutive no_traversable/unreachable/no_path_found ticks before nav_stuck fires (default: 10 @ ~1Hz evaluation timer)')
    args = parser.parse_args()

    rclpy.init()
    node = G1RealClientNode(args.api_url, args.model, stuck_ticks=args.stuck_ticks)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
