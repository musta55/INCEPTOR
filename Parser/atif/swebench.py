"""SWE-bench agent trajectories -> ATIF: what the three adapters share.

The adapters read the trajectories SWE-bench agents publish, one JSON document per run:

    format id            agent            file
    sweagent_traj        SWE-agent        ``<instance>.traj`` (0.x and 1.x)   ``atif.sweagent``
    sweagent_chat        SWE-agent        the chat export of Hugging Face's SWE-agent
                                          trajectory datasets (``role`` system/user/ai,
                                          ``text``), one row or its ``trajectory`` list
    openhands_messages   OpenHands        the LLM messages with tool calls (SWE-bench
                                          submissions' ``trajs/<instance>.json``)
    openhands_events     OpenHands        the event stream (``--save-trajectory-path``, or
                                          an evaluation row's ``history``) ``atif.openhands``
    mini_swe_agent       mini-swe-agent   ``<instance>.traj.json``, live-SWE-agent too
                                                                              ``atif.miniswe``

Each run becomes one ATIF trajectory: the system prompt and the task as a system and a user
step, then one agent step per model turn with its tool call(s) and their output.  The
trajectory records its project in ``extra.project`` (``atif.project``): a SWE-bench project
whose repository root is the folder the task names (``<uploaded_files>``, "in the directory
/testbed", SWE-agent's ``(Current directory: ...)``), else the folder the agent ``cd``s into
most.  None of these logs carries the evaluation outcome or a corpus bug id: the outcome stays
the user's, and the bug is the SWE-bench instance id when the log names one.

Agentless and AutoCodeRover are pipelines rather than agents (fixed stages, several files per
run) and are not read.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import project, schema

#: the task's statement of where the repository is
_UPLOADED = re.compile(r"<uploaded_files>\s*(/[^\s<]+)\s*</uploaded_files>")
_IN_DIRECTORY = re.compile(r"repository in the directory\s+(/[\w.\-/]+?)\.?(?=\s|$)")
_CURRENT_DIR = re.compile(r"\(Current directory: (/[^)\s]*)\)")
_CD = re.compile(r"(?:^|&&|;|\n)\s*cd\s+(/[\w.\-/]+)")
#: a SWE-bench instance id: ``astropy__astropy-12907``, ``django__django-11099``
INSTANCE_ID = re.compile(r"^[\w.\-]+__[\w.\-]+-\d+$")


def text_of(content: Any) -> str:
    """A message's text: a string, or the text parts of a content-part list."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") if isinstance(p, dict) else str(p)
                         for p in content
                         if not isinstance(p, dict) or p.get("type", "text") == "text")
    if isinstance(content, dict):
        return str(content.get("text") or json.dumps(content, default=str))
    return str(content)


def find_roots(texts: Iterable[str], commands: Iterable[str] = ()) -> List[str]:
    """Repository roots: the folder the task names, else the folder the agent's commands
    ``cd`` into most (reduced to its shortest prefix that is also a ``cd`` target)."""
    for text in texts:
        for pattern in (_UPLOADED, _IN_DIRECTORY, _CURRENT_DIR):
            match = pattern.search(text or "")
            if match and match.group(1).rstrip("/"):
                return [match.group(1).rstrip("/")]
    targets = collections.Counter(t.rstrip("/") for c in commands for t in _CD.findall(c or "")
                                  if t.rstrip("/"))
    if not targets:
        return []
    top = targets.most_common(1)[0][0]
    prefixes = [t for t in targets if top == t or top.startswith(t + "/")]
    return [min(prefixes, key=len)]


def instance_id(*candidates: Any) -> str:
    """The first candidate that is a SWE-bench instance id, else ""."""
    for value in candidates:
        if isinstance(value, str) and INSTANCE_ID.match(value.strip()):
            return value.strip()
    return ""


