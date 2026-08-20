"""A monitor that exists only in this process, on the gateway's own bus interface.

This is a **fiction**, and it says so on the wire: ``services.ros.detail`` names it, so
an operator looking at the page can never mistake mocked sensor values for a robot's.
It exists because this host has no ``rclpy`` and cannot see the robot's DDS graph, so
it is the only way to develop or review the operator surface at all.

What it is not allowed to be is an *approximation*. Every frame it publishes goes
through ``core.api``'s builders and is validated by the same validators the real
producers are held to -- see ``tests/test_web_ui.py``. If the contract moves and this
does not, the tests fail here rather than in a browser.

The spec and the adapter are the real ones off disk (``specs/g1`` and
``adapters/real_g1.json``): the panes that render a spec, its APs and its topic list are
then rendering the actual artefacts, not a stand-in shaped like them.
"""

from __future__ import annotations

import json
import math
import threading
import time

import skill_monitor
from skill_monitor.backend.gateway import BusUnavailable, MonitorBus
from skill_monitor.core import adapter_spec, api, spec_contract

NS = "/g1"

#: Sensor keys whose value is a number the mock varies over time. Everything else in the
#: schema is categorical and is driven by the little state machine in `_sensors`.
_NOISY = ("linear_vel", "angular_vel", "base_roll", "base_pitch")


