"""Build the dashboard's example dataset: Dataset/demo/dataset1 (25 bugs x 3 agents x 3 runs,
see make_demo.py) analysed in advance under the default lookup tables, so that the Corpus
Overview opens with these bugs already in it (uploads.js, TV.uploads.seed) and the user adds
more by uploading.

    viewer/data/seed/
      dataset1.json.gz              {schema, dataset, runs: [{bug, agent, run, outcome, name,
                                    path, size, hash, file, result}]}: what a folder upload
                                    of dataset1 keeps per run (result = atif.upload.request)
      dataset1/<bug>/<agent>/run<k>.json.gz
                                    {text (the log as uploaded), atif}: read only when needed
                                    (the details panel, or another rule set)

A run is read as the Upload page reads a folder: its first file the engine reads, the bug and
agent from the folder names, the outcome from outcomes.csv. ``hash`` and ``size`` are those of
the log's text, so uploading the same folder again is recognised as the same files.

    python3 make_seed.py [--src ../Dataset/demo/dataset1] [--out viewer/data/seed]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import sys
from pathlib import Path

from atif import upload

HERE = Path(__file__).resolve().parent
SCHEMA = "trajectiers-seed/1"
DEFAULT_RULES = {"schema": "trajectiers-tables/1", "optional": [], "custom": []}
TRY_EXT = {"jsonl": 0, "ndjson": 0, "traj": 0, "json": 1, "log": 2, "txt": 3}   # uploads.js tryRank


def fnv(text: str) -> str:
    """uploads.js hashText: FNV-1a over the text's UTF-16 code units, and its length."""
    units = text.encode("utf-16-le")
    h = 0x811C9DC5
    for i in range(0, len(units), 2):
        h ^= units[i] | (units[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:x}-{len(units) // 2}"


def rank(path: Path) -> int:
    if path.name.endswith(".meta.json"):
        return 9
    return TRY_EXT.get(path.suffix.lstrip(".").lower(), -1)


def outcomes(src: Path) -> dict:
    """(bug, agent, run) -> True / False from outcomes.csv (bug, agent, run1, run2, ...)."""
    out = {}
    path = src / "outcomes.csv"
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            for col, value in row.items():
                m = re.fullmatch(r"run(\d+)", col or "")
                if m and value in ("pass", "fail"):
                    out[(row["bug"].replace("bug-", ""), row["agent"], int(m.group(1)))] = value == "pass"
    return out


def write_gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=HERE.parent / "Dataset" / "demo" / "dataset1")
    ap.add_argument("--out", type=Path, default=HERE / "viewer" / "data" / "seed")
    args = ap.parse_args(argv)
    src, name = args.src, args.src.name
    if not src.is_dir():
        print(f"{src} is not a folder (run make_demo.py first)", file=sys.stderr)
        return 1
    table = outcomes(src)
    if (args.out / name).exists():
        shutil.rmtree(args.out / name)
    runs, failed = [], []
    for run_dir in sorted(src.glob("bug-*/*/run*")):
        bug, agent = run_dir.parent.parent.name.replace("bug-", ""), run_dir.parent.name
        run = int(re.sub(r"\D", "", run_dir.name))
        files = sorted((f for f in run_dir.iterdir() if f.is_file() and not f.name.startswith(".") and rank(f) >= 0),
                       key=lambda f: (rank(f), -f.stat().st_size))
        outcome = table.get((bug, agent, run))
        for f in files:
            text = f.read_bytes().decode("utf-8", errors="replace")
            res = upload.request({"name": f.name, "text": text, "rules": DEFAULT_RULES, "bug": bug,
                                  "outcome": outcome, "atif": True})
            if "error" in res:
                continue
            atif = res.pop("atif")
            rel = f"{name}/bug-{bug}/{agent}/run{run}.json.gz"
            write_gz(args.out / rel, {"text": text, "atif": atif})
            runs.append({"bug": bug, "agent": agent, "run": run, "outcome": outcome, "name": f.name,
                         "path": f"{name}/bug-{bug}/{agent}/{run_dir.name}/{f.name}",
                         "size": f.stat().st_size, "hash": fnv(text), "file": rel, "result": res})
            break
        else:
            failed.append(str(run_dir.relative_to(src)))
    key = lambda r: (len(r["bug"]), r["bug"], r["agent"], r["run"])
    runs.sort(key=key)
    write_gz(args.out / f"{name}.json.gz", {"schema": SCHEMA, "dataset": name, "runs": runs})
    bugs = sorted({r["bug"] for r in runs}, key=lambda b: (len(b), b))
    print(f"{name}: {len(bugs)} bugs, {len(runs)} runs -> {args.out}"
          + (f"; no trajectory in {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
