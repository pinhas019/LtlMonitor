"""Shared /vision/goal_similarity subscription, used by every adapter (real robot and
sim) so visual goal confirmation works the same way regardless of environment.
"""

from __future__ import annotations

from std_msgs.msg import Float32
from rclpy.node import Node


class VisionScoreMixin:
    def __init__(self):
        self._vision_score = 0.0

    def _register_vision_subscription(self, node: Node) -> None:
        node.create_subscription(Float32, "/vision/goal_similarity", self._vision_cb, 10)

    def _vision_cb(self, msg: Float32) -> None:
        self._vision_score = round(float(msg.data), 3)

    @property
    def vision_score(self) -> float:
        return self._vision_score
