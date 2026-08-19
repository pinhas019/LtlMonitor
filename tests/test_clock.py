"""The tick: four invariants, and the rate change that must be refused.

    python3 -m pytest tests/test_clock.py

Everything here runs against an injected time source. No sleeping, no sockets, no ROS --
which is the point of keeping `core/clock.py` pure: the properties that decide whether
two runs of the same episode are comparable are testable by advancing a number.

The four, from docs/packages/P1-clock.md:

  1. the tick count depends only on elapsed clock time, not on how often the loop ran
  2. replay speed does not change it
  3. a pulse fires on an empty interval
  4. a stall produces a gap, never a burst
"""

from __future__ import annotations

import pytest

from skill_monitor.core import api
from skill_monitor.core.clock import (
    MAX_TICK_HZ, ArmedTracker, ClockError, ClockService, ManualClock, Pulse, ReplayClock,
    SOURCES, TickEngine, WallClock, tolerance,
)


class FakeWall:
    """A wall clock a test drives directly. Same shape as `Freshness(clock=...)`."""

    def __init__(self, t: float = 0.0):
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t


def _wall(tick_hz: float = 1.0) -> tuple[TickEngine, FakeWall]:
    fake = FakeWall()
    return TickEngine(WallClock(now=fake), tick_hz=tick_hz, started_at=lambda: 1000.0), fake


def _drain(engine: TickEngine) -> list[Pulse]:
    """Every pulse the engine will give up right now.

    Which is at most ONE, always -- that is invariant 4, and this helper exists so a
    test that expects a burst would see it rather than quietly polling once.
    """
    pulses = []
    while (pulse := engine.poll()) is not None:
        pulses.append(pulse)
        if len(pulses) > 100:  # a catch-up bug would otherwise hang the suite
            break
    return pulses


# =============================================================================
# 1. The tick count is a function of elapsed clock time
# =============================================================================

@pytest.mark.parametrize("poll_dt", [0.5, 0.1, 0.05, 0.017, 0.001])
def test_tick_count_depends_only_on_elapsed_clock_time(poll_dt):
    """10 s at 2 Hz is 20 pulses, whether the loop ran 20 times or 10 000."""
    engine, fake = _wall(tick_hz=2.0)
    pulses = []
    elapsed = 0.0
    while elapsed < 10.0 - 1e-9:
        fake.advance(poll_dt)
        elapsed += poll_dt
        pulses.extend(_drain(engine))

    assert len(pulses) == 20
    assert [p.seq for p in pulses] == list(range(1, 21))
    # Boundaries are exact multiples of the period, not an accumulation of poll_dt.
    assert [round(p.t, 9) for p in pulses] == [round(k * 0.5, 9) for k in range(1, 21)]


def test_a_faster_loop_does_not_produce_more_ticks():
    """The same elapsed time, polled 100x more often, is the same stream."""
    slow, slow_clock = _wall(tick_hz=4.0)
    fast, fast_clock = _wall(tick_hz=4.0)

    slow_seqs = []
    for _ in range(50):          # 0.1 s per poll
        slow_clock.advance(0.1)
        slow_seqs += [p.seq for p in _drain(slow)]

    fast_seqs = []
    for _ in range(5000):        # 0.001 s per poll, same 5 s
        fast_clock.advance(0.001)
        fast_seqs += [p.seq for p in _drain(fast)]

    assert slow_seqs == fast_seqs == list(range(1, 21))


def test_the_payload_is_the_wire_contract():
    engine, fake = _wall()
    fake.advance(1.0)
    pulse = engine.poll()
    assert api.validate_tick(pulse.payload) == []
    assert pulse.payload == {
        "schema_version": api.SCHEMA_VERSION, "seq": 1, "t": 1.0,
        "tick_hz": 1.0, "mode": "wall", "t0": 1000.0,
    }


def test_a_tick_is_named_by_the_boundary_that_closes_it():
    """`seq=0` means no interval has closed yet; the first real interval is `seq=1`.

    The convention docs/clocking.md defines: tick k is `(B_(k-1), B_k]`. A pulse, the
    observation folded from it and the verdict stepped from that observation all carry
    the same `seq` for the same interval -- the one that just ended. Naming a tick by
    the boundary that OPENS it would put the pulse a whole period out of step with
    every consumer of it.
    """
    engine, fake = _wall(tick_hz=1.0)
    assert engine.seq == 0                      # nothing has closed
    assert engine.state()["seq"] == 0
    assert engine.poll() is None                # and 0 is never a frame on the wire

    fake.advance(1.0)
    first = engine.poll()
    assert (first.seq, first.t) == (1, 1.0)     # the interval (0, 1], closing at Delta

    fake.advance(1.0)
    assert (engine.poll().seq, engine.t) == (2, 2.0)


