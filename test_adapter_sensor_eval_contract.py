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
from pathlib import Path

from sensor_adapter import CANONICAL_SENSOR_EVAL_KEYS

SPEC = json.loads((Path(__file__).parent / "formulas_g1.json").read_text())

_TRUE_WHEN_RE = re.compile(r"[Tt]rue when\s+(.+?)(?:\.|$)", re.IGNORECASE)
_QUOTED = re.compile(r"'[^']*'")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NON_SENSOR_TOKENS = {"and", "or", "not", "in", "True", "False", "None"}


def _sensor_keys_in_rule(desc: str) -> set[str]:
    m = _TRUE_WHEN_RE.search(desc)
    if not m:
        return set()
    rule = m.group(1)
    rule = _QUOTED.sub("", rule)  # strip string literals (e.g. 'AUTOMATIC') first --
    # otherwise their contents get mistaken for bare identifiers by _IDENT below.
    return {t for t in _IDENT.findall(rule) if t not in _NON_SENSOR_TOKENS}


def test_every_rule_ap_only_references_canonical_sensor_keys():
    referenced: set[str] = set()
    for desc in SPEC["atomic_propositions"].values():
        referenced |= _sensor_keys_in_rule(desc)
    unknown = referenced - CANONICAL_SENSOR_EVAL_KEYS
    assert not unknown, (
        f"formulas_g1.json rule APs reference sensor_eval keys no adapter contract "
        f"guarantees: {sorted(unknown)} (add to CANONICAL_SENSOR_EVAL_KEYS in "
        f"sensor_adapter.py and every adapter's get_sensor_eval(), or fix the typo)"
    )
