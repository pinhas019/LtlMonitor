#!/usr/bin/env python3
"""The console, as one file you can send somebody.

    python3 -m skill_monitor.frontend.web --mock --port 8799 &
    python3 tools/console_snapshot.py capture http://127.0.0.1:8799 run.json 45
    python3 tools/console_snapshot.py build   run.json console.html

`capture` records a window of the console's own stream -- the latched documents first,
then every frame that arrives -- through the gateway's HTTP and WebSocket API, which is
the same path the page itself uses. `build` glues that recording into `index.html` behind
a transport shim, so the result is one self-contained page with no server, no ROS and no
network: open it over `file://` and it replays the run in a loop, with the buttons live.

**This is not `backend/replay_node.py` and does not overlap with it.** That one records
the ROS topics and re-runs the *monitor* over them to compare verdicts; it is a
correctness check. This one records what the *page* was shown and re-runs the page; it is
a screenshot that moves. It exists because a still frame of a live monitor is a monitor
you cannot tell is running -- and because the preview tooling's screenshot times out on
this page, so "show me" has to be something the reader runs rather than something I send.

Works against `--mock` and against a real robot equally: the page has no vocabulary of
its own, so a capture off the G1 renders the same way this one does.
"""

import json
import pathlib
import sys
import time
import urllib.request

HDR = {"X-Skill-Monitor": "1"}

# The shim. Replaces `fetch` and `WebSocket` before `index.html`'s own script runs, so the
# page is unmodified -- which is the point: what you look at is the console, not a mockup
# of it. `%s` is the recording; `%%` is an escaped percent for the modulo below.
SHIM = """
<script>
const CAP = %s;
const T = CAP.topics;
let ST = Object.assign({}, CAP.latched[T.status]);
let ECHO = null, lastSeq = 0, sock = null;
const seg = CAP.ns.replace(/^\\//, "");
function emit(topic, payload) {
  if (sock && sock.onmessage)
    sock.onmessage({data: JSON.stringify({ns: CAP.ns, topic: topic, dropped: 0, payload: payload})});
}
function setState(state, reason) {
  ST = {schema_version:1, seq:lastSeq, t:lastSeq, state:state, reason:reason, since_seq:lastSeq};
  emit(T.status, ST);
}
window.fetch = async (path, opts) => {
  const method = ((opts||{}).method || "GET").toUpperCase();
  if (method === "POST" && path === `/api/monitors/${seg}/command`) {
    let cmd=null; try { cmd = JSON.parse((opts||{}).body||"{}").command; } catch(e){}
    if (CAP.commands.indexOf(cmd) < 0)
      return {status:400, text: async () => JSON.stringify({ok:false, error:"unknown command"})};
    setState(cmd === "pause" ? "paused" : "running", "operator command");
    return {status:202, text: async () => JSON.stringify({ok:true, published:cmd})};
  }
  if (method === "POST" && path === `/api/monitors/${seg}/raw_echo_request`) {
    let sid=null; try { sid = JSON.parse((opts||{}).body||"{}").source_id; } catch(e){}
    ECHO = sid;
    return {status:202, text: async () => JSON.stringify({ok:true, published:{source_id:sid}})};
  }
  if (method === "POST" && path === "/api/clock/step")
    return {status:409, text: async () => JSON.stringify({ok:false,
      error:"this is a recording; the clock that produced it is not running"})};
  let body = null;
  if (path === "/api/health") body = {ok:true, ros:{available:true, detail:"a captured run, replayed in the browser"}};
  else if (path === "/api/monitors") body = CAP.monitors;
  else if (path === `/api/monitors/${seg}/status`) body = ST;
  else {
    const hit = Object.keys(CAP.latched).find(k => path.endsWith("/" + k.split("/").pop()));
    if (hit) body = CAP.latched[hit];
    else return {status:503, text: async () => JSON.stringify({ok:false, error:"replay: no monitor"})};
  }
  return {status:200, text: async () => JSON.stringify(body)};
};
window.WebSocket = class {
  constructor() {
    this.readyState = 1; sock = this; let i = 0;
    setTimeout(() => { this.onopen && this.onopen(); emit(T.status, ST); }, 0);
    const pump = () => {
      if (!this.onmessage) return setTimeout(pump, 40);
      if (ST.state !== "running") return setTimeout(pump, 120);
      const f = CAP.frames[i %% CAP.frames.length]; i++;
      if (f.topic === T.echo && !ECHO) return setTimeout(pump, 2);
      if (f.payload && typeof f.payload.seq === "number") lastSeq = f.payload.seq;
      emit(f.topic, f.payload);
      setTimeout(pump, f.topic.endsWith("/verdict") ? 140 : 4);
    };
    pump();
  }
  close() {} send() {}
};
window.confirm = () => true;
</script>
"""


