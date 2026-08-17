"""The validation oracle for skill-agnostic synthesis.

    python3 -m pytest test_spec_contract.py

This is the gate a generated spec must pass before it can run, so its failure modes
matter more than most: a false PASS ships an always-false atomic proposition to the
robot, and a false FAIL blocks a correct spec.
"""

import skill_monitor.core.spec_contract as spec_contract
from skill_monitor.backend.adapters.base import NAV_SCHEMA, SensorAdapter

NAV_KEYS = frozenset(NAV_SCHEMA)


def _spec(aps, **rest):
    return {"atomic_propositions": aps, **rest}


# -- rule extraction ---------------------------------------------------------

def test_rule_ap_is_recognised():
    assert spec_contract.rule_of("True when min_range < 0.25. Something is close.") \
        == "min_range < 0.25"


def test_decimal_literals_survive_extraction():
    """Regression. A non-greedy `(.+?)(?:\\.|$)` terminated at the first period, which
    in a numeric threshold is the DECIMAL POINT. On formulas_g1.json that silently
    turned `min_range < 0.25` into `min_range < 0` (never true for a distance, so
    collision_risk could never fire and G(!collision_risk) could never trigger) and
    `image_similarity_to_goal > 0.75` into `> 0` (fires almost immediately)."""
    assert spec_contract.rule_of("True when min_range < 0.25. Obstacle ahead.") \
        == "min_range < 0.25"
    assert spec_contract.rule_of("True when image_similarity_to_goal > 0.75.") \
        == "image_similarity_to_goal > 0.75"
    assert spec_contract.rule_of("True when x > 1.5 and y < 0.125") == "x > 1.5 and y < 0.125"


def test_non_rule_ap_has_no_rule():
    assert spec_contract.rule_of("The robot believes the door is open.") is None
    # ...and therefore carries no schema obligation.
    assert spec_contract.sensor_keys_in_rule("The robot believes the door is open.") == set()


def test_string_literals_are_not_mistaken_for_fields():
    # The regression that motivates stripping quotes: AUTOMATIC is a value, not a field.
    keys = spec_contract.sensor_keys_in_rule("True when nav_mode == 'AUTOMATIC'.")
    assert keys == {"nav_mode"}


def test_double_quoted_literals_too():
    assert spec_contract.sensor_keys_in_rule('True when nav_state == "following".') \
        == {"nav_state"}


def test_operators_and_literals_are_not_fields():
    keys = spec_contract.sensor_keys_in_rule(
        "True when nav_stuck == True and not mission_finished.")
    assert keys == {"nav_stuck", "mission_finished"}


# -- schema checking ---------------------------------------------------------

def test_hallucinated_field_is_caught():
    # The failure this whole module exists for: an LLM inventing a plausible sensor.
    bad = _spec({"near": "True when distance_to_target < 0.5."})
    assert spec_contract.unknown_keys(bad, NAV_KEYS) == {"near": {"distance_to_target"}}
    problems = spec_contract.validate(bad, NAV_KEYS)
    assert any("distance_to_target" in p for p in problems)
    # The message must list the legal alternatives -- it is fed back to the LLM.
    assert any("nav_state" in p for p in problems)


def test_valid_spec_passes():
    good = _spec({
        "moving": "True when nav_state == 'following'. Robot is driving.",
        "close": "True when min_range < 0.25. Obstacle ahead.",
    })
    assert spec_contract.unknown_keys(good, NAV_KEYS) == {}
    assert spec_contract.validate(good, NAV_KEYS) == []


def test_undeclared_ap_used_in_formula_is_caught():
    # Always-false at runtime, and silent without this check.
    spec = _spec(
        {"moving": "True when nav_state == 'following'."},
        ltl_formulas=[{"name": "seq", "formula": "F(moving && F(arrived))"}],
    )
    assert spec_contract.undeclared_aps(spec) == {"arrived"}
    assert any("arrived" in p for p in spec_contract.validate(spec, NAV_KEYS))


def test_ltl_operators_are_not_undeclared_aps():
    spec = _spec(
        {"moving": "True when nav_state == 'following'."},
        ltl_formulas=[{"name": "g", "formula": "G(F(moving))"}],
    )
    assert spec_contract.undeclared_aps(spec) == set()


def test_phase_and_terminal_conditions_are_scanned():
    spec = _spec(
        {"moving": "True when nav_state == 'following'."},
        execution_phases=[{"phase": "Go", "enter_condition": "started",
                           "exit_condition": "moving"}],
        terminal_success={"condition": "all_done"},
    )
    assert spec_contract.undeclared_aps(spec) == {"started", "all_done"}


def test_empty_spec_is_a_problem():
    assert spec_contract.validate({}, NAV_KEYS)


# -- the per-adapter seam ----------------------------------------------------

def test_adapter_must_declare_a_schema():
    class _Undeclared(SensorAdapter):
        def register_subscriptions(self, node): pass
        def get_sensor_eval(self): return {}

    try:
        _Undeclared.schema()
    except NotImplementedError:
        return
    raise AssertionError("an adapter with no SCHEMA must fail loudly, not inherit nav keys")


def test_validate_sensor_eval_uses_the_adapters_own_schema():
    # A manipulation adapter must be validated against gripper keys, not nav keys --
    # this is the whole point of moving the schema off a global.
    class _Gripper(SensorAdapter):
        SCHEMA = {"gripper_closed": "bool", "object_grasped": "bool"}

        def register_subscriptions(self, node): pass

        def get_sensor_eval(self):
            return self.validate_sensor_eval(
                {"gripper_closed": True, "object_grasped": False})

    assert _Gripper().get_sensor_eval() == {"gripper_closed": True, "object_grasped": False}
    assert _Gripper.schema_keys() == frozenset({"gripper_closed", "object_grasped"})

    class _Broken(_Gripper):
        def get_sensor_eval(self):
            return self.validate_sensor_eval({"gripper_closed": True})   # missing one

    try:
        _Broken().get_sensor_eval()
    except ValueError as e:
        assert "object_grasped" in str(e) and "_Broken" in str(e)
        return
    raise AssertionError("a drifted adapter must fail loudly")