def json_args(raw: Any) -> dict:
    """A tool call's arguments: a JSON string or a dict; anything else kept as ``raw``."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"raw": raw}
        return value if isinstance(value, dict) else {"raw": value}
    return {} if raw is None else {"raw": raw}


class Builder:
    """Accumulates ATIF steps: system and user messages, and agent turns with their calls."""

    def __init__(self, model: str = "") -> None:
        self.steps: List[dict] = []
        self.model = model
        self.calls = 0

    def message(self, source: str, text: str, timestamp: str = "") -> None:
        if text and text.strip():
            self.steps.append(schema.message_step(len(self.steps) + 1, source, text, timestamp))

    def turn(self, thought: str, calls: List[Tuple[str, str, dict]],
             results: Optional[Dict[str, Tuple[Any, Dict[str, Any]]]] = None, *,
             timestamp: str = "", model: str = "", reasoning: str = "") -> None:
        """One model turn: its text, its calls ``(id, tool, arguments)`` and their results
        ``{id: (output, result extra)}``.  A call without a result gets none."""
        step = schema.agent_step(len(self.steps) + 1, timestamp=timestamp,
                                 model_name=model or self.model)
        step["message"] = thought or ""
        if reasoning:
            step["reasoning_content"] = reasoning
        for call_id, name, arguments in calls:
            schema.add_tool_call(step, call_id, name, arguments)
            if results and call_id in results:
                content, meta = results[call_id]
                schema.add_observation(step, call_id, content, **(meta or {}))
        self.calls += len(calls)
        self.steps.append(schema.finalize(step))

    def envelope(self, *, agent: str, version: str, source_format: str, source_file: str,
                 proj: project.Project, session_id: str = "", extra: Optional[dict] = None
                 ) -> dict:
        info: Dict[str, Any] = {"source_format": source_format, "source_file": source_file,
                                "parser_version": schema.PARSER_VERSION,
                                "parsed_tool_calls": self.calls}
        info.update({k: v for k, v in (extra or {}).items() if v not in (None, "", [], {})})
        trajectory = schema.envelope(
            session_id=session_id or proj.instance_id or None, agent_name=agent,
            agent_version=version, model_name=self.model,
            steps=schema.placeholder_steps(self.steps, "the log holds no turns"), extra=info)
        return project.stamp(trajectory, proj)


# --------------------------------------------------------------------------- #
# detection and dispatch

def _formats() -> List[Tuple[str, str, Callable[[Any], bool], Callable[..., dict]]]:
    """(format id, agent, recogniser, parser), in the order they are tried."""
    from . import miniswe, openhands, sweagent
    return [
        (sweagent.SOURCE_FORMAT, sweagent.AGENT_NAME, sweagent.is_traj, sweagent.parse_traj),
        (sweagent.CHAT_FORMAT, sweagent.AGENT_NAME, sweagent.is_chat, sweagent.parse_chat),
        (miniswe.SOURCE_FORMAT, miniswe.AGENT_NAME, miniswe.is_mini, miniswe.parse_object),
        (openhands.EVENTS_FORMAT, openhands.AGENT_NAME, openhands.is_events,
         openhands.parse_events),
        (openhands.MESSAGES_FORMAT, openhands.AGENT_NAME, openhands.is_messages,
         openhands.parse_messages),
    ]


def detect_document(obj: Any) -> Optional[str]:
    """The format id of a parsed JSON document, or None when it is none of these."""
    for fmt, _agent, recognise, _parse in _formats():
        try:
            if recognise(obj):
                return fmt
        except (AttributeError, KeyError, TypeError, IndexError):
            continue
    return None


def agent_of(fmt: str) -> str:
    return next(agent for f, agent, _r, _p in _formats() if f == fmt)


def parse_document(obj: Any, fmt: Optional[str] = None, *, source_file: str = "") -> dict:
    """ATIF of a parsed document (``fmt``: its format id, detected when not given)."""
    fmt = fmt or detect_document(obj)
    for f, _agent, _recognise, parse in _formats():
        if f == fmt:
            return parse(obj, source_file=source_file)
    raise ValueError("not a SWE-agent, OpenHands or mini-swe-agent trajectory")


def load(path: Path) -> Optional[Any]:
    """The file as one JSON document, or None when it is not one (JSON lines, a repr dump)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.lstrip()[:1] in ("{", "["):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def detect(path: Path) -> Optional[str]:
    obj = load(path)
    return detect_document(obj) if obj is not None else None


def parse(path: Path, **_options: Any) -> dict:
    obj = load(path)
    if obj is None:
        raise ValueError(f"{path}: not a JSON document")
    return parse_document(obj, source_file=Path(path).name)


# --------------------------------------------------------------------------- #
# ATIF written by others (Harbor runs SWE-bench tasks too)

_ANDROID_CHECKOUT = re.compile(r"/bug-\d+(?:/|\b)")


def infer_project(trajectory: dict) -> Optional[project.Project]:
    """The SWE-bench project of an ATIF file that records none, when its task names the
    repository folder (``<uploaded_files>``, "in the directory /testbed") or its calls work
    in ``/testbed``; None for anything else, a ``bug-<id>`` checkout above all."""
    steps = trajectory.get("steps") or []
    texts = [text_of(s.get("message")) for s in steps[:3] if s.get("source") in ("system", "user")]
    calls = [json.dumps(c.get("arguments") or {}) for s in steps[:400]
             for c in s.get("tool_calls") or []]
    if any(_ANDROID_CHECKOUT.search(c) for c in calls):
        return None
    roots = [r for r in find_roots(texts) if r]
    if not roots and any("/testbed" in c for c in calls):
        roots = ["/testbed"]
    if not roots:
        return None
    extra = trajectory.get("extra") or {}
    return project.make(project.SWEBENCH, roots,
                        instance_id(extra.get("instance_id"), trajectory.get("session_id")))
