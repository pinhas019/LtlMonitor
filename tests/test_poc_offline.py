"""The offline proof of concept: flat goal formula vs phase ladder on the same frames."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "poc_offline", Path(__file__).resolve().parents[1] / "tools" / "poc_offline.py")
poc = importlib.util.module_from_spec(_spec)
sys.modules["poc_offline"] = poc   # dataclasses resolves annotations via sys.modules
_spec.loader.exec_module(poc)


def _result():
    return poc.evaluate(poc.synth_dataset(seed=0))


def test_flat_goal_never_reports_a_failure():
    r = _result()["arms"]["B1 flat"]
    assert r["detection_rate"] == 0.0 and r["false_alarm_rate"] == 0.0


def test_ladder_detects_every_stall_and_names_the_phase():
    r = _result()["arms"]["C  phase ladder"]
    assert r["detection_rate"] == 1.0
    assert all(name.startswith("phase:") for name in r["faults"])


def test_ladder_is_faster_than_a_single_mission_deadline():
    arms = _result()["arms"]
    assert arms["C  phase ladder"]["median_delay"] < arms["B2 flat + mission deadline"]["median_delay"]


def test_conformal_quantile_is_an_upper_order_statistic():
    assert poc.conformal_quantile(list(range(1, 21)), 0.1) == 19
    assert poc.conformal_quantile([5, 1, 3], 0.01) == 5


def test_a_successful_episode_completes_the_ladder():
    rows, onset = poc.synth_episode(__import__("random").Random(1), "success")
    v = poc.run_ladder(poc.to_aps(rows), {n: 10**6 for n, _, _ in poc.PHASES}, budget=10**6)
    assert onset == -1 and v.completed and v.fault is None
