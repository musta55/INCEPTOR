"""Build the manual-annotation kit for the phase taxonomy: a stratified sample of 15
trajectories and one workbook per annotator.

Writes into ``--out`` (default ``Ground Truth/`` next to this file), from the converted
trajectories of one configuration and run (default ``original``, run 1; run
``python3 -m atif.cli convert --config original --runs 1 --all`` first if they are missing):

  annotator_<k>.xlsx      the workbook annotator k fills (Annotation Codebook.docx §5):
                          Start here, Phases, Action categories, Grouping rules, Outcomes and
                          flags, one tab per trajectory (T01..T15), Codebook changes
  atif/<tab>_bug-<id>_<agent>.atif.json   each sampled trajectory, copied unchanged
  tracker.xlsx            one row per trajectory and annotator, with status columns
  README.md               what the folder holds

and the sampling record ``ground_truth_sample.csv`` next to this file. It carries the APR
outcomes, so it stays out of the folder annotators work in: the workbooks are blind to the
outcome and to every automatic phase or subphase.

Sampling (Annotation Codebook.docx §3).  The frame is one configuration and run: 3 agents
x 50 bugs = 150 trajectories.  Each agent gets 5 trajectories, split between its passing and
failing runs in proportion to its APR pass rate (largest remainder; a tie goes to the failing
stratum, which is the smaller one in the corpus).  Within a stratum the draw is simple random
with a fixed seed, preferring a bug of an app the agent has not been given yet and a bug no
other agent has been given yet.  Bug 18 is excluded: it is the codebook's worked example.

Rounds.  Per agent, one passing and one failing trajectory (when the agent has both) form
round 1, in which the codebook may still change; the other nine form round 2, annotated
after the codebook is frozen.  Tabs are ordered round 1 first.

An existing output folder is never rebuilt unless ``--overwrite`` is given.

Usage: python3 make_ground_truth.py [--config original] [--run 1] [--annotators 2]
                                    [--per-agent 5] [--out DIR] [--overwrite]
"""
import argparse
import csv
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from atif import corpus, outcomes, phase, taxonomy
from atif.codebook import (CATEGORY_TEXT, CHANGE_KINDS, FLAG_TEXT, OUTCOME_ROWS, PHASE_TEXT,
                           RULES)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "Ground Truth"
DATASET = HERE.parent / "Dataset"
AGENTS = corpus.AGENTS
SEED = 20261010
EXCLUDE = {"18": "worked example of the codebook (§9.5, §9.6)"}

# App of each bug, from the Java package the agents read and edit
APP = {
    "8": "TrickyTripper", "18": "Calendula", "44": "Omni-Notes", "53": "Markor",
    "54": "Markor", "71": "KISS", "84": "Ultrasonic", "92": "WiFiAnalyzer",
    "114": "Harmonic", "129": "andOTP", "130": "andOTP", "136": "Harmonic",
    "159": "AnkiDroid", "160": "AnkiDroid", "171": "Harmonic", "181": "Harmonic",
    "191": "Anuto", "192": "Markor", "271": "Aegis", "273": "AnkiDroid", "275": "Aegis",
    "358": "URLCheck", "365": "URLCheck", "382": "URLCheck", "447": "URLCheck",
    "1130": "AntennaPod", "1138": "GPSLogger", "1146": "GPSTest", "1151": "GPSTest",
    "1198": "PDFConverter", "1202": "PDFConverter", "1205": "PDFConverter",
    "1207": "andOTP", "1213": "andOTP", "1214": "andOTP", "1215": "andOTP",
    "1255": "SkyTube", "1299": "FieldBook", "1441": "AnglersLog", "1445": "AnglersLog",
    "1446": "AnglersLog", "1563": "lrkFM", "1568": "lrkFM", "1640": "TrainerApp",
    "1641": "TrainerApp", "1645": "TrainerApp", "2587": "PSLab", "2677": "PSLab",
    "2678": "PSLab", "123451": "AnkiDroid",
}

# ----------------------------------------------------------------------------- vocabularies
# The reference tabs repeat the codebook's tables word for word (atif/codebook.py).

# Trajectory tab columns, in order: the three the annotator fills come first (frozen).
COLUMNS = ["phase", "category_fix", "notes", "step", "sub_agent", "fix_stage", "category",
           "tool", "target", "file_role", "verdict", "fail_kind", "result_preview",
           "thought_preview", "thought"]
