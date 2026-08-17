#!/usr/bin/env python3
"""Skill Center -- one control panel for every skill monitor on the DDS graph.

Deliberately standalone: it depends on ROS and Docker, NOT on the TRAV app. It
discovers monitors by scanning the ROS graph rather than being told about them, so
a skill that starts later, in another container, or on another machine, shows up
by itself. Nothing here imports anything from TRAV-metric-map.

    python3 skill_center.py                  # discover and control whatever is running
    python3 skill_center.py --demo           # fake monitor in-process, for UI work
    python3 skill_center.py --selftest       # headless logic check, no ROS, no Tk

Run it on a HOST, not inside trav_app: the container has no docker CLI and no
/var/run/docker.sock, so lifecycle control would be impossible from in there.

Discovery contract -- a monitor is anything publishing

    <ns>/ltl/state_description      (std_msgs/String, JSON)

where <ns> is empty for a single unnamespaced monitor. Companion topics
<ns>/ltl/required_aps and <ns>/ltl/evaluations are read when present. That is the
protocol main.py already speaks, so no monitor change is needed to appear here.
"""

import argparse
import json
import queue
import subprocess
import sys
import threading
import time

# Palette matched to the TRAV GUI so the two look like one system, copied rather
# than imported -- this app must not depend on that codebase.
BG, PANEL, CARD = "#0f141b", "#161d27", "#1d2734"
TEXT, MUTED, ACCENT = "#e5e7eb", "#9ca3af", "#3b82f6"
OK, OFF, BAD, WARN = "#22c55e", "#6b7280", "#ef4444", "#fbbf24"

STATE_TOPIC = "ltl/state_description"
STALE_AFTER = 5.0          # a monitor silent this long is presumed dead
POLL_SECS = 2.0            # graph rescan period


# ---------------------------------------------------------------- pure logic

def parse_namespaces(topic_names):
    """Namespaces of every discovered monitor, '' for the unnamespaced one.

    Pure so it can be tested without a ROS graph.
    """
    out = set()
    for t in topic_names:
        if t == "/" + STATE_TOPIC:
            out.add("")
        elif t.endswith("/" + STATE_TOPIC):
            out.add(t[: -len("/" + STATE_TOPIC)])
    return sorted(out)


def health(last_seen, now, stale_after=STALE_AFTER):
    """'live' | 'stale' | 'gone'. A monitor that has published and then stopped is
    NOT the same as one that never published: the first is a crash, the second is
    a stack that was never started, and the operator needs to tell them apart."""
    if last_seen is None:
        return "gone"
    return "live" if (now - last_seen) <= stale_after else "stale"


def summarize(desc):
    """One-line summary of a /ltl/state_description payload, for the card header."""
    if not desc:
        return "no data"
    if desc.get("state") == "halt":
        return f"HALTED — {desc.get('reason', '')}"
    if desc.get("state") == "idle":
        return f"IDLE — {desc.get('reason', '')}"
    phase = desc.get("phase") or "—"
    risk = desc.get("risk") or {}
    bits = [f"phase {phase}"]
    if risk.get("warn"):
        bits.append(f"WARN {risk.get('severity') or ''}".strip())
    sto = risk.get("steps_to_timeout")
    if sto is not None:
        bits.append(f"{sto} steps to timeout")
    conf = risk.get("trigger_confidence")
    if conf is not None and conf < 1.0:
        stale = ", ".join(risk.get("stale_sources") or []) or "?"
        bits.append(f"confidence {conf:.2f} (stale: {stale})")
    return "  ·  ".join(bits)


def docker_ps(run=subprocess.run):
    """Names of running containers, or None if Docker is unreachable. `run` is
    injected so this is testable without a daemon."""
    for cmd in (["docker", "ps", "--format", "{{.Names}}"],
                ["sudo", "-n", "docker", "ps", "--format", "{{.Names}}"]):
        try:
            p = run(cmd, capture_output=True, text=True, timeout=10)
        except Exception:
            continue
        if p.returncode == 0:
            return [n for n in p.stdout.split() if n]
    return None


# ---------------------------------------------------------------- ROS thread

