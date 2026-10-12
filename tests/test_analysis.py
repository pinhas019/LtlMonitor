"""The statistics behind the paper's table: checked against reference values, and the
per-episode detection scoring against the cases that are easy to get wrong."""

from __future__ import annotations

import json

import pytest

from skill_monitor.core import analysis, episode_record

from tools import analyze_episodes


def rec(*, arm="full", policy="detect", scenario="weaken_000", success=True,
        injected_tick=None, detected_tick=None, recoveries=0, i=0):
    faults = []
    if injected_tick is not None:
        faults = [episode_record.build_fault(type="weaken", onset_s=4.0,
                                             injected_tick=injected_tick,
                                             injected_t=float(injected_tick))]
    return episode_record.build_record(
        episode_id=f"e{i}", arm=arm, policy=policy, seed=0, scenario=scenario,
        faults=faults, terminal=True, success=success,
        cause="reached_goal" if success else "fell", elapsed_s=1.0,
        detected_tick=detected_tick, recoveries=recoveries)


# =============================================================================
# Reference values
# =============================================================================

@pytest.mark.parametrize("table,p", [
    ((8, 2, 1, 5), 0.034965),           # R: fisher.test(matrix(c(8,1,2,5), 2))
    ((1, 9, 11, 3), 0.0027594),         # the tea-tasting-sized classic, SciPy
    ((3, 1, 1, 3), 0.48571),
    ((5, 5, 5, 5), 1.0),
    ((0, 0, 0, 0), 1.0),
])
def test_fisher_exact_matches_reference_implementations(table, p):
    assert analysis.fisher_exact(*table) == pytest.approx(p, rel=1e-4)


@pytest.mark.parametrize("k,n,lo,hi", [
    (5, 10, 0.236593, 0.763407),
    (0, 10, 0.0, 0.277533),
    (10, 10, 0.722467, 1.0),
    (0, 0, 0.0, 1.0),
])
def test_wilson_matches_reference_values(k, n, lo, hi):
    got = analysis.wilson(k, n)
    assert got[0] == pytest.approx(lo, abs=1e-5) and got[1] == pytest.approx(hi, abs=1e-5)


def test_the_bootstrap_is_seeded_and_brackets_the_true_difference():
    xs, ys = [1] * 18 + [0] * 2, [1] * 8 + [0] * 12
    first = analysis.bootstrap_diff(xs, ys, seed=3)
    assert first == analysis.bootstrap_diff(xs, ys, seed=3)
    assert first[0] < 0.5 < first[1]
    assert first[0] > 0                              # 90% vs 40% is not noise at n=20


# =============================================================================
# Detection scoring
# =============================================================================

@pytest.mark.parametrize("injected,detected,expect", [
    (None, None, dict(faulty=False, tp=False, fp=False, fn=False, ttd=None)),  # clean
    (None, 5, dict(faulty=False, tp=False, fp=True, fn=False, ttd=None)),      # alarm
    (4, None, dict(faulty=True, tp=False, fp=False, fn=True, ttd=None)),       # missed
    (4, 7, dict(faulty=True, tp=True, fp=False, fn=False, ttd=3)),             # caught
    (4, 4, dict(faulty=True, tp=True, fp=False, fn=False, ttd=0)),
    (4, 2, dict(faulty=True, tp=False, fp=True, fn=True, ttd=None)),           # too early
])
def test_detection_is_scored_against_the_injection(injected, detected, expect):
    assert analysis.detection(rec(injected_tick=injected, detected_tick=detected)) == expect


def test_a_scheduled_fault_that_never_fired_is_not_a_fault():
    record = rec()
    record["faults"] = [episode_record.build_fault(type="push", onset_s=40.0)]
    assert analysis.detection(record)["faulty"] is False


@pytest.mark.parametrize("name,fam", [("weaken_007", "weaken"), ("block_route_012",
                                                                  "block_route"),
                                      ("clear", "clear"), ("box_in_path", "box_in_path")])
def test_family_strips_the_generated_seed(name, fam):
    assert analysis.family(rec(scenario=name)) == fam


# =============================================================================
# The table
# =============================================================================

def corpus():
    records = []
    for i in range(10):      # off: the monitor sees it, nothing acts; 3/10 succeed
        records.append(rec(policy="off", success=i < 3, injected_tick=4,
                           detected_tick=6 if i < 8 else None, i=i))
    for i in range(10):      # recover: 9/10 succeed
        records.append(rec(policy="recover", success=i < 9, injected_tick=4,
                           detected_tick=5, recoveries=1, i=10 + i))
    records.append(rec(policy="recover", scenario="clear_000", detected_tick=3, i=99))
    return records


def test_one_row_per_arm_policy_and_family_compared_with_off():
    rows = {(r.policy, r.family): r for r in analysis.summarize(corpus())}
    assert set(rows) == {("off", "weaken"), ("recover", "weaken"), ("recover", "clear")}

    off, rec_ = rows[("off", "weaken")], rows[("recover", "weaken")]
    assert (off.n, off.successes, off.delta) == (10, 3, None)
    assert (off.tp, off.fn, off.fp) == (8, 2, 0) and off.ttd_mean == 2.0
    assert rec_.delta == pytest.approx(0.6)
    assert rec_.delta_p == pytest.approx(analysis.fisher_exact(9, 1, 3, 7))
    assert rec_.delta_ci[0] > 0
    assert rec_.recall == 1.0 and rec_.precision == 1.0 and rec_.recoveries_mean == 1.0

    clean = rows[("recover", "clear")]
    assert clean.fp == 1 and clean.precision == 0.0 and clean.recall is None
    assert clean.delta is None                       # no `off` run of that family


def test_the_markdown_table_has_a_row_per_group():
    table = analysis.to_markdown(analysis.summarize(corpus()))
    lines = table.splitlines()
    assert len(lines) == 2 + 3
    assert "| full | recover | weaken | 10 | 90%" in table
    assert "+60 pp" in table


def test_the_cli_reads_several_files_and_reports_invalid_records(tmp_path, capsys):
    good, bad = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    for r in corpus():
        episode_record.write_record(good, r)
    broken = rec()
    broken["policy"] = "panic"
    bad.write_text(json.dumps(broken) + "\n", encoding="utf-8")
    out = tmp_path / "table.md"
    assert analyze_episodes.main([str(good), str(bad), "--out", str(out)]) == 0
    assert "skipped invalid record" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8").count("\n") == 5
