"""The viewer datasets ``trajview/3`` and ``trajview-overview/3`` (``Parser/View data contract.md``).

    python3 -m atif.cli view --all      # -> Parser/viewer/data/overview.js + data/bugs/bug-<id>.js

The viewer shows one prompt configuration (``original`` by default) at two levels, so no
page has to load the whole corpus:

``viewer/data/overview.js``         ``window.TRAJ_OVERVIEW = {...};`` -- one run (run 1) of
                                    every bug x agent, summaries only (no per-action text),
                                    plus every bug's pass/fail in each run from the outcome CSVs;
``viewer/data/bugs/bug-<id>.js``    ``window.TRAJ_BUG = {...};`` -- the bug's trajectories in
                                    full (3 agents x 3 runs), for ``viewer/bug.html``;
``viewer/data/atif/run<k>/bug-<id>.json.gz``  the same trajectories as converted ATIF
                                    (``write_packs``), which the viewer re-runs when the user
                                    sets rules of their own.

Both are JavaScript statements, not JSON, so the pages work from ``file://`` (where
``fetch()`` of a local file is blocked): ``bug.html`` loads a bug by injecting a
``<script>`` tag.  Built from the converted ATIF files (``convert`` first), the phase
taxonomy (``atif.phase``: phases -> outcome subphases, attempts, metrics), the badges and
outcomes (``atif.outcomes``) and the codebook's tables (``atif.codebook``), which the viewer
quotes in its tooltips.

Fields beyond the contract (the viewer must ignore what it does not know): ``model``,
``outcome.by_config``, ``badges.self_report``, ``badge_steps``, ``stats.reported_duration_s``
(the log's own ``duration_ms``; Claude and Qwen steps carry no timestamps, so ``duration_s``
is null for them), the actions' ``thought_source``, ``edits`` and ``cmd``, the
``evidence`` and ``evidence_line`` of an action with a verdict (which marker decided it, and
the result's line with that marker: ``BUILD SUCCESSFUL in 1m 55s``), and the subphases'
``checks`` (the action indexes that decided the outcome; a repair attempt's judging run may
come after the subphase).

Text policy: ``thought`` and ``result`` are whitespace-collapsed and cut to 300 characters,
``target`` to 200.  ``thought`` is the reasoning or narration of the LLM step that issued
the call, so parallel calls of one step repeat it.  The full texts stay in the ATIF (the
corpus packs, ``write_packs``), which the viewer's details panel reads on demand.
"""
from __future__ import annotations

import collections
import gzip
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import codebook, corpus, lookup, outcomes, phase, project, rules, schema, segment, taxonomy, \
    verdict
from .corpus import Key

SCHEMA = "trajview/3"
OVERVIEW_SCHEMA = "trajview-overview/3"
#: one bug's converted ATIF in one run, for the viewer to re-run under the user's rules
PACK_SCHEMA = "trajectiers-pack/1"
THOUGHT_CHARS = 300
RESULT_CHARS = 300
TARGET_CHARS = 200
#: the files an action names, and the files a search's output lists (``files``, ``found``)
FILES_MAX = 12
FOUND_MAX = 20
BUG_VAR = "window.TRAJ_BUG"
OVERVIEW_VAR = "window.TRAJ_OVERVIEW"
#: the targets of the files an action works on (the target table), the actions' file_role
FILE_ROLES = lookup.TARGETS
_APP = re.compile(r"App package: ([A-Za-z_][\w.]*)")
_APP_ID = re.compile(r"applicationId\s*[=:]?\s*\\?[\"']([A-Za-z_][\w.]*)")
_MANIFEST = re.compile(r"<manifest[^>]*?\spackage=\\?\"([A-Za-z_][\w.]*)")
_SRC_PKG = re.compile(r"src/main/java/([a-z]\w*/\w+/\w+)/")


