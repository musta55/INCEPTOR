"""Codex CLI -> ATIF.

Source format: the native rollout JSONL written by ``codex exec``
(``~/.codex/sessions/<Y>/<M>/<D>/rollout-*.jsonl``), one JSON object per line with a
``type`` of ``session_meta`` / ``turn_context`` / ``response_item`` / ``event_msg``.

Step boundary: Codex appends one ``event_msg/token_count`` after every model response,
carrying that response's own usage in ``info.last_token_usage``, so the items between two
token counts are exactly one LLM inference. This is the boundary for rollouts of
``cli_version`` 0.138 (this corpus): 18,671 of its 68,163 responses carry no ``reasoning``
item and 1,802 carry two or three, so the older rule -- every ``reasoning`` item starts an
inference -- would merge the first kind into its predecessor (inventing parallel calls;
0.138 never issued more than one call per response here) and split the second. Rollouts
without per-response token counts fall back to that older rule; ``extra.step_boundary``
records which one was used.

Chain of thought is encrypted in this corpus (``summary: []``, ``content: null``,
``encrypted_content`` set), so ``reasoning_content`` is usually absent and
``extra.reasoning_encrypted`` records why. Image outputs (``view_image``) keep a
placeholder instead of their base64 payload; ``patch_apply_end`` events are attached to
the ``exec_command`` call that applied the patch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import schema

SOURCE_FORMAT = "codex_rollout_jsonl"
SUPPORTED_MAJOR_MINOR = ("0.114", "0.138")

CALL_TYPES = ("function_call", "custom_tool_call")
OUTPUT_TYPES = ("function_call_output", "custom_tool_call_output")
#: response_item kinds the parser reads; anything else is counted, never dropped silently
HANDLED_ITEMS = CALL_TYPES + OUTPUT_TYPES + ("message", "reasoning", "web_search_call")


def read_events(path: Path) -> List[dict]:
    events: List[dict] = []
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event["__line__"] = lineno
            events.append(event)
    return events


def _payload(event: dict) -> dict:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _arguments(payload: dict) -> Any:
    if payload.get("type") == "custom_tool_call":
        return {"input": payload.get("input", "")}
    raw = payload.get("arguments")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _reasoning_text(payload: dict) -> str:
    parts: List[str] = []
    for item in payload.get("summary") or []:
        if isinstance(item, dict):
            parts.append(item.get("text", ""))
        elif isinstance(item, str):
            parts.append(item)
    content = payload.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def p_base_instructions(payload: dict) -> str:
    """Codex records its own system prompt in session_meta.base_instructions."""
    value = payload.get("base_instructions")
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def _context_step(step_id: int, source: str, message: str, timestamp: str,
                  record_kind: str) -> dict:
    step = schema.message_step(step_id, source, message, timestamp)
    step["extra"] = {"record_kind": record_kind}
    return step


def _last_usage(payload: dict) -> dict:
    info = payload.get("info")
    return (info.get("last_token_usage") or {}) if isinstance(info, dict) else {}


def parse(path: Path, *, extra: Optional[dict] = None) -> dict:
    path = Path(path)
    events = read_events(path)

    meta: Dict[str, Any] = {}
    turn_context: Dict[str, Any] = {}
    for event in events:
        if event.get("type") == "session_meta" and not meta:
            meta = _payload(event)
        elif event.get("type") == "turn_context" and not turn_context:
            turn_context = _payload(event)
    model = turn_context.get("model") or meta.get("model") or ""

    outputs: Dict[str, dict] = {}
    patches: Dict[str, dict] = {}
    for event in events:
        payload = _payload(event)
        if payload.get("type") in OUTPUT_TYPES and payload.get("call_id"):
            outputs[payload["call_id"]] = payload
        elif payload.get("type") == "patch_apply_end" and payload.get("call_id"):
            patches[payload["call_id"]] = payload

    boundary = ("token_count" if any(event.get("type") == "event_msg"
                                     and _payload(event).get("type") == "token_count"
                                     and _last_usage(_payload(event)) for event in events)
                else "reasoning")

    # The instruction blocks the agent was given before the task: its system prompt,
    # the sandbox/permissions developer message, and any project AGENTS.md. They are
    # context the agent acted under, so they are steps, not metadata -- but they are
    # tagged with extra.record_kind so analysis can exclude them from inference counts.
    task_messages = {
        (e.get("payload") or {}).get("message", "").strip()
        for e in events
        if e.get("type") == "event_msg" and (e.get("payload") or {}).get("type") == "user_message"
    }

    steps: List[dict] = []
    current: Optional[dict] = None
    totals = {"prompt": 0, "completion": 0, "cached": 0}
    encrypted_reasoning = 0
    event_counts: Dict[str, int] = {}
    unhandled: Dict[str, int] = {}

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        for call in current.get("tool_calls") or []:
            payload = outputs.get(call["tool_call_id"])
            if payload is None:
                continue
            body, images = schema.render_content(payload.get("output", ""))
            exit_code = None
            status = payload.get("status")
            marker = "Process exited with code "
            if marker in body:
                tail = body.split(marker, 1)[1][:10].split()[0].strip(".")
                exit_code = int(tail) if tail.isdigit() else None
            patch = patches.get(call["tool_call_id"])
            schema.add_observation(
                current, call["tool_call_id"], body, exit_code=exit_code, status=status,
                images=images or None,
                patch_apply={"success": patch.get("success"),
                             "changes": [{"path": name,
                                          "type": change.get("type")
                                          if isinstance(change, dict) else change}
                                         for name, change in (patch.get("changes") or {}).items()]}
                if patch else None)
        schema.finalize(current)
        current = None

    def start(timestamp: str) -> dict:
        nonlocal current
        flush()
        current = schema.agent_step(len(steps) + 1, timestamp=timestamp, model_name=model)
        current["extra"] = {"source_lines": []}
        steps.append(current)
        return current

    for event in events:
        payload = _payload(event)
        kind = event.get("type")
        subtype = payload.get("type")
        timestamp = event.get("timestamp") or ""
        if kind == "event_msg" and subtype:
            event_counts[subtype] = event_counts.get(subtype, 0) + 1
        if kind == "response_item" and subtype not in HANDLED_ITEMS:
            unhandled[str(subtype)] = unhandled.get(str(subtype), 0) + 1

        if kind == "session_meta":
            instructions = p_base_instructions(payload)
            if instructions:
                steps.append(_context_step(len(steps) + 1, "system", instructions, timestamp,
                                           "agent_system_prompt"))
        elif kind == "response_item" and subtype == "message" and \
                payload.get("role") in ("developer", "user"):
            body = "\n".join(part.get("text", "") for part in (payload.get("content") or [])
                              if isinstance(part, dict)).strip()
            # the task prompt itself also arrives as an event_msg; keep it there only
            if body and body not in task_messages:
                steps.append(_context_step(
                    len(steps) + 1,
                    "system" if payload["role"] == "developer" else "user", body, timestamp,
                    "sandbox_instructions" if payload["role"] == "developer"
                    else "project_instructions"))
        elif kind == "event_msg" and subtype == "user_message":
            flush()
            steps.append(schema.message_step(len(steps) + 1, "user",
                                             (payload.get("message") or "").strip(), timestamp))
        elif kind == "response_item" and subtype == "reasoning":
            step = start(timestamp) if boundary == "reasoning" else (current or start(timestamp))
            step["extra"]["source_lines"].append(event["__line__"])
            text = _reasoning_text(payload)
            if text:
                step["reasoning_content"] = "\n".join(
                    t for t in (step.get("reasoning_content"), text) if t)
            else:
                encrypted_reasoning += 1
                step["extra"]["reasoning_encrypted"] = bool(payload.get("encrypted_content"))
        elif kind == "event_msg" and subtype == "agent_message":
            step = current or start(timestamp)
            step["message"] = (step["message"] + "\n" + (payload.get("message") or "")).strip()
            if payload.get("phase"):
                step["extra"]["phase"] = payload["phase"]
        elif kind == "response_item" and subtype in CALL_TYPES:
            step = current or start(timestamp)
            step["extra"]["source_lines"].append(event["__line__"])
            schema.add_tool_call(step, payload.get("call_id", ""), payload.get("name", ""),
                                 _arguments(payload))
        elif kind == "response_item" and subtype == "web_search_call":
            step = current or start(timestamp)
            schema.add_tool_call(step, payload.get("id", "") or f"web-{event['__line__']}",
                                 "web_search", payload.get("action") or {})
        elif kind == "event_msg" and subtype == "token_count":
            info = payload.get("info") or {}
            total = info.get("total_token_usage") or {}
            if total:
                totals["prompt"] = max(totals["prompt"], total.get("input_tokens") or 0)
                totals["completion"] = max(totals["completion"], total.get("output_tokens") or 0)
                totals["cached"] = max(totals["cached"], total.get("cached_input_tokens") or 0)
            last = _last_usage(payload)
            if current is not None and last:
                current["metrics"] = {
                    "prompt_tokens": last.get("input_tokens") or 0,
                    "completion_tokens": last.get("output_tokens") or 0,
                    "cached_tokens": last.get("cached_input_tokens") or 0,
                }
                if boundary == "token_count":
                    flush()                      # this response's usage closes it
        elif kind == "event_msg" and subtype in ("task_complete", "turn_aborted"):
            flush()
    flush()

    terminal = None
    final_message = ""
    for event in reversed(events):
        payload = _payload(event)
        if event.get("type") == "event_msg" and payload.get("type") in (
                "task_complete", "turn_aborted", "error"):
            terminal = payload["type"]
            final_message = str(payload.get("last_agent_message") or payload.get("message") or "")
            break
    started = next((_payload(e) for e in events if _payload(e).get("type") == "task_started"), {})
    finished = next((_payload(e) for e in reversed(events)
                     if _payload(e).get("type") == "task_complete"), {})
    agent_turns = sum(1 for s in steps if s["source"] == "agent")
    unanswered = [call["tool_call_id"] for step in steps for call in step.get("tool_calls") or []
                  if call["tool_call_id"] not in outputs]

    steps = schema.placeholder_steps(steps, "no conversation records in the rollout")
    version = str(meta.get("cli_version") or "")
    known_gaps = ["reasoning_encrypted"] if encrypted_reasoning else []
    if unanswered:
        known_gaps.append("tool_calls_without_result")
    if not agent_turns:
        known_gaps.append("no_model_output")
    trajectory_extra: Dict[str, Any] = {
        "source_format": SOURCE_FORMAT,
        "source_file": path.name,
        "parser_version": schema.PARSER_VERSION,
        "cwd": meta.get("cwd") or turn_context.get("cwd") or "",
        "originator": meta.get("originator", ""),
        "sandbox_policy": (turn_context.get("sandbox_policy") or {}).get("type", ""),
        "approval_policy": turn_context.get("approval_policy", ""),
        "turn_context": {k: v for k, v in turn_context.items()
                         if k in ("turn_id", "current_date", "timezone", "personality",
                                  "collaboration_mode", "summary", "truncation_policy",
                                  "user_instructions", "effort", "permission_profile")},
        "outcome": terminal,
        "duration_ms": finished.get("duration_ms"),
        "time_to_first_token_ms": finished.get("time_to_first_token_ms"),
        "model_context_window": started.get("model_context_window"),
        "step_boundary": boundary,
        "parsed_agent_turns": agent_turns,
        "event_counts": event_counts,
        "encrypted_reasoning_items": encrypted_reasoning,
        "final_message": schema.truncate(final_message, 4000)[0],
        "known_gaps": known_gaps,
    }
    if unanswered:
        trajectory_extra["unanswered_tool_calls"] = unanswered
    if unhandled:
        trajectory_extra["unhandled_record_counts"] = unhandled
    if version and not version.startswith(SUPPORTED_MAJOR_MINOR):
        trajectory_extra["schema_warning"] = (
            f"rollout written by cli_version {version}; parser targets "
            f"{'/'.join(SUPPORTED_MAJOR_MINOR)}.x")
    if extra:
        trajectory_extra.update(extra)

    return schema.envelope(
        session_id=meta.get("id"),
        agent_name="codex",
        agent_version=version,
        model_name=model,
        steps=steps,
        final_metrics={
            "total_prompt_tokens": totals["prompt"],
            "total_completion_tokens": totals["completion"],
            "total_cached_tokens": totals["cached"],
            "total_steps": len(steps),
        },
        extra=trajectory_extra,
    )