class MockBus(MonitorBus):
    """One namespace, one monitor, ticking at the adapter's own ``tick_hz``."""

    def __init__(self, spec_name: str = "g1", adapter_name: str = "real_g1",
                 rate_scale: float = 1.0):
        self.spec = json.loads(skill_monitor.spec_path(spec_name).read_text())
        # The descriptor's own manifest, wrapped in the wire envelope it predates.
        described = adapter_spec.load(adapter_name).manifest()
        self.adapter = api.build_adapter(
            adapter=adapter_name,
            doc=described["doc"],
            tick_hz=described["tick_hz"],
            schema=described["schema"],
            sources=described["sources"],
            warnings=described.get("warnings", ()),
        )
        self.tick_hz = float(self.adapter["tick_hz"])
        # Wall-clock seconds between pulses. Scaled separately from `tick_hz` because
        # the wire value must stay the robot's -- a page that renders "1 Hz" while
        # frames arrive at 4 Hz is showing a lie the operator cannot see through.
        self.period = 1.0 / (self.tick_hz * rate_scale)
        self.t0 = time.time()

        self._latched = {
            api.ADAPTER: json.dumps(self.adapter),
            api.MANIFEST: json.dumps(
                api.build_skill_manifest(spec=self.spec, source="mock")),
            api.SPEC_STATUS: json.dumps({
                "schema_version": api.SCHEMA_VERSION, "ok": True, "problems": [],
                "skill_name": self.spec.get("skill_name", ""), "source": "mock",
            }),
        }
        self._subs: list[tuple[str, tuple, callable]] = []
        self._lock = threading.Lock()
        self._last_seen: float | None = None
        self._seq = 0
        self._step = 0
        self._paused = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mock-monitor",
                                        daemon=True)
        self._thread.start()

    # -- MonitorBus --------------------------------------------------------

    def namespaces(self):
        return [NS]

    def latched(self, ns, topic):
        return self._latched.get(topic) if ns == NS else None

    def last_seen(self, ns):
        return self._last_seen if ns == NS else None

    def status(self):
        return {
            "available": True,
            "detail": ("MOCK -- there is no ROS here. Every sensor value on this page "
                       "is fabricated by skill_monitor.frontend.mock_monitor."),
            "mock": True,
        }

    def subscribe(self, ns, topics, callback):
        entry = (ns, tuple(topics), callback)
        with self._lock:
            self._subs.append(entry)

        def unsubscribe():
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)
        return unsubscribe

    def publish(self, ns, topic, payload_text):
        if ns != NS:
            raise BusUnavailable(f"the mock serves {NS} only, not {ns!r}")
        if topic == api.COMMAND:
            self._command(json.loads(payload_text).get("command"))
        elif topic == api.LOAD_SPEC:
            self._load_spec(json.loads(payload_text).get("spec") or {})
        # Anything else is accepted and dropped: the mock is not the place to decide
        # which ingress topics a real monitor answers.

    def shutdown(self):
        self._stop.set()

    # -- the fiction -------------------------------------------------------

    def _command(self, command):
        if command == "reset":
            self._step = 0
        elif command in ("pause", "resume"):
            self._paused = command == "pause"

    def _load_spec(self, spec):
        """Hot reload, and the episode ends because of it.

        A spec swap mid-episode leaves the automaton stepping propositions from a
        document nobody is looking at any more, so the step counter restarts and the
        answer says which spec is now loaded.
        """
        problems = spec_contract.validate(spec, self.adapter["schema"].keys())
        status = {
            "schema_version": api.SCHEMA_VERSION,
            "ok": not problems,
            "problems": problems,
            "skill_name": spec.get("skill_name", ""),
            "source": "load_spec",
        }
        if not problems:
            self.spec = spec
            self._step = 0
            self._latched[api.MANIFEST] = json.dumps(
                api.build_skill_manifest(spec=spec, source="load_spec"))
        self._latched[api.SPEC_STATUS] = json.dumps(status)
        self._emit(api.SPEC_STATUS, self._latched[api.SPEC_STATUS])

    def _run(self):
        while not self._stop.wait(self.period):
            if self._paused:
                continue
            self._seq += 1
            self._step += 1
            self._pulse()
            if self._step >= self._episode_steps():
                # The episode ends and the next one starts. `seq` does not restart with
                # it -- it is the clock's axis, not the run's, and a console that saw
                # both go back to 1 could not tell a new episode from a new clock.
                self._step = 0

    def _pulse(self):
        seq, step = self._seq, self._step
        t = self.t0 + seq / self.tick_hz
        self._emit(api.TICK, json.dumps(api.build_tick(
            seq=seq, t=t, tick_hz=self.tick_hz, t0=self.t0, mode="wall")))

        sensors = self._sensors(step)
        stale = self._stale_sources(step)
        ap_values, unknown = self._aps(sensors, stale)
        confidence = 0.5 if stale else 1.0
        self._emit(api.OBSERVATION, json.dumps(api.build_observation(
            seq=seq, t=t, step=step, sensors=sensors, ap_values=ap_values,
            unknown_aps=unknown, confidence=confidence,
            data_health=self._health(step, stale))))

        self._emit(api.VERDICT, json.dumps(self._verdict(seq, t, step, ap_values,
                                                         unknown, stale, confidence)))
        self._last_seen = time.time()

    def _emit(self, topic, text):
        with self._lock:
            subs = [s for s in self._subs if s[0] == NS and topic in s[1]]
        for _ns, _topics, callback in subs:
            callback(topic, text)

    def _episode_steps(self) -> int:
        """The whole run's bound: every phase's own, summed. A spec with no bounds runs
        for a nominal 150 ticks rather than forever, so the mock's step counter is
        always something the max-steps pane can be read against."""
        total = sum(_max_steps(self.spec, i) or 0
                    for i in range(len(self.spec.get("execution_phases") or [])))
        return total or 150

    def _stale_sources(self, step):
        # The depth camera drops out for six ticks in every sixty. This is the case the
        # panes exist for: staleness, an UNKNOWN AP, and a de-rated confidence, all at
        # once and all visible.
        return ["points"] if 20 <= step % 60 < 26 else []

    def _phase_at(self, step):
        """(index, steps spent in it), walking the spec's own per-phase bounds."""
        phases = self.spec.get("execution_phases") or []
        if not phases:
            return None, step
        left = step
        for i in range(len(phases)):
            bound = _max_steps(self.spec, i) or 50
            if left < bound or i == len(phases) - 1:
                return i, left
            left -= bound
        return len(phases) - 1, left

    def _sensors(self, step):
        phase = min((self._phase_at(step)[0] or 0), 2)
        min_range = max(0.18, 3.0 - 0.02 * (step % 150))
        return {
            "min_range": round(min_range, 3),
            "base_roll": round(0.02 * math.sin(step / 6.0), 4),
            "base_pitch": round(0.03 * math.cos(step / 9.0), 4),
            "base_height": round(0.78 + 0.01 * math.sin(step / 4.0), 4),
            "upright_flag": 1.0,
            "linear_vel": round(max(0.0, 0.45 + 0.08 * math.sin(step / 5.0)), 3),
            "angular_vel": round(0.15 * math.sin(step / 11.0), 3),
            "nav_mode": "AUTOMATIC",
            "nav_state": ("planning", "following", "following")[phase],
            "num_waypoints": 4,
            "current_target_idx": min(3, step // 20),
            "mission_finished": step % 150 > 140,
            "nav_stuck": False,
            "image_similarity_to_goal": round(min(0.95, 0.2 + 0.006 * (step % 150)), 3),
        }

    def _aps(self, sensors, stale):
        """Evaluate the spec's own rules against the fabricated sensors.

        The same ``eval`` shape the evaluator uses, over the same rule text, so an AP
        that this page shows as true is true *for the reason the rule gives*. A key fed
        only by a stale source makes its APs UNKNOWN rather than false -- which is the
        whole reason ``unknown_aps`` is a sibling list and not a third truth value.
        """
        blind = {k for k in self.adapter["schema"]
                 if any(k in s.get("keys", []) for s in self.adapter["sources"]
                        if s["id"] in stale)}
        values, unknown = {}, []
        for name, description in self.spec["atomic_propositions"].items():
            keys = spec_contract.sensor_keys_in_rule(description)
            if keys & blind:
                unknown.append(name)
                continue
            rule = spec_contract.rule_of(description)
            if rule is None:
                unknown.append(name)          # an LLM-evaluated AP; the mock has no model
                continue
            try:
                values[name] = bool(eval(rule, {}, sensors))
            except Exception:                       # noqa: BLE001
                unknown.append(name)
        return values, unknown

    def _health(self, step, stale):
        health = {}
        for source in self.adapter["sources"]:
            is_stale = source["id"] in stale
            expected = float(source["expected_hz"])
            health[source["id"]] = {
                "rate_hz": 0.0 if is_stale else round(expected * (0.95 + 0.1 *
                                                      math.sin(step / 7.0)), 3),
                "expected_hz": expected,
                "age_s": round(6.0 if is_stale else 1.0 / max(expected, 1e-6), 3),
                "samples_this_tick": 0 if is_stale else max(1, int(expected)),
                "refreshed": not is_stale,
                "dropped": 0,
            }
        return health

    def _verdict(self, seq, t, step, ap_values, unknown, stale, confidence):
        phases = api.phase_names(self.spec.get("execution_phases"))
        phase_index, in_phase = self._phase_at(step)
        phase = phases[phase_index] if phases and phase_index is not None else None
        bound = _max_steps(self.spec, phase_index)

        # Whichever failure mode the spec declares first, and only that one. Naming a
        # mode here would tie the mock to this particular navigation spec, and tripping
        # every SAFETY mode at once would have the page claim the robot fell over at the
        # same instant it saw an obstacle.
        declared = self.spec.get("named_failure_modes", [])
        tripped = declared[0]["name"] if declared else None
        violated = ap_values.get("collision_risk", False)
        modes = [
            api.build_failure_mode(
                name=m["name"], fault_category=m.get("fault_category", "SAFETY"),
                status="VIOLATED" if violated and m["name"] == tripped
                       else "INCONCLUSIVE",
                confidence=confidence)
            for m in declared
        ]
        action = ("HALT" if violated and confidence > 0.75 else
                  "WARN" if violated or stale else "CONTINUE")
        return api.build_verdict(
            seq=seq, t=t, step=step,
            skill_name=self.spec.get("skill_name", ""),
            phase=phase, phase_index=phase_index,
            verdict="VIOLATED" if violated else "UNDECIDED",
            formulas=[api.build_formula(name=f["name"], status="INCONCLUSIVE")
                      for f in self.spec.get("ltl_formulas", [])],
            failure_modes=modes,
            risk=api.build_risk(
                steps_to_timeout=None if bound is None else max(0, bound - in_phase),
                seconds_to_timeout=(None if bound is None
                                    else round(max(0, bound - in_phase) / self.tick_hz, 3)),
                violations_to_fault=None,
                warn=bool(stale or violated),
                severity="SAFETY" if violated else None,
                trigger_confidence=confidence,
                stale_sources=list(stale),
            ),
            intervention=api.build_intervention(
                action=action,
                category="SAFETY" if violated else None,
                imminence="now" if violated else None,
                confidence=confidence),
            missed_ticks=0,
        )


def _max_steps(spec, phase_index):
    phases = spec.get("execution_phases") or []
    if phase_index is None or not (0 <= phase_index < len(phases)):
        return None
    bounds = phases[phase_index].get("timing_bounds") or {}
    value = bounds.get("max_steps")
    return value if isinstance(value, int) else None