def _clip(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _parse_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_s(trajectory: dict) -> Optional[float]:
    """Seconds from the first to the last step timestamp; None without timestamps."""
    stamps = [t for t in (_parse_ts(s.get("timestamp") or "") for s in trajectory.get("steps", []))
              if t is not None]
    if len(stamps) < 2:
        return None
    return round((max(stamps) - min(stamps)).total_seconds(), 1)


def app_package(trajectories: List[dict]) -> Optional[str]:
    """The app under repair, pooled over a bug's trajectories: ``run_pipeline.sh``'s
    ``App package:`` line, else an ``applicationId`` or a manifest ``package=`` the agents
    read, else the most-cited three-level source package (``src/main/java/de/danoeh/
    antennapod/...`` -> ``de.danoeh.antennapod``, a heuristic); None if nothing appears."""
    for pattern in (_APP, _APP_ID, _MANIFEST, _SRC_PKG):
        counts: collections.Counter = collections.Counter()
        for trajectory in trajectories:
            for step in trajectory.get("steps", []):
                for result in (step.get("observation") or {}).get("results", []):
                    counts.update(m.replace("/", ".") for m in
                                  pattern.findall(str(result.get("content") or "")))
        counts.pop("edu.sage.android", None)        # the reproducing test project itself
        if counts:
            return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return None


def _named_files(row: dict) -> List[str]:
    """The repository files an action names (``segment.enrich``), without folders."""
    return [_clip(f, TARGET_CHARS) for f in row.get("files") or []
            if os.path.basename(f.rstrip("/")) not in ("", ".", "..")][:FILES_MAX]


def _found_files(row: dict, bug: str) -> Tuple[List[str], int]:
    """(the repository files a search's output lists, how many there are): grep, find and
    glob results, as paths relative to the repository.  Only a path that starts its line
    counts (``grep -rn`` / ``rg`` / ``find`` / ``grep -l`` output), so paths inside matched
    source lines are left out."""
    found: List[str] = []
    for line in (row.get("result") or "").splitlines():
        m = segment.PATH_RE.match(line.strip())
        if not m:
            continue
        rel = segment.repo_rel(m.group(0), bug)
        if rel and rel != "." and "*" not in rel and rel not in found:
            found.append(rel)
    return [_clip(f, TARGET_CHARS) for f in found[:FOUND_MAX]], len(found)


_TEST_FILTER = re.compile(r"--tests[ =]+[\"']?([^\s\"']+)|-e\s+class\s+([\w.$#,]+)")
_TEST_TASK = re.compile(r"\b((?:test|connected)\w*(?:UnitTest|AndroidTest)|test|check|checkstyle"
                        r"|lint\w*)\b")
_PATCH_FILE = re.compile(r"[\w.\-]+\.(?:patch|diff)\b")


def _test_names(row: dict) -> List[str]:
    """What a test run tests, by name: its test filters (``--tests``, ``-e class``), else the
    test or scratch source files it names, else its gradle test tasks (the whole suite), a
    patch it applies on trial, or the app on a device (``adb``)."""
    cmd = row.get("cmd") or row.get("target") or ""
    names = [n for m in _TEST_FILTER.finditer(cmd) for g in m.groups() if g for n in g.split(",")]
    if not names:
        names = [os.path.basename(p) for p in segment.PATH_RE.findall(cmd)
                 if p.endswith((".java", ".kt", ".py", ".sh"))]
    if not names and re.search(r"gradlew?\b", cmd):
        names = ["task " + t for t in _TEST_TASK.findall(cmd.split("|")[0])]
    if not names and re.search(r"--dry-run|apply --check", cmd):
        names = ["dry run of " + f for f in _PATCH_FILE.findall(cmd)] or ["patch dry run"]
    if not names and re.search(r"\badb\b|\$ADB\b", cmd):
        names = ["the app on a device (adb)"]
    return list(dict.fromkeys(_clip(n, 80) for n in names))[:6]


def _actions(result: Dict[str, Any], bug: str) -> List[dict]:
    """One view action per prepared row: its category and the action table's entry that gave
    it (``item``), the targets of its files (``file_role``), its phase and the phase table's
    row that gave it (``row``: L1-L15, LG for the general rule, or ``user`` for the user's
    own phase row), and ``own_patch`` when it reads back files the agent already changed;
    the files it names (``files``), those a search lists (``found``), what a test run tests
    (``tests``) and the outcome its own step shows (``step_outcome``, ``step_evidence``:
    ``phase.step_outcomes``; absent = unchecked).  Call it under ``project.use`` of the
    trajectory."""
    out: List[dict] = []
    steps = phase.step_outcomes(result)
    for x, row in enumerate(result["actions"]):
        item = {
            "i": row["action_index"], "step": row["step_id"], "scope": row["scope"],
            "tool": row["tool"], "category": row["category"], "phase": result["phase"][x],
            "target": _clip(row["target"], TARGET_CHARS),
            "file_role": lookup.action_targets(row),
            "verdict": row["verdict"], "fail_kind": row["fail_kind"],
            "failed_raw": bool(row["failed"]),
            "ts": row["timestamp"] or None,
            "thought": _clip(row["thought"], THOUGHT_CHARS),
            "thought_source": row.get("thought_source") or None,
            "result": _clip(row["result"], RESULT_CHARS),
            "call_id": row["call_id"],
        }
        if result.get("table_row"):
            item["row"] = result["table_row"][x]
        if row.get("lookup_item"):
            item["item"] = row["lookup_item"]
        if row.get("own_patch"):
            item["own_patch"] = True
        command = _clip(row.get("cmd"), TARGET_CHARS)
        if command and command != item["target"]:
            item["cmd"] = command            # the shell command, when the target is not it
        if row.get("reverts"):
            item["reverts"] = True
        if row.get("verdict_evidence") and (row["verdict"] != "none"
                                             or row["verdict_evidence"] == "no_test_evidence"):
            item["evidence"] = row["verdict_evidence"]
            line = verdict.evidence_line(row.get("result") or "", row["verdict_evidence"])
            if line:
                item["evidence_line"] = line
        edits = [_clip(f, TARGET_CHARS) for f in (row.get("edit_files") or [])][:6]
        if edits:
            item["edits"] = edits
        files = _named_files(row)
        if files:
            item["files"] = files
        if row["category"] == "search":
            found, n_found = _found_files(row, bug)
            if found:
                item["found"] = found
            if n_found > len(found):
                item["n_found"] = n_found
        if steps[x]:
            item["step_outcome"], item["step_evidence"] = steps[x]
        if row["category"] == "test":
            tests = _test_names(row)
            if tests:
                item["tests"] = tests
        out.append(item)
    return out


def _spans(result: Dict[str, Any]) -> List[dict]:
    """The phase spans with their subphases, without the private positions."""
    return [{**{k: v for k, v in s.items() if not k.startswith("_") and k != "subphases"},
             "subphases": [{k: v for k, v in sp.items() if not k.startswith("_")}
                           for sp in s["subphases"]]}
            for s in result["phases"]]


def _attempts(result: Dict[str, Any]) -> List[dict]:
    """Repair attempts by action index: first edit, edits, the run that judges them (the
    first decisive run after the edits, in the validation span that follows), last action,
    outcome and evidence; ``judge`` is null for an attempt never run."""
    index = [a["action_index"] for a in result["actions"]]
    return [{"id": at["id"], "start": index[at["start"]], "end": index[at["end"]],
             "edits": [index[x] for x in at["edits"]],
             "judge": index[at["judge"]] if at["judge"] is not None else None,
             "outcome": at["outcome"], "evidence": at["evidence"]}
            for at in result["attempts"]]


def stats(trajectory: dict, result: Dict[str, Any]) -> Dict[str, Any]:
    """Numbers for the trajectory bar and the overview cards.

    n_failed_actions   verdict fail or the log's own error flag
    anchor             action index of the first fix (the first edit of app source), or null
    The measures of the phase taxonomy (spec §8) are in the trajectory's ``metrics``."""
    acts, spans = result["actions"], result["phases"]
    reported = (trajectory.get("extra") or {}).get("duration_ms")
    return {
        "n_phases": len(spans),
        "n_subphases": sum(len(s["subphases"]) for s in spans),
        "n_attempts": len(result["attempts"]),
        "n_failed_actions": sum(1 for a in acts if a["verdict"] == "fail" or a.get("failed")),
        "anchor": result["anchor"],
        "duration_s": duration_s(trajectory),
        "reported_duration_s": round(reported / 1000.0, 1) if isinstance(reported, (int, float))
        else None,
    }


def trajectory_view(trajectory: dict, *, key: Key, app: Optional[str],
                    outcome_table: outcomes.OutcomeTable,
                    ruleset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One ``trajview/3`` trajectory: actions, phases -> subphases, attempts, metrics,
    outcome, badges, stats.  ``ruleset`` (``atif.rules``) replaces the default rules.
    Raises ValueError when it breaks a contract invariant."""
    result = phase.phases(trajectory, key.bug) if ruleset is None \
        else rules.phases(trajectory, key.bug, ruleset)
    outcome = outcomes.outcome_for(outcome_table, key.agent, key.bug, key.config, key.run)
    return build_view(trajectory, result, traj_id=corpus.traj_id(key), bug=key.bug,
                      agent=key.agent, config=key.config, run=key.run, app=app,
                      outcome={"pass": outcome["pass"], "by_run": outcome["by_run"],
                               "by_config": outcome["by_config"]})


def build_view(trajectory: dict, result: Dict[str, Any], *, traj_id: str, bug: str,
               agent: str, config: str, run: int, app: Optional[str],
               outcome: Dict[str, Any]) -> Dict[str, Any]:
    """The ``trajview/3`` trajectory of a phase result (``phase.phases`` or
    ``rules.phases``); ``outcome`` is the trajectory's ``outcome`` object."""
    badges, badge_steps = outcomes.phase_badges(trajectory, result)
    with project.use(trajectory):
        actions = _actions(result, str(bug))
    ctx = result.get("context") or {}
    obj = {
        "id": traj_id, "bug": str(bug), "agent": agent,
        "config": config, "run": int(run), "app": app,
        "model": (trajectory.get("agent") or {}).get("model_name"),
        "n_actions": len(actions),
        "n_steps": sum(1 for s in trajectory.get("steps", []) if s.get("source") == "agent"),
        "outcome": outcome,
        "badges": badges, "badge_steps": badge_steps,
        "stats": stats(trajectory, result),
        "metrics": result["metrics"],
        "anchor": result["anchor"],
        "actions": actions,
        "phases": _spans(result),
        "attempts": _attempts(result),
        "targets": {"source": ctx.get("target_source") or "none",
                    "files": sorted(ctx.get("targets") or [])[:FILES_MAX]},
    }
    check_view(obj, name=obj["id"])
    return obj


def check_view(obj: Dict[str, Any], name: str = "") -> None:
    """Raise ValueError when a ``trajview/3`` trajectory breaks an invariant of the contract
    (``View data contract.md``, "Invariants")."""
    problems: List[str] = []
    n, acts = obj["n_actions"], obj["actions"]
    if len(acts) != n or any(a["i"] != k + 1 for k, a in enumerate(acts)):
        problems.append("actions are not numbered 1..n_actions")
    pos = 1
    for s in obj["phases"]:
        if s["start"] != pos or s["end"] < s["start"] or not s["subphases"]:
            problems.append(f"{s['id']} does not continue at #{pos} or has no subphase")
        if s["phase"] not in phase.PHASES:
            problems.append(f"{s['id']} has phase {s['phase']}")
        inner = s["start"]
        for k, sp in enumerate(s["subphases"]):
            if sp["start"] != inner or sp["end"] < sp["start"]:
                problems.append(f"{sp['id']} does not continue at #{inner}")
            inner = sp["end"] + 1
            if sp["outcome"] not in phase.PHASE_OUTCOMES[s["phase"]] \
                    or sp["evidence"] not in phase.EVIDENCE \
                    or set(sp["flags"]) - set(phase.FLAGS):
                problems.append(f"{sp['id']} has a value outside the vocabulary")
            if any(not 1 <= c <= n for c in sp.get("checks", [])):
                problems.append(f"{sp['id']} names a deciding action out of range")
            if k and s["subphases"][k - 1]["outcome"] == sp["outcome"]:
                problems.append(f"{sp['id']} repeats the outcome before it")
        if inner != s["end"] + 1:
            problems.append(f"{s['id']}'s subphases end at #{inner - 1}, the span at #{s['end']}")
        for i in range(s["start"], min(s["end"], n) + 1):
            if acts[i - 1]["phase"] != s["phase"]:
                problems.append(f"action #{i} has phase {acts[i - 1]['phase']} in {s['id']}")
                break
        pos = s["end"] + 1
    if pos != n + 1:
        problems.append(f"phases cover #1..#{pos - 1} of {n} actions")
    for a in acts:
        if a["category"] not in lookup.CATEGORIES or a.get("own_phase", a["phase"]) \
                not in phase.PHASES:
            problems.append(f"action #{a['i']} has a value outside the vocabulary")
    for at in obj["attempts"]:
        if not (1 <= at["start"] <= at["end"] <= n) or at["outcome"] not in phase.OUTCOMES \
                or at["evidence"] not in phase.EVIDENCE:
            problems.append(f"attempt {at['id']} is out of range or outside the vocabulary")
    if obj["anchor"] is not None and not 1 <= obj["anchor"] <= n:
        problems.append(f"anchor #{obj['anchor']} is out of range")
    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems[:10]))