class Discovery(threading.Thread):
    """Scans the graph, subscribes to every monitor it finds, and pushes
    ('state', ns, payload) / ('aps', ns, payload) tuples onto a queue.

    Never touches Tk. Same one-queue-plus-after() discipline the TRAV GUI uses.
    """

    def __init__(self, out_q, on_error=lambda m: None):
        super().__init__(daemon=True)
        self.q = out_q
        self.on_error = on_error
        self._reset_q = queue.Queue()
        self._stop = threading.Event()
        self._subscribed = {}

    def request_reset(self, ns):
        """Re-arm a monitor sitting IDLE. This is the engine's existing protocol
        ({"__reset__": true} on /ltl/evaluations), not a new control channel."""
        self._reset_q.put(ns)

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import String
        except Exception as exc:
            self.on_error(f"ROS unavailable: {exc}")
            return

        # Only own the context if nobody else does -- --demo and any embedding
        # process may already have initialised rclpy, and a second init raises.
        own_context = not rclpy.ok()
        if own_context:
            rclpy.init()
        try:
            self._loop(rclpy, Node, String)
        except Exception as exc:                 # a dead thread must not be silent
            self.on_error(f"discovery stopped: {exc}")
        finally:
            if own_context and rclpy.ok():
                rclpy.shutdown()

    def _loop(self, rclpy, Node, String):
        node = Node("skill_center")
        reset_pubs = {}
        last_scan = 0.0

        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_scan >= POLL_SECS:
                last_scan = now
                try:
                    names = [t for t, _ in node.get_topic_names_and_types()]
                except Exception:
                    names = []
                found = parse_namespaces(names)
                self.q.put(("discovered", None, found))
                for ns in found:
                    if ns in self._subscribed:
                        continue
                    node.create_subscription(
                        String, f"{ns}/{STATE_TOPIC}",
                        (lambda m, _n=ns: self._emit("state", _n, m.data)), 10)
                    node.create_subscription(
                        String, f"{ns}/ltl/required_aps",
                        (lambda m, _n=ns: self._emit("aps", _n, m.data)), 10)
                    reset_pubs[ns] = node.create_publisher(
                        String, f"{ns}/ltl/evaluations", 10)
                    self._subscribed[ns] = True

            try:
                while True:
                    ns = self._reset_q.get_nowait()
                    pub = reset_pubs.get(ns)
                    if pub is not None:
                        pub.publish(String(data=json.dumps({"__reset__": True})))
            except queue.Empty:
                pass

            rclpy.spin_once(node, timeout_sec=0.1)

        node.destroy_node()

    def _emit(self, kind, ns, raw):
        try:
            self.q.put((kind, ns, json.loads(raw)))
        except Exception:
            pass


# ---------------------------------------------------------------- containers

class Containers:
    """Lifecycle control for the monitor stack. Every call degrades to a message
    rather than an exception when Docker is absent -- the panel must stay useful
    read-only on a machine that cannot run containers."""

    def __init__(self, names, run=subprocess.run):
        self.names = list(names)
        self._run = run

    def _docker(self, *args):
        last = ""
        for prefix in (["docker"], ["sudo", "-n", "docker"]):
            try:
                p = self._run(prefix + list(args), capture_output=True,
                              text=True, timeout=60)
            except Exception as exc:
                # Keep trying: `docker` missing from PATH does not mean `sudo docker`
                # is missing too, and on this fleet every script uses the sudo form.
                last = str(exc)
                continue
            if p.returncode == 0:
                return True, p.stdout.strip()
            last = (p.stderr or p.stdout or "").strip()
        return False, f"docker unavailable ({last or 'not installed, or sudo needs a password'})"

    def running(self):
        names = docker_ps(self._run)
        if names is None:
            return None
        return [n for n in self.names if n in names]

    def start(self, name):
        return self._docker("start", name)

    def stop(self, name):
        return self._docker("stop", name)


# ---------------------------------------------------------------- Tk panel