def test_every_mode_in_the_wire_vocabulary_has_a_clock():
    """A mode the contract names but the clock cannot build is a 400 waiting to happen."""
    assert sorted(SOURCES) == sorted(api.CLOCK_MODES)
    for mode in api.CLOCK_MODES:
        assert TickEngine(mode=mode).mode == mode


# =============================================================================
# 2. Replay speed does not change the tick count
# =============================================================================

def _replay(tick_hz: float, episode_s: float, driver_dt: float) -> list[dict]:
    """Drive `episode_s` of recording forward in `driver_dt` increments."""
    engine = TickEngine(ReplayClock(), tick_hz=tick_hz, started_at=lambda: 1000.0)
    payloads = []
    steps = round(episode_s / driver_dt)
    for _ in range(steps):
        engine.source.advance(driver_dt)
        payloads += [p.payload for p in _drain(engine)]
    return payloads


def test_replay_speed_does_not_change_tick_count():
    """1x and 10x differ in wall time per driver iteration -- and in nothing else.

    A replay that produced a different number of ticks would produce a different trace
    and therefore a different verdict, which would make the sim-vs-real comparison the
    whole engine exists for meaningless.
    """
    at_1x = _replay(tick_hz=2.0, episode_s=10.0, driver_dt=0.1)
    at_10x = _replay(tick_hz=2.0, episode_s=10.0, driver_dt=0.01)
    assert at_1x == at_10x
    assert [p["seq"] for p in at_1x] == list(range(1, 21))


def test_a_replay_clock_never_runs_backwards():
    """Rewinding would reuse a seq, and every consumer reads a repeat as a redelivery."""
    clock = ReplayClock(start=5.0)
    with pytest.raises(ValueError):
        clock.seek(4.0)
    with pytest.raises(ValueError):
        clock.advance(-1.0)


# =============================================================================
# 3. A pulse fires on an empty interval
# =============================================================================

def test_pulse_fires_on_an_empty_interval():
    """Nothing has been observed, by anyone, ever -- and the tick still fires.

    That tick is precisely the one that must report "not enough data" downstream, so
    suppressing it would delete the only evidence that a sensor died.
    """
    engine, fake = _wall(tick_hz=5.0)
    for _ in range(5):
        fake.advance(0.2)
        pulse = engine.poll()
        assert pulse is not None


def test_the_engine_has_no_way_to_be_given_data():
    """Structural, not behavioural: the pulse cannot wait for data it cannot receive.

    There is no watermark and no adaptive delay here -- that was considered and dropped
    (docs/clocking.md). This test fails the moment someone adds an input.
    """
    engine, _ = _wall()
    surface = {name for name in dir(engine) if not name.startswith("_")}
    assert surface == {
        "delta", "mode", "now", "pause", "paused", "poll", "resume", "seq", "set_mode",
        "set_rate", "source", "state", "step", "t", "t0", "tick_hz",
    }


# =============================================================================
# 4. A stall reports a gap, never a burst
# =============================================================================

def test_no_catch_up_after_a_stall():
    """Three periods pass with the process descheduled: ONE pulse, and the gap is said.

    A burst would make every consumer fold three windows in the same instant, silently
    merging three ticks' worth of observations into one.
    """
    engine, fake = _wall(tick_hz=1.0)
    fake.advance(1.0)
    assert [p.seq for p in _drain(engine)] == [1]

    fake.advance(3.0)              # the stall
    pulses = _drain(engine)
    assert len(pulses) == 1
    assert pulses[0].seq == 4      # seq stays the index of the boundary, so the gap shows
    assert pulses[0].skipped == 2  # two boundaries went by unpublished
    assert pulses[0].t == 4.0

    fake.advance(1.0)
    resumed = _drain(engine)
    assert [p.seq for p in resumed] == [5]
    assert resumed[0].skipped == 0


