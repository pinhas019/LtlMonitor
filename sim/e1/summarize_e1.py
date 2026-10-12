"""E1's tables and figure from the episode records written by run_e1.py.

    python sim/e1/summarize_e1.py e1.jsonl --out docs/e1

Writes `results.md` (the tables below), `detection.svg/png` (detection by family and arm)
and prints the headline numbers.

  * Detection (policy `off`: the monitor reports, nothing acts) -- per family and arm:
    recall on fault episodes, false alarms on the fault-free families, median ticks from
    injection to the first intervention. Scored by core/analysis.detection.
  * Paired -- the full spec against each flat arm on the same scenario: detection latency
    under `off` and time to deliver under `recover`, with an exact sign test.
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


def is_clean(family: str) -> bool:
    """Fault-free families, in E1 (`clear`) and E1b (`carry_clear`) alike."""
    return family.endswith(CLEAN)


#: An intervention the E1b runner raises when the executor reports the task done and the
#: monitor does not confirm it: a detection made only at the end, not during the task.
AT_COMPLETION = "completion_unverified"


def _first_intervention(record):
    log = (record.get("timing") or {}).get("interventions") or []
    return log[0][1] if log else None


def load(paths):
    return [json.loads(line) for p in paths for line in Path(p).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def detection_table(records):
    off = [r for r in records if r["policy"] == "off"]
    fams = sorted({analysis.family(r) for r in off}, key=lambda f: (not is_clean(f), f))
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
            if is_clean(fam):
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
                  key=lambda f: (not is_clean(f), f))
    rows = []
    for fam in fams:
        eps = [s for (a, s) in off if a == "full" and analysis.family(off[(a, s)]) == fam]
        failed = [s for s in eps if not off[("full", s)]["success"]]
        detected, early = {}, {}
        for arm in ARMS:
            detected[arm] = early[arm] = 0
            for s in failed:
                r = off.get((arm, s))
                if r is None:
                    continue
                inj = [f["injected_tick"] for f in r["faults"] if f["injected_tick"] is not None]
                if r["detected_tick"] is not None and (not inj or r["detected_tick"] >= min(inj)):
                    detected[arm] += 1
                    if _first_intervention(r) != AT_COMPLETION:
                        early[arm] += 1
        wasted = sum(1 for s in eps if off[("full", s)]["success"]
                     and off[("full", s)]["detected_tick"] is not None)
        rows.append((fam, len(failed), len(eps), detected, wasted, early))
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


def monitor_said(record) -> str | None:
    """What the monitor concluded about the episode from its messages alone, by its last
    verdict: "success", "failure" or "undecided". None for records that predate it."""
    out = (record.get("timing") or {}).get("monitor_outcome")
    if out is None:
        return None
    if out.get("terminal") == "SUCCESS" or out.get("verdict") == "SATISFIED":
        return "success"
    if out.get("terminal") == "FAILURE" or out.get("verdict") == "VIOLATED":
        return "failure"
    return "undecided"


def inferred_outcome_rows(records):
    """Per arm, policy `off`: the monitor's conclusion against the simulator's truth.
    Each row: (arm, n, truly ok -> said success/undecided/failure, truly failed -> ...,
    agreement = said success exactly when the task succeeded)."""
    rows = []
    for arm in ARMS:
        group = [r for r in records if r["arm"] == arm and r["policy"] == "off"
                 and monitor_said(r) is not None]
        if not group:
            continue
        cells = {(ok, said): 0 for ok in (True, False)
                 for said in ("success", "undecided", "failure")}
        for r in group:
            cells[(bool(r["success"]), monitor_said(r))] += 1
        agree = sum(1 for r in group if (monitor_said(r) == "success") == bool(r["success"]))
        rows.append((arm, len(group), cells, agree))
    return rows


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact sign test on the non-tied pairs."""
    from math import comb
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired_rows(records, base="full"):
    """Full spec against each flat arm, episode by episode on the same scenario.

    `detect`: under `off`, on the episodes that failed, ticks from injection to the first
    intervention. `deliver`: under `recover`, on the episodes both arms got right, the
    simulated seconds to finish. Each row: (family, arm, measure, n pairs, median base,
    median arm, base better, ties, base worse, sign-test p).
    """
    idx = {(r["arm"], r["policy"], r["scenario"]): r for r in records}
    fams = sorted({analysis.family(r) for r in records if not is_clean(analysis.family(r))})
    rows = []
    for fam in fams:
        scen = sorted({r["scenario"] for r in records if analysis.family(r) == fam})
        for arm in ARMS:
            if arm == base:
                continue
            for measure, policy in (("detect", "off"), ("deliver", "recover")):
                pairs = []
                for s in scen:
                    a, b = idx.get((base, policy, s)), idx.get((arm, policy, s))
                    if a is None or b is None:
                        continue
                    if measure == "detect":
                        if idx[(base, "off", s)]["success"]:
                            continue
                        x, y = analysis.detection(a)["ttd"], analysis.detection(b)["ttd"]
                    else:
                        if not (a["success"] and b["success"]):
                            continue
                        x, y = a["elapsed_s"], b["elapsed_s"]
                    if x is not None and y is not None:
                        pairs.append((x, y))
                if not pairs:
                    continue
                better = sum(x < y for x, y in pairs)
                worse = sum(x > y for x, y in pairs)
                rows.append((fam, arm, measure, len(pairs),
                             statistics.median(x for x, _ in pairs),
                             statistics.median(y for _, y in pairs),
                             better, len(pairs) - better - worse, worse,
                             sign_test(better, worse)))
    return rows


