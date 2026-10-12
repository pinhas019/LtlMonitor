"""episode_record — the one shape every paper table is computed from. Pure, no ROS."""

import json

import pytest

from skill_monitor.core import episode_record as er


def _record(**overrides):
    base = dict(
        episode_id="ep-0", arm="full", seed=3, scenario="clear",
        terminal=True, success=True, cause="reached_goal", elapsed_s=12.5,
    )
    base.update(overrides)
    return er.build_record(**base)


def test_a_built_record_is_valid_and_carries_every_field():
    rec = _record()
    assert er.validate_record(rec) == []
    assert set(rec) == set(er.FIELDS)
    assert rec["schema_version"] == er.SCHEMA_VERSION


def test_an_unknown_field_is_a_problem_so_a_typo_cannot_drop_out_of_the_analysis():
    rec = _record()
    rec["sucess"] = True
    assert any("unknown field 'sucess'" in p for p in er.validate_record(rec))


def test_a_missing_field_is_a_problem():
    rec = _record()
    del rec["arm"]
    assert "missing field 'arm'" in er.validate_record(rec)


@pytest.mark.parametrize("field,value", [
    ("seed", 1.5), ("seed", True), ("terminal", "yes"), ("elapsed_s", -1.0),
    ("elapsed_s", float("nan")), ("steps", -2), ("detected_tick", 2.0),
    ("policy", "panic"), ("recoveries", -1), ("recoveries", None),
    ("arm", 7), ("timing", []),
])
def test_wrongly_typed_fields_are_rejected(field, value):
    rec = _record()
    rec[field] = value
    assert er.validate_record(rec)


def test_success_requires_a_terminal_episode():
    problems = er.validate_record(_record(terminal=False, success=True))
    assert "a non-terminal episode cannot be a success" in problems


def test_a_fault_records_its_injection_independently_of_the_monitor():
    fault = er.build_fault(type="push", onset_s=4.0, injected_tick=4, injected_t=4.02,
                           params={"force_n": 300})
    rec = _record(faults=[fault], success=False, cause="fell_over", detected_tick=6)
    assert er.validate_record(rec) == []
    assert rec["faults"][0]["injected_tick"] == 4


def test_a_scheduled_fault_that_never_fired_is_still_valid():
    rec = _record(faults=[er.build_fault(type="push", onset_s=30.0)])
    assert er.validate_record(rec) == []


@pytest.mark.parametrize("fault", [
    "push",
    {"type": "", "onset_s": 1.0, "injected_tick": None, "injected_t": None, "params": {}},
    {"type": "push", "onset_s": -1, "injected_tick": None, "injected_t": None, "params": {}},
    {"type": "push", "onset_s": 1.0, "injected_tick": 1.5, "injected_t": None, "params": {}},
    {"type": "push", "onset_s": 1.0, "injected_tick": None, "injected_t": None,
     "params": {}, "extra": 1},
])
def test_malformed_faults_are_reported_with_their_index(fault):
    problems = er.validate_record(_record(faults=[fault]))
    assert problems and all(p.startswith("faults[0]") for p in problems)


def test_time_to_detection_counts_from_the_earliest_injection():
    faults = [er.build_fault(type="slip", onset_s=8, injected_tick=8),
              er.build_fault(type="push", onset_s=5, injected_tick=5)]
    assert er.time_to_detection(_record(faults=faults, detected_tick=7)) == 2


def test_a_detection_before_any_injection_is_negative_so_it_reads_as_a_false_alarm():
    faults = [er.build_fault(type="push", onset_s=5, injected_tick=5)]
    assert er.time_to_detection(_record(faults=faults, detected_tick=2)) == -3


@pytest.mark.parametrize("faults,detected", [
    ([], 4),
    ([er.build_fault(type="push", onset_s=5)], 4),
    ([er.build_fault(type="push", onset_s=5, injected_tick=5)], None),
])
def test_time_to_detection_is_none_without_both_ends(faults, detected):
    assert er.time_to_detection(_record(faults=faults, detected_tick=detected)) is None


def test_records_round_trip_through_json_lines(tmp_path):
    path = tmp_path / "episodes.jsonl"
    first, second = _record(episode_id="a"), _record(episode_id="b", seed=4)
    er.write_record(path, first)
    er.write_record(path, second)
    assert list(er.read_records(path)) == [first, second]
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def test_an_invalid_record_is_refused_rather_than_written(tmp_path):
    path = tmp_path / "episodes.jsonl"
    with pytest.raises(ValueError, match="invalid episode record"):
        er.write_record(path, _record(seed="three"))
    assert not path.exists()
