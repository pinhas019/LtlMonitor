"""Unified sensor evaluator for the LTL monitor -- agnostic to which environment it's
running against. Replaces llm_client.py (Isaac-Lab-sim/Nav2-specific) and
g1_real_client.py (real-robot-specific): all environment-specific sensor wiring now
lives in a SensorAdapter (sensor_adapter.py), selected with --adapter. Everything else
here -- the /ltl/required_aps -> /ltl/evaluations -> /ltl/state_description protocol,
rule-eval-first/LLM-fallback AP evaluation, the console print block -- is identical
regardless of which adapter is loaded.

Usage:
    python3 generic_client.py --adapter real_g1
    python3 generic_client.py --adapter mujoco
    python3 generic_client.py --adapter isaac_lab
"""

import json
import importlib
import inspect
import re
import sys
import time
import urllib.request
import argparse
import queue
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

import skill_monitor.core.spec_contract as spec_contract
from skill_monitor.core import adapter_spec, api
from std_msgs.msg import String

from skill_monitor.backend.adapters.base import SensorAdapter

#: The pre-migration adapter topic. P5 and P7 still read it, so it stays until
#: they move; `api.ADAPTER` is the contract topic and carries the same document.
_LEGACY_ADAPTER = "/ltl/adapter"

#: The pre-migration observation topic: a flat dict of AP booleans with no tick index.
#: `api.OBSERVATION` is the contract topic and now carries every tick too; this one
#: stays until `monitor_node._LEGACY_EVALUATIONS` stops being read. Named rather than
#: written out at the publisher so the two spellings cannot drift.
_LEGACY_EVALUATIONS = "/ltl/evaluations"

#: How many ticks of LLM backlog to hold before shedding. See `query_queue`.
_QUEUE_TICKS = 8

#: Seconds between free-running emissions when NO clock is publishing api.TICK.
#: The fallback goes dormant the moment a real pulse arrives -- two things driving
#: one trace is the bug docs/clocking.md exists to prevent -- but without it an
#: evaluator on a graph with no clock (a dev host, `--mock`) would simply go silent.
_FREE_RUN_S = 1.0

ADAPTERS: dict[str, str] = {
    # name -> "module:ClassName", imported lazily in _load_adapter so choosing one
    # adapter doesn't require every adapter's dependencies to be importable.
    # Only for embodiments whose plumbing genuinely needs code; the normal case is a
    # JSON descriptor in skill_monitor/adapters/, which needs no entry here.
    "real_g1_py": "skill_monitor.backend.adapters.real_g1:RealG1Adapter",
    "mujoco_py": "skill_monitor.backend.adapters.mujoco:MujocoAdapter",
    "isaac_lab_py": "skill_monitor.backend.adapters.isaac_lab:IsaacLabAdapter",
}


def adapter_choices() -> list[str]:
    return sorted(set(adapter_spec.available()) | set(ADAPTERS))


def _jsonable(v):
    if isinstance(v, (str, bool, int, float)) or v is None:
        return v
    return float(v) if hasattr(v, "__float__") else str(v)


def _load_adapter(name: str, **kwargs) -> SensorAdapter:
    """A JSON descriptor by preference, a Python class only where one exists."""
    if name in adapter_spec.available():
        from skill_monitor.backend.adapters.declarative import DeclarativeAdapter
        cls, kwargs = DeclarativeAdapter, {"descriptor": name, **kwargs}
    elif name in ADAPTERS:
        module_name, class_name = ADAPTERS[name].split(":")
        cls = getattr(importlib.import_module(module_name), class_name)
    else:
        raise SystemExit(f"Unknown --adapter '{name}'. Choices: {adapter_choices()}")
    # Only forward tuning knobs the chosen adapter actually accepts, so a knob that
    # is meaningful for one environment does not break construction of the others.
    accepted = inspect.signature(cls).parameters
    return cls(**{k: v for k, v in kwargs.items() if k in accepted})


