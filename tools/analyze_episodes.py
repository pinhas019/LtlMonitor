#!/usr/bin/env python3
"""Render the episode records as the paper's main table (Markdown).

    python tools/analyze_episodes.py full.jsonl flat.jsonl > results.md
    python tools/analyze_episodes.py runs/*.jsonl --out results.md

One row per arm x policy x scenario family; see skill_monitor/core/analysis.py for what
each column means and how detection is scored against the injected ground truth.
Invalid records are reported and left out, never silently counted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_monitor.core import analysis                        # noqa: E402
from skill_monitor.core.episode_record import read_records, validate_record  # noqa: E402


def load(paths) -> tuple[list[dict], list[str]]:
    records, problems = [], []
    for path in paths:
        for i, record in enumerate(read_records(path)):
            found = validate_record(record)
            if found:
                problems.append(f"{path}:{i + 1}: {'; '.join(found)}")
            else:
                records.append(record)
    return records, problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("records", nargs="+", help="episodes.jsonl files")
    parser.add_argument("--out", help="write the table here instead of stdout")
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    args = parser.parse_args(argv)

    records, problems = load(args.records)
    for problem in problems:
        print(f"skipped invalid record {problem}", file=sys.stderr)
    if not records:
        print("no valid records", file=sys.stderr)
        return 1
    table = analysis.to_markdown(analysis.summarize(records,
                                                    bootstrap_seed=args.bootstrap_seed))
    if args.out:
        Path(args.out).write_text(table + "\n", encoding="utf-8")
    else:
        print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
