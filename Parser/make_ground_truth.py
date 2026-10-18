"""Build the manual-annotation kit for the phase taxonomy: a stratified sample of 15
trajectories and one annotation workbook (the Final lookup tables).

Writes into ``--out`` (default ``Ground Truth/`` next to this file), from the converted
trajectories of one configuration and run (default ``original``, run 1; run
``python3 -m atif.cli convert --config original --runs 1 --all`` first if they are missing):

  annotation_workbook.xlsx  the one workbook (Annotation Codebook.docx §5): Start here; the
                          Annotation sheet with all 15 trajectories, one row per action, and
                          the phase, category_fix and notes columns of annotator 1 and of
                          annotator 2; the reference tabs Phases and Final lookup table
                          (``atif.lookup``, word for word); Codebook changes
  atif/<tab>_bug-<id>_<agent>.atif.json   each sampled trajectory, copied unchanged
  tracker.xlsx            one row per trajectory and annotator, with status columns
  README.md               what the folder holds

``--workbook-only`` rewrites the workbook alone, from the existing sample
(``ground_truth_sample.csv``) and ``atif/`` copies, leaving the rest of the kit as it is.
``--labels PATH[:K]`` copies the phase, category_fix and notes an annotator already wrote
into an earlier workbook (one tab per trajectory, version 3) into the columns of annotator K
(default 1).  Only files this script writes are ever replaced; annotators' own copies in the
folder are left alone.

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
       python3 make_ground_truth.py --workbook-only [--labels PATH[:K] ...] [--out DIR]
"""
import argparse
import csv
import json
import random
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from atif import corpus, lookup, outcomes, phase, taxonomy
from atif.codebook import CHANGE_KINDS, EVIDENCE_TEXT

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "Ground Truth"
SAMPLE = HERE / "ground_truth_sample.csv"
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
# The reference tabs repeat the Final lookup tables word for word (atif/lookup.py).

WORKBOOK = "annotation_workbook.xlsx"
#: files earlier versions of this script wrote; a rebuild removes them, and nothing else
OLD_WORKBOOKS = ("annotator_1.xlsx", "annotator_2.xlsx")
#: the Annotation sheet: trajectory columns, then each annotator's three columns, then the
#: given columns (the layout an annotator chose on 2026-10-14, plus the ATIF columns after it)
IDS = ["trajectory", "bug_id", "agent", "action"]
TO_FILL = ["phase", "category_fix", "notes"]
GIVEN = ["step", "sub_agent", "thought_preview", "message", "tool", "full command",
         "shell command", "target", "result_preview", "fix_stage", "category", "file_role",
         "verdict", "fail_kind", "own_patch", "result_end", "is_error", "exit_code", "files",
         "waits_for", "reasoning", "timestamp", "tool_call_id", "result"]


def fill_columns(k: int) -> List[str]:
    return [f"A{k} {c}" for c in TO_FILL]


