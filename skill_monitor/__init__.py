"""Skill Monitor -- runtime progress monitoring for robot skills.

Layers, strictly one-directional (core knows nothing about the layers above it):

    core/       pure logic. No ROS, no Tk, no network. Unit-testable anywhere:
                Buchi automata, the spec-contract oracle, guard/threshold helpers.
    backend/    the ROS layer. Monitor + evaluator nodes, and adapters/ -- one per
                embodiment, each declaring the sensor schema that embodiment offers.
    frontend/   the operator surface. Skill Center control panel.
    describer/  free-language skill description -> validated formulas_<skill>.json.
    specs/      the specs themselves.
"""

from pathlib import Path

SPECS_DIR = Path(__file__).parent / "specs"


def spec_path(name: str) -> Path:
    """Locate a bundled spec by file name or bare skill label.

    Everything that needs a spec -- tests, the engine's --formulas-file default,
    the describer's output target, the Docker images -- goes through here, so the
    specs can move without another hunt through relative paths.
    """
    p = SPECS_DIR / (name if name.endswith(".json") else f"formulas_{name}.json")
    if not p.exists():
        available = sorted(q.name for q in SPECS_DIR.glob("*.json"))
        raise FileNotFoundError(f"no spec {p.name!r} in {SPECS_DIR} (have: {available})")
    return p
