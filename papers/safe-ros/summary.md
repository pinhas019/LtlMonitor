# Safe-ROS: An Architecture for Autonomous Robots in Safety-Critical Domains

**Diana C. Benjumea** (Diana C. Benjumea Hernandez), **Marie Farrell**, **Louise A. Dennis** —
all University of Manchester, Manchester, UK.
arXiv:2511.14433v1, November 2025 (the exact submission day is **not verified** — arxiv.org
and alphaxiv.org were both unreachable from this session; the month follows from the `2511`
identifier). Published version: *Proceedings of the Seventh International Workshop on Formal
Methods for Autonomous Systems (FMAS 2025)*, eds. Luckcuck, Schwammberger & Xu,
**EPTCS 436, 2025, pp. 48–68**, doi:10.4204/EPTCS.436.6. CC-BY. Read from the arXiv v1 PDF.

Code: `https://github.com/dianabenjumea/Safe-ROS` (stated in the paper, p. 52 and p. 63; the
repository itself was **not opened** for this study guide, so nothing below is sourced from it).

Page numbers below are the printed EPTCS page numbers (48–68), which is what the running header
of the arXiv PDF carries. Quotations are exact. Anything the retrieved pages did not state is
marked **not verified** rather than inferred — in particular Figures 1, 2, 3 and 4 were read
only through their captions and the surrounding prose, never as images.

---

## 1. In one paragraph

Safe-ROS is an *architectural pattern*, not a tool: split a ROS robot into a **Safety-Related
Autonomous System (SRAS)** that does the actual job using whatever unverified, probabilistic
machinery the job needs (`move_base`, neural perception, feedback control), and a separate
**Safety System (SS)** made of **Safety Instrumented Functions (SIFs)** — a term lifted
deliberately from IEC 61508 / 61511 / 61513 process-industry functional safety — whose only job
is formally verifiable oversight of the first. The paper's contribution is to instantiate that
pattern end-to-end, once, on real hardware, and to carry a single safety requirement all the way
from structured natural language to a machine-checked proof: the requirement "the robot shall
maintain a safe distance from obstacles" is written in FRET, auto-translated to
`G (too_close -> F stopped)`, implemented as a **three-line GWENDOLEN BDI agent** running outside
ROS on the JVM, model-checked with AJPF, connected to the ROS graph through `java_rosbridge`, and
given actuator authority by a Python **orchestrator node** (`cmd_vel_interceptor`) whose core
logic is separately proved correct in Dafny. The whole stack is then validated in a Gazebo
nuclear-waste-store simulation and on an AgileX Scout Mini in a Manchester lab. The claim is
feasibility and traceability across the lifecycle — explicitly *not* system-level safety, which
the authors repeatedly say they have not established.

---

## 2. Key concepts

**SRAS — Safety-Related Autonomous System.** The operational subsystem. "uses autonomous control
technologies such as neural networks and feedback controllers for routine operation" (p. 50).
Here: a ROS **Noetic** (i.e. ROS 1) motion controller built on the standard navigation stack —
`move_base`, `amcl`, `pointcloud_to_laserscan`, `rf2o_laser_odometry` are all in the bibliography.
Assumed unverified and probabilistic, on purpose.

**SS — Safety System.** The oversight subsystem, "which provide[s] reversionary control and
ensure[s] safety-critical requirements while retaining some intelligence" (p. 50). In this
instantiation the SS contains exactly one SIF.

**SIF — Safety Instrumented Function.** Borrowed straight from functional safety: "a vital
component of safety systems in various industries, including nuclear, chemical processing and oil
and gas ... designed to prevent or mitigate hazardous events by taking specific actions when
certain conditions are met" (p. 49). The novelty is *implementing the SIF as a cognitive agent*
rather than as a relay or a hardware cut-off — and the authors concede the point: "The current SIF
could be implemented using a hardware cut-off, but further work aims to explore more complex
behaviour, such as returning to a door, which cannot be achieved with simple hardware guards"
(p. 62).

**Cognitive / BDI agent.** GWENDOLEN, from the MCAPL framework — a Belief–Desire–Intention
language chosen "primarily due to its strong support for formal verification" with model checking
"embedded within the framework" (p. 51). The motivation is stated as encoding "safety requirements
as a set of beliefs or rules of the system ... providing transparency in the system's logical
decision-making process" (p. 51).

