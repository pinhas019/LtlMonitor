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
from sensor_msgs.msg import LaserScan
from action_msgs.msg import GoalStatusArray
from geometry_msgs.msg import PoseStamped

class LlmClientNode(Node):
    def __init__(self, api_url: str, model: str):
        super().__init__('ltl_llm_client')
        self.api_url = api_url
        self.model = model

        # State storage
        self.required_aps = []
        self.state_desc = {}
        self.odom_data = {}
        self.scan_data = {}
        self.nav_status = ""
        self.idle = True  # start idle until monitor sends APs

        # Buffer / Queue for asynchronous Ollama queries
        self.query_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()

        # LTL Subscriptions
        self.create_subscription(String, '/ltl/required_aps', self.aps_callback, 10)
        self.create_subscription(String, '/ltl/state_description', self.desc_callback, 10)

        # LTL Publisher
        self.eval_pub = self.create_publisher(String, '/ltl/evaluations', 10)

        # Sensor Subscriptions
        self.create_subscription(Odometry, '/odom', self.odom_callback, 10)
        self.create_subscription(LaserScan, '/scan', self.scan_callback, 10)
        self.create_subscription(GoalStatusArray, '/navigate_to_pose/_action/status', self.nav_status_callback, 10)
        self.create_subscription(PoseStamped, '/goal_pose', self.goal_callback, 10)

        # Target Tracking State
        self.target_x = 3.0
        self.target_y = 2.0

        # Evaluation timer
        self.timer = self.create_timer(1.0, self.evaluate_and_publish)
        
        self.get_logger().info(f"LLM Client started using model: {self.model} at {self.api_url}")


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
            # Transition → idle
            self._drain_queue()
            self.get_logger().info(
                "Monitor entered IDLE state — evaluation halted. "
                "Waiting for next skill execution."
            )
        elif was_idle and not self.idle:
            # Transition → active
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
                f"Monitor halted ({data.get('reason','')}) — shutting down LLM client."
            )
            self._drain_queue()
            rclpy.shutdown()
            return

        self.state_desc = data

    def odom_callback(self, msg: Odometry):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        self.odom_data = {
            "position": {"x": round(x, 2), "y": round(y, 2)},
            "linear_vel": round(msg.twist.twist.linear.x, 2),
            "angular_vel": round(msg.twist.twist.angular.z, 2),
            "distance_to_target": round(((self.target_x - x)**2 + (self.target_y - y)**2)**0.5, 2)
        }

    def goal_callback(self, msg: PoseStamped):
        self.target_x = msg.pose.position.x
        self.target_y = msg.pose.position.y

    def scan_callback(self, msg: LaserScan):
        valid_ranges = [r for r in msg.ranges if r > 0.0 and r != float('inf')]
        if not valid_ranges:
            self.scan_data = {
                "min_range": 10.0,
                "mean_range": 10.0,
                "close_objects": 0
            }
            return
        self.scan_data = {
            "min_range": round(min(valid_ranges), 2),
            "mean_range": round(sum(valid_ranges)/len(valid_ranges), 2),
            "close_objects": len([r for r in valid_ranges if r < 1.0])
        }

    def nav_status_callback(self, msg: GoalStatusArray):
        if msg.status_list:
            status = msg.status_list[-1].status
            status_map = {
                1: "accepted", 2: "executing", 3: "canceling",
                4: "succeeded", 5: "canceled", 6: "aborted"
            }
            self.nav_status = status_map.get(status, f"unknown({status})")

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

        # Snapshot of current state for queuing
        snapshot = {
            "required_aps": list(self.required_aps),
            "state_desc": dict(self.state_desc),
            "odom_data": dict(self.odom_data),
            "scan_data": dict(self.scan_data),
            "nav_status": self.nav_status
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

    # Matches "True when <rule>" in AP descriptions — used for rule-based eval
    _TRUE_WHEN_RE = re.compile(r'[Tt]rue when\s+(.+?)(?:\.|$)', re.IGNORECASE)

    def _rule_eval(self, desc: str, sensor_data: dict):
        """
        Extract the 'True when <expr>' rule from an AP description and evaluate
        it directly against sensor_data.  Returns bool on success, None if the
        rule cannot be parsed or evaluated (→ fall back to LLM).
        """
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
        nav_status   = task["nav_status"]

        ap_descriptions  = state_desc.get("ap_descriptions", {})
        terminal_success = state_desc.get("terminal_success", {})
        terminal_failure = state_desc.get("terminal_failure", {})
        phase_info       = state_desc.get("phase_info", {})

        # ── Build sensor data for display (strings) and rule eval (numbers) ──
        pos = odom_data.get("position", {})
        px  = pos.get("x", "N/A")
        py  = pos.get("y", "N/A")
        vel = odom_data.get("linear_vel",        "N/A")
        ang = odom_data.get("angular_vel",        "N/A")
        dist= odom_data.get("distance_to_target", "N/A")
        rng = scan_data.get("min_range",          "N/A")
        rng_mean = scan_data.get("mean_range",    "N/A")
        close    = scan_data.get("close_objects", "N/A")
        nav      = nav_status or "none"

        # Numeric dict for Python rule evaluation — safe defaults keep APs false
        # when sensors haven't published yet (e.g. dist=9999 → never near_target)
        sensor_eval = {
            "position_x":        pos.get("x",     0.0),
            "position_y":        pos.get("y",     0.0),
            "linear_vel":        odom_data.get("linear_vel",        0.0),
            "angular_vel":       odom_data.get("angular_vel",       0.0),
            "distance_to_target":odom_data.get("distance_to_target",9999.0),
            "min_range":         scan_data.get("min_range",         10.0),
            "mean_range":        scan_data.get("mean_range",        10.0),
            "close_objects":     int(scan_data.get("close_objects", 0)),
            "nav_status":        nav_status or "",
        }

        skill = state_desc.get("skill_name", "?")
        phase = state_desc.get("phase") or "Idle"
        B, D, R, C = self._BOLD, self._DIM, self._RESET, self._CYAN

        violations = phase_info.get("violation_count", 0)
        vlimit     = phase_info.get("violation_limit", 3)
        viol_str   = f"  {B}\033[33m⚠ {violations}/{vlimit} violations{R}" if violations > 0 else ""

        # ── Pre-query display block ─────────────────────────────────────
        print(f"  {B}┌── Eval  [{C}{skill}{R}{B}]  phase: {C}{phase}{R}{B}  {'─' * 22}{R}")
        print(f"  │ {D}pos=({px}, {py}) m  vel={vel} m/s  dist={dist} m  min_range={rng} m{R}")
        print(f"  │ {D}nav_status={nav}  close_objects={close}{R}")
        if phase_info:
            print(f"  │ {'─' * 52}")
            print(f"  │ {D}Progress :{R}  {phase_info.get('progress_condition','—')}{viol_str}")
            print(f"  │ {D}Exit  →  :{R}  {phase_info.get('next_phase','?')}  when: {phase_info.get('exit_condition','—')}")

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

        # ── LLM evaluation (fallback for non-rule APs) ───────────────────
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
  position_x         = {px} m
  position_y         = {py} m
  linear_vel         = {vel} m/s
  angular_vel        = {ang} rad/s
  distance_to_target = {dist} m
  min_range          = {rng} m
  mean_range         = {rng_mean} m
  close_objects      = {close}
  nav_status         = "{nav}"

Evaluate each proposition to true or false using the sensor values above.

{ap_lines}

Reply with ONLY a JSON object. No markdown, no explanation.
"""
            raw = self._query_llm(prompt)
            llm_evals = {ap: bool(raw.get(ap, False)) for ap in llm_aps} if raw else {}

        # ── Merge and publish ────────────────────────────────────────────
        final_evals = {**rule_evals, **llm_evals}
        # Ensure every required AP is present (default False if LLM failed)
        for ap in required_aps:
            final_evals.setdefault(ap, False)

        # ── Result display ───────────────────────────────────────────────
        print(f"  │ {'─' * 52}")
        G, RE = self._GREEN, self._RED
        def _ap_tag(ap):
            tag = "R" if ap in rule_evals else "L"
            color = G if final_evals[ap] else RE
            return f"{color}{ap}[{tag}]{R}"

        true_aps  = [ap for ap in required_aps if final_evals[ap]]
        false_aps = [ap for ap in required_aps if not final_evals[ap]]
        print(f"  │ {D}TRUE :{R}  {'  '.join(_ap_tag(a) for a in true_aps)  or '—'}")
        print(f"  │ {D}FALSE:{R}  {'  '.join(_ap_tag(a) for a in false_aps) or '—'}")
        if llm_aps:
            print(f"  │ {D}(rule:{len(rule_evals)}  llm:{len(llm_evals)}){R}")
        print(f"  {B}└{'─' * 50}{R}")
        print()

        msg = String()
        msg.data = json.dumps(final_evals)
        self.eval_pub.publish(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', '--ollama-url', dest='api_url', default='http://192.168.140.111/developer-api/v1')
    parser.add_argument('--model', default='Gemma4')
    args = parser.parse_args()

    rclpy.init()
    node = LlmClientNode(args.api_url, args.model)
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__ == '__main__':
    main()
