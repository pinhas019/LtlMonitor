# ROSMonitoring: A Runtime Verification Framework for ROS

Ferrando, Cardoso, Fisher, Ancona, Franceschini & Mascardi — TAROS 2020, LNCS 12228, pp. 387–399.
Key: `ferrando2020rosmonitoring`. See `bibtex.md`.

> **Use the successor too.** A direct extension exists: **ROSMonitoring 2.0** (Ghaffari Saadat,
> Ferrando, Dennis & Fisher, FMAS 2024, EPTCS 411:38–55, [arXiv:2411.14367](https://arxiv.org/abs/2411.14367)).
> It adds service monitoring and publication-order traces, and it contains the clearest
> first-party description of the 2020 architecture (its §2.2). The code line has moved further
> still: the official repo's `master` was rewritten on **29 June 2026** into an integrated
> v3.0.0 covering ROS1 **and** ROS2. Cite 2020 for the framework, 2.0 for services/ordering, and
> describe the tool from the repo if you claim anything about what it does *today*.

---

## Provenance — what I actually read

Read carefully because this determines which claims below you may repeat in a paper.

| Source | How much I read |
|---|---|
| ROSMonitoring 2.0, FMAS 2024 (arXiv:2411.14367) | **Full text of the relevant pages** (1–6, 9–11, 13–14, 16–17) via PDF retrieval |
| Varanus, arXiv:2506.14426 | Full text — used only to cross-check the 2020 citation |
| Caldas et al., *RV and Field-based Testing for ROS-based Robotic Systems*, arXiv:2404.11498 | Full text of the instrumentation/specification guideline tables |
| `github.com/autonomy-and-verification-uol/ROSMonitoring` | `master` README (37 KB), `docs/architecture.md`, `src/rosmonitoring/instrumentation.py`, `examples/tutorials/topic_filter_rml.yaml`, `LICENSE`, `pyproject.toml`, full branch list, full commit list — all read directly |
| `ros1_legacy` and `old_without_remapping` branch READMEs | Fetched, but returned to me as a **tool-generated summary with a few verbatim quotes**, not the raw file |
| **The TAROS 2020 paper itself** | **NOT read.** See below. |

**I could not obtain the 2020 PDF.** The network egress proxy in this environment blocks
`link.springer.com`, `dl.acm.org`, `dblp.org`, `dblp.uni-trier.de`, `semanticscholar.org`,
`researchgate.net`, `research.manchester.ac.uk`, `ceur-ws.org`, `pmc.ncbi.nlm.nih.gov`,
`unige.iris.cineca.it` and `angeloferrando.github.io`. An author preprint exists at
`unige.iris.cineca.it/retrieve/e268c4cd-59c8-a6b7-e053-3a05fe0adea1/ROSMonitoring_ICRA2020.pdf`
(titled for an earlier ICRA submission) — **fetch it yourself; it is the version to read.**
Everything I state about the 2020 paper's *own* Sections 4–5 comes from search-engine snippets
of that preprint and is marked `[snippet-only]`. Everything about the architecture comes from
the 2.0 paper's first-party restatement of it, or from the code, and is marked accordingly.

**Author list: VERIFIED.** The list you were given is correct, in that order. Confirmed
independently three times: (a) reference [15] of the FMAS 2024 paper, read verbatim from the PDF;
(b) reference [12] of the Varanus arXiv paper, read verbatim; (c) the DBLP-exported BibTeX
pasted in the official repository's README on github.com. DBLP itself was unreachable, so the
BibTeX in `bibtex.md` is a DBLP *export* recovered from the authors' own repo rather than a
DBLP page I loaded — cross-checked field-by-field against (a) and (b).

---

## 1. In one paragraph

ROSMonitoring is a runtime-verification framework for ROS that turns a YAML file listing
topics into generated Python ROS **monitor nodes**, and pairs them with an **external oracle**
that decides verdicts. The monitor's only job is to observe a ROS message, flatten it into a
JSON event, and — in online mode — send it over a WebSocket to the oracle and act on the reply;
the oracle's only job is to decide whether the trace so far satisfies a formal property. That
split is the whole design idea: because the interface between them is JSON-over-WebSocket, the
framework is **formalism-agnostic** — RML, past-LTL, past-MTL and past-STL oracles all ship with
it, and any other oracle speaking the protocol drops in unchanged. Because the monitor is an
ordinary ROS node written in rospy rather than a patched middleware, the framework is
**portable across ROS distributions**. A monitor can passively `log` events, or `filter` them:
in filter mode the monitor is spliced *into* the communication path by topic remapping and
drops messages the oracle rejects, making it a runtime *enforcer*, not just a detector. The
2020 paper demonstrates this on a simulated Mars Curiosity rover with RML properties, plus
scalability experiments measuring the message-delivery delay the monitors add.

---

## 2. Key concepts

**Monitor / oracle split.** ROSMonitoring's defining structural choice.
The *monitor* is a generated ROS node: it intercepts or observes messages, serialises each one
as JSON, logs it, and (online) asks the oracle. The *oracle* is a process entirely outside ROS
that owns the formalism and the property. Quoting 2.0 §2.2.2: "ROSMonitoring decouples the
message interception (monitor) and the formal verification aspects (oracle) and so is highly
customizable… ROSMonitoring requires very few constraints for adding a new oracle." The oracle
never sees a ROS message type, only JSON. This is the reason the framework can claim formalism
agnosticism, and it is also why it has no way to check that a property's predicates correspond
to anything the robot actually publishes (see §6).

**Specification language — there isn't one; there are several.** The framework deliberately has
no native property language. Three oracle bundles ship in the repo's `oracle/` directory:
- **RML** (Runtime Monitoring Language) — the Genoa group's own DSL (Ancona, Franceschini,
  Ferrando, Mascardi, *SCP* 205:102610, 2021). An `.rml` file is compiled by `rml-compiler.jar`
  into a SWI-Prolog *trace expression*; a Prolog oracle then listens on a WebSocket. This is the
  oracle used in the 2020 paper's rover case study. `[snippet-only]` for the case-study claim.
- **TL oracle** — wraps the **Reelay** library, supporting **past-LTL, past-MTL and past-STL**.
  This is what the 2.0 paper uses (its Table 1 gives six properties in "Past Metric Temporal
  Logic according to the Reelay Expression Format").
- **LamaConv** (`rltlconv.jar`) — LTL/automata conversion. Present in the repo; I did not
  confirm it was in the 2020 paper.

**Online vs offline monitoring.** From 2.0 §2.2.3, verbatim: "**offline monitors** which simply
log the intercepted events in a specified file to be parsed by the Oracle later"; "**online
monitors** which query the Oracle in real time". Concretely, a monitor with no `oracle:` block
in its YAML is offline. Note this is *not* deterministic replay in the sense you need — see §6.

**Log vs filter (detection vs enforcement).** Orthogonal to online/offline, and the more
important axis. 2.0 §2.2.3, verbatim: with logging-without-filtering, "if the online monitor
finds a violation… it publishes a warning message… However, the monitor does not stop the
message from propagating further in the system. In contrast, if filtering is enabled, since
monitors can be placed between the communication of different nodes, ROSMonitoring monitors
enforces the property under analysis by not propagating messages that represent a property
violation. **This is achieved by directing communication on the monitored topics to pass
through the monitors.**"

**Verdict domain.** 2.0 §2.1: "A monitor returns ⊤ if the trace satisfies the property, ⊥ if it
violates it, and ? if there is insufficient information. Depending on the property's formalism,
? may further split into ?⊤ or ?⊥." So three- or four-valued depending on the oracle, and the
wire protocol carries `true`, `false`, `currently_true`, `currently_false`, `unknown`. This is
close to your LTL3 domain; you can call it comparable rather than different.

**Instrumentation.** In ROSMonitoring the word means: run a generator over a YAML config, which
emits monitor nodes *and edits the application's launch files* to remap topic names, creating a
"gap" in the communication that the monitor then bridges. Details in §3.

---

## 3. Architecture and instrumentation — concretely

### 3.1 The pipeline

The 2020 paper's Figure 1 (reproduced and described in 2.0 §2.2) is:

```
config.yaml ──▶ instrument ──▶ { monitor.py , instrumented nodes/launch files }
                                      │
                                      ├── online ──▶ oracle ◀── spec
                                      └── offline ─▶ log.txt ──▶ oracle ◀── spec
```

Per 2.0 §2.2.1, verbatim: "ROSMonitoring starts with a YAML configuration file to guide the
instrumentation process required to generate the monitors. Within this file, the user can
specify the communication channels, called 'ROS topics', to be intercepted by each monitor. In
particular, the user indicates the name of the topic, the ROS message type expected in that
topic, and the type of action that the monitor should perform. After preferences have been
configured in `config.yaml`, the last step is to run the generator script to automatically
generate the monitors **and instrument the required ROS launch files**."

A representative config (from the repo, `examples/tutorials/topic_filter_rml.yaml`, read
verbatim):

```yaml
ros_version: ros2
monitors:
  - monitor:
      id: rml_chatter_guard
      log: ./logs/rml_chatter_guard.jsonl
      status: {enabled: true, log: ./logs/status.jsonl}
      oracle: {url: 127.0.0.1, port: 8080, action: nothing}
      topics:
        - name: chatter
          type: std_msgs.msg.String   # ← the real ROS type, not a JSON envelope
          action: filter
          publishers: [chatter_talker]
```

### 3.2 The event on the wire

One flat JSON object per observed message, sent over WebSocket and written to a JSONL log
(repo `docs/architecture.md`, verbatim):

```json
{"topic": "battery_status", "time": 1782469999.9, "data": "critical"}
{"service": "set_led", "time": 1782469999.9, "request": {"data": true}}
```

Message fields are **flattened next to `topic` and `time`**. The oracle replies
`{"verdict": true}` / `{"verdict": false}` or a legacy string verdict. Monitors also republish
the normalised verdict inside ROS on `/<monitor_id>/monitor_verdict` as `std_msgs/String`
(latched in ROS1, transient-local QoS in ROS2), so application nodes can react. The repo calls
this "the legacy ROSMonitoring verdict publication contract"; the `with_verdict` branch dates
from **November 2021**, so I would **not** claim this feature is in the 2020 paper.

### 3.3 How invasive is it, exactly

This is your question 1 and it deserves a precise answer, because a flat "ROSMonitoring is
invasive" is attackable.

**Three regimes, from the current repo's "Propagation Semantics" section (verbatim):**

> For topics:
> - non-intercepting monitor: subscribe to the original topic and log/check;
> - intercepted publisher-side topic: subscribe to `<topic>_mon`, publish accepted messages to `<topic>`;
> - intercepted subscriber-side topic: subscribe to `<topic>`, publish accepted messages to `<topic>_mon`.
>
> For services: serve `<service>_mon`; … if accepted, call the original `<service>`; … return the
> original response to the client.

So:

1. **Log-only, no `publishers:`/`subscribers:` entry → genuinely passive.** The monitor is an
   ordinary subscriber on the real topic. Nothing in the robot stack changes. This is the mode
   the Caldas et al. survey (arXiv:2404.11498) has in mind when it files ROSMonitoring under
   *outline* logging — "techniques that enable an external means to gather and filter
   information that **does not require changing the source code**". **Do not claim
   ROSMonitoring cannot observe passively. It can.**

2. **Filtering / interception → strictly invasive.** The monitor is spliced into the path by
   renaming topics. Somebody must make the publisher publish to `chatter_mon` instead of
   `chatter`. In the ROS1 line the generator did this for you by rewriting node source and
   launch files. The `old_without_remapping` branch (Aug 2019) is named for the fact that the
   main line *added* remapping; its README describes the mechanism as "the talker publishes on
   a different topic now (`chatter_mon`), while the listener… listens on the old one
   (`chatter`)", and the `ros1_legacy` README says the generator "instrument[s] the nodes
   changing the names and creating gaps in the communications", adding `remap` parameters to
   generate `run_instrumented.launch`.

3. **Services (2.0) → unavoidably invasive.** 2.0 §4.1, verbatim: "when monitoring services,
   our monitor node **must directly intervene** in the communication between the server and
   client. The monitor node then assumes the role of a server for the client, and conversely
   acts as a client for the server." There is no passive service mode.

The single most quotable piece of evidence is in the current code. `src/rosmonitoring/instrumentation.py`
is a 40-line module whose whole job is to inject `<remap from=… to=…>` elements into the user's
ROS1 XML launch file, in place, and its docstring reads (verbatim):

> "Add missing remap tags to a ROS1 XML launch file. … The function is intentionally small and
> deterministic so it can be used in tests and **reviewed before applying invasive
> instrumentation to application launch files**."

The maintainers call it invasive instrumentation themselves.

**The defensible claim for your paper:** *ROSMonitoring's detection mode can be passive, but its
distinguishing capability — filtering, i.e. runtime enforcement — requires interposing a proxy
node in the message path, achieved by remapping topic names in the application's launch files
(and, in the ROS1 line, its node sources). `skill_monitor` obtains its observations without any
such rewrite.* That is true, checkable, and does not overreach.

**A second, cleaner distinction that costs you nothing.** ROSMonitoring monitors are typed
against the real ROS interface: the YAML names `std_msgs.msg.String`,
`geometry_msgs.msg.PoseStamped`, `example_interfaces.srv.AddTwoInts`, and the repo states
"Generated ROS2 packages declare `ament_python` and **message/service package dependencies
inferred from the YAML interface types**." A ROSMonitoring deployment therefore needs the
robot's `.msg`/`.srv` packages available at monitor build time. Your `std_msgs/String`-carrying-JSON
wire format removes that dependency outright. This is a real, verifiable architectural
difference and a reviewer can check it in five minutes.

---

## 4. Evaluation

### 4.1 The 2020 paper `[snippet-only — verify against the preprint before citing]`

- **Case study: a simulated Mars Curiosity rover.** Four waypoints (o, A, B, C) spread over
  Martian terrain. Properties written in **RML**, compiled to SWI-Prolog trace expressions. The
  `filter` action was used "to intercept external message sources (e.g. human or autonomous
  agent) that violate the property" — i.e. the demonstration is of *enforcement*, not just
  detection. (A companion paper, *Heterogeneous Verification of an Autonomous Curiosity Rover*,
  arXiv:2007.10045, covers the same system.)
- **Scalability experiments.** Overhead is defined as **the delay introduced in message
  delivery time between ROS nodes**. Setup: **10 nodes, 10 topics** (one publisher per topic),
  publication frequency swept over **100, 500 and 1000 Hz** → **1000, 5000 and 10000 msg/s**.
  The property under test was held fixed and deliberately trivial — "a property which analyzes
  each event in constant time and is always considered satisfied" — so the measurement isolates
  the *monitor's* cost from the oracle's. The paper also varies system size and monitor count.
- **Findings.** At 100 Hz / 1000 msg/s "the presence of one or multiple monitors was practically
  transparent to the system". Overheads from RML monitors are reported as "slight" / "negligible";
  increasing the number of rover waypoints increased mission time but "the overhead introduced
  by the monitors remained almost constant".

I have **no verified number** for the delay at 500 or 1000 Hz, and none for the multi-monitor
sweep. Do not put a figure in a table from this summary — read the preprint.

### 4.2 ROSMonitoring 2.0 (read directly, cite freely)

- **Case study: a Battery Supervisor for a fire-fighting UAV.** Three nodes — Battery (publishes
  `/battery_percentage`), Battery Supervisor (publishes `/battery_status`, calls `/SetLED`),
  LED Panel. **ROS1 Noetic.** Node frequencies **25 / 10 / 35 Hz**. **10 runs, averaged, with
  mean and standard deviation reported**; each run ends when the battery hits zero.
- **Six properties in past-MTL** (Reelay Expression Format), in three groups: topic-only,
  topic+service, service-only. Each group has a correspondence property (a) and a bounded-response
  property (b) with a 100-time-step window.
- **Headline result, verbatim:** "the overhead incurred by monitoring `/SetLED` without ordering
  appears negligible, but **the introduction of ordering substantially delays the process**,
  particularly noticeable during the last status change."
- **Ordering can deadlock.** The paper reports having to restructure the *application* to make
  ordering work: a redundant `/status_change` topic left deliberately unordered, and separation
  of topic publication from service invocation, "so that the service does not block the receipt
  of messages needed for producing a response." They offer the redundancy trick as "a general
  technique to prevent deadlocks." This is a strong, honest limitation and it is worth citing.
- **They concede there is no benchmark yet:** "a comprehensive performance evaluation of
  ROSMonitoring 2.0 will be a critical focus. We aim to assess key metrics such as execution
  time, resource usage, and system overhead, benchmarking our approach against existing
  alternatives."

---

## 5. Limitations

**Of the 2020 framework, as stated by its own successor (2.0 §1):**
- **Services are not supported at all**, "restricting the framework's functionality to solely
  monitoring messages."
- **Order is subscriber-receive order.** "The framework orders messages based on the
  chronological order in which they are received by subscriber nodes… ROSMonitoring does not
  currently provide a representation of the order in which messages are published and received."
  For any multi-topic property this is a soundness hazard, not merely an inconvenience.
- **ROS1 only.**

**Of 2.0, as stated by 2.0:**
- ROS2 support is **partial**: service monitoring was ported; message reordering was not.
- Ordering costs real latency and introduces deadlock risk requiring manual application-level
  workarounds.
- The reordering algorithm rests on **Assumption 1** — "messages on each single topic arrive at
  subscribers in the order of publication" — which is what the correctness lemma is proved
  relative to. Fine for ROS1 TCP; worth a second look under lossy ROS2 QoS profiles, which the
  authors themselves flag as future work ("a balance must be struck between message order and
  timely delivery").

**Structural limitations neither paper frames as limitations, but which matter to you:**
- **Specifications are entirely hand-written**, in a formalism the user picks. There is no
  elicitation, no synthesis, no natural-language front end anywhere in either paper.
- **No grounding check.** 2.0's Table 2 is titled "Predicates construction based upon JSON
  messages sent to Oracle" — the mapping from message fields to property atoms (`percentage`,
  `status`, `status_change`, `req_id`…) is written by hand, per case study, and nothing verifies
  it against the message schema. A property naming a field that does not exist simply never
  fires. The YAML pins the ROS *type* for deserialisation, but that is a build-time import, not
  a check that the property's atoms are satisfiable.
- **Filtering monitors are on the critical path.** The repo is explicit: a filtering monitor
  "records the terminal verdict but keeps running; stopping it would break the ROS application
  path it is protecting." Latency and liveness of the robot now depend on the monitor and on the
  oracle's WebSocket round-trip.
- **No timing model of its own.** There is no external clock and no notion of a tick; the
  monitor steps once per observed message. Under the ordering extension the step order is
  source-timestamp order, but the trace is still message-driven, not clock-driven.

---

## 6. For `skill_monitor`

### Q1 — How does ROSMonitoring instrument a ROS system?

**Answer: it depends on the mode, and you must say which.** Passive subscription for log-only
monitoring on unremapped topics; **launch-file remapping to interpose a proxy node** for
filtering; **an unavoidable proxy server/client pair** for services. The generator edits the
user's launch files (`instrumentation.py` injects `<remap>` tags in place, in a function whose
own docstring calls this "invasive instrumentation"); the ROS1 generator also rewrote node
sources. There is **no** ROS Master replacement — that is ROSRV's approach, and 2.0's related
work draws exactly this contrast: "ROSRV replaces the ROS Master node with RVMaster… In
contrast, ROSMonitoring adds the monitor through node instrumentation without altering the ROS
Master node."