**Percept.** The unit at the SS's input boundary. Raw ROS topics are *not* the agent's input; a
Java environment class converts them into logical literals (`too_close`) that are inserted into
the agent's belief base. This is the paper's abstraction boundary and it is named as a threat:
"Our abstraction of ROS topics into agent beliefs enables verification but raises questions about
sensor validity and translation correctness" (p. 63).

**FRET / FRETish.** The Formal Requirements Elicitation Tool. Requirements are written in a
constrained English template with slots (scope, condition, component, timing, response) and FRET
emits the LTL mechanically. Not an LLM, not free-form English.

**AJPF.** Agent Java PathFinder — extends JPF to model-check BDI programs by exploring the agent's
actual Java execution paths, "considering control flow and the agent's reasoning" (p. 51). Program
model checking, not model checking of an abstraction.

**Corroborative V&V.** The paper's own framing (citing Webster et al. [74]): several techniques of
different kinds aimed at the same claim — AJPF on the agent, Dafny on the orchestrator, simulation
and physical testing on the deployment.

**Monitor placement — the important one.** The SIF is *not* a ROS node. "the GWENDOLEN agent
implementing the SS runs outside ROS in a JAVA BDI framework (MCAPL), and the SRAS control system
uses Python and C++, providing software diversity and interface segregation" (p. 55). It reaches
the graph over a WebSocket via `java_rosbridge`, and is integrated using the ROS-A framework [16].

**Safety case / assurance argument.** There is **no GSN, no structured safety case, and no
assurance-argument diagram** in this paper. What exists is (a) a traceability thread — hazard
analysis → FRET requirement → LTL → agent → proof → test, offered as the answer to research
question Q3 — and (b) a section titled "Safety Argument" (p. 63) which is a statement of what a
safety argument *would* require and an admission that it is absent: "a complete safety argument
requires consideration of factors beyond formal verification. Stopping the robot does not always
guarantee a safe state, especially if it stops in a hazardous location."

---

## 3. Architecture, concretely

Two subsystems, one shared robot, one mediating node.

```
  LiDAR  --+--> [ROS: /scan]  -->  move_base --> /cmd_vel --+
           |                       (SRAS: Python/C++)       |
           |                                                v
           +--> java_rosbridge (WebSocket)          cmd_vel_interceptor
                      |                              (orchestrator, Python)
                      v                                     |
              Java environment class                        |
              (parses LaserScan, min range)                 |
                      |  addPercept(too_close)              |
                      v                                     |
              GWENDOLEN agent `agilex_agent`  --------------+
              (SS / SIF, on the JVM, outside ROS)           |
                  publishes /gwendolen_control  ------------+
                        (std_msgs/Bool)                     |
                                                            v
                                                    robot actuators
```

**The SIF itself is three lines** (Listing 2, p. 55):

```
GWENDOLEN
:name: agilex_agent
:Plans:
  +too_close : { True } <- stop_moving, +stopped;
```

**The environment class does the real sensing work** (Listing 1, p. 55). It opens a WebSocket
bridge to ROS, subscribes to `/scan` typed `sensor_msgs/LaserScan`, and in `handleLaserScanData`
extracts the minimum range; `if (minValue < 0.05) addPercept(new Literal("too_close"))`. On
`stop_moving` it publishes `true` on `/gwendolen_control` (`std_msgs/Bool`). Note where the safety
threshold lives: **a hardcoded `0.05` literal in Java**, not in the spec, not in a config file, not
in the FRET requirement (which states 5 cm in prose — the two agree, but nothing enforces that they
agree).

**The orchestrator node `cmd_vel_interceptor`** (§3.3, p. 56) is the enforcement point. It
"subscribes to both the `/gwendolen_control` topic and the standard `/cmd_vel` topic generated by
`move_base`. Under normal conditions, the `cmd_vel_interceptor` node transparently forwards
velocity commands from `move_base` to the robot's actuators. However, if a true message is received
on the `/gwendolen_control` topic, the node overrides all incoming velocity commands and instead
publishes a zero-velocity `Twist` message, stopping the robot. When the safety condition is cleared
(i.e., no new stop signals are received), normal velocity forwarding resumes."

**The requirement and its formalisation** (§3.4, p. 55 and p. 58):

- R1, prose: "When the robot detects that an obstacle is within 5cm of it, then it must stop
  immediately."
