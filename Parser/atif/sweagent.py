"""SWE-agent -> ATIF.

Source formats (``atif.swebench`` dispatches here):

``sweagent_traj``  the ``<instance>.traj`` file SWE-agent writes, one JSON object:
    trajectory   one entry per step: ``action`` (the command as a string), ``observation``,
                 ``thought`` / ``response``, ``state`` (``working_dir``, 0.x also
                 ``open_file``; JSON in 0.x, a Python repr in 1.x)
    history      the model's messages.  In 1.x (function calling) each assistant message
                 carries the step's ``tool_calls``, whose name and JSON arguments are used
                 instead of re-parsing the action string; messages marked ``is_demo`` are the
                 demonstration of another task and are skipped
    info         ``exit_status``, ``submission`` (the diff), ``model_stats``, version
    A file with only ``history`` (the demonstrations shipped with SWE-agent) is read from
    its assistant ``action`` messages.

``sweagent_chat``  the chat export of Hugging Face's SWE-agent trajectory datasets
    (``nebius/SWE-agent-trajectories``): ``{"role": "system"|"user"|"ai", "text": ...}``,
    as a list or as a dataset row whose ``trajectory`` is that list (with ``instance_id``,
    ``model_name``, ``exit_status``, ``generated_patch``).  The command of an ``ai`` turn
    is its last fenced block; the next ``user`` turn is its output, which ends with
    ``(Open file: ...)`` / ``(Current directory: ...)``.

Commands.  SWE-agent 0.x and the export run the windowed file interface: ``open <path>
[<line>]``, ``goto``, ``scroll_up`` / ``scroll_down``, ``create``, ``edit <a>:<b>`` (with the
replacement up to ``end_of_edit``), ``search_dir`` / ``search_file`` / ``find_file`` and
``submit``; anything else is a shell command.  Each becomes a tool call of that name; the
ones that act on the open file name it as ``path`` (tracked from ``open`` / ``create`` and
the step's state), so the edits are attributed to their file.  SWE-agent 1.x calls
``str_replace_editor`` (OpenHands' editor), ``bash`` and ``submit``.  Neither version
records exit codes.
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from . import project, swebench

SOURCE_FORMAT = "sweagent_traj"
CHAT_FORMAT = "sweagent_chat"
AGENT_NAME = "swe-agent"

#: commands that act on the file open in the window
_ON_OPEN_FILE = {"goto", "scroll_up", "scroll_down", "edit", "insert"}
_ACI = _ON_OPEN_FILE | {"open", "create", "search_dir", "search_file", "find_file", "submit"}
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_STATE_KEY = re.compile(r"['\"](working_dir|open_file)['\"]\s*:\s*['\"]([^'\"]*)['\"]")
_FOOTER = re.compile(r"\s*\(Open file: ([^)\n]*)\)\s*\n\(Current directory: ([^)\n]*)\)\s*"
                     r"(?:\n\s*bash-\$\s*)?$")


def _state(raw: Any) -> Dict[str, str]:
    """``working_dir`` / ``open_file`` of a step's state: a dict, JSON or a Python repr."""
    if isinstance(raw, dict):
        return {k: str(v) for k, v in raw.items() if k in ("working_dir", "open_file")}
    out: Dict[str, str] = {}
    for key, value in _STATE_KEY.findall(str(raw or "")):
        out.setdefault(key, value)
    return out


def _open(path: str) -> Optional[str]:
    return path if path and path not in ("n/a", "None") else None


