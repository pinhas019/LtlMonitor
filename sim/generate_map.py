"""Nav2's startup map, generated from a scenario -- the same file the simulator loads.

    python3 generate_map.py --scenario scenarios/clear.json --out /maps
    python3 generate_map.py --scenario scenarios/clear.json --print-goal   # "x y"

Replaces the version that read obstacles out of `<body>` elements in arena.xml while the
lidar only saw worldbody geoms. The bridge rewrites the same map on every reset; this
script exists so map_server has one before the bridge's first reset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from g1sim import load                                  # noqa: E402
from g1sim.occupancy import write_map                   # noqa: E402

MAP_RESOLUTION_M = 0.05          # matches mujoco_ros_bridge.MAP_RESOLUTION_M


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scenario", default="scenarios/clear.json")
    parser.add_argument("--out", default="/maps")
    parser.add_argument("--print-goal", action="store_true",
                        help="print the scenario's first goal as 'x y' and exit")
    args = parser.parse_args(argv)

    scenario = load(args.scenario)
    if args.print_goal:
        x, y = scenario.goals[0]
        print(f"{x} {y}")
        return 0
    pgm, yaml_path = write_map(scenario, args.out, resolution=MAP_RESOLUTION_M)
    print(f"map for scenario {scenario.name!r}: {yaml_path} ({pgm.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