MEANING = {
    "trajectory": "The trajectory: T01 ... T15 (T01-T06 round 1, T07-T15 round 2).",
    "bug_id": "The bug the agent was fixing.",
    "agent": "The agent: claude (Claude Code), codex (Codex CLI) or qwen (Qwen Code).",
    "action": "The action's number within its trajectory (1 = the first action). Use it with "
              "the trajectory to point at a row: T03 action 12.",
    "phase": "YOU FILL, on the first row of each phase stretch (action 1 always): one of the five "
             "phases, from the phase table (Final lookup table tab). Leave the other rows of the "
             "stretch empty.",
    "category_fix": "YOU FILL only when the given category is wrong: the right category from the "
                    "action table (Final lookup table tab), or NEW when none fits (then describe "
                    "it in notes and in Codebook changes).",
    "notes": "YOU MAY FILL: \"thought\" when a thought decided a row that takes the previous "
             "step's phase; \"departure:\" and the evidence when you depart from the phase "
             "table; any doubt.",
    "step": "The agent's inference step. Rows of one step were issued together and share one "
            "thought.",
    "sub_agent": "yes when a sub-agent made the action.",
    "thought_preview": "First 300 characters of the step's reasoning and message (first row of "
                       "the step).",
    "message": "The step's message, uncut (ATIF message; first row of the step).",
    "tool": "The tool the agent called.",
    "full command": "Every argument of the tool call, uncut, as the agent sent it (ATIF "
                    "tool_calls[].arguments).",
    "shell command": "For a shell tool (Bash, exec_command, run_shell_command): the command line "
                     "that ran, uncut. Empty for other tools.",
    "target": "File, search or the agent's description of the command (first 200 characters).",
    "result_preview": "Start of the tool's output (first 300 characters).",
    "fix_stage": "pre-fix before the first change of app source, post-fix from it on.",
    "category": "The action category, from the action table (Final lookup table tab).",
    "file_role": "The targets of the files the action touches, from the target table (Final "
                 "lookup table tab): source, test, docs, build, other, outside.",
    "verdict": "For a build, test or other run: pass, fail, or none (no result visible).",
    "fail_kind": "Why a run failed: test (a test ran and failed), build (does not compile), env "
                 "(the machine or toolchain stopped it), exit (other).",
    "own_patch": "yes when the row reads or searches a file the agent already changed (phase "
                 "table row 11).",
    "result_end": "End of the tool's output (last 300 characters), where Gradle and test "
                  "runners print their result. Empty when result_preview already shows it all.",
    "is_error": "yes when the tool reported an error for the call.",
    "exit_code": "The command's exit code, when the agent's log records one.",
    "files": "Every path the action names (project paths relative to the checkout).",
    "waits_for": "For a wait or poll: the action number of the run it waits for.",
    "reasoning": "The step's reasoning, uncut (ATIF reasoning_content; Codex and Qwen Code; "
                 "first row of the step).",
    "timestamp": "When the step ran (Codex only).",
    "tool_call_id": "The call's id in the ATIF file (search for it there).",
    "result": "The tool's whole output (up to 32,000 characters; longer ones are cut, the rest "
              "is in the ATIF file).",
}
WIDTH = {"trajectory": 6, "bug_id": 10, "agent": 7, "action": 6, "phase": 13,
         "category_fix": 12, "notes": 18, "step": 6, "sub_agent": 6, "thought_preview": 26,
         "message": 38, "tool": 12, "full command": 32, "shell command": 32, "target": 34,
         "result_preview": 36, "fix_stage": 9, "category": 12, "file_role": 10, "verdict": 8,
         "fail_kind": 8, "own_patch": 7, "result_end": 36, "is_error": 6, "exit_code": 6,
         "files": 30, "waits_for": 7, "reasoning": 38, "timestamp": 12, "tool_call_id": 14,
         "result": 50}
