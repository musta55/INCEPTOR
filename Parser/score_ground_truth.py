"""Score the phase annotation of the Ground Truth kit against the automated labelling
(Annotation Codebook.docx §11.1; Phase taxonomy.md §9).

Reads the annotators' filled workbooks (download each annotator's copy from Drive) and, once
the disagreements are settled, the reference workbook (the third copy with the agreed
labels). Computes the tool's labels on the same 15 trajectories (``Ground Truth/atif/``, the
files the annotators read), and reports:

  1. agreement between the annotators, the ceiling: per-row accuracy and Cohen's kappa on
     the phase, boundary F1 exact and within one row, WindowDiff, and the Levenshtein
     distance between the phase sequences (the order of the stretches; ``atif/agreement.py``);
  2. the tool against the reference (or, before adjudication, against each annotator), with
     the baselines B1-B3 and the ablations without K1 and without P4; round 2 is the scored
     set, round 1 the development set the codebook was tuned on;
  3. the accuracy of the action categories (Table 2): the share of rows without a category_fix;
  4. the subphase outcomes: precision per outcome, from the audit sheet this script writes
     on its first run (one row per tool subphase; fill in ``correct``).

A workbook tab counts once its first row has a phase and every phase it holds is one of the
five; the rows below a phase take it until the next one (a stretch is a maximal run of one
phase, so writing the same phase again does not start a new stretch). Tabs that are empty or
incomplete are listed and left out.

Writes into ``--out`` (default ``data/ground_truth/``), never into ``Ground Truth/``, whose
files the annotators see:

  tool_labels.csv      one row per action of the 15 trajectories: the tool's phase, own phase,
                       subphase, outcome, evidence and attempt, and the baselines' phases
  rows.csv             the same rows with each workbook's phase and category_fix beside them
  disagreements.csv    for the adjudication meeting: the rows where the two annotators differ
                       on the phase or the category_fix, with no tool label (so the reference
                       stays blind to the tool)
  scores.json          every number of the report
  report.md            the report (also printed)
  subphase_audit.xlsx  the outcome audit sheet; written only when missing, never overwritten

Usage: python3 score_ground_truth.py [--annotator PATH ...] [--reference PATH] [--out DIR]
       (defaults: Ground Truth/annotator_1.xlsx and annotator_2.xlsx, no reference)
"""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from atif import agreement, baselines, phase, segment, taxonomy

HERE = Path(__file__).resolve().parent
KIT = HERE / "Ground Truth"
SAMPLE = HERE / "ground_truth_sample.csv"
OUT = HERE / "data" / "ground_truth"
METHODS = [("tool", "phase taxonomy (P1-P4)"), ("B1", "B1 V2 first-edit split"),
           ("B2", "B2 P1 table only"), ("B3", "B3 old purposes"),
           ("no_K1", "ablation: without K1"), ("no_P4", "ablation: without P4")]
ROUND_NAME = {"2": "round 2 (scored)", "1": "round 1 (development)"}
AUDIT_COLUMNS = ["tab", "agent", "bug", "round", "phase", "subphase", "first action",
                 "last action", "outcome", "evidence", "checks in it", "correct", "should be",
                 "notes"]


# ----------------------------------------------------------------------------- inputs
def load_sample(path: Path = SAMPLE) -> List[dict]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["actions"] = int(row["actions"])
    return rows


def _trajectory(entry: dict) -> dict:
    path = KIT / "atif" / f"{entry['tab']}_bug-{entry['bug']}_{entry['agent']}.atif.json"
    return json.loads(path.read_text(encoding="utf-8"))


def tool_labels(sample: List[dict]) -> Dict[str, dict]:
    """{tab: {"rows": action_labels, "acts": prepared rows, "result": phase result,
    method: [phase per action] for every METHODS key}}."""
    out: Dict[str, dict] = {}
    for entry in sample:
        traj, bug = _trajectory(entry), entry["bug"]
        result = phase.phases(traj, bug)
        rows = phase.action_labels(result)
        seg = segment.segment(traj, bug)
        labels = {
            "tool": [r["phase"] for r in rows],
            "B1": baselines.first_edit_split(segment.prepare(traj, bug)),
            "B2": phase.assign(segment.prepare(traj, bug), keep_rules=False,
                               smoothing=False)["phase"],
            "B3": baselines.old_purposes(seg["actions"], seg["hierarchy"]),
            "no_K1": phase.assign(segment.prepare(traj, bug), keep_rules=False)["phase"],
            "no_P4": phase.assign(segment.prepare(traj, bug), smoothing=False)["phase"],
        }
        for name, values in labels.items():
            if len(values) != entry["actions"]:
                raise SystemExit(f"{entry['tab']}: {name} labels {len(values)} actions, the sample "
                                 f"says {entry['actions']}")
        out[entry["tab"]] = {"rows": rows, "acts": result["actions"], "result": result, **labels}
    return out