def summary_view(view: Dict[str, Any]) -> Dict[str, Any]:
    """The overview's light-weight form of a ``trajectory_view``: no actions, no text.

    ``strip`` is one ``[phase, start, end]`` per phase span and ``sub_strip`` one
    ``[outcome, start, end, phase, evidence]`` per subphase, both in action order; the
    overview draws them as the phase strip and the subphase-outcome strip of a cell."""
    by_outcome: collections.Counter = collections.Counter()
    by_phase: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for s in view["phases"]:
        for sp in s["subphases"]:
            by_outcome[sp["outcome"]] += 1
            by_phase[s["phase"]][sp["outcome"]] += 1
    return {
        "id": view["id"], "pass": view["outcome"]["pass"], "by_run": view["outcome"]["by_run"],
        "model": view.get("model"),
        "n_actions": view["n_actions"], "n_steps": view["n_steps"],
        "strip": [[s["phase"], s["start"], s["end"]] for s in view["phases"]],
        "sub_strip": [[sp["outcome"], sp["start"], sp["end"], s["phase"], sp["evidence"]]
                      for s in view["phases"] for sp in s["subphases"]],
        "stats": view["stats"], "badges": view["badges"], "metrics": view["metrics"],
        "subphases": {"by_outcome": dict(by_outcome),
                      "by_phase": {p: dict(c) for p, c in by_phase.items()}},
    }


