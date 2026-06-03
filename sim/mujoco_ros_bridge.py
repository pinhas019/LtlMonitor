import math
import threading
import time

import mujoco
import numpy as np

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped, PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster
from transforms3d.euler import euler2quat, quat2euler
from visualization_msgs.msg import Marker
import json
import os
import xml.etree.ElementTree as ET

class MujocoRosBridge(Node):
    def __init__(self):
        super().__init__('mujoco_ros_bridge')
        
        # Load config
        config_path = 'sim_config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        else:
            config = {}
            
        map_size_x = config.get('map_size_x', 10.0)
        map_size_y = config.get('map_size_y', 10.0)
        agent_start_x = config.get('agent_start_x', 0.0)
        agent_start_y = config.get('agent_start_y', 0.0)
        
        # Modify arena.xml to match map size
        try:
            tree = ET.parse('arena.xml')
            root = tree.getroot()
            for geom in root.iter('geom'):
                if geom.get('name') == 'floor':
                    geom.set('size', f"{map_size_x / 2.0} {map_size_y / 2.0} 0.05")
                    break
            tree.write('arena_configured.xml')
            self.model = mujoco.MjModel.from_xml_path('arena_configured.xml')
        except Exception as e:
            self.get_logger().error(f"Failed to configure arena XML: {e}")
            self.model = mujoco.MjModel.from_xml_path('arena.xml')
            
        self.data = mujoco.MjData(self.model)
        
        # Initialize agent start position
        if len(self.data.qpos) >= 7:
            self.data.qpos[0] = agent_start_x
            self.data.qpos[1] = agent_start_y
            
        self.cmd_vel_sub = self.create_subscription(Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.scan_pub = self.create_publisher(LaserScan, '/scan', 10)
        self.goal_sub = self.create_subscription(PoseStamped, '/goal_pose', self.goal_callback, 10)
        self.marker_pub = self.create_publisher(Marker, '/visualization_marker', 10)
        self.target_pose_pub = self.create_publisher(PoseStamped, '/target_pose', 10)
        self.tf_broadcaster = TransformBroadcaster(self)
        
        self.target_v_x = 0.0
        self.target_v_y = 0.0
        self.target_w_z = 0.0
        
        self.sim_thread = threading.Thread(target=self.sim_loop)
        self.sim_thread.daemon = True
        self.sim_thread.start()
        
        self.pub_timer = self.create_timer(0.05, self.publish_state)
        
        self.get_logger().info('MuJoCo ROS 2 Bridge started.')

    def cmd_vel_callback(self, msg: Twist):
        self.target_v_x = msg.linear.x
        self.target_v_y = msg.linear.y
        self.target_w_z = msg.angular.z

    def goal_callback(self, msg: PoseStamped):
        try:
            body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, 'target')
            if body_id != -1:
                self.model.body_pos[body_id][0] = msg.pose.position.x
                self.model.body_pos[body_id][1] = msg.pose.position.y
                self.get_logger().info(f"Moved target marker to ({msg.pose.position.x}, {msg.pose.position.y})")
        except Exception as e:
            self.get_logger().error(f"Failed to move target marker: {e}")

    def sim_loop(self):
        try:
            dt = self.model.opt.timestep
            last_time = time.time()
            
            while rclpy.ok():
                now = time.time()
                if now - last_time < dt:
                    time.sleep(dt - (now - last_time))
                    continue
                last_time = time.time()
                
                qpos = self.data.qpos
                qvel = self.data.qvel
                
                if len(qpos) >= 7:
                    qpos[2] = 0.78
                    quat = [qpos[3], qpos[4], qpos[5], qpos[6]]
                    roll, pitch, yaw = quat2euler(quat, axes='sxyz')
                    new_quat = euler2quat(0, 0, yaw, axes='sxyz')
                    qpos[3:7] = new_quat
                    
                    v_x_world = self.target_v_x * math.cos(yaw) - self.target_v_y * math.sin(yaw)
                    v_y_world = self.target_v_x * math.sin(yaw) + self.target_v_y * math.cos(yaw)
                    
                    qpos[0] += v_x_world * dt
                    qpos[1] += v_y_world * dt
                    
                    yaw += self.target_w_z * dt
                    qpos[3:7] = euler2quat(0, 0, yaw, axes='sxyz')
                
                if len(qvel) >= 6:
                    qvel[0:6] = 0.0
                
                mujoco.mj_step(self.model, self.data)
        except Exception as e:
            self.get_logger().error(f"Error in sim_loop: {e}")

    def publish_state(self):
        try:
            qpos = self.data.qpos
            if len(qpos) < 7:
                return
            x, y, z = qpos[0], qpos[1], qpos[2]
            qw, qx, qy, qz = qpos[3], qpos[4], qpos[5], qpos[6]
            
            now = self.get_clock().now().to_msg()
            
            t = TransformStamped()
            t.header.stamp = now
            t.header.frame_id = 'odom'
            t.child_frame_id = 'base_link'
            t.transform.translation.x = float(x)
            t.transform.translation.y = float(y)
            t.transform.translation.z = float(z)
            t.transform.rotation.w = float(qw)
            t.transform.rotation.x = float(qx)
            t.transform.rotation.y = float(qy)
            t.transform.rotation.z = float(qz)
            self.tf_broadcaster.sendTransform(t)
            
            odom = Odometry()
            odom.header.stamp = now
            odom.header.frame_id = 'odom'
            odom.child_frame_id = 'base_link'
            odom.pose.pose.position.x = float(x)
            odom.pose.pose.position.y = float(y)
            odom.pose.pose.position.z = float(z)
            odom.pose.pose.orientation.w = float(qw)
            odom.pose.pose.orientation.x = float(qx)
            odom.pose.pose.orientation.y = float(qy)
            odom.pose.pose.orientation.z = float(qz)
            odom.twist.twist.linear.x = float(self.target_v_x)
            odom.twist.twist.linear.y = float(self.target_v_y)
            odom.twist.twist.angular.z = float(self.target_w_z)
            self.odom_pub.publish(odom)
            
            # Publish green target marker
            body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, 'target')
            if body_id != -1:
                tx = self.model.body_pos[body_id][0]
                ty = self.model.body_pos[body_id][1]
                
                # 1. Publish visual marker
                marker = Marker()
                marker.header.stamp = now
                marker.header.frame_id = 'map'
                marker.ns = 'target'
                marker.id = 0
                marker.type = Marker.SPHERE
                marker.action = Marker.ADD
                marker.pose.position.x = float(tx)
                marker.pose.position.y = float(ty)
                marker.pose.position.z = 0.25
                marker.pose.orientation.w = 1.0
                marker.scale.x = 0.5
                marker.scale.y = 0.5
                marker.scale.z = 0.5
                marker.color.r = 0.0
                marker.color.g = 1.0
                marker.color.b = 0.0
                marker.color.a = 0.8
                self.marker_pub.publish(marker)

                # 2. Publish target pose
                t_pose = PoseStamped()
                t_pose.header.stamp = now
                t_pose.header.frame_id = 'map'
                t_pose.pose.position.x = float(tx)
                t_pose.pose.position.y = float(ty)
                t_pose.pose.position.z = 0.25
                t_pose.pose.orientation.w = 1.0
                self.target_pose_pub.publish(t_pose)
            
            self.publish_lidar(now, float(x), float(y), float(z), float(qw), float(qx), float(qy), float(qz))
        except Exception as e:
            self.get_logger().error(f"Error in publish_state: {e}")

    def publish_lidar(self, stamp, x, y, z, qw, qx, qy, qz):
        scan = LaserScan()
        scan.header.stamp = stamp
        scan.header.frame_id = 'base_link'
        scan.angle_min = -math.pi
        scan.angle_max = math.pi
        
        num_rays = 360
        scan.angle_increment = 2.0 * math.pi / num_rays
        scan.time_increment = 0.0
        scan.range_min = 0.1
        scan.range_max = 10.0
        
        ranges = []
        _, _, yaw = quat2euler([qw, qx, qy, qz], axes='sxyz')
        
        for i in range(num_rays):
            angle = scan.angle_min + i * scan.angle_increment
            world_angle = yaw + angle
            
            pnt = np.array([x, y, z + 0.5])
            vec = np.array([math.cos(world_angle), math.sin(world_angle), 0.0])
            
            geomid = np.array([-1], dtype=np.int32)
            dist = mujoco.mj_ray(self.model, self.data, pnt, vec, None, 1, -1, geomid)
            
            # Only count the hit if it hit an external object (worldbody geom, body_id == 0)
            if dist > 0 and geomid[0] >= 0 and self.model.geom_bodyid[geomid[0]] == 0:
                ranges.append(float(dist))
            else:
                ranges.append(float('inf'))
                
        scan.ranges = ranges
        self.scan_pub.publish(scan)

def main(args=None):
    rclpy.init(args=args)
    bridge = MujocoRosBridge()
    rclpy.spin(bridge)
    bridge.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
