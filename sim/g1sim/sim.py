"""G1Sim: a resettable G1 that walks under real MuJoCo physics. No ROS.

    sim = G1Sim()                          # assets from $G1SIM_ASSETS
    sim.reset(scenario)                    # rebuilds the world only if the layout changed
    sim.set_command(0.5, 0.0, 0.0)         # m/s, m/s, rad/s -- what /cmd_vel carries
    sim.step(1.0)                          # simulated seconds
    sim.base_pose(), sim.upright(), sim.ranges()

Faults scheduled in the scenario fire on their own as `step()` crosses their onset
(faults.py); `pop_fault_events()` hands over the ones that fired since the last call.
Sensor faults change only what the bridge should report -- `reported_pose()` and
`scan_available()` -- while `base_pose()` and `ranges()` stay the truth.

The ROS bridge is a thin shell around this; everything worth testing is here, and runs
headless with nothing but mujoco, numpy and pyyaml installed.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np

from . import assets as _assets
from .fault_spec import SPARE_BODIES
from .faults import FaultInjector
from .locomotion import Locomotion, LocomotionConfig
from .policy import LstmPolicy
from .scenario import Scenario
from .world import ENV_GROUP, PELVIS, SPARE, TARGET, build_model, spare_park

#: The pelvis height the shipped model is authored at.
STANDING_HEIGHT_M = 0.793

#: Commands are clipped to what the policy can follow. Conservative relative to the
#: training ranges, which is the right side to err on for a planner it was not trained
#: with; raise them only after checking the gait holds.
DEFAULT_COMMAND_LIMITS = (0.8, 0.4, 1.0)            # |vx| m/s, |vy| m/s, |wz| rad/s

#: Same thresholds as the monitor's `upright` extractor (skill_monitor/adapters/
#: mujoco.json -> core/g1_sensors.base_upright). `sim/tests` pins the two together.
UPRIGHT_TILT_MAX = 0.5
UPRIGHT_HEIGHT_MIN = 0.5


def _yaw_quat(yaw: float) -> np.ndarray:
    return np.array([math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)])


def quat_to_rpy(q: np.ndarray) -> tuple[float, float, float]:
    """Roll, pitch, yaw from a MuJoCo (w, x, y, z) quaternion."""
    w, x, y, z = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


class G1Sim:
    def __init__(self, assets: str | None = None, *, body_collision: bool = True,
                 command_limits: tuple[float, float, float] = DEFAULT_COMMAND_LIMITS):
        root = _assets.assets_root(assets)
        self.model_xml = _assets.model_xml(root)
        self.config = LocomotionConfig.from_yaml(_assets.locomotion_config(root))
        self.locomotion = Locomotion(self.config,
                                     LstmPolicy.load(_assets.policy_path(root)))
        self.body_collision = body_collision
        self.command_limits = np.array(command_limits, dtype=np.float64)
        self.model: mujoco.MjModel | None = None
        self.data: mujoco.MjData | None = None
        self.scenario: Scenario | None = None
        self._layout = None
        self._command = np.zeros(3)
        self._episode_start = 0.0
        self._push_until = 0.0
        self.resets = 0
        self._clear_faults()
        self.injector = FaultInjector(self)
        self._fault_events: list[dict] = []

    # ------------------------------------------------------------------ episode

    def reset(self, scenario: Scenario, settle_s: float = 1.0) -> None:
        """Start a new episode. The robot stands at the scenario's start pose, settled."""
        if self.model is None or scenario.layout_key() != self._layout:
            self.model = build_model(scenario, self.model_xml, timestep=self.config.dt,
                                     body_collision=self.body_collision)
            self.data = mujoco.MjData(self.model)
            self._pelvis = self.model.body(PELVIS).id
            self._target_mocap = self.model.body(TARGET).mocapid[0]
            self._spares = [(self.model.body(SPARE.format(i)).mocapid[0],
                             self.model.geom(SPARE.format(i)).id)
                            for i in range(SPARE_BODIES)]
            self._nominal_friction = self.model.geom_friction.copy()
            self._nominal_spare_size = [self.model.geom_size[g].copy()
                                        for _, g in self._spares]
            self._layout = scenario.layout_key()
        self.scenario = scenario
        model, data = self.model, self.data

        mujoco.mj_resetData(model, data)
        x, y, yaw = scenario.start
        data.qpos[0:3] = (x, y, STANDING_HEIGHT_M)
        data.qpos[3:7] = _yaw_quat(yaw)
        data.qpos[7:] = self.config.default_angles
        mujoco.mj_forward(model, data)
        self.set_goal(*scenario.goals[0])

        self.locomotion.reset()            # zeroes the LSTM memory: no gait leaks over
        # A same-layout reset reuses the model, so everything a fault mutated in it --
        # friction, the spare boxes -- is put back here, not left to the next episode.
        model.geom_friction[:] = self._nominal_friction
        for i in range(len(self._spares)):
            self._park_spare(i)
        self._clear_faults()
        self._command = np.zeros(3)
        self._push_until = 0.0
        self.injector = FaultInjector(self)          # nothing fires while settling
        self.step(settle_s)
        self._episode_start = data.time
        self.injector = FaultInjector(self, scenario.faults)
        self._fault_events = []
        self.resets += 1

    def _clear_faults(self) -> None:
        self.locomotion.torque_scale = 1.0
        self.command_scale = 1.0
        self._drift = None                 # (rate m/s, world angle, onset time)
        self._scan_dropout_until = 0.0

    @property
    def time(self) -> float:
        """Simulated seconds since the episode started (after settling)."""
        return self.data.time - self._episode_start

    # ------------------------------------------------------------------ control

    def set_command(self, vx: float, vy: float, wz: float) -> np.ndarray:
        """Clip and store the velocity command; returns what will actually be used."""
        raw = np.array([vx, vy, wz], dtype=np.float64)
        if not np.all(np.isfinite(raw)):
            raw = np.zeros(3)
        self._command = np.clip(raw, -self.command_limits, self.command_limits)
        return self._command.copy()

    @property
    def command(self) -> np.ndarray:
        return self._command.copy()

    @property
    def executed_command(self) -> np.ndarray:
        """What the legs are actually asked for: the command, after a `stall` fault."""
        return self._command * self.command_scale

    def step(self, seconds: float | None = None, control_steps: int | None = None) -> None:
        """Advance by whole control periods (20 ms): `seconds` rounded, or a count.

        Faults are checked before each period, so one fires within 20 ms of its onset.
        """
        if control_steps is None:
            control_steps = max(1, int(round((seconds or 0.0) / self.config.control_dt)))
        for _ in range(control_steps):
            self._fault_events.extend(self.injector.update())
            if self._push_until and self.data.time >= self._push_until:
                self.data.xfrc_applied[self._pelvis, :] = 0.0
                self._push_until = 0.0
            self.locomotion.control_step(self.model, self.data, self.executed_command)

    def pop_fault_events(self) -> list[dict]:
        """Faults fired since the last call, each `{type, onset_s, t, params}`."""
        events, self._fault_events = self._fault_events, []
        return events

    def push(self, force_xyz, duration_s: float = 0.2) -> None:
        """Apply a world-frame force (N) to the pelvis for `duration_s`."""
        self.data.xfrc_applied[self._pelvis, :3] = np.asarray(force_xyz, dtype=np.float64)
        self._push_until = self.data.time + duration_s

    def set_goal(self, x: float, y: float) -> None:
        self.data.mocap_pos[self._target_mocap] = (x, y, 0.05)

    # ------------------------------------------------------------------ faults

    def set_friction(self, mu: float) -> None:
        """Sliding friction of every geom. MuJoCo takes a contact's friction as the max
        of the pair, so lowering the floor alone would leave the feet's in charge."""
        self.model.geom_friction[:, 0] = mu

    def set_torque_scale(self, scale: float) -> None:
        self.locomotion.torque_scale = float(scale)

    def set_command_scale(self, scale: float) -> None:
        self.command_scale = float(scale)

    def place_spare(self, index: int, pos, size, yaw: float = 0.0) -> None:
        """Move spare box `index` into the arena: centre (x, y), half-extents, yaw."""
        if not 0 <= index < len(self._spares):
            raise ValueError(f"no spare body {index}; the world has {len(self._spares)}")
        mocap, _ = self._spares[index]
        half = np.asarray(size, dtype=np.float64)
        self._resize_spare(index, half)
        self.data.mocap_pos[mocap] = (pos[0], pos[1], half[2] + 0.01)
        self.data.mocap_quat[mocap] = _yaw_quat(yaw)
        mujoco.mj_kinematics(self.model, self.data)   # visible to the next scan at once

    def _park_spare(self, index: int) -> None:
        mocap, _ = self._spares[index]
        self._resize_spare(index, self._nominal_spare_size[index])
        self.data.mocap_pos[mocap] = spare_park(index)
        self.data.mocap_quat[mocap] = (1.0, 0.0, 0.0, 0.0)

    def _resize_spare(self, index: int, half: np.ndarray) -> None:
        """Every bound the compiler derived from the spare's parked size follows the new
        one: the collision broadphase prunes by `geom_rbound`/`geom_aabb`, and
        `mj_multiRay` -- the scan -- by the body's BVH box, so a box resized without it
        is solid but invisible to the lidar from some angles."""
        mocap, geom = self._spares[index]
        body = self.model.geom_bodyid[geom]
        aabb = np.concatenate([np.zeros(3), half])
        self.model.geom_size[geom] = half
        self.model.geom_rbound[geom] = float(np.linalg.norm(half))
        self.model.geom_aabb[geom] = aabb
        adr, num = self.model.body_bvhadr[body], self.model.body_bvhnum[body]
        self.model.bvh_aabb[adr:adr + num] = aabb          # one geom, so one node

    def start_odom_drift(self, rate_m_s: float, angle: float = 0.0) -> None:
        """From now on the reported position walks away from the true one at `rate_m_s`,
        in the world direction `angle` -- a slow bias, as from wheel or leg odometry."""
        self._drift = (float(rate_m_s), float(angle), self.time)

    def drop_scan(self, duration_s: float | None = None) -> None:
        """No scan for `duration_s` simulated seconds; `None` for the rest of the episode."""
        self._scan_dropout_until = math.inf if duration_s is None \
            else self.time + float(duration_s)

    def odom_offset(self) -> tuple[float, float]:
        if self._drift is None:
            return 0.0, 0.0
        rate, angle, onset = self._drift
        travelled = rate * max(0.0, self.time - onset)
        return travelled * math.cos(angle), travelled * math.sin(angle)

    def reported_pose(self) -> tuple[float, float, float, float]:
        """`base_pose()` as the robot's odometry reports it, drift included."""
        x, y, z, yaw = self.base_pose()
        dx, dy = self.odom_offset()
        return x + dx, y + dy, z, yaw

    def scan_available(self) -> bool:
        return self.time >= self._scan_dropout_until

    # ------------------------------------------------------------------ state

    def base_position(self) -> np.ndarray:
        return self.data.qpos[0:3].copy()

    def base_quat(self) -> np.ndarray:
        return self.data.qpos[3:7].copy()

    def base_pose(self) -> tuple[float, float, float, float]:
        """x, y, z, yaw."""
        x, y, z = self.data.qpos[0:3]
        return float(x), float(y), float(z), quat_to_rpy(self.data.qpos[3:7])[2]

    def roll_pitch(self) -> tuple[float, float]:
        roll, pitch, _ = quat_to_rpy(self.data.qpos[3:7])
        return roll, pitch

    def base_height(self) -> float:
        return float(self.data.qpos[2])

    def linear_velocity_body(self) -> np.ndarray:
        """Measured base velocity in the base frame -- what an odometry twist reports."""
        rot = np.zeros(9)
        mujoco.mju_quat2Mat(rot, self.data.qpos[3:7])
        return rot.reshape(3, 3).T @ self.data.qvel[0:3]

    def angular_velocity_body(self) -> np.ndarray:
        """MuJoCo's free-joint angular velocity is already in the body frame."""
        return self.data.qvel[3:6].copy()

    def upright(self) -> bool:
        roll, pitch = self.roll_pitch()
        return (abs(roll) < UPRIGHT_TILT_MAX and abs(pitch) < UPRIGHT_TILT_MAX
                and self.base_height() > UPRIGHT_HEIGHT_MIN)

    def ranges(self, count: int = 360, scan_height: float = 0.3,
               max_range: float = 10.0) -> np.ndarray:
        """A planar scan of walls and obstacles at `scan_height` above the floor.

        Angles run from -pi to pi in the base frame, counter-clockwise, as a
        LaserScan's do. `inf` means no return within `max_range`. Only ENV_GROUP geoms
        are visible, so neither the robot's own body nor the floor is ever hit.
        """
        x, y, _, yaw = self.base_pose()
        angles = -math.pi + 2.0 * math.pi * np.arange(count) / count
        world = yaw + angles
        vec = np.stack([np.cos(world), np.sin(world), np.zeros(count)], axis=1)
        geomgroup = np.zeros(6, dtype=np.uint8)
        geomgroup[ENV_GROUP] = 1
        geomid = np.full(count, -1, dtype=np.int32)
        dist = np.full(count, -1.0)
        mujoco.mj_multiRay(self.model, self.data, np.array([x, y, scan_height]),
                           vec.reshape(-1), geomgroup, True, -1, geomid, dist, None,
                           count, max_range)
        return np.where((dist >= 0) & (dist <= max_range), dist, np.inf)

    def min_range(self, **kwargs) -> float:
        finite = self.ranges(**kwargs)
        finite = finite[np.isfinite(finite)]
        return float(finite.min()) if finite.size else math.inf
