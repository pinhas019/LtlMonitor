"""Generate procedural scenarios into a directory (see g1sim/generator.py).

    python3 sim/generate_scenarios.py --family clear weaken stall --seeds 0-19 \
        --out sim/scenarios/generated

The episode runner then takes the directory: `ablation_runner --scenario-dir ...`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from g1sim.generator import main                        # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