def _get(base, path):
    req = urllib.request.Request(base + path, headers=HDR)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _post(base, path, body):
    req = urllib.request.Request(
        base + path, method="POST", data=json.dumps(body).encode(),
        headers=dict(HDR, **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def capture(base, out, seconds):
    # Imported here and not at module scope: `build` is fully offline -- a recording and
    # `index.html` -- and importing the gateway for it made the whole tool unrunnable
    # from a checkout that is not on `sys.path`. `capture` genuinely needs both, so it
    # still fails loudly, and only when it is the half being asked for.
    from skill_monitor.backend.gateway import ws_connect
    from skill_monitor.core import api

    monitors = _get(base, "/api/monitors")
    if not monitors.get("monitors"):
        raise SystemExit(f"{base}: the gateway has discovered no monitor to record")
    ns = monitors["monitors"][0]["ns"]
    seg = ns.lstrip("/")

    # The latched documents first. A page that joined late gets these from the gateway,
    # so a recording without them is a recording of a console that never loaded a spec.
    latched = {}
    for verb, topic in sorted({t.rsplit("/", 1)[-1]: t for t in api.LATCHED_TOPICS}.items()):
        try:
            latched[topic] = _get(base, f"/api/monitors/{seg}/{verb}")
        except Exception as exc:                       # a build without that route
            print(f"no {verb}: {exc}", file=sys.stderr)

    # One echo asked for, so panel 4 has a frame in it rather than an empty picker.
    sources = (latched.get(api.ADAPTER) or {}).get("sources") or []
    if sources:
        _post(base, f"/api/monitors/{seg}/raw_echo_request",
              api.build_raw_echo_request(source_id=sources[0]["id"]))

    frames = []
    ws = ws_connect(base.replace("http", "ws") + f"/api/monitors/{seg}/stream", timeout=5)
    end = time.time() + seconds
    while time.time() < end:
        try:
            text = ws.recv()
        except Exception:
            break
        if text is None:
            break
        frame = json.loads(text)
        if frame.get("topic") and frame.get("payload") is not None:
            frames.append({"topic": frame["topic"], "payload": frame["payload"]})
    ws.close()

    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"frames": frames, "latched": latched, "ns": ns,
                   "topics": {"tick": api.TICK, "obs": api.OBSERVATION,
                              "verdict": api.VERDICT, "status": api.MONITOR_STATUS,
                              "echo": api.RAW_ECHO},
                   "commands": list(api.COMMANDS), "monitors": monitors},
                  fh, separators=(",", ":"))
    counts = {}
    for f in frames:
        counts[f["topic"]] = counts.get(f["topic"], 0) + 1
    print(f"{out}: {len(frames)} frames {counts}", file=sys.stderr)


def build(recording, out):
    here = pathlib.Path(__file__).resolve().parents[1]
    page = (here / "skill_monitor" / "frontend" / "index.html").read_text(encoding="utf-8")
    cap = pathlib.Path(recording).read_text(encoding="utf-8")

    # Head and body only: an artifact host supplies the skeleton. The charset stays in
    # it. Over `file://` -- which is how the docstring and `RESUME.md` both say to open
    # the result -- there is no HTTP header to say utf-8, and the page is full of `ⓘ ✖ ·
    # — Büchi`, so stripping it rendered a wall of mojibake. A host that wraps this in
    # its own skeleton gets the same declaration twice, which costs nothing.
    body = (page.split("<head>", 1)[1].split("</head>", 1)[0]
            + page.split("<body>", 1)[1].rsplit("</body>", 1)[0])

    # `json.dumps` does not escape `/`, so a payload that ever recorded the text
    # `</script>` would close the shim's own block and the rest of the file would be
    # read as markup. The snapshot is made to be sent to somebody; it has to survive
    # its own contents.
    shim = SHIM % cap.replace("</", "<\\/")
    out_html = body.replace('<script>\n"use strict";', shim + '<script>\n"use strict";', 1)
    if shim not in out_html:
        raise SystemExit("the page's script tag moved; the shim has nowhere to go")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(out_html)
    print(f"{out}: {len(out_html)} bytes", file=sys.stderr)


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__.split("\n\n")[1].strip())
    if argv[0] == "capture":
        capture(argv[1], argv[2] if len(argv) > 2 else "run.json",
                float(argv[3]) if len(argv) > 3 else 45.0)
    elif argv[0] == "build":
        build(argv[1], argv[2] if len(argv) > 2 else "console.html")
    else:
        raise SystemExit(f"unknown command {argv[0]!r}; want capture or build")


if __name__ == "__main__":
    main(sys.argv[1:])