Phrase your claim as: *ROSMonitoring supports passive observation but requires rewriting the
application's launch files to interpose a proxy node whenever it enforces; `skill_monitor` never
modifies the robot stack.* Then add the message-typing point (§3.3) — it is the sharper and more
easily verified half of the distinction.

### Q2 — Where do their specifications come from?

**Hand-written, in a formalism of the user's choosing, with no synthesis and no grounding step
at all.** RML in the 2020 rover study; past-MTL via Reelay in 2.0; LamaConv also bundled. The
framework's *selling point* is that it refuses to own a specification language. There is no NL
front end, no LLM, no requirements elicitation, and no static validation that a property's atoms
correspond to fields the robot publishes — the field→predicate mapping is a hand-built table per
case study (2.0 Table 2).

This is precisely the gap `skill_monitor` claims. It also means ROSMonitoring is **complementary
rather than competing**: a `skill_monitor`-generated automaton could in principle be served as a
ROSMonitoring oracle over the WebSocket protocol, since the protocol is JSON in / verdict out.
Worth one sentence in related work — it shows you understand the design rather than dismissing it.

### Q3 — Tool-table row

| Tool | Spec synthesis from NL | Schema grounding | Embodiment portability | Deterministic replay |
|---|---|---|---|---|
| **ROSMonitoring** (2020; 2.0, 2024) | **No** — hand-written specs; formalism-agnostic by design, no NL front end in either paper | **No** — YAML pins the ROS message *type* for deserialisation, but field→predicate mapping is hand-written per case study and unchecked | **Partial / manual** — portable across *ROS distributions* (an ordinary rospy node, no middleware patch), but a new robot needs a new YAML, new remaps and hand-rewritten predicates. **No** per-embodiment adapter layer | **Partial** — offline mode replays a JSONL log through the oracle, and 2.0 adds source-timestamp reordering, but there is no clock/tick discipline and no determinism claim |

