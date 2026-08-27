"""Contract test: formulas_g1.json's rule-AP expressions may only reference sensor_eval
keys every adapter is required to provide (sensor_adapter.CANONICAL_SENSOR_EVAL_KEYS).
This is what makes swapping --adapter actually safe -- a spec author can't
accidentally write a rule against a field only one adapter happens to expose.

Doesn't import rclpy or any adapter module (this sandbox has neither installed);
sensor_adapter.py is deliberately rclpy-free (see its own docstring) so this check
runs anywhere. The complementary runtime check -- does an adapter's get_sensor_eval()
actually RETURN every canonical key -- is SensorAdapter.validate_sensor_eval, called
from every adapter's get_sensor_eval() and enforced live in whatever environment
actually runs it (real robot, MuJoCo, Isaac Lab), not by this test.

Run: python3 -m pytest test_adapter_sensor_eval_contract.py
"""

import json
import re
from skill_monitor import spec_path

import skill_monitor.core.spec_contract as spec_contract
from skill_monitor.backend.adapters.base import NAV_SCHEMA

SPEC = json.loads(spec_path("g1").read_text(encoding="utf-8"))

def test_every_rule_ap_only_references_canonical_sensor_keys():
    unknown = set()
    for missing in spec_contract.unknown_keys(SPEC, NAV_SCHEMA).values():
        unknown |= missing
    assert not unknown, (
        f"formulas_g1.json rule APs reference sensor_eval keys no adapter contract "
        f"guarantees: {sorted(unknown)} (add to NAV_SCHEMA in "
        f"sensor_adapter.py and every adapter's get_sensor_eval(), or fix the typo)"
    )