TO_FILL = ["phase", "category_fix", "notes"]
MEANING = {
    "phase": "YOU FILL, on the first row of each phase stretch only (row 2 always): one of the "
             "five phases. Leave the other rows of the stretch empty.",
    "category_fix": "YOU FILL only when the given category is wrong: the right category, or "
                    "NEW when none fits (then describe it in notes and in Codebook changes).",
    "notes": "YOU MAY FILL: doubts, the reason for a departure from a rule, anything unusual.",
    "step": "The agent's inference step. Rows of one step share one thought.",
    "sub_agent": "yes when a sub-agent made the action.",
    "fix_stage": "pre-fix before the first change of app source, post-fix from it on (G1).",
    "category": "The action category from the lookup table (Action categories tab).",
    "tool": "The tool the agent called.",
    "target": "File, command or search query (first 200 characters).",
    "file_role": "Role of the files the action touches: source, test, toolchain (build files), "
                 "harness (the benchmark's check script), docs, outside (outside the project).",
    "verdict": "For a build, test or other run: pass, fail, or none (no result visible).",
    "fail_kind": "Why a run failed: test (a test ran and failed), build (does not compile), "
                 "env (the machine or toolchain stopped it), exit (other).",
    "result_preview": "Start of the tool's output (first 300 characters).",
    "thought_preview": "First 300 characters of the step's reasoning (first row of the step).",
    "thought": "The step's full reasoning, uncut (click the cell to read it).",
}
RUNS = {"build", "run_test", "device_ops", "env_setup", "run_shell", "wait_process"}
WIDTH = {"phase": 14, "category_fix": 13, "notes": 24, "step": 6, "sub_agent": 8,
         "fix_stage": 9, "category": 12, "tool": 13, "target": 42, "file_role": 11,
         "verdict": 8, "fail_kind": 9, "result_preview": 40, "thought_preview": 40,
         "thought": 60}
FONT = "Arial"
GIVEN_HEAD = PatternFill("solid", fgColor="D9D9D9")
FILL_HEAD = PatternFill("solid", fgColor="FFFF00")
FILL_CELL = PatternFill("solid", fgColor="FFF2CC")
TITLE = Font(name=FONT, bold=True, size=12)
BOLD = Font(name=FONT, bold=True)
BODY = Font(name=FONT, size=10)
WRAP = Alignment(wrap_text=True, vertical="top")


# ----------------------------------------------------------------------------- sampling
def allocate(n: int, passed: int, total: int) -> Dict[str, int]:
    """Largest-remainder split of n draws between pass and fail, proportional to the pass
    rate; a tie goes to fail."""
    want = {"pass": n * passed / total, "fail": n * (total - passed) / total}
    got = {k: int(v) for k, v in want.items()}
    order = sorted(want, key=lambda k: (-(want[k] - got[k]), k != "fail"))
    for k in order[:n - sum(got.values())]:
        got[k] += 1
    return got


def frame(config: str, run: int) -> List[dict]:
    table = outcomes.load(DATASET)
    out = []
    for agent in AGENTS:
        for bug in corpus.all_bug_ids(DATASET):
            passed = table.get((agent, config, run, bug))
            if passed is None:
                continue
            out.append({"agent": agent, "bug": bug, "app": APP.get(bug, "?"),
                        "outcome": "pass" if passed else "fail"})
    return out


def draw(rows: List[dict], per_agent: int, seed: int) -> List[dict]:
    rng = random.Random(seed)
    picked: List[dict] = []
    for agent in AGENTS:
        mine = [r for r in rows if r["agent"] == agent and r["bug"] not in EXCLUDE]
        passed = sum(r["outcome"] == "pass" for r in rows if r["agent"] == agent)
        split = allocate(per_agent, passed, sum(r["agent"] == agent for r in rows))
        apps = set()
        for outcome in ("fail", "pass"):
            pool = [r for r in mine if r["outcome"] == outcome]
            rng.shuffle(pool)
            for _ in range(split[outcome]):
                taken = {(p["agent"], p["bug"]) for p in picked}
                bugs = {p["bug"] for p in picked}
                free = [r for r in pool if (r["agent"], r["bug"]) not in taken]
                best = (next((r for r in free if r["app"] not in apps and r["bug"] not in bugs),
                             None) or next((r for r in free if r["app"] not in apps), None)
                        or (free[0] if free else None))
                if best is None:
                    raise SystemExit(f"{agent}: not enough {outcome} trajectories")
                picked.append({**best, "allocation": f"{split['pass']} pass / {split['fail']} fail"})
                apps.add(best["app"])
    for agent in AGENTS:                        # round 1: one pass and one fail per agent
        mine = [p for p in picked if p["agent"] == agent]
        first = [next((p for p in mine if p["outcome"] == o), None) for o in ("pass", "fail")]
        first = [p for p in first if p] or mine[:1]
        while len(first) < 2 and len(first) < len(mine):
            first.append(next(p for p in mine if p not in first))
        for p in mine:
            p["round"] = 1 if p in first else 2
    picked.sort(key=lambda p: (p["round"], AGENTS.index(p["agent"]), p["outcome"] != "pass",
                               int(p["bug"])))
    for k, p in enumerate(picked, 1):
        p["tab"] = f"T{k:02d}"
    return picked


