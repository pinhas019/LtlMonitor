"""The whole stack in one process tree, shown in the browser.

    python sim/stack.py                     # then open http://localhost:8080
    python sim/stack.py --text --fault drop --spec flat     # one run, in the terminal

What runs, as in the E1b experiments over ROS 2:
  * the **evaluator** (`python -m skill_monitor.backend.evaluator_node`) and the **monitor**
    (`python -m skill_monitor.backend.monitor_node --passive`) as their own processes,
    talking over DDS on their own ROS_DOMAIN_ID;
  * the **driver** (this process): the MuJoCo G1, the navigator, the fetch-and-deliver
    executor and the perception stand-in, publishing /clock, /odom, /scan, /object/pose,
    /goal_pose, /task and the tick, and reading /monitor/verdict -- sim/e1/ros_e1b.py;
  * a **web page**: the robot rendered off-screen (MuJoCo, OSMesa in the container), the
    monitor's phase, inferred "held", verdict and alarms next to the simulator's ground
    truth, and buttons for the demo scenarios.

Needs ROS 2 Humble (RoboStack works), Spot, MuJoCo and Pillow -- the Docker image and
`python3 run.py` provide them. Standard library HTTP, no web framework.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import queue
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (HERE / "e1", HERE / "e1" / "carry", HERE, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

PRESETS = [
    ("Clean run", "clear", "full", "off"),
    ("Dropped object: full spec", "drop", "full", "off"),
    ("Dropped object: flat spec", "drop", "flat", "off"),
    ("Failed grasp: full spec + re-plan", "grasp_fail", "full", "recover"),
    ("Hand-coded checks: dropped object", "drop", "closed_loop", "off"),
    ("Hand-coded checks: wrong drop-off", "wrong_dropoff", "closed_loop", "off"),
    ("Monitor: wrong drop-off", "wrong_dropoff", "full", "off"),
]
FAST_DDS_PROFILE = HERE / "fastdds_udp.xml"


class Cancelled(Exception):
    pass


class Stack:
    """Owns the ROS 2 side: one long-lived thread runs every episode, so the node
    processes it starts (which die with the thread that started them) live as long as
    the stack does."""

    def __init__(self, domain: int, logdir: Path, size=(800, 500), fps: float = 10.0,
                 echo=None):
        self.domain, self.logdir, self.size, self.fps = domain, logdir, size, fps
        self.echo = echo                  # also print the tick log (the --text mode)
        self.finished: queue.Queue = queue.Queue()      # the state after each run
        self.requests: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.paused = threading.Event()   # the presenter holds the run to explain a stage
        self.frame_cv = threading.Condition()
        self.frame, self.frame_no = None, 0
        self.lock = threading.Lock()
        self.state = {"stack": "starting", "run": None, "fields": {}, "log": [],
                      "result": None, "error": None, "graph": {}, "auto": None,
                      "paused": False}
        self._snap, self._snap_ready = None, threading.Event()
        self.thread = threading.Thread(target=self._main, name="ros-stack", daemon=True)
        self.thread.start()
        if fps > 0:
            threading.Thread(target=self._render_loop, name="render", daemon=True).start()

    # ----------------------------------------------------------------- public
    def submit(self, run: dict) -> None:
        self.cancel.set()                 # stop whatever is running
        self.set_paused(False)
        self._set(auto=None)              # not the previous run's automaton
        self.requests.put(run)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.paused.set()
        else:
            self.paused.clear()
        self._set(paused=paused)

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state))

    # ----------------------------------------------------------------- internals
    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _log(self, line: str):
        if self.echo:
            self.echo(line)
        with self.lock:
            self.state["log"].append(line)
            del self.state["log"][:-400]

    def _main(self):
        try:
            self._serve_episodes()
        except Exception as exc:                                  # noqa: BLE001
            traceback.print_exc()
            self._set(stack="error", error=f"{type(exc).__name__}: {exc}")
            self.finished.put(self.snapshot())

    def _serve_episodes(self):
        os.environ["ROS_DOMAIN_ID"] = str(self.domain)
        os.environ.setdefault("ROS_LOCALHOST_ONLY", "1")
        if FAST_DDS_PROFILE.exists() and not os.environ.get("LTL_DDS_DEFAULT"):  # UDP only
            os.environ.setdefault("FASTRTPS_DEFAULT_PROFILES_FILE", str(FAST_DDS_PROFILE))
        import spot  # noqa: F401  -- the real one, before anything could shadow it
        import rclpy
        from std_msgs.msg import String

        import ros_e1b
        import run_e1b
        from g1sim import G1Sim
        from skill_monitor.core import api

        from rclpy.signals import SignalHandlerOptions
        # rclpy's own SIGINT/SIGTERM handlers would swallow Ctrl+C and `docker stop`.
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        node = ros_e1b.make_driver_node()
        node.observation = {}

        def on_obs(msg):
            try:
                node.observation = json.loads(msg.data)
            except ValueError:
                pass
        node.create_subscription(String, api.OBSERVATION, on_obs, 10)
        # The monitor's latched manifest: its spec, phases and every automaton it built,
        # which the page draws and lights up from each verdict's states.
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        node.manifest = None

        def on_manifest(msg):
            try:
                node.manifest = json.loads(msg.data)
            except ValueError:
                pass
        node.create_subscription(String, api.MANIFEST, on_manifest, QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        ros_e1b._assert_domain_empty(node, self.domain)
        sim = G1Sim()
        self.logdir.mkdir(parents=True, exist_ok=True)
        procs, current, episode = [], None, 0
        self._set(stack="ready")
        try:
            while True:
                run = self.requests.get()
                while not self.requests.empty():            # only the latest request
                    run = self.requests.get()
                if run is None:                             # shut down
                    return
                self.cancel.clear()
                spec = run["spec"]
                if spec != current:
                    self._set(stack="starting nodes", run=run, fields={}, log=[],
                              result=None, error=None, auto=None)
                    self._stop(procs, node)
                    node.manifest = None
                    procs = ros_e1b._launch_nodes(spec, self.domain, self.logdir)
                    ros_e1b._wait_ready(node)
                    end = time.monotonic() + 15
                    while node.manifest is None and time.monotonic() < end:
                        node.exe.spin_once(timeout_sec=0.1)
                    current = spec
                    self._set(graph=self._graph(node))
                self._set(stack="running", run=run, fields={}, log=[], result=None,
                          error=None, auto=self._view(run, node, None, None, {}))
                try:
                    rec = self._episode(run, sim, node, episode, run_e1b, ros_e1b)
                    from demo_common import result_line
                    self._set(stack="ready", result=result_line(rec, spec))
                except Cancelled:
                    self._set(stack="ready")
                except Exception as exc:                          # noqa: BLE001
                    traceback.print_exc()          # one bad run must not take the stack down
                    self._set(stack="ready", error=f"{type(exc).__name__}: {exc}")
                episode += 1
                self.finished.put(self.snapshot())
        finally:
            self._stop(procs, node)
            node.destroy_node()
            rclpy.try_shutdown()

    def _stop(self, procs, node):
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:                                     # noqa: BLE001
                p.kill()
        if procs:                         # let DDS forget them before new ones appear
            from skill_monitor.core import api
            end = time.monotonic() + 15
            while time.monotonic() < end and node.count_publishers(api.VERDICT):
                node.exe.spin_once(timeout_sec=0.2)

    @staticmethod
    def _view(run, node, verdict, observation, prev) -> dict:
        from demo_common import NO_MONITOR
        if run["spec"] in NO_MONITOR:
            return {"none": True}
        from stack_view import automata_view
        return automata_view(node.manifest, verdict, observation, prev)

    def _graph(self, node) -> dict:
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            node.exe.spin_once(timeout_sec=0.1)
        nodes = sorted(n for n, _ in node.get_node_names_and_namespaces())
        topics = sorted(t for t, _ in node.get_topic_names_and_types()
                        if not t.startswith(("/parameter_events", "/rosout")))
        return {"domain": self.domain, "nodes": nodes, "topics": topics}

    def _episode(self, run, sim, node, episode, run_e1b, ros_e1b):
        from demo_common import TickView
        from task import generate

        task = generate(run["fault"], int(run["seed"]))
        item = {"task": task, "arm": run["spec"], "policy": run["policy"]}
        speed = max(0.25, float(run.get("speed", 2.0)))
        tv = TickView(task, run["spec"])
        self._log(f"{task['name']}: {run['spec']} spec, policy {run['policy']}. Injected: "
                  + (", ".join(f["type"] for f in task["scenario"].get("faults", [])
                               + task.get("task_faults", [])) or "nothing"))
        r = {"wall0": time.monotonic(), "last": 0.0, "verdict": None, "prev": {}}

        def on_step(s):
            if self.cancel.is_set():
                raise Cancelled
            if self.paused.is_set():            # hold here; the clock does not advance
                t0 = time.monotonic()
                while self.paused.is_set() and not self.cancel.is_set():
                    time.sleep(0.05)
                r["wall0"] += time.monotonic() - t0
            now = time.monotonic()
            if self.fps > 0 and now - r["last"] >= 1.0 / self.fps:
                r["last"] = now                  # a snapshot; the render thread draws it
                self._snap = (s.model, s.data.qpos.copy(), s.data.mocap_pos.copy(),
                              s.data.mocap_quat.copy(), s.base_pose()[:2])
                self._snap_ready.set()
            ahead = s.time / speed - (time.monotonic() - r["wall0"])
            if ahead > 0:
                time.sleep(ahead)

        def on_tick(seq, verdict, name, ex, s, link):
            for line in tv.fault_events(ex, s):
                self._log(f"      ** {line}")
            held = (node.observation.get("sensors") or {}).get("holding")
            f = tv.tick(seq, verdict, name, ex, s, held)
            self._log(f["line"])
            if verdict:                         # the monitor is silent after a terminal
                r["verdict"] = verdict
            view = self._view(run, node, r["verdict"], node.observation, r["prev"])
            if verdict and view and view.get("automata"):
                r["prev"] = {a["name"]: a["current"] for a in view["automata"]}
            self._set(fields={k: f[k] for k in ("t", "phase", "held", "verdict", "alarm",
                                                "truth")}, auto=view)

        link = ros_e1b.RosLink(node, episode=episode)
        return run_e1b.play_episode(item, sim, link, on_step=on_step, on_tick=on_tick)

    def _render_loop(self):
        """Draw the latest snapshot, in its own thread with its own MjData and GL context,
        so the simulation and the ROS lockstep never wait for the (software) renderer."""
        import mujoco
        cam = mujoco.MjvCamera()
        cam.distance, cam.elevation, cam.azimuth = 6.0, -35.0, 90.0
        opt = mujoco.MjvOption()
        opt.geomgroup[3] = 1                     # the object and the drop-off pad
        model = renderer = data = None
        while True:
            self._snap_ready.wait()
            self._snap_ready.clear()
            snap = self._snap
            if snap is None:
                continue
            m, qpos, mpos, mquat, (x, y) = snap
            try:
                if m is not model:
                    vis = m.vis.global_          # the default framebuffer is 640x480
                    vis.offwidth = max(vis.offwidth, self.size[0])
                    vis.offheight = max(vis.offheight, self.size[1])
                    if renderer is not None:
                        renderer.close()
                    renderer = mujoco.Renderer(m, self.size[1], self.size[0])
                    for flag in (mujoco.mjtRndFlag.mjRND_SHADOW,
                                 mujoco.mjtRndFlag.mjRND_REFLECTION):
                        renderer.scene.flags[flag] = 0
                    data, model = mujoco.MjData(m), m
                data.qpos[:], data.mocap_pos[:], data.mocap_quat[:] = qpos, mpos, mquat
                mujoco.mj_forward(model, data)
                cam.lookat[:] = (x, y, 0.5)
                renderer.update_scene(data, camera=cam, scene_option=opt)
                for flag in (mujoco.mjtRndFlag.mjRND_SHADOW, mujoco.mjtRndFlag.mjRND_REFLECTION):
                    renderer.scene.flags[flag] = 0
                self._publish_frame(renderer.render())
            except Exception:                                     # noqa: BLE001
                traceback.print_exc()
                time.sleep(1.0)

    def _publish_frame(self, pixels):
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(pixels).save(buf, format="JPEG", quality=80)
        with self.frame_cv:
            self.frame, self.frame_no = buf.getvalue(), self.frame_no + 1
            self.frame_cv.notify_all()


# ===================================================================== the web page

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LTL skill monitor: live demo</title>
<style>
:root{--bg:#f6f6f3;--fg:#14213d;--mut:#5b6472;--card:#fff;--line:#dde3ea;--acc:#1f5fae;--bad:#b5503c}
@media (prefers-color-scheme:dark){:root{--bg:#10151f;--fg:#e8edf5;--mut:#9aa6b8;--card:#18202d;--line:#2b3648;--acc:#6aa5ec;--bad:#f08c74}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line)}h1{font-size:19px;margin:0}header p{margin:2px 0 0;color:var(--mut)}
main{display:grid;grid-template-columns:minmax(0,800px) minmax(300px,1fr);gap:16px;padding:16px 20px}
@media (max-width:1100px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
img#view{width:100%;aspect-ratio:8/5;background:#0b0f16;border-radius:10px;display:block}
table{border-collapse:collapse;width:100%}td{padding:4px 6px;border-bottom:1px solid var(--line);vertical-align:top}td:first-child{color:var(--mut);width:42%}
.alarm{color:var(--bad);font-weight:600}.presets button,.go{margin:3px 4px 3px 0;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);cursor:pointer;font:inherit}
.presets button:hover,.go:hover{border-color:var(--acc)}.go{background:var(--acc);color:#fff;border-color:var(--acc)}
select,input{font:inherit;padding:4px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
pre{margin:0;max-height:300px;overflow:auto;font:12px/1.4 ui-monospace,monospace;white-space:pre}
h2{font-size:14px;margin:0 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.state{color:var(--mut)}
.now{font-size:17px;line-height:1.45;margin:0 0 12px;padding:10px 12px;border-left:4px solid var(--acc);background:var(--bg);border-radius:6px}
.now.bad{border-color:var(--bad)}.now.ok{border-color:#2f8f4e}
.lbl{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;margin:12px 0 6px}
.phases{display:flex;flex-wrap:wrap;align-items:stretch;gap:4px}
.ph{border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:96px;max-width:190px;font-size:13px;background:var(--bg)}
.ph b{display:block;font-size:14px}.ph small{color:var(--mut);display:block;font-size:11px;line-height:1.3}
.ph.cur{background:var(--acc);border-color:var(--acc);color:#fff}.ph.cur small{color:#e6eefc}
.ph.done{opacity:.6}.ph.fault{background:var(--bad);border-color:var(--bad);color:#fff}.ph.fault small{color:#fde9e4}
.ph.win{background:#2f8f4e;border-color:#2f8f4e;color:#fff}.ph.win small{color:#e2f3e8}
.ph.broke{outline:3px solid var(--bad)}.arrow{align-self:center;color:var(--mut)}
#aut{width:100%}#aut svg{display:block;margin:0 auto;height:auto}
.pills span{display:inline-block;margin:2px 4px 2px 0;padding:2px 8px;border-radius:999px;font:12px ui-monospace,monospace;border:1px solid var(--line);color:var(--mut)}
.pills span.t{background:var(--acc);border-color:var(--acc);color:#fff}.pills span.u{border-style:dashed}
.chips span{display:inline-block;margin:2px 6px 2px 0;padding:3px 8px;border-radius:6px;font-size:12px;border:1px solid var(--line)}
.chips span.v{background:var(--bad);color:#fff;border-color:var(--bad)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media (max-width:700px){.two{grid-template-columns:1fr}}
#guards td{font-size:12px}#guards td:first-child{width:28%}
</style></head><body>
<header><h1>LTL skill monitor: fetch and deliver, live</h1>
<p>MuJoCo G1 · evaluator and monitor as separate ROS 2 processes · the monitor sees only ROS messages; the last row is the simulator's ground truth, which it never sees.</p></header>
<main>
<div><img id="view" src="/stream" alt="live view of the robot">
<div class="card" style="margin-top:12px" id="autocard"><h2>What the monitor is doing</h2>
<p class="now" id="now">Pick a scenario.</p>
<div id="autobody">
<div class="lbl">Phase machine (from the generated spec)</div><div class="phases" id="phases"></div>
<div class="lbl">LTL task automaton · <span id="fname" style="text-transform:none;font-family:ui-monospace,monospace"></span></div>
<div id="aut" role="img" aria-label="task automaton"></div>
<div class="two"><div><div class="lbl">Propositions this tick (from __OBS_TOPIC__)</div><div class="pills" id="props"></div>
<div class="lbl">Safety automata</div><div class="chips" id="safety"></div></div>
<div><div class="lbl">This phase's checks (from __VERDICT_TOPIC__)</div><table id="guards"></table></div></div>
</div></div></div>
<div style="display:flex;flex-direction:column;gap:12px">
<div class="card"><h2>Scenarios</h2><div class="presets" id="presets"></div>
<div class="row" style="margin-top:8px">
<select id="fault"></select><select id="spec"></select><select id="policy"></select>
<label>seed <input id="seed" type="number" value="0" min="0" max="999" style="width:64px"></label>
<label>speed <input id="speed" type="number" value="2" min="0.5" max="20" step="0.5" style="width:64px"></label>
<button class="go" onclick="go()">Run</button>
<button class="go" id="pause" onclick="fetch('/pause',{method:'POST'})" style="background:var(--bg);color:var(--fg);border-color:var(--line)">Pause</button></div>
<p class="state" id="state">starting...</p></div>
<div class="card"><h2>Monitor</h2><table id="fields"></table><p id="result"></p></div>
<div class="card"><h2>Tick log</h2><pre id="log"></pre></div>
<div class="card"><h2>ROS 2 graph</h2><pre id="graph"></pre></div>
</div></main>
<script>
const OPT=__OPTIONS__;
for(const k of ["fault","spec","policy"]){const s=document.getElementById(k);for(const v of OPT[k]){const o=document.createElement("option");o.textContent=v;s.appendChild(o)}}
document.getElementById("spec").value="full";document.getElementById("fault").value="drop";
const P=document.getElementById("presets");
for(const [label,fault,spec,policy] of OPT.presets){const b=document.createElement("button");b.textContent=label;
b.onclick=()=>{Object.assign(document.getElementById("fault"),{value:fault});Object.assign(document.getElementById("spec"),{value:spec});
Object.assign(document.getElementById("policy"),{value:policy});go()};P.appendChild(b)}
function go(){run({fault:fault.value,spec:spec.value,policy:policy.value,seed:+seed.value,speed:+speed.value})}
function run(r){fetch("/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(r)})}
const L={t:"t (s)",phase:"monitor phase",held:"held (inferred)",verdict:"verdict",alarm:"last alarm",truth:"truth (simulator)"};
async function poll(){try{const s=await (await fetch("/status")).json();
const r=s.run;document.getElementById("state").textContent="stack: "+s.stack+(r?` · ${r.fault} · ${r.spec} spec · policy ${r.policy} · seed ${r.seed}`:"")+(s.error?" · "+s.error:"");
document.getElementById("fields").innerHTML=Object.entries(L).map(([k,n])=>`<tr><td>${n}</td><td class="${k==="alarm"&&s.fields[k]?"alarm":""}">${s.fields[k]??"-"}</td></tr>`).join("");
document.getElementById("result").textContent=s.result||"";
const lg=document.getElementById("log");lg.textContent=s.log.join("\\n");lg.scrollTop=lg.scrollHeight;
const g=s.graph;document.getElementById("graph").textContent=g.nodes?`ROS_DOMAIN_ID ${g.domain}\\nnodes:\\n  ${g.nodes.join("\\n  ")}\\ntopics:\\n  ${g.topics.join("\\n  ")}`:"";
document.getElementById("pause").textContent=s.paused?"Resume":"Pause";
if(s.paused)document.getElementById("state").textContent+=" · PAUSED";
drawAuto(s.auto,s.fields);
}catch(e){console.error(e)}setTimeout(poll,300)}poll();
const esc=t=>String(t??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let lastKey="";
function drawAuto(a,f){
const now=document.getElementById("now"),body=document.getElementById("autobody");
if(!a){now.textContent="Pick a scenario.";now.className="now";body.style.display="none";return}
if(a.none){now.textContent="No monitor acting in this run: only the executor's own hand-coded checks. (A monitor node still runs for the record, but nothing it says is shown or used.) Watch the truth row: when the checks miss a fault, nothing says so.";now.className="now";body.style.display="none";return}
body.style.display="";
let words=a.now;if(f&&f.alarm&&a.terminal!=="FAILURE")words+=` Alarm: ${f.alarm}.`;
now.textContent=words;now.className="now"+(a.terminal==="FAILURE"||(f&&f.alarm)?" bad":a.success?" ok":"");
const key=JSON.stringify([a.phase,a.terminal,a.automata.map(x=>[x.current,x.prev]),a.props.map(p=>p.value),a.guards.map(g=>g.value),a.safety.map(x=>x.status),a.seconds_left]);
if(key===lastKey)return;lastKey=key;
// phase machine
const idx=a.phases.findIndex(p=>p.name===a.phase);
let h="";a.phases.forEach((p,i)=>{let c="ph";
if(a.success&&p.name==="Done")c+=" win";else if(i===idx&&a.terminal==="FAILURE")c+=" broke";else if(i===idx)c+=" cur";else if(i<idx)c+=" done";
const sub=[p.budget!=null?`≤ ${p.budget} s`:"",p.invariant?`keep: ${p.invariant}`:"",p.exit?`next when: ${p.exit}`:""].filter(Boolean).map(x=>`<small>${esc(x)}</small>`).join("");
h+=(i?'<span class="arrow">→</span>':"")+`<div class="${c}" title="${esc(p.description)}"><b>${i<idx&&a.terminal!=="FAILURE"?"✓ ":""}${esc(p.name)}</b>${sub}</div>`});
h+=`<span class="arrow">⇢</span><div class="ph${a.terminal==="FAILURE"?" fault":""}" style="${a.terminal==="FAILURE"?"":"opacity:.45"}"><b>FAULT</b><small>${a.terminal==="FAILURE"?esc((a.fault||{}).name||""):"invariant broken / over budget / no progress"}</small></div>`;
document.getElementById("phases").innerHTML=h;
// task automaton
const A=a.automata[0];document.getElementById("fname").textContent=A?A.formula||A.name:"";
document.getElementById("aut").innerHTML=A?autSvg(A):"";
document.getElementById("props").innerHTML=a.props.map(p=>`<span class="${p.value===true?"t":p.value==null?"u":""}" title="${esc(p.meaning)}">${esc(p.name)} ${p.value===true?"✓":p.value===false?"✗":"?"}</span>`).join("");
document.getElementById("safety").innerHTML=a.safety.map(x=>`<span class="${x.status==="VIOLATED"?"v":""}" title="${esc(x.formula)}">${esc(x.name)}: ${esc(x.formula)} · ${x.status==="VIOLATED"?"VIOLATED":"ok"}</span>`).join("")||"<small>none</small>";
document.getElementById("guards").innerHTML=a.guards.map(g=>`<tr><td>${esc(g.name.replace("_condition",""))}</td><td><code>${esc(g.expr)}</code></td><td>${g.value===true?"✓":g.value===false?'<b class="alarm">✗</b>':"·"}</td></tr>`).join("");
}
function wrap(t,n){const w=String(t).replace(/ ([|&]) /g," $1\\u00a0").split(" ");const out=[];let cur="";for(const x of w){if(cur&&(cur+" "+x).length>n){out.push(cur);cur=x}else cur=cur?cur+" "+x:x}if(cur)out.push(cur);return out}
function autSvg(A){
const st=[...A.states].sort((x,y)=>x.id-y.id),n=st.length,W=n>3?128:170,R=22,top=46,cy=top+R+8;
const X=i=>W/2+i*W,pos={};st.forEach((s,i)=>pos[s.id]=i);
const H=cy+R+100,acc="var(--acc)",line="var(--line)",mut="var(--mut)",fg="var(--fg)";
let g=`<svg viewBox="0 0 ${W*n} ${H}" width="100%" style="max-width:${Math.round(W*n*1.35)}px" xmlns="http://www.w3.org/2000/svg"><defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="${mut}"/></marker><marker id="ahA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="${acc}"/></marker></defs>`;
for(const e of A.edges){const i=pos[e.from],j=pos[e.to];if(i==null||j==null)continue;const hot=A.prev!=null&&e.from===A.prev&&e.to===A.current&&A.prev!==A.current;
const x1=X(i),x2=X(j),dx=(x2>x1?1:-1);let d;if(Math.abs(j-i)===1)d=`M${x1+dx*R},${cy} L${x2-dx*(R+2)},${cy}`;else{const hgt=Math.min(top-6,18+14*Math.abs(j-i));d=`M${x1+dx*R*0.7},${cy-R*0.7} C${x1+dx*20},${cy-R-hgt} ${x2-dx*20},${cy-R-hgt} ${x2-dx*R*0.7},${cy-R*0.75}`}
g+=`<path d="${d}" fill="none" stroke="${hot?acc:line}" stroke-width="${hot?3.5:1.3}" marker-end="url(#${hot?"ahA":"ah"})"><title>${esc(e.label)}</title></path>`}
st.forEach((s,i)=>{const x=X(i),cur=s.id===A.current;
g+=`<path d="M${x-9},${cy-R+2} C${x-22},${cy-R-26} ${x+22},${cy-R-26} ${x+9},${cy-R+2}" fill="none" stroke="${cur?acc:line}" stroke-width="1.2" marker-end="url(#ah)"><title>${esc(s.stay)}</title></path>`;
g+=`<circle cx="${x}" cy="${cy}" r="${R}" fill="${cur?acc:"var(--card)"}" stroke="${cur?acc:mut}" stroke-width="${cur?3:1.4}"/>`;
if(s.accepting)g+=`<circle cx="${x}" cy="${cy}" r="${R-5}" fill="none" stroke="${cur?"#fff":mut}" stroke-width="1.2"/>`;
if(s.id===A.initial)g+=`<text x="${x-R-4}" y="${cy-R-4}" font-size="11" fill="${mut}" text-anchor="end">start</text>`;
g+=`<text x="${x}" y="${cy+6}" font-size="17" font-weight="700" text-anchor="middle" fill="${cur?"#fff":fg}">${s.id}</text>`;
let y=cy+R+18;if(s.meaning){for(const l of wrap(s.meaning,17)){g+=`<text x="${x}" y="${y}" font-size="13.5" font-weight="${cur?700:500}" text-anchor="middle" fill="${cur?acc:fg}">${esc(l)}</text>`;y+=16}}
if(s.stay&&s.stay!=="1"){g+=`<text x="${x}" y="${y}" font-size="11.5" text-anchor="middle" fill="${mut}">stays while</text>`;y+=14;
for(const l of wrap(s.stay,Math.floor(W/7.3)).slice(0,3)){g+=`<text x="${x}" y="${y}" font-size="11.5" font-family="ui-monospace,monospace" text-anchor="middle" fill="${mut}">${esc(l)}</text>`;y+=14}}
else if(s.accepting){g+=`<text x="${x}" y="${y}" font-size="11.5" text-anchor="middle" fill="${mut}">accepting: done</text>`}});
return g+"</svg>"}
</script></body></html>"""


