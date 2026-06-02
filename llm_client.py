import json
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
            self.state_desc = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse state description: {e}")

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
        self.get_logger().info(f"Queued evaluation request (Queue size: {self.query_queue.qsize()})")

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

    def _process_evaluation(self, task):
        required_aps = task["required_aps"]
        state_desc = task["state_desc"]
        odom_data = task["odom_data"]
        scan_data = task["scan_data"]
        nav_status = task["nav_status"]

        # Prepare context
        ap_descriptions = state_desc.get("ap_descriptions", {})

        terminal_success = state_desc.get("terminal_success", {})
        terminal_failure = state_desc.get("terminal_failure", {})
        terminal_section = ""
        if terminal_success.get("description") or terminal_failure.get("description"):
            terminal_section = (
                f"\nTerminal conditions (evaluate these APs precisely):\n"
                f"  SUCCESS when: {terminal_success.get('description', 'N/A')}\n"
                f"  FAILURE when: {terminal_failure.get('description', 'N/A')}\n"
            )

        # Build one line per AP: description + the current sensor value most relevant to it
        sensor_summary = {
            "position_x":        odom_data.get("position", {}).get("x", "N/A"),
            "position_y":        odom_data.get("position", {}).get("y", "N/A"),
            "linear_vel":        odom_data.get("linear_vel", "N/A"),
            "angular_vel":       odom_data.get("angular_vel", "N/A"),
            "distance_to_target": odom_data.get("distance_to_target", "N/A"),
            "min_range":         scan_data.get("min_range", "N/A"),
            "mean_range":        scan_data.get("mean_range", "N/A"),
            "close_objects":     scan_data.get("close_objects", "N/A"),
            "nav_status":        nav_status or "N/A",
        }

        ap_lines = []
        for ap in required_aps:
            desc = ap_descriptions.get(ap, "No description provided.")
            ap_lines.append(f'  "{ap}": {desc}')

        prompt = f"""You are evaluating atomic propositions for a robot skill monitor.

Skill: {state_desc.get("skill_name", "Unknown")} — {state_desc.get("description", "")}
Phase: {state_desc.get("phase", "Unknown")}
{terminal_section}
Current sensor readings:
  position_x        = {sensor_summary["position_x"]} m
  position_y        = {sensor_summary["position_y"]} m
  linear_vel        = {sensor_summary["linear_vel"]} m/s
  angular_vel       = {sensor_summary["angular_vel"]} rad/s
  distance_to_target = {sensor_summary["distance_to_target"]} m
  min_range         = {sensor_summary["min_range"]} m
  mean_range        = {sensor_summary["mean_range"]} m
  close_objects     = {sensor_summary["close_objects"]}
  nav_status        = "{sensor_summary["nav_status"]}"

Evaluate each proposition below to true or false.
Each description contains the exact rule to apply — follow it literally using the sensor values above.

{chr(10).join(ap_lines)}

Reply with ONLY a JSON object: keys are proposition names, values are booleans (true/false).
No markdown, no explanation.
"""
        self.get_logger().info(
            f"\n--- [Evaluation Queue Size: {self.query_queue.qsize()}] ---\n"
            f"Evaluating APs: {required_aps}\n"
            f"Against Current State Description: Phase={state_desc.get('phase', 'Unknown')}, Skill={state_desc.get('skill_name', 'Unknown')}\n"
            f"Sensor & Odometry Data: Odom={json.dumps(odom_data)}, Scan={json.dumps(scan_data)}, NavStatus={nav_status}"
        )

        evals = self._query_llm(prompt)
        if evals:
            # Ensure all required APs are present and boolean
            final_evals = {}
            for ap in required_aps:
                val = evals.get(ap, False)
                final_evals[ap] = bool(val)
                
            self.get_logger().info(f"Evaluation results from LLM: {json.dumps(final_evals)}")
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