**Flag as unsupported (do not claim without checking the preprint yourself):**
- *Deterministic replay* is the shakiest cell. Offline log-then-check is real and documented. But
  neither paper claims replay determinism, and the ordering machinery has a `max_delay_ms`
  watermark, timeouts and a "flush on stop" path — all of which make bit-identical re-runs a
  thing to demonstrate, not assume. **Write "offline log replay; determinism not claimed"** rather
  than a bare ✓ or ✗.
- *Embodiment portability* — "portable" in the abstract means across **ROS distributions**, not
  across robots. Do not let the word do work it was not meant to do, in either direction.
- Every cell here is about the framework as published. If you also run the June 2026 repo, say
  which artefact each claim is about.

**What ROSMonitoring has that you should credit it with,** because a reviewer who knows the tool
will notice if you don't: enforcement (message and service filtering), service monitoring,
publication-order traces, four oracle formalisms out of the box, and an in-ROS verdict topic.

### Q4 — Is it maintained and usable today?

**Yes — and more actively than the 2020 date suggests. Check the repo before you write "2020
tool" anywhere.**

Verified directly on github.com (`autonomy-and-verification-uol/ROSMonitoring`, MIT, 44 stars):

- **`master` was rewritten on 29 June 2026** by AngeloFerrando — three commits, the base one
  titled *"New ROSMonitoring integrating ROS1, ROS2, services, and ordering"*. `LICENSE` carries
  "Copyright (c) 2019 Angelo Ferrando / Copyright (c) 2026 ROSMonitoring contributors".
