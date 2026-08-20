"""The monitor's pure half.

What a client can rely on finding in a manifest, that a pushed spec is judged before it
is run, and -- the part `monitor_node` cannot be tested for directly, because it needs
`rclpy` -- that one tick produces exactly one verdict, that the verdict validates
against the contract it claims to implement, and that a failure mode nobody is sure
about does not actuate the robot.
"""

import json

import pytest

import skill_monitor
from skill_monitor.core import api, manifest, spec_contract
from skill_monitor.core.monitor_action import Action


def _spec():
    return json.loads(skill_monitor.spec_path("g1").read_text())


def _verdict(**overrides):
    """A verdict with the boring fields filled in, so each test states only its point."""
    kwargs = dict(
        seq=1041, t=1041.0, step=88,
        skill_name="G1HumanoidNavigation",
        phase="ExecutionAndTracking", phase_index=1,
        formula_statuses=[("full_navigation_sequence", "INCONCLUSIVE")],
        failure_modes=[],
        confidence=1.0,
    )
    kwargs.update(overrides)
    return manifest.build_verdict_payload(**kwargs)


def test_manifest_passes_the_spec_through_unchanged():
    raw = _spec()
    m = manifest.skill_manifest(raw, source="/tmp/formulas_g1.json")
    for k, v in raw.items():
        assert m[k] == v, f"manifest dropped or altered {k}"
    assert m["source"] == "/tmp/formulas_g1.json"
    assert json.loads(json.dumps(m)) == m       # must survive the wire


def test_manifest_names_the_phases_in_order():
    m = manifest.skill_manifest(_spec())
    expected = [p["phase"] for p in _spec()["execution_phases"]]
    assert m["phases"] == expected


def test_phase_names_tolerate_an_unnamed_phase():
    assert manifest.phase_names([{"phase": "A"}, {}]) == ["A", "phase1"]
    assert manifest.phase_names(None) == []


def test_ap_rows_distinguish_false_from_not_evaluated():
    m = {"atomic_propositions": {"a": "desc a", "b": "desc b"}}
    rows = manifest.ap_rows(m, {"ap_values": {"a": False}})
    assert rows == [("a", False, "desc a"), ("b", None, "desc b")]


def test_sensor_rows_come_from_the_adapter_schema():
    adapter = {"schema": {"min_range": {"doc": "metres"}, "nav_state": {"doc": "state"}}}
    rows = manifest.sensor_rows(adapter, {"sensors": {"min_range": 1.5}})
    assert rows == [("min_range", 1.5, "metres"), ("nav_state", None, "state")]

    # A robot with a completely different vocabulary renders with no code change.
    rows = manifest.sensor_rows({"schema": {"gripper_width": {"doc": "m"}}},
                                {"sensors": {"gripper_width": 0.02}})
    assert rows == [("gripper_width", 0.02, "m")]


def test_pushed_spec_is_rejected_for_fields_the_robot_lacks():
    bad = {
        "skill_name": "x",
        "atomic_propositions": {"holding": "True when gripper_force > 1.0. Prose."},
        "ltl_formulas": [{"formula": "G(holding)"}],
    }
    problems = spec_contract.validate(bad, ["min_range", "nav_state"])
    assert any("gripper_force" in p for p in problems)
    # …and accepted once the robot actually provides the field.
    assert spec_contract.validate(bad, ["gripper_force"]) == []


def test_structure_check_runs_without_a_schema():
    # No adapter on the graph yet: still catch a spec that references an AP it never
    # declared, which would silently evaluate as always-false.
    problems = spec_contract.validate_structure({
        "atomic_propositions": {"a": "prose"},
        "ltl_formulas": [{"formula": "G(a & ghost)"}],
    })
    assert any("ghost" in p for p in problems)
    assert spec_contract.validate_structure({}) != []
    assert spec_contract.validate_structure(_spec()) == []


# =============================================================================
# The manifest is `api`'s, not a second copy of it
# =============================================================================

def test_manifest_delegates_to_the_contract_module():
    """P0 reimplemented `skill_manifest`/`phase_names` in `api` rather than importing
    them, to avoid depending on a file another branch was editing. Two copies of "what
    is a phase called" is one too many, so this module now delegates."""
    raw = _spec()
    assert manifest.skill_manifest(raw, "x") == api.build_skill_manifest(spec=raw, source="x")
    assert manifest.phase_names is api.phase_names
    # …and the envelope comes with it, which the hand-rolled copy never carried.
    assert manifest.skill_manifest(raw)["schema_version"] == api.SCHEMA_VERSION


# =============================================================================
# Where the spec comes from  (P8: compose passes a bare name, not a path)
# =============================================================================

