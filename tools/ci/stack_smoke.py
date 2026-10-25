"""Smoke-test a running stack (sim/stack.py) over HTTP: it comes up, runs the dropped-
object scenario with the full spec, the monitor raises the Carry alarm, and the live
view serves a JPEG. Standard library only; used by .github/workflows/demo-image.yml.

    python tools/ci/stack_smoke.py --url http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read()


def status(base):
    return json.loads(get(base + "/status"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    base, end = args.url.rstrip("/"), time.monotonic() + args.timeout

    s = {}
    while time.monotonic() < end:
        try:
            s = status(base)
            if s.get("stack") == "ready":
                break
        except Exception:                                         # noqa: BLE001
            pass
        time.sleep(2)
    else:
        print(f"FAIL: stack never ready: {s}")
        return 1
    print("stack ready; graph:", s.get("graph"))
    nodes = set((s.get("graph") or {}).get("nodes") or [])

    body = json.dumps({"fault": "drop", "spec": "full", "policy": "off", "seed": 0,
                       "speed": 10}).encode()
    req = urllib.request.Request(base + "/run", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()
    while time.monotonic() < end:
        s = status(base)
        if s.get("result"):
            break
        if s.get("error"):
            print("FAIL: episode error:", s["error"])
            return 1
        time.sleep(2)
    log = "\n".join(s.get("log", []))
    print(log[-1500:])
    print("result:", s.get("result"))
    nodes |= set((s.get("graph") or {}).get("nodes") or [])
    ok = True
    for need, what in (("Carry phase broken", "the monitor's Carry alarm"),
                       ("FAILED (false_arrival)", "the ground-truth failure")):
        if need not in log + (s.get("result") or ""):
            print(f"FAIL: missing {what} ({need!r})")
            ok = False
    for node in ("ltl_generic_client", "ltl_monitor_node", "e1b_driver"):
        if node not in nodes:
            print(f"FAIL: ROS node {node} not in the graph {sorted(nodes)}")
            ok = False
    frame = get(base + "/frame.jpg")
    if frame[:2] != b"\xff\xd8":
        print("FAIL: /frame.jpg is not a JPEG")
        ok = False
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
