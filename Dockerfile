# The whole stack in one image. Same command on every machine:
#
#   docker run --rm -p 8080:8080 ghcr.io/pinhas019/ltlmonitor-demo      # then open http://localhost:8080
#
# Inside: ROS 2 Humble (RoboStack), Spot, MuJoCo with Unitree's G1 and walking policy,
# and sim/stack.py -- the evaluator and the monitor as their own ROS 2 processes, the
# simulated robot and task as a driver node, and a web page that renders the robot
# off-screen (OSMesa: no GPU, no display). Other entry points, same image:
#
#   docker run --rm ghcr.io/pinhas019/ltlmonitor-demo python sim/demo_e1b.py --no-view --fault drop
#   docker run --rm ghcr.io/pinhas019/ltlmonitor-demo python -m pytest -q -p no:launch_testing -p no:launch_ros sim/tests
FROM mambaorg/micromamba:1.5.10

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libosmesa6 libgl1 libegl1 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Unitree's 12-DoF G1 and its pretrained walking policy, at a pinned commit (sim/NOTICE).
COPY sim/fetch_assets.sh /tmp/fetch_assets.sh
RUN bash /tmp/fetch_assets.sh /opt/unitree && chown -R $MAMBA_USER:$MAMBA_USER /opt/unitree

USER $MAMBA_USER
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && micromamba clean --all --yes

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER pyproject.toml ./
COPY --chown=$MAMBA_USER:$MAMBA_USER skill_monitor ./skill_monitor
COPY --chown=$MAMBA_USER:$MAMBA_USER sim ./sim
COPY --chown=$MAMBA_USER:$MAMBA_USER tests ./tests

ENV G1SIM_ASSETS=/opt/unitree \
    MUJOCO_GL=osmesa \
    PYOPENGL_PLATFORM=osmesa \
    ROS_LOCALHOST_ONLY=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["python", "sim/stack.py", "--host", "0.0.0.0", "--port", "8080"]