def run_gui(args):
    import tkinter as tk

    q = queue.Queue()
    disc = Discovery(q)
    containers = Containers(args.containers)
    state = {}          # ns -> {"desc":…, "aps":[…], "last":monotonic}
    discovered = []

    root = tk.Tk()
    root.title("Skill Center")
    root.configure(bg=BG)
    root.geometry("760x560")

    head = tk.Frame(root, bg=PANEL)
    head.pack(fill=tk.X)
    tk.Label(head, text="Skill Center", bg=PANEL, fg=TEXT,
             font=("TkDefaultFont", 13, "bold")).pack(side=tk.LEFT, padx=12, pady=10)
    hint = tk.Label(head, text="scanning…", bg=PANEL, fg=MUTED)
    hint.pack(side=tk.LEFT, padx=6)

    ctr_bar = tk.Frame(root, bg=PANEL)
    ctr_bar.pack(fill=tk.X)
    ctr_labels = {}
    for name in args.containers:
        row = tk.Frame(ctr_bar, bg=PANEL)
        row.pack(side=tk.LEFT, padx=(12, 4), pady=6)
        dot = tk.Canvas(row, width=12, height=12, bg=PANEL, highlightthickness=0)
        dot.create_oval(1, 1, 11, 11, fill=OFF, outline="", tags="d")
        dot.pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(row, text=name, bg=PANEL, fg=TEXT).pack(side=tk.LEFT)
        for label, fn in (("start", containers.start), ("stop", containers.stop)):
            tk.Button(row, text=label, bg=CARD, fg=TEXT, relief=tk.FLAT, padx=6,
                      command=(lambda f=fn, n=name: _do(f, n))).pack(side=tk.LEFT, padx=2)
        ctr_labels[name] = dot

    body = tk.Frame(root, bg=BG)
    body.pack(fill=tk.BOTH, expand=True)
    cards = {}

    def _do(fn, name):
        okk, msg = fn(name)
        hint.config(text=msg if not okk else f"{name}: ok", fg=TEXT if okk else BAD)

    def _card(ns):
        f = tk.Frame(body, bg=CARD)
        f.pack(fill=tk.X, padx=12, pady=(10, 0))
        top = tk.Frame(f, bg=CARD)
        top.pack(fill=tk.X, padx=12, pady=(10, 4))
        dot = tk.Canvas(top, width=14, height=14, bg=CARD, highlightthickness=0)
        dot.create_oval(1, 1, 13, 13, fill=OFF, outline="", tags="d")
        dot.pack(side=tk.LEFT, padx=(0, 8))
        title = tk.Label(top, text=ns or "(default)", bg=CARD, fg=TEXT,
                         font=("TkDefaultFont", 11, "bold"))
        title.pack(side=tk.LEFT)
        tk.Button(top, text="arm / reset", bg=CARD, fg=TEXT, relief=tk.FLAT, padx=8,
                  command=(lambda _n=ns: disc.request_reset(_n))).pack(side=tk.RIGHT)
        sub = tk.Label(f, text="", bg=CARD, fg=MUTED, anchor="w", justify=tk.LEFT)
        sub.pack(fill=tk.X, padx=12)
        aps = tk.Label(f, text="", bg=CARD, fg=MUTED, anchor="w", justify=tk.LEFT,
                       font=("TkFixedFont", 9))
        aps.pack(fill=tk.X, padx=12, pady=(4, 10))
        return {"frame": f, "dot": dot, "title": title, "sub": sub, "aps": aps}

    def tick():
        try:
            while True:
                kind, ns, payload = q.get_nowait()
                if kind == "discovered":
                    discovered[:] = payload
                elif kind == "state":
                    state.setdefault(ns, {})["desc"] = payload
                    state[ns]["last"] = time.monotonic()
                elif kind == "aps":
                    state.setdefault(ns, {})["aps"] = payload
        except queue.Empty:
            pass

        now = time.monotonic()
        hint.config(
            text=(f"{len(discovered)} skill monitor(s) on the graph"
                  if discovered else
                  "no skill monitor detected — is the monitor container running?"),
            fg=TEXT if discovered else MUTED)

        for ns in discovered:
            if ns not in cards:
                cards[ns] = _card(ns)
            c = cards[ns]
            st = state.get(ns, {})
            desc = st.get("desc") or {}
            h = health(st.get("last"), now)
            c["dot"].itemconfig("d", fill={"live": OK, "stale": WARN, "gone": OFF}[h])
            name = desc.get("skill_name") or ns or "(unknown skill)"
            c["title"].config(text=f"{name}   [{h}]")
            c["sub"].config(
                text=summarize(desc),
                fg=BAD if (desc.get("risk") or {}).get("warn") else MUTED)
            ap_names = st.get("aps") or []
            c["aps"].config(text="APs: " + (", ".join(ap_names) if ap_names else "—"))

        running = containers.running()
        for name, dot in ctr_labels.items():
            dot.itemconfig("d", fill=OFF if running is None
                           else (OK if name in running else BAD))

        root.after(500, tick)

    disc.start()
    if args.demo:
        threading.Thread(target=_demo_publisher, daemon=True).start()
    root.after(500, tick)
    root.protocol("WM_DELETE_WINDOW", lambda: (disc.stop(), root.destroy()))
    root.mainloop()