def test_an_interval_is_never_widened_by_a_stall():
    """Recovery is back on the original phase, not Delta after the late pulse."""
    engine, fake = _wall(tick_hz=2.0)
    fake.advance(2.6)              # boundaries at 0.5 .. 2.5 all passed
    late = engine.poll()
    assert (late.seq, late.t) == (5, 2.5)
    fake.advance(0.4)              # 3.0 -- the next boundary is 3.0, not 3.1
    assert engine.poll().t == 3.0


def test_the_gap_is_not_a_field_of_the_wire_payload():
    """Consumers see the gap in `seq` and record `missed_ticks` themselves.

    Putting it in the frame would both break the closed contract and invite someone to
    interpolate the ticks that never happened.
    """
    engine, fake = _wall()
    fake.advance(3.0)
    pulse = engine.poll()
    assert pulse.skipped == 2
    assert "skipped" not in pulse.payload
    assert api.validate_tick(pulse.payload) == []


# =============================================================================
# Manual mode
# =============================================================================

def test_manual_mode_advances_exactly_one_tick_per_step():
    engine = TickEngine(ManualClock(), tick_hz=1.0)
    assert engine.poll() is None            # nothing advances a manual clock but a step

    seqs = []
    for _ in range(5):
        seqs.append(engine.step().seq)
        assert engine.poll() is None        # the step consumed exactly its own boundary
    assert seqs == [1, 2, 3, 4, 5]
    assert engine.t == 5.0


@pytest.mark.parametrize("tick_hz", [1.0, 3.0, 10.0, 60.0])
def test_stepping_does_not_drift(tick_hz):
    """400 steps at 3 Hz must be tick 400, not 399: float error must not eat a step."""
    engine = TickEngine(ManualClock(), tick_hz=tick_hz)
    for _ in range(400):
        engine.step()
    assert engine.seq == 400
    assert engine.t == pytest.approx(400.0 / tick_hz)


def test_a_wall_clock_cannot_be_stepped():
    engine, _ = _wall()
    with pytest.raises(ClockError):
        engine.step()


def test_a_paused_clock_emits_nothing_and_reports_no_gap():
    engine, fake = _wall()
    engine.pause()
    fake.advance(100.0)
    assert _drain(engine) == []

    engine.resume()
    fake.advance(1.0)
    pulses = _drain(engine)
    # One pulse, seq 1: the 100 s spent paused are not 100 lost ticks.
    assert [(p.seq, p.skipped) for p in pulses] == [(1, 0)]


# =============================================================================
# seq is monotonic over the clock's lifetime and never reused
# =============================================================================

def test_seq_is_monotonic_and_never_reused():
    """Across a rate change, a mode change and a pause -- the clock's whole lifetime.

    Episode-scoped counting is `step`, and that is the monitor's business: nothing here
    resets.
    """
    engine, fake = _wall(tick_hz=1.0)
    seen = []

    for _ in range(3):
        fake.advance(1.0)
        seen += [p.seq for p in _drain(engine)]

    engine.set_rate(4.0)
    for _ in range(8):
        fake.advance(0.25)
        seen += [p.seq for p in _drain(engine)]

    engine.pause()
    fake.advance(10.0)
    engine.resume()
    fake.advance(0.25)
    seen += [p.seq for p in _drain(engine)]

    engine.set_mode("manual")
    seen.append(engine.step().seq)

    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))
    assert seen[0] == 1


def test_restarting_the_clock_is_observable():
    """seq starts again from 0, so t0 is the only thing that tells two runs apart."""
    first = TickEngine(mode="wall", started_at=lambda: 1000.0)
    second = TickEngine(mode="wall", started_at=lambda: 2000.0)
    assert first.t0 != second.t0
    assert first.seq == second.seq == 0


