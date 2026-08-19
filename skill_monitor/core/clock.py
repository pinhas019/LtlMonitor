"""The tick, as arithmetic over an injectable time source.

The whole point of this module is that **the trace is a function of one declared
frequency**, not of whichever timer happened to fire. Everything downstream folds one
window per pulse and steps its automaton once per pulse, so if the pulse count depended
on how often a loop ran, on how fast a bag replayed, or on how loaded the machine was,
then the same episode would produce a different verdict on a different day -- and the
planned Isaac Sim re-execution of counterfactuals would compare two things that were
never comparable.

Pure Python: no ``rclpy``, no sockets, no ``sleep``. The time source is injected exactly
the way ``Freshness(clock=...)`` injects one, which is what lets every invariant below be
tested by advancing a number instead of waiting.

The definitions, from ``docs/clocking.md#the-tick-defined``:

  * ``Delta = 1 / tick_hz`` **seconds** on the *active* clock. Frequency is declared;
    the period is what the arithmetic uses.
  * Tick *k* is the half-open interval ``(B_(k-1), B_k]`` where ``B_k = k*Delta`` from
    the clock's start. Half-open is the point: every instant belongs to exactly one
    tick, so no sample is counted twice and none falls between ticks.
  * **A tick is named by the boundary that CLOSES it**, not the one that opens it. That
    is what makes a pulse, the observation folded from it and the verdict stepped from
    that observation all carry the same ``seq`` for the same interval -- the one that
    just ended. Consequently ``seq = 0`` means *no interval has closed yet*: it is the
    value ``state()`` reports before the first pulse, and it is never the ``seq`` of a
    frame on the wire. **The first real interval is ``seq = 1``**, closing at
    ``t = Delta``.
  * A pulse carries ``seq`` = the index of the boundary it fired on and ``t`` = that
    boundary's time, **not** the moment the code got round to noticing. Scheduling jitter
    therefore cannot leak into the recorded time base. This is why the example in
    ``docs/api.md`` reads ``{"seq": 1041, "t": 1041.0, "tick_hz": 1.0}``: at 1 Hz the
    boundary that closes tick 1041 is at 1041.0 s, exactly, however late the process
    woke up.

Four invariants, each of which has a test named after it in ``tests/test_clock.py``:

  1. **The pulse never waits for data.** There is no way to hand data to a `TickEngine` --
     look at the API surface, it has no input. A tick fires on an empty interval because
     that is precisely the tick that has to report "not enough data" downstream.
  2. **Replay speed cannot change the tick count.** A `ReplayClock` is advanced by its
     driver, so 10x means "the driver advances the same episode seconds in less wall
     time", never "more or fewer ticks".
  3. **No catch-up.** A stall of 3*Delta emits ONE pulse whose ``seq`` jumps by 3.
     `Pulse.skipped` reports the gap for the clock's own health; consumers see the gap in
     ``seq`` and record ``missed_ticks``. Emitting three pulses back-to-back would make a
     consumer fold three windows in one instant, silently merging them.
  4. **`seq` is monotonic over the clock's lifetime and never reused** -- across a rate
     change, a mode change and a pause. Episode-scoped counting is ``step``, and that
     belongs to the monitor: this module knows nothing about episodes. A *restart* is
     the one thing that does reset it, which is why ``t0`` rides in every pulse: see
     `api.build_tick`.

`ClockService` is the policy layer: it answers `docs/api.md#clock-api` in terms of
``(status, payload)`` pairs and fans one pulse out to every sink. It is here, and not in
``backend/clock_node.py``, so that "a rate change is refused while a monitor is armed" is
a tested rule rather than a branch inside an HTTP handler that no test can reach.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable

from skill_monitor.core import api

# Boundary tests are float comparisons, and a driven clock that is advanced by Delta a
# few hundred times lands a few ULPs short of the boundary it was aimed at. Without a
# tolerance, `ManualClock` would occasionally swallow a step -- the one failure mode that
# would make single-stepping useless for debugging. One nanosecond is far below any
# meaningful tick period and far above the accumulated error.
_EPS = 1e-9

#: The tolerance is never more than this fraction of a period. An *absolute* tolerance
#: is a bug waiting for a small enough Delta: `_boundary_at` accepts a boundary that is
#: up to the tolerance in the future, so the overshoot it can produce is exactly
#: `tolerance / Delta` ticks. At 1 Hz that is a billionth of a tick and invisible; at a
#: Delta below a microsecond a fixed 1 ns would start counting boundaries that have not
#: happened. Relative, it is a millionth of a tick at every rate, by construction.
_EPS_FRACTION = 1e-6

#: Upper bound on the declared rate, matching the descriptor's own bound (P2).
#:
#: Not a performance opinion: it is what keeps `_boundary_at`'s correction loop bounded.
#: The loop walks one boundary per iteration, so a rate absurd enough that the initial
#: floor-divide lands thousands of boundaries away turns a request into a hang -- and
#: `POST /api/clock/rate` is reachable by anything that can open the port. `tick_hz`
#: ships at 1.0 and the poll timer cannot usefully resolve a Delta below a millisecond
#: anyway (see `backend/clock_node.poll_period`), so the ceiling costs nothing real.
MAX_TICK_HZ = 1000.0


class ClockError(RuntimeError):
    """An operation the active clock cannot perform (stepping a wall clock)."""


def tolerance(delta: float) -> float:
    """Boundary-comparison slack for a tick period of `delta` seconds.

    Bounded *both* ways on purpose: never more than `_EPS` (so it stays far below any
    meaningful duration) and never more than `_EPS_FRACTION` of a period (so it cannot
    grow into a whole tick as `delta` shrinks).
    """
    return min(_EPS, abs(delta) * _EPS_FRACTION)


def valid_tick_hz(value) -> float:
    """The declared rate, or `ValueError` saying why it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"tick_hz must be a number, got {value!r}")
    hz = float(value)
    if not hz > 0.0 or hz != hz or hz in (float("inf"), float("-inf")):
        raise ValueError(f"tick_hz must be finite and > 0, got {value!r}")
    if hz > MAX_TICK_HZ:
        raise ValueError(
            f"tick_hz must be <= {MAX_TICK_HZ:g}, got {value!r}: above that the tick "
            f"period is finer than the poll timer can resolve and the boundary "
            f"arithmetic stops being cheap"
        )
    return hz