def _demo_publisher():
    """Publish a plausible monitor so the panel can be exercised with no stack."""
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    if not rclpy.ok():
        rclpy.init()
    node = Node("skill_center_demo")
    sp = node.create_publisher(String, "/ltl/state_description", 10)
    ap = node.create_publisher(String, "/ltl/required_aps", 10)
    phases = ["PlanningAndInitiation", "ExecutionAndTracking", "VisualGoalConfirmation"]
    i = 0
    while rclpy.ok():
        d = {"skill_name": "G1HumanoidNavigation", "phase": phases[(i // 8) % 3],
             "risk": {"steps_to_timeout": 30 - (i % 30), "violations_to_fault": 5,
                      "trigger_confidence": 1.0 if i % 20 < 15 else 0.67,
                      "stale_sources": [] if i % 20 < 15 else ["points"],
                      "warn": (i % 30) > 26, "severity": "TIMEOUT" if (i % 30) > 26 else None}}
        sp.publish(String(data=json.dumps(d)))
        ap.publish(String(data=json.dumps(
            ["mission_started", "path_active", "nav_stuck", "collision_risk"])))
        i += 1
        time.sleep(0.5)


# ---------------------------------------------------------------- selftest

def _selftest():
    assert parse_namespaces(["/ltl/state_description"]) == [""]
    assert parse_namespaces(["/nav/ltl/state_description",
                             "/pick/ltl/state_description"]) == ["/nav", "/pick"]
    # A topic that merely CONTAINS the name must not be mistaken for a monitor.
    assert parse_namespaces(["/ltl/state_description_debug", "/other"]) == []
    assert parse_namespaces([]) == []

    # never-published and stopped-publishing must be distinguishable
    assert health(None, 100.0) == "gone"
    assert health(99.0, 100.0) == "live"
    assert health(50.0, 100.0) == "stale"

    assert summarize({}) == "no data"
    assert "HALTED" in summarize({"state": "halt", "reason": "fell"})
    assert "IDLE" in summarize({"state": "idle", "reason": "done"})
    s = summarize({"phase": "Exec", "risk": {"warn": True, "severity": "TIMEOUT",
                                             "steps_to_timeout": 2}})
    assert "phase Exec" in s and "WARN TIMEOUT" in s and "2 steps" in s
    s = summarize({"phase": "Exec", "risk": {"trigger_confidence": 0.67,
                                             "stale_sources": ["points"]}})
    assert "confidence 0.67" in s and "points" in s, s

    class _P:
        def __init__(self, rc, out=""): self.returncode, self.stdout = rc, out

    assert docker_ps(lambda *a, **k: _P(0, "ltl-monitor\nltl-client\n")) == \
        ["ltl-monitor", "ltl-client"]
    assert docker_ps(lambda *a, **k: _P(1)) is None          # daemon refuses
    def _boom(*a, **k): raise FileNotFoundError("docker")
    assert docker_ps(_boom) is None                          # not installed

    c = Containers(["ltl-monitor"], run=lambda *a, **k: _P(0, "ltl-monitor\n"))
    assert c.running() == ["ltl-monitor"]
    assert c.start("ltl-monitor")[0] is True
    c_bad = Containers(["ltl-monitor"], run=_boom)
    assert c_bad.running() is None
    okk, msg = c_bad.stop("ltl-monitor")
    assert okk is False and "docker unavailable" in msg

    print("selftest OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--containers", nargs="*",
                    default=["ltl-monitor", "ltl-client"],
                    help="container names to show lifecycle controls for")
    ap.add_argument("--demo", action="store_true",
                    help="publish a fake monitor in-process, for UI work with no stack")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