- FRETish: `(global) whenever too_close agilex_agent shall (eventually) satisfy stopped`
- LTL (auto-generated by FRET, future-time, infinite trace): **`G (too_close -> F stopped)`**
- AJPF property language (Listing 4, p. 58):
  `[] (B(agilex_agent, too_close) -> <> B(agilex_agent, stopped))`

The word "immediately" in R1 does not survive: "the model checker used in this work (AJPF) does not
support the LTL next operator, and we cannot represent explicit time dependencies. As a result, we
interpret the timing field using the default eventually semantics" (p. 58). The verified property is
untimed.

**Separation, as built vs. as intended.** The paper is unusually candid. "In a final deployment of
the Safe-ROS architecture, the SRAS and SS should be independent, diverse, and segregated. However,
given resource availability and aiming to present a proof of concept ... we integrate both systems
on the same hardware and share some ROS packages" (p. 55). What is shared: "the mobile platform,
LiDAR percepts, and computing resources". What is nevertheless maintained: language diversity,
JVM-vs-ROS process separation, and a bridge as the only interface. What is wanted: "different
computers or processors ... with redundant sensors and components, ensuring no integration between
them" (p. 55).

**Scope, self-declared.** "The framework focuses on enforcing safety rules at the application level
(e.g., maintaining safe distances, speed limits, or initiating emergency stops) rather than
verifying low-level sensor processing, ROS middleware communication, or overall system safety"
(p. 50). The middleware "remain[s] unverifiable" (p. 49). Docker and the OS are noted as not
certified (p. 61).

---

## 4. Evaluation

Four strands, corresponding to declared success criteria (formalise the requirement; implement the
SIF; verify it; integrate it into the operational system).

**AJPF model checking of the SIF.** A `VerificationEnv` extending
`VerificationofAutonomousSystemsEnvironment` replaces the ROS topics: "We abstract away the raw ROS
topics, in this case, the LIDAR sensor data, and instead represent the relevant information as
percepts or beliefs for the agent" (p. 58). The listing shown generates percepts with
`random_bool_generator.nextBoolean()`, adding a `stopped` predicate when true. Result: the property
`G(too_close -> F stopped)` is verified. **No state count, no exploration time, and no machine
specification is reported for the AJPF run** — not verified. Note also that Listing 3 is explicitly
a "code snippet" with elided lines, and the shown fragment generates `stopped`, not `too_close`;
**how `too_close` enters the verification environment is not shown in the text retrieved** — not
verified.

**Dafny proof of the orchestrator.** The Python node's core logic is re-modelled as a
`CmdVelInterceptor` class with a `stop_requested: bool`, a `stop_callback(msg: bool)`, and a
`cmd_vel_callback(msg: Twist) returns (out: Twist)` carrying
`ensures stop_requested ==> out == Twist(0,0,0)` and `ensures !stop_requested ==> out == msg`
(Listing 5, p. 59). **Three proof obligations** discharged automatically — constructor,
`stop_callback`, `cmd_vel_callback` — on **Dafny 3.4.4**, VSCode 1.103.1, Mac M2 Pro, macOS Sequoia
15.6 (p. 60). Establishes: "If a True `stop_request` is received, current and new velocity commands
must be replaced with a zero-velocity message."

**Gazebo simulation** (Fig. 5a, p. 60). A nuclear waste storage room model (Manchester's published
Gazebo nuclear assets [75]) with walls and storage elements. Mission: visit three inspection points,
return to start, avoid obstacles. Navigation by `move_base`. Finding, and it is the most interesting
empirical result in the paper: the safety system fired *often*. "These events occurred frequently,
which required adjusting `move_base` parameters to prevent path computation through unsafe regions.
Despite these adjustments, the safety system was triggered multiple times, demonstrating both its
effectiveness and its necessity when using probabilistic approaches" (p. 60). **No trigger counts,
no rates, no latencies are given** — not verified.

**Physical lab testing** (Fig. 5b, p. 60), AgileX Scout Mini at the Autonomy and Verification lab,
University of Manchester. Cones and barrels; obstacles deliberately displaced from their mapped
positions and also moved dynamically during operation to provoke `too_close`. "In all cases, the
robot stopped when detecting an obstacle within the safety threshold." **Number of trials not
reported** — not verified.

The paper's own summary of what the testing bought: "This test suite helped us to bridge the reality
gap between our static verification methods (AJPF and Dafny) and actual physical executions. These
tests address local runtime safety but do not demonstrate how system-level safety emerges from
SRAS–SS interactions" (p. 60).