def test_a_restart_is_visible_in_the_pulse_and_not_only_in_the_http_sample():
    """`t0` rides in every `/monitor/tick` frame, because that is where it is needed.

    The consumer that gets hurt by a restart is the one watching the TOPIC. P4's
    `TickLedger` correctly refuses to step backwards -- the right answer to a
    redelivered frame -- so a clock that restarts `seq` at 1 while signalling the
    restart only in `GET /api/clock` makes the monitor discard the new run's first N
    ticks, N being however far the previous run got, and then silently resume
    mid-episode. A clock restarted after 83 minutes at 1 Hz swallows the next 83
    minutes of monitoring with no error.

    Same `t0` and a lower `seq` is a redelivery to drop; a different `t0` is a new
    clock. Neither is inferable from `seq` alone.
    """
    first, first_wall = _wall(tick_hz=1.0)
    first_wall.advance(5000.0)
    long_run = first.poll()
    assert long_run.seq == 5000

    second = TickEngine(WallClock(now=(second_wall := FakeWall())), tick_hz=1.0,
                        started_at=lambda: 9999.0)
    second_wall.advance(1.0)
    fresh = second.poll()

    # The new run's very first frame is `seq=1`, far behind the old run's last.
    assert fresh.seq == 1 < long_run.seq
    # ...and the frame itself says so, without anyone having to poll the HTTP sample.
    assert long_run.payload["t0"] == 1000.0
    assert fresh.payload["t0"] == 9999.0
    assert fresh.payload["t0"] != long_run.payload["t0"]
    assert api.validate_tick(fresh.payload) == []


def test_t0_is_required_by_the_wire_contract_not_merely_tolerated():
    """A tick without it validates as a problem, so a producer cannot forget it."""
    engine, fake = _wall()
    fake.advance(1.0)
    payload = engine.poll().payload
    stripped = {k: v for k, v in payload.items() if k != "t0"}
    assert any("t0" in problem for problem in api.validate_tick(stripped))


def test_every_pulse_carries_t0_not_just_the_first():
    """A consumer that connects mid-run must be able to tell which clock it joined."""
    engine, fake = _wall(tick_hz=2.0)
    seen = []
    for _ in range(6):
        fake.advance(0.5)
        seen.append(engine.poll().payload["t0"])
    assert seen == [1000.0] * 6


def test_a_mode_change_does_not_jump_the_time_base():
    """Wall and manual clocks have unrelated origins; `t` must not notice the swap."""
    engine, fake = _wall(tick_hz=1.0)
    fake.advance(2.5)
    _drain(engine)
    assert engine.now() == pytest.approx(2.5)

    engine.set_mode("manual")
    assert engine.now() == pytest.approx(2.5)
    assert engine.step().t == 3.0          # the next boundary, on the same phase


# =============================================================================
# The rate change, and who is allowed to make it
# =============================================================================

def _service(tick_hz=1.0, armed=False, subscribers=0):
    engine, fake = _wall(tick_hz=tick_hz)
    # One FakeWall drives both the tick source and the service's uptime, so on a `wall`
    # clock the two agree -- which is exactly the case where the old single `uptime_s`
    # looked correct.
    service = ClockService(engine, armed=lambda: armed, subscribers=lambda: subscribers,
                           monotonic=fake)
    return service, engine, fake


def test_rate_change_refused_while_armed():
    """A tick-denominated max_steps means a new rate silently rewrites every timeout."""
    service, engine, _ = _service(armed=True)
    status, body = service.handle("POST", "/api/clock/rate", {"tick_hz": 5.0})
    assert status == 409
    assert "armed" in body["error"]
    assert engine.tick_hz == 1.0


def test_accepted_rate_change_is_recorded():
    """No separate record needed: the next pulse carries the rate that is running."""
    service, engine, fake = _service(armed=False)
    fake.advance(1.0)
    assert service.pulse().payload["tick_hz"] == 1.0

    status, _ = service.handle("POST", "/api/clock/rate", {"tick_hz": 4.0})
    assert status == 200

    fake.advance(0.25)
    pulse = service.pulse()
    assert pulse.payload["tick_hz"] == 4.0
    assert pulse.seq == 2                  # continuous; the rate changed, not the count
    assert pulse.skipped == 0


def test_a_rate_change_does_not_backdate_ticks():
    """Raising the rate must not make the elapsed run retroactively contain more ticks."""
    service, engine, fake = _service(tick_hz=1.0)
    fake.advance(10.0)
    service.pulse()
    assert engine.seq == 10

    service.handle("POST", "/api/clock/rate", {"tick_hz": 100.0})
    assert engine.poll() is None           # the new phase starts now, not at t0
    fake.advance(0.01)
    assert engine.poll().seq == 11


