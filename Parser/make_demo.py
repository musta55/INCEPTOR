"""Build the demo datasets: the corpus (config ``original``, runs 1-3, Claude Code, Codex and
Qwen Code) laid out as the dashboard's folder upload reads it, split into two datasets.

    Dataset/demo/
      dataset1/                     the first 25 bugs (by id)
        bug-<id>/<agent>/run<k>/    the run's raw trajectory log, as the agent wrote it
        outcomes.csv                bug, agent, run1, run2, run3 (pass / fail; empty: unknown)
      dataset2/                     the other 25 bugs, the same way

Each run folder holds the one log ``atif.corpus.log_path`` reads for that run (the Codex
rollout, not its sidecar files). The dashboard opens with ``dataset1`` already in it
(make_seed.py builds it into viewer/data/seed/); uploading ``dataset2`` on the Upload page
completes the corpus table with the same experiment.

    python3 make_demo.py [--out ../Dataset/demo] [--force]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from atif import corpus, outcomes

HERE = Path(__file__).resolve().parent
DATASET = HERE.parent / "Dataset"
AGENTS = ("claude", "codex", "qwen")
RUNS = (1, 2, 3)
CONFIG = corpus.DEFAULT_CONFIG


def corpus_bugs() -> list:
    """The bug ids of the dashboard's corpus (viewer/data/overview.js), sorted numerically."""
    text = (HERE / "viewer" / "data" / "overview.js").read_text(encoding="utf-8")
    data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return sorted((str(b["bug"]) for b in data["bugs"]), key=lambda b: (len(b), b))


def build(out: Path, bugs: list, table: dict) -> tuple:
    """Copy the logs of ``bugs`` into ``out`` and write its outcomes.csv; (logs, missing)."""
    logs, missing = 0, []
    rows = []
    for bug in bugs:
        for agent in AGENTS:
            row = {"bug": f"bug-{bug}", "agent": agent}
            for run in RUNS:
                src = corpus.log_path(DATASET, agent, CONFIG, run, bug)
                if src is None:
                    missing.append(f"bug-{bug}/{agent}/run{run}")
                else:
                    dest = out / f"bug-{bug}" / agent / f"run{run}" / src.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    logs += 1
                passed = table.get((agent, CONFIG, run, bug))
                row[f"run{run}"] = "" if passed is None else "pass" if passed else "fail"
            rows.append(row)
    with (out / "outcomes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bug", "agent", *[f"run{r}" for r in RUNS]])
        writer.writeheader()
        writer.writerows(rows)
    return logs, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DATASET / "demo")
    ap.add_argument("--force", action="store_true", help="replace an existing demo folder")
    args = ap.parse_args(argv)
    if args.out.exists():
        if not args.force:
            print(f"{args.out} exists; pass --force to rebuild it", file=sys.stderr)
            return 1
        shutil.rmtree(args.out)
    bugs = corpus_bugs()
    half = len(bugs) // 2
    table = outcomes.load(DATASET)
    for name, part in (("dataset1", bugs[:half]), ("dataset2", bugs[half:])):
        logs, missing = build(args.out / name, part, table)
        print(f"{name}: {len(part)} bugs (bug-{part[0]} .. bug-{part[-1]}), {logs} logs"
              + (f", {len(missing)} runs without a log: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
