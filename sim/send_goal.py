import time
import sys
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped

class GoalSender(Node):
    def __init__(self):
        super().__init__('goal_sender')
        self._action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self._goal_pub = self.create_publisher(PoseStamped, '/goal_pose', 10)

    def send_goal(self, x, y):
        self.get_logger().info('Waiting for action server...')
        self._action_client.wait_for_server()
        
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)
        goal_msg.pose.pose.orientation.w = 1.0
        
        self.get_logger().info(f'Sending goal to ({x}, {y})...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        
        # Publish to /goal_pose as well for visualizer & bridge target update
        pose_msg = PoseStamped()
        pose_msg.header = goal_msg.pose.header
        pose_msg.pose = goal_msg.pose.pose
        self._goal_pub.publish(pose_msg)

def main(args=None):
    rclpy.init(args=args)
    sender = GoalSender()
    
    # Check if arguments are provided
    if len(sys.argv) >= 3:
        try:
            x = float(sys.argv[1])
            y = float(sys.argv[2])
            sender.send_goal(x, y)
            start_time = time.time()
            while rclpy.ok() and (time.time() - start_time) < 2.0:
                rclpy.spin_once(sender, timeout_sec=0.1)
        except ValueError:
            print("Usage: python3 send_goal.py [x y]")
    else:
        if sys.stdin.isatty():
            print("Nav2 Goal Sender — type 'x y' to send a goal, 'q' to quit.")
            try:
                while rclpy.ok():
                    try:
                        raw = input("Goal (x y) > ").strip()
                    except EOFError:
                        break
                    if not raw:
                        continue
                    if raw.lower() in ("q", "quit", "exit"):
                        break
                    parts = raw.split()
                    if len(parts) != 2:
                        print("  Enter exactly two numbers, e.g.:  3.0 2.0")
                        continue
                    try:
                        x, y = float(parts[0]), float(parts[1])
                    except ValueError:
                        print("  Invalid numbers. Try:  3.0 2.0")
                        continue

                    sender.send_goal(x, y)
                    start_time = time.time()
                    while rclpy.ok() and (time.time() - start_time) < 1.0:
                        rclpy.spin_once(sender, timeout_sec=0.1)
                    print(f"  ✔ Goal ({x}, {y}) sent to Nav2")
            except KeyboardInterrupt:
                print("\nExiting.")
        else:
            print("Non-interactive mode — sending default goal (3.0, 2.0).")
            sender.send_goal(3.0, 2.0)
            start_time = time.time()
            while rclpy.ok() and (time.time() - start_time) < 5.0:
                rclpy.spin_once(sender, timeout_sec=0.1)
                
    sender.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