def figure(records, out: Path):
    """Detection of the faults that mattered: episodes that failed under `off`."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"full": "#2a78d6", "flat": "#eb6834", "flat_strict": "#1baf7a"}
    rows = [r for r in consequence_rows(records) if r[1] > 0]
    stacked = any(r[5] != r[3] for r in rows)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    width = 0.26
    for i, arm in enumerate(ARMS):
        vals = [r[3][arm] / r[1] for r in rows]
        xs = [j + (i - 1) * width for j in range(len(rows))]
        if stacked:
            during = [r[5][arm] / r[1] for r in rows]
            ax.bar(xs, during, width=width - 0.03, color=colors[arm], label=ARM_LABEL[arm])
            ax.bar(xs, [v - d for v, d in zip(vals, during)], bottom=during,
                   width=width - 0.03, color=colors[arm], alpha=0.3)
        else:
            ax.bar(xs, vals, width=width - 0.03, color=colors[arm], label=ARM_LABEL[arm])
    ax.set_xticks(range(len(rows)),
                  [f"{r[0].replace('_', ' ')}\n({r[1]} failed)" for r in rows])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("failures detected")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e3df")
    ax.set_axisbelow(True)
    handles, labels = ax.get_legend_handles_labels()
    if stacked:
        from matplotlib.patches import Patch
        handles.append(Patch(color="#9a9a96", alpha=0.3))
        labels.append("lighter: caught only when the executor claimed success")
    ax.legend(handles, labels, frameon=False, ncol=4 if stacked else 3, loc="upper center",
              bbox_to_anchor=(0.5, 1.13), fontsize=9 if stacked else 10)
    fig.tight_layout()
    fig.savefig(out / "detection.svg")
    fig.savefig(out / "detection.png", dpi=160)


def latency_figure(records, out: Path):
    """Median seconds from injection to the first intervention, per family and arm, over
    the faults that mattered and were detected (policy off)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"full": "#2a78d6", "flat": "#eb6834", "flat_strict": "#1baf7a"}
    off = [r for r in records if r["policy"] == "off" and not r["success"]]
    fams = sorted({analysis.family(r) for r in off if not is_clean(analysis.family(r))})
    med = {}
    for fam in fams:
        for arm in ARMS:
            ttd = [analysis.detection(r)["ttd"] for r in off
                   if r["arm"] == arm and analysis.family(r) == fam]
            ttd = [t for t in ttd if t is not None]
            med[(fam, arm)] = statistics.median(ttd) if ttd else None
    fams = [f for f in fams if any(med[(f, a)] is not None for a in ARMS)]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    width = 0.26
    for i, arm in enumerate(ARMS):
        xs = [j + (i - 1) * width for j in range(len(fams))]
        vals = [med[(f, arm)] or 0 for f in fams]
        bars = ax.bar(xs, vals, width=width - 0.03, color=colors[arm], label=ARM_LABEL[arm])
        for x, v in zip(xs, vals):
            ax.text(x, v + 0.8, f"{v:.0f}", ha="center", fontsize=9, color="#52514e")
    ax.set_xticks(range(len(fams)), [f.replace("carry_", "").replace("_", " ") for f in fams])
    ax.set_ylabel("seconds to detection (median)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e4e3df")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.13))
    fig.tight_layout()
    fig.savefig(out / "latency.svg")
    fig.savefig(out / "latency.png", dpi=160)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", nargs="+")
    parser.add_argument("--out", default="docs/e1")
    parser.add_argument("--title", default="E1 results")
    args = parser.parse_args(argv)
    records = load(args.records)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows, cells = detection_table(records)
    fams = [r["family"] for r in rows]
    lines = [f"# {args.title} ({len(records)} episodes)", "",
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
    rows = consequence_rows(records)
    for fam, failed, n, detected, wasted, early in rows:
        lines.append(f"| {fam} | {failed}/{n} | " + " | ".join(
            f"{detected[a]}/{failed}" for a in ARMS) + f" | {wasted} |")
    if any(r[5] != r[3] for r in rows):
        lines += ["", "### …of which caught during the task, before the executor claimed "
                  "success", "",
                  "The rest were caught only by the completion check "
                  "(`completion_unverified`), when it is too late to save the attempt.", "",
                  "| family | failed | " + " | ".join(ARM_LABEL[a] for a in ARMS) + " |",
                  "|---|---|" + "---|" * len(ARMS)]
        for fam, failed, n, detected, wasted, early in rows:
            if failed:
                lines.append(f"| {fam} | {failed} | " + " | ".join(
                    f"{early[a]}/{failed}" for a in ARMS) + " |")
    inferred = inferred_outcome_rows(records)
    if inferred:
        lines += ["", "## The monitor's own conclusion against ground truth (policy off)", "",
                  "The monitor's last verdict, from the ROS messages alone: *success* "
                  "(SATISFIED or terminal success), *failure* (VIOLATED or terminal "
                  "failure) or *undecided*. Truth is the simulator's (object at the "
                  "drop-off, not held, no fall). Agreement: the monitor said success "
                  "exactly when the task succeeded.", "",
                  "| arm | n | succeeded: said success / undecided / failure | failed: "
                  "said success / undecided / failure | agreement |",
                  "|---|---|---|---|---|"]
        for arm, n, c, agree in inferred:
            ok = " / ".join(str(c[(True, k)]) for k in ("success", "undecided", "failure"))
            bad = " / ".join(str(c[(False, k)]) for k in ("success", "undecided", "failure"))
            lines.append(f"| {arm} | {n} | {ok} | {bad} | {agree}/{n} "
                         f"({100 * agree / n:.0f}%) |")
    paired = paired_rows(records)
    if paired:
        lines += ["", "## Paired: full spec against each flat arm, scenario by scenario", "",
                  "*detect*: policy `off`, episodes that failed, ticks from injection to the "
                  "first intervention. *deliver*: policy `recover`, episodes both arms "
                  "completed, simulated seconds to finish. Lower is better; the sign test "
                  "counts the pairs where the full spec was lower against those where it "
                  "was higher.", "",
                  "| family | against | measure | pairs | median full | median other | "
                  "full lower / tie / higher | sign test p |",
                  "|---|---|---|---|---|---|---|---|"]
        for fam, arm, measure, n, ma, mb, better, ties, worse, p in paired:
            lines.append(f"| {fam} | {arm} | {measure} | {n} | {ma:.1f} | {mb:.1f} | "
                         f"{better} / {ties} / {worse} | {p:.2g} |")
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
    latency_figure(records, out)
    print("\n".join(lines[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
