"""Simulator-core tests. Not part of the main suite (`testpaths = ["tests"]`).

    pip install mujoco numpy pyyaml pytest
    sim/fetch_assets.sh /tmp/unitree && export G1SIM_ASSETS=/tmp/unitree
    python -m pytest sim/tests

The scenario and occupancy tests are pure Python and always run. The physics tests need
mujoco and the Unitree assets, and say so when either is missing rather than failing on
an import -- in the simulator image both are present, so nothing is skipped there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SIM_DIR = Path(__file__).resolve().parents[1]
REPO = SIM_DIR.parent
for path in (SIM_DIR, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _assets_or_skip():
    pytest.importorskip("mujoco")
    pytest.importorskip("yaml")
    from g1sim import assets
    try:
        return assets.assets_root()
    except FileNotFoundError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def assets_root():
    return _assets_or_skip()


@pytest.fixture(scope="module")
def sim(assets_root):
    from g1sim import G1Sim
    return G1Sim(str(assets_root))
