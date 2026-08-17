"""The wire contract between a running monitor and anything watching it.

Two latched topics carry everything a client needs; neither requires importing this
package, and both are plain JSON:

    /ltl/manifest   the skill: spec as authored, plus phase names and where it came from
    /ltl/adapter    the robot: sensor schema and which topic feeds which key

and the per-tick /ltl/state_description carries the live part (phase, AP values,
sensor values, risk, failure-mode status). A GUI that reads these three is agnostic
to skill AND to embodiment: it renders what it is told exists.

Kept in core, ROS-free, so the GUI and the tests can build and check a manifest
without a graph.
"""

from __future__ import annotations


def phase_names(execution_phases) -> list:
    return [p.get("phase", f"phase{i}") for i, p in enumerate(execution_phases or [])]


def skill_manifest(raw_spec: dict, source: str = "inline") -> dict:
    """The /ltl/manifest payload for a spec.

    The spec is passed through as authored rather than reassembled from parsed
    pieces -- a client should see exactly the document the engine was given,
    including any field this engine version does not itself understand.
    """
    return dict(raw_spec) | {
        "skill_name": raw_spec.get("skill_name", ""),
        "phases": phase_names(raw_spec.get("execution_phases")),
        "source": source,
    }


def ap_rows(manifest: dict, state: dict) -> list:
    """One row per atomic proposition: (name, value, description).

    `value` is True/False from the monitor's last observation, or None when the AP
    is not currently required (phases only evaluate the APs they need, so an absent
    AP means "not asked", never "false").
    """
    values = (state or {}).get("ap_values") or {}
    aps = (manifest or {}).get("atomic_propositions") or {}
    return [(name, values.get(name), desc) for name, desc in sorted(aps.items())]


def sensor_rows(adapter: dict, state: dict) -> list:
    """One row per sensor field: (key, value, doc). Driven by the adapter's schema,
    so a robot with entirely different fields renders with no code change."""
    values = (state or {}).get("sensors") or {}
    schema = (adapter or {}).get("schema") or {}
    keys = sorted(set(schema) | set(values))
    return [(k, values.get(k), (schema.get(k) or {}).get("doc", "")) for k in keys]
