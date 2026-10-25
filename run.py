#!/usr/bin/env python3
"""One command for the whole stack, on any machine.

    python3 run.py                  # then the browser opens http://localhost:8080
    python3 run.py --text           # the same demo in the terminal, no browser
    python3 run.py --text -- --fault wrong_dropoff --spec closed_loop

With Docker installed, this runs the published image (ghcr.io/pinhas019/ltlmonitor-demo;
built from ./Dockerfile if the pull fails). Without Docker, on Linux or macOS, the first
run sets up a private environment in ./.ltl -- micromamba, ROS 2 Humble (RoboStack),
Spot, MuJoCo and Unitree's G1 model (a few minutes on a fast network, ~2.5 GB) -- and later runs start at
once. Windows without Docker is not supported: Spot has no Windows build.

What starts: the evaluator and the monitor as their own ROS 2 processes, the simulated G1
doing fetch-and-deliver as the driver node, and a web page showing the robot, the
monitor's phase and alarms, and the simulator's ground truth (sim/stack.py).

Only the Python standard library is used here.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = "ghcr.io/pinhas019/ltlmonitor-demo:latest"
LOCAL_IMAGE = "ltl-demo"
LTL = ROOT / ".ltl"


def say(msg: str) -> None:
    print(f"[run.py] {msg}", flush=True)


def wait_and_open(url: str, open_browser: bool, timeout: float = 600) -> None:
    """Open the browser once the stack answers."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url + "/status", timeout=2) as r:
                if json.load(r).get("stack") in ("ready", "running"):
                    say(f"ready: {url}")
                    if open_browser:
                        webbrowser.open(url)
                    return
        except Exception:                                         # noqa: BLE001
            pass
        time.sleep(1)


# ----------------------------------------------------------------------- Docker

def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_docker(args) -> int:
    image = IMAGE
    say(f"Docker found: pulling {IMAGE}")
    if subprocess.run(["docker", "pull", IMAGE]).returncode != 0:
        say(f"pull failed; building {LOCAL_IMAGE} from ./Dockerfile (once, ~10 min)")
        if subprocess.run(["docker", "build", "-t", LOCAL_IMAGE, str(ROOT)]).returncode != 0:
            return 1
        image = LOCAL_IMAGE
    tty = ["-it"] if sys.stdin.isatty() else []
    if args.text:
        cmd = ["docker", "run", "--rm", *tty, image, "python", "sim/demo_e1b.py", "--no-view",
               *args.rest]
        return subprocess.run(cmd).returncode
    url = f"http://localhost:{args.port}"
    threading.Thread(target=wait_and_open, args=(url, not args.no_browser), daemon=True).start()
    say(f"starting the stack; it opens at {url} (Ctrl+C to stop)")
    cmd = ["docker", "run", "--rm", *tty, "-p", f"{args.port}:8080", image]
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


# ------------------------------------------------------------------ local setup

def conda_platform() -> str:
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Linux":
        return "linux-aarch64" if arm else "linux-64"
    if system == "Darwin":
        return "osx-arm64" if arm else "osx-64"
    raise SystemExit("Without Docker this runs on Linux or macOS only (Spot has no Windows "
                     "build). On Windows: install Docker Desktop, then run this again.")


def micromamba() -> Path:
    exe = LTL / "bin" / "micromamba"
    if exe.exists():
        return exe
    plat = conda_platform()
    exe.parent.mkdir(parents=True, exist_ok=True)
    # The official release binary on GitHub first; micro.mamba.pm (a tarball) as fallback.
    binary = ("https://github.com/mamba-org/micromamba-releases/releases/latest/download/"
              f"micromamba-{plat}")
    try:
        say(f"downloading micromamba for {plat}")
        urllib.request.urlretrieve(binary, exe)
    except Exception as exc:                                      # noqa: BLE001
        say(f"GitHub download failed ({exc}); trying micro.mamba.pm")
        archive = LTL / "micromamba.tar.bz2"
        urllib.request.urlretrieve(f"https://micro.mamba.pm/api/micromamba/{plat}/latest",
                                   archive)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extract(tar.getmember("bin/micromamba"), LTL)
        archive.unlink()
    exe.chmod(0o755)
    return exe


def setup_local() -> Path:
    """The environment and the assets, once. Returns the environment's python."""
    env = LTL / "env"
    py = env / "bin" / "python"
    stamp = LTL / "env.ok"
    if not stamp.exists():
        mm = micromamba()
        say("creating the environment (ROS 2 Humble, Spot, MuJoCo); once, ~10 minutes")
        menv = dict(os.environ, MAMBA_ROOT_PREFIX=str(LTL / "root"))
        if subprocess.run([str(mm), "create", "-y", "-p", str(env), "-f",
                           str(ROOT / "environment.yml")], env=menv).returncode != 0:
            raise SystemExit("environment creation failed (see above)")
        # The package cache is ~0.8 GB that nothing reads again.
        subprocess.run([str(mm), "clean", "--all", "-y"], env=menv, capture_output=True)
        stamp.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    assets = LTL / "unitree"
    if not (assets / "LICENSE").exists():
        say("fetching Unitree's G1 model and walking policy")
        if subprocess.run(["bash", str(ROOT / "sim" / "fetch_assets.sh"), str(assets)]).returncode:
            raise SystemExit("fetching the assets failed (needs git and network)")
    return py


def run_local(args) -> int:
    py = setup_local()
    env = dict(os.environ, G1SIM_ASSETS=str(LTL / "unitree"), PYTHONUNBUFFERED="1")
    if platform.system() == "Linux" and not (os.environ.get("DISPLAY")
                                             or os.environ.get("WAYLAND_DISPLAY")):
        env.setdefault("MUJOCO_GL", "osmesa")        # headless: software rendering
        env.setdefault("PYOPENGL_PLATFORM", "osmesa")
    if args.text:
        return subprocess.run([str(py), "sim/demo_e1b.py", "--no-view", *args.rest],
                              cwd=ROOT, env=env).returncode
    url = f"http://localhost:{args.port}"
    threading.Thread(target=wait_and_open, args=(url, not args.no_browser), daemon=True).start()
    say(f"starting the stack; it opens at {url} (Ctrl+C to stop)")
    try:
        return subprocess.run([str(py), "sim/stack.py", "--port", str(args.port)],
                              cwd=ROOT, env=env).returncode
    except KeyboardInterrupt:
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the whole LTL-monitor stack.")
    parser.add_argument("--text", action="store_true",
                        help="the terminal demo instead of the web page")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--docker", action="store_true", help="use Docker (the default if found)")
    where.add_argument("--local", action="store_true", help="use the local environment")
    parser.add_argument("rest", nargs=argparse.REMAINDER,
                        help="after --, options for the text demo (e.g. --fault drop)")
    args = parser.parse_args(argv)
    if args.rest and args.rest[0] == "--":
        args.rest = args.rest[1:]
    if args.docker or (not args.local and docker_available()):
        return run_docker(args)
    return run_local(args)


if __name__ == "__main__":
    raise SystemExit(main())
