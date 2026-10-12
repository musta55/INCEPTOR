"""Identify which agent produced a log file, from its content rather than its name.

The three formats cannot be confused with one another:

* Claude Code: a ``repr()`` dump, so its lines start with a class name, never with ``{``.
* Codex CLI: JSON lines whose ``type`` is a rollout record kind (``session_meta``,
  ``turn_context``, ``response_item``, ``event_msg``) and which wrap content in ``payload``.
* Qwen Code: JSON lines whose ``type`` is a stream-json kind (``system``, ``assistant``,
  ``user``, ``stream_event``, ``result``) and which all carry ``session_id``; the ``init``
  event names ``qwen_code_version``. A log whose head was lost (no ``init``) is still
  recognised from its assistant/user events, which carry ``parent_tool_use_id``.
* Claude Code's raw JSON (stream-json, or a session transcript): the same stream-json
  kinds as Qwen's, but the ``init`` event names ``claude_code_version``, a transcript's
  events carry ``parentUuid`` / ``isSidechain``, and an assistant event names a ``claude-``
  model.  Only those decide; an event that fits both (a ``user`` event of a log whose head
  was lost) makes Qwen the answer only if nothing later decides otherwise.

Non-JSON lines (harness stderr) and JSON lines split by them are skipped while probing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import claude, codex, qwen

PARSERS = {
    claude.SOURCE_FORMAT: claude.parse,
    claude.JSON_SOURCE_FORMAT: claude.parse,
    codex.SOURCE_FORMAT: codex.parse,
    qwen.SOURCE_FORMAT: qwen.parse,
}
AGENT_OF_FORMAT = {
    claude.SOURCE_FORMAT: "claude",
    claude.JSON_SOURCE_FORMAT: "claude",
    codex.SOURCE_FORMAT: "codex",
    qwen.SOURCE_FORMAT: "qwen",
}
CLAUDE_CLASSES = ("SystemMessage(", "AssistantMessage(", "UserMessage(", "ResultMessage(",
                  "TaskStartedMessage(", "TaskNotificationMessage(", "TaskProgressMessage(",
                  "TaskUpdatedMessage(")
CODEX_KINDS = ("session_meta", "turn_context", "response_item", "event_msg")
QWEN_KINDS = ("system", "assistant", "user", "stream_event", "result")


def _qwen_event(event: dict) -> bool:
    kind = event.get("type")
    if kind not in QWEN_KINDS or "session_id" not in event or "payload" in event:
        return False
    if kind == "system" and event.get("subtype") == "init":
        # Claude Code's own stream-json looks alike but names claude_code_version
        return "qwen_code_version" in event
    if kind == "result":
        return "num_turns" in event
    return "parent_tool_use_id" in event


def _claude_json_event(event: dict) -> bool:
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        return "claude_code_version" in event
    if kind in ("user", "assistant", "summary") and ("parentUuid" in event
                                                     or "isSidechain" in event):
        return True
    model = (event.get("message") or {}).get("model") if kind == "assistant" and \
        isinstance(event.get("message"), dict) else None
    return isinstance(model, str) and model.startswith("claude")


def _decisive(event: dict) -> bool:
    """A Qwen-looking event that settles the question: an init or an assistant event
    that names its (non-Claude) model, or a result."""
    kind = event.get("type")
    return kind in ("system", "result") or (
        kind == "assistant" and bool((event.get("message") or {}).get("model")))


def detect(path: Path, probe_lines: int = 400) -> Optional[str]:
    """Return a source format id, or None if the file is not a known trajectory."""
    path = Path(path)
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    tentative: Optional[str] = None
    with handle:
        for _ in range(probe_lines):
            line = handle.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith(CLAUDE_CLASSES):
                return claude.SOURCE_FORMAT
            if line.startswith("{"):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") in CODEX_KINDS and isinstance(event.get("payload"), dict):
                    return codex.SOURCE_FORMAT
                if _claude_json_event(event):
                    return claude.JSON_SOURCE_FORMAT
                if _qwen_event(event):
                    if _decisive(event):
                        return qwen.SOURCE_FORMAT
                    tentative = qwen.SOURCE_FORMAT
    return tentative


def parse(path: Path, **kwargs):
    """Parse a log with whichever parser matches it."""
    fmt = detect(path)
    if fmt is None:
        raise ValueError(f"{path}: unrecognised trajectory format")
    return PARSERS[fmt](Path(path), **kwargs)