def test_a_bare_spec_name_resolves_through_the_config_search_path(tmp_path, monkeypatch):
    """The compose files pass `--formulas-file formulas_g1.json`. Treating that as a
    plain relative path makes a container fail to find a spec it was shipped with."""
    monkeypatch.delenv(skill_monitor.CONFIG_ENV, raising=False)
    skill_monitor.set_config_dir(None)
    assert manifest.resolve_spec_path("formulas_g1.json") == skill_monitor.spec_path("g1")
    assert manifest.resolve_spec_path("g1") == skill_monitor.spec_path("g1")

    # A mounted volume's spec of the same name wins…
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "formulas_g1.json").write_text("{}")
    monkeypatch.setenv(skill_monitor.CONFIG_ENV, str(tmp_path))
    assert manifest.resolve_spec_path("formulas_g1.json") == specs / "formulas_g1.json"

    # …but an explicit path to a real file still wins over the search, so a developer
    # can point at a scratch spec anywhere on disk.
    scratch = tmp_path / "scratch.json"
    scratch.write_text("{}")
    assert manifest.resolve_spec_path(scratch) == scratch


def test_an_unresolvable_spec_name_says_where_it_looked():
    with pytest.raises(FileNotFoundError) as exc:
        manifest.resolve_spec_path("formulas_no_such_robot.json")
    assert "formulas_no_such_robot.json" in str(exc.value)


# =============================================================================
# Exactly one automaton step per tick
# =============================================================================

def test_one_step_per_seq():
    """A redelivered tick must not advance a debounce or a phase counter twice."""
    ledger = manifest.TickLedger()
    assert ledger.admit(10).step is True
    for _ in range(3):
        again = ledger.admit(10)
        assert again.step is False
        assert again.reason == "redelivered"
    assert ledger.admit(11).step is True
    assert ledger.redelivered == 3


def test_a_backwards_seq_within_one_epoch_is_refused_not_replayed():
    """Out of order, i.e. a tick the automaton has already moved past. It cannot be
    applied without rewinding state the automaton has no undo for.

    Within *one* epoch: the same index arriving from a restarted clock is a different
    thing entirely, and the test below says so."""
    ledger = manifest.TickLedger()
    ledger.admit(10, epoch=1000.0)
    ledger.admit(11, epoch=1000.0)
    stale = ledger.admit(9, epoch=1000.0)
    assert stale.step is False and stale.reason == "stale"
    assert ledger.last_seq == 11

    # A clock that never sends `t0` has one epoch forever, and behaves identically.
    plain = manifest.TickLedger()
    plain.admit(10)
    plain.admit(11)
    assert plain.admit(9).reason == "stale"


def test_a_new_epoch_is_adopted_rather_than_refused_forever():
    """The clock container restarts and republishes from 0. Refusing those as stale
    meant zero verdicts for the rest of the monitor's life, and `reset()` kept
    `last_seq` so an operator could not recover it either."""
    ledger = manifest.TickLedger()
    for seq in (197, 198, 199):
        assert ledger.admit(seq, epoch=1000.0).step is True

    restarted = ledger.admit(0, epoch=2000.0)
    assert restarted.step is True
    assert restarted.reason == "epoch"
    assert restarted.missed == 0            # a restart is not 197 missed ticks
    assert ledger.admit(1, epoch=2000.0).step is True
    assert ledger.epochs == 1

    # …and the new epoch is an ordinary stream: backwards within it is stale again.
    assert ledger.admit(0, epoch=2000.0).reason == "stale"


def test_the_epoch_residual_costs_one_tick_and_not_the_rest_of_the_run():
    """The epoch rides `/monitor/tick` and the seq rides `/monitor/observation`, so one
    observation from the old epoch can arrive after the new clock's first pulse. Adopted
    as the high-water mark it refused every genuine tick underneath it: an old epoch that
    reached 5000 cost 5001 consecutive refusals -- about eight minutes of no stepping at
    10 Hz -- and `missed_ticks` stayed 0 throughout, because it only moves on a step."""
    ledger = manifest.TickLedger()
    for seq in range(4998, 5001):
        ledger.admit(seq, epoch=1000.0, clock_seq=seq)

    # The clock restarts. Its first pulse is seq 0; the straggler from the old epoch
    # arrives after it.
    straggler = ledger.admit(5000, epoch=2000.0, clock_seq=0)
    assert straggler.step is False
    assert straggler.reason == "ahead"
    assert ledger.last_seq is None, "the old epoch's index became the new epoch's floor"

    # …and the restarted stream steps from its very next tick.
    stepped = [ledger.admit(seq, epoch=2000.0, clock_seq=seq).step for seq in range(200)]
    assert all(stepped)
    assert ledger.ahead == 1


def test_a_corrupt_seq_is_refused_rather_than_believed_forever():
    """10^6 as a first index is not a tick: adopting it refused every real one after it
    for the life of the process, with nothing in the verdict stream to say why."""
    ledger = manifest.TickLedger()
    assert ledger.admit(10 ** 6, clock_seq=3).reason == "ahead"
    assert ledger.admit(3, clock_seq=3).step is True
    assert ledger.admit(4, clock_seq=4).step is True


def test_without_a_clock_to_check_against_the_ledger_behaves_exactly_as_before():
    """`clock_seq=None` is "no clock on the graph yet", not "seq 0". Bounding against a
    number nobody published would refuse the first observation of every run."""
    ledger = manifest.TickLedger()
    assert ledger.admit(9000).step is True
    assert ledger.last_seq == 9000
    # …and an index equal to the clock's own is a tick that closed, not one ahead.
    at_the_clock = manifest.TickLedger()
    assert at_the_clock.admit(42, clock_seq=42).step is True