- **`pyproject.toml` declares `rosmonitoring` v3.0.0**, Python ≥3.9, PyYAML only for generation.
  CLI: `python3 -m rosmonitoring.cli validate|generate|status`. **I did not confirm a PyPI
  release** — pypi.org failed to load in this environment. Assume you install from a git clone.
- **Branches:** `master` and `ros1_legacy` (both 2026-06-29), `ros2` (2025-02-20),
  `ros_services_1and2` (2024-04-20), `with_verdict` (2021-11-02), `add-license-1` (2020-01-27),
  `old_without_remapping` and `curiosity` (2019-08-29). The feature lines that were scattered
  across branches have been merged into one generator.
- **It ships tests**, which is the thing that decides whether you can run it as a baseline:
  pytest unit/regression tests that need no ROS at all; a ROS2 integration test that generates a
  workspace, builds it with `colcon` and drives real ROS2 processes end to end; and a ROS1 Docker
  smoke test against `ros:noetic-ros-base`.
- The README self-reports "64 passed, 1 skipped" unsourced, "65 passed" with Humble sourced, a
  passing standalone ROS2 integration test, ten tutorial workspaces generated and built, and a
  full turtlesim + Reelay ROS2 end-to-end case study. **These are the maintainer's own claims; I
  did not execute anything.**