def _sheet(wb, tab: str):
    for name in wb.sheetnames:
        if name == tab or name.startswith(tab + " "):
            return wb[name]
    return None


def read_workbook(path: Path, sample: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    """({tab: {"status", "phase" (forward-filled), "category_fix", "notes"}}, problems)."""
    wb = load_workbook(path, data_only=True)
    tabs: Dict[str, dict] = {}
    problems: List[str] = []
    for entry in sample:
        tab, n = entry["tab"], entry["actions"]
        ws = _sheet(wb, tab)
        if ws is None:
            problems.append(f"{tab}: no such tab")
            tabs[tab] = {"status": "missing"}
            continue
        head = {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}
        if not {"phase", "category_fix", "category"} <= set(head):
            problems.append(f"{tab}: the header row lacks phase, category_fix or category")
            tabs[tab] = {"status": "invalid"}
            continue
        given = [ws.cell(row=r, column=head["category"]).value for r in range(2, ws.max_row + 1)]
        n_rows = len([v for v in given if v not in (None, "")])
        if n_rows != n:
            problems.append(f"{tab}: {n_rows} action rows, the trajectory has {n} "
                            f"(rows inserted or deleted?)")
            tabs[tab] = {"status": "invalid"}
            continue

        def column(name: str) -> List[str]:
            if name not in head:
                return [""] * n
            return [str(ws.cell(row=r, column=head[name]).value or "").strip()
                    for r in range(2, n + 2)]

        marks, fixes, notes = column("phase"), column("category_fix"), column("notes")
        filled: List[Optional[str]] = []
        current: Optional[str] = None
        bad = False
        for k, mark in enumerate(marks, 1):
            if mark:
                if mark.lower() in phase.PHASES:
                    current = mark.lower()
                else:
                    problems.append(f"{tab} row {k}: '{mark}' is not a phase")
                    bad = True
            filled.append(current)
        for k, fix in enumerate(fixes, 1):
            if fix and fix not in taxonomy.CATEGORIES:
                problems.append(f"{tab} row {k}: category_fix '{fix}' is not a category")
        if not any(marks):
            status = "empty"
        elif bad or not marks[0]:
            status = "incomplete"
            if not marks[0]:
                problems.append(f"{tab}: the first row has no phase")
        else:
            status = "complete"
        tabs[tab] = {"status": status, "phase": filled, "category_fix": fixes, "notes": notes}
    return tabs, problems


# ----------------------------------------------------------------------------- measures
def _fmt(x: float, pct: bool = False) -> str:
    if x != x:                                                          # nan
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.2f}"


def measure(pairs: agreement.Pairs) -> Dict[str, Any]:
    out = agreement.compare(pairs)
    out["kappa_ci95"] = agreement.bootstrap(pairs, agreement.pooled_kappa)
    out["boundary_tol1_f1_ci95"] = agreement.bootstrap(pairs, agreement.pooled_boundary_f1(1))
    return out


def _row(name: str, m: Dict[str, Any], coverage: bool = False) -> str:
    lo, hi = m["kappa_ci95"]
    ci = f" [{_fmt(lo)}, {_fmt(hi)}]" if lo == lo else ""
    cells = [name, str(m["trajectories"]), str(m["actions"])]
    if coverage:
        cells.append(_fmt(m["coverage"], True))
    cells += [_fmt(m["accuracy"], True), _fmt(m["kappa"]) + ci,
              _fmt(m["boundary_tol0"]["f1"]), _fmt(m["boundary_tol1"]["f1"]),
              _fmt(m["window_diff"]), f"{_fmt(m['sequence']['normalized'])} "
              f"({m['sequence']['edit_distance']:.1f})", _fmt(m["sequence"]["identical"], True)]
    return "| " + " | ".join(cells) + " |"


HEAD = ("| {} | trajectories | actions |{} accuracy | kappa [95% CI] | boundary F1 exact "
        "| boundary F1 ±1 | WindowDiff | sequence distance (edits) | same sequence |")


def _head(first: str, coverage: bool = False) -> List[str]:
    line = HEAD.format(first, " coverage |" if coverage else "")
    return [line, "|" + "---|" * (line.count("|") - 1)]