def test_the_epoch_is_the_clocks_t0_and_nothing_else():
    """Not a heuristic on the size of the backwards jump: a big jump backwards is
    exactly what a badly delayed redelivery looks like too."""
    assert manifest.tick_epoch({"seq": 1, "t": 1.0, "t0": 1699999999.5}) == 1699999999.5
    assert manifest.tick_epoch({"seq": 1, "t": 1.0}) is None      # P1 has not landed
    assert manifest.tick_epoch({"t0": True}) is None
    assert manifest.tick_epoch({"t0": "recently"}) is None
    assert manifest.tick_epoch(None) is None


def test_a_non_finite_t0_is_no_epoch_at_all():
    """`isinstance(nan, float)` is True and `nan != nan`, so a NaN `t0` read as an epoch
    compares unequal to itself on every later pulse: a clock restart declared every
    tick, `last_seq` dropped every tick, and one-step-per-tick quietly becoming
    one-step-per-message. Reachable, not theoretical: `json.dumps(float("nan"))` emits
    bare `NaN` and `json.loads` accepts it, so an uninitialised `t0` round-trips."""
    assert manifest.tick_epoch(json.loads('{"seq": 1, "t": 1.0, "t0": NaN}')) is None
    assert manifest.tick_epoch({"t0": float("inf")}) is None
    assert manifest.tick_epoch({"t0": float("-inf")}) is None


def test_a_nan_epoch_does_not_readmit_every_redelivery():
    """The consequence, at the ledger. Seven arrivals of five distinct indices -- three
    redeliveries and two backwards jumps among them -- are two steps. Under a NaN epoch
    they were seven, and `redelivered` stayed 0 so nothing in the record said so."""
    nan = manifest.tick_epoch({"t0": float("nan")})
    ledger = manifest.TickLedger()
    stepped = [
        ledger.admit(seq, epoch=nan).step
        for seq in (10, 10, 10, 11, 9, 11, 5)
    ]
    assert sum(stepped) == 2
    assert ledger.redelivered == 5
    assert ledger.epochs == 0


def test_a_field_a_newer_clock_adds_is_not_a_malformed_tick():
    """`api.validate_tick` closes the payload, so any field a later release adds reads as
    an unknown one -- and a monitor that drops the pulse for that reason goes deaf to the
    very clock that would have told it about a restart. `t0` was the worked example until
    P1 landed and made it known; the rule outlives it, so the example moves on."""
    newer = api.build_tick(seq=1, t=1.0, tick_hz=1.0, t0=1000.0) | {"drift_ppm": 12.0}
    assert api.validate_tick(newer) != []                      # the contract says so…
    assert manifest.tick_problems_that_matter(api.validate_tick(newer)) == []

    broken = {"schema_version": 1, "seq": "eleven", "t": 1.0, "tick_hz": 1.0,
              "mode": "wall", "t0": 1000.0}
    assert manifest.tick_problems_that_matter(api.validate_tick(broken)) != []


def test_missed_ticks_are_recorded_not_interpolated():
    """A gap is one number on one verdict, not a burst of catch-up steps."""
    ledger = manifest.TickLedger()
    ledger.admit(100)
    jumped = ledger.admit(104)
    assert jumped.step is True
    assert jumped.missed == 3            # 101, 102, 103
    assert ledger.total_missed == 3
    # One step, not four: the caller is handed a single admission and steps once.
    assert ledger.admit(105).missed == 0
    assert ledger.total_missed == 3


def test_a_payload_with_no_seq_keeps_the_legacy_arrival_behaviour():
    """Legacy `/ltl/evaluations` predates the envelope and carries no tick index. It
    gets the next implicit one, so the un-migrated stack still gets a verdict."""
    ledger = manifest.TickLedger()
    assert [ledger.admit(None).seq for _ in range(3)] == [0, 1, 2]
    assert ledger.admit(None).reason == "implicit"
    # `True` is an int in Python and is a bug where a seq belongs, not a tick index.
    assert manifest.TickLedger().admit(True).reason == "implicit"


def test_a_fabricated_index_does_not_make_the_next_real_one_look_redelivered():
    """A ledger that has seen both. The implicit index used to be `last_seq + 1` and to
    *write* `last_seq`, so one legacy copy of tick N fabricated N+1 and the real
    envelope for tick N+1 then arrived looking redelivered -- two live wires, and only
    the fabricated one advancing."""
    ledger = manifest.TickLedger()
    assert ledger.admit(7).step is True
    assert ledger.admit(None).seq == 0            # its own counter, not 8
    assert ledger.admit(8).step is True           # …and the real stream is untouched
    assert ledger.last_seq == 8
    assert ledger.implicit == 1


def test_a_reset_does_not_make_a_stale_redelivery_look_fresh():
    """The episode restarts; the global tick stream does not restart with it. A clock
    that genuinely restarted says so with a new epoch, which is a different thing."""
    ledger = manifest.TickLedger()
    ledger.admit(50, epoch=1000.0)
    ledger.reset()
    assert ledger.admit(50, epoch=1000.0).step is False
    assert ledger.admit(51, epoch=2000.0).step is True