@pytest.mark.parametrize("bad", [{"tick_hz": 0}, {"tick_hz": -1.0}, {"tick_hz": "fast"},
                                 {"tick_hz": None}, {}, None, "5",
                                 {"tick_hz": 1000.1}, {"tick_hz": 1e11},
                                 {"tick_hz": float("inf")}])
def test_an_impossible_rate_is_a_400_not_a_crash(bad):
    service, engine, _ = _service()
    status, body = service.handle("POST", "/api/clock/rate", bad)
    assert status == 400
    assert "error" in body
    assert engine.tick_hz == 1.0


# =============================================================================
# The rate is bounded above, and the boundary tolerance is relative
# =============================================================================

def test_the_rate_is_bounded_above():
    """An absurd rate is reachable through an unauthenticated POST, so it is refused.

    `tick_hz=1e11` used to be accepted: one second of elapsed time then produced
    `seq=100000000100` -- the overshoot being exactly `_EPS/Delta` -- and `_boundary_at`
    walks its correction loop one boundary at a time, so at extreme rates it does not
    finish in useful time.
    """
    assert MAX_TICK_HZ == 1000.0                      # what P2 bounds the descriptor to

    with pytest.raises(ValueError):
        TickEngine(tick_hz=1e11)
    with pytest.raises(ValueError):
        TickEngine(tick_hz=MAX_TICK_HZ + 0.001)
    with pytest.raises(ValueError):
        TickEngine(tick_hz=1.0).set_rate(1e11)

    # The bound itself is allowed, and is a rate the arithmetic is exact at.
    assert TickEngine(tick_hz=MAX_TICK_HZ).tick_hz == MAX_TICK_HZ


def test_the_boundary_tolerance_is_relative_to_the_period():
    """An absolute slack is a bug waiting for a small enough Delta.

    `_boundary_at` accepts a boundary up to the tolerance in the future, so the
    overshoot it can produce is exactly `tolerance/Delta` ticks. Fixed at 1 ns that is
    100 whole ticks at a 10 ps period; relative it is a millionth of a tick at every
    period there is.
    """
    assert tolerance(1.0) == 1e-9                     # unchanged where it always was
    assert tolerance(1e-6) == pytest.approx(1e-12)
    assert tolerance(1e-9) == pytest.approx(1e-15)
    for delta in (100.0, 1.0, 1e-3, 1e-6, 1e-9, 1e-12):
        assert 0.0 < tolerance(delta) <= delta * 1e-6


def test_no_overshoot_at_the_highest_permitted_rate():
    """Exactly N ticks for N periods of elapsed time, with no slack-induced extras."""
    engine, fake = _wall(tick_hz=MAX_TICK_HZ)
    fake.advance(1.0)
    pulse = engine.poll()
    assert pulse.seq == 1000                          # not 1001, and not 100000000100
    assert pulse.t == pytest.approx(1.0)
    assert engine.poll() is None                      # nothing is owed


def test_stepping_is_still_exact_at_the_highest_permitted_rate():
    """The tolerance got smaller; it must still be large enough to not swallow a step.

    This is the failure mode `_EPS` existed for in the first place -- a driven clock
    advanced by Delta a few hundred times lands a few ULPs short of where it aimed.
    """
    engine = TickEngine(ManualClock(), tick_hz=MAX_TICK_HZ)
    for _ in range(400):
        engine.step()
    assert engine.seq == 400
    assert engine.t == pytest.approx(400.0 / MAX_TICK_HZ)


def test_armed_is_what_the_clock_saw_on_the_wire():
    now = FakeWall()
    armed = ArmedTracker(hold_s=5.0, clock=now)
    assert armed() is False

    armed.on_command(api.build_command(command="arm"))
    assert armed() is True
    armed.on_command(api.build_command(command="reset"))
    assert armed() is False

    # A clock restarted mid-episode never saw the arm; a verdict with a step says so.
    armed.on_verdict({"step": 12})
    assert armed() is True
    now.advance(6.0)
    assert armed() is False        # and it expires, so a departed monitor unpins the rate

    armed.on_verdict({"step": None})
    assert armed() is False
    for junk in (None, "arm", [], {"step": None}):
        armed.on_command(junk)
        armed.on_verdict(junk)
    assert armed() is False


# =============================================================================
# The HTTP surface -- policy only; the socket is backend/clock_node.py's
# =============================================================================

