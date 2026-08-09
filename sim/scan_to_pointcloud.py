"""Sim-only shim: republishes /scan (LaserScan, from mujoco_ros_bridge.py) as a
PointCloud2 on /depth_anything/points, so g1_real_client.py's points_callback can be
exercised end-to-end against the MuJoCo sim without a real depth camera.

NOT deployed to the real robot. laser_geometry.LaserProjection outputs points already
in a body-planar convention (X-forward, Y-left, Z-up) -- NOT the camera-optical
convention (camera_color_optical_frame) the real /depth_anything/points uses. This
shim validates topic wiring and min_range thresholding/phase logic; it does not
exercise g1_real_frame.py's optical-frame axis remap (see that module's own unit
tests, and M4's bag replay, for that).
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, PointCloud2
from laser_geometry import LaserProjection


class ScanToPointCloud(Node):
    def __init__(self):
        super().__init__("scan_to_pointcloud_shim")
        self.projector = LaserProjection()
        self.pub = self.create_publisher(PointCloud2, "/depth_anything/points", 10)
        self.create_subscription(LaserScan, "/scan", self._on_scan, 10)
        self.get_logger().info("scan_to_pointcloud shim started (sim-only).")

    def _on_scan(self, msg: LaserScan):
        cloud = self.projector.projectLaser(msg)
        self.pub.publish(cloud)


def main():
    rclpy.init()
    node = ScanToPointCloud()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