def test_a_reset_clears_every_number_it_says_it_clears():
    """`total_missed` is documented as "every gap since the ledger was reset"; a
    run-level number that survives its run is read by somebody as this run's."""
    ledger = manifest.TickLedger()
    ledger.admit(1)
    ledger.admit(5)          # 3 missed
    ledger.admit(5)          # redelivered
    ledger.admit(None)       # implicit
    assert (ledger.total_missed, ledger.redelivered, ledger.implicit) == (3, 1, 1)
    ledger.reset()
    assert (ledger.missed, ledger.total_missed, ledger.redelivered, ledger.implicit) \
        == (0, 0, 0, 0)
    assert ledger.last_seq == 5      # …but not the ones it says it keeps


# =============================================================================
# One observation, either wire
# =============================================================================

def test_an_observation_reads_the_same_off_either_wire():
    modern = manifest.normalize_observation({
        "schema_version": 1, "seq": 7, "t": 7.0, "step": 3,
        "clock": "external", "tick_membership": "arrival",
        "sensors": {"min_range": 0.42},
        "ap_values": {"path_active": True, "collision_risk": False},
        "unknown_aps": ["blocked"],
        "confidence": 0.5,
        "data_health": {
            "points": {"refreshed": True}, "status": {"refreshed": False},
        },
    })
    assert modern.ap_values == {"path_active": True, "collision_risk": False}
    assert modern.sensors == {"min_range": 0.42}
    assert modern.seq == 7 and modern.step == 3 and modern.confidence == 0.5
    assert modern.stale_sources == ("status",)   # derived from data_health.refreshed
    assert modern.unknown_aps == ("blocked",)
    assert modern.legacy is False

    legacy = manifest.normalize_observation({
        "path_active": True, "collision_risk": False,
        "__sensors__": {"min_range": 0.42},
        "__confidence__": 0.5,
        "__stale__": ["status"],
    })
    assert legacy.ap_values == modern.ap_values
    assert legacy.sensors == modern.sensors
    assert legacy.confidence == modern.confidence
    assert legacy.stale_sources == modern.stale_sources
    assert legacy.seq is None and legacy.legacy is True


def test_reserved_keys_never_reach_the_automaton():
    """`__done__` and friends are metadata about the observation, not part of it: a
    phase guard's eval namespace must never see them."""
    obs = manifest.normalize_observation({"a": True, "__done__": True, "__reset__": True})
    assert obs.ap_values == {"a": True}
    assert obs.control == "done"        # done outranks reset
    assert manifest.normalize_observation({"__reset__": True}).control == "reset"
    assert manifest.normalize_observation("nonsense") is None
    assert manifest.normalize_observation(None) is None


def test_an_out_of_range_confidence_is_clamped_not_propagated():
    """`api.UNIT_INTERVAL` rejects 1.2, and a verdict that fails its own validator
    because a producer sent a stray number is the worse outcome."""
    assert manifest.normalize_observation({"__confidence__": 1.7}).confidence == 1.0
    assert manifest.normalize_observation({"__confidence__": -3}).confidence == 0.0
    assert manifest.normalize_observation({"__confidence__": "nan-ish"}).confidence == 1.0


# =============================================================================
# The verdict
# =============================================================================

def test_verdict_validates_against_api_schema():
    """The monitor's own payload, judged by the contract it claims to implement."""
    assert api.validate_verdict(_verdict()) == []
    # …in every shape the node can produce: idle, mid-phase, and terminal.
    assert api.validate_verdict(_verdict(
        phase=None, phase_index=None, formula_statuses=[], has_data=False,
    )) == []
    assert api.validate_verdict(_verdict(
        terminal="SUCCESS", missed_ticks=4, steps_to_timeout=0,
        violations_to_fault=1, violations_seen=2, stale_sources=["status"],
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
        confidence=0.2,
    )) == []


def test_verdict_carries_confidence_on_every_failure_mode():
    """Required, not optional. Without it a VIOLATED derived from a dead sensor grades
    at 1.0 and the intervention ladder goes straight to ABORT."""
    v = _verdict(
        confidence=0.4,
        failure_modes=[
            {"name": "fell_over", "fault_category": "SAFETY", "status": "VIOLATED"},
            {"name": "wandered", "fault_category": "PROGRESS", "status": "INCONCLUSIVE"},
        ],
    )
    assert [fm["confidence"] for fm in v["failure_modes"]] == [0.4, 0.4]
    assert all("confidence" in fm for fm in v["failure_modes"])


