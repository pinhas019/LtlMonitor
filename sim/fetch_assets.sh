#!/usr/bin/env bash
# Fetch the Unitree G1 assets the simulator walks with, at a pinned commit.
#
#   sim/fetch_assets.sh [DEST]          DEST defaults to /opt/unitree_rl_gym
#
# From unitreerobotics/unitree_rl_gym (BSD-3-Clause, see DEST/LICENSE and sim/NOTICE):
#   resources/robots/g1_description/   g1_12dof.xml, scene.xml, meshes
#   deploy/pre_train/g1/motion.pt      the pretrained walking policy (TorchScript)
#   deploy/deploy_mujoco/              their sim2sim script and g1.yaml, kept as the
#                                      reference sim/g1sim/locomotion.py reproduces
#
# Pinned, not `main`: the policy and the model it was trained on must not drift apart
# underneath an experiment. Point G1SIM_ASSETS at DEST.
set -euo pipefail

COMMIT="276801e46c5d433564f24658bac64f254b7d2d4b"
REPO="https://github.com/unitreerobotics/unitree_rl_gym.git"
DEST="${1:-/opt/unitree_rl_gym}"

if [ -f "$DEST/.fetched-$COMMIT" ]; then
    echo "unitree assets already at $DEST ($COMMIT)"
    exit 0
fi

rm -rf "$DEST"
git init -q "$DEST"
git -C "$DEST" remote add origin "$REPO"
git -C "$DEST" config core.sparseCheckout true
git -C "$DEST" sparse-checkout set --no-cone \
    /LICENSE \
    /resources/robots/g1_description/ \
    /deploy/pre_train/g1/ \
    /deploy/deploy_mujoco/
git -C "$DEST" fetch -q --depth 1 --filter=blob:none origin "$COMMIT"
git -C "$DEST" checkout -q FETCH_HEAD

for required in LICENSE \
                resources/robots/g1_description/g1_12dof.xml \
                deploy/pre_train/g1/motion.pt \
                deploy/deploy_mujoco/configs/g1.yaml; do
    if [ ! -f "$DEST/$required" ]; then
        echo "fetch_assets: $required missing after checkout of $COMMIT" >&2
        exit 1
    fi
done
rm -rf "$DEST/.git"
touch "$DEST/.fetched-$COMMIT"
echo "unitree assets fetched to $DEST ($COMMIT)"