---

## 5. Limitations

Mostly the authors' own, and they are stated plainly.

1. **One requirement.** "we evaluated Safe-ROS ... focusing on a single safety requirement" (p. 62).
   The SS contains exactly one SIF.
2. **No timing.** AJPF has no `next` operator; "immediately" became "eventually" (p. 58, restated
   p. 61). A stop that eventually happens satisfies the verified property.
3. **The proof is of a model, not of the code.** "The Orchestrator node (`cmd_vel_interceptor`) is
   implemented in Python, but for formal verification, we model its core logic in the Dafny
   programming language, abstracting away ROS-specific details like subscribers and publishers"
   (p. 59). Python and Dafny agreeing is an unproved assumption.
4. **The AJPF guarantee is about the agent's head, not the world.** "verification performed using
   AJPF ensures that the SIF behaves correctly according to its formalized internal logic; however,
   it does not account for perception errors, message delays, or actuator uncertainties. As a
   result, the safety guarantees apply primarily to the internal decision-making process of the SIF
   rather than the full, real-world operational system" (p. 63).
5. **Stopping ≠ safe.** "stopping the robot does not automatically guarantee a safe state,
   particularly if the robot stops near a hazardous location" (p. 60). Safe states, recovery and
   fault tolerance are all future work.
6. **No compositional / global guarantee.** "The architecture does not formally establish how
   system-level safety emerges from SRAS–SS interaction" (p. 63).
7. **Segregation not achieved.** Shared hardware, shared LiDAR, shared compute (p. 55).
8. **Percept translation unverified.** The Java environment class that turns `/scan` into
   `too_close` sits outside both proofs.
9. **No probabilistic reasoning.** "AJPF does not support probabilities" (p. 61); the architecture
   wraps probabilistic components rather than reasoning about them.
10. **Evaluation is a proof of concept.** "the current evaluation establishes only a proof of
    concept; future work will develop a robust evaluation strategy involving fault injection,
    statistically focused simulation, and experimental campaigns" (p. 63).
11. **Unverified platform.** OS and Docker are not FS-certified (p. 61); tool qualification (MCAPL,
    Dafny) with UK nuclear licensees/regulators is out of scope (p. 63).

---

## 6. For `skill_monitor`

### 6.1 Separation of monitor from system-under-monitoring — vs. adapter ⟂ spec

**What Safe-ROS separates, and how.** By *diversity and channel*, in the IEC 61508 tradition:
different language (GWENDOLEN/Java vs. Python/C++), different runtime (a JVM outside the ROS graph
entirely), a single narrow interface (a WebSocket bridge, plus one `std_msgs/Bool` topic and the
intercepted `/cmd_vel`). Aspirationally different processors and redundant sensors; **in the
prototype, none of that** — same platform, same LiDAR, same box (p. 55).

