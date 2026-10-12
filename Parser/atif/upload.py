"""Analyse one trajectory that is not in the corpus: a raw log of Claude Code, Codex CLI or
Qwen Code, or an ATIF file, given as text (the viewer's Analyze page) or as a path
(``python3 -m atif.cli analyze``).

Raw logs: Codex's rollout JSONL, Qwen Code's stream-json, Claude Code's stream-json or
session transcript JSONL (``atif.claude.read_json_messages``), or the claude-agent-sdk dump of
the corpus.  A JSON log saved as one array of events (``[{...}, {...}]``) is read as one event
per line.

    analyze(text, name="bug-18_output.txt", ruleset=None, outcome=None)
        -> {"schema": "trajview-single/1", "trajectory": <trajview/3 trajectory>,
            "vocab": ..., "rules": <rules report>, "source": {...}, "warnings": [...]}

The format is recognised from the content (``atif.detect``), never from the name.  The bug
id matters because paths are read relative to the ``bug-<id>`` checkout (``segment.repo_rel``);
it comes from the caller, else the ATIF file, the log's working directory, the file name or
the paths the log mentions most.  There is no harness verdict for an uploaded log, so the
outcome is the caller's (pass, fail or unknown).
"""
from __future__ import annotations

import collections
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import detect, rules, schema, view

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


def parse_text(text: str, name: str = "") -> Dict[str, Any]:
    """(trajectory, format, agent) of a log or ATIF text.  Raises UploadError."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise UploadError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not text.strip():
        raise UploadError("the file is empty")
    text = _event_lines(text)
    trajectory = _atif(text)
    if trajectory is not None:
        extra = trajectory.get("extra") or {}
        agent = extra.get("agent") or _agent_of(trajectory)
        return {"trajectory": trajectory, "format": "atif", "agent": agent}
    suffix = _SUFFIX.search(name or "")
    with tempfile.TemporaryDirectory(prefix="trajectiers-") as tmp:
        path = Path(tmp) / ("upload" + (suffix.group(0) if suffix else ".log"))
        path.write_text(text, encoding="utf-8")
        fmt = detect.detect(path)
        if fmt is None:
            raise UploadError("this is not a log of Claude Code, Codex CLI or Qwen Code, "
                              "nor an ATIF file")
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
            outcome: Optional[bool] = None, bug: Optional[str] = None) -> Dict[str, Any]:
    """Parse, phase and build the view of one uploaded trajectory under ``ruleset``.
    Raises UploadError for a file it cannot read and rules.RuleError for a bad rule set."""
    checked = rules.normalize(ruleset)
    parsed = parse_text(text, name)
    trajectory, agent = parsed["trajectory"], parsed["agent"]
    warnings: List[str] = []
    bug_id = str(bug).replace("bug-", "").strip() if bug else infer_bug(trajectory, name)
    if not bug_id:
        warnings.append("No bug-<id> checkout was found in the log, so absolute paths count "
                        "as outside the project. Enter the bug id to read them as project files.")
    try:
        result = rules.phases(trajectory, bug_id or "0", checked)
    except ValueError as exc:
        raise UploadError(f"the phases could not be computed: {exc}")
    label = re.sub(r"[^\w.\-]+", "_", Path(name or "upload").name)[:80] or "upload"
    obj = view.build_view(
        trajectory, result, traj_id=f"upload/{agent}/{label}", bug=bug_id or "",
        agent=agent, config="upload", run=1, app=view.app_package([trajectory]),
        outcome={"pass": outcome, "by_run": {"1": outcome}})
    if not obj["n_actions"]:
        warnings.append("The log holds no tool calls, so there are no phases to show.")
    return {
        "schema": SCHEMA, "generated_by": f"atif {schema.PARSER_VERSION}",
        "trajectory": obj, "vocab": view.vocab(checked), "rules": result["rules"],
        "source": {"name": name, "format": parsed["format"], "agent": agent,
                   "model": (trajectory.get("agent") or {}).get("model_name") or None,
                   "bug": bug_id, "bug_inferred": not bug and bool(bug_id),
                   "steps": len(trajectory.get("steps") or [])},
        "warnings": warnings,
    }


def analyze_path(path: Path, **options: Any) -> Dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise UploadError(f"{path.name} is larger than {MAX_BYTES // (1024 * 1024)} MB")
    return analyze(path.read_text(encoding="utf-8", errors="replace"), path.name, **options)