def test_api_payload_is_identical_to_topic_payload():
    """`WS /api/clock/stream` and `/monitor/tick` carry the same object, not two copies.

    P6 proxies this and P7 renders it; a stream that re-serialised the clock's state
    would be up to one period out of step with the topic and nothing would say so.
    """
    service, _, fake = _service()
    topic, stream = [], []
    service.subscribe(topic.append)
    service.subscribe(stream.append)

    fake.advance(3.0)
    pulse = service.pulse()
    assert topic == stream == [pulse.payload]
    assert topic[0] is stream[0]


def test_get_clock_is_the_documented_sample():
    service, _, fake = _service(subscribers=2)
    fake.advance(1.0)
    service.pulse()
    state = service.get_state()
    assert set(state) == {"seq", "t", "t0", "tick_hz", "mode", "clock_time_s",
                          "subscribers"}
    assert (state["seq"], state["t"], state["tick_hz"], state["mode"]) == (1, 1.0, 1.0,
                                                                          "wall")
    assert state["subscribers"] == 2

    # A sample, by construction: time moves on and the sample does not, until the pulse.
    fake.advance(0.9)
    assert service.get_state()["seq"] == 1
    assert service.get_state()["clock_time_s"] == pytest.approx(1.9)


def test_engine_time_is_not_called_uptime():
    """A driven clock's engine time is seconds ADVANCED, not seconds since boot.

    Reported as `uptime_s`, sitting in `GET /api/clock/health` next to `t0` and
    `last_pulse_age_s`, a reader takes it for wall uptime -- and a manual clock stepped
    three times during an hour-long debugging session says `3.0`. Health now reports
    both quantities under names that mean what they say, and the gap between them is
    itself the diagnosis.
    """
    wall = FakeWall()
    engine = TickEngine(ManualClock(), tick_hz=1.0, started_at=lambda: 1000.0)
    service = ClockService(engine, monotonic=wall)

    wall.advance(3600.0)                       # an hour of the operator staring at it
    for _ in range(3):
        service.handle("POST", "/api/clock/step", {})

    assert engine.now() == 3.0                 # three ticks is all the clock advanced
    health = service.get_health()
    assert health["clock_time_s"] == pytest.approx(3.0)
    assert health["uptime_s"] == pytest.approx(3600.0)
    # The honest name is on the sample too, and `uptime_s` is not a field of it.
    assert "uptime_s" not in service.get_state()
    assert service.get_state()["clock_time_s"] == pytest.approx(3.0)


def test_on_a_wall_clock_uptime_and_clock_time_agree():
    """Which is why one field looked right: the mode it is wrong for is the driven one."""
    service, _, fake = _service()
    fake.advance(12.0)
    health = service.get_health()
    assert health["uptime_s"] == pytest.approx(health["clock_time_s"]) == 12.0


def test_health_says_whether_anything_consumes_the_pulse():
    """A clock pulsing into an empty graph is healthy by every other measure."""
    lonely, _, _ = _service(subscribers=0)
    assert lonely.get_health()["consumed"] is False
    assert lonely.get_health()["last_pulse_age_s"] is None

    heard, _, fake = _service(subscribers=1)
    fake.advance(1.0)
    heard.pulse()
    fake.advance(0.4)
    health = heard.get_health()
    assert health["consumed"] is True
    assert health["ok"] is True
    assert health["last_pulse_age_s"] == pytest.approx(0.4)


def test_step_over_the_api_advances_the_whole_system_by_one_tick():
    engine = TickEngine(ManualClock(), tick_hz=2.0, started_at=lambda: 1000.0)
    service = ClockService(engine)
    frames = []
    service.subscribe(frames.append)

    status, body = service.handle("POST", "/api/clock/step", {})
    assert status == 200
    assert body == frames[-1] == {"schema_version": api.SCHEMA_VERSION, "seq": 1,
                                  "t": 0.5, "tick_hz": 2.0, "mode": "manual",
                                  "t0": 1000.0}
    assert len(frames) == 1


def test_step_is_refused_on_a_self_advancing_clock():
    service, _, _ = _service()
    status, body = service.handle("POST", "/api/clock/step", {})
    assert status == 409
    assert body["mode"] == "wall"