class GenericClientNode(Node):
    def __init__(self, adapter: SensorAdapter, api_url: str, model: str):
        super().__init__("ltl_generic_client")
        self.adapter = adapter
        self.api_url = api_url
        self.model = model

        self.required_aps: list[str] = []
        self.state_desc: dict = {}
        self.idle = True  # start idle until monitor sends APs

        # Buffer / queue for asynchronous LLM queries -- kept for parity even when a
        # spec is fully rule-based (formulas_g1.json is), so llm_aps is simply empty.
        #
        # BOUNDED. Unbounded, a worker blocked on an LLM that has stopped answering
        # grows this without limit on a robot, and every queued snapshot pins the
        # sensor_eval dict it captured. The bound is in ticks because that is what a
        # backlog is measured in: past this many, the answers are describing a robot
        # that has already moved on and dropping them is the correct outcome, not a
        # degradation. A drop costs one observation, which shows up as a gap in `seq`
        # downstream rather than as silence.
        self.query_queue = queue.Queue(maxsize=_QUEUE_TICKS)
        #: Snapshots shed because the worker could not keep up. Logged, never silent.
        self.snapshots_dropped = 0
        self.worker_thread = threading.Thread(target=self._worker_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()

        # LTL subscriptions/publisher -- identical regardless of adapter.
        self.create_subscription(String, "/ltl/required_aps", self.aps_callback, 10)
        self.create_subscription(String, "/ltl/state_description", self.desc_callback, 10)
        self.eval_pub = self.create_publisher(String, _LEGACY_EVALUATIONS, 10)

        # The clock's pulse, and the observation it closes. Ingestion is event-driven;
        # emission is tick-driven -- a subscription callback only hands its payload to
        # SensorState.update(), and THIS is what closes the window and publishes.
        self.create_subscription(String, api.TICK, self.tick_callback, 10)
        self.obs_pub = self.create_publisher(String, api.OBSERVATION, 10)
        #: The tick being described. seq 0 means nothing has closed yet, so the first
        #: real pulse is seq 1 -- see core/clock.py.
        self._tick_seq = 0
        self._tick_t = 0.0
        #: False until a pulse arrives on api.TICK. While false the free-running timer
        #: drives emission and the observation says `clock: "internal"`, which is the
        #: wire admitting that its tick index is this process's own count and not a
        #: clock's. It never goes back to true.
        self._clock_seen = False

        # What this robot can observe, announced once and latched. The monitor uses it
        # to reject a spec written over fields this embodiment does not have; the GUI
        # uses it to show the schema. Neither has to import the adapter to get it.
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE,
                             history=HistoryPolicy.KEEP_LAST)
        # Both wires, like every other topic mid-migration. `docs/api.md` names P3 the
        # producer of api.ADAPTER, and until this file's own migration lands it was the
        # one payload with a subscriber on the new wire and nobody publishing it: the
        # monitor listens on both, the gateway serves it as a latched GET, and the
        # console keys its raw-echo source picker on it -- so a console against a real
        # robot could not name a single source to echo. The legacy topic stays until P5
        # and P7 stop reading it.
        # Through the builder, not `json.dumps` of the raw dict. `AdapterSpec.manifest`
        # says in as many words that it returns "the keyword arguments
        # `core.api.build_adapter` takes ... so P3 publishes it with
        # `api.build_adapter(**spec.manifest(), ...)` and the shape cannot drift from
        # the wire contract" -- and P3 did not, so what went out had no
        # `schema_version` and failed `api.validate_adapter`. It was never noticed
        # because nothing validates on receipt.
        #
        # `tick_hz` is defaulted rather than required: a hand-written adapter's
        # `base.manifest()` has no topic map and no rate to report. The declarative
        # descriptors all carry their own, which wins.
        described = {"tick_hz": 1.0, **self.adapter.manifest()}
        manifest = json.dumps(api.build_adapter(**described))
        self.adapter_pub = self.create_publisher(String, api.ADAPTER, latched)
        self.adapter_pub.publish(String(data=manifest))
        self.legacy_adapter_pub = self.create_publisher(String, _LEGACY_ADAPTER, latched)
        self.legacy_adapter_pub.publish(String(data=manifest))

        # Raw echo: opt-in, one source at a time, off until a console asks. The request
        # topic is the only thing that can turn it on, and `{"source_id": null}` is the
        # only thing that has to turn it off -- nothing here starts echoing on its own.
        self.raw_echo_pub = self.create_publisher(String, api.RAW_ECHO, 10)
        self.create_subscription(
            String, api.RAW_ECHO_REQUEST, self.raw_echo_request_callback, 10)
        #: Echoes published since this process started. NOT the clock's `seq`: this node
        #: does not consume api.TICK yet (P3's tick migration is what gives it one), so
        #: the envelope carries the only sequence it honestly has. `step` is null for
        #: the same reason -- the evaluator tracks no episode.
        self._raw_echo_seq = 0

        # Everything environment-specific lives behind this one call.
        self.adapter.register_subscriptions(self)

        self.timer = self.create_timer(_FREE_RUN_S, self._free_run)

        self.get_logger().info(
            f"Generic client started (adapter={type(adapter).__name__}, "
            f"model={self.model} @ {self.api_url})"
        )

    def _drain_queue(self) -> None:
        drained = 0
        try:
            while True:
                self.query_queue.get_nowait()
                self.query_queue.task_done()
                drained += 1
        except queue.Empty:
            pass
        if drained:
            self.get_logger().info(f"Drained {drained} stale evaluation(s) from queue.")

    def aps_callback(self, msg: String):
        try:
            new_aps = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse required APs: {e}")
            return

        was_idle = self.idle
        self.idle = not new_aps

        if not was_idle and self.idle:
            self._drain_queue()
            self.get_logger().info(
                "Monitor entered IDLE state — evaluation halted. "
                "Waiting for next skill execution."
            )
        elif was_idle and not self.idle:
            self._drain_queue()
            self.get_logger().info(f"Monitor resumed — starting evaluation for APs: {new_aps}")

        self.required_aps = new_aps

    def desc_callback(self, msg: String):
        try:
            data = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse state description: {e}")
            return

        if data.get("state") == "halt":
            self.get_logger().info(
                f"Monitor halted ({data.get('reason','')}) — shutting down evaluator."
            )
            self._drain_queue()
            rclpy.shutdown()
            return

        self.state_desc = data

    # ------------------------------------------------------------------ raw echo

    def raw_echo_request_callback(self, msg: String):
        """Select the one source to echo, or stop echoing.

        Validated with the same `core.api` validator every other consumer uses, so a
        malformed request is reported here rather than turning into an echo of nothing
        that an operator would read as a dead camera.
        """
        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse raw echo request: {e}")
            return
        problems = api.validate_raw_echo_request(payload)
        if problems:
            self.get_logger().error(f"Refusing raw echo request: {'; '.join(problems)}")
            return

        source_id = payload.get("source_id")
        if not self.adapter.set_raw_echo(source_id):
            self.get_logger().error(
                f"Cannot echo source {source_id!r}: this adapter has no such source. "
                f"The echo is unchanged."
            )
            return
        self.get_logger().info(
            "Raw echo stopped." if source_id is None
            else f"Raw echo now following source {source_id!r}."
        )

    def _publish_raw_echo(self):
        """One summary per tick for the selected source, or nothing at all.

        Above the idle early-return in `evaluate_and_publish` on purpose: an operator
        pointing the console at a camera before arming a skill is the normal case, and
        an echo that only works while a spec is loaded would be useless exactly then.
        """
        taken = self.adapter.take_raw_echo()
        if taken is None:
            return
        source_id, summary = taken
        payload = api.build_raw_echo(
            seq=self._raw_echo_seq, t=time.time(), step=None,
            source_id=source_id, summary=summary,
        )
        self._raw_echo_seq += 1
        problems = api.validate_raw_echo(payload)
        if problems:
            # A summary this node built and the contract refuses is this node's bug;
            # say so and publish nothing rather than putting it on the wire.
            self.get_logger().error(
                f"Not publishing raw echo for {source_id!r}: {'; '.join(problems)}")
            return
        self.raw_echo_pub.publish(String(data=json.dumps(payload)))

    def _query_llm(self, prompt: str) -> dict:
        is_openai = "/v1" in self.api_url or "openai" in self.api_url
        if is_openai:
            endpoint = self.api_url if self.api_url.endswith("/chat/completions") else f"{self.api_url.rstrip('/')}/chat/completions"
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
        else:
            endpoint = f"{self.api_url.rstrip('/')}/api/generate"
            data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        req.add_header("Authorization", "Bearer dummy-key")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
                if is_openai:
                    content = result["choices"][0]["message"]["content"].strip()
                    if content.startswith("```"):
                        first_nl = content.find("\n")
                        if first_nl != -1:
                            content = content[first_nl:].strip()
                        if content.endswith("```"):
                            content = content[:-3].strip()
                    return json.loads(content)
                else:
                    return json.loads(result["response"])
        except Exception as e:
            self.get_logger().error(f"LLM query failed: {e}")
            if hasattr(e, "read"):
                try:
                    self.get_logger().error(f"Response body: {e.read().decode('utf-8')}")
                except Exception:
                    pass
            return {}

    def tick_callback(self, msg: String) -> None:
        """The clock's pulse. THIS drives emission; the timer is only a fallback."""
        try:
            payload = json.loads(msg.data)
        except Exception:                                        # noqa: BLE001
            self.get_logger().error("tick is not JSON; ignoring")
            return
        if problems := api.validate_tick(payload):
            self.get_logger().error(f"invalid tick, ignoring: {'; '.join(problems)}")
            return

        if not self._clock_seen:
            self._clock_seen = True
            self.get_logger().info(
                f"{api.TICK} is live; the free-running fallback stops emitting.")
        self._tick_seq = payload["seq"]
        self._tick_t = payload["t"]
        self.evaluate_and_publish(self._tick_t)

    def _free_run(self):
        """Emit without a clock, and only until one appears.

        A dev host or `--mock` has no clock node, and an evaluator that published
        nothing there would look broken. Once `api.TICK` arrives this goes quiet
        for good: two producers on one trace is precisely the failure
        docs/clocking.md is written to prevent.
        """
        if self._clock_seen:
            return
        self._tick_seq += 1
        self._tick_t = time.time()
        self.evaluate_and_publish(self._tick_t)

    def evaluate_and_publish(self, t: float | None = None):
        # Before the idle check: the echo is an operator looking at a sensor, which is
        # not conditional on a spec being armed.
        #
        # Guarded because it is the one thing on this timer that touches a raw message:
        # a camera publishing something the summariser did not anticipate must cost a
        # logged error and one missing frame, never the evaluation of the tick.
        try:
            self._publish_raw_echo()
        except Exception as e:                                   # noqa: BLE001
            self.get_logger().error(f"Raw echo failed for this tick: {e!r}")

        # ABOVE the idle return, and that is the whole point of it being here.
        #
        # tick() is the sole writer of the held sensor values, so if only the
        # publishing path closed the window, an idle evaluator would never close one:
        # the window would grow across the entire idle stretch and the first armed
        # tick would fold minutes of samples into one observation. An obstacle the
        # robot walked past two minutes ago would fire collision_risk on the resume
        # tick. Close on every pulse; publish only when armed.
        try:
            self.adapter.tick(t)
        except Exception as e:                                   # noqa: BLE001
            # SensorState.tick() already rolled the whole tick back, so the previous
            # observation is intact. One poisoned window costs one tick, not the run.
            self.get_logger().error(f"tick failed, holding last observation: {e!r}")

        if self.idle or not self.required_aps:
            return

        snapshot = {
            "required_aps": list(self.required_aps),
            "state_desc": dict(self.state_desc),
            "sensor_eval": self.adapter.get_sensor_eval(),
            "debug": self.adapter.describe(),
            # Sampled here, WITH the sensor_eval it describes -- not in the worker
            # thread, which runs later and would report freshness at publish time
            # rather than at observation time.
            "confidence": self.adapter.confidence(),
            "stale": list(self.adapter.stale_sources()),
            # Same reason: the tick index and the health of the sources that produced
            # this observation belong to the moment it was taken, not to whenever the
            # worker gets round to answering.
            "seq": self._tick_seq,
            "t": self._tick_t,
            "clock": "external" if self._clock_seen else "internal",
            "data_health": self.adapter.data_health(),
        }
        try:
            self.query_queue.put_nowait(snapshot)
        except queue.Full:
            self.snapshots_dropped += 1
            self.get_logger().warn(
                f"LLM backlog full at {_QUEUE_TICKS} ticks; dropped the observation "
                f"for tick {self._tick_seq} ({self.snapshots_dropped} so far). The "
                f"gap is visible as a jump in seq downstream.")
            return
        phase = self.state_desc.get("phase") or "—"
        self.get_logger().info(
            f"→ queued | phase={phase} | aps={len(self.required_aps)} | depth={self.query_queue.qsize()}"
        )

    def _worker_loop(self):
        while rclpy.ok():
            try:
                task = self.query_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_evaluation(task)
            except Exception as e:
                self.get_logger().error(f"Error in processing evaluation: {e}")
            finally:
                self.query_queue.task_done()

    # ------------------------------------------------------------------
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
    _DIM = "\033[2m"
    _CYAN = "\033[36m"
    _GREEN = "\033[32m"
    _RED = "\033[31m"

    # Shared with spec_contract (and therefore with the contract test and the
    # generator), so the rule the validator checks is byte-for-byte the rule this
    # evaluates. Previously a private copy here silently truncated decimals.
    _TRUE_WHEN_RE = spec_contract.TRUE_WHEN_RE

    def _rule_eval(self, desc: str, sensor_eval: dict):
        m = self._TRUE_WHEN_RE.search(desc)
        if not m:
            return None
        rule = m.group(1).strip().rstrip(".")
        try:
            return bool(eval(rule, {"__builtins__": {}}, sensor_eval))
        except Exception:
            return None

    def _process_evaluation(self, task):
        required_aps = task["required_aps"]
        state_desc = task["state_desc"]
        sensor_eval = task["sensor_eval"]
        debug = task["debug"]

        ap_descriptions = state_desc.get("ap_descriptions", {})
        terminal_success = state_desc.get("terminal_success", {})
        terminal_failure = state_desc.get("terminal_failure", {})
        phase_info = state_desc.get("phase_info", {})

        skill = state_desc.get("skill_name", "?")
        phase = state_desc.get("phase") or "Idle"
        B, D, R, C = self._BOLD, self._DIM, self._RESET, self._CYAN

        violations = phase_info.get("violation_count", 0)
        vlimit = phase_info.get("violation_limit", 3)
        viol_str = f"  {B}\033[33m⚠ {violations}/{vlimit} violations{R}" if violations > 0 else ""

        print(f"  {B}┌── Eval  [{C}{skill}{R}{B}]  phase: {C}{phase}{R}{B}  {'─' * 22}{R}")
        debug_str = "  ".join(f"{k}={v}" for k, v in debug.items())
        if debug_str:
            print(f"  │ {D}{debug_str}{R}")
        if phase_info:
            print(f"  │ {'─' * 52}")
            invariant = phase_info.get("invariant", "")
            if invariant:
                inv_cat = phase_info.get("invariant_fault_category", "INVARIANT")
                print(f"  │ {B}\033[31mInvariant:{R}  {invariant}  {D}[{inv_cat}]{R}")
            print(f"  │ {D}Progress :{R}  {phase_info.get('progress_condition','—')}{viol_str}")
            print(f"  │ {D}Exit  →  :{R}  {phase_info.get('next_phase','?')}  when: {phase_info.get('exit_condition','—')}")
            timing = phase_info.get("timing_bounds", {})
            step_count = phase_info.get("step_count", 0)
            max_steps = timing.get("max_steps")
            min_steps = timing.get("min_steps")
            if max_steps is not None:
                pct = int(100 * step_count / max_steps) if max_steps else 0
                bar_filled = pct // 5
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                print(f"  │ {D}Timing   :{R}  step {step_count}/{max_steps}  [{bar}] {pct}%"
                      + (f"  {D}(min {min_steps}){R}" if min_steps else ""))

        rule_evals: dict[str, bool] = {}
        llm_aps: list[str] = []

        for ap in required_aps:
            desc = ap_descriptions.get(ap, "")
            result = self._rule_eval(desc, sensor_eval)
            if result is not None:
                rule_evals[ap] = result
            else:
                llm_aps.append(ap)

        llm_evals: dict[str, bool] = {}
        if llm_aps:
            terminal_section = ""
            if terminal_success.get("description") or terminal_failure.get("description"):
                terminal_section = (
                    f"\nTerminal conditions:\n"
                    f"  SUCCESS when: {terminal_success.get('description','N/A')}\n"
                    f"  FAILURE when: {terminal_failure.get('description','N/A')}\n"
                )
            ap_lines = "\n".join(
                f'  "{ap}": {ap_descriptions.get(ap,"No description.")}' for ap in llm_aps
            )
            sensor_lines = "\n".join(f"  {k} = {v}" for k, v in sensor_eval.items())
            prompt = f"""You are evaluating atomic propositions for a robot skill monitor.

Skill: {skill} — {state_desc.get("description","")}
Phase: {phase}
{terminal_section}
Current sensor readings:
{sensor_lines}

Evaluate each proposition to true or false using the sensor values above.

{ap_lines}

Reply with ONLY a JSON object. No markdown, no explanation.
"""
            raw = self._query_llm(prompt)
            llm_evals = {ap: bool(raw.get(ap, False)) for ap in llm_aps} if raw else {}

        # What was actually decided, before the legacy wire's defaulting below. An AP
        # is in here only if a rule read it or a model answered it.
        evaluated = {**rule_evals, **llm_evals}

        final_evals = dict(evaluated)
        for ap in required_aps:
            # The legacy wire has no way to say UNKNOWN -- it is a flat dict of
            # booleans -- so an AP nothing could evaluate has always gone out as
            # False. That is why `api.OBSERVATION` is published from `evaluated`
            # instead: on that wire an undecided AP names itself in `unknown_aps`,
            # because "no rule matched and the model did not answer" and "there is no
            # obstacle" must not be the same message. Left as-is here; changing the
            # legacy semantics is P10's, not this migration's.
            final_evals.setdefault(ap, False)

        print(f"  │ {'─' * 52}")
        G, RE = self._GREEN, self._RED

        def _ap_colored(ap):
            color = G if final_evals.get(ap) else RE
            return f"{color}{ap}{R}"

        rule_true = [ap for ap in required_aps if ap in rule_evals and rule_evals[ap]]
        rule_false = [ap for ap in required_aps if ap in rule_evals and not rule_evals[ap]]
        if rule_evals:
            print(f"  │ {B}⚡ Rule-based (instant){R}")
            print(f"  │   {D}TRUE :{R}  {'  '.join(_ap_colored(a) for a in rule_true)  or '—'}")
            print(f"  │   {D}FALSE:{R}  {'  '.join(_ap_colored(a) for a in rule_false) or '—'}")

        if llm_aps:
            llm_true = [ap for ap in llm_aps if final_evals.get(ap)]
            llm_false = [ap for ap in llm_aps if not final_evals.get(ap)]
            print(f"  │ {B}🤖 LLM-evaluated (queried){R}")
            print(f"  │   {D}TRUE :{R}  {'  '.join(_ap_colored(a) for a in llm_true)  or '—'}")
            print(f"  │   {D}FALSE:{R}  {'  '.join(_ap_colored(a) for a in llm_false) or '—'}")

        print(f"  {B}└{'─' * 50}{R}")
        print()

        # Reserved keys travel beside the AP booleans (same convention as __reset__/
        # __done__). Guard expressions never reference a dunder name, so this is
        # inert for evaluation; main.py reads it for the risk block.
        payload = dict(final_evals)
        payload["__confidence__"] = task.get("confidence", 1.0)
        # The observation the APs were derived from, so the monitor can forward it to
        # operators. JSON-safe: an adapter may hand back numpy scalars.
        payload["__sensors__"] = {k: _jsonable(v) for k, v in sensor_eval.items()}
        stale = task.get("stale") or []
        if stale:
            payload["__stale__"] = stale
            self.get_logger().warn(
                f"stale sensor source(s): {', '.join(stale)} — confidence "
                f"{payload['__confidence__']:.2f}; APs derived from them are not trustworthy"
            )

        msg = String()
        msg.data = json.dumps(payload)
        self.eval_pub.publish(msg)

        self._publish_observation(task, sensor_eval, evaluated)

    def _publish_observation(self, task, sensor_eval, evaluated) -> None:
        """The same tick as the legacy dict above, in the envelope that has a `seq`.

        Both wires carry every tick during the migration. `monitor_node` prefers this
        one the moment it first arrives and stops stepping the automaton on the legacy
        copy, so publishing both is additive rather than a double step -- and dropping
        back to one is a one-line revert if this goes wrong on the robot.

        The envelope is what makes the episode recordable at all: `core/recording.py`
        replays `api.OBSERVATION`, and the flat dict beside it carries no tick index,
        so a recording of it could not be replayed against a clock.
        """
        # Booleans only, and an AP that produced no value names itself instead.
        # `evaluated` is deliberately the PRE-defaulting dict: a required AP that no
        # rule matched and no model answered is absent from it, and the whole reason
        # this wire has an `unknown_aps` field is so that case does not have to be
        # spelled False. On a safety AP -- collision_risk is one -- False is not a
        # neutral default, it is "the way is clear".
        ap_values, unknown = {}, []
        for ap in task["required_aps"]:
            value = evaluated.get(ap)
            if isinstance(value, bool):
                ap_values[ap] = value
            else:
                unknown.append(ap)

        payload = api.build_observation(
            seq=task["seq"],
            t=task["t"],
            # The evaluator tracks no episode; the monitor owns `step`, and inventing
            # one here would put two counters on one field.
            step=None,
            sensors={k: _jsonable(v) for k, v in sensor_eval.items()},
            ap_values=ap_values,
            unknown_aps=unknown,
            confidence=task.get("confidence", 1.0),
            data_health=task.get("data_health") or {},
            clock=task.get("clock", "internal"),
        )
        if problems := api.validate_observation(payload):
            # Refuse to publish rather than put a malformed envelope on the contract
            # topic: the monitor does not validate on receipt, so this is the only
            # place the shape can be caught.
            self.get_logger().error(
                f"observation failed validation, not published: {'; '.join(problems)}")
            return
        msg = String()
        msg.data = json.dumps(payload)
        self.obs_pub.publish(msg)


