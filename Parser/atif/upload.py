"""Analyse one trajectory that is not in the corpus: a raw log of Claude Code, Codex CLI or
Qwen Code, a SWE-bench run of SWE-agent, OpenHands or mini-swe-agent (``atif.swebench``), or an
ATIF file, given as text (the viewer's Analyze page) or as a path
(``python3 -m atif.cli analyze``).

Raw logs: Codex's rollout JSONL, Qwen Code's stream-json, Claude Code's stream-json or
session transcript JSONL (``atif.claude.read_json_messages``), or the claude-agent-sdk dump of
the corpus.  A JSON log saved as one array of events (``[{...}, {...}]``) is read as one event
per line.

    analyze(text, name="bug-18_output.txt", ruleset=None, outcome=None)
        -> {"schema": "trajview-single/1", "trajectory": <trajview/3 trajectory>,
            "vocab": ..., "rules": <rules report>, "source": {...}, "warnings": [...],
            "unrecognized": <atif.diagnose report>, "atif": <the ATIF, when asked>}

``unrecognized`` lists the steps the lookup tables do not recognise (unknown tools and
programs), grouped, each group with a suggested row the user may add (``atif.diagnose``).
``atif`` (``with_atif=True``; the request's ``"atif": true``) is the trajectory as ATIF, which
the viewer keeps beside the upload to show a step's full texts and raw JSON.

The format is recognised from the content (``atif.detect``), never from the name.  The bug
id matters because paths are read relative to the ``bug-<id>`` checkout (``segment.repo_rel``);
it comes from the caller, else the ATIF file, the log's working directory, the file name or
the paths the log mentions most.  There is no harness verdict for an uploaded log, so the
outcome is the caller's (pass, fail or unknown).

A SWE-bench run is kept apart from the Android corpus: its trajectory records a SWE-bench
project (``atif.project``), so paths are read relative to its repository root and Python's
test conventions apply; it needs no bug id (its "bug" is the SWE-bench instance id when the
log or the file name gives one), and the result says ``source.project = "swebench"`` so the
viewer does not compare it with the corpus.  An ATIF file that records no project is a
SWE-bench one when its task names the repository folder (``swebench.infer_project``).

The viewer reaches this module in one of two ways, with the same three calls:
``rules_info()``, ``request(body)`` (one uploaded log) and ``corpus_request(body)`` (corpus
trajectories re-run under the user's rules, from ``view.write_packs``).  The local server
(``atif.serve``) answers them over HTTP; the hosted viewer runs this package in the browser
with Pyodide (``atif.engine``).
"""
from __future__ import annotations

import collections
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import corpus, detect, diagnose, lookup, phase, project, rules, schema, swebench, view

SCHEMA = "trajview-single/1"
#: the largest log accepted (the corpus's largest is under 20 MB)
MAX_BYTES = 100 * 1024 * 1024
_BUG = re.compile(r"/bug-(\d+)(?:/|\b)")
_BUG_NAME = re.compile(r"bug-(\d+)")
_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}$")


class UploadError(ValueError):
    """A file that cannot be analysed, with a message for the user."""


def _atif(text: str) -> Optional[dict]:
    """The trajectory, when the text is an ATIF file (one JSON object with steps)."""
    head = text.lstrip()[:1]
    if head != "{":
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("steps"), list) \
            and str(obj.get("schema_version", "")).startswith("ATIF"):
        return obj
    return None


def _event_lines(text: str) -> str:
    """A JSON array of events as JSON lines; any other text unchanged."""
    if not text.lstrip().startswith("["):
        return text
    try:
        events = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(events, list) and events and all(isinstance(e, dict) for e in events):
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    return text