# ----------------------------------------------------------------------------- rows
def step_thoughts(trajectory: dict, scope: str = "main") -> Dict[tuple, str]:
    """(scope, step_id) -> the agent's full reasoning and message for that step."""
    out = {}
    for step in trajectory.get("steps", []):
        parts = [(step.get("reasoning_content") or "").strip(), (step.get("message") or "").strip()]
        out[(scope, step["step_id"])] = "\n\n".join(p for p in parts if p)
    for sub in trajectory.get("subagent_trajectories") or []:
        out.update(step_thoughts(sub, sub.get("trajectory_id")))
    return out


file_role = taxonomy.action_roles


def sheet_rows(trajectory: dict, bug: str) -> List[dict]:
    """One row per action, with the given columns only: no phase or outcome of the tool."""
    result = phase.phases(trajectory, bug)
    acts, anchor = result["actions"], result["context"].get("anchor", 0)
    thoughts = step_thoughts(trajectory)
    out, last_step = [], None
    for x, a in enumerate(acts):
        key = (a["scope"], a["step_id"])
        thought = thoughts.get(key, "") if key != last_step else ""      # once per step
        last_step = key
        out.append({
            "step": a["step_id"], "sub_agent": "" if a["scope"] == "main" else "yes",
            "fix_stage": "pre-fix" if x < anchor else "post-fix",
            "category": a["category"], "tool": a["tool"], "target": a["target"],
            "file_role": file_role(a),
            "verdict": a["verdict"] if a["mid_level"] in RUNS or a["verdict"] != "none" else "",
            "fail_kind": a["fail_kind"] or "",
            "result_preview": " ".join((a["result_preview"] or "").split())[:300],
            "thought_preview": " ".join(thought.split())[:300], "thought": thought,
            **{c: "" for c in TO_FILL},
        })
    return out


# ----------------------------------------------------------------------------- workbook
def _clean(value):
    """Text without the control characters a worksheet cannot hold (terminal colour codes
    in test output)."""
    return ILLEGAL_CHARACTERS_RE.sub("", value) if isinstance(value, str) else value


def _header(ws, names, fills) -> None:
    for col, (name, fill) in enumerate(zip(names, fills), 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font, cell.fill = BOLD, fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _list(ws, ref: str, values: List[str], what: str) -> None:
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle=f"Not a {what}",
                        error=f"Use one of the {what} values of the lookup tables.")
    dv.add(ref)
    ws.add_data_validation(dv)


def _table(ws, title: str, head: List[str], rows: List[List], widths: List[int],
           intro: Optional[List[str]] = None) -> None:
    ws.cell(row=1, column=1, value=title).font = TITLE
    r = 2
    for line in intro or []:
        cell = ws.cell(row=r, column=1, value=line)
        cell.font, cell.alignment = BODY, Alignment(wrap_text=False, vertical="top")
        r += 1
    r += 1
    for col, h in enumerate(head, 1):
        cell = ws.cell(row=r, column=col, value=h)
        cell.font, cell.fill = BOLD, GIVEN_HEAD
    for row in rows:
        r += 1
        for col, v in enumerate(row, 1):
            cell = ws.cell(row=r, column=col, value=v)
            cell.font, cell.alignment = BODY, WRAP
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w