def main():
    from rclpy.utilities import remove_ros_args

    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True, choices=adapter_choices(),
                         help="Which environment's sensor topics to evaluate against.")
    parser.add_argument("--api-url", "--ollama-url", dest="api_url",
                        default="http://192.168.140.101/developer-api/v1")
    parser.add_argument("--model", default="Gemma4")
    parser.add_argument("--stale-after", type=float, default=2.0,
                        help="Seconds without a message before a sensor source counts "
                             "as stale and drops __confidence__. Must exceed the slowest "
                             "tracked topic's period (UNCALIBRATED against the real robot).")
    parser.add_argument("--upright-tilt-max", type=float, default=0.5,
                        help="Max |roll|/|pitch| (rad) still considered upright.")
    parser.add_argument("--upright-height-min", type=float, default=0.5,
                        help="Min base height (m) still considered upright. UNCALIBRATED "
                             "against the real G1's standing pelvis height.")
    args = parser.parse_args(args=remove_ros_args(args=sys.argv)[1:])

    adapter = _load_adapter(
        args.adapter,
        stale_after=args.stale_after,
        upright_tilt_max=args.upright_tilt_max,
        upright_height_min=args.upright_height_min,
    )

    rclpy.init(args=sys.argv)
    node = GenericClientNode(adapter, args.api_url, args.model)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