def test_step_advances_a_replay_clock_too():
    """A deliberate widening of the contract, now written down in docs/api.md.

    `POST /api/clock/step` is accepted on any DRIVEN clock, not `manual` alone: a replay
    driver advances a `ReplayClock` by seconds regardless, and refusing to let it
    advance by exactly one tick would only push the boundary arithmetic -- the one thing
    this module exists to own -- out into every driver.
    """
    engine = TickEngine(ReplayClock(), tick_hz=2.0, started_at=lambda: 1000.0)
    service = ClockService(engine)
    frames = []
    service.subscribe(frames.append)

    status, body = service.handle("POST", "/api/clock/step", {})
    assert status == 200
    assert (body["seq"], body["t"], body["mode"]) == (1, 0.5, "replay")
    assert frames == [body]
    assert api.validate_tick(body) == []

    # And the driver's own advance and an API step share one boundary sequence.
    engine.source.advance(0.5)
    assert engine.poll().seq == 2
    assert service.handle("POST", "/api/clock/step", {})[1]["seq"] == 3


def test_mode_can_be_switched_over_the_api():
    service, engine, fake = _service()
    fake.advance(1.0)
    service.pulse()

    status, body = service.handle("POST", "/api/clock/mode", {"mode": "manual"})
    assert status == 200
    assert body["mode"] == "manual"
    assert body["seq"] == 1                       # the swap does not reset the count
    assert service.handle("POST", "/api/clock/step", None)[0] == 200

    for bad in ({"mode": "sundial"}, {"mode": None}, {}, None, [1]):
        assert service.handle("POST", "/api/clock/mode", bad)[0] == 400
    assert service.handle("POST", "/api/clock/mode",
                          {"mode": "wall", "paused": "yes"})[0] == 400


def test_pausing_over_the_api_stops_the_pulse():
    service, engine, fake = _service()
    assert service.handle("POST", "/api/clock/mode", {"mode": "wall", "paused": True})[0] == 200
    fake.advance(5.0)
    assert service.pulse() is None
    assert service.handle("POST", "/api/clock/mode", {"mode": "wall", "paused": False})[0] == 200
    fake.advance(1.0)
    assert service.pulse().seq == 1


@pytest.mark.parametrize("method,path,status", [
    ("GET", "/api/clock", 200),
    ("GET", "/api/clock/", 200),
    ("GET", "/api/clock/health", 200),
    ("GET", "/api/clock/step", 405),
    ("POST", "/api/clock", 405),
    ("PUT", "/api/clock", 405),
    ("GET", "/api/clocks", 404),
    ("GET", "/", 404),
])
def test_the_router_answers_every_request_with_a_status(method, path, status):
    """Including the wrong ones: a clock that raises on a bad path is a clock that dies."""
    service, _, _ = _service()
    got, body = service.handle(method, path, {})
    assert got == status
    assert isinstance(body, dict)


# =============================================================================
# The node's transport helpers -- pure enough to pin without a socket
# =============================================================================

def test_websocket_handshake_and_framing():
    """RFC 6455's own example key, so the ~30 lines that replace a dependency are pinned."""
    from skill_monitor.backend import clock_node

    assert clock_node.ws_accept("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    assert clock_node.ws_frame(b"hi") == b"\x81\x02hi"
    assert clock_node.ws_frame(b"x" * 200)[:4] == b"\x81\x7e\x00\xc8"
    assert clock_node.ws_frame(b"x" * 70000)[:2] == b"\x81\x7f"


def test_the_compose_flag_spelling_still_parses():
    """deploy/docker-compose.*.yml pass --rate/--source; those files are P8's, not ours."""
    from skill_monitor.backend import clock_node

    args = clock_node.build_parser().parse_args(
        ["--rate", "5.0", "--source", "replay", "--paused"])
    assert (args.tick_hz, args.mode, args.paused) == (5.0, "replay", True)

    documented = clock_node.build_parser().parse_args(["--tick-hz", "5.0", "--mode", "replay"])
    assert (documented.tick_hz, documented.mode) == (5.0, "replay")


def test_the_poll_timer_is_finer_than_the_tick():
    """It decides how promptly a boundary is noticed, and nothing else."""
    from skill_monitor.backend import clock_node

    for tick_hz in (0.1, 1.0, 10.0, 100.0):
        period = clock_node.poll_period(1.0 / tick_hz)
        assert 0.0 < period <= 1.0 / tick_hz
