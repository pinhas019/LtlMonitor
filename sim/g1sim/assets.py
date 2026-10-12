"""Where Unitree's G1 assets live. Fetched, never vendored: run `sim/fetch_assets.sh`."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ROOT = "/opt/unitree_rl_gym"
ENV_VAR = "G1SIM_ASSETS"

MODEL_XML = "resources/robots/g1_description/g1_12dof.xml"
POLICY = "deploy/pre_train/g1/motion.pt"
LOCOMOTION_CONFIG = "deploy/deploy_mujoco/configs/g1.yaml"


def assets_root(path: str | os.PathLike | None = None) -> Path:
    """The asset directory: `path`, else $G1SIM_ASSETS, else /opt/unitree_rl_gym."""
    root = Path(path or os.environ.get(ENV_VAR) or DEFAULT_ROOT)
    missing = [rel for rel in (MODEL_XML, POLICY, LOCOMOTION_CONFIG)
               if not (root / rel).is_file()]
    if missing:
        raise FileNotFoundError(
            f"G1 assets incomplete under {root} (missing {', '.join(missing)}). "
            f"Run `sim/fetch_assets.sh {root}` or set {ENV_VAR}.")
    return root


def model_xml(root: Path) -> Path:
    return root / MODEL_XML


def policy_path(root: Path) -> Path:
    return root / POLICY


def locomotion_config(root: Path) -> Path:
    return root / LOCOMOTION_CONFIG