def _document(text: str) -> Optional[Any]:
    """The text as one JSON document, or None."""
    if text.lstrip()[:1] not in ("{", "["):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_text(text: str, name: str = "") -> Dict[str, Any]:
    """(trajectory, format, agent) of a log or ATIF text.  Raises UploadError."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise UploadError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not text.strip():
        raise UploadError("the file is empty")
    document = _document(text)
    fmt = swebench.detect_document(document) if document is not None else None
    if fmt:
        try:
            trajectory = swebench.parse_document(document, fmt, source_file=Path(name).name)
        except Exception as exc:                    # a damaged log: say so, do not crash
            raise UploadError(f"the {detect.AGENT_OF_FORMAT[fmt]} log could not be read: {exc}")
        return {"trajectory": trajectory, "format": fmt, "agent": detect.AGENT_OF_FORMAT[fmt]}
    text = _event_lines(text)
    trajectory = _atif(text)
    if trajectory is not None:
        extra = trajectory.get("extra") or {}
        agent = extra.get("agent") or _agent_of(trajectory)
        if "project" not in extra:
            inferred = swebench.infer_project(trajectory)
            if inferred is not None:
                project.stamp(trajectory, inferred)
        return {"trajectory": trajectory, "format": "atif", "agent": agent}
    suffix = _SUFFIX.search(name or "")
    with tempfile.TemporaryDirectory(prefix="trajectiers-") as tmp:
        path = Path(tmp) / ("upload" + (suffix.group(0) if suffix else ".log"))
        path.write_text(text, encoding="utf-8")
        fmt = detect.detect(path)
        if fmt is None:
            raise UploadError("this is not a log of Claude Code, Codex CLI, Qwen Code, "
                              "SWE-agent, OpenHands or mini-swe-agent, nor an ATIF file")
        try:
            trajectory = detect.PARSERS[fmt](path)
        except Exception as exc:                    # a damaged log: say so, do not crash
            raise UploadError(f"the {detect.AGENT_OF_FORMAT[fmt]} log could not be read: {exc}")
    return {"trajectory": trajectory, "format": fmt, "agent": detect.AGENT_OF_FORMAT[fmt]}


def _agent_of(trajectory: dict) -> str:
    name = str((trajectory.get("agent") or {}).get("name") or "").lower()
    for agent in ("claude", "codex", "qwen"):
        if agent in name:
            return agent
    return name or "agent"


def infer_bug(trajectory: dict, name: str = "") -> Optional[str]:
    """The bug id: the ATIF file's own, the working directory's ``bug-<id>``, the file
    name's, else the ``/bug-<id>/`` the log's paths name most; None when nothing does."""
    extra = trajectory.get("extra") or {}
    if extra.get("bug_id"):
        return str(extra["bug_id"]).replace("bug-", "")
    match = _BUG.search(str(extra.get("cwd") or "") + "/")
    if match:
        return match.group(1)
    match = _BUG_NAME.search(name or "")
    if match:
        return match.group(1)
    counts: collections.Counter = collections.Counter()
    for step in trajectory.get("steps", [])[:400]:
        for call in step.get("tool_calls") or []:
            counts.update(_BUG.findall(json.dumps(call.get("arguments") or {})))
    return counts.most_common(1)[0][0] if counts else None


def analyze(text: str, name: str = "", *, ruleset: Optional[Dict[str, Any]] = None,
            outcome: Optional[bool] = None, bug: Optional[str] = None,
            with_atif: bool = False) -> Dict[str, Any]:
    """Parse, phase and build the view of one uploaded trajectory under ``ruleset``.
    Raises UploadError for a file it cannot read and rules.RuleError for a bad rule set."""
    checked = rules.normalize(ruleset)
    parsed = parse_text(text, name)
    trajectory, agent = parsed["trajectory"], parsed["agent"]
    proj = project.of(trajectory)
    warnings: List[str] = []
    if proj.swebench:
        bug_id = str(bug).strip() if bug else (proj.instance_id or swebench.instance_id(
            re.sub(r"(\.traj)?\.\w+$", "", Path(name or "").name)) or None)
        if not proj.roots:
            warnings.append("No repository folder was found in the log, so absolute paths "
                            "count as outside the project.")
    else:
        bug_id = str(bug).replace("bug-", "").strip() if bug else infer_bug(trajectory, name)
        if not bug_id:
            warnings.append("No bug-<id> checkout was found in the log, so absolute paths "
                            "count as outside the project. Enter the bug id to read them as "
                            "project files.")
    label = re.sub(r"[^\w.\-]+", "_", Path(name or "upload").name)[:80] or "upload"
    with project.use(proj):
        try:
            result = rules.phases(trajectory, bug_id or "0", checked)
        except ValueError as exc:
            raise UploadError(f"the phases could not be computed: {exc}")
        obj = view.build_view(
            trajectory, result, traj_id=f"upload/{agent}/{label}", bug=bug_id or "",
            agent=agent, config="upload", run=1,
            app=None if proj.swebench else view.app_package([trajectory]),
            outcome={"pass": outcome, "by_run": {"1": outcome}})
        found = diagnose.unrecognized(result["actions"], result.get("table_row"),
                                      result["rules"])
    if proj.swebench:
        obj["project"] = proj.kind
    if not obj["n_actions"]:
        warnings.append("The log holds no tool calls, so there are no phases to show.")
    return {
        "schema": SCHEMA, "generated_by": f"atif {schema.PARSER_VERSION}",
        "trajectory": obj, "vocab": view.vocab(checked), "rules": result["rules"],
        "source": {"name": name, "format": parsed["format"], "agent": agent,
                   "model": (trajectory.get("agent") or {}).get("model_name") or None,
                   "bug": bug_id, "bug_inferred": not bug and bool(bug_id),
                   "project": proj.kind, "repo_root": proj.roots[0] if proj.roots else None,
                   "steps": len(trajectory.get("steps") or [])},
        "warnings": warnings, "unrecognized": found,
        **({"atif": trajectory} if with_atif else {}),
    }


def rules_info() -> Dict[str, Any]:
    """What the Lookup tables page and the Analyze page need before any upload."""
    return {
        "schema": rules.SCHEMA, "default": rules.default_ruleset(),
        "mandatory": rules.mandatory(), "optional": rules.optional([]),
        "tables": rules.tables(), "lookup": rules.contents(),
        "kinds": list(rules.KINDS), "fields": list(rules.FIELDS),
        "categories": list(lookup.CATEGORIES), "phases": list(phase.PHASES),
        "follow": rules.FOLLOW, "file_roles": list(lookup.TARGETS),
        "max_bytes": MAX_BYTES, "parser_version": schema.PARSER_VERSION,
    }


def request(body: Any) -> Dict[str, Any]:
    """One request of the Analyze page, ``{"name", "text", "rules", "outcome", "bug",
    "atif"}``:
    the ``analyze`` result, or ``{"error": message}`` for a log or rule set the user must fix.
    Any other exception is a fault of the analysis and propagates."""
    try:
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise ValueError("expected {\"name\", \"text\", \"rules\"}")
        outcome = body.get("outcome")
        return analyze(body["text"], str(body.get("name") or ""), ruleset=body.get("rules"),
                       outcome=outcome if isinstance(outcome, bool) else None,
                       bug=str(body["bug"]) if body.get("bug") else None,
                       with_atif=body.get("atif") is True)
    except (UploadError, rules.RuleError, ValueError) as exc:
        return {"error": str(exc)}


def reanalyze(pack: Dict[str, Any], ruleset: Optional[Dict[str, Any]] = None, *,
              summary: bool = False) -> Dict[str, Any]:
    """The views of one corpus pack (``view.write_packs``: one bug, one run, its agents'
    ATIF) under a rule set: per agent the full ``trajview/3`` trajectory, or with ``summary``
    its overview form (``view.summary_view``), plus ``rule_hits``, the number of actions
    each optional or custom rule changed.  The outcome and the app name do not depend on the
    rules; the caller keeps its own (``outcome.pass`` is null here)."""
    if not isinstance(pack, dict) or pack.get("schema") != view.PACK_SCHEMA:
        raise ValueError(f"not a corpus pack ({view.PACK_SCHEMA})")
    checked = rules.normalize(ruleset)
    bug, config, run = str(pack["bug"]), str(pack["config"]), int(pack["run"])
    views: Dict[str, Any] = {}
    for agent, trajectory in pack["trajectories"].items():
        key = corpus.Key(agent, config, run, bug)
        result = rules.phases(trajectory, bug, checked)
        obj = view.build_view(trajectory, result, traj_id=corpus.traj_id(key), bug=bug,
                              agent=agent, config=config, run=run, app=pack.get("app"),
                              outcome={"pass": None, "by_run": {}})
        item = view.summary_view(obj) if summary else obj
        report = result["rules"]
        item["rule_hits"] = {r["id"]: len(r["matched"]) for r in report["optional"] +
                             report["custom"] if r.get("matched")}
        views[agent] = item
    return {"bug": bug, "config": config, "run": run, "views": views}


def corpus_request(body: Any) -> Dict[str, Any]:
    """Re-run corpus packs under the user's rules: ``{"rules", "summary", "packs": [pack,
    ...]}`` -> ``{"vocab", "packs": [reanalyze(pack), ...]}``, or ``{"error": message}`` for
    a rule set the user must fix.  The local server reads the packs from disk, the browser
    engine fetches them; both then call this."""
    try:
        if not isinstance(body, dict) or not isinstance(body.get("packs"), list):
            raise ValueError("expected {\"rules\", \"packs\": [...]}")
        checked = rules.normalize(body.get("rules"))
        summary = bool(body.get("summary"))
        return {"schema": "trajectiers-corpus/1", "vocab": view.vocab(checked),
                "packs": [reanalyze(p, checked, summary=summary) for p in body["packs"]]}
    except (rules.RuleError, ValueError) as exc:
        return {"error": str(exc)}


def analyze_path(path: Path, **options: Any) -> Dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise UploadError(f"{path.name} is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return analyze(path.read_text(encoding="utf-8", errors="replace"), path.name, **options)