# =============================================================================
# Time sources -- three of them, one interface
# =============================================================================

class TimeSource(ABC):
    """Something that answers "what time is it on the active clock".

    Seconds, monotonic, origin arbitrary: `TickEngine` measures elapsed time and never
    reads the absolute value, which is what lets the source be swapped mid-run without
    the tick's time base jumping.
    """

    #: One of `api.CLOCK_MODES`; travels in every pulse so a recording is never
    #: ambiguous about what drove it.
    MODE: str = ""

    @abstractmethod
    def now(self) -> float:
        """Seconds on this clock."""


class WallClock(TimeSource):
    """Live time. `now` is injected so a test drives it instead of sleeping.

    `time.monotonic` rather than `time.time`: an NTP correction mid-episode must not
    move a tick boundary, and must never move one backwards.
    """

    MODE = "wall"

    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._now = now

    def now(self) -> float:
        return float(self._now())


class _DrivenClock(TimeSource):
    """Time that only moves when something advances it.

    The shared body of `ReplayClock` and `ManualClock`. They differ in *who* drives them
    and therefore in what a pulse means, which is why they are two names on the wire and
    not one mode with a flag.
    """

    def __init__(self, start: float = 0.0):
        self._t = float(start)

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> float:
        """Move forward by `seconds`. Returns the new time."""
        seconds = float(seconds)
        if seconds < 0.0:
            raise ValueError(f"a clock never runs backwards; got advance({seconds!r})")
        self._t += seconds
        return self._t

    def seek(self, t: float) -> float:
        """Move to absolute time `t`, which must not be in the past.

        Backwards is refused rather than clamped: a driver that rewinds would reuse a
        `seq`, and every consumer treats a repeated `seq` as a redelivery to ignore.
        """
        t = float(t)
        if t < self._t:
            raise ValueError(f"a clock never runs backwards; at {self._t!r}, asked {t!r}")
        self._t = t
        return t