def start_tab(ws, annotator: int, sample: List[dict], counts: Dict[str, int]) -> None:
    ws.title = "Start here"
    lines = [
        f"Annotator {annotator}: phase annotation of 15 agent trajectories",
        "",
        "What you do, per trajectory tab (T01 ... T15), one row per action of the agent:",
        "1. Read the trajectory top to bottom. Spreadsheet row N + 1 is action N.",
        "2. phase: on the first row of each phase stretch, write one of the five phases "
        "(dropdown). Row 2 always starts a stretch. Leave the other rows empty.",
        "3. Use the lookup tables: Phases, Action categories, Grouping rules (G1-G8). The given "
        "category column comes from the Action categories table.",
        "4. category_fix: only when the given category is wrong; NEW when no category fits.",
        "5. Anything the tables cannot express: write it in notes and add a row to Codebook "
        "changes. Do not invent a phase label in the phase column.",
        "6. Fill the status columns below when you finish a tab.",
        "",
        "Rounds: annotate the round-1 tabs first. After round 1 both annotators and the lead "
        "meet, decide on the Codebook changes, and freeze the codebook. Round 2 uses the frozen "
        "codebook; new proposals in round 2 are logged but not applied.",
        "Work alone: do not discuss trajectories with the other annotator before adjudication.",
        "Full definitions, Table 5 and the worked examples: Annotation Codebook.docx, Sections 8-9.",
    ]
    for r, text in enumerate(lines, 1):
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = TITLE if r == 1 else BOLD if text.startswith("Rounds") else BODY
    r = len(lines) + 2
    head = ["tab", "round", "agent", "bug", "actions", "started", "finished", "minutes",
            "comments"]
    for col, h in enumerate(head, 1):
        cell = ws.cell(row=r, column=col, value=h)
        cell.font = BOLD
        cell.fill = FILL_HEAD if h in ("started", "finished", "minutes", "comments") else GIVEN_HEAD
    for p in sample:
        r += 1
        for col, v in enumerate([p["tab"], p["round"], p["agent"], f"bug-{p['bug']}",
                                 counts[p["tab"]], None, None, None, None], 1):
            cell = ws.cell(row=r, column=col, value=v)
            cell.font = BODY
            if col > 5:
                cell.fill = FILL_CELL
    ws.column_dimensions["A"].width = 12
    for col, w in zip("BCDEFGHI", (7, 8, 10, 8, 11, 11, 9, 40)):
        ws.column_dimensions[col].width = w


