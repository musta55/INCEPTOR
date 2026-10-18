"""Split the study corpus into a pilot set, a development set and a held-out evaluation set,
as copies, so that the evaluation trajectories never reach the people or the LLM that build
the lookup tables.

The frame is configuration ``original``, runs 1-3: 3 agents x 50 bugs x 3 runs = 450
trajectories.  ``Dataset/`` and ``data/atif/`` are left exactly as they are; every set gets
its own copy of the converted ATIF file and of the raw log under ``--out`` (default
``data/splits/``):

  pilot/        3 trajectories on which the lookup tables were drafted and confirmed by hand:
                T01, T03 and T05 of ``ground_truth_sample.csv`` (one per agent, all three
                passing), which two authors labelled and then agreed on as the Final labels
  evaluation/   12 held-out trajectories, a stratified sample drawn before any lookup-table
                expansion: 4 per agent, at least one passing and one failing per agent and the
                rest in proportion to the agent's pass rate over the 3 runs (largest
                remainder), simple random within a stratum with seed 20261015, one trajectory
                per bug, preferring an app the agent has not been given yet.  Bugs of the
                earlier 15-trajectory sample, bug 18 (the codebook's worked example) and bugs 8
                and 159 (the paper's RQ4 examples) are not eligible, so no evaluation bug has
                been labelled or discussed
  development/  every other trajectory of the frame except all runs of all agents on an
                evaluation bug (held out by bug, so a second run of the same repair cannot leak
                into the tables); the LLM-assisted expansion of the lookup tables reads only this
                folder

Each set folder holds ``atif/run<k>/bug-<id>_<agent>.atif.json`` and
``raw/<agent>_original_run<k>/...`` (the agent's log: Claude ``bug-<id>_output.txt``, Qwen
``bug-<id>.log`` and ``.meta.json``, Codex the ``log-bug-<id>/`` session folder).  The record
``splits.csv`` (one row per trajectory: set, agent, bug, app, run, APR outcome, actions) sits
next to the three folders; ``evaluation/manifest.csv`` lists the held-out trajectories without
their outcomes.

An existing output folder is never rebuilt unless ``--overwrite`` is given.

Usage: python3 make_splits.py [--out DIR] [--seed 20261015] [--overwrite]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from atif import corpus, outcomes, project, segment
from make_ground_truth import APP, allocate

HERE = Path(__file__).resolve().parent
DATASET = HERE.parent / "Dataset"
ATIF = HERE / "data" / "atif"
OUT = HERE / "data" / "splits"
SAMPLE = HERE / "ground_truth_sample.csv"
AGENTS = corpus.AGENTS
CONFIG = "original"
RUNS = (1, 2, 3)
SEED = 20261015
PER_AGENT = 4
PILOT_TABS = ("T01", "T03", "T05")
EXCLUDE = {"18": "worked example of the codebook",
           "8": "RQ4 example in the paper", "159": "RQ4 example in the paper"}


def frame() -> List[dict]:
    table = outcomes.load(DATASET)
    rows = []
    for run in RUNS:
        for agent in AGENTS:
            for bug in corpus.all_bug_ids(DATASET):
                passed = table.get((agent, CONFIG, run, bug))
                if passed is None:
                    continue
                rows.append({"agent": agent, "bug": bug, "app": APP.get(bug, "?"), "run": run,
                             "outcome": "pass" if passed else "fail"})
    return rows


def split_counts(passed: int, total: int) -> Dict[str, int]:
    """At least one of each outcome, the rest by largest remainder (make_ground_truth.allocate)."""
    got = {k: v + 1 for k, v in allocate(PER_AGENT - 2, passed, total).items()}
    return got


def draw(rows: List[dict], banned: set, seed: int) -> List[dict]:
    rng = random.Random(seed)
    picked: List[dict] = []
    for agent in AGENTS:
        mine = [r for r in rows if r["agent"] == agent]
        split = split_counts(sum(r["outcome"] == "pass" for r in mine), len(mine))
        apps = set()
        for outcome in ("fail", "pass"):
            pool = [r for r in mine if r["outcome"] == outcome and r["bug"] not in banned]
            rng.shuffle(pool)
            for _ in range(split[outcome]):
                bugs = {p["bug"] for p in picked}
                free = [r for r in pool if r["bug"] not in bugs]
                best = next((r for r in free if r["app"] not in apps), None) or \
                    (free[0] if free else None)
                if best is None:
                    raise SystemExit(f"{agent}: not enough {outcome} trajectories")
                picked.append({**best, "allocation": f"{split['pass']} pass / {split['fail']} fail"})
                apps.add(best["app"])
    picked.sort(key=lambda p: (AGENTS.index(p["agent"]), p["outcome"] != "pass", int(p["bug"])))
    for k, p in enumerate(picked, 1):
        p["id"] = f"E{k:02d}"
    return picked


def actions(path: Path, bug: str) -> int:
    """Rows of the annotation workbook: the engine's actions, sub-agent calls included."""
    with project.use(trajectory := json.loads(path.read_text())):
        return len(segment.prepare(trajectory, bug))