def make_handler(stack: Stack, options: dict):
    from skill_monitor.core import api
    page = (PAGE.replace("__OPTIONS__", json.dumps(options))
            .replace("__OBS_TOPIC__", api.OBSERVATION)
            .replace("__VERDICT_TOPIC__", api.VERDICT)).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):        # quiet
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                return self._send(200, page, "text/html; charset=utf-8")
            if self.path == "/status":
                return self._send(200, json.dumps(stack.snapshot()).encode(),
                                  "application/json")
            if self.path == "/frame.jpg":
                if stack.frame is None:
                    return self._send(404, b"no frame yet", "text/plain")
                return self._send(200, stack.frame, "image/jpeg")
            if self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                seen = -1
                try:
                    while True:
                        with stack.frame_cv:
                            stack.frame_cv.wait_for(lambda: stack.frame_no != seen, timeout=5)
                            frame, seen = stack.frame, stack.frame_no
                        if frame is None:
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                         + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                                         + frame + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path == "/pause":
                stack.set_paused(not stack.paused.is_set())
                return self._send(200, json.dumps({"paused": stack.paused.is_set()}).encode(),
                                  "application/json")
            if self.path != "/run":
                return self._send(404, b"not found", "text/plain")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                run = {"fault": body.get("fault", "drop"), "spec": body.get("spec", "full"),
                       "policy": body.get("policy", "off"), "seed": int(body.get("seed", 0)),
                       "speed": float(body.get("speed", 2.0))}
                if (run["fault"] not in options["fault"] or run["spec"] not in options["spec"]
                        or run["policy"] not in options["policy"]):
                    raise ValueError("unknown fault, spec or policy")
                if run["spec"] == "closed_loop":
                    run["policy"] = "off"
            except (ValueError, TypeError) as exc:
                return self._send(400, str(exc).encode(), "text/plain")
            stack.submit(run)
            return self._send(202, b"started", "text/plain")

    return Handler


