"""A small stand-in for Nav2, for running experiments headless: plan on the scenario's map,
see surprises in the scan, follow the plan, and give up the way Nav2 does.

    nav = Navigator(scenario)
    nav.set_goal(x, y, t)
    vx, wz = nav.update(t, reported_pose, scan_points)      # every control period
    nav.status                                              # executing | succeeded | aborted

Why it exists: the full stack (ROS 2 + Nav2 in Docker) is how the system is deployed, but an
experiment of a thousand episodes needs to run where neither is available. The monitor
never reads the planner (P12), so what the planner is matters to the results only through
the robot's behaviour -- and this one is applied identically to every arm. Its parameters
are Nav2's as configured in `sim/nav2_params.yaml`: 0.26 m/s, 0.25 m goal tolerance, and
the progress checker's 0.05 m within 30 s before the goal is aborted.

It works in the frame odometry reports, exactly as Nav2 does: a drifting odometry makes it
plan from the wrong place and declare arrival at the wrong place, which is the point of the
`odom_drift` fault.
"""

from __future__ import annotations

import heapq
import math

import numpy as np

from .occupancy import OCCUPIED, occupancy_grid
from .scenario import Scenario

SQRT2 = math.sqrt(2.0)


class Navigator:
    def __init__(self, scenario: Scenario, *, resolution: float = 0.1,
                 robot_radius: float = 0.35, lethal_radius: float = 0.12,
                 max_speed: float = 0.26, max_turn: float = 0.6, lookahead: float = 0.6,
                 goal_tolerance: float = 0.25, replan_s: float = 1.0,
                 scan_memory_s: float = 2.0, scan_range: float = 4.0,
                 progress_radius: float = 0.05, progress_window_s: float = 30.0,
                 abort_after_failures: int = 5):
        self.res = resolution
        self.half = (scenario.map_size[0] / 2.0, scenario.map_size[1] / 2.0)
        self.robot_radius, self.lethal_radius = robot_radius, lethal_radius
        self.max_speed, self.max_turn, self.lookahead = max_speed, max_turn, lookahead
        self.goal_tolerance, self.replan_s = goal_tolerance, replan_s
        self.scan_memory_s, self.scan_range = scan_memory_s, scan_range
        self.progress_radius, self.progress_window_s = progress_radius, progress_window_s
        self.abort_after_failures = abort_after_failures

        self.inflated = self._grid(scenario, robot_radius)
        self.lethal = self._grid(scenario, lethal_radius)
        self.rows, self.cols = self.inflated.shape
        self._disk_inflated = self._disk(robot_radius)
        self._disk_lethal = self._disk(lethal_radius)
        self.goal = None
        self.status = "idle"
        self.path: list[tuple[float, float]] | None = None
        self._hits: list[tuple[float, np.ndarray]] = []
        self._next_plan = 0.0
        self._failures = 0
        self._progress_ref = None
        self.plans = 0

    # ------------------------------------------------------------------ grid

    def _grid(self, scenario, inflation):
        w, h, pixels = occupancy_grid(scenario, self.res, inflation)
        return np.frombuffer(pixels, dtype=np.uint8).reshape(h, w) == OCCUPIED

    def _disk(self, radius):
        r = int(math.ceil(radius / self.res))
        return [(dr, dc) for dr in range(-r, r + 1) for dc in range(-r, r + 1)
                if math.hypot(dr, dc) * self.res <= radius]

    def cell(self, x, y):
        col = int((x + self.half[0]) / self.res)
        row = int((self.half[1] - y) / self.res)
        return min(max(row, 0), self.rows - 1), min(max(col, 0), self.cols - 1)

    def center(self, row, col):
        return (-self.half[0] + (col + 0.5) * self.res, self.half[1] - (row + 0.5) * self.res)

    def _layers(self, t):
        """Static map plus the scan hits of the last `scan_memory_s` seconds."""
        self._hits = [(ts, pts) for ts, pts in self._hits if t - ts <= self.scan_memory_s]
        inflated, lethal = self.inflated.copy(), self.lethal.copy()
        for _, pts in self._hits:
            for x, y in pts:
                r, c = self.cell(x, y)
                for disk, layer in ((self._disk_inflated, inflated), (self._disk_lethal, lethal)):
                    for dr, dc in disk:
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < self.rows and 0 <= cc < self.cols:
                            layer[rr, cc] = True
        return inflated, lethal

    # ------------------------------------------------------------------ planning

    def plan(self, start, goal, t):
        inflated, lethal = self._layers(t)
        s, g = self.cell(*start), self.cell(*goal)
        if lethal[g]:
            return None
        # From a start inside the inflation (pressed against a box that appeared), the
        # robot may cross inflated cells to get out, never lethal ones.
        escaping = {s}
        frontier = [(0.0, s)]
        cost = {s: 0.0}
        parent = {s: None}
        while frontier:
            _, cur = heapq.heappop(frontier)
            if cur == g:
                break
            r, c = cur
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (r + dr, c + dc)
                if not (0 <= nxt[0] < self.rows and 0 <= nxt[1] < self.cols) or lethal[nxt]:
                    continue
                if inflated[nxt] and nxt != g:
                    if cur not in escaping:
                        continue
                    escaping.add(nxt)
                step = SQRT2 if dr and dc else 1.0
                new = cost[cur] + step
                if new < cost.get(nxt, math.inf):
                    cost[nxt] = new
                    parent[nxt] = cur
                    heapq.heappush(frontier, (new + math.hypot(g[0] - nxt[0], g[1] - nxt[1]), nxt))
        if g not in parent:
            return None
        cells, node = [], g
        while node is not None:
            cells.append(node)
            node = parent[node]
        path = [self.center(*c) for c in reversed(cells)]
        path[-1] = goal
        return path

    # ------------------------------------------------------------------ control

    def set_goal(self, x, y, t):
        self.goal = (float(x), float(y))
        self.restart(t)

    def restart(self, t):
        """Re-send the goal: a fresh plan, the scan memory cleared (Nav2's recovery
        clears its costmap), and the progress checker started over."""
        self.status = "executing"
        self.path = None
        self._hits = []
        self._next_plan = t
        self._failures = 0
        self._progress_ref = None

    def update(self, t, pose, scan_points=None):
        """One control period: `pose` is (x, y, yaw) as odometry reports it."""
        if scan_points is not None and len(scan_points):
            self._hits.append((t, scan_points))
        if self.status != "executing":
            return 0.0, 0.0
        x, y, yaw = pose
        gx, gy = self.goal
        dist = math.hypot(gx - x, gy - y)
        if dist <= self.goal_tolerance:
            self.status = "succeeded"
            return 0.0, 0.0

        if self._progress_ref is None:
            self._progress_ref = (t, x, y)
        elif math.hypot(x - self._progress_ref[1], y - self._progress_ref[2]) >= self.progress_radius:
            self._progress_ref = (t, x, y)
        elif t - self._progress_ref[0] > self.progress_window_s:
            self.status = "aborted"
            return 0.0, 0.0

        if self.path is None or t >= self._next_plan:
            self._next_plan = t + self.replan_s
            path = self.plan((x, y), self.goal, t)
            self.plans += 1
            if path is None:
                self._failures += 1
                if self._failures >= self.abort_after_failures:
                    self.status = "aborted"
                    return 0.0, 0.0
            else:
                self._failures = 0
                self.path = path
        if not self.path:
            return 0.0, 0.0

        pts = np.asarray(self.path)
        nearest = int(np.argmin(np.hypot(pts[:, 0] - x, pts[:, 1] - y)))
        target = self.path[-1]
        for px, py in self.path[nearest:]:
            if math.hypot(px - x, py - y) >= self.lookahead:
                target = (px, py)
                break
        err = math.atan2(target[1] - y, target[0] - x) - yaw
        err = math.atan2(math.sin(err), math.cos(err))
        if abs(err) > 0.7:
            return 0.0, math.copysign(self.max_turn, err)
        vx = self.max_speed * max(0.3, math.cos(err))
        vx = min(vx, 0.6 * dist + 0.05)
        return vx, max(-self.max_turn, min(self.max_turn, 1.5 * err))


def scan_points(ranges: np.ndarray, pose, max_range: float = 4.0) -> np.ndarray:
    """A planar scan (angles -pi..pi in the base frame) as world points, from `pose`."""
    x, y, yaw = pose
    n = len(ranges)
    angles = yaw - math.pi + 2.0 * math.pi * np.arange(n) / n
    ok = np.isfinite(ranges) & (ranges <= max_range)
    r = ranges[ok]
    return np.stack([x + r * np.cos(angles[ok]), y + r * np.sin(angles[ok])], axis=1)