RUNS = {"build", "run_test", "device_ops", "env_setup", "run_shell", "wait_process"}
CELL_MAX = 32000                    # a worksheet cell holds at most 32,767 characters
FONT = "Arial"
GIVEN_HEAD = PatternFill("solid", fgColor="D9D9D9")
FILL_HEAD = [PatternFill("solid", fgColor="FFFF00"), PatternFill("solid", fgColor="FFC000")]
FILL_CELL = [PatternFill("solid", fgColor="FFF2CC"), PatternFill("solid", fgColor="FCE4D6")]
TITLE = Font(name=FONT, bold=True, size=12)
BOLD = Font(name=FONT, bold=True)
BODY = Font(name=FONT, size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
NEW_TRAJECTORY = Border(top=Side(style="medium", color="000000"))


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
def step_texts(trajectory: dict, scope: str = "main") -> Dict[tuple, Tuple[str, str]]:
    """(scope, step_id) -> (reasoning, message) of that step, uncut."""
    out = {}
    for step in trajectory.get("steps", []):
        out[(scope, step["step_id"])] = ((step.get("reasoning_content") or "").strip(),
                                         (step.get("message") or "").strip())
    for sub in trajectory.get("subagent_trajectories") or []:
        out.update(step_texts(sub, sub.get("trajectory_id")))
    return out


def call_results(trajectory: dict) -> Dict[str, dict]:
    """tool_call_id -> the ``extra`` of its observation result (is_error, exit_code, ...)."""
    out: Dict[str, dict] = {}
    for step in trajectory.get("steps", []):
        for result in (step.get("observation") or {}).get("results") or []:
            if result.get("source_call_id"):
                out[result["source_call_id"]] = result.get("extra") or {}
    for sub in trajectory.get("subagent_trajectories") or []:
        out.update(call_results(sub))
    return out


def _flat(text: str, n: int, tail: bool = False) -> str:
    text = " ".join((text or "").split())
    return text[-n:] if tail else text[:n]


def _uncut(text: str) -> str:
    text = text or ""
    if len(text) <= CELL_MAX:
        return text
    return text[:CELL_MAX] + f" … [cut: {len(text) - CELL_MAX} more characters in the ATIF file]"


def sheet_rows(trajectory: dict, bug: str) -> List[dict]:
    """One row per action, with the given columns only: no phase or outcome of the tool."""
    result = phase.phases(trajectory, bug)
    acts, anchor = result["actions"], result["context"].get("anchor", 0)
    texts, extras = step_texts(trajectory), call_results(trajectory)
    out, last_step = [], None
    for x, a in enumerate(acts):
        key = (a["scope"], a["step_id"])
        reasoning, message = texts.get(key, ("", "")) if key != last_step else ("", "")
        last_step = key
        thought = "\n\n".join(t for t in (reasoning, message) if t)
        call = {"function_name": a["tool"], "arguments": a.get("arguments") or {}}
        shell = taxonomy.shell_command(call) if a["tool"] in taxonomy.SHELL_TOOLS else ""
        extra = extras.get(a.get("call_id") or "", {})
        output = a.get("result") or ""
        files = [taxonomy.repo_path(f) for f in a.get("files") or []]
        files += [o for o in a.get("outside") or [] if not o.startswith("/dev/")]
        waits = a.get("waits_pos")
        out.append({
            "step": a["step_id"], "sub_agent": "" if a["scope"] == "main" else "yes",
            "thought_preview": _flat(thought, 300), "message": message, "tool": a["tool"],
            "full command": json.dumps(a.get("arguments") or {}, ensure_ascii=False),
            "shell command": shell, "target": a["target"],
            "result_preview": _flat(output, 300),
            "fix_stage": "pre-fix" if x < anchor else "post-fix",
            "category": a["category"], "file_role": taxonomy.action_roles(a),
            "verdict": a["verdict"] if a["mid_level"] in RUNS or a["verdict"] != "none" else "",
            "fail_kind": a["fail_kind"] or "", "own_patch": "yes" if a.get("own_patch") else "",
            "result_end": _flat(output, 300, tail=True) if len(_flat(output, 10 ** 9)) > 300 else "",
            "is_error": "yes" if extra.get("is_error") else "",
            "exit_code": extra.get("exit_code", ""), "files": ", ".join(dict.fromkeys(files)),
            "waits_for": waits + 1 if waits is not None else "", "reasoning": reasoning,
            "timestamp": a.get("timestamp") or "", "tool_call_id": a.get("call_id") or "",
            "result": _uncut(output),
        })
    return out


def read_labels(path: Path, sample: List[dict]) -> Dict[str, List[Tuple[str, str, str]]]:
    """{tab: [(phase, category_fix, notes) per action]} from an earlier workbook with one tab
    per trajectory (version 3; columns found by their header, in any order)."""
    wb = load_workbook(path, data_only=True)
    out: Dict[str, List[Tuple[str, str, str]]] = {}
    for p in sample:
        name = next((n for n in wb.sheetnames if n.startswith(p["tab"] + " ")), None)
        if name is None:
            continue
        ws = wb[name]
        head = {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}
        n = int(p["actions"])
        given = [ws.cell(row=r, column=head["category"]).value for r in range(2, ws.max_row + 1)]
        if len([v for v in given if v not in (None, "")]) != n:
            raise SystemExit(f"{path.name} {name}: not {n} action rows; labels not copied")

        def col(c: str) -> List[str]:
            return [str(ws.cell(row=r, column=head[c]).value or "").strip() if c in head else ""
                    for r in range(2, n + 2)]

        rows = list(zip(col("phase"), col("category_fix"), col("notes")))
        if any(any(r) for r in rows):
            out[p["tab"]] = rows
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


def _tables(ws, title: str, parts: List[tuple], widths: List[int]) -> None:
    """Several tables on one tab: each part is (heading, intro lines, head, rows)."""
    ws.cell(row=1, column=1, value=title).font = TITLE
    r = 2
    for heading, intro, head, rows in parts:
        r += 1
        ws.cell(row=r, column=1, value=heading).font = BOLD
        for line in intro:
            r += 1
            ws.cell(row=r, column=1, value=line).font = BODY
        if head:
            r += 1
            for col, h in enumerate(head, 1):
                cell = ws.cell(row=r, column=col, value=h)
                cell.font, cell.fill = BOLD, GIVEN_HEAD
        for row in rows:
            r += 1
            for col, v in enumerate(row, 1):
                cell = ws.cell(row=r, column=col, value=v)
                cell.font, cell.alignment = BODY, WRAP
        r += 1
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w


def start_tab(ws, sample: List[dict], counts: Dict[str, int], first: Dict[str, int],
              annotators: int) -> None:
    ws.title = "Start here"
    lines = [
        "Phase annotation of 15 agent trajectories (the Final lookup tables)",
        "",
        "The Annotation tab holds all 15 trajectories, one row per action, in the order the "
        "agent made them. A thick line starts each trajectory.",
        "Annotator 1 fills the yellow columns (A1 ...), annotator 2 the orange ones (A2 ...). "
        "Work in your own copy and hide the other annotator's three columns (the - above them).",
        "1. Read a trajectory top to bottom before you label it: thought, command, result.",
        "2. category: check it against the action table (Final lookup table tab). If it is "
        "wrong, write the right one in category_fix (NEW when none fits).",
        "3. phase: give each row the phase of the first matching row of the phase table (Final "
        "lookup table tab). A row that says the previous step's phase takes the phase of the row "
        "above.",
        "4. Write the phase on the first row of each stretch of one phase (action 1 always); "
        "leave the other rows empty. Writing the same phase again does not start a new stretch.",
        "5. notes: \"thought\" when a thought decided a row that takes the previous step's "
        "phase; \"departure:\" and the evidence when you depart from the phase table; and add "
        "a row to Codebook changes.",
        "6. Fill the status columns below when you finish a trajectory.",
        "",
        "Rounds: annotate T01-T06 first (round 1). After round 1 both annotators and the lead "
        "meet, decide on the Codebook changes and freeze the codebook. Round 2 (T07-T15) uses "
        "the frozen codebook; new proposals in round 2 are logged but not applied.",
        "Work alone: do not look at the other annotator's columns or discuss trajectories "
        "before adjudication.",
        "The tables, with two development steps for every entry: the Final lookup table and "
        "Lookup justification tabs of the authors' workbook.",
    ]
    for r, text in enumerate(lines, 1):
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = TITLE if r == 1 else BOLD if text.startswith("Rounds") else BODY
    r = len(lines) + 2
    status = [f"A{k} done" for k in range(1, annotators + 1)] + ["comments"]
    head = ["trajectory", "round", "agent", "bug", "actions", "first row"] + status
    for col, h in enumerate(head, 1):
        cell = ws.cell(row=r, column=col, value=h)
        cell.font = BOLD
        cell.fill = FILL_HEAD[0] if h in status else GIVEN_HEAD
    for p in sample:
        r += 1
        values = [p["tab"], int(p["round"]), p["agent"], f"bug-{p['bug']}", counts[p["tab"]],
                  first[p["tab"]]] + [None] * len(status)
        for col, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=col, value=v)
            cell.font = BODY
            if col > 6:
                cell.fill = FILL_CELL[0]
    for col, w in zip("ABCDEFGHI", (11, 7, 8, 10, 8, 9, 9, 9, 40)):
        ws.column_dimensions[col].width = w