def main(argv=None) -> int:
    from task import FAMILIES
    import run_e1b

    parser = argparse.ArgumentParser(description="Run the whole stack with a web view.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--domain", type=int, default=42, help="ROS_DOMAIN_ID")
    parser.add_argument("--logdir", default=str(Path.home() / ".ltl_stack_logs"))
    parser.add_argument("--fps", type=float, default=8.0, help="rendered frames per second")
    parser.add_argument("--run", default=None,
                        help="start one preset at launch, e.g. 'drop,full,off'")
    text = parser.add_argument_group("--text: one run in the terminal, no web page")
    text.add_argument("--text", action="store_true")
    text.add_argument("--fault", default="drop", choices=list(FAMILIES))
    text.add_argument("--spec", default="full", choices=list(run_e1b.ARMS))
    text.add_argument("--policy", default="off", choices=["off", "detect", "recover"])
    text.add_argument("--seed", type=int, default=0)
    text.add_argument("--speed", type=float, default=50.0,
                      help="simulated seconds per wall second (the web page uses 2)")
    args = parser.parse_args(argv)
    if not 0 <= args.domain <= 101:
        parser.error("--domain must be 0..101 (ROS 2 domain IDs)")
    if not os.environ.get("G1SIM_ASSETS"):
        print("G1SIM_ASSETS is not set: run sim/fetch_assets.sh DIR and export it "
              "(the Docker image and run.py do this).", file=sys.stderr)
        return 2
    if args.text:
        return run_text(args)
    options = {"fault": list(FAMILIES), "spec": list(run_e1b.ARMS),
               "policy": ["off", "detect", "recover"], "presets": PRESETS}
    stack = Stack(args.domain, Path(args.logdir), fps=args.fps)
    if args.run:
        fault, spec, policy = args.run.split(",")
        stack.submit({"fault": fault, "spec": spec, "policy": policy, "seed": 0, "speed": 2.0})
    server = ThreadingHTTPServer((args.host, args.port), make_handler(stack, options))
    server.daemon_threads = True
    shown = "localhost" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
    print(f"\n  LTL monitor demo: open http://{shown}:{args.port}\n", flush=True)
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping", flush=True)
    return 0


