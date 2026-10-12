"""The spec-generation step, against a scripted model: what is written, what is refused,
and what the provenance says. No LLM is ever called."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from skill_monitor.core import api
from skill_monitor.describer import generate_formulas, generate_spec

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/g1_sim_spec.json").read_text(encoding="utf-8"))
DESCRIPTION = ROOT / "skill_monitor/specs/descriptions/g1_navigation.md"
NOW = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)


def _scripted(*replies):
    """An LLM that returns each reply in turn; records the prompts it was given."""
    seen = []

    def llm(api_url, model, prompt):
        seen.append(prompt)
        return copy.deepcopy(replies[min(len(seen) - 1, len(replies) - 1)])
    llm.prompts = seen
    return llm


def with_category(category):
    spec = copy.deepcopy(FIXTURE)
    spec["named_failure_modes"][0]["fault_category"] = category
    return spec


def with_condition(condition):
    spec = copy.deepcopy(FIXTURE)
    spec["execution_phases"][1]["progress_condition"] = condition
    return spec


def generate(tmp_path, llm, attempts=3):
    out = tmp_path / "formulas_g1_sim.json"
    spec, problems = generate_spec.run(
        adapter="mujoco", description_path=DESCRIPTION, out=out,
        api_url="http://llm.invalid/v1", model="scripted", attempts=attempts, llm=llm,
        now=NOW)
    return out, spec, problems


def provenance(out):
    return json.loads(generate_spec.provenance_path(out).read_text(encoding="utf-8"))


# =============================================================================
# The fixture and the description
# =============================================================================

def test_the_fixture_passes_every_gate_and_says_it_is_a_fixture():
    assert generate_spec.offline_gate(FIXTURE) == []
    assert FIXTURE["description"].startswith("TEST FIXTURE ONLY")


def test_the_description_names_no_sensor_field():
    """The model must ground the skill in the vocabulary itself; a description that
    spelled the keys out would be the hand-written spec by another route."""
    from skill_monitor.core import adapter_spec
    text = DESCRIPTION.read_text(encoding="utf-8")
    keys = adapter_spec.load("mujoco").docs()
    assert [k for k in keys if k in text] == []


# =============================================================================
# Generation
# =============================================================================

def test_a_clean_reply_is_written_with_its_provenance(tmp_path):
    llm = _scripted(FIXTURE)
    out, spec, problems = generate(tmp_path, llm)
    assert problems == [] and len(llm.prompts) == 1
    assert json.loads(out.read_text(encoding="utf-8")) == spec
    record = provenance(out)
    assert record["accepted"] is True and record["llm_calls"] == 1
    assert record["adapter"] == "mujoco" and record["model"] == "scripted"
    assert record["generated_at"] == "2026-01-02T03:04:05+00:00"
    assert record["history"] == [{"attempt": 1, "problems": [], "fixes": []}]
    assert len(record["description_sha256"]) == 64 and record["spec_sha256"]


def test_the_prompt_carries_the_description_and_this_robots_vocabulary(tmp_path):
    llm = _scripted(FIXTURE)
    generate(tmp_path, llm)
    prompt = llm.prompts[0]
    assert "commanded to reach" in prompt
    assert "no_progress" in prompt and "closing_speed" in prompt


def test_the_prompt_offers_only_categories_the_monitor_grades():
    prompt = generate_formulas.formulas_prompt("walk", {"x": "float"})
    assert "NAVIGATION" not in prompt
    assert all(f'"{c}"' in prompt for c in api.FAULT_CATEGORIES)


def test_an_unknown_fault_category_is_repaired_in_the_loop(tmp_path):
    """`generate` alone checked only the schema, so a NAVIGATION category sailed
    through and the monitor rejected the spec at load."""
    llm = _scripted(with_category("NAVIGATION"), FIXTURE)
    out, spec, problems = generate(tmp_path, llm)
    assert problems == [] and len(llm.prompts) == 2
    assert "NAVIGATION" in llm.prompts[1], "the repair prompt must name the problem"
    history = provenance(out)["history"]
    assert [bool(h["problems"]) for h in history] == [True, False]


def test_an_unparseable_condition_is_repaired_in_the_loop(tmp_path):
    llm = _scripted(with_condition("not (stalled"), FIXTURE)
    _, _, problems = generate(tmp_path, llm)
    assert problems == [] and "progress_condition" in llm.prompts[1]


def test_a_model_that_never_repairs_writes_no_spec_and_says_why(tmp_path):
    llm = _scripted(with_category("NAVIGATION"))
    out, _, problems = generate(tmp_path, llm, attempts=3)
    assert problems and any("NAVIGATION" in p for p in problems)
    assert not out.exists()
    record = provenance(out)
    assert record["accepted"] is False and record["llm_calls"] == 3
    assert record["spec_sha256"] is None and record["surviving_problems"] == problems


def test_a_model_that_fails_outright_is_recorded(tmp_path):
    def broken(*_a):
        raise ConnectionError("endpoint unreachable")
    out, _, problems = generate(tmp_path, broken)
    assert problems == ["LLM query failed: endpoint unreachable"]
    assert provenance(out)["accepted"] is False and not out.exists()


@pytest.mark.parametrize("spec,needle", [
    ({**FIXTURE, "execution_phases": []}, "no execution_phases"),
    ({**FIXTURE, "terminal_success": {"condition": "arrived and"}}, "terminal_success"),
    ({**FIXTURE, "terminal_failure": {"condition": 3}}, "must be a string"),
])
def test_condition_problems(spec, needle):
    assert any(needle in p for p in generate_spec.condition_problems(spec))


def test_the_cli_exit_code_follows_acceptance(tmp_path, monkeypatch, capsys):
    out = tmp_path / "spec.json"
    argv = ["--adapter", "mujoco", "--description", str(DESCRIPTION), "--out", str(out)]
    monkeypatch.setattr(generate_formulas, "query_llm", _scripted(FIXTURE))
    assert generate_spec.main(argv) == 0 and out.exists()
    out.unlink()
    monkeypatch.setattr(generate_formulas, "query_llm", _scripted(with_category("NAV")))
    assert generate_spec.main(argv + ["--attempts", "1"]) == 1 and not out.exists()
    assert "NAV" in capsys.readouterr().err