def annotation_tab(ws, sample: List[dict], rows: Dict[str, List[dict]], annotators: int,
                   labels: Dict[int, Dict[str, list]]) -> Dict[str, int]:
    """All trajectories on one sheet; returns the sheet row where each trajectory starts."""
    ws.title = "Annotation"
    fills = [c for k in range(1, annotators + 1) for c in fill_columns(k)]
    names = IDS + fills + GIVEN
    heads = [GIVEN_HEAD] * len(IDS) + [FILL_HEAD[(k - 1) % 2] for k in range(1, annotators + 1)
                                       for _ in TO_FILL] + [GIVEN_HEAD] * len(GIVEN)
    _header(ws, names, heads)
    first: Dict[str, int] = {}
    r = 1
    for p in sample:
        tab = p["tab"]
        first[tab] = r + 1
        for x, row in enumerate(rows[tab]):
            r += 1
            values = [tab, f"bug-{p['bug']}", p["agent"], x + 1]
            for k in range(1, annotators + 1):
                values += list(labels.get(k, {}).get(tab, [("", "", "")] * len(rows[tab]))[x])
            values += [row[c] for c in GIVEN]
            for col, v in enumerate(values, 1):
                cell = ws.cell(row=r, column=col, value=_clean(v) if v not in ("", None) else None)
                cell.font, cell.alignment = BODY, WRAP
                k = (col - len(IDS) - 1) // len(TO_FILL) + 1
                if len(IDS) < col <= len(IDS) + len(fills):
                    cell.fill = FILL_CELL[(k - 1) % 2]
                if x == 0:
                    cell.border = NEW_TRAJECTORY
            ws.row_dimensions[r].height = 27        # two lines; longer text is clipped
    for col, name in enumerate(names, 1):
        letter = ws.cell(row=1, column=col).column_letter
        ws.column_dimensions[letter].width = WIDTH[name.split(" ", 1)[1]] \
            if name.startswith("A") and name[1:2].isdigit() else WIDTH[name]
        base = name.split(" ", 1)[1] if name in fills else name
        ws.cell(row=1, column=col).comment = Comment(MEANING[base], "codebook")
    for k in range(1, annotators + 1):              # each annotator's columns fold together
        lo = len(IDS) + (k - 1) * len(TO_FILL) + 1
        ws.column_dimensions.group(ws.cell(row=1, column=lo).column_letter,
                                   ws.cell(row=1, column=lo + len(TO_FILL) - 1).column_letter,
                                   outline_level=1, hidden=False)
        _list(ws, f"{ws.cell(row=1, column=lo).column_letter}2:"
                  f"{ws.cell(row=1, column=lo).column_letter}{r}", list(phase.PHASES), "phase")
        _list(ws, f"{ws.cell(row=1, column=lo + 1).column_letter}2:"
                  f"{ws.cell(row=1, column=lo + 1).column_letter}{r}",
              list(lookup.CATEGORIES) + ["NEW"], "category")
    ws.freeze_panes = ws.cell(row=2, column=len(IDS) + len(fills) + 1).coordinate
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(names)).column_letter}{r}"
    return first