def run_text(args) -> int:
    """The same stack -- evaluator and monitor as ROS 2 processes -- for one run, printing
    the tick log. What sim/demo_e1b.py --no-view prints, but over DDS."""
    from demo_common import HEADER
    policy = "off" if args.spec == "closed_loop" else args.policy
    print(f"starting the evaluator and the monitor ({args.spec} spec) as ROS 2 processes, "
          f"ROS_DOMAIN_ID {args.domain}", flush=True)
    stack = Stack(args.domain, Path(args.logdir), fps=0,
                  echo=lambda line: print(line, flush=True))
    first = [True]

    def echo(line):                       # the run's first line describes it
        print(line, flush=True)
        if first[0]:
            first[0] = False
            print("\n" + HEADER, flush=True)
    stack.echo = echo
    stack.submit({"fault": args.fault, "spec": args.spec, "policy": policy,
                  "seed": args.seed, "speed": args.speed})
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        while True:
            state = stack.finished.get()
            if state.get("result") or state.get("error") or state["stack"] == "error":
                break
    except KeyboardInterrupt:
        return 130
    print(f"\nROS 2 graph: {', '.join(state['graph'].get('nodes', []))}")
    if state.get("error"):
        print(f"error: {state['error']}", file=sys.stderr)
        return 1
    print(state["result"], flush=True)
    stack.requests.put(None)              # let the ROS thread stop its nodes
    stack.thread.join(timeout=20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
