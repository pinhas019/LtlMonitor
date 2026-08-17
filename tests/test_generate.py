"""Generation is the skill-agnostic claim's load-bearing step, so it is tested against
a SCRIPTED model -- no live LLM run, and the loop's behaviour is deterministic."""

from skill_monitor.describer import generate_formulas as g

SCHEMA = {
    "gripper_width": "float, metres. Distance between the fingers.",
    "object_grasped": "bool, True when the force sensors report a held object.",
}


def _spec(rule):
    return {
        "skill_name": "PickUpCup",
        "atomic_propositions": {"holding": f"True when {rule}. The cup is held."},
        "ltl_formulas": [{"name": "eventually_holding", "formula": "F(holding)"}],
        "terminal_success": {"condition": "holding", "description": "cup held"},
    }


def _scripted(*replies):
    """An LLM that returns each reply in turn; records the prompts it was given."""
    seen = []

    def llm(api_url, model, prompt):
        seen.append(prompt)
        return replies[min(len(seen) - 1, len(replies) - 1)]
    llm.prompts = seen
    return llm


def test_prompt_offers_only_this_robots_fields():
    text = g.schema_prompt(SCHEMA)
    assert "gripper_width" in text and "object_grasped" in text
    # The old hardcoded schema advertised fields no adapter provides; a rule written
    # over them is rejected by the contract, so they must not be suggested.
    for ghost in ("distance_to_target", "nav_status", "close_objects", "mean_range"):
        assert ghost not in text


def test_a_spec_over_real_fields_is_accepted_first_try():
    llm = _scripted(_spec("gripper_width < 0.01 and object_grasped"))
    spec, problems = g.generate("pick up the cup", SCHEMA, llm=llm)
    assert problems == []
    assert spec["skill_name"] == "PickUpCup"
    assert len(llm.prompts) == 1, "no repair round should have been needed"


def test_an_invented_sensor_field_is_caught_and_repaired():
    llm = _scripted(_spec("cup_detected > 0.5"),          # invents a field
                    _spec("object_grasped"))              # repairs to a real one
    spec, problems = g.generate("pick up the cup", SCHEMA, llm=llm)
    assert problems == []
    assert "object_grasped" in spec["atomic_propositions"]["holding"]
    assert len(llm.prompts) == 2
    # The repair prompt has to name the offending field and the legal alternatives,
    # or the model is guessing twice instead of once.
    repair = llm.prompts[1]
    assert "cup_detected" in repair and "gripper_width" in repair


def test_a_model_that_never_repairs_reports_the_surviving_problems():
    llm = _scripted(_spec("cup_detected > 0.5"))
    spec, problems = g.generate("pick up the cup", SCHEMA, llm=llm, attempts=2)
    assert any("cup_detected" in p for p in problems)
    assert spec, "the best attempt is still returned for inspection"


def test_llm_failure_is_reported_not_raised():
    def boom(*_):
        raise TimeoutError("no route to host")
    spec, problems = g.generate("pick up the cup", SCHEMA, llm=boom)
    assert problems and "no route to host" in problems[0]


def test_garbage_reply_is_reported_not_raised():
    spec, problems = g.generate("pick up the cup", SCHEMA, llm=_scripted("not a dict"))
    assert problems == ["model did not return a JSON object"]