**What `adapter ⟂ spec` separates.** Something else entirely. It is an *information* separation
*inside the monitoring stack*: the monitor never reads an adapter descriptor, the evaluator never
reads a spec, and each learns of the other only through a latched topic (`architecture.md`, "The
invariant, stated because it is checkable"). Its purpose is embodiment portability, not redundancy.
`skill_monitor`'s monitor-vs-system separation is a different property again: the monitor's inputs
are a spec and an observation stream, and "neither names an embodiment."

**So they are not two points on one scale.** Safe-ROS separates *by redundancy* — the safety channel
is a second, differently-built thing. `skill_monitor` separates *by ignorance* — each component is
denied the artifact that would couple it. Neither subsumes the other, and both could be held at
once. Do not write the comparison as "stronger/weaker" without saying on which axis.

Where each is genuinely stronger:

- **Safe-ROS is stronger on input independence from the planner.** The SIF's only input is raw
  `/scan`. It never reads `move_base`'s state, mode, or status. That is exactly the property
  `architecture.md` admits `skill_monitor` does not currently have: the shipped schema reads
  `nav_state`, `nav_mode`, `nav_stuck`, `mission_finished`, `num_waypoints`, `current_target_idx` —
  the planner's own account of itself — and the doc's own verdict is "A monitor that must be told by
  the planner whether the planner is stuck is not independent of it." P12 fixes this and has not
  landed. **Until P12 lands, Safe-ROS has the better independence story and a reviewer can see it in
  one figure.** This is the single most useful thing to take from the paper.
- **Safe-ROS is stronger on implementation diversity.** A monitor written in the same language, in
  the same process family, against the same libraries as the thing it watches shares that thing's
  bugs. `skill_monitor`'s tier-1 monitor is Python next to Python. No claim of diversity is made and
  none should be.
- **`skill_monitor` is stronger on checkability.** Safe-ROS's separation is prose plus a deployment
  aspiration — "the architecture is designed so that the two systems could be fully independent"
  (p. 63), *could*. `adapter ⟂ spec` is asserted as a test: "the monitor package never reads
  `skill_monitor/adapters/`." A separation you can fail CI on is a different kind of object than a
  separation you intend.
- **`skill_monitor` is stronger on what the safety channel can express.** Safe-ROS's SIF is one plan
  over one percept produced by one hardcoded float. There is no spec artifact — the "specification"
  is a FRET sentence that was compiled once, by hand, into three lines of GWENDOLEN. Nothing at
  runtime holds the LTL. `skill_monitor` loads a spec, builds an automaton, and steps it.

**Positioning sentence you can use.** Safe-ROS separates the safety channel by *construction
diversity*, which is what functional-safety regulators ask for; `skill_monitor` separates it by
*artifact ignorance*, which is what makes a single monitor container portable across embodiments.
Cite Safe-ROS as the regulatory-lineage neighbour, and be honest that its planner-independence is
currently ahead of yours.

### 6.2 Enforcement — interception vs. out-publishing zero `Twist`

**Safe-ROS enforces by mediation, not by contention.** `cmd_vel_interceptor` sits *in* the datapath:
`move_base` → `/cmd_vel` → interceptor → actuators. Every command physically passes through a node
whose behaviour is a total function of `(msg, stop_requested)`, and that function is what Dafny
proves. There is no race, no last-writer-wins, no publication rate to tune.

**Does it assume a cooperative planner?** *Behaviourally, no* — `move_base` does not know the
interceptor exists and needs no cooperation from it. **But it assumes a cooperative graph.** The
actuator driver must be subscribed to the interceptor's *output*, not to `/cmd_vel`; and no other
node may publish onto the actuator topic. That is a launch-file/remapping assumption, it is
load-bearing for every safety claim in the paper, and it is **outside** the Dafny proof, which
"abstract[s] away ROS-specific details like subscribers and publishers" (p. 59). The paper never
states the remapping explicitly nor tests for a bypassing publisher.

**Honest scoring against out-publishing.**

| | Safe-ROS interception | `skill_monitor` out-publishing |
|---|---|---|
| what it requires of the planner | nothing behaviourally | nothing behaviourally |
| what it requires of the *graph* | actuator topic must be downstream of the interceptor; no other publisher | only that planner and supervisor share a topic |
| mechanism | mediation — commands pass through | contention — zero `Twist` at 10 Hz outnumbers the planner |
| worst case | interceptor dies → no motion at all (fail-safe, but total authority in one Python node) | planner publishes faster / a command lands last → robot moves between zeros |
| formal backing | Dafny, 3 obligations, on a Dafny re-model of the Python node | none stated |
| deployment cost | topic remapping in the launch/compose files | none |

**Verdict, unwelcome but correct: on enforcement guarantee, Safe-ROS is stronger, and this is a
competitor rather than an argument.** Out-publishing does not *stop* the planner's commands; it
outnumbers them. The doc's line that it "requires the planner to be *nothing* — not correct, not
cooperative, just present on the same bus" is true and worth keeping, but it describes the
*assumption*, not the *guarantee*. Interception makes an equally weak assumption about the planner
while giving a guarantee out-publishing cannot: between two zero commands, nothing else reaches the
wheels.

**Where you can push back, legitimately:**

1. **The proof is of a re-model.** Dafny verifies a `CmdVelInterceptor` class, not the Python node.
   The paper says so (p. 59). The gap between the two is unproved and unmeasured.
2. **The mediator is a single point of authority.** All motion depends on one unverified Python node
   staying alive and scheduled. Out-publishing degrades gracefully (fewer zeros land); interception
   has an on/off failure mode.
3. **Release semantics are underspecified.** "When the safety condition is cleared (i.e., no new
   stop signals are received), normal velocity forwarding resumes" (p. 56). Nothing in the retrieved
   text states a latch, a hysteresis, a debounce, or a timeout, and the shown GWENDOLEN plan adds
   `stopped` but never retracts `too_close`. Compare `skill_monitor`'s safety ladder and arm/reset
   states, which are explicit. **Whether Safe-ROS has an explicit release rule is not verified** —
   the paper does not give one.
