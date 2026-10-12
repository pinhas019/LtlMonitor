"""One record per evaluated episode — the unit every paper table is computed from.

Pure: no ROS, no simulator. Every runner writes through `write_record`, so the analysis
reads one shape whichever simulator, robot or arm produced the episode.

Ground truth lives here and nowhere else. `faults[*].injected_tick` and
`faults[*].injected_t` are set by whoever *injected* the fault — the simulator or the
scenario driver — never derived from the monitor's own verdicts. A benchmark whose labels
come from the detector under test measures nothing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1

#: Every key a record carries. Closed: an unknown key is a validation problem, so a
#: misspelt field cannot silently fall out of the analysis.
FIELDS = (
    "schema_version",
    "episode_id",
    "arm",
    "policy",
    "seed",
    "scenario",
    "scenario_params",
    "faults",
    "terminal",
    "success",
    "cause",
    "elapsed_s",
    "steps",
    "detected_tick",
    "recoveries",
    "timing",
)

#: What the episode runner did with the monitor's interventions (core/episode_outcome).
POLICIES = ("off", "detect", "recover")

_FAULT_FIELDS = ("type", "onset_s", "injected_tick", "injected_t", "params")


def build_fault(
    *,
    type: str,
    onset_s: float,
    injected_tick: int | None = None,
    injected_t: float | None = None,
    params: dict | None = None,
) -> dict:
    """A scheduled fault. `injected_*` stay None until the injector actually fires it."""
    return {
        "type": type,
        "onset_s": onset_s,
        "injected_tick": injected_tick,
        "injected_t": injected_t,
        "params": dict(params or {}),
    }


def build_record(
    *,
    episode_id: str,
    arm: str,
    policy: str = "detect",
    seed: int,
    scenario: str,
    scenario_params: dict | None = None,
    faults: Iterable[dict] = (),
    terminal: bool,
    success: bool,
    cause: str,
    elapsed_s: float,
    steps: int | None = None,
    detected_tick: int | None = None,
    recoveries: int = 0,
    timing: dict | None = None,
) -> dict:
    """Assemble a record. Validation is separate so a runner can log a bad one, not crash."""
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "arm": arm,
        "policy": policy,
        "seed": seed,
        "scenario": scenario,
        "scenario_params": dict(scenario_params or {}),
        "faults": [dict(f) if isinstance(f, dict) else f for f in faults],
        "terminal": terminal,
        "success": success,
        "cause": cause,
        "elapsed_s": elapsed_s,
        "steps": steps,
        "detected_tick": detected_tick,
        "recoveries": recoveries,
        "timing": dict(timing or {}),
    }


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_record(record: Any) -> list[str]:
    """Problems with `record`, one string each; empty means valid."""
    if not isinstance(record, dict):
        return [f"record must be an object, got {type(record).__name__}"]
    problems = []
    for key in FIELDS:
        if key not in record:
            problems.append(f"missing field {key!r}")
    for key in record:
        if key not in FIELDS:
            problems.append(f"unknown field {key!r}")

    if record.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("episode_id", "arm", "scenario", "cause"):
        if key in record and not isinstance(record[key], str):
            problems.append(f"{key} must be a string")
    if "seed" in record and not _is_int(record["seed"]):
        problems.append("seed must be an integer")
    for key in ("terminal", "success"):
        if key in record and not isinstance(record[key], bool):
            problems.append(f"{key} must be a boolean")
    if "elapsed_s" in record and not (_is_number(record["elapsed_s"])
                                      and record["elapsed_s"] >= 0):
        problems.append("elapsed_s must be a non-negative number")
    for key in ("steps", "detected_tick"):
        value = record.get(key)
        if value is not None and not (_is_int(value) and value >= 0):
            problems.append(f"{key} must be a non-negative integer or null")
    if "policy" in record and record["policy"] not in POLICIES:
        problems.append(f"policy must be one of {list(POLICIES)}")
    if "recoveries" in record and not (_is_int(record["recoveries"])
                                       and record["recoveries"] >= 0):
        problems.append("recoveries must be a non-negative integer")
    for key in ("scenario_params", "timing"):
        if key in record and not isinstance(record[key], dict):
            problems.append(f"{key} must be an object")
    if record.get("success") is True and record.get("terminal") is False:
        problems.append("a non-terminal episode cannot be a success")

    faults = record.get("faults")
    if faults is not None and not isinstance(faults, list):
        problems.append("faults must be a list")
        faults = []
    for i, fault in enumerate(faults or []):
        problems.extend(f"faults[{i}]: {p}" for p in _validate_fault(fault))
    return problems


def _validate_fault(fault: Any) -> list[str]:
    if not isinstance(fault, dict):
        return ["must be an object"]
    problems = []
    for key in _FAULT_FIELDS:
        if key not in fault:
            problems.append(f"missing field {key!r}")
    for key in fault:
        if key not in _FAULT_FIELDS:
            problems.append(f"unknown field {key!r}")
    if not isinstance(fault.get("type"), str) or not fault.get("type"):
        problems.append("type must be a non-empty string")
    if "onset_s" in fault and not (_is_number(fault["onset_s"]) and fault["onset_s"] >= 0):
        problems.append("onset_s must be a non-negative number")
    tick, t = fault.get("injected_tick"), fault.get("injected_t")
    if tick is not None and not (_is_int(tick) and tick >= 0):
        problems.append("injected_tick must be a non-negative integer or null")
    if t is not None and not (_is_number(t) and t >= 0):
        problems.append("injected_t must be a non-negative number or null")
    if "params" in fault and not isinstance(fault["params"], dict):
        problems.append("params must be an object")
    return problems


def time_to_detection(record: dict) -> int | None:
    """Ticks from the first injected fault to detection; None if either is missing.

    Negative means the monitor fired before any fault was injected — a false alarm on
    that episode, which the analysis has to count as one rather than as a fast detection.
    """
    injected = [f["injected_tick"] for f in record.get("faults", [])
                if f.get("injected_tick") is not None]
    detected = record.get("detected_tick")
    if not injected or detected is None:
        return None
    return detected - min(injected)


def write_record(path: str | Path, record: dict) -> None:
    """Append `record` as one JSON line. Refuses an invalid record rather than write it."""
    problems = validate_record(record)
    if problems:
        raise ValueError("invalid episode record: " + "; ".join(problems))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_records(path: str | Path) -> Iterator[dict]:
    """Yield the records in a JSON Lines file, skipping blank lines."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)