class ReplayClock(_DrivenClock):
    """Offline time, advanced by a replay driver from the recording's own timestamps.

    Because the driver advances *episode* seconds, the wall-clock speed of the replay is
    invisible here: 1x and 10x produce the same boundaries, the same tick count and
    therefore the same verdict. That is the entire reason replay does not simply run a
    `WallClock` faster.
    """

    MODE = "replay"


class ManualClock(_DrivenClock):
    """Single-step time: `POST /api/clock/step` advances the whole system one tick.

    The debugging tool that makes a stuck monitor inspectable -- with this mode the
    operator, not the machine, decides when the next window closes.
    """

    MODE = "manual"


#: mode name -> source class. `TickEngine(mode=...)` and `POST /api/clock/mode` both
#: resolve through this, so there is one place where a mode becomes a clock.
SOURCES: dict[str, type[TimeSource]] = {
    cls.MODE: cls for cls in (WallClock, ReplayClock, ManualClock)
}


# =============================================================================
# The pulse
# =============================================================================

class Pulse:
    """One tick boundary: the wire payload, plus what the clock knows about it.

    `payload` is exactly the `/monitor/tick` frame -- the same dict object goes to the
    ROS publisher and to every WebSocket client, so "identical payload, byte for byte"
    is structural rather than a promise two code paths have to keep.

    `skipped` is the number of boundaries that passed *without* a pulse because the
    process was not running when they went by. It is deliberately NOT a field of the
    payload: the wire contract is closed, consumers already see the gap in `seq`, and
    a clock reporting its own lateness in the frame would invite someone to interpolate.
    """

    __slots__ = ("payload", "skipped")

    def __init__(self, payload: dict, skipped: int = 0):
        self.payload = payload
        self.skipped = skipped

    @property
    def seq(self) -> int:
        return self.payload["seq"]

    @property
    def t(self) -> float:
        return self.payload["t"]

    @property
    def tick_hz(self) -> float:
        return self.payload["tick_hz"]

    @property
    def mode(self) -> str:
        return self.payload["mode"]

    def __repr__(self) -> str:
        return (f"Pulse(seq={self.seq}, t={self.t}, tick_hz={self.tick_hz}, "
                f"mode={self.mode!r}, skipped={self.skipped})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, Pulse) and other.payload == self.payload
                and other.skipped == self.skipped)


# =============================================================================
# The engine
# =============================================================================

