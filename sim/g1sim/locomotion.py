"""The G1 walking controller, reproducing Unitree's `deploy_mujoco.py` exactly.

Their loop, per physics step: apply PD torques toward the current joint targets, step,
and every `control_decimation` steps (50 Hz at dt = 2 ms) build the 47-d observation and
ask the policy for new targets. The only change is where the velocity command comes
from: theirs is fixed in `g1.yaml`; ours is whatever `set_command` last received.

Observation layout (`build_observation`), in their order:
    [0:3]   base angular velocity (body frame) * ang_vel_scale
    [3:6]   gravity direction in the body frame
    [6:9]   command (vx, vy, wz) * cmd_scale
    [9:21]  (q - default_angles) * dof_pos_scale
    [21:33] dq * dof_vel_scale
    [33:45] previous action
    [45:47] sin / cos of the gait phase, period 0.8 s, counted from the episode start
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np
import yaml

GAIT_PERIOD_S = 0.8


@dataclass(frozen=True)
class LocomotionConfig:
    dt: float
    decimation: int
    kps: np.ndarray
    kds: np.ndarray
    default_angles: np.ndarray
    ang_vel_scale: float
    dof_pos_scale: float
    dof_vel_scale: float
    action_scale: float
    cmd_scale: np.ndarray
    num_actions: int
    num_obs: int

    @classmethod
    def from_yaml(cls, path: str | Path) -> "LocomotionConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        f32 = lambda key: np.array(raw[key], dtype=np.float32)   # noqa: E731
        return cls(
            dt=float(raw["simulation_dt"]), decimation=int(raw["control_decimation"]),
            kps=f32("kps"), kds=f32("kds"), default_angles=f32("default_angles"),
            ang_vel_scale=float(raw["ang_vel_scale"]),
            dof_pos_scale=float(raw["dof_pos_scale"]),
            dof_vel_scale=float(raw["dof_vel_scale"]),
            action_scale=float(raw["action_scale"]), cmd_scale=f32("cmd_scale"),
            num_actions=int(raw["num_actions"]), num_obs=int(raw["num_obs"]),
        )

    @property
    def control_dt(self) -> float:
        return self.dt * self.decimation


def gravity_orientation(quat_wxyz: np.ndarray) -> np.ndarray:
    """Gravity in the body frame, Unitree's formula (MuJoCo quaternions are w, x, y, z)."""
    qw, qx, qy, qz = quat_wxyz
    return np.array([
        2.0 * (-qz * qx + qw * qy),
        -2.0 * (qz * qy + qw * qx),
        1.0 - 2.0 * (qw * qw + qz * qz),
    ], dtype=np.float32)


def build_observation(cfg: LocomotionConfig, qpos: np.ndarray, qvel: np.ndarray,
                      command: np.ndarray, last_action: np.ndarray,
                      physics_steps: int) -> np.ndarray:
    n = cfg.num_actions
    obs = np.zeros(cfg.num_obs, dtype=np.float32)
    obs[0:3] = qvel[3:6] * cfg.ang_vel_scale
    obs[3:6] = gravity_orientation(qpos[3:7])
    obs[6:9] = np.asarray(command, dtype=np.float32) * cfg.cmd_scale
    obs[9:9 + n] = (qpos[7:] - cfg.default_angles) * cfg.dof_pos_scale
    obs[9 + n:9 + 2 * n] = qvel[6:] * cfg.dof_vel_scale
    obs[9 + 2 * n:9 + 3 * n] = last_action
    phase = (physics_steps * cfg.dt) % GAIT_PERIOD_S / GAIT_PERIOD_S
    obs[9 + 3 * n:9 + 3 * n + 2] = (np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase))
    return obs


class Locomotion:
    """Drives the 12 leg joints of a G1 model from a velocity command."""

    def __init__(self, cfg: LocomotionConfig, policy):
        self.cfg = cfg
        self.policy = policy
        #: Scales the PD torques; 1.0 is the healthy robot. The fault library lowers
        #: it to weaken the actuators.
        self.torque_scale = 1.0
        self.reset()

    def reset(self) -> None:
        self.policy.reset()
        self.action = np.zeros(self.cfg.num_actions, dtype=np.float32)
        self.target = self.cfg.default_angles.copy()
        self.physics_steps = 0
        self.last_observation = np.zeros(self.cfg.num_obs, dtype=np.float32)

    def control_step(self, model: mujoco.MjModel, data: mujoco.MjData,
                     command: np.ndarray) -> None:
        """One 20 ms control period: `decimation` physics steps, then a new action."""
        cfg = self.cfg
        for _ in range(cfg.decimation):
            tau = (self.target - data.qpos[7:]) * cfg.kps - data.qvel[6:] * cfg.kds
            data.ctrl[:] = tau * self.torque_scale
            mujoco.mj_step(model, data)
            self.physics_steps += 1
        obs = build_observation(cfg, data.qpos, data.qvel, command, self.action,
                                self.physics_steps)
        self.last_observation = obs
        self.action = np.asarray(self.policy(obs), dtype=np.float32)
        self.target = self.action * cfg.action_scale + cfg.default_angles
