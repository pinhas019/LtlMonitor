"""Applying scheduled faults to a running G1Sim, and recording when each one fired.

    injector = FaultInjector(sim, scenario.faults)
    events = injector.update()      # each control step; returns faults fired this step

Each event is `{type, onset_s, t, params}` with `t` the simulated episode time at which
the fault actually took effect -- the ground truth an episode record is scored against.
It comes from here, the injector, and never from the monitor.

Physical faults change the world or the robot (`push`, `slip`, `weaken`, `stall`, a box
that appears). Sensor faults (`odom_drift`, `scan_dropout`) leave the physics alone and
change what the bridge reports; the truth stays available on the sim for scoring.
"""

from __future__ import annotations

import math

import numpy as np

from . import fault_spec


class FaultInjector:
    def __init__(self, sim, faults=()):
        self.sim = sim
        self._pending = sorted((dict(f) for f in faults), key=lambda f: f["onset_s"])
        self.fired: list[dict] = []
        self._spare = 0

    def update(self) -> list[dict]:
        """Fire every fault whose onset has passed; return the ones fired now."""
        events = []
        while self._pending and self._pending[0]["onset_s"] <= self.sim.time:
            fault = self._pending.pop(0)
            params = fault_spec.resolved_params(fault)
            getattr(self, f"_{fault['type']}")(params)
            event = {"type": fault["type"], "onset_s": float(fault["onset_s"]),
                     "t": round(self.sim.time, 4), "params": params}
            self.fired.append(event)
            events.append(event)
        return events

    # ------------------------------------------------------------------ physical

    def _push(self, p):
        heading = self.sim.base_pose()[3] + p["angle"]
        force = p["force_n"] * np.array([math.cos(heading), math.sin(heading), 0.0])
        self.sim.push(force, duration_s=p["duration_s"])

    def _slip(self, p):
        self.sim.set_friction(p["mu"])

    def _weaken(self, p):
        self.sim.set_torque_scale(p["scale"])

    def _stall(self, p):
        self.sim.set_command_scale(p["scale"])

    def _obstacle(self, p):
        self._spawn(p)

    def _block_route(self, p):
        self._spawn(p)

    def _spawn(self, p):
        self.sim.place_spare(self._spare, p["pos"], p["size"], p["yaw"])
        self._spare += 1

    # ------------------------------------------------------------------ sensor

    def _odom_drift(self, p):
        self.sim.start_odom_drift(p["rate_m_s"], p["angle"])

    def _scan_dropout(self, p):
        self.sim.drop_scan(p["duration_s"])
