"""Nav2's map, generated from the same Scenario the world is built from.

Pure Python. The old `generate_map.py` read obstacles out of `<body>` elements in
`arena.xml` while the lidar only saw worldbody geoms, so any obstacle appeared to the
planner or to the sensor but never both. One source removes the possibility.

Pixel convention matches the map it replaces: 255 free, 0 occupied, `negate: 0`, and the
first image row is the top of the map (largest y), which is what `map_server` expects.
"""

from __future__ import annotations

from pathlib import Path

from .scenario import Scenario

FREE, OCCUPIED = 255, 0
WALL_THICKNESS_M = 0.1


def occupancy_grid(scenario: Scenario, resolution: float = 0.05,
                   inflation: float = 0.0) -> tuple[int, int, bytes]:
    """`(width, height, pixels)`: row-major, top row first."""
    size_x, size_y = scenario.map_size
    width, height = int(round(size_x / resolution)), int(round(size_y / resolution))
    origin_x, origin_y = -size_x / 2.0, -size_y / 2.0
    pixels = bytearray([FREE] * (width * height))

    for row in range(height):
        # Row 0 is the top of the image, i.e. the largest y.
        y = origin_y + (height - row - 0.5) * resolution
        for col in range(width):
            x = origin_x + (col + 0.5) * resolution
            if _occupied(scenario, x, y, inflation):
                pixels[row * width + col] = OCCUPIED
    return width, height, bytes(pixels)


def _occupied(scenario: Scenario, x: float, y: float, inflation: float) -> bool:
    if scenario.walls:
        half_x, half_y = scenario.map_size[0] / 2.0, scenario.map_size[1] / 2.0
        edge = WALL_THICKNESS_M + inflation
        if abs(x) > half_x - edge or abs(y) > half_y - edge:
            return True
    return any(o.distance_to(x, y) <= inflation for o in scenario.obstacles)


def write_map(scenario: Scenario, directory: str | Path, name: str = "map",
              resolution: float = 0.05, inflation: float = 0.0) -> tuple[Path, Path]:
    """Write `<name>.pgm` and `<name>.yaml` for `map_server`; return both paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    width, height, pixels = occupancy_grid(scenario, resolution, inflation)
    pgm = directory / f"{name}.pgm"
    with open(pgm, "wb") as fh:
        fh.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        fh.write(pixels)
    yaml_path = directory / f"{name}.yaml"
    yaml_path.write_text(
        f"image: {pgm.name}\n"
        f"resolution: {resolution}\n"
        f"origin: [{-scenario.map_size[0] / 2.0}, {-scenario.map_size[1] / 2.0}, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n",
        encoding="utf-8")
    return pgm, yaml_path
