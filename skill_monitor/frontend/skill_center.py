#!/usr/bin/env python3
"""Skill Center -- one control panel for every skill monitor on the DDS graph.

Deliberately standalone: it depends on ROS and Docker, NOT on the TRAV app, and not
on any particular skill or robot. Everything it renders comes off the wire:

    <ns>/ltl/manifest            (latched) the skill: APs, formulas, phases, terminals
    <ns>/ltl/adapter             (latched) the robot: sensor schema, topic map
    <ns>/ltl/state_description   per tick: phase, AP values, sensor values, risk
    <ns>/ltl/spec_status         the monitor's verdict on a pushed spec
    <ns>/ltl/evaluations         reset signal out
    <ns>/ltl/load_spec           a new spec in

There is no navigation-specific widget here, and no import of a spec or schema from
disk: a manipulation monitor with an entirely different vocabulary renders with no
change. That is the point -- if this file had to know the skill, the engine's
skill-agnosticism would be a claim the operator surface quietly contradicts.

    python3 -m skill_monitor.frontend.skill_center            # the real graph
    python3 -m skill_monitor.frontend.skill_center --mock     # no ROS at all
    python3 -m skill_monitor.frontend.skill_center --selftest # headless, no Tk

Run it on a HOST, not inside trav_app: the container has no docker CLI and no
/var/run/docker.sock, so lifecycle control would be impossible from in there.
"""

import argparse
import json
import math
import queue
import subprocess
import sys
import threading
import time

from skill_monitor.core import manifest as manifest_mod

# Palette matched to the TRAV GUI so the two look like one system, copied rather
# than imported -- this app must not depend on that codebase.
BG, PANEL, CARD = "#0f141b", "#161d27", "#1d2734"
TEXT, MUTED, ACCENT = "#e5e7eb", "#9ca3af", "#3b82f6"
OK, OFF, BAD, WARN = "#22c55e", "#6b7280", "#ef4444", "#fbbf24"

STATE_TOPIC = "ltl/state_description"
STALE_AFTER = 5.0          # a monitor silent this long is presumed dead
POLL_SECS = 2.0            # graph rescan period
MAX_EVENTS = 500           # per monitor; the timeline is a window, not a log file


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


def timeline_events(prev, new):
    """What changed between two state_description payloads, as (severity, text).

    Pure, and the only place the timeline's content is decided -- an episode log
    assembled by diffing the live state means the monitor needs no extra topic and
    no memory of what a given client has already seen.

    severity: 'info' | 'warn' | 'bad'.
    """
    prev, new = prev or {}, new or {}
    out = []

    if new.get("state") == "halt" and prev.get("state") != "halt":
        out.append(("bad", f"HALTED — {new.get('reason', '')}"))
    if new.get("state") == "idle" and prev.get("state") != "idle":
        out.append(("info", f"IDLE — {new.get('reason', '')}"))
    # Coming back from idle/halt is the start of a new episode, worth a marker.
    if prev.get("state") in ("idle", "halt") and new.get("state") not in ("idle", "halt"):
        out.append(("info", "— new episode —"))

    if new.get("phase") and new.get("phase") != prev.get("phase"):
        out.append(("info", f"phase → {new['phase']}"))

    prev_modes = {m["name"]: m.get("status") for m in prev.get("named_failure_modes") or []}
    for m in new.get("named_failure_modes") or []:
        was, now_ = prev_modes.get(m["name"]), m.get("status")
        if was is not None and now_ != was:
            sev = "bad" if now_ == "VIOLATED" else "info"
            out.append((sev, f"failure mode {m['name']}: {was} → {now_}"))

    risk, prev_risk = new.get("risk") or {}, prev.get("risk") or {}
    if risk.get("warn") and not prev_risk.get("warn"):
        out.append(("warn", f"WARN {risk.get('severity') or ''} "
                            f"({risk.get('steps_to_timeout')} steps to timeout, "
                            f"{risk.get('violations_to_fault')} violations to fault)"))

    conf, prev_conf = risk.get("trigger_confidence"), prev_risk.get("trigger_confidence")
    if conf is not None and conf < 1.0 and (prev_conf is None or prev_conf >= 1.0):
        out.append(("warn", "confidence %.2f — stale: %s" % (
            conf, ", ".join(risk.get("stale_sources") or []) or "?")))
    elif conf == 1.0 and prev_conf is not None and prev_conf < 1.0:
        out.append(("info", "sensors fresh again"))

    step = new.get("step")
    prefix = f"[{step:>4}] " if isinstance(step, int) else ""
    return [(sev, prefix + text) for sev, text in out]


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