def reference_tabs(wb) -> None:
    _tables(wb.create_sheet("Phases"), "The five phases", [
        ("Every action belongs to exactly one phase; a phase can come back later.", [
            "The first fix is the first edit of a source file, even when the tool reports an "
            "error for it. fix_stage marks every row before it (pre-fix) and from it on "
            "(post-fix)."], ["phase", "the agent is…", "typical rows", "where"],
         [[k, *v] for k, v in lookup.PHASE_TEXT.items()]),
    ], [16, 34, 90, 22])
    _tables(wb.create_sheet("Final lookup table"), "Final lookup table", [
        ("Action to Action Category Mapping Table", [],
         ["Category", "Shell Commands", "Native tools"],
         [list(r) for r in lookup.ACTION_TABLE]
         + [[lookup.SHELL_RUNNER_ROW[0], "", lookup.SHELL_RUNNER_ROW[1]],
            [lookup.IGNORED_ROW[0], lookup.IGNORED_ROW[1], ""],
            [lookup.COMPOUND_ROW[0], lookup.COMPOUND_ROW[1], ""]]),
        ("Action Category to Phases Mapping Table. Use the first row that matches.",
         [f"General rule: {lookup.GENERAL_RULE}"],
         ["#", "Phases", "Action Category", "Target file", "Position/Rules"],
         [[n, ph.capitalize() if ph != lookup.PREVIOUS else ph, cats, target, where]
          for n, (_, ph, cats, target, where) in enumerate(lookup.PHASE_TABLE, 1)]),
        ("File to Target File Mapping Table", [], ["Target file", "Files"],
         [[name, files] for _, name, files in lookup.TARGET_TABLE]),
        ("Thoughts and results", [], ["topic", "what to do"],
         [list(r) for r in EVIDENCE_TEXT]),
    ], [22, 70, 50, 34, 60])


def changes_tab(ws) -> None:
    head = ["date", "annotator", "trajectory", "action", "kind", "proposal",
            "why the tables cannot express it", "decision (lead)", "codebook version"]
    _header(ws, head, [FILL_HEAD[0]] * 7 + [GIVEN_HEAD] * 2)
    for col, w in zip("ABCDEFGHI", (11, 9, 9, 7, 18, 50, 50, 25, 10)):
        ws.column_dimensions[col].width = w
    _list(ws, "E2:E200", CHANGE_KINDS, "change kind")
    ws.freeze_panes = "A2"


def write_workbook(path: Path, sample: List[dict], rows: Dict[str, List[dict]],
                   annotators: int = 2, labels: Optional[Dict[int, Dict[str, list]]] = None) -> None:
    wb = Workbook()
    start = wb.active
    first = annotation_tab(wb.create_sheet("Annotation"), sample, rows, annotators, labels or {})
    start_tab(start, sample, {t: len(r) for t, r in rows.items()}, first, annotators)
    reference_tabs(wb)
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
    _header(ws, cols + status, [GIVEN_HEAD] * len(cols) + [FILL_HEAD[0]] * len(status))
    for i, p in enumerate(sample, 2):
        for col, v in enumerate([p["tab"], p["round"], p["agent"], int(p["bug"]),
                                 counts[p["tab"]]] + [0] * (annotators + 1) + [None], 1):
            cell = ws.cell(row=i, column=col, value=v)
            cell.font = BODY
            if col > len(cols):
                cell.fill = FILL_CELL[0]
    ws.freeze_panes = "A2"
    wb.save(path)