class TickEngine:
    """Turns elapsed time on one source into a stream of pulses.

    Boundaries are computed from an *epoch* -- a (time, seq) pair known to be a boundary
    -- rather than by accumulating a period, so no amount of polling drifts the phase and
    a stall costs nothing but a gap in `seq`.

    Also usable by a consumer that has to free-run because no clock is on the graph
    (P3, P4): construct one, poll it, and mark the output `clock: internal`. Deciding
    *when* to fall back is the consumer's business -- only it knows it stopped hearing
    pulses.
    """

    def __init__(
        self,
        source: TimeSource | None = None,
        *,
        tick_hz: float = 1.0,
        mode: str = "wall",
        paused: bool = False,
        started_at: Callable[[], float] = time.time,
    ):
        """`mode` builds the source when none is given; a given source wins, and its
        `MODE` is what travels in the pulse. `started_at` is injected so a test can pin
        `t0`, and is unix time rather than monotonic precisely because it is the field
        that has to mean something across a restart.
        """
        if source is None:
            if mode not in SOURCES:
                raise ValueError(f"unknown clock mode {mode!r}; expected one of "
                                 f"{sorted(SOURCES)}")
            source = SOURCES[mode]()
        self._source = source
        self._tick_hz = valid_tick_hz(tick_hz)

        # Unix time at construction, recorded once. This is what makes a restart
        # observable: `seq` starts again from 0, and `t0` is how a reader tells the
        # second run's seq 7 from the first run's seq 7.
        self._t0 = float(started_at())

        # Engine time is elapsed-since-construction on whatever source is active, so
        # swapping wall -> manual (whose origins are unrelated) cannot jump `t`.
        self._origin = source.now()
        self._carried = 0.0

        # The epoch: `_epoch_t` (engine time) IS the boundary of `_epoch_seq`.
        self._epoch_t = 0.0
        self._epoch_seq = 0

        self._seq = 0
        self._last_t = 0.0
        self._paused = bool(paused)

    # ------------------------------------------------------------------ state

    @property
    def tick_hz(self) -> float:
        return self._tick_hz

    @property
    def delta(self) -> float:
        """The tick period, in seconds. The only unit any duration is compared in."""
        return 1.0 / self._tick_hz

    @property
    def mode(self) -> str:
        return self._source.MODE

    @property
    def source(self) -> TimeSource:
        return self._source

    @property
    def seq(self) -> int:
        """The last emitted tick index. 0 means no pulse has fired yet."""
        return self._seq

    @property
    def t(self) -> float:
        """The boundary time of the last pulse; 0.0 before the first."""
        return self._last_t

    @property
    def t0(self) -> float:
        """Unix time at which this clock started. Changes on every restart."""
        return self._t0

    @property
    def paused(self) -> bool:
        return self._paused

    def now(self) -> float:
        """Engine time: seconds elapsed on the active clock since construction.

        On a `WallClock` this is also wall time. On a driven clock it is **not**: it is
        how far the driver has advanced, so a `ManualClock` stepped three times reports
        3.0 whether the process started a second or a week ago. That is why the field
        this feeds is called `clock_time_s` and not `uptime_s`.
        """
        return self._carried + (self._source.now() - self._origin)

    def state(self) -> dict:
        """The body of `GET /api/clock`, minus the fields only the node knows.

        A sample, not a stream: `seq` and `t` describe the last boundary that fired and
        are up to Delta seconds stale by construction.
        """
        return {
            "seq": self._seq,
            "t": self._last_t,
            "t0": self._t0,
            "tick_hz": self._tick_hz,
            "mode": self.mode,
            # Seconds advanced on the ACTIVE clock, which on a driven clock is episode
            # time and not wall uptime. `GET /api/clock/health` carries a real
            # `uptime_s` beside this one; naming both the same thing was the bug.
            "clock_time_s": self.now(),
        }

    # ------------------------------------------------------------- boundaries

    def _t_of(self, seq: int) -> float:
        """Engine time of boundary `seq`. Exact, from the epoch -- never accumulated."""
        return self._epoch_t + (seq - self._epoch_seq) * self.delta

    def _boundary_at(self, now: float) -> int:
        """Index of the latest boundary at or before `now`."""
        delta = self.delta
        eps = tolerance(delta)
        seq = self._epoch_seq + int((now - self._epoch_t) // delta)
        if seq < self._epoch_seq:
            seq = self._epoch_seq
        # Float correction, both directions. `(3 * 0.1) / 0.1` is 2.9999999999999996,
        # and a clock that quietly skipped every 30th manual step would be worse than
        # no manual mode at all. The slack is relative (see `tolerance`): a fixed one
        # would let a fine enough Delta walk this loop past boundaries that have not
        # happened, and the walk is what makes it slow as well as wrong.
        while self._t_of(seq + 1) <= now + eps:
            seq += 1
        while seq > self._epoch_seq and self._t_of(seq) > now + eps:
            seq -= 1
        return seq

    def _rebase(self) -> None:
        """Declare *now* a boundary, keeping `seq` where it is.

        Used when the phase must restart -- a rate change or a resume. The interval in
        flight is truncated at the change instant; the alternative (letting it run to the
        boundary the old rate would have produced) would mean the pulse after a rate
        change is at neither rate, and "the tick_hz in the payload is the rate that is
        actually running" is the only property that makes a recording readable.
        """
        self._epoch_t = self.now()
        self._epoch_seq = self._seq

    # ------------------------------------------------------------------ pulse

    def _emit(self, seq: int) -> Pulse:
        skipped = seq - self._seq - 1
        self._seq = seq
        self._last_t = self._t_of(seq)
        # `t0` rides in every pulse, not just in `GET /api/clock`: a consumer that only
        # ever sees the topic is exactly the one that cannot otherwise tell this run's
        # seq 7 from the previous run's, and refusing to step backwards -- the right
        # answer to a redelivery -- would make it swallow the whole start of a new run.
        payload = api.build_tick(
            seq=seq, t=self._last_t, tick_hz=self._tick_hz, mode=self.mode, t0=self._t0
        )
        return Pulse(payload, skipped=skipped)

    def poll(self) -> Pulse | None:
        """At most ONE pulse per call, whatever the elapsed time.

        Call it as often as you like: the pulse count is a function of elapsed clock
        time and the declared rate, never of the polling rate. Poll faster than Delta or
        the boundary is noticed late; poll slower and boundaries are missed, reported as
        `skipped` and a jump in `seq`, never as a burst.
        """
        if self._paused:
            return None
        seq = self._boundary_at(self.now())
        if seq <= self._seq:
            return None
        return self._emit(seq)

    def step(self) -> Pulse:
        """Advance a driven clock to the next boundary and emit exactly that one pulse.

        `POST /api/clock/step`. Works while paused -- an explicit step is an explicit
        advance, and a paused clock is the normal state to single-step from.
        """
        if not isinstance(self._source, _DrivenClock):
            raise ClockError(
                f"cannot step a {self.mode!r} clock: it advances itself. "
                f"POST /api/clock/mode {{'mode': 'manual'}} first."
            )
        target = self._t_of(self._seq + 1)
        ahead = target - self.now()
        if ahead > 0.0:
            self._source.advance(ahead)
        return self._emit(self._seq + 1)

    # ----------------------------------------------------------------- control

    def set_rate(self, tick_hz: float) -> float:
        """Change the declared frequency from the next interval on.

        Refusing this while a monitor is armed is `ClockService`'s job, not the engine's:
        the engine has no idea what a monitor is.
        """
        self._tick_hz = valid_tick_hz(tick_hz)
        self._rebase()
        return self._tick_hz

    def set_mode(self, mode: str, *, source: TimeSource | None = None) -> str:
        """Swap the time source, keeping engine time and `seq` continuous.

        No rebase: a mode change is a change of *what* measures the seconds, not of how
        long a tick is, so the phase carries over. Selecting the mode already running is
        a no-op rather than a fresh clock of the same kind -- an idempotent `POST
        /api/clock/mode` is one a frontend can send on every reconnect.
        """
        if source is None:
            if mode not in SOURCES:
                raise ValueError(f"unknown clock mode {mode!r}; expected one of "
                                 f"{sorted(SOURCES)}")
            if mode == self.mode:
                return self.mode
            source = SOURCES[mode]()
        self._carried = self.now()
        self._source = source
        self._origin = source.now()
        return self.mode

    def pause(self) -> None:
        """Stop emitting. Time spent paused produces no ticks and no gap."""
        self._paused = True

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            # Rebase, so a clock paused for an hour does not resume with a `seq` jump of
            # 3600 that every consumer would read as an hour of lost data.
            self._rebase()


# =============================================================================
# What the clock is allowed to believe about a monitor
# =============================================================================

class ArmedTracker:
    """Whether any monitor is armed, inferred from the wire and nothing else.

    `POST /api/clock/rate` is refused while a monitor is armed, and the clock has no
    other way to know: it holds no episode state, by design. Two independent signals,
    because either alone is wrong:

      * `/monitor/command` -- `arm` arms, `reset` disarms. Exact, but a clock that was
        restarted mid-episode never saw the `arm`, and would then happily accept a rate
        change that redefines every remaining timeout in the spec.
      * `/monitor/verdict` -- a verdict whose `step` is not null *is* an armed monitor
        saying so, once per tick. Self-healing after a restart, and it expires, so a
        monitor that goes away does not leave the rate pinned forever.

    Errs toward refusing: `hold_s` outlives several ticks, and the cost of a wrongly
    refused rate change is an error message, while the cost of a wrongly accepted one is
    a recorded episode whose timeouts silently mean something else.
    """

    def __init__(self, *, hold_s: float = 5.0, clock: Callable[[], float] = time.monotonic):
        self._hold_s = float(hold_s)
        self._clock = clock
        self._commanded = False
        self._last_armed_verdict: float | None = None

    def on_command(self, payload) -> None:
        if isinstance(payload, dict):
            command = payload.get("command")
            if command == "arm":
                self._commanded = True
            elif command == "reset":
                self._commanded = False
                self._last_armed_verdict = None

    def on_verdict(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("step") is not None:
            self._last_armed_verdict = self._clock()

    def __call__(self) -> bool:
        if self._commanded:
            return True
        seen = self._last_armed_verdict
        return seen is not None and (self._clock() - seen) <= self._hold_s


# =============================================================================
# The service -- docs/api.md#clock-api, without a socket in sight
# =============================================================================

class ClockService:
    """The clock's HTTP surface as pure ``(status, payload)`` decisions, plus the fan-out.

    Every sink registered with `subscribe` receives *the same dict object* the ROS
    publisher gets, which is how `WS /api/clock/stream` is identical to `/monitor/tick`
    byte for byte rather than by a comment asking two code paths to agree.

    `armed` and `subscribers` are injected callables: the clock cannot know whether a
    monitor is armed or whether anything is listening, and reaching for either would put
    ROS inside this module.
    """

    def __init__(
        self,
        engine: TickEngine,
        *,
        armed: Callable[[], bool] = lambda: False,
        subscribers: Callable[[], int] = lambda: 0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._engine = engine
        self._armed = armed
        self._subscribers = subscribers
        # Wall seconds this process has been up, which is a different quantity from the
        # engine's clock time and only coincides on a `WallClock`. Injected, and read
        # once here, so `GET /api/clock/health` can report both without a test having
        # to wait for either.
        self._monotonic = monotonic
        self._started = float(monotonic())
        self._sinks: list[Callable[[dict], None]] = []

    @property
    def engine(self) -> TickEngine:
        return self._engine

    # --------------------------------------------------------------- fan-out

    def subscribe(self, sink: Callable[[dict], None]) -> Callable[[dict], None]:
        """Register a pulse sink (the ROS publisher, a WebSocket client, a test)."""
        self._sinks.append(sink)
        return sink

    def unsubscribe(self, sink: Callable[[dict], None]) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    def _dispatch(self, pulse: Pulse) -> Pulse:
        # A copy of the list: a WebSocket sink that unsubscribes itself on a dead socket
        # must not shorten the list being iterated.
        for sink in list(self._sinks):
            sink(pulse.payload)
        return pulse

    def pulse(self) -> Pulse | None:
        """Poll the engine and fan out at most one pulse. The node's timer calls this."""
        pulse = self._engine.poll()
        return None if pulse is None else self._dispatch(pulse)

    # ---------------------------------------------------------------- reads

    def get_state(self) -> dict:
        """`GET /api/clock` -- a SAMPLE. Polling this loop will miss ticks."""
        return self._engine.state() | {"subscribers": int(self._subscribers())}

    def get_health(self) -> dict:
        """`GET /api/clock/health` -- alive, and is anything actually consuming the pulse.

        `consumed` is the interesting one: a clock pulsing into an empty graph looks
        perfectly healthy from every other angle.

        **`uptime_s` and `clock_time_s` are two different quantities** and both are
        reported, because next to `t0` and `last_pulse_age_s` a single one would be
        read as wall uptime whichever it was. `uptime_s` is how long this process has
        run; `clock_time_s` is how far the active clock has advanced. On a `wall` clock
        they track each other. On a `manual` clock stepped three times in an hour they
        are 3600 and 3.0, and the gap between them is the diagnosis.
        """
        subscribers = int(self._subscribers())
        engine = self._engine
        return {
            "ok": True,
            "mode": engine.mode,
            "tick_hz": engine.tick_hz,
            "seq": engine.seq,
            "t": engine.t,
            "t0": engine.t0,
            "uptime_s": float(self._monotonic()) - self._started,
            "clock_time_s": engine.now(),
            "paused": engine.paused,
            # Age on the ACTIVE clock: on a driven clock a pulse is not "old" because
            # nobody stepped it, and reporting wall seconds here would make a parked
            # replay look like a dead clock.
            "last_pulse_age_s": None if engine.seq == 0 else engine.now() - engine.t,
            "subscribers": subscribers,
            "consumed": subscribers > 0,
        }

    # --------------------------------------------------------------- writes

    def post_mode(self, body) -> tuple[int, dict]:
        """`POST /api/clock/mode` -- `{"mode": "manual"}`, optionally `"paused"`."""
        if not isinstance(body, dict):
            return 400, {"error": "body must be a JSON object"}
        mode = body.get("mode")
        if mode not in api.CLOCK_MODES:
            return 400, {"error": f"mode must be one of {list(api.CLOCK_MODES)}, "
                                  f"got {mode!r}"}
        self._engine.set_mode(mode)
        paused = body.get("paused")
        if paused is not None:
            if not isinstance(paused, bool):
                return 400, {"error": f"paused must be a bool, got {paused!r}"}
            self._engine.pause() if paused else self._engine.resume()
        return 200, self.get_state()

    def post_step(self, body=None) -> tuple[int, dict]:
        """`POST /api/clock/step` -- advance the whole system by exactly one tick.

        Answers with the pulse itself, so the stepping client reads the same frame every
        other consumer just received instead of inferring it from a subsequent GET.

        Accepted on **any driven clock**, so `replay` as well as `manual`. That is a
        deliberate widening of `docs/api.md`'s original "manual only", now recorded
        there too: a replay driver advances a `ReplayClock` by seconds anyway, and
        refusing to let it advance by exactly one tick would only push the boundary
        arithmetic -- the one thing this module exists to own -- into every driver.
        `wall` is still a 409, because a self-advancing clock stepped by hand would
        emit a boundary that never happened.
        """
        try:
            pulse = self._engine.step()
        except ClockError as exc:
            return 409, {"error": str(exc), "mode": self._engine.mode}
        self._dispatch(pulse)
        return 200, pulse.payload

    def post_rate(self, body) -> tuple[int, dict]:
        """`POST /api/clock/rate` -- `{"tick_hz": 5.0}`, refused while a monitor is armed.

        `max_steps` is tick-denominated until P11, so a 120-tick phase budget is 2
        minutes at 1 Hz and 24 seconds at 5 Hz: accepting this mid-episode would silently
        redefine every timeout in the spec. The accepted change needs no separate record
        -- the next pulse carries the new `tick_hz`, which is why a recording can never be
        misread about the rate it ran at.
        """
        if not isinstance(body, dict):
            return 400, {"error": "body must be a JSON object"}
        try:
            tick_hz = valid_tick_hz(body.get("tick_hz"))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        if self._armed():
            return 409, {
                "error": "rate change refused while a monitor is armed: spec budgets are "
                         "tick-denominated, so a new rate would redefine every timeout "
                         "mid-episode",
                "tick_hz": self._engine.tick_hz,
            }
        self._engine.set_rate(tick_hz)
        return 200, self.get_state()

    # --------------------------------------------------------------- routing

    def handle(self, method: str, path: str, body=None) -> tuple[int, dict]:
        """One router, so `backend/clock_node.py` holds no policy at all.

        The gateway (P6) proxies these same paths; keeping the table here means the two
        cannot drift.
        """
        route = path.rstrip("/")
        reads = {"/api/clock": self.get_state, "/api/clock/health": self.get_health}
        writes = {
            "/api/clock/mode": self.post_mode,
            "/api/clock/step": self.post_step,
            "/api/clock/rate": self.post_rate,
        }
        method = method.upper()
        if method == "GET":
            if route in reads:
                return 200, reads[route]()
            if route in writes:
                return 405, {"error": f"{route} is POST only"}
        elif method == "POST":
            if route in writes:
                return writes[route](body)
            if route in reads:
                return 405, {"error": f"{route} is GET only"}
        else:
            return 405, {"error": f"method {method} not allowed"}
        return 404, {"error": f"no such endpoint {path!r}",
                     "endpoints": sorted(reads) + sorted(writes)}
