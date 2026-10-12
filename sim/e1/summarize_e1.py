"""E1's tables and figure from the episode records written by run_e1.py.

    python sim/e1/summarize_e1.py e1.jsonl --out docs/e1

Writes `results.md` (the tables below), `detection.svg/png` (detection by family and arm)
and prints the headline numbers.

  * Detection (policy `off`: the monitor reports, nothing acts) -- per family and arm:
    recall on fault episodes, false alarms on the fault-free families, median ticks from
    injection to the first intervention. Scored by core/analysis.detection.
  * Outcomes -- success rate per arm x policy over all families, with Wilson intervals, and
    the change against `off` with a Fisher exact p-value.
  * The full analysis.summarize table (arm x policy x family), for the appendix.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from skill_monitor.core import analysis                          # noqa: E402

ARMS = ("full", "flat", "flat_strict")
ARM_LABEL = {"full": "full spec", "flat": "flat (keeps terminal failure)",
             "flat_strict": "flat strict (no terminal failure)"}
CLEAN = ("clear", "cluttered")


def load(paths):
    return [json.loads(line) for p in paths for line in Path(p).read_text().splitlines()
            if line.strip()]


def detection_table(records):
    off = [r for r in records if r["policy"] == "off"]
    fams = sorted({analysis.family(r) for r in off}, key=lambda f: (f not in CLEAN, f))
    rows, cells = [], {}
    for fam in fams:
        row = {"family": fam}
        for arm in ARMS:
            group = [r for r in off if r["arm"] == arm and analysis.family(r) == fam]
            scored = [analysis.detection(r) for r in group]
            faulty = [s for s in scored if s["faulty"]]
            tp = sum(s["tp"] for s in scored)
            fp = sum(s["fp"] for s in scored)
            ttd = [s["ttd"] for s in scored if s["ttd"] is not None]
            cells[(fam, arm)] = {"n": len(group), "faulty": len(faulty), "tp": tp, "fp": fp,
                                 "ttd_median": statistics.median(ttd) if ttd else None}
            if fam in CLEAN:
                row[arm] = f"{fp}/{len(group)} false alarms"
            else:
                med = cells[(fam, arm)]["ttd_median"]
                row[arm] = (f"{tp}/{len(faulty)}" +
                            (f" · {med:.0f} ticks" if med is not None else ""))
        rows.append(row)
    return rows, cells


def consequence_rows(records):
    off = {(r["arm"], r["scenario"]): r for r in records if r["policy"] == "off"}
    fams = sorted({analysis.family(r) for r in off.values()},
                  key=lambda f: (f not in CLEAN, f))
    rows = []
    for fam in fams:
        eps = [s for (a, s) in off if a == "full" and analysis.family(off[(a, s)]) == fam]
        failed = [s for s in eps if not off[("full", s)]["success"]]
        detected = {}
        for arm in ARMS:
            detected[arm] = 0
            for s in failed:
                r = off.get((arm, s))
                if r is None:
                    continue
                inj = [f["injected_tick"] for f in r["faults"] if f["injected_tick"] is not None]
                if r["detected_tick"] is not None and (not inj or r["detected_tick"] >= min(inj)):
                    detected[arm] += 1
        wasted = sum(1 for s in eps if off[("full", s)]["success"]
                     and off[("full", s)]["detected_tick"] is not None)
        rows.append((fam, len(failed), len(eps), detected, wasted))
    return rows


def outcome_rows(records):
    rows = []
    by = defaultdict(list)
    for r in records:
        by[(r["arm"], r["policy"])].append(r)
    for arm in ARMS:
        base = by.get((arm, "off"), [])
        b_succ = sum(r["success"] for r in base)
        for policy in ("off", "detect", "recover"):
            group = by.get((arm, policy), [])
            if not group:
                continue
            k = sum(r["success"] for r in group)
            lo, hi = analysis.wilson(k, len(group))
            if policy == "off":
                delta = "—"
            else:
                p = analysis.fisher_exact(k, len(group) - k, b_succ, len(base) - b_succ)
                delta = f"{100 * (k / len(group) - b_succ / len(base)):+.0f} pp (p={p:.2g})"
            rec = statistics.mean(r["recoveries"] for r in group)
            rows.append((arm, policy, len(group), f"{100 * k / len(group):.0f}% "
                         f"({100 * lo:.0f}–{100 * hi:.0f})", delta, f"{rec:.2f}"))
    return rows


def figure(records, out: Path):
    """Detection of the faults that mattered: episodes that failed under `off`."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"full": "#2a78d6", "flat": "#eb6834", "flat_strict": "#1baf7a"}
    rows = [r for r in consequence_rows(records) if r[1] > 0]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    width = 0.26
    for i, arm in enumerate(ARMS):
        vals = [r[3][arm] / r[1] for r in rows]
        xs = [j + (i - 1) * width for j in range(len(rows))]
        ax.bar(xs, vals, width=width - 0.03, color=colors[arm], label=ARM_LABEL[arm])
    ax.set_xticks(range(len(rows)),
                  [f"{r[0].replace('_', ' ')}\n({r[1]} failed)" for r in rows])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("failures detected")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e3df")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.13))
    fig.tight_layout()
    fig.savefig(out / "detection.svg")
    fig.savefig(out / "detection.png", dpi=160)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", nargs="+")
    parser.add_argument("--out", default="docs/e1")
    args = parser.parse_args(argv)
    records = load(args.records)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows, cells = detection_table(records)
    fams = [r["family"] for r in rows]
    lines = [f"# E1 results ({len(records)} episodes)", "",
             "## Detection (policy off: the monitor reports, nothing acts)", "",
             "Fault families: detected / injected · median ticks (1 tick = 1 s) from "
             "injection to the first intervention. Fault-free families: episodes with any "
             "intervention.", "",
             "| family | " + " | ".join(ARM_LABEL[a] for a in ARMS) + " |",
             "|---|" + "---|" * len(ARMS)]
    for row in rows:
        lines.append(f"| {row['family']} | " + " | ".join(row[a] for a in ARMS) + " |")
    lines += ["", "## Detection of faults that mattered (policy off)", "",
              "A fault *mattered* when the episode failed under `off` (judged from ground "
              "truth). Alarms on episodes that succeeded anyway are interventions a "
              "policy would have acted on for nothing.", "",
              "| family | failed under off | " + " | ".join(
                  f"detected · {ARM_LABEL[a]}" for a in ARMS) +
              " | alarms on episodes that succeeded anyway (full) |",
              "|---|---|" + "---|" * len(ARMS) + "---|"]
    for fam, failed, n, detected, wasted in consequence_rows(records):
        lines.append(f"| {fam} | {failed}/{n} | " + " | ".join(
            f"{detected[a]}/{failed}" for a in ARMS) + f" | {wasted} |")
    lines += ["", "## Outcomes (all families pooled; success judged from simulator "
              "ground truth)", "",
              "| arm | policy | n | success (95% CI) | Δ vs off | mean recoveries |",
              "|---|---|---|---|---|---|"]
    for arm, policy, n, succ, delta, rec in outcome_rows(records):
        lines.append(f"| {arm} | {policy} | {n} | {succ} | {delta} | {rec} |")
    lines += ["", "## Causes of failure", "", "| arm | policy | causes |", "|---|---|---|"]
    by = defaultdict(lambda: defaultdict(int))
    for r in records:
        if not r["success"]:
            by[(r["arm"], r["policy"])][r["cause"]] += 1
    for (arm, policy), causes in sorted(by.items()):
        lines.append(f"| {arm} | {policy} | " + ", ".join(
            f"{c} {n}" for c, n in sorted(causes.items(), key=lambda kv: -kv[1])) + " |")
    lines += ["", "## Full table (arm × policy × family)", "",
              analysis.to_markdown(analysis.summarize(records))]
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    figure(records, out)
    print("\n".join(lines[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