def test_low_confidence_safety_violation_grades_below_abort():
    """The live bug this closes: a `fell_over` derived from a sensor that stopped
    publishing used to grade at full confidence and abort the mission."""
    dead_sensor = _verdict(
        confidence=0.2, stale_sources=["imu"],
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert dead_sensor["intervention"]["action"] == "WARN"
    assert Action[dead_sensor["intervention"]["action"]] < Action.HALT

    # Safety is not softened away, only de-escalated while the evidence is weak: the
    # same fault on fresh data still aborts.
    live_sensor = _verdict(
        confidence=1.0,
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert live_sensor["intervention"]["action"] == "ABORT"


# =============================================================================
# Confidence is per failure mode, not one number for all of them
# =============================================================================

def _adapter():
    """Three required sources. `battery` feeds no AP any spec here mentions."""
    return api.build_adapter(
        adapter="test_robot", doc="", tick_hz=1.0,
        schema={"min_range": {}, "upright_flag": {}, "battery_v": {}},
        sources=[
            {"id": "points", "topic": "/p", "type": "T", "expected_hz": 15.0,
             "max_age_s": 0.5, "required": True, "tracked": True,
             "keys": ["min_range"], "steps": []},
            {"id": "odom", "topic": "/o", "type": "T", "expected_hz": 50.0,
             "max_age_s": 0.5, "required": True, "tracked": True, "keys": [],
             "steps": [{"keys": ["upright_flag"], "aggregate": "last", "on": "message"}]},
            {"id": "battery", "topic": "/b", "type": "T", "expected_hz": 1.0,
             "max_age_s": 5.0, "required": True, "tracked": True,
             "keys": ["battery_v"], "steps": []},
        ],
    )


_APS = {
    "collision_risk": "True when min_range < 0.25. An obstacle is too close.",
    "upright": "True when upright_flag > 0.5. The base is standing.",
    "llm_judged": "The scene looks like the goal.",     # no rule: LLM-evaluated
}


def test_an_ap_maps_to_the_sources_its_rule_actually_reads():
    ap_map = manifest.ap_source_map(_APS, _adapter())
    assert ap_map["collision_risk"] == frozenset({"points"})
    # Derived key: `upright_flag` is named only by a step, and a lookup that read the
    # source's top-level `keys` would map it to nothing, i.e. to permanently fresh.
    assert ap_map["upright"] == frozenset({"odom"})
    # An LLM-evaluated AP is handed the whole sensor dict, so it depends on every
    # source. Mapping it to "no sources" is exactly backwards.
    assert ap_map["llm_judged"] == frozenset({"points", "odom", "battery"})
    # No adapter announced: nothing to map against, and the caller is told so.
    assert manifest.ap_source_map(_APS, {}) is None


def test_a_quiet_source_only_de_escalates_the_modes_that_read_it():
    """One global scalar -- the fraction of *all* required sources fresh -- stamped on
    every entry meant a quiet battery topic dragged a perfectly-evidenced
    `collision_imminent` under `min_confidence`, so a real collision graded WARN
    instead of HALT and the supervisor did not zero /cmd_vel."""
    ap_map = manifest.ap_source_map(_APS, _adapter())
    mode_sources = manifest.expression_source_map(
        {"collision_imminent": "G(!collision_risk)", "fell_over": "G(upright)"}, ap_map
    )
    v = _verdict(
        confidence=0.34, stale_sources=["battery"], mode_sources=mode_sources,
        failure_modes=[
            {"name": "collision_imminent", "fault_category": "SAFETY",
             "status": "VIOLATED"},
            {"name": "fell_over", "fault_category": "SAFETY", "status": "INCONCLUSIVE"},
        ],
    )
    assert [fm["confidence"] for fm in v["failure_modes"]] == [1.0, 1.0]
    assert v["intervention"]["action"] == "ABORT"

    # …and the same fault on its own dead sensor is still de-escalated.
    blind = _verdict(
        confidence=0.34, stale_sources=["points"], mode_sources=mode_sources,
        failure_modes=[{"name": "collision_imminent", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert blind["failure_modes"][0]["confidence"] == 0.0
    assert blind["intervention"]["action"] == "WARN"


def test_with_no_map_the_global_scalar_is_the_documented_fallback():
    """No adapter has announced itself, so nothing says which source feeds which AP."""
    v = _verdict(
        confidence=0.4, mode_sources=None,
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert v["failure_modes"][0]["confidence"] == 0.4

    # A mode a map does not cover falls back the same way: "its expression named no AP
    # I know" is ignorance, not freshness.
    v = _verdict(
        confidence=0.4, mode_sources={"other": frozenset()},
        failure_modes=[{"name": "fell_over", "fault_category": "SAFETY",
                        "status": "VIOLATED"}],
    )
    assert v["failure_modes"][0]["confidence"] == 0.4


def test_a_fault_graded_below_halt_only_by_confidence_does_not_stop_the_run():
    """The node's `_halt()` and the token it publishes must be one decision."""
    sure = {"fault_category": "SAFETY", "confidence": 1.0}
    unsure = {"fault_category": "SAFETY", "confidence": 0.2}
    assert manifest.fault_stops_the_run(sure) is True
    assert manifest.fault_stops_the_run(unsure) is False

    # A fault the ladder never takes to HALT at any confidence is a different case:
    # "this episode is over" is not "stop the robot", and the phase machine's
    # termination contract predates this PR.
    assert manifest.fault_stops_the_run(
        {"fault_category": "TIMEOUT", "confidence": 1.0}
    ) is True
    assert manifest.fault_stops_the_run(
        {"fault_category": "PROGRESS", "confidence": 0.1}
    ) is True


def test_the_intervention_token_ships_in_the_verdict():
    """The monitor decides the rung; the supervisor only enforces. A verdict with no
    token would leave the decision in the actuator, and unlogged."""
    quiet = _verdict()
    assert quiet["intervention"]["action"] == "CONTINUE"
    assert quiet["intervention"]["category"] is None

    # A phase about to time out is a pre-emptive rung, before any hard fault.
    soon = _verdict(steps_to_timeout=2, violations_to_fault=3, confidence=0.9)
    assert soon["risk"]["severity"] == "TIMEOUT"
    assert soon["intervention"]["action"] == "REPLAN"
    assert soon["intervention"]["imminence"] == "2 steps"
    assert soon["intervention"]["confidence"] == 0.9


def test_a_mode_named_after_a_severity_does_not_hijack_the_evidence():
    """`decision.reason` is a failure mode's *name* on one branch and a severity string
    on the other, so matching it against mode names let a mode literally named "TIMEOUT"
    supply the `imminence` and `confidence` of a risk-branch decision -- the right rung
    beside the wrong evidence."""
    v = _verdict(
        steps_to_timeout=2, violations_to_fault=3, confidence=0.9,
        failure_modes=[{"name": "TIMEOUT", "fault_category": "PROGRESS",
                        "status": "INCONCLUSIVE"}],
    )
    assert v["risk"]["severity"] == "TIMEOUT"          # the risk branch fired…
    assert v["intervention"]["imminence"] == "2 steps"  # …so the evidence is the risk's
    assert v["intervention"]["confidence"] == 0.9

    # And the branch is picked by the same rule `decide_intervention` uses.
    modes = [
        {"name": "wandered", "fault_category": "PROGRESS", "status": "VIOLATED"},
        {"name": "fell_over", "fault_category": "SAFETY", "status": "VIOLATED"},
    ]
    assert manifest.breached_mode(modes)["name"] == "fell_over"   # safety is preferred
    assert manifest.breached_mode(modes[:1])["name"] == "wandered"


def test_the_imminence_is_read_off_the_bound_the_severity_names():
    """`steps_to_timeout` and `violations_to_fault` count unrelated things, so reporting
    the first one that happens to be set put the timeout's horizon beside a PROGRESS
    severity: a fault two violations away, published as a hundred steps of headroom."""
    v = _verdict(steps_to_timeout=100, violations_to_fault=2, violations_seen=1)
    assert v["risk"]["severity"] == "PROGRESS"       # progress is what is going wrong…
    assert v["intervention"]["imminence"] == "2 steps"   # …so that is the count reported

    # The timeout branch still reads its own bound, and outranks progress when both warn.
    both = _verdict(steps_to_timeout=2, violations_to_fault=1, violations_seen=1)
    assert both["risk"]["severity"] == "TIMEOUT"
    assert both["intervention"]["imminence"] == "2 steps"

    # No bound is warning, so there is no imminence to report -- not the raw countdown.
    quiet = _verdict(steps_to_timeout=100, violations_to_fault=90, violations_seen=1)
    assert quiet["risk"]["severity"] is None
    assert quiet["intervention"]["imminence"] is None
    assert manifest.breached_mode([]) is None
    assert manifest.breached_mode(
        [{"name": "x", "fault_category": "SAFETY", "status": "INCONCLUSIVE"}]
    ) is None


def _two_safety_breaches():
    """The shipped situation: one mode read by a dead source, one by a fresh source."""
    mode_sources = manifest.expression_source_map(
        {"collision_imminent": "G(!collision_risk)", "fell_over": "G(upright)"},
        manifest.ap_source_map(_APS, _adapter()),
    )
    blind = {"name": "collision_imminent", "fault_category": "SAFETY",
             "status": "VIOLATED"}                      # reads `points`, which is dead
    proven = {"name": "fell_over", "fault_category": "SAFETY",
              "status": "VIOLATED"}                     # reads `odom`, which is fresh
    return mode_sources, blind, proven


def test_a_breach_on_a_dead_sensor_does_not_grade_the_one_the_evidence_proves():
    """Same tick, same facts: the depth camera is dead so `collision_imminent` grades
    0.0, the IMU is fresh so `fell_over` is proven at 1.0. The token was graded from
    whichever was authored first, so in `formulas_g1.json`'s own order the unbelievable
    mode masked the proven one and a robot on the floor was published as WARN -- the
    supervisor obeys the token and nothing else, so it would not have stopped."""
    mode_sources, blind, proven = _two_safety_breaches()
    for order in ([blind, proven], [proven, blind]):
        v = _verdict(confidence=0.5, stale_sources=["points"],
                     mode_sources=mode_sources, failure_modes=order)
        assert [fm["confidence"] for fm in v["failure_modes"]] == (
            [0.0, 1.0] if order[0] is blind else [1.0, 0.0]
        )
        assert v["intervention"]["action"] == "ABORT", "list position decided the rung"
        assert v["intervention"]["confidence"] == 1.0

    # The de-escalation itself is untouched: a lone breach on its own dead sensor is
    # still held back, because nothing else is violated to outrank it.
    lone = _verdict(confidence=0.5, stale_sources=["points"],
                    mode_sources=mode_sources, failure_modes=[blind])
    assert lone["intervention"]["action"] == "WARN"


def test_the_breach_that_is_named_is_the_breach_the_rung_was_graded_from():
    """`intervention_block` reports the evidence and `decide_intervention` grades the
    rung. If they pick different entries the token states one fault's rung beside
    another fault's confidence, and the record cannot be read back.

    A de-escalated SAFETY breach beside a VIOLATED PROGRESS one is where they come
    apart: safety-first names the first, the ladder grades the second higher (REPLAN
    over WARN), and no reordering of the list can make first-match agree."""
    mode_sources = manifest.expression_source_map(
        {"collision_imminent": "G(!collision_risk)", "wandered": "G(upright)"},
        manifest.ap_source_map(_APS, _adapter()),
    )
    modes = [
        {"name": "collision_imminent", "fault_category": "SAFETY",
         "status": "VIOLATED"},
        {"name": "wandered", "fault_category": "PROGRESS", "status": "VIOLATED"},
    ]
    v = _verdict(confidence=0.5, stale_sources=["points"],
                 mode_sources=mode_sources, failure_modes=modes)
    named = manifest.breached_mode(v["failure_modes"])
    assert named["name"] == "wandered"
    assert v["intervention"]["action"] == "REPLAN"
    assert v["intervention"]["category"] == named["fault_category"]
    assert v["intervention"]["confidence"] == named["confidence"] == 1.0


def test_ties_on_the_ladder_keep_the_safety_first_then_authored_order():
    """Worst-of is the rule; the old precedence is what breaks the tie, so the same
    facts pick the same entry on every run and an operator can say why."""
    modes = [
        {"name": "wandered", "fault_category": "PROGRESS", "status": "VIOLATED"},
        {"name": "stalled", "fault_category": "TIMEOUT", "status": "VIOLATED"},
    ]
    assert manifest.breached_mode(modes)["name"] == "wandered"   # both REPLAN: authored
    safety_too = modes + [{"name": "shaky", "fault_category": "SAFETY",
                           "status": "VIOLATED", "confidence": 0.1}]
    # …and a SAFETY mode too unsure to outrank them does not win on being SAFETY.
    assert manifest.breached_mode(safety_too)["name"] == "wandered"


def test_seconds_to_timeout_accompanies_steps_to_timeout():
    """Beside, never replacing: spec bounds stay tick-denominated until P11 and a
    consumer asserting on the existing field has to keep working."""
    at_1hz = _verdict(steps_to_timeout=32, tick_hz=1.0)["risk"]
    assert at_1hz["steps_to_timeout"] == 32
    assert at_1hz["seconds_to_timeout"] == 32.0

    # The same 32-tick budget is 6.4 seconds at 5 Hz — which is exactly why the two
    # numbers travel together rather than one being derived at the consumer.
    at_5hz = _verdict(steps_to_timeout=32, tick_hz=5.0)["risk"]
    assert at_5hz["steps_to_timeout"] == 32
    assert at_5hz["seconds_to_timeout"] == pytest.approx(6.4)

    no_bound = _verdict()["risk"]
    assert no_bound["steps_to_timeout"] is None
    assert no_bound["seconds_to_timeout"] is None


def test_missed_ticks_travel_on_the_verdict():
    assert _verdict()["missed_ticks"] == 0
    assert _verdict(missed_ticks=7)["missed_ticks"] == 7


# =============================================================================
# The two INCONCLUSIVEs are different axes
# =============================================================================

def test_no_data_is_a_different_axis_from_a_formula_being_inconclusive():
    """`MonitorStatus` is deliberately not extended. "The prefix neither proves nor
    refutes" is the normal state of a healthy run; "nothing arrived" is a statement
    about the sensors. Both travel, in different fields."""
    healthy = _verdict(has_data=True)
    assert healthy["verdict"] == "UNDECIDED"
    assert healthy["formulas"][0]["status"] == "INCONCLUSIVE"

    silent = _verdict(has_data=False)
    assert silent["verdict"] == "INCONCLUSIVE_NO_DATA"
    assert silent["formulas"][0]["status"] == "INCONCLUSIVE"   # unchanged by the silence
    assert set(api.FORMULA_STATUSES).isdisjoint({"INCONCLUSIVE_NO_DATA"})


def test_a_proven_violation_outranks_a_silent_tick():
    """It is already proven, and a later absence of data does not unprove it."""
    v = _verdict(has_data=False, formula_statuses=[("nav", "VIOLATED")])
    assert v["verdict"] == "VIOLATED"


def test_all_property_formulas_accepted_is_satisfied():
    v = _verdict(formula_statuses=[("a", "ACCEPTED"), ("b", "ACCEPTED")])
    assert v["verdict"] == "SATISFIED"
    # One straggler is enough to keep it undecided.
    assert _verdict(
        formula_statuses=[("a", "ACCEPTED"), ("b", "INCONCLUSIVE")]
    )["verdict"] == "UNDECIDED"


# =============================================================================
# Closed vocabularies
# =============================================================================

def test_an_authored_fault_category_is_mapped_onto_the_closed_vocabulary():
    """`fault_category` is closed on the wire, and specs author more names than it
    holds -- the shipped G1 spec has a `precondition_fault_category` of "NONE"."""
    assert manifest.wire_fault_category("SAFETY") == "SAFETY"
    assert manifest.wire_fault_category("precondition") == "INVARIANT"
    assert manifest.wire_fault_category("NONE") is None
    assert manifest.wire_fault_category(None) is None
    assert manifest.wire_fault_category("WEIRD") == manifest.UNCLASSIFIED_CATEGORY
    assert manifest.UNCLASSIFIED_CATEGORY in api.FAULT_CATEGORIES


def test_a_category_this_build_cannot_grade_never_stops_the_robot():
    """A spec typo used to become INVARIANT, i.e. ABORT, where pre-PR it graded WARN --
    and `build_failure_mode_infos` defaults a missing field to "UNKNOWN", so it fired on
    any spec that omits it at all. `core/automata.py` documents "NAVIGATION" as an
    example category, so an unenumerated name is an expected input."""
    for authored in ("SAFTEY", "NAVIGATION", "UNKNOWN"):
        v = _verdict(failure_modes=[
            {"name": "x", "fault_category": authored, "status": "VIOLATED"},
        ])
        assert api.validate_verdict(v) == []
        assert v["failure_modes"][0]["fault_category"] == manifest.UNCLASSIFIED_CATEGORY
        assert Action[v["intervention"]["action"]] < Action.HALT

    # PRECONDITION is a real alias, not an unrecognised name: a precondition that did
    # not hold on entry is the world not being as the spec required.
    v = _verdict(failure_modes=[
        {"name": "pre", "fault_category": "PRECONDITION", "status": "VIOLATED"},
    ])
    assert v["failure_modes"][0]["fault_category"] == "INVARIANT"
    assert v["intervention"]["action"] == "ABORT"


def test_an_unrecognised_category_is_reported_where_the_author_can_see_it():
    """The rung is deliberately mild, so the loudness has to be at load time."""
    problems = manifest.fault_category_problems({
        "named_failure_modes": [{"name": "fell_over", "fault_category": "SAFTEY"}],
        "execution_phases": [{"phase": "Approach",
                              "invariant_fault_category": "NAVIGATION"}],
    })
    assert any("SAFTEY" in p and "fell_over" in p for p in problems)
    assert any("NAVIGATION" in p and "Approach" in p for p in problems)

    # A missing category is the same defect wearing "UNKNOWN".
    assert manifest.fault_category_problems(
        {"named_failure_modes": [{"name": "wandered", "formula": "G(x)"}]}
    ) != []

    # The shipped spec is clean, "NONE" and all.
    assert manifest.fault_category_problems(_spec()) == []
    assert manifest.fault_category_problems({}) == []
    assert manifest.fault_category_problems(None) == []


def test_none_ships_as_null_only_where_the_wire_has_a_null():
    """`verdict.intervention.category` is nullable and
    `verdict.failure_modes[].fault_category` is not, so "NONE" cannot mean the same
    thing in both places -- and claiming it did was wrong end to end."""
    assert manifest.wire_fault_category("NONE") is None
    assert _verdict()["intervention"]["category"] is None
    on_a_mode = _verdict(failure_modes=[
        {"name": "x", "fault_category": "NONE", "status": "INCONCLUSIVE"},
    ])["failure_modes"][0]
    assert on_a_mode["fault_category"] == manifest.UNCLASSIFIED_CATEGORY
    assert api.validate_verdict(_verdict(failure_modes=[
        {"name": "x", "fault_category": "NONE", "status": "INCONCLUSIVE"},
    ])) == []


def test_the_ladder_horizon_is_not_two_numbers():
    """One definition of the horizon, not a fourth literal `3` in this module.

    Read off `grade_action.__kwdefaults__` this used to be an import-time landmine:
    `__kwdefaults__` is None for a function with no keyword-only defaults, so moving
    that parameter in front of the `*` raised TypeError while *importing* this module.
    `inspect.signature` here rather than there: a red test is the right failure, an
    unimportable package is not.
    """
    import inspect

    from skill_monitor.core.monitor_action import grade_action

    defaults = inspect.signature(grade_action).parameters
    assert manifest.WARN_STEPS == defaults["warn_steps"].default
    assert manifest.MIN_CONFIDENCE == defaults["min_confidence"].default

    # The landmine itself: moving the parameter in front of the `*` is a refactor that
    # changes nothing about the ladder, and `__kwdefaults__` is None for the result.
    def moved(category, *, imminence=None):
        return category

    def moved_again(category, warn_steps=3):
        return category

    assert moved.__kwdefaults__ is not None
    assert moved_again.__kwdefaults__ is None
    with pytest.raises(TypeError):
        moved_again.__kwdefaults__["warn_steps"]      # what import used to do
    assert inspect.signature(moved_again).parameters["warn_steps"].default == 3