def _tokens(line: str) -> List[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _editor_args(action: str) -> dict:
    """Arguments of a ``str_replace_editor <command> <path> [--flag value ...]`` string."""
    tokens = _tokens(action)
    args: Dict[str, Any] = {}
    if len(tokens) > 1:
        args["command"] = tokens[1]
    if len(tokens) > 2:
        args["path"] = tokens[2]
    k = 3
    while k < len(tokens):
        if tokens[k].startswith("--"):
            key, values = tokens[k][2:], []
            k += 1
            while k < len(tokens) and not tokens[k].startswith("--"):
                values.append(tokens[k])
                k += 1
            args[key] = values[0] if len(values) == 1 else values
        else:
            k += 1
    return args


def command_call(action: str, open_file: Optional[str]) -> Tuple[str, dict, Optional[str]]:
    """(tool, arguments, open file afterwards) of one SWE-agent command string."""
    first, _, body = action.strip().partition("\n")
    tokens = _tokens(first)
    verb = tokens[0] if tokens else ""
    if verb == "str_replace_editor":
        return verb, _editor_args(action), open_file
    if verb not in _ACI:
        return "bash", {"command": action.strip()}, open_file
    rest = tokens[1:]
    if verb in ("open", "create"):
        path = rest[0] if rest else ""
        args: Dict[str, Any] = {"path": path}
        if verb == "open" and len(rest) > 1:
            args["line_number"] = rest[1]
        return verb, args, path or open_file
    if verb in _ON_OPEN_FILE:
        args = {"path": open_file} if open_file else {}
        if rest:
            args["lines" if verb == "edit" else "line_number"] = " ".join(rest)
        if body:
            args["text"] = re.sub(r"\n?end_of_edit\s*$", "", body)
        return verb, args, open_file
    if verb in ("search_dir", "search_file", "find_file"):
        args = {"pattern": rest[0]} if rest else {}
        where = rest[1] if len(rest) > 1 else (open_file if verb == "search_file" else None)
        if where:
            args["path"] = where
        return verb, args, open_file
    return verb, {}, open_file                                   # submit


def _turn_call(builder: swebench.Builder, n: int, thought: str, action: str,
               observation: Any, open_file: Optional[str],
               given: Optional[Tuple[str, dict]] = None) -> Optional[str]:
    """Add one step; returns the open file afterwards.  ``given``: the step's own tool call
    (1.x history), else the action string is parsed."""
    if not action.strip():
        builder.turn(thought, [])
        return open_file
    name, args, open_file = command_call(action, open_file)
    if given:
        name, args = given
        if name in ("open", "create") and args.get("path"):
            open_file = args["path"]
    call_id = f"call_{n}"
    builder.turn(thought, [(call_id, name, args)],
                 {call_id: (swebench.text_of(observation), {})})
    return open_file


def _history_calls(history: List[dict]) -> List[Tuple[str, dict]]:
    """(tool, arguments) of each assistant tool call in the history, in order."""
    out = []
    for message in history:
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            out.append((function.get("name") or "", swebench.json_args(function.get("arguments"))))
    return out


def is_traj(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    steps = obj.get("trajectory")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        return "action" in steps[0] and "observation" in steps[0]
    history = obj.get("history")
    return isinstance(history, list) and any(isinstance(m, dict) and "message_type" in m
                                             for m in history)


def parse_traj(obj: dict, *, source_file: str = "") -> dict:
    info = obj.get("info") or {}
    history = [m for m in obj.get("history") or [] if isinstance(m, dict)
               and not m.get("is_demo")]
    steps = obj.get("trajectory") or [
        {"action": m.get("action") or "", "thought": m.get("thought") or
         swebench.text_of(m.get("content")), "observation": ""}
        for m in history if m.get("role") == "assistant"]
    if not obj.get("trajectory"):                 # history only: outputs follow each action
        outputs = iter([swebench.text_of(m.get("content")) for k, m in enumerate(history)
                        if k and history[k - 1].get("role") == "assistant"
                        and m.get("role") in ("user", "tool")])
        for step in steps:
            step["observation"] = next(outputs, "")
    model = ""
    try:
        config = json.loads(obj.get("replay_config") or "{}")
        model = str(((config.get("agent") or {}).get("model") or {}).get("name") or "")
    except (TypeError, ValueError, AttributeError):
        pass
    builder = swebench.Builder(model)
    system = next((m for m in history if m.get("role") == "system"), None)
    task = next((m for m in history if m.get("role") == "user"), None)
    builder.message("system", swebench.text_of((system or {}).get("content")))
    builder.message("user", swebench.text_of((task or {}).get("content")))
    states = [_state(s.get("state")) for s in steps]
    roots = [states[0]["working_dir"]] if states and states[0].get("working_dir") else \
        swebench.find_roots([swebench.text_of((task or {}).get("content"))],
                            [s.get("action") or "" for s in steps])
    calls = _history_calls(history)
    aligned = len(calls) == sum(1 for s in steps if (s.get("action") or "").strip())
    queue = iter(calls if aligned else [])
    open_file: Optional[str] = None
    for n, step in enumerate(steps):
        action = step.get("action") or ""
        given = next(queue, None) if action.strip() else None
        open_file = _turn_call(builder, n, step.get("thought") or step.get("response") or "",
                               action, step.get("observation"), open_file, given)
        open_file = _open(states[n].get("open_file", "")) or open_file
    proj = project.make(project.SWEBENCH, roots,
                        swebench.instance_id(obj.get("environment"), info.get("instance_id"),
                                             source_file.split(".")[0]))
    return builder.envelope(
        agent=AGENT_NAME, version=str(info.get("swe_agent_version") or ""),
        source_format=SOURCE_FORMAT, source_file=source_file, proj=proj,
        extra={"exit_status": info.get("exit_status"),
               "submission": (info.get("submission") or "")[:20000],
               "model_stats": info.get("model_stats"),
               "tool_calls_from": "history" if aligned and calls else "action_strings"})


# --------------------------------------------------------------------------- #
# Hugging Face chat export

_CHAT_ROLES = {"system", "user", "ai"}


def _chat(obj: Any) -> Optional[List[dict]]:
    messages = obj.get("trajectory") if isinstance(obj, dict) else obj
    if isinstance(messages, list) and messages and all(
            isinstance(m, dict) and m.get("role") in _CHAT_ROLES and "text" in m for m in messages) \
            and any(m["role"] == "ai" for m in messages):
        return messages
    return None


def is_chat(obj: Any) -> bool:
    return _chat(obj) is not None


def parse_chat(obj: Any, *, source_file: str = "") -> dict:
    messages = _chat(obj) or []
    row = obj if isinstance(obj, dict) else {}
    builder = swebench.Builder(str(row.get("model_name") or ""))
    system = next((m for m in messages if m["role"] == "system"), {})
    builder.message("system", system.get("system_prompt") or system.get("text") or "")
    first = next((k for k, m in enumerate(messages) if m["role"] == "user"), None)
    task = messages[first]["text"] if first is not None else ""
    builder.message("user", task)
    roots = swebench.find_roots([task])
    footer = _FOOTER.search(task)
    open_file = _open(footer.group(1)) if footer else None
    commands: List[str] = []
    for k, message in enumerate(messages):
        if message["role"] != "ai":
            continue
        text = message.get("text") or ""
        blocks = list(_FENCE.finditer(text))
        action = blocks[-1].group(1).strip() if blocks else ""
        thought = text[:blocks[-1].start()].strip() if blocks else text
        reply = messages[k + 1] if k + 1 < len(messages) and messages[k + 1]["role"] == "user" \
            else None
        output = (reply or {}).get("text") or ""
        footer = _FOOTER.search(output)
        if footer:
            output = output[:footer.start()]
        commands.append(action)
        open_file = _turn_call(builder, k, thought, action, output, open_file)
        if footer:
            open_file = _open(footer.group(1)) or open_file
    if not roots:
        roots = swebench.find_roots([], commands)
    proj = project.make(project.SWEBENCH, roots,
                        swebench.instance_id(row.get("instance_id"), source_file.split(".")[0]))
    return builder.envelope(
        agent=AGENT_NAME, version="", source_format=CHAT_FORMAT, source_file=source_file,
        proj=proj, extra={"exit_status": row.get("exit_status"),
                          "submission": (row.get("generated_patch") or "")[:20000]})
