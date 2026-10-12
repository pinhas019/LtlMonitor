"""Statistics for the episode records: the paper's main table, computed, never typed.

    from skill_monitor.core import analysis
    rows = analysis.summarize(records)          # one row per arm x policy x family
    print(analysis.to_markdown(rows))

Pure Python (`math` and `random` only), so it runs wherever the records are.

**Success** is the record's own `success`, which the runner judged from ground truth.
**Detection** is scored per episode against the injector's ground truth:

    the episode had a fault        a fault was injected (`injected_t` set)
    the monitor detected it        `detected_tick` is set and not before the injection
    a false alarm                  `detected_tick` is set and there was no fault yet --
                                   on a clean episode, or before the injection tick

A false alarm on a faulty episode is also a miss: the alarm was not about the fault.
Precision, recall and F1 are over episodes. Time to detection is in clock ticks
(`episode_record.time_to_detection`), averaged over detections that can be timed.

`delta` compares a group's success rate with the same arm and family under policy `off`
-- the effect of acting on the monitor -- with a two-sided Fisher exact p-value and a
seeded bootstrap interval on the difference.
"""

from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field

from skill_monitor.core.episode_record import time_to_detection

Z_95 = 1.959963984540054
_SEEDED_NAME = re.compile(r"^(?P<family>.+)_(?P<seed>\d+)$")


# =============================================================================
# Intervals and tests
# =============================================================================

def wilson(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion; (0, 1) when there is no data."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for [[a, b], [c, d]].

    Sums the probability of every table with the same margins that is no more likely
    than the one observed (the usual definition, as in R and SciPy).
    """
    row1, col1, n = a + b, a + c, a + b + c + d
    if n == 0:
        return 1.0

    def prob(x: int) -> float:
        return math.comb(col1, x) * math.comb(n - col1, row1 - x) / math.comb(n, row1)

    observed = prob(a)
    lo, hi = max(0, row1 + col1 - n), min(row1, col1)
    p = sum(q for q in map(prob, range(lo, hi + 1)) if q <= observed * (1 + 1e-7))
    return min(1.0, p)


def bootstrap_diff(xs: list[float], ys: list[float], *, iterations: int = 2000,
                   seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap interval for mean(xs) - mean(ys), resampling each group."""
    if not xs or not ys:
        return -math.inf, math.inf
    rng = random.Random(seed)
    diffs = sorted(
        sum(rng.choices(xs, k=len(xs))) / len(xs) - sum(rng.choices(ys, k=len(ys))) / len(ys)
        for _ in range(iterations))
    tail = (1 - level) / 2
    return diffs[int(tail * (iterations - 1))], diffs[int((1 - tail) * (iterations - 1))]


# =============================================================================
# Per-episode scoring
# =============================================================================

def family(record: dict) -> str:
    """`weaken_007` -> `weaken`: generated scenarios are named `<family>_<seed>`."""
    name = record.get("scenario", "")
    match = _SEEDED_NAME.match(name)
    return match.group("family") if match else name


def _injected(record: dict) -> list[dict]:
    return [f for f in record.get("faults") or [] if f.get("injected_t") is not None]


def detection(record: dict) -> dict:
    """{faulty, tp, fp, fn, ttd} for one episode (see the module docstring)."""
    faulty = bool(_injected(record))
    detected = record.get("detected_tick") is not None
    ttd = time_to_detection(record)
    early = ttd is not None and ttd < 0
    tp = faulty and detected and not early
    fp = detected and (not faulty or early)
    return {"faulty": faulty, "tp": tp, "fp": fp, "fn": faulty and not tp,
            "ttd": ttd if tp else None}


# =============================================================================
# Grouped summary
# =============================================================================

@dataclass
class Row:
    arm: str
    policy: str
    family: str
    n: int
    successes: int
    success_ci: tuple[float, float]
    tp: int
    fp: int
    fn: int
    ttd_mean: float | None
    recoveries_mean: float
    outcomes: list[int] = field(repr=False, default_factory=list)
    delta: float | None = None
    delta_ci: tuple[float, float] | None = None
    delta_p: float | None = None

    @property
    def success_rate(self) -> float:
        return self.successes / self.n if self.n else 0.0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p is not None and r is not None and p + r else None


def summarize(records, *, bootstrap_seed: int = 0) -> list[Row]:
    """One row per (arm, policy, family), sorted, each compared against `off`."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for record in records:
        groups[(record.get("arm", ""), record.get("policy", "detect"), family(record))] \
            .append(record)

    rows = []
    for (arm, policy, fam), group in sorted(groups.items()):
        scored = [detection(r) for r in group]
        ttds = [s["ttd"] for s in scored if s["ttd"] is not None]
        outcomes = [int(bool(r.get("success"))) for r in group]
        rows.append(Row(
            arm=arm, policy=policy, family=fam, n=len(group),
            successes=sum(outcomes), success_ci=wilson(sum(outcomes), len(group)),
            tp=sum(s["tp"] for s in scored), fp=sum(s["fp"] for s in scored),
            fn=sum(s["fn"] for s in scored),
            ttd_mean=sum(ttds) / len(ttds) if ttds else None,
            recoveries_mean=sum(r.get("recoveries", 0) for r in group) / len(group),
            outcomes=outcomes,
        ))

    baselines = {(r.arm, r.family): r for r in rows if r.policy == "off"}
    for row in rows:
        base = baselines.get((row.arm, row.family))
        if base is None or row.policy == "off":
            continue
        row.delta = row.success_rate - base.success_rate
        row.delta_ci = bootstrap_diff(row.outcomes, base.outcomes, seed=bootstrap_seed)
        row.delta_p = fisher_exact(row.successes, row.n - row.successes,
                                   base.successes, base.n - base.successes)
    return rows


# =============================================================================
# Rendering
# =============================================================================

def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def _num(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def to_markdown(rows: list[Row]) -> str:
    header = ("| arm | policy | family | n | success (95% CI) | Δ vs off [95% CI] (p) "
              "| precision | recall | F1 | TTD (ticks) | recoveries |")
    lines = [header, "|" + "---|" * 11]
    for r in rows:
        lo, hi = r.success_ci
        success = f"{_pct(r.success_rate)} ({_pct(lo)}–{_pct(hi)})"
        if r.delta is None:
            delta = "—"
        else:
            dlo, dhi = r.delta_ci
            delta = (f"{100 * r.delta:+.0f} pp [{100 * dlo:+.0f}, {100 * dhi:+.0f}] "
                     f"(p={r.delta_p:.3g})")
        lines.append(
            f"| {r.arm} | {r.policy} | {r.family} | {r.n} | {success} | {delta} "
            f"| {_pct(r.precision)} | {_pct(r.recall)} | {_num(r.f1, 2)} "
            f"| {_num(r.ttd_mean)} | {_num(r.recoveries_mean, 2)} |")
    return "\n".join(lines)