class Monitors:
    """Everything known about every monitor on the graph. No Tk, no ROS -- the panel
    renders this, and the selftest drives it."""

    def __init__(self):
        self.by_ns = {}
        self.order = []

    def _slot(self, ns):
        if ns not in self.by_ns:
            self.by_ns[ns] = {"desc": {}, "manifest": {}, "adapter": {}, "aps": [],
                              "spec_status": None, "last": None, "events": []}
            if ns not in self.order:
                self.order.append(ns)
        return self.by_ns[ns]

    def discovered(self, namespaces):
        for ns in namespaces:
            self._slot(ns)
        self.order = [ns for ns in self.order if ns in self.by_ns]
        return self.order

    def apply(self, kind, ns, payload, now=None):
        slot = self._slot(ns)
        if kind == "state":
            events = timeline_events(slot["desc"], payload)
            slot["events"].extend(events)
            del slot["events"][:-MAX_EVENTS]
            slot["desc"] = payload
            slot["last"] = time.monotonic() if now is None else now
            return events
        if kind in ("manifest", "adapter", "aps", "spec_status"):
            slot[kind] = payload
        return []

    def get(self, ns):
        return self._slot(ns)


# ---------------------------------------------------------------- ROS thread

class Discovery(threading.Thread):
    """Scans the graph, subscribes to every monitor it finds, and pushes
    (kind, ns, payload) tuples onto a queue.

    Never touches Tk. Same one-queue-plus-after() discipline the TRAV GUI uses.
    """

    #: subscribed topic suffix -> queue message kind
    TOPICS = {
        STATE_TOPIC: "state",
        "ltl/manifest": "manifest",
        "ltl/adapter": "adapter",
        "ltl/required_aps": "aps",
        "ltl/spec_status": "spec_status",
    }

    def __init__(self, out_q, on_error=lambda m: None):
        super().__init__(daemon=True)
        self.q = out_q
        self.on_error = on_error
        self._out = queue.Queue()      # (ns, topic_suffix, json-string) to publish
        self._stop = threading.Event()
        self._subscribed = {}

    def request_reset(self, ns):
        """Re-arm a monitor sitting IDLE. This is the engine's existing protocol
        ({"__reset__": true} on /ltl/evaluations), not a new control channel."""
        self._out.put((ns, "ltl/evaluations", json.dumps({"__reset__": True})))

    def push_spec(self, ns, spec):
        self._out.put((ns, "ltl/load_spec", json.dumps(spec)))

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

        # Only own the context if nobody else does -- any embedding
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
        from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                               ReliabilityPolicy)

        # The manifests are published TRANSIENT_LOCAL, so a VOLATILE subscription
        # would receive them only if it happened to connect before they were sent --
        # i.e. the late-joining case they exist for would be the one that fails.
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE,
                             history=HistoryPolicy.KEEP_LAST)
        qos_for = {"ltl/manifest": latched, "ltl/adapter": latched,
                   "ltl/spec_status": latched}

        node = Node("skill_center")
        pubs = {}
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
                    for suffix, kind in self.TOPICS.items():
                        node.create_subscription(
                            String, f"{ns}/{suffix}",
                            (lambda m, _n=ns, _k=kind: self._emit(_k, _n, m.data)),
                            qos_for.get(suffix, 10))
                    for suffix in ("ltl/evaluations", "ltl/load_spec"):
                        pubs[(ns, suffix)] = node.create_publisher(
                            String, f"{ns}/{suffix}", 10)
                    self._subscribed[ns] = True

            try:
                while True:
                    ns, suffix, data = self._out.get_nowait()
                    pub = pubs.get((ns, suffix))
                    if pub is None:
                        self.on_error(f"no publisher for {ns}/{suffix} yet")
                    else:
                        pub.publish(String(data=data))
            except queue.Empty:
                pass

            rclpy.spin_once(node, timeout_sec=0.1)

        node.destroy_node()

    def _emit(self, kind, ns, raw):
        try:
            self.q.put((kind, ns, json.loads(raw)))
        except Exception:
            pass