def _labels(specs: List[str], sample: List[dict]) -> Dict[int, Dict[str, list]]:
    """--labels PATH[:K] -> {K: {tab: rows}}."""
    out: Dict[int, Dict[str, list]] = {}
    for spec in specs or []:
        path, _, k = spec.rpartition(":") if re.search(r":\d+$", spec) else (spec, "", "1")
        out[int(k)] = read_labels(Path(path), sample)
        print(f"labels of annotator {k} from {Path(path).name}: {', '.join(out[int(k)]) or 'none'}")
    return out


def workbook_only(out: Path, annotators: int, label_specs: List[str]) -> int:
    """Rewrite the workbook from the existing sample and atif/ copies."""
    with SAMPLE.open(newline="") as handle:
        sample = list(csv.DictReader(handle))
    rows: Dict[str, List[dict]] = {}
    for p in sample:
        src = out / "atif" / f"{p['tab']}_bug-{p['bug']}_{p['agent']}.atif.json"
        rows[p["tab"]] = sheet_rows(json.loads(src.read_text()), p["bug"])
        if len(rows[p["tab"]]) != int(p["actions"]):
            raise SystemExit(f"{p['tab']}: {len(rows[p['tab']])} actions, the sample says "
                             f"{p['actions']}")
    write_workbook(out / WORKBOOK, sample, rows, annotators, _labels(label_specs, sample))
    print(f"wrote {out / WORKBOOK}: {sum(len(r) for r in rows.values())} actions in "
          f"{len(sample)} trajectories")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=corpus.DEFAULT_CONFIG, choices=corpus.CONFIGS)
    ap.add_argument("--run", type=int, default=1, choices=corpus.RUNS)
    ap.add_argument("--annotators", type=int, default=2)
    ap.add_argument("--per-agent", type=int, default=5)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--overwrite", action="store_true",
                    help="rebuild an existing output folder (its workbook and atif/ are replaced)")
    ap.add_argument("--workbook-only", action="store_true",
                    help="rewrite only the workbook, from the existing sample and atif/ copies")
    ap.add_argument("--labels", action="append", metavar="PATH[:K]",
                    help="copy the labels of an earlier one-tab-per-trajectory workbook into the "
                         "columns of annotator K (default 1)")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    if args.workbook_only:
        return workbook_only(out, args.annotators, args.labels)
    if out.exists() and any(p.name != "README.md" for p in out.iterdir()) and not args.overwrite:
        print(f"{out} is not empty; pass --overwrite to rebuild it", file=sys.stderr)
        return 2
    rows_frame = frame(args.config, args.run)
    sample = draw(rows_frame, args.per_agent, args.seed)
    if out.exists():
        shutil.rmtree(out / "atif", ignore_errors=True)
        for name in (WORKBOOK,) + OLD_WORKBOOKS:    # never an annotator's own copy
            (out / name).unlink(missing_ok=True)
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
    for p in sample:
        p["actions"] = counts[p["tab"]]
    write_workbook(out / WORKBOOK, sample, rows, args.annotators, _labels(args.labels, sample))
    write_tracker(out / "tracker.xlsx", sample, args.annotators, counts)
    with SAMPLE.open("w", newline="") as f:
        cols = ["tab", "round", "agent", "bug", "app", "outcome", "allocation", "actions",
                "config", "run", "seed"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in sample:
            w.writerow({**p, "config": args.config, "run": args.run, "seed": args.seed})
    print(f"{args.config}, run {args.run}: frame {len(rows_frame)} trajectories -> {out}")
    for p in sample:
        print(f"  {p['tab']} round {p['round']}  {p['agent']:6s} bug-{p['bug']:7s} "
              f"{p['app']:13s} {p['outcome']:4s} {counts[p['tab']]:4d} actions  "
              f"(agent split {p['allocation']})")
    print(f"  {sum(counts.values())} actions in {len(sample)} trajectories; one workbook, "
          f"{args.annotators} annotators")
    return 0


if __name__ == "__main__":
    sys.exit(main())