**Practical read for an ICRA baseline:** the framework/oracle protocol has been stable since
2020 and RML/Reelay/LamaConv oracles are checked in and runnable, so a genuine head-to-head is
realistic. Two cautions: (i) the tool you would run in 2026 is materially more capable than the
2020 paper — attribute correctly, and cite 2.0 for services/ordering; (ii) `master` is only three
commits old and the ROS1 line lives on a separate `ros1_legacy` branch, so pin a commit SHA in
your artefact description and say which branch you built.

---

## 7. Check yourself

**1. A reviewer says: "ROSMonitoring is non-invasive too — it just subscribes to topics. Your
non-invasiveness claim is not a contribution." Are they right?**

Partly, and the honest answer is stronger than a denial. A ROSMonitoring monitor configured with
`action: log` and no `publishers:`/`subscribers:` entry *is* a plain subscriber on the real topic
and changes nothing — the Caldas et al. ROS-RV survey classifies it as *outline* instrumentation
on exactly that basis. But its filtering/enforcement mode, which is the framework's headline
capability, requires interposing a proxy: the publisher must be redirected to `<topic>_mon` and
the monitor republishes to `<topic>`, which the generator arranges by editing the application's
launch files in place (`instrumentation.py`'s own docstring says "invasive instrumentation").
Service monitoring in 2.0 has no passive mode at all. So the correct claim is narrower and
survives contact: enforcement requires a rewrite there and does not here — plus the independent
point that ROSMonitoring monitors are typed against the robot's `.msg`/`.srv` packages while
yours are not.

**2. Could a `skill_monitor` Büchi automaton be dropped into ROSMonitoring as an oracle? What
would break?**

Yes, in principle: the oracle contract is a WebSocket server that receives one flat JSON event
and replies with a verdict, and it is deliberately formalism-agnostic. What would break is your
timing model. Your automaton takes exactly one step per external clock tick; a ROSMonitoring
oracle is called once per *observed ROS message*, at whatever rate publishers happen to publish,
with no tick and no notion of a step where nothing was observed. You would have to either drive
ticks yourself outside the protocol or abandon the one-step-per-tick discipline. The verdict
domains, by contrast, line up almost exactly (⊤/⊥/? with the ?⊤/?⊥ refinement).

**3. What does the 2020 paper mean by "portable", and what does it not mean?**

Portable **across ROS distributions**. The monitor is an ordinary rospy node rather than a
patched middleware, so it runs anywhere from Groovy through Noetic (the legacy README's stated
range), unlike ROSRV which swaps out the ROS Master. It does **not** mean portable across robots
or embodiments: moving to a new platform requires a new YAML naming that platform's topics and
types, new remaps, and a hand-rewritten field→predicate mapping in the oracle. There is nothing
resembling your per-embodiment adapter descriptor.

**4. Name the two limitations of the original framework that ROSMonitoring 2.0 was written to
fix, and the price 2.0 paid for one of them.**

(i) No service monitoring — the framework could only see topic messages. (ii) Message order was
subscriber-*receive* order, with no representation of publication order, which is unsound for
properties spanning several topics. 2.0 fixes ordering with per-interface buffers keyed on
`header.stamp`, released once every buffer is non-empty. The price: ordering "substantially
delays the process" in their own UAV measurements, and it introduces genuine deadlock risk —
they had to restructure the application under test, adding a deliberately unordered
`/status_change` topic and splitting topic publication from service invocation, and they present
that redundancy as "a general technique to prevent deadlocks."

**5. You want to cite a monitoring-overhead number from the 2020 paper. What can you safely
write?**

Very little from this summary, and that is the point. The verified qualitative claim is that
overhead was measured as *added message-delivery delay*, in a setup with 10 nodes and 10 topics
at 100/500/1000 Hz, deliberately using a property that is constant-time and always satisfied so
the figure isolates the monitor from the oracle — and that at 1000 msg/s monitors were
"practically transparent". Those numbers reached me through search-engine snippets of the
author preprint, not the PDF, which the egress proxy blocked. Fetch
`unige.iris.cineca.it/…/ROSMonitoring_ICRA2020.pdf` and read the table before any of it goes in
your paper. If you want a fully verified overhead figure today, use ROSMonitoring 2.0's UAV
experiment instead — ROS1 Noetic, 25/10/35 Hz, 10 runs, mean and standard deviation — where the
finding is that service monitoring alone is negligible but ordering is not.
