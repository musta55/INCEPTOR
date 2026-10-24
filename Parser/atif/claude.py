"""Claude Code -> ATIF.

Source format: a line-per-message ``repr()`` dump of ``claude-agent-sdk`` objects,
e.g. ``AssistantMessage(content=[ToolUseBlock(id='toolu_01', name='Read', input={...})])``.
This is a derived log, not Claude Code's native session JSONL, and it loses some of what
the native log records.

Claude Code's raw JSON is read too (``read_json_messages``, format ``JSON_SOURCE_FORMAT``):
the ``--output-format stream-json`` stream, whose events are the same messages the SDK
prints (``{"type": "assistant", "message": {...}, "parent_tool_use_id": ...}``), and the
session transcript the CLI keeps in ``~/.claude/projects/`` (no ``init`` event: one is
made from the events' ``cwd``, ``sessionId`` and ``version``; its sidechain events, whose
delegating call the transcript does not name, are left out and counted).  Both become the
SDK's message objects, so everything below applies unchanged.

Three things the format forces on us:

1. The SDK emits **one message per content block**, so a single LLM inference spans
   several ``AssistantMessage`` lines (thinking, then text, then each tool_use). The SDK of
   this corpus (Claude Code with ``claude-opus-5``) stamps every one of them with the API
   ``message_id``, and starts executing a tool while the rest of the response is still
   streaming, so tool results can arrive *between* two tool_use blocks of the same
   response. One step is therefore one ``message_id``. Dumps from older SDKs carry no
   ``message_id``; for them a turn ends when the next ``UserMessage`` (tool results)
   arrives, as before. ``ResultMessage.num_turns`` no longer counts API responses in this
   SDK (it agrees with the ``message_id`` count in 609 of 2,639 runs), so it is recorded
   but is not the cross-check any more.
2. Subagent (Task/Agent tool) messages are interleaved with the parent's and
   distinguished only by ``parent_tool_use_id``, which becomes an embedded
   ATIF ``subagent_trajectories`` entry (nested ones embed in their own parent).
3. A few dumps are damaged: a line cut short or corrupted mid-way, a head that was never
   written (no ``init``), a tail cut before the tool result or ``ResultMessage``. Such
   lines are recovered up to the last keyword argument that still parses, and every
   loss is recorded in ``extra`` rather than raised.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import schema

SOURCE_FORMAT = "claude_agent_sdk_repr"
JSON_SOURCE_FORMAT = "claude_code_stream_json"
AGENT_NAME = "claude-code"
#: an inference the CLI fabricated to report an API failure; no model was called
SYNTHETIC_MODEL = "<synthetic>"
#: ``, name=`` -- the start of a keyword argument, where a damaged line can be cut
_KEYWORD = re.compile(r", (\w+)=")
MAX_RECOVERY_CUTS = 64
#: SDK message classes that describe background tasks (Bash run_in_background, subagents)
TASK_CLASSES = ("TaskStartedMessage", "TaskNotificationMessage", "TaskProgressMessage",
                "TaskUpdatedMessage")


class ClaudeLogError(Exception):
    pass


def _node_to_obj(node: ast.AST) -> Any:
    """Convert a Python literal/constructor-call AST into plain data.

    Uses ``ast`` rather than ``eval`` so a trajectory can never execute anything.
    Constructor calls become ``{"__type__": ClassName, ...kwargs}``.
    """
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ClaudeLogError("unexpected non-name call in log line")
        obj: Dict[str, Any] = {"__type__": node.func.id}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ClaudeLogError("unexpected **kwargs in log line")
            obj[keyword.arg] = _node_to_obj(keyword.value)
        if node.args:
            obj["__args__"] = [_node_to_obj(arg) for arg in node.args]
        return obj
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_node_to_obj(element) for element in node.elts]
    if isinstance(node, ast.Dict):
        return {_node_to_obj(k): _node_to_obj(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Constant):
        return node.value
    return ast.literal_eval(node)


def _parse_line(line: str) -> dict:
    obj = _node_to_obj(ast.parse(line, mode="eval").body)
    if not isinstance(obj, dict) or "__type__" not in obj:
        raise ClaudeLogError("line is not a message constructor")
    return obj


def _recover(line: str) -> Optional[dict]:
    """Parse the longest prefix of a damaged line that ends at a keyword argument.

    ``UserMessage(content=[...], uuid='..', tool_use_result={...corrupted...})`` keeps its
    content and uuid; the dropped tail is named in ``__recovered__``."""
    cuts = [m.start() for m in _KEYWORD.finditer(line)][::-1][:MAX_RECOVERY_CUTS]
    for cut in cuts:
        try:
            obj = _parse_line(line[:cut] + ")")
        except (SyntaxError, ValueError, ClaudeLogError, RecursionError):
            continue
        obj["__recovered__"] = {"dropped_chars": len(line) - cut,
                                "dropped_from_field": _KEYWORD.match(line, cut).group(1)}
        return obj
    return None


def read_messages(path: Path, damaged: Optional[List[dict]] = None) -> List[dict]:
    """Parse every line of the dump.

    A line that does not parse is recovered up to its last intact keyword argument;
    failing that it is skipped. Either way it is reported in ``damaged`` (when given) as
    ``{"line", "kind", ...}``, so a caller can record the loss.
    """
    messages: List[dict] = []
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = _parse_line(line)
            except (SyntaxError, ValueError, ClaudeLogError, RecursionError) as exc:
                obj = _recover(line)
                if damaged is not None:
                    entry: Dict[str, Any] = {"line": lineno, "error": type(exc).__name__,
                                             "chars": len(line)}
                    if obj is None:
                        entry.update(kind="unparsed", preview=line[:500])
                    else:
                        entry.update(kind="recovered", message_type=obj["__type__"],
                                     **obj["__recovered__"])
                    damaged.append(entry)
                if obj is None:
                    continue
            obj["__line__"] = lineno
            messages.append(obj)
    return messages


#: stream-json / transcript content block type -> SDK block class
_JSON_BLOCKS = {"text": "TextBlock", "thinking": "ThinkingBlock", "tool_use": "ToolUseBlock",
                "tool_result": "ToolResultBlock", "server_tool_use": "ServerToolUseBlock"}
#: stream-json system subtype -> SDK task message class (TASK_CLASSES)
_JSON_TASKS = {"task_started": "TaskStartedMessage", "task_notification": "TaskNotificationMessage",
               "task_progress": "TaskProgressMessage", "task_updated": "TaskUpdatedMessage"}


def is_json_log(path: Path) -> bool:
    """Whether a Claude log is raw JSON (stream-json or a transcript), not an SDK dump."""
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            if raw.strip():
                return raw.lstrip().startswith("{")
    return False


def _json_block(block: dict) -> dict:
    kind = str(block.get("type") or "")
    out = {k: v for k, v in block.items() if k != "type"}
    out["__type__"] = _JSON_BLOCKS.get(kind) or (
        "".join(part.title() for part in kind.split("_")) + "Block")
    return out


def message_from_event(event: dict) -> Optional[dict]:
    """One stream-json or transcript event as the SDK message it stands for (None for an
    event the SDK has no message for: a stream delta, a transcript summary)."""
    kind = event.get("type")
    if kind == "system":
        subtype = event.get("subtype")
        return {"__type__": _JSON_TASKS.get(subtype, "SystemMessage"), "subtype": subtype,
                "data": event}
    if kind in ("assistant", "user"):
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        content = message.get("content")
        blocks = content if isinstance(content, str) else [
            _json_block(b) for b in content or [] if isinstance(b, dict)]
        out: Dict[str, Any] = {"content": blocks,
                               "parent_tool_use_id": event.get("parent_tool_use_id"),
                               "uuid": event.get("uuid"),
                               "session_id": event.get("session_id") or event.get("sessionId")}
        if kind == "assistant":
            out.update({"__type__": "AssistantMessage", "model": message.get("model"),
                        "usage": message.get("usage"), "message_id": message.get("id"),
                        "stop_reason": message.get("stop_reason"),
                        "error": event.get("error")})
        else:
            out["__type__"] = "UserMessage"
            result = event.get("tool_use_result", event.get("toolUseResult"))
            if result is not None:
                out["tool_use_result"] = result
        return out
    if kind == "result":
        return {"__type__": "ResultMessage", **{k: v for k, v in event.items() if k != "type"}}
    return None


def read_json_messages(path: Path, damaged: Optional[List[dict]] = None) -> List[dict]:
    """``read_messages`` for Claude Code's raw JSON: one event per line.  A line that is
    not JSON is reported in ``damaged``; sidechain events of a transcript are dropped and
    reported there as one entry."""
    messages: List[dict] = []
    first: Dict[str, Any] = {}
    sidechain = 0
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                if damaged is not None:
                    damaged.append({"line": lineno, "error": type(exc).__name__,
                                    "chars": len(line), "kind": "unparsed",
                                    "preview": line[:500]})
                continue
            if not isinstance(event, dict):
                continue
            if event.get("isSidechain"):
                sidechain += 1
                continue
            if not first and event.get("cwd"):
                first = event
            message = message_from_event(event)
            if message is not None:
                message["__line__"] = lineno
                messages.append(message)
    if sidechain and damaged is not None:
        damaged.append({"line": 0, "kind": "sidechain_dropped", "events": sidechain})
    if first and not any(m["__type__"] == "SystemMessage" and m.get("subtype") == "init"
                         for m in messages):
        model = next((m.get("model") for m in messages
                      if m["__type__"] == "AssistantMessage" and m.get("model")), "")
        messages.insert(0, {"__type__": "SystemMessage", "subtype": "init", "__line__": 0,
                            "data": {"type": "system", "subtype": "init",
                                     "cwd": first.get("cwd"),
                                     "session_id": first.get("sessionId")
                                     or first.get("session_id"),
                                     "claude_code_version": first.get("version", ""),
                                     "model": model, "synthesized": True}})
    return messages


def _blocks(message: dict) -> List[dict]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"__type__": "TextBlock", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _result_text(content: Any) -> str:
    """Tool results arrive as a string or as a list of content parts (text, image,
    tool_reference); images become a placeholder, see ``schema.render_content``."""
    return schema.render_content(content)[0]


def _data(message: dict) -> dict:
    data = message.get("data")
    return data if isinstance(data, dict) else {}


def parse(path: Path, *, extra: Optional[dict] = None) -> dict:
    path = Path(path)
    damaged: List[dict] = []
    raw_json = is_json_log(path)
    source_format = JSON_SOURCE_FORMAT if raw_json else SOURCE_FORMAT
    messages = (read_json_messages if raw_json else read_messages)(path, damaged)

    init = next((m for m in messages
                 if m["__type__"] == "SystemMessage" and m.get("subtype") == "init"), {})
    meta = _data(init)
    result_msg = next((m for m in messages if m["__type__"] == "ResultMessage"), {})

    declared = {b.get("id") for m in messages if m["__type__"] == "AssistantMessage"
                for b in _blocks(m) if b["__type__"] == "ToolUseBlock"}
    # tool_use_id -> (text, is_error, images); and the SDK's structured copy of the result
    results: Dict[str, Tuple[str, bool, int]] = {}
    structured: Dict[str, dict] = {}
    for message in messages:
        if message["__type__"] != "UserMessage":
            continue
        for block in _blocks(message):
            if block["__type__"] == "ToolResultBlock":
                text, images = schema.render_content(block.get("content"))
                results[block.get("tool_use_id", "")] = (text, bool(block.get("is_error")),
                                                        images)
                if isinstance(message.get("tool_use_result"), dict):
                    structured[block.get("tool_use_id", "")] = message["tool_use_result"]

    denied: Dict[str, str] = {}
    for entry in result_msg.get("permission_denials") or []:
        if isinstance(entry, dict) and entry.get("tool_use_id"):
            denied[entry["tool_use_id"]] = ""
    for message in messages:
        if message["__type__"] == "SystemMessage" and message.get("subtype") == "permission_denied":
            data = _data(message)
            if data.get("tool_use_id"):
                denied[data["tool_use_id"]] = str(data.get("decision_reason") or "")

    # group the conversation into scopes: None = main agent, otherwise the
    # tool_use_id of the delegating Agent/Task call
    scopes: Dict[Optional[str], List[dict]] = {}
    for message in messages:
        if message["__type__"] in ("AssistantMessage", "UserMessage"):
            scopes.setdefault(message.get("parent_tool_use_id"), []).append(message)

    unknown_blocks: Dict[str, int] = {}
    thinking = {"empty": 0, "text": 0}

    def build(sequence: List[dict], main: bool) -> List[dict]:
        steps: List[dict] = []
        by_message_id: Dict[str, dict] = {}
        current: Optional[dict] = None
        for message in sequence:
            blocks = _blocks(message)
            if message["__type__"] == "UserMessage":
                current = None  # tool results close the inference that issued them
                text = "\n".join(b.get("text", "") for b in blocks
                                 if b["__type__"] == "TextBlock").strip()
                if text:
                    step = schema.message_step(len(steps) + 1, "user", text)
                    # the task prompt is never in the dump: a main-scope user text is the
                    # CLI's (image notes, "resume" nudges), a subagent's is its prompt
                    step["extra"] = {"record_kind": "injected_user_message" if main
                                     else "delegated_prompt"}
                    steps.append(step)
                orphans = [b for b in blocks if b["__type__"] == "ToolResultBlock"
                           and b.get("tool_use_id") not in declared]
                if orphans:
                    # the call is not in the log (its head was never written); keep the
                    # output, on a system step, rather than lose it
                    step = schema.message_step(
                        len(steps) + 1, "system",
                        f"[{len(orphans)} tool result(s) whose call is not in the log]")
                    step["extra"] = {"record_kind": "orphan_tool_result"}
                    for block in orphans:
                        text, original = schema.truncate(_result_text(block.get("content")))
                        orphan: Dict[str, Any] = {"content": text, "extra": {
                            "orphan_call_id": block.get("tool_use_id", ""),
                            "is_error": bool(block.get("is_error"))}}
                        if original > len(text):
                            orphan["extra"].update(original_chars=original, truncated=True)
                        step.setdefault("observation", {"results": []})["results"].append(orphan)
                    steps.append(step)
                continue
            message_id = message.get("message_id")
            step = by_message_id.get(message_id) if message_id else current
            if step is None:
                step = schema.agent_step(len(steps) + 1)
                step["extra"] = {"source_lines": []}
                model = message.get("model") or ""
                if model == SYNTHETIC_MODEL:
                    # an API error the CLI reported as a message: no inference happened
                    step["llm_call_count"] = 0
                    step["extra"]["synthetic"] = True
                elif model:
                    step["model_name"] = model
                if message_id:
                    step["extra"]["message_id"] = message_id
                    by_message_id[message_id] = step
                usage = message.get("usage")
                if isinstance(usage, dict) and model != SYNTHETIC_MODEL:
                    # the SDK repeats the response's message_start usage on every block:
                    # the prompt side is final, output_tokens is not, so it is left out
                    step["metrics"] = {
                        "prompt_tokens": ((usage.get("input_tokens") or 0)
                                          + (usage.get("cache_creation_input_tokens") or 0)
                                          + (usage.get("cache_read_input_tokens") or 0)),
                        "cached_tokens": usage.get("cache_read_input_tokens") or 0}
                steps.append(step)
            current = step
            step["extra"]["source_lines"].append(message["__line__"])
            if message.get("stop_reason"):
                step["extra"]["stop_reason"] = message["stop_reason"]
            if message.get("error"):
                step["extra"]["api_error"] = message["error"]
            for block in blocks:
                kind = block["__type__"]
                if kind == "ThinkingBlock":
                    text = block.get("thinking") or ""
                    thinking["text" if text else "empty"] += 1
                    step["reasoning_content"] = step.get("reasoning_content", "") + text
                elif kind == "TextBlock":
                    step["message"] = (step["message"] + "\n" + block.get("text", "")).strip()
                elif kind == "ToolUseBlock":
                    schema.add_tool_call(step, block.get("id", ""), block.get("name", ""),
                                         block.get("input") or {})
                else:
                    # never drop a block type silently (e.g. SensorDataBlock)
                    unknown_blocks[kind] = unknown_blocks.get(kind, 0) + 1
                    step["extra"].setdefault("unparsed_blocks", []).append(kind)
        for step in steps:
            if step["source"] != "agent":
                continue
            for call in step.get("tool_calls") or []:
                found = results.get(call["tool_call_id"])
                if found is not None:
                    schema.add_observation(
                        step, call["tool_call_id"], found[0], is_error=found[1],
                        images=found[2] or None,
                        permission_denied=(denied[call["tool_call_id"]] or True)
                        if call["tool_call_id"] in denied else None)
            schema.finalize(step)
        return steps

    steps_by_scope: Dict[Optional[str], List[dict]] = {
        scope: schema.placeholder_steps(
            build(sequence, scope is None),
            "no conversation messages in the log" if scope is None
            else "no message of this subagent is in the log")
        for scope, sequence in scopes.items()}
    steps_by_scope.setdefault(None, schema.placeholder_steps(
        [], "no conversation messages in the log"))

    # which scope issued each call, so a nested delegation embeds in its own parent
    owner: Dict[str, Optional[str]] = {}
    call_args: Dict[str, dict] = {}
    for scope, steps in steps_by_scope.items():
        for step in steps:
            for call in step.get("tool_calls") or []:
                owner[call["tool_call_id"]] = scope
                call_args[call["tool_call_id"]] = call.get("arguments") or {}
    children: Dict[Optional[str], List[str]] = {}
    for scope in steps_by_scope:
        if scope is not None:
            children.setdefault(owner.get(scope), []).append(scope)

    def embed(scope: Optional[str]) -> List[dict]:
        subagents: List[dict] = []
        for parent_call_id in children.get(scope, []):
            sub_steps = steps_by_scope[parent_call_id]
            trajectory_id = "sub-" + str(parent_call_id)
            # the Agent tool's structured result reports what the subagent was and cost
            report = structured.get(parent_call_id, {})
            sub_extra: Dict[str, Any] = {
                "scope": "subagent", "delegating_tool_call_id": parent_call_id,
                "source_format": source_format,
                "subagent_type": report.get("agentType")
                or call_args.get(parent_call_id, {}).get("subagent_type", ""),
            }
            for key, name in (("status", "status"), ("resolvedModel", "resolved_model"),
                              ("totalToolUseCount", "reported_tool_uses"),
                              ("totalTokens", "reported_total_tokens"),
                              ("totalDurationMs", "duration_ms")):
                if report.get(key) is not None:
                    sub_extra[name] = report[key]
            sub_model = report.get("resolvedModel") or next(
                (s["model_name"] for s in sub_steps if s.get("model_name")), "")
            subagents.append(schema.envelope(
                session_id=meta.get("session_id"),
                agent_name=AGENT_NAME,
                agent_version=meta.get("claude_code_version", ""),
                model_name=sub_model,
                steps=sub_steps,
                trajectory_id=trajectory_id,
                subagents=embed(parent_call_id),
                final_metrics={"total_steps": len(sub_steps)},
                extra=sub_extra,
            ))
            # link the delegating call to the embedded trajectory
            for step in steps_by_scope.get(scope, []):
                if any(c["tool_call_id"] == parent_call_id for c in step.get("tool_calls") or []):
                    schema.attach_subagent_ref(step, parent_call_id, trajectory_id)
        return subagents

    main_steps = steps_by_scope[None]
    subagents = embed(None)

    unanswered = [call["tool_call_id"]
                  for steps in steps_by_scope.values() for step in steps
                  for call in step.get("tool_calls") or [] if call["tool_call_id"] not in results]

    system_subtypes: Dict[str, int] = {}
    tasks: Dict[str, Dict[str, Any]] = {}
    for message in messages:
        kind = message["__type__"]
        if kind == "SystemMessage" or kind in TASK_CLASSES:
            key = str(message.get("subtype"))
            system_subtypes[key] = system_subtypes.get(key, 0) + 1
        if kind in TASK_CLASSES and kind != "TaskProgressMessage":
            data = _data(message)
            task_id = str(data.get("task_id") or message.get("task_id") or "")
            task = tasks.setdefault(task_id, {"task_id": task_id})
            # a local_agent's notification carries the CLI's own cost report (``usage``),
            # which differs from the Agent tool's structured result kept on the sub-agent;
            # its started message's ``prompt`` is the Agent call's prompt, already kept
            for field in ("tool_use_id", "task_type", "subagent_type", "description", "status",
                          "summary", "usage"):
                value = data.get(field, message.get(field))
                if value:
                    task[field] = value
            patch = data.get("patch")
            if isinstance(patch, dict) and patch.get("status"):
                task["status"] = patch["status"]

    usage = result_msg.get("usage") or {}
    if result_msg:
        final_metrics: Dict[str, Any] = {
            "total_prompt_tokens": ((usage.get("input_tokens") or 0)
                                    + (usage.get("cache_creation_input_tokens") or 0)
                                    + (usage.get("cache_read_input_tokens") or 0)),
            "total_completion_tokens": usage.get("output_tokens") or 0,
            "total_cached_tokens": usage.get("cache_read_input_tokens") or 0,
            "total_cost_usd": result_msg.get("total_cost_usd") or 0.0,
        }
    else:
        # no ResultMessage: the prompt side is known per step; output tokens are not
        streamed = [s.get("metrics") or {} for steps in steps_by_scope.values() for s in steps]
        final_metrics = {
            "total_prompt_tokens": sum(m.get("prompt_tokens", 0) for m in streamed),
            "total_cached_tokens": sum(m.get("cached_tokens", 0) for m in streamed)}
    final_metrics["total_steps"] = len(main_steps)

    agent_turns = sum(1 for s in main_steps if s["source"] == "agent")
    has_message_ids = any(m.get("message_id") for m in messages
                          if m["__type__"] == "AssistantMessage")
    known_gaps = ["no_per_step_timestamps", "no_initial_user_prompt"]
    known_gaps.append("per_step_completion_tokens_unavailable" if has_message_ids
                      else "no_request_id_grouping")
    if thinking["empty"] and not thinking["text"]:
        known_gaps.append("thinking_content_omitted")
    if not init:
        known_gaps.append("log_head_missing")
    if not result_msg:
        known_gaps.append("no_result_message")
    if any(d["kind"] == "recovered" for d in damaged):
        known_gaps.append("corrupted_source_line")
    if any(d["kind"] == "unparsed" for d in damaged):
        known_gaps.append("unparsed_source_line")
    if unanswered:
        known_gaps.append("tool_calls_without_result")

    trajectory_extra: Dict[str, Any] = {
        "source_format": source_format,
        "source_file": path.name,
        "parser_version": schema.PARSER_VERSION,
        "cwd": meta.get("cwd", ""),
        "permission_mode": meta.get("permissionMode", ""),
        "outcome": result_msg.get("subtype") or "missing",
        "is_error": result_msg.get("is_error"),
        "stop_reason": result_msg.get("stop_reason"),
        "api_error_status": result_msg.get("api_error_status"),
        "errors": result_msg.get("errors"),
        "duration_ms": result_msg.get("duration_ms"),
        "duration_api_ms": result_msg.get("duration_api_ms"),
        "reported_num_turns": result_msg.get("num_turns"),
        "parsed_agent_turns": agent_turns,
        "step_boundary": "message_id" if has_message_ids else "user_message",
        "model_usage": result_msg.get("model_usage"),
        "system_event_counts": system_subtypes,
        "final_message": schema.truncate(result_msg.get("result"), 4000)[0],
        # documented gaps of this source format, so downstream analysis can filter
        "known_gaps": known_gaps,
    }
    if tasks:
        trajectory_extra["background_tasks"] = list(tasks.values())
    if denied:
        trajectory_extra["permission_denials"] = sorted(denied)
    if unanswered:
        trajectory_extra["unanswered_tool_calls"] = unanswered
    if damaged:
        trajectory_extra["damaged_lines"] = damaged
    if unknown_blocks:
        trajectory_extra["unparsed_block_types"] = unknown_blocks
    if extra:
        trajectory_extra.update(extra)

    return schema.envelope(
        session_id=meta.get("session_id") or result_msg.get("session_id"),
        agent_name=AGENT_NAME,
        agent_version=meta.get("claude_code_version", ""),
        model_name=meta.get("model") or next(
            (s["model_name"] for s in main_steps if s.get("model_name")), ""),
        steps=main_steps,
        subagents=subagents,
        final_metrics=final_metrics,
        extra=trajectory_extra,
        tool_definitions=[{"type": "function", "function": {"name": name}}
                          for name in meta.get("tools") or []],
    )