def pairs_for(tabs: List[str], ref: Dict[str, List], hyp: Dict[str, List]) -> agreement.Pairs:
    return [(ref[t], hyp[t]) for t in tabs]


# ----------------------------------------------------------------------------- audit sheet
def write_audit(path: Path, sample: List[dict], tool: Dict[str, dict]) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "subphases"
    ws.append(AUDIT_COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="FFFF00" if c.value in ("correct", "should be", "notes")
                             else "D9D9D9")
    n = 0
    for entry in sample:
        t = tool[entry["tab"]]
        acts = t["acts"]
        for s in t["result"]["phases"]:
            for sp in s["subphases"]:
                checks = [f"{acts[x]['action_index']}: {acts[x]['category']} {acts[x]['verdict']}"
                          + (f" ({acts[x]['fail_kind']})" if acts[x]["fail_kind"] else "")
                          for x in range(sp["_lo"], sp["_hi"]) if acts[x]["verdict"] in ("pass", "fail")]
                ws.append([entry["tab"], entry["agent"], entry["bug"], entry["round"], s["phase"],
                           sp["id"], sp["start"], sp["end"], sp["outcome"], sp["evidence"],
                           "; ".join(checks), None, None, None])
                n += 1
    yes = DataValidation(type="list", formula1='"1,0"', allow_blank=True)
    yes.add(f"L2:L{n + 1}")
    should = DataValidation(type="list", formula1='"' + ",".join(phase.OUTCOMES) + '"', allow_blank=True)
    should.add(f"M2:M{n + 1}")
    ws.add_data_validation(yes)
    ws.add_data_validation(should)
    for col, width in zip("ABCDEFGHIJKLMN", (6, 8, 8, 6, 14, 9, 7, 7, 11, 11, 60, 8, 11, 30)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        row[10].alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    note = wb.create_sheet("how to fill")
    for line in ["One row per subphase the tool computed for the 15 trajectories.",
                 "Actions are numbered as the workbook rows: action k is sheet line k + 1 of the "
                 "trajectory tab.",
                 "Check the outcome against the verdict and fail_kind columns of those rows "
                 "('checks in it' lists the build and test runs of the subphase) and the codebook's "
                 "Table 6.",
                 "correct: 1 when the outcome is right, 0 when it is wrong. should be: the right "
                 "outcome, when it is wrong. notes: why, or a remark on the evidence.",
                 "score_ground_truth.py reports precision per outcome from the rows with a 1 or 0. "
                 "It never overwrites this file; delete it to get a fresh one."]:
        note.append([line])
    note.column_dimensions["A"].width = 120
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return n


def read_audit(path: Path, tool: Dict[str, dict]) -> Tuple[Dict[str, Any], List[str]]:
    wb = load_workbook(path, data_only=True)
    ws = wb["subphases"]
    head = [str(c.value) for c in ws[1]]
    col = {name: head.index(name) for name in AUDIT_COLUMNS if name in head}
    current = {(tab, sp["id"]): (sp["start"], sp["end"], sp["outcome"])
               for tab, t in tool.items() for s in t["result"]["phases"] for sp in s["subphases"]}
    judged: Dict[str, List[int]] = {o: [0, 0] for o in phase.OUTCOMES}
    wrong_as: Dict[str, Dict[str, int]] = {o: {} for o in phase.OUTCOMES}
    problems: List[str] = []
    total = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[col["tab"]] is None:
            continue
        total += 1
        key = (str(row[col["tab"]]), str(row[col["subphase"]]))
        seen = (row[col["first action"]], row[col["last action"]], row[col["outcome"]])
        mark = row[col["correct"]]
        if mark in (None, ""):
            continue
        if current.get(key) != seen:
            problems.append(f"audit {key[0]} {key[1]}: the tool's subphase changed since the sheet "
                            f"was written; left out")
            continue
        outcome = seen[2]
        if str(mark).strip() in ("1", "1.0"):
            judged[outcome][0] += 1
        elif str(mark).strip() in ("0", "0.0"):
            judged[outcome][1] += 1
            should = str(row[col["should be"]] or "?")
            wrong_as[outcome][should] = wrong_as[outcome].get(should, 0) + 1
        else:
            problems.append(f"audit {key[0]} {key[1]}: correct is '{mark}', not 1 or 0")
    result = {"subphases": total,
              "judged": sum(a + b for a, b in judged.values()),
              "per_outcome": {o: {"correct": a, "wrong": b,
                                  "precision": a / (a + b) if a + b else float("nan"),
                                  "should_be": wrong_as[o]}
                              for o, (a, b) in judged.items()}}
    return result, problems


# ----------------------------------------------------------------------------- report
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--annotator", action="append", metavar="PATH",
                    help="an annotator's filled workbook; give it once per annotator "
                         "(default: Ground Truth/annotator_1.xlsx and annotator_2.xlsx)")
    ap.add_argument("--reference", metavar="PATH",
                    help="the adjudicated workbook with the agreed labels")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    paths = [Path(p) for p in (args.annotator or [KIT / "annotator_1.xlsx", KIT / "annotator_2.xlsx"])]
    out = Path(args.out)
    if out.resolve() == KIT.resolve() or KIT.resolve() in out.resolve().parents:
        raise SystemExit("--out must not be inside Ground Truth/: the annotators read that folder")
    sample = load_sample()
    tool = tool_labels(sample)
    rounds = {e["tab"]: e["round"] for e in sample}
    agents = {e["tab"]: e["agent"] for e in sample}

    books: Dict[str, Dict[str, dict]] = {}
    problems: List[str] = []
    for k, path in enumerate(paths, 1):
        books[f"A{k}"], issues = read_workbook(path, sample)
        problems += [f"A{k} ({path.name}): {p}" for p in issues]
    if args.reference:
        books["reference"], issues = read_workbook(Path(args.reference), sample)
        problems += [f"reference: {p}" for p in issues]
    done = {name: [e["tab"] for e in sample if book[e["tab"]]["status"] == "complete"]
            for name, book in books.items()}
    phases_of = {name: {t: book[t]["phase"] for t in done[name]} for name, book in books.items()}
    method_labels = {m: {t: tool[t][m] for t in tool} for m, _ in METHODS}

    scores: Dict[str, Any] = {"generated": date.today().isoformat(),
                              "inputs": {name: str(p) for name, p in
                                         zip(list(books), paths + ([Path(args.reference)] if args.reference else []))},
                              "complete_tabs": done}
    lines = [f"# Ground-truth scores ({scores['generated']})", ""]
    lines += ["Labelled tabs: " + "; ".join(f"{name} {len(done[name])}/{len(sample)}" for name in books),
              "", "Tool: `atif.phase` with ABSORB_MAX=%d, on `Ground Truth/atif/`." % phase.ABSORB_MAX,
              "", "Sequence distance: Levenshtein distance between the phase sequences (the order "
              "of the stretches, ignoring their lengths), divided by the longer sequence, mean over "
              "trajectories (0 = same order); the mean number of edits is in brackets. Same sequence: "
              "share of trajectories whose phase sequences are identical.", ""]

    def sets(tabs: List[str]) -> List[Tuple[str, List[str]]]:
        out_sets = [(ROUND_NAME[r], [t for t in tabs if rounds[t] == r]) for r in ("2", "1")]
        out_sets.append(("all", list(tabs)))
        return [(n, ts) for n, ts in out_sets if ts]

    # 1. annotators
    annot = [n for n in books if n != "reference"]
    lines += ["## 1. Agreement between the annotators (the ceiling)", ""]
    scores["annotators"] = {}
    if len(annot) >= 2:
        a, b = annot[0], annot[1]
        both = [t for t in done[a] if t in done[b]]
        if both:
            lines += _head("set")
            for name, ts in sets(both):
                m = measure(pairs_for(ts, phases_of[a], phases_of[b]))
                scores["annotators"][name] = m
                lines.append(_row(name, m))
            lines.append("")
        else:
            lines += ["No tab is labelled in both workbooks yet.", ""]
    else:
        lines += ["Give two annotator workbooks to measure their agreement.", ""]

    # 2. tool and baselines
    if "reference" in books:
        targets = [("reference", phases_of["reference"], done["reference"])]
        lines += ["## 2. The tool against the reference", ""]
    else:
        targets = [(n, phases_of[n], done[n]) for n in annot]
        lines += ["## 2. The tool against each annotator (no reference yet)", "",
                  "Before adjudication the tool is compared with each annotator separately; "
                  "the scored comparison is against the reference workbook (`--reference`).", ""]
    scores["methods"] = {}
    headline: Optional[Tuple[str, str, List[str]]] = None
    for target, ref, tabs in targets:
        for set_name, ts in sets(tabs):
            if set_name == "all":
                continue
            lines += [f"**{target}, {set_name}**", ""] + _head("method", coverage=True)
            for m_key, m_name in METHODS:
                m = measure(pairs_for(ts, ref, method_labels[m_key]))
                scores["methods"].setdefault(target, {}).setdefault(set_name, {})[m_key] = m
                lines.append(_row(m_name, m, coverage=True))
            lines.append("")
            if headline is None or (headline[0] == target and set_name.startswith("round 2")):
                headline = (target, set_name, ts)
    if headline:
        target, set_name, ts = headline
        ref = next(r for n, r, _ in targets if n == target)
        pairs = pairs_for(ts, ref, method_labels["tool"])
        per = agreement.per_label(pairs, phase.PHASES)
        conf = agreement.confusion(pairs)
        scores["tool_per_phase"] = {"target": target, "set": set_name, "per_phase": per,
                                    "confusion": {f"{r} -> {h}": v for (r, h), v in conf.items()}}
        lines += [f"**The tool per phase ({target}, {set_name})**", "",
                  "| phase | precision | recall | F1 | rows in the reference |", "|---|---|---|---|---|"]
        for p in phase.PHASES:
            x = per[p]
            lines.append(f"| {p} | {_fmt(x['precision'])} | {_fmt(x['recall'])} | {_fmt(x['f1'])} | {x['support']} |")
        lines += ["", "Confusion (rows: " + target + ", columns: tool)", "",
                  "| | " + " | ".join(phase.PHASES) + " |", "|---|" + "---|" * len(phase.PHASES)]
        for r in phase.PHASES:
            lines.append(f"| {r} | " + " | ".join(str(conf.get((r, h), 0)) for h in phase.PHASES) + " |")
        lines += ["", f"**The tool by agent ({target}, {set_name})**", ""] + _head("agent")
        scores["tool_by_agent"] = {}
        for agent in ("claude", "codex", "qwen"):
            mine = [t for t in ts if agents[t] == agent]
            if mine:
                m = measure(pairs_for(mine, ref, method_labels["tool"]))
                scores["tool_by_agent"][agent] = m
                lines.append(_row(agent, m))
        lines.append("")

    # 3. categories
    lines += ["## 3. Action categories (Table 2)", "",
              "| workbook | rows | rows with a category_fix | accuracy of the categories | most frequent fixes |",
              "|---|---|---|---|---|"]
    scores["categories"] = {}
    fixes_of: Dict[str, Dict[Tuple[str, int], str]] = {}
    for name, book in books.items():
        rows = 0
        fixes_of[name] = {}
        for t in done[name]:
            for k, fix in enumerate(book[t]["category_fix"]):
                rows += 1
                given = tool[t]["rows"][k]["category"]
                if fix == given:
                    problems.append(f"{name} {t} row {k + 1}: category_fix repeats the given "
                                    f"category {given}; not counted as a fix")
                elif fix in taxonomy.CATEGORIES:
                    fixes_of[name][(t, k)] = fix
        fixed = len(fixes_of[name])
        acc = 1 - fixed / rows if rows else float("nan")
        pairs_fixed: Dict[str, int] = {}
        for (t, k), fix in fixes_of[name].items():
            key = f"{tool[t]['rows'][k]['category']} -> {fix}"
            pairs_fixed[key] = pairs_fixed.get(key, 0) + 1
        scores["categories"][name] = {"rows": rows, "fixed": fixed, "accuracy": acc,
                                      "fixes": pairs_fixed}
        top = sorted(pairs_fixed.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        lines.append(f"| {name} | {rows} | {fixed} | {_fmt(acc, True)} | "
                     + (", ".join(f"{k} ({v})" for k, v in top) or "–") + " |")
    lines.append("")
    if len(annot) >= 2:
        a, b = annot[0], annot[1]
        shared = [t for t in done[a] if t in done[b]]
        fa = {key for key in fixes_of[a] if key[0] in shared}
        fb = {key for key in fixes_of[b] if key[0] in shared}
        same = sum(1 for key in fa & fb if fixes_of[a][key] == fixes_of[b][key])
        scores["categories"]["annotators"] = {"fixed_by_" + a: len(fa), "fixed_by_" + b: len(fb),
                                              "fixed_by_both": len(fa & fb), "same_fix": same}
        lines += [f"On the tabs both labelled, {a} fixed {len(fa)} rows and {b} {len(fb)}; both "
                  f"fixed {len(fa & fb)}, with the same category on {same}. Rows only one "
                  f"annotator fixed go to the adjudication meeting like phase disagreements.", ""]

    # 4. subphase audit
    audit_path = out / "subphase_audit.xlsx"
    lines += ["## 4. Subphase outcomes (audit)", ""]
    if not audit_path.is_file():
        n = write_audit(audit_path, sample, tool)
        lines += [f"Wrote `{audit_path.relative_to(HERE) if HERE in audit_path.parents else audit_path}` "
                  f"with {n} subphases. Fill in `correct` (1 / 0) and run this script again.", ""]
    else:
        audit, issues = read_audit(audit_path, tool)
        problems += issues
        scores["audit"] = audit
        lines += [f"{audit['judged']} of {audit['subphases']} subphases judged.", "",
                  "| outcome | correct | wrong | precision | wrong ones should be |", "|---|---|---|---|---|"]
        for o, x in audit["per_outcome"].items():
            lines.append(f"| {o} | {x['correct']} | {x['wrong']} | {_fmt(x['precision'])} | "
                         + (", ".join(f"{k} {v}" for k, v in x["should_be"].items()) or "–") + " |")
        lines.append("")

    if problems:
        lines += ["## Problems in the workbooks", ""] + [f"- {p}" for p in problems] + [""]
    scores["problems"] = problems

    # files
    out.mkdir(parents=True, exist_ok=True)
    tool_cols = ["tab", "round", "agent", "bug", "action", "category", "file_role", "fix_stage",
                 "tool_phase", "own_phase", "subphase", "subphase_outcome", "subphase_evidence",
                 "attempt"] + [m for m, _ in METHODS if m != "tool"]
    human_cols = [f"{name}_{c}" for name in books for c in ("phase", "category_fix", "notes")]
    with (out / "tool_labels.csv").open("w", newline="") as h1, (out / "rows.csv").open("w", newline="") as h2:
        w1, w2 = csv.writer(h1), csv.writer(h2)
        w1.writerow(tool_cols)
        w2.writerow(tool_cols + human_cols)
        for e in sample:
            t = tool[e["tab"]]
            for k, r in enumerate(t["rows"]):
                base = [e["tab"], e["round"], e["agent"], e["bug"], k + 1, r["category"], r["file_role"],
                        r["fix_stage"], r["phase"], r["own_phase"], r["subphase"], r["subphase_outcome"],
                        r["subphase_evidence"], r["attempt"]] + [t[m][k] or "" for m, _ in METHODS if m != "tool"]
                human = []
                for name, book in books.items():
                    b = book[e["tab"]]
                    if b.get("status") in ("complete", "incomplete", "empty"):
                        human += [b["phase"][k] or "", b["category_fix"][k], b["notes"][k]]
                    else:
                        human += ["", "", ""]
                w1.writerow(base)
                w2.writerow(base + human)
    n_disagree = 0
    if len(annot) >= 2:
        a, b = annot[0], annot[1]
        with (out / "disagreements.csv").open("w", newline="") as handle:
            w = csv.writer(handle)
            w.writerow(["tab", "action", "sheet line", "category", "target", f"{a}_phase",
                        f"{b}_phase", f"{a}_category_fix", f"{b}_category_fix", f"{a}_notes",
                        f"{b}_notes"])
            for e in sample:
                t = e["tab"]
                if t not in done[a] or t not in done[b]:
                    continue
                ba, bb = books[a][t], books[b][t]
                for k, act in enumerate(tool[t]["acts"]):
                    if ba["phase"][k] != bb["phase"][k] or ba["category_fix"][k] != bb["category_fix"][k]:
                        n_disagree += 1
                        w.writerow([t, k + 1, k + 2, act["category"], " ".join(str(act["target"]).split())[:200],
                                    ba["phase"][k], bb["phase"][k], ba["category_fix"][k],
                                    bb["category_fix"][k], ba["notes"][k], bb["notes"][k]])
        lines.insert(lines.index("## 2. The tool against the reference") if "## 2. The tool against the reference" in lines
                     else next(i for i, l in enumerate(lines) if l.startswith("## 2.")),
                     f"Rows to settle in the adjudication meeting: {n_disagree} (`disagreements.csv`, "
                     f"no tool labels in it).\n")
    (out / "scores.json").write_text(json.dumps(scores, indent=1, default=str), encoding="utf-8")
    report = "\n".join(lines)
    (out / "report.md").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nwrote {out}/: tool_labels.csv, rows.csv, scores.json, report.md"
          + (", disagreements.csv" if len(annot) >= 2 else "")
          + (", subphase_audit.xlsx" if audit_path.is_file() else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