def trajectory_tab(ws, rows: List[dict]) -> None:
    _header(ws, COLUMNS, [FILL_HEAD if c in TO_FILL else GIVEN_HEAD for c in COLUMNS])
    for i, row in enumerate(rows, 2):
        for col, name in enumerate(COLUMNS, 1):
            cell = ws.cell(row=i, column=col, value=_clean(row[name]) if row[name] != "" else None)
            cell.font, cell.alignment = BODY, WRAP
            if name in TO_FILL:
                cell.fill = FILL_CELL
        ws.row_dimensions[i].height = 27            # two lines; longer text is clipped
    for col, name in enumerate(COLUMNS, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = WIDTH[name]
    ws.freeze_panes = "D2"                          # header row and the three columns to fill
    last = ws.cell(row=1, column=len(COLUMNS)).column_letter
    ws.auto_filter.ref = f"A1:{last}{len(rows) + 1}"
    _list(ws, f"A2:A{len(rows) + 1}", list(phase.PHASES), "phase")
    _list(ws, f"B2:B{len(rows) + 1}", list(taxonomy.CATEGORIES) + ["NEW"], "category")
    for i, name in enumerate(COLUMNS, 1):           # column meanings as header comments
        ws.cell(row=1, column=i).comment = Comment(MEANING[name], "codebook")


def changes_tab(ws) -> None:
    head = ["date", "tab", "row", "kind", "proposal", "why the tables cannot express it",
            "decision (lead)", "codebook version"]
    _header(ws, head, [FILL_HEAD] * 6 + [GIVEN_HEAD] * 2)
    for col, w in zip("ABCDEFGH", (11, 6, 6, 18, 50, 50, 25, 10)):
        ws.column_dimensions[col].width = w
    _list(ws, "D2:D200", CHANGE_KINDS, "change kind")
    ws.freeze_panes = "A2"


def write_workbook(path: Path, annotator: int, sample: List[dict],
                   rows: Dict[str, List[dict]]) -> None:
    wb = Workbook()
    start_tab(wb.active, annotator, sample, {t: len(r) for t, r in rows.items()})
    _table(wb.create_sheet("Phases"), "Table 1: Phases",
           ["phase", "the agent is…", "typical rows", "where"],
           [[k, *v] for k, v in PHASE_TEXT.items()], [16, 34, 90, 22],
           ["Every action belongs to exactly one phase; a phase can come back later."])
    _table(wb.create_sheet("Action categories"), "Table 2: Action categories",
           ["category", "family", "the action…", "tools (Claude / Codex / Qwen) and shell programs"],
           [[k, *v] for k, v in CATEGORY_TEXT.items()], [14, 11, 44, 90],
           ["Given in the category column. Correct it in category_fix only when it is wrong."])
    _table(wb.create_sheet("Grouping rules"), "Table 4: Grouping rules (how rows form phases)",
           ["rule", "name", "what to do"], [list(r) for r in RULES], [6, 34, 110],
           ["Apply G1 first, then decide each row's own phase with G2-G6 (Table 5 in the "
            "codebook), then join rows into stretches with G7. G8 settles doubts."])
    _table(wb.create_sheet("Outcomes and flags"),
           "Tables 6 and 7: outcomes and flags (reference only: the tool computes them)",
           ["phase / flag", "check / meaning", "succeeded", "failed", "blocked", "unchecked"],
           [list(r) for r in OUTCOME_ROWS] + [["", "", "", "", "", ""]]
           + [[k, v, "", "", "", ""] for k, v in FLAG_TEXT.items()], [24, 40, 26, 30, 28, 22],
           ["Each phase stretch is split into subphases, one per run of the same outcome."])
    for p in sample:
        trajectory_tab(wb.create_sheet(f"{p['tab']} {p['agent']} bug-{p['bug']}"), rows[p["tab"]])
    changes_tab(wb.create_sheet("Codebook changes"))
    wb.save(path)


def write_tracker(path: Path, sample: List[dict], annotators: int,
                  counts: Dict[str, int]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "tracker"
    cols = ["tab", "round", "agent", "bug", "actions"]
    status = [f"annotator_{k}_done" for k in range(1, annotators + 1)] + ["adjudicated",
                                                                          "comments"]
    _header(ws, cols + status, [GIVEN_HEAD] * len(cols) + [FILL_HEAD] * len(status))
    for i, p in enumerate(sample, 2):
        for col, v in enumerate([p["tab"], p["round"], p["agent"], int(p["bug"]),
                                 counts[p["tab"]]] + [0] * (annotators + 1) + [None], 1):
            cell = ws.cell(row=i, column=col, value=v)
            cell.font = BODY
            if col > len(cols):
                cell.fill = FILL_CELL
    ws.freeze_panes = "A2"
    wb.save(path)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=corpus.DEFAULT_CONFIG, choices=corpus.CONFIGS)
    ap.add_argument("--run", type=int, default=1, choices=corpus.RUNS)
    ap.add_argument("--annotators", type=int, default=2)
    ap.add_argument("--per-agent", type=int, default=5)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--overwrite", action="store_true",
                    help="rebuild an existing output folder (its workbooks and atif/ are replaced)")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    if out.exists() and any(p.name != "README.md" for p in out.iterdir()) and not args.overwrite:
        print(f"{out} is not empty; pass --overwrite to rebuild it", file=sys.stderr)
        return 2
    rows_frame = frame(args.config, args.run)
    sample = draw(rows_frame, args.per_agent, args.seed)
    if out.exists():
        shutil.rmtree(out / "atif", ignore_errors=True)
        for old in out.glob("annotator_*.xlsx"):
            old.unlink()
    (out / "atif").mkdir(parents=True, exist_ok=True)
    rows: Dict[str, List[dict]] = {}
    for p in sample:
        key = corpus.Key(p["agent"], args.config, args.run, p["bug"])
        src = corpus.atif_path(DATA, key)
        if not src.is_file():
            raise SystemExit(f"{src} is missing: run python3 -m atif.cli convert --config "
                             f"{args.config} --runs {args.run} --all")
        rows[p["tab"]] = sheet_rows(json.loads(src.read_text()), p["bug"])
        shutil.copyfile(src, out / "atif" / f"{p['tab']}_bug-{p['bug']}_{p['agent']}.atif.json")
    counts = {t: len(r) for t, r in rows.items()}
    for k in range(1, args.annotators + 1):
        write_workbook(out / f"annotator_{k}.xlsx", k, sample, rows)
    write_tracker(out / "tracker.xlsx", sample, args.annotators, counts)
    with (HERE / "ground_truth_sample.csv").open("w", newline="") as f:
        cols = ["tab", "round", "agent", "bug", "app", "outcome", "allocation", "actions",
                "config", "run", "seed"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in sample:
            w.writerow({**p, "actions": counts[p["tab"]], "config": args.config,
                        "run": args.run, "seed": args.seed})
    print(f"{args.config}, run {args.run}: frame {len(rows_frame)} trajectories -> {out}")
    for p in sample:
        print(f"  {p['tab']} round {p['round']}  {p['agent']:6s} bug-{p['bug']:7s} "
              f"{p['app']:13s} {p['outcome']:4s} {counts[p['tab']]:4d} actions  "
              f"(agent split {p['allocation']})")
    print(f"  {sum(counts.values())} actions in {len(sample)} trajectories; "
          f"{args.annotators} annotator workbooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
