"""ROS-free core of the G1 simulator: scenario, world, walking policy, physics.

`sim/mujoco_ros_bridge.py` is the ROS shell around `G1Sim`. `scenario` and `occupancy`
are pure Python; the rest needs mujoco, numpy and pyyaml (no torch).
"""

from .scenario import Obstacle, Scenario, ScenarioError, from_dict, load

__all__ = ["Obstacle", "Scenario", "ScenarioError", "from_dict", "load", "G1Sim"]


def __getattr__(name):
    # Lazy, so the pure modules import without mujoco installed.
    if name == "G1Sim":
        from .sim import G1Sim
        return G1Sim
    raise AttributeError(name)