def copy(row: dict, dest: Path) -> dict:
    agent, bug, run = row["agent"], row["bug"], row["run"]
    src = ATIF / CONFIG / f"run{run}" / f"bug-{bug}_{agent}.atif.json"
    if not src.is_file():
        raise SystemExit(f"missing {src}; run python3 -m atif.cli convert --all first")
    out = dest / "atif" / f"run{run}" / src.name
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out)
    log = corpus.log_path(DATASET, agent, CONFIG, run, bug)
    base = corpus.run_dir(DATASET, agent, CONFIG, run)
    raw = dest / "raw" / f"{agent}_{CONFIG}_run{run}"
    raw.mkdir(parents=True, exist_ok=True)
    if agent == "codex":
        shutil.copytree(base / f"log-bug-{bug}", raw / f"log-bug-{bug}", dirs_exist_ok=True)
    elif log is not None:
        shutil.copy2(log, raw / log.name)
        meta = log.with_name(f"bug-{bug}.meta.json")
        if meta.is_file():
            shutil.copy2(meta, raw / meta.name)
    return {**row, "actions": actions(src, bug), "atif": str(out.relative_to(dest.parent))}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    if args.out.exists():
        if not args.overwrite:
            print(f"{args.out} exists; pass --overwrite to rebuild it", file=sys.stderr)
            return 1
        shutil.rmtree(args.out)

    rows = frame()
    with SAMPLE.open() as f:
        sample = list(csv.DictReader(f))
    pilot_keys = {(s["agent"], s["bug"], int(s["run"])) for s in sample if s["tab"] in PILOT_TABS}
    banned = {s["bug"] for s in sample} | set(EXCLUDE)
    evaluation = draw(rows, banned, args.seed)
    held_bugs = {p["bug"] for p in evaluation}

    record = []
    for row in rows:
        key = (row["agent"], row["bug"], row["run"])
        if key in pilot_keys:
            record.append(copy({**row, "set": "pilot", "id": next(
                s["tab"] for s in sample if (s["agent"], s["bug"], int(s["run"])) == key)},
                args.out / "pilot"))
        elif row["bug"] not in held_bugs:
            record.append(copy({**row, "set": "development", "id": ""}, args.out / "development"))
    for p in evaluation:
        record.append(copy({**p, "set": "evaluation"}, args.out / "evaluation"))

    order = {"pilot": 0, "evaluation": 1, "development": 2}
    record.sort(key=lambda r: (order[r["set"]], r["id"], r["run"], AGENTS.index(r["agent"]),
                               int(r["bug"])))
    cols = ["set", "id", "agent", "bug", "app", "run", "outcome", "allocation", "actions", "atif"]
    with (args.out / "splits.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in record:
            w.writerow({**r, "allocation": r.get("allocation", ""), "config": CONFIG})
    with (args.out / "evaluation" / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "agent", "bug", "app", "run", "actions", "atif"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(r for r in record if r["set"] == "evaluation")

    for name in ("pilot", "evaluation", "development"):
        mine = [r for r in record if r["set"] == name]
        print(f"{name:12s} {len(mine):4d} trajectories  {sum(r['actions'] for r in mine):6d} actions  "
              f"pass {sum(r['outcome'] == 'pass' for r in mine)}")
    for r in record:
        if r["set"] != "development":
            print(f"  {r['id']}  {r['set']:10s} {r['agent']:6s} run{r['run']} bug-{r['bug']:7s} "
                  f"{r['app']:13s} {r['outcome']:4s} {r['actions']:4d} actions")
    print(f"held out by bug: {sorted(held_bugs, key=int)}; "
          f"{450 - len(record)} trajectories of those bugs are in no set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