class MockSource(threading.Thread):
    """A monitor that exists only in this process: same queue protocol, no ROS.

    Not a toy -- it is the only way to exercise this panel on a machine with no ROS
    (the dev host cannot even see the robot's DDS graph), and it makes the layout
    reviewable without a robot.
    """

    def __init__(self, out_q, period=0.4):
        super().__init__(daemon=True)
        self.q = out_q
        self.period = period
        self._stop = threading.Event()
        self.pushed = []                      # specs pushed at us, for the selftest

    def request_reset(self, ns):
        self.q.put(("spec_status", ns, {"ok": True, "problems": [], "skill_name": "reset"}))
        self._step = 0

    def push_spec(self, ns, spec):
        self.pushed.append(spec)
        from skill_monitor.core import spec_contract
        schema = (self._adapter.get("schema") or {}).keys()
        problems = spec_contract.validate(spec, schema)
        self.q.put(("spec_status", ns, {"ok": not problems, "problems": problems,
                                        "skill_name": spec.get("skill_name", "")}))

    def stop(self):
        self._stop.set()

    def run(self):
        import skill_monitor
        from skill_monitor.core import adapter_spec

        spec = json.loads(skill_monitor.spec_path("g1").read_text(encoding="utf-8"))
        self._adapter = adapter_spec.load("real_g1").manifest()
        ns = "/g1"
        self.q.put(("discovered", None, [ns]))
        self.q.put(("manifest", ns, manifest_mod.skill_manifest(spec, "mock")))
        self.q.put(("adapter", ns, self._adapter))
        self.q.put(("aps", ns, sorted(spec["atomic_propositions"])))

        phases = [p["phase"] for p in spec["execution_phases"]]
        self._step = 0
        while not self._stop.is_set():
            self.q.put(("state", ns, self._state(spec, phases)))
            self._step += 1
            time.sleep(self.period)

    def _state(self, spec, phases):
        i = self._step
        phase_idx = min(i // 12, len(phases) - 1)
        # A plausible run: the robot closes on an obstacle, goes stale for a while,
        # and trips its collision failure mode near the end.
        min_range = max(0.2, 3.0 - 0.05 * i)
        stale = ["points"] if 20 <= i % 60 < 26 else []
        violated = min_range < 0.25
        # ...walking along the odometry frame's +X axis toward a goal 6 m out, so the
        # X-Y track and dist_to_goal are a consistent story rather than seven constants.
        pos_x, pos_y = round(0.1 * i, 3), 0.0
        goal_x, goal_y = 6.0, 0.0
        sensors = {
            "min_range": round(min_range, 2), "base_roll": 0.01, "base_pitch": -0.02,
            "base_height": 0.78, "upright_flag": 1.0,
            "linear_vel": round(0.4 + 0.05 * ((i % 7) - 3), 2), "angular_vel": 0.0,
            "pos_x": pos_x, "pos_y": pos_y, "pos_z": 0.78, "yaw": 0.0,
            "goal_x": goal_x, "goal_y": goal_y,
            "dist_to_goal": round(math.hypot(goal_x - pos_x, goal_y - pos_y), 3),
            "nav_mode": "AUTOMATIC", "nav_state": "following",
            "num_waypoints": 4, "current_target_idx": min(3, i // 15),
            "mission_finished": False, "nav_stuck": False,
            "image_similarity_to_goal": round(min(0.95, 0.2 + 0.01 * i), 2),
        }
        aps = {name: bool(i % 5) for name in spec["atomic_propositions"]}
        modes = spec.get("named_failure_modes", [])
        # Whichever failure mode the spec happens to declare first -- naming one here
        # would tie the mock to this particular navigation spec.
        tripped = modes[0]["name"] if modes else None
        return {
            "phase": phases[phase_idx], "phase_index": phase_idx, "phases": phases,
            "step": i, "skill_name": spec["skill_name"],
            "description": spec.get("description", ""),
            "ap_descriptions": spec["atomic_propositions"],
            "ap_values": aps, "sensors": sensors,
            "risk": {"steps_to_timeout": max(0, 40 - (i % 40)),
                     "violations_to_fault": 3 - (i % 4 == 3),
                     "trigger_confidence": 0.67 if stale else 1.0,
                     "stale_sources": stale,
                     "warn": (i % 40) > 36 or violated,
                     "severity": "SAFETY" if violated else
                                 ("TIMEOUT" if (i % 40) > 36 else None)},
            "named_failure_modes": [
                {"name": m["name"], "fault_category": m.get("fault_category", ""),
                 "description": m.get("description", ""), "formula": m["formula"],
                 "status": ("VIOLATED" if violated and m["name"] == tripped
                            else "INCONCLUSIVE")}
                for m in modes
            ],
        }


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

def _text(parent, height=8, mono=True, **kw):
    import tkinter as tk
    t = tk.Text(parent, height=height, bg=CARD, fg=TEXT, relief=tk.FLAT,
                insertbackground=TEXT, wrap=tk.NONE, padx=8, pady=6,
                font=("TkFixedFont", 9) if mono else ("TkDefaultFont", 10), **kw)
    t.tag_config("head", foreground=MUTED)
    t.tag_config("ok", foreground=OK)
    t.tag_config("bad", foreground=BAD)
    t.tag_config("warn", foreground=WARN)
    t.tag_config("muted", foreground=MUTED)
    t.tag_config("info", foreground=TEXT)
    return t


def _scrolled(parent, **kw):
    import tkinter as tk
    frame = tk.Frame(parent, bg=CARD)
    t = _text(frame, **kw)
    bar = tk.Scrollbar(frame, command=t.yview, bg=CARD, troughcolor=PANEL,
                       relief=tk.FLAT, borderwidth=0)
    t.config(yscrollcommand=bar.set)
    t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    bar.pack(side=tk.RIGHT, fill=tk.Y)
    return frame, t


def _fill(widget, rows):
    """Replace a read-only Text's contents with (text, tag) rows."""
    import tkinter as tk
    widget.config(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    for text, tag in rows:
        widget.insert(tk.END, text + "\n", tag)
    widget.config(state=tk.DISABLED)


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}"
    if v is None:
        return "—"
    return str(v)


class Panel:
    """The window. Holds no skill knowledge: every row it draws is derived from a
    manifest it was handed."""

    def __init__(self, args, source, containers):
        import tkinter as tk
        self.tk = tk
        self.args = args
        self.source = source
        self.containers = containers
        self.q = queue.Queue()
        self.model = Monitors()
        self.selected = None
        self._built_phases = None

        root = self.root = tk.Tk()
        root.title("Skill Center")
        root.configure(bg=BG)
        # Size in TEXT units, not pixels: Tk scales fonts by the display's DPI (1.66x
        # on the 120 DPI monitor this runs on), so a fixed pixel geometry that looks
        # right on a laptop clips half the tables there.
        scale = max(1.0, float(root.tk.call("tk", "scaling")) / 1.33)
        root.geometry(f"{int(1180 * scale)}x{int(760 * scale)}")
        root.minsize(int(820 * scale), int(520 * scale))

        self._build_head()
        body = tk.Frame(root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self._build_sidebar(body)
        self._build_tabs(body)
        self._show_tab(args.tab)

    # -- construction ---------------------------------------------------------

    def _build_head(self):
        tk = self.tk
        head = tk.Frame(self.root, bg=PANEL)
        head.pack(fill=tk.X)
        tk.Label(head, text="Skill Center", bg=PANEL, fg=TEXT,
                 font=("TkDefaultFont", 13, "bold")).pack(side=tk.LEFT, padx=12, pady=10)
        self.hint = tk.Label(head, text="scanning…", bg=PANEL, fg=MUTED, anchor="w")
        self.hint.pack(side=tk.LEFT, padx=6)

    def _build_sidebar(self, body):
        tk = self.tk
        # Fixed width in CHARACTERS, not pixels: this panel is used on a 120 DPI
        # display where Tk scales fonts ~1.7x, and a pixel-sized sidebar clips the
        # monitor names there while looking fine on the developer's laptop.
        side = tk.Frame(body, bg=PANEL)
        side.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        tk.Label(side, text="MONITORS", bg=PANEL, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.listbox = tk.Listbox(
            side, bg=PANEL, fg=TEXT, relief=tk.FLAT, highlightthickness=0, width=16,
            selectbackground=ACCENT, selectforeground="#ffffff", activestyle="none")
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 8))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        tk.Button(side, text="arm / reset", bg=CARD, fg=TEXT, relief=tk.FLAT,
                  highlightthickness=0,
                  command=self._reset).pack(fill=tk.X, padx=8, pady=(0, 10))

        tk.Label(side, text="CONTAINERS", bg=PANEL, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=12, pady=(0, 4))
        self.ctr_dots = {}
        for name in self.args.containers:
            row = tk.Frame(side, bg=PANEL)
            row.pack(fill=tk.X, padx=8, pady=2)
            dot = tk.Canvas(row, width=10, height=10, bg=PANEL, highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=OFF, outline="", tags="d")
            dot.pack(side=tk.LEFT, padx=(0, 5))
            tk.Label(row, text=name, bg=PANEL, fg=MUTED).pack(side=tk.LEFT)
            for label, fn in (("stop", self.containers.stop),
                              ("start", self.containers.start)):
                tk.Button(row, text=label, bg=CARD, fg=TEXT, relief=tk.FLAT, padx=4,
                          highlightthickness=0,
                          command=(lambda f=fn, n=name: self._container(f, n))
                          ).pack(side=tk.RIGHT, padx=2)
            self.ctr_dots[name] = dot

    def _build_tabs(self, body):
        tk = self.tk
        right = tk.Frame(body, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bar = tk.Frame(right, bg=BG)
        bar.pack(fill=tk.X)
        self.tab_buttons, self.tabs = {}, {}
        for name in ("Live", "Spec", "Timeline"):
            b = tk.Button(bar, text=name, bg=BG, fg=MUTED, relief=tk.FLAT, padx=14,
                          highlightthickness=0,
                          command=(lambda n=name: self._show_tab(n)))
            b.pack(side=tk.LEFT)
            self.tab_buttons[name] = b
            self.tabs[name] = tk.Frame(right, bg=BG)

        self._build_live(self.tabs["Live"])
        self._build_spec(self.tabs["Spec"])
        self._build_timeline(self.tabs["Timeline"])

    def _build_live(self, parent):
        tk = self.tk
        self.title = tk.Label(parent, text="—", bg=BG, fg=TEXT, anchor="w",
                              font=("TkDefaultFont", 12, "bold"))
        self.title.pack(fill=tk.X, pady=(10, 0))
        self.subtitle = tk.Label(parent, text="", bg=BG, fg=MUTED, anchor="w",
                                 justify=tk.LEFT)
        self.subtitle.pack(fill=tk.X)

        self.phase_bar = tk.Frame(parent, bg=BG)
        self.phase_bar.pack(fill=tk.X, pady=8)
        self.phase_labels = []

        self.risk = tk.Label(parent, text="", bg=CARD, fg=TEXT, anchor="w",
                             padx=10, pady=6)
        self.risk.pack(fill=tk.X)

        # Stacked, not side by side: at 120 DPI Tk scales the fixed-width font enough
        # that two columns clip their own rows, and a clipped rule is worse than a
        # short pane -- the whole point of this table is the rule text.
        tk.Label(parent, text="ATOMIC PROPOSITIONS", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(8, 0))
        f, self.ap_text = _scrolled(parent, height=6)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(parent, text="SENSORS", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(8, 0))
        f, self.sensor_text = _scrolled(parent, height=4)
        f.pack(fill=tk.BOTH, expand=True)

        tk.Label(parent, text="FAILURE MODES", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        f, self.fm_text = _scrolled(parent, height=3)
        f.pack(fill=tk.X)

    def _build_spec(self, parent):
        tk = self.tk
        tk.Label(parent, text="DESCRIBE THE SKILL", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 2))
        self.desc_box = _text(parent, height=4, mono=False)
        self.desc_box.pack(fill=tk.X)
        self.desc_box.insert("1.0", "Walk to each waypoint in turn without hitting "
                                    "anything or falling over, and confirm the goal "
                                    "visually on arrival.")

        row = tk.Frame(parent, bg=BG)
        row.pack(fill=tk.X, pady=6)
        for label, cmd in (("generate", self._generate), ("validate", self._validate),
                           ("load…", self._load), ("save…", self._save),
                           ("push to monitor", self._push)):
            tk.Button(row, text=label, bg=CARD, fg=TEXT, relief=tk.FLAT, padx=10,
                      highlightthickness=0, command=cmd).pack(side=tk.LEFT, padx=(0, 6))
        self.spec_hint = tk.Label(row, text="", bg=BG, fg=MUTED, anchor="w")
        self.spec_hint.pack(side=tk.LEFT, padx=6)

        tk.Label(parent, text="PROBLEMS", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        f, self.problems_text = _scrolled(parent, height=5)
        f.pack(fill=tk.X)

        tk.Label(parent, text="SPEC", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(8, 0))
        f, self.spec_text = _scrolled(parent, height=16)
        f.pack(fill=tk.BOTH, expand=True)

    def _build_timeline(self, parent):
        tk = self.tk
        tk.Label(parent, text="EPISODE TIMELINE", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 2))
        f, self.timeline_text = _scrolled(parent, height=30)
        f.pack(fill=tk.BOTH, expand=True)

    # -- actions --------------------------------------------------------------

    def _show_tab(self, name):
        for n, frame in self.tabs.items():
            frame.pack_forget()
            self.tab_buttons[n].config(fg=MUTED, bg=BG)
        self.tabs[name].pack(fill=self.tk.BOTH, expand=True)
        self.tab_buttons[name].config(fg=TEXT, bg=CARD)
        self.active_tab = name

    def _on_select(self, _evt=None):
        sel = self.listbox.curselection()
        if sel:
            self.selected = self.model.order[sel[0]]
            self._built_phases = None
            self._redraw_timeline()

    def _container(self, fn, name):
        okk, msg = fn(name)
        self.hint.config(text=msg if not okk else f"{name}: ok", fg=TEXT if okk else BAD)

    def _reset(self):
        if self.selected is not None:
            self.source.request_reset(self.selected)
            self.hint.config(text=f"reset sent to {self.selected or '(default)'}", fg=TEXT)

    def _editor_spec(self):
        raw = self.spec_text.get("1.0", self.tk.END).strip()
        if not raw:
            return None, ["the spec editor is empty — generate or load one first"]
        try:
            return json.loads(raw), []
        except Exception as exc:
            return None, [f"not valid JSON: {exc}"]

    def _set_problems(self, problems, ok_text="no problems — this spec runs here"):
        rows = ([(f"• {p}", "bad") for p in problems] if problems
                else [(ok_text, "ok")])
        _fill(self.problems_text, rows)

    def _schema(self):
        """The selected robot's schema, straight off its adapter manifest."""
        slot = self.model.get(self.selected) if self.selected is not None else {}
        return (slot.get("adapter") or {}).get("schema") or {}

    def _validate(self):
        from skill_monitor.core import spec_contract
        spec, problems = self._editor_spec()
        if spec is None:
            self._set_problems(problems)
            return
        schema = self._schema()
        if not schema:
            self._set_problems(
                spec_contract.validate_structure(spec),
                "structure is sound — no adapter on the graph, so sensor fields "
                "could not be checked")
            return
        self._set_problems(spec_contract.validate(spec, schema.keys()))

    def _generate(self):
        """Run the describer off the Tk thread; a slow model must not freeze the UI."""
        desc = self.desc_box.get("1.0", self.tk.END).strip()
        if not desc:
            self.spec_hint.config(text="describe the skill first", fg=BAD)
            return
        schema = {k: (v or {}).get("doc", "") for k, v in self._schema().items()}
        self.spec_hint.config(text="generating…", fg=MUTED)

        def work():
            from skill_monitor.describer import generate_formulas as gen
            spec, problems = gen.generate(
                desc, schema or None, api_url=self.args.api_url, model=self.args.model,
                llm=_mock_llm if self.args.mock_llm else None)
            self.q.put(("generated", self.selected, (spec, problems)))

        threading.Thread(target=work, daemon=True).start()

    def _load(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("spec", "*.json")])
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            self._set_spec(json.load(f))
        self.spec_hint.config(text=f"loaded {path}", fg=TEXT)

    def _save(self):
        from tkinter import filedialog
        spec, problems = self._editor_spec()
        if spec is None:
            self._set_problems(problems)
            return
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            initialfile="formulas_new.json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        self.spec_hint.config(text=f"saved {path}", fg=TEXT)

    def _push(self):
        spec, problems = self._editor_spec()
        if spec is None:
            self._set_problems(problems)
            return
        if self.selected is None:
            self.spec_hint.config(text="no monitor selected", fg=BAD)
            return
        self.source.push_spec(self.selected, spec)
        self.spec_hint.config(text="pushed — awaiting the monitor's verdict", fg=MUTED)

    def _set_spec(self, spec):
        self.spec_text.config(state=self.tk.NORMAL)
        self.spec_text.delete("1.0", self.tk.END)
        self.spec_text.insert("1.0", json.dumps(spec, indent=2))

    # -- rendering ------------------------------------------------------------

    def _redraw_sidebar(self):
        now = time.monotonic()
        want = [f"{'●' if health(self.model.get(ns)['last'], now) == 'live' else '○'} "
                f"{(self.model.get(ns)['desc'].get('skill_name') or ns or '(default)')}"
                for ns in self.model.order]
        if list(self.listbox.get(0, self.tk.END)) != want:
            sel = self.listbox.curselection()
            self.listbox.delete(0, self.tk.END)
            for row in want:
                self.listbox.insert(self.tk.END, row)
            if sel:
                self.listbox.selection_set(sel[0])
            elif want:
                self.listbox.selection_set(0)
                self._on_select()

    def _redraw_phases(self, phases, active):
        tk = self.tk
        if self._built_phases != phases:
            for w in self.phase_bar.winfo_children():
                w.destroy()
            self.phase_labels = []
            for i, name in enumerate(phases):
                if i:
                    tk.Label(self.phase_bar, text="›", bg=BG, fg=MUTED).pack(side=tk.LEFT)
                # Phase names are generated, so they can be arbitrarily long; the
                # strip has to stay one row regardless of how the LLM named them.
                lab = tk.Label(self.phase_bar, text=_clip(name, 18), bg=CARD, fg=MUTED,
                               padx=10, pady=5)
                lab.pack(side=tk.LEFT)
                self.phase_labels.append(lab)
            self._built_phases = list(phases)
        for i, lab in enumerate(self.phase_labels):
            done = active is not None and i < active
            lab.config(bg=ACCENT if i == active else CARD,
                       fg="#ffffff" if i == active else (TEXT if done else MUTED))

    def _redraw_detail(self):
        if self.selected is None:
            return
        slot = self.model.get(self.selected)
        desc, man, adapter = slot["desc"], slot["manifest"], slot["adapter"]
        h = health(slot["last"], time.monotonic())

        name = desc.get("skill_name") or man.get("skill_name") or self.selected or "—"
        self.title.config(text=f"{name}    [{h}]")
        # One line. The full description is in the Spec tab; letting it wrap here
        # pushed the live tables off the bottom of the window on a HiDPI display.
        self.subtitle.config(text="  ·  ".join(x for x in (
            _clip(man.get("description") or desc.get("description") or "", 110),
            f"robot: {adapter.get('adapter')}" if adapter else "",
            f"spec: {_clip(str(man.get('source', '')), 40)}" if man else "") if x))

        phases = desc.get("phases") or man.get("phases") or []
        self._redraw_phases(phases, desc.get("phase_index"))

        risk = desc.get("risk") or {}
        self.risk.config(
            text=summarize(desc),
            fg=BAD if risk.get("warn") else (MUTED if h != "live" else TEXT))

        # APs: value + the rule the evaluator actually applies.
        rows = []
        for ap, value, description in manifest_mod.ap_rows(
                man or {"atomic_propositions": desc.get("ap_descriptions") or {}}, desc):
            mark, tag = ({True: ("✔", "ok"), False: ("✘", "muted")}
                         .get(value, ("·", "muted")))
            rows.append((f"{mark} {ap:<24}{_clip(description, 34)}", tag))
        _fill(self.ap_text, rows or [("no manifest yet", "muted")])

        rows = [(f"{k:<24}{_fmt(v):<9} {_clip(doc, 30)}",
                 "muted" if v is None else "info")
                for k, v, doc in manifest_mod.sensor_rows(adapter, desc)]
        _fill(self.sensor_text, rows or [("no adapter on the graph", "muted")])

        rows = []
        for m in desc.get("named_failure_modes") or man.get("named_failure_modes") or []:
            status = m.get("status", "—")
            tag = {"VIOLATED": "bad", "ACCEPTED": "ok"}.get(status, "muted")
            rows.append((f"{status:<14}{m.get('name',''):<22}"
                         f"{_clip(m.get('formula',''), 30)}", tag))
        _fill(self.fm_text, rows or [("none declared", "muted")])

    def _redraw_timeline(self):
        if self.selected is None:
            return
        _fill(self.timeline_text, [(t, sev) for sev, t in
                                   self.model.get(self.selected)["events"]]
              or [("nothing yet", "muted")])
        self.timeline_text.see(self.tk.END)

    def _redraw_containers(self):
        running = self.containers.running()
        for name, dot in self.ctr_dots.items():
            dot.itemconfig("d", fill=OFF if running is None
                           else (OK if name in running else BAD))

    # -- main loop ------------------------------------------------------------

    def tick(self):
        new_events = False
        try:
            while True:
                kind, ns, payload = self.q.get_nowait()
                if kind == "discovered":
                    self.model.discovered(payload)
                elif kind == "generated":
                    spec, problems = payload
                    self._set_spec(spec)
                    self._set_problems(problems)
                    self.spec_hint.config(
                        text="generated" + (" with problems" if problems else " — clean"),
                        fg=BAD if problems else OK)
                elif kind == "error":
                    self.hint.config(text=payload, fg=BAD)
                else:
                    events = self.model.apply(kind, ns, payload)
                    new_events = new_events or (ns == self.selected and bool(events))
                    if kind == "spec_status":
                        self.spec_hint.config(
                            text="monitor accepted the spec" if payload.get("ok")
                            else "monitor REJECTED the spec",
                            fg=OK if payload.get("ok") else BAD)
                        if payload.get("problems"):
                            self._set_problems(payload["problems"])
        except queue.Empty:
            pass

        n = len(self.model.order)
        self.hint.config(
            text=(f"{n} skill monitor(s) on the graph" if n else
                  "no skill monitor detected — is the monitor container running?"),
            fg=TEXT if n else MUTED)

        self._redraw_sidebar()
        self._redraw_detail()
        if new_events:
            self._redraw_timeline()
        self._redraw_containers()
        self.root.after(500, self.tick)

    def run(self):
        self.source.q = self.q
        self.source.start()
        self.root.after(200, self.tick)
        self.root.protocol("WM_DELETE_WINDOW",
                           lambda: (self.source.stop(), self.root.destroy()))
        self.root.mainloop()


def _mock_llm(_api_url, _model, prompt):
    """A scripted model, so the Spec tab can be exercised with no LLM reachable.
    Returns a spec written over whatever fields the prompt says the robot has."""
    import re
    fields = re.findall(r"^  (\w+)\s+- ", prompt, re.M)
    first = fields[0] if fields else "min_range"
    return {
        "skill_name": "GeneratedSkill",
        "description": "Placeholder spec from the mock model (--mock-llm).",
        "atomic_propositions": {
            "started": f"True when {first} > 0. The skill has begun.",
            "finished": f"True when {first} < 0.1. The skill is complete.",
        },
        "ltl_formulas": [{"name": "eventually_done", "formula": "F(finished)"}],
        "named_failure_modes": [],
        "execution_phases": [
            {"phase": "Execution", "description": "Doing the thing.",
             "enter_condition": "started", "precondition": "", "invariant": "",
             "progress_condition": "started", "exit_condition": "finished",
             "progress_violation_limit": 3, "timing_bounds": {"max_steps": 60}}],
        "terminal_success": {"condition": "finished", "description": "done"},
        "terminal_failure": {"condition": "False", "description": "n/a"},
    }


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
    ap.add_argument("--mock", action="store_true",
                    help="drive the panel from a simulated monitor, with no ROS at all")
    ap.add_argument("--mock-llm", action="store_true",
                    help="use a scripted model for the Spec tab instead of a live one")
    ap.add_argument("--api-url", default="http://192.168.140.101/developer-api/v1")
    ap.add_argument("--model", default="Gemma4")
    ap.add_argument("--tab", default="Live", choices=("Live", "Spec", "Timeline"),
                    help="which tab to open on; handy for screenshots")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    q = queue.Queue()
    source = MockSource(q) if args.mock else Discovery(q)
    panel = Panel(args, source, Containers(args.containers))
    if not args.mock:
        source.on_error = lambda m: q.put(("error", None, m))
    return panel.run()


if __name__ == "__main__":
    sys.exit(main() or 0)