def vocab(ruleset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The vocabularies, and the codebook's words for them (``text``), which the viewer
    shows in legends and tooltips; ``rules`` are the built-in rules in plain words (with
    whether each optional rule is added in ``ruleset``) and ``custom_rules`` the user's own
    rules, when any."""
    checked = rules.normalize(ruleset)
    return {
        "categories": list(lookup.CATEGORIES),
        "category_family": dict(lookup.CATEGORY_FAMILY),
        "phases": list(phase.PHASES),
        "outcomes": list(phase.OUTCOMES),
        "phase_outcomes": {p: list(v) for p, v in phase.PHASE_OUTCOMES.items()},
        "evidence": list(phase.EVIDENCE),
        "flags": list(phase.FLAGS),
        "verdicts": list(verdict.VERDICTS), "fail_kinds": list(verdict.FAIL_KINDS),
        "file_roles": list(FILE_ROLES),
        "text": {
            "phases": {p: {"doing": v[0], "typical": v[1], "where": v[2]}
                       for p, v in lookup.PHASE_TEXT.items()},
            "categories": {c: {"family": lookup.CATEGORY_FAMILY[c],
                               "does": lookup.CATEGORY_TEXT[c],
                               "tools": "; ".join(x for x in (shell, native) if x)}
                           for c, shell, native in lookup.ACTION_TABLE},
            "outcomes": {row[0]: dict(zip(("check",) + phase.OUTCOMES, row[1:]))
                         for row in codebook.OUTCOME_ROWS},
            "flags": dict(codebook.FLAG_TEXT),
        },
        "rules": rules.builtin(checked),
        "tables": rules.tables(),
        "lookup": rules.contents(),
        **({"custom_rules": [{**r, "sentence": rules.describe(r)} for r in checked["custom"]]}
           if checked["custom"] else {}),
    }


def _generated_by() -> str:
    return f"atif {schema.PARSER_VERSION}"


# --------------------------------------------------------------------------- #
# building


def _load(out_dir: Path, key: Key) -> Optional[dict]:
    path = corpus.atif_path(out_dir, key)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_bug(out_dir: Path, dataset: Path, bug: str, *, config: str = corpus.DEFAULT_CONFIG,
              runs: Sequence[int] = corpus.RUNS, agents: Sequence[str] = corpus.AGENTS,
              outcome_table: Optional[outcomes.OutcomeTable] = None,
              extra_runs: Sequence[int] = (), view_runs: Optional[Sequence[int]] = None,
              ruleset: Optional[Dict[str, Any]] = None
              ) -> Tuple[Dict[str, Any], Dict[int, Dict[str, dict]], List[str]]:
    """(``trajview/3`` object for one bug, {run: {agent: view}}, ids of the trajectories of
    ``runs`` that have no converted file).

    Every converted trajectory of ``runs`` + ``extra_runs`` is read and pools into the app
    name; views are built for ``view_runs`` (default: all of them).  The bug object holds
    the views of ``runs`` only, agents in canonical order, then by run."""
    table = outcome_table if outcome_table is not None else outcomes.load(dataset)
    bug = str(bug)
    runs = [int(r) for r in runs]
    wanted = list(dict.fromkeys(runs + [int(r) for r in extra_runs]))
    build = set(wanted if view_runs is None else [int(r) for r in view_runs])
    loaded: Dict[Tuple[int, str], dict] = {}
    missing: List[str] = []
    for run in wanted:
        for agent in agents:
            key = Key(agent, config, run, bug)
            trajectory = _load(out_dir, key)
            if trajectory is None:
                if run in runs:
                    missing.append(corpus.traj_id(key))
                continue
            loaded[(run, agent)] = trajectory
    app = app_package(list(loaded.values()))
    views: Dict[int, Dict[str, dict]] = collections.defaultdict(dict)
    for (run, agent), trajectory in loaded.items():
        if run in build:
            views[run][agent] = trajectory_view(trajectory, key=Key(agent, config, run, bug),
                                                app=app, outcome_table=table, ruleset=ruleset)
    in_bug = [views[r][a] for a in agents for r in runs if a in views.get(r, {})]
    obj = {"schema": SCHEMA, "generated_by": _generated_by(), "bug": bug, "app": app,
           "config": config, "runs": runs, "agents": list(agents),
           "outcome_source": outcomes.OUTCOME_SOURCE, "vocab": vocab(ruleset),
           "trajectories": in_bug}
    return obj, dict(views), missing


def bug_entry(bug: str, app: Optional[str], run_views: Dict[str, dict], *, config: str,
              overview_run: int, agents: Sequence[str],
              table: outcomes.OutcomeTable) -> Dict[str, Any]:
    """One row of the overview: run ``overview_run`` of each agent (when converted), and the
    agent's pass/fail in every run straight from the outcome CSVs."""
    entry: Dict[str, Any] = {"bug": str(bug), "app": app, "agents": {}, "by_run": {}}
    for agent in agents:
        entry["by_run"][agent] = outcomes.outcome_for(table, agent, bug, config,
                                                      overview_run)["by_run"]
        if agent in run_views:
            entry["agents"][agent] = summary_view(run_views[agent])
    return entry


def write_js(variable: str, data: Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(f"{variable} = {body};\n", encoding="utf-8")
    return path


def read_js(path: Path, variable: Optional[str] = None) -> Dict[str, Any]:
    """Load a written overview.js or bug-<id>.js back (for the tests and for checking a
    viewer bug)."""
    text = Path(path).read_text(encoding="utf-8").strip()
    for name in ([variable] if variable else [OVERVIEW_VAR, BUG_VAR]):
        prefix = f"{name} = "
        if text.startswith(prefix) and text.endswith(";"):
            return json.loads(text[len(prefix):-1])
    raise ValueError(f"{path}: not a trajview data file")


def bug_file(viewer_dir: Path, bug: str) -> Path:
    return Path(viewer_dir) / "data" / "bugs" / f"bug-{bug}.js"


def pack_file(viewer_dir: Path, run: int, bug: str) -> Path:
    return Path(viewer_dir) / "data" / "atif" / f"run{int(run)}" / f"bug-{bug}.json.gz"


def write_packs(out_dir: Path, viewer_dir: Path, *, config: str = corpus.DEFAULT_CONFIG,
                runs: Iterable[int] = corpus.RUNS, bug_ids: Iterable[str] = (),
                agents: Sequence[str] = corpus.AGENTS) -> Dict[str, Any]:
    """Write ``viewer/data/atif/run<k>/bug-<id>.json.gz``: the converted ATIF of one bug's
    agents in one run (``PACK_SCHEMA``), gzipped.  The viewer re-runs them in the browser
    when the user's rule set is not the default one (``atif.upload.reanalyze``).  The
    gzip stream has no timestamp, so an unchanged corpus rewrites every file byte for byte."""
    out_dir, viewer_dir = Path(out_dir), Path(viewer_dir)
    files, size = 0, 0
    for run in [int(r) for r in runs]:
        for bug in bug_ids:
            bug = str(bug).replace("bug-", "")
            found = {agent: _load(out_dir, Key(agent, config, run, bug)) for agent in agents}
            found = {a: t for a, t in found.items() if t is not None}
            if not found:
                continue
            body = json.dumps({"schema": PACK_SCHEMA, "bug": bug, "config": config, "run": run,
                               "trajectories": found}, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            path = pack_file(viewer_dir, run, bug)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
            files += 1
            size += path.stat().st_size
    return {"files": files, "bytes": size}


def overview_file(viewer_dir: Path) -> Path:
    return Path(viewer_dir) / "data" / "overview.js"


def export(out_dir: Path, dataset: Path, viewer_dir: Path, config: str = corpus.DEFAULT_CONFIG,
           runs: Iterable[int] = corpus.RUNS, overview_run: int = 1,
           bug_ids: Optional[Iterable[str]] = None,
           agents: Optional[Iterable[str]] = None,
           ruleset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write ``viewer/data/bugs/bug-<id>.js`` for ``bug_ids`` (default: every bug) and
    rewrite ``viewer/data/overview.js``; ``ruleset`` (``atif.rules``) replaces the default
    phase rules.

    The overview always covers every bug of the dataset, so that refreshing a few bug pages
    (``view 8 18``) leaves it complete; a bug's row says whether its page file exists.
    ``out_dir`` is the conversion output root (``Parser/data``), whose
    ``atif/<config>/run<k>/`` files are read; nothing is converted here.  Returns a summary:
    files written with sizes, trajectory counts and the ids of trajectories with no
    converted file."""
    out_dir, dataset, viewer_dir = Path(out_dir), Path(dataset), Path(viewer_dir)
    runs = [int(r) for r in runs]
    overview_run = int(overview_run)
    agents = [a for a in corpus.AGENTS if agents is None or a in set(agents)]
    table = outcomes.load(dataset)
    every_bug = corpus.all_bug_ids(dataset)
    pages = sorted({str(b).replace("bug-", "") for b in bug_ids}, key=int) if bug_ids \
        else list(every_bug)
    unknown = [b for b in pages if b not in every_bug]
    if unknown:
        raise ValueError(f"no such bug(s) in {dataset}: {', '.join(unknown)}")
    written: List[Tuple[str, int]] = []
    missing: List[str] = []
    n_traj = 0
    entries: List[Dict[str, Any]] = []
    page_set = set(pages)
    for bug in every_bug:
        if bug in page_set:
            obj, views, lacking = build_bug(out_dir, dataset, bug, config=config, runs=runs,
                                            agents=agents, outcome_table=table,
                                            extra_runs=[overview_run], ruleset=ruleset)
            missing.extend(lacking)
            n_traj += len(obj["trajectories"])
            path = write_js(BUG_VAR, obj, bug_file(viewer_dir, bug))
            written.append((str(path), path.stat().st_size))
            app = obj["app"]
        else:
            _obj, views, _lacking = build_bug(out_dir, dataset, bug, config=config, runs=runs,
                                              agents=agents, outcome_table=table,
                                              extra_runs=[overview_run],
                                              view_runs=[overview_run], ruleset=ruleset)
            app = _obj["app"]
        entry = bug_entry(bug, app, views.get(overview_run, {}), config=config,
                          overview_run=overview_run, agents=agents, table=table)
        entry["page"] = bug_file(viewer_dir, bug).is_file()
        entries.append(entry)
    overview = {"schema": OVERVIEW_SCHEMA, "generated_by": _generated_by(), "config": config,
                "run": overview_run, "runs": runs, "agents": agents,
                "outcome_source": outcomes.OUTCOME_SOURCE,
                "models": _models(entries, agents), "vocab": vocab(ruleset), "bugs": entries}
    opath = write_js(OVERVIEW_VAR, overview, overview_file(viewer_dir))
    largest = max(written, key=lambda w: w[1]) if written else (None, 0)
    return {"config": config, "runs": runs, "overview_run": overview_run, "agents": agents,
            "overview": str(opath), "overview_bytes": opath.stat().st_size,
            "bug_files": len(written), "bug_bytes": sum(w[1] for w in written),
            "largest_bug_file": largest[0], "largest_bug_bytes": largest[1],
            "bugs": len(entries), "trajectories": n_traj,
            "overview_trajectories": sum(len(e["agents"]) for e in entries),
            "missing": missing}


def _models(entries: List[Dict[str, Any]], agents: Sequence[str]) -> Dict[str, Optional[str]]:
    """{agent: model name} as the converted logs report it (most common over the overview)."""
    out: Dict[str, Optional[str]] = {}
    for agent in agents:
        counts = collections.Counter(e["agents"][agent].get("model") for e in entries
                                     if agent in e["agents"] and e["agents"][agent].get("model"))
        out[agent] = counts.most_common(1)[0][0] if counts else None
    return out