4. **No timing bound anywhere.** The property is `F stopped`, not a bounded response. The robot's
   stopping distance is not related to anything proved.

**Concrete design option for `skill_monitor`.** You do not have to choose. The supervisor could be
given an *optional* mediating mode (subscribe `/cmd_vel_planner`, publish `/cmd_vel`) alongside the
current out-publishing mode, with out-publishing kept as the zero-config default. Then the paper's
strength becomes a configuration you support rather than a gap you concede, and the ablation
"mediated vs. contending" is a real experiment with a real number.

### 6.3 Determinism and replay

**Not addressed. Anywhere.** The retrieved text contains no clock, no tick, no step semantics, no
message-ordering discipline, no rosbag, no re-execution, and no claim that a verdict is a function
of the data. "Reproducibility" appears twice (p. 52, p. 63) and both times means the open-source
artifact, not verdict reproducibility.

Three things sharpen this into a claim you can make:

- **The one place nondeterminism *is* discussed, it is design-time and deliberate.** The AJPF
  environment feeds the agent percepts from `random_bool_generator.nextBoolean()` (Listing 3, p. 58)
  so that model checking explores all branches. That is exhaustive exploration of a nondeterministic
  model — the opposite of a reproducible runtime verdict.
- **The architecture has no temporal semantics to be deterministic about.** "AJPF ... does not
  support the LTL next operator, and we cannot represent explicit time dependencies" (p. 58). There
  is no notion of a step, so there is nothing for a tick to index.
- **The SS is reactive and rate-free.** The Java environment reacts to `/scan` callbacks; the
  interceptor reacts to `/cmd_vel` callbacks; no rate, period or synchronisation is stated for
  either. `skill_monitor`'s "exactly one automaton step per tick, verdict is a function of the data"
  has no counterpart here.

**This is the cleanest gap in the paper and the safest thing to claim.** Say it precisely and
narrowly: *Safe-ROS's guarantee is a design-time proof about an agent's internal logic; it makes no
claim that a runtime intervention is reproducible from a recording, and provides no mechanism by
which it could be.* Do not overclaim it as a criticism — reproducible verdicts were not their goal —
but it is a genuine axis on which you are alone.

### 6.4 Tool-table row

| tool | spec synthesis from NL | schema grounding | embodiment portability | deterministic replay |
|---|---|---|---|---|
| **Safe-ROS** (`saferos2025`) | **partial** — FRET/FRETish structured NL → LTL, mechanically. No LLM, no free-form English. One requirement demonstrated. | **no** | **claimed, not demonstrated** | **no** |

Cell-by-cell evidence:

- **spec synthesis from NL — partial, and be careful how you word it.** FRET is a
  *constrained-template* translator, not natural language in your sense: the author writes
  `(global) whenever too_close agilex_agent shall (eventually) satisfy stopped` and FRET emits
  `G (too_close -> F stopped)` (p. 58). The English-to-slots step is human. In a table whose other
  rows are LLM translators, mark this "structured NL (FRET), no LLM" rather than plain "yes" — the
  difference is exactly your paper's contribution area.
- **schema grounding — no, and this is the weakest cell.** The atom `too_close` is defined by
  `if (minValue < 0.05)` inside a Java class (Listing 1, p. 55). There is no declared sensor
  vocabulary, no validation of the formula's atoms against anything, and no artifact linking the
  FRET requirement's "5cm" to the code's `0.05`. Nothing would catch a spec naming an atom the
  environment cannot produce. Contrast `spec_contract.validate()`.
- **embodiment portability — claimed as a pattern, unsupported by evidence.** The claim: "the
  underlying concept ... can be extended to other domains (e.g., aerospace, mining, infrastructure)
  where autonomy is implemented on middleware such as ROS and where external intervention channels
  (e.g., motion overrides, mode switching) exist ... a reusable pattern for modular safety
  supervision architectures" (p. 63). The evidence: one robot (AgileX Scout Mini), one simulator
  (Gazebo) simulating that same robot, one skill. There is no adapter layer, no schema, no
  descriptor; topic names (`/scan`, `/gwendolen_control`) and message types
  (`sensor_msgs/LaserScan`, `std_msgs/Bool`) are hardcoded in the Java environment. Mark the cell
  **claimed / not demonstrated** and footnote it — "no" would misrepresent them, "yes" would be
  unsupported.
