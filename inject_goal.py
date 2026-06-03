#!/usr/bin/env python3
"""
inject_goal.py — Send navigation goals to Nav2 from the host terminal.

Runs on the host (no ROS 2 required).  Injects goals into the running
ltl-nav2 container via `docker exec`.

Usage:
    python3 inject_goal.py              # interactive loop
    python3 inject_goal.py 3.0 2.0     # send a single goal and exit
"""

import subprocess
import sys

CONTAINER = "ltl-nav2"
SCRIPT    = "/app/send_goal.py"


def send_goal(x: float, y: float) -> bool:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", SCRIPT, str(x), str(y)],
    )
    return result.returncode == 0


def main():
    # Single-shot mode: python3 inject_goal.py x y
    if len(sys.argv) == 3:
        try:
            x, y = float(sys.argv[1]), float(sys.argv[2])
        except ValueError:
            print("Usage: inject_goal.py [x y]", file=sys.stderr)
            sys.exit(1)
        ok = send_goal(x, y)
        sys.exit(0 if ok else 1)

    if len(sys.argv) != 1:
        print("Usage: inject_goal.py [x y]", file=sys.stderr)
        sys.exit(1)

    # Interactive loop
    print(f"Nav2 Goal Injector  (container: {CONTAINER})")
    print("Type  x y  to send a goal, or 'q' to quit.\n")

    while True:
        try:
            raw = input("Goal (x y) > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            break

        parts = raw.split()
        if len(parts) != 2:
            print("  Enter exactly two numbers, e.g.:  3.0 2.0")
            continue

        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            print("  Invalid numbers. Try:  3.0 2.0")
            continue

        print(f"  → Sending goal ({x}, {y}) to Nav2 ...")
        ok = send_goal(x, y)
        if ok:
            print(f"  ✔ Goal ({x}, {y}) accepted")
        else:
            print(f"  ✘ Failed — is '{CONTAINER}' running?  (docker ps)")


if __name__ == "__main__":
    main()