- **deterministic replay — no.** See §6.3. Not "no evidence"; the concept does not appear.

**Also worth a footnote in that table's caption:** Safe-ROS is the only entry whose enforcement is
*proved* (Dafny, 3 obligations) rather than merely implemented. If your table has an enforcement
column, Safe-ROS wins it and you should say so rather than let a reviewer find it.

### 6.5 Three smaller things worth stealing

1. **The IEC vocabulary is free credibility.** "Safety Instrumented Function" carries IEC
   61508/61511/61513 lineage and lands with reviewers from safety engineering. `skill_monitor`
   already *has* a SIF — the supervisor — and calling it one costs nothing.
2. **The `move_base` finding is a citable motivation for your whole paper.** A tuned,
   production-grade ROS planner tripped the safety layer *frequently* in simulation, and retuning
   did not eliminate it (p. 60). That is third-party evidence that unverified planners need external
   oversight — better than asserting it yourself.
3. **The empty-safety-case admission is a gap you could occupy.** They name what a safety case needs
   (safe states, recovery, fault tolerance, compositional guarantees) and supply none of it. If
   `skill_monitor`'s safety ladder defines states and recovery explicitly, that is a contribution
   they have flagged as missing in their own field.

---

## 7. Check yourself

**Q1. Safe-ROS's SIF and `skill_monitor`'s tier-1 monitor both watch a navigation stack. Name the one
input-independence property Safe-ROS has that `skill_monitor` currently does not, and say what would
fix it.**

The SIF's only input is raw `/scan`; it never reads the planner's own account of itself. The
`skill_monitor` schema currently ingests `nav_state`, `nav_mode`, `nav_stuck`, `mission_finished`,
`num_waypoints` and `current_target_idx` — planner status topics — which `architecture.md` itself
identifies as a fault ("A monitor that must be told by the planner whether the planner is stuck is
not independent of it"). P12, the planner-independent schema, forbids every planner topic by test
and is the fix; it has not landed.

**Q2. Does Safe-ROS assume a cooperative planner?**

Not behaviourally — `move_base` is treated as unverified and uncooperative, which is the whole
premise. But it assumes a *cooperative graph*: the actuator driver must be wired downstream of
`cmd_vel_interceptor` and nothing else may publish to the actuator topic. That assumption is never
stated in the paper, never tested, and lies outside the Dafny proof, which abstracts away subscribers
and publishers.

**Q3. What exactly did Dafny prove, and what did it not?**

It discharged three proof obligations over a `CmdVelInterceptor` Dafny class — constructor,
`stop_callback`, `cmd_vel_callback` — establishing that `stop_requested` implies the output is
`Twist(0,0,0)` and that otherwise the input is forwarded unchanged. It did **not** prove anything
about the Python node that actually runs: the paper states the node is Python and the Dafny is a
model of its core logic with ROS specifics abstracted away. It also proved nothing about timing,
message loss, or the release-from-stop condition.

**Q4. A reviewer says "Safe-ROS already gives verified enforcement; what does deterministic replay
add?" Answer in two sentences.**

Safe-ROS's guarantee is design-time and about the SIF's internal logic — the paper states the
guarantees "apply primarily to the internal decision-making process of the SIF rather than the full,
real-world operational system", and it offers no mechanism to reconstruct why a particular runtime
intervention happened. Deterministic replay makes the *runtime verdict* an auditable function of a
recorded observation stream, which is what an incident investigation and a regulator ask for after a
deployment, and which no amount of pre-deployment model checking supplies.

**Q5. Why did "immediately" in requirement R1 not survive into the verified property, and why does
that matter for a stopping-distance argument?**

AJPF does not support the LTL `next` operator and cannot express explicit time dependencies, so
FRET's timing field was taken with its default *eventually* semantics, yielding
`G (too_close -> F stopped)`. That property is satisfied by a robot that stops at any point after
detecting the obstacle, including long after it has closed the 5 cm gap — so the verification
establishes nothing about whether the robot stops *in time*, and the 5 cm threshold is not connected
by any proof to the robot's actual braking distance.
