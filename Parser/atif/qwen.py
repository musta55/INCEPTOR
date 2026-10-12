"""Qwen Code -> ATIF.

Source format: the ``--output-format stream-json`` event stream of Qwen Code (0.24.x),
one JSON object per line:

    system      subtype init / task_started / task_notification / retry
    assistant   one content block per event: thinking, text or tool_use (Anthropic shape)
    user        tool_result blocks, or text (a sub-agent's prompt, a harness notification)
    stream_event   UI state (goal_state); no trajectory content
    result      subtype success / error_during_execution; absent if the process was killed

Step boundary: like the Claude SDK dump, Qwen emits **one event per content block**, so an
LLM inference spans consecutive ``assistant`` events of one scope (thinking, then text,
then the tool_use event, which carries every parallel call of the inference). The last
event of an inference is the only one with non-zero ``usage`` (a corpus-wide invariant:
72,862 of 72,862 completed main-agent inferences), so an inference closes at that event,
at the next ``user`` event of the same scope, or at a ``system/retry``. A retry abandons a
partially streamed attempt; that attempt stays a step of its own, flagged
``extra.interrupted_by_retry``, because the model was called and its output was shown.
The count is cross-checked against the number of usage-bearing events
(``extra.reported_usage_events``). ``result.num_turns`` counts every non-retried inference
in runs without a background-agent notification (1,044 of 1,044), but after a notification
its counter stops following the model calls (830 of 1,555 agree), so it is recorded and
flagged (``num_turns_excludes_continuation_turns``), not trusted.

Sub-agents (``agent`` tool): events whose ``parent_tool_use_id`` is set belong to the
sub-agent launched by that call and become an embedded ``subagent_trajectories`` entry,
exactly as in ``atif.claude``. Background sub-agents stream only their prompt; their own
steps go to a separate file the corpus does not contain, and their report reaches the
model as a notification the stream shows only as ``Background agent "..." completed.``
Both gaps are recorded per sub-agent and in the root ``extra.known_gaps``. A background
agent resumed with ``send_message`` runs again under the same id; each run's notification
is kept in ``extra.runs`` (``extra.resumed`` counts the resumes) and ``reported_usage``
is their sum. An ``agent``
call that errored before launching (``Cannot use working_dir``) leaves only the prompt and
is marked ``status = "launch_failed"``.

The harness writes its stderr into the same file. ``Retrying provider attempt (...).``
lines are kept as ``extra.stderr_diagnostics``; when such a line lands inside a JSON event
that was being written at a 64 KiB pipe boundary, the event is split across two lines and
is rejoined (``extra.repaired_lines``). Any other non-JSON line is kept verbatim in
``extra.stray_lines``, so nothing in the file is dropped silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import schema

SOURCE_FORMAT = "qwen_stream_json"
AGENT_NAME = "qwen-code"
#: harness/CLI stderr lines seen in this corpus; anchored at the end so a line that was
#: spliced into a JSON event (the 64 KiB split) is recognised too
STDERR_LINE = re.compile(r"(Retrying provider attempt \(.*?\)\.|Operation cancelled\.)$")
#: how many following physical lines a split JSON event may span
MAX_JOIN = 3


def read_events(path: Path) -> Tuple[List[dict], Dict[str, list]]:
    """Return (json events, diagnostics).

    ``diagnostics`` holds ``stderr`` (recognised stderr lines, with their line number),
    ``repaired`` (events rejoined after a stderr line split them), and ``stray`` (any
    other unparseable line, verbatim). Each event gets ``__line__``.
    """
    events: List[dict] = []
    found: Dict[str, list] = {"stderr": [], "repaired": [], "stray": []}
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        lines = handle.read().split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip("\r")
        lineno = index + 1
        index += 1
        text = raw.strip()
        if not text:
            continue
        if text.startswith("{"):
            event = _loads(text)
            joined = 0
            buffer = raw
            while event is None and joined < MAX_JOIN and index + joined < len(lines):
                match = STDERR_LINE.search(buffer.rstrip())
                if not match:
                    break
                found["stderr"].append({"line": lineno + joined, "message": match.group(1),
                                        "inside_json_event": True})
                # the continuation keeps its leading whitespace: it is the middle of a string
                buffer = buffer[:match.start()] + lines[index + joined].rstrip("\r")
                joined += 1
                event = _loads(buffer.strip())
            if event is not None:
                if joined:
                    found["repaired"].append({"line": lineno, "joined_lines": joined + 1})
                    index += joined
                event["__line__"] = lineno
                events.append(event)
                continue
            # an unrepaired split leaves its stderr notes behind; they are reported once
            # below when the line is classified, so drop the speculative ones
            del found["stderr"][len(found["stderr"]) - joined:]
        match = STDERR_LINE.search(text)
        if match and match.start() == 0:
            found["stderr"].append({"line": lineno, "message": text})
        else:
            found["stray"].append({"line": lineno, "text": text})
    return events, found


def _loads(text: str) -> Optional[dict]:
    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _blocks(event: dict) -> List[dict]:
    content = (event.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _usage_reported(usage: Any) -> bool:
    """Qwen sends ``{"input_tokens": 0, "output_tokens": 0}`` on every block event but the
    last one of an inference."""
    return isinstance(usage, dict) and bool((usage.get("input_tokens") or 0)
                                            or (usage.get("output_tokens") or 0))


def _step_metrics(usage: dict) -> dict:
    # Qwen's input_tokens already include the cache hits (total = input + output), which
    # is exactly ATIF's prompt_tokens; cache_read_input_tokens is the cached subset
    return {"prompt_tokens": usage.get("input_tokens") or 0,
            "completion_tokens": usage.get("output_tokens") or 0,
            "cached_tokens": usage.get("cache_read_input_tokens") or 0}


def _sum_usage(usages) -> dict:
    """Add up the ``usage`` dicts of a background agent's runs, key by key. Each
    task_notification reports its own run only (a resumed run restarts at 0 tool uses),
    so the sum is the sub-agent's whole cost; one run passes through unchanged."""
    total: Dict[str, Any] = {}
    for usage in usages:
        for key, value in (usage or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
    return total


def sidecar_path(path: Path) -> Path:
    """``bug-18.log`` -> ``bug-18.meta.json`` (written by the harness, not by Qwen)."""
    path = Path(path)
    return path.with_name(path.stem + ".meta.json")


def parse(path: Path, *, extra: Optional[dict] = None) -> dict:
    path = Path(path)
    events, found = read_events(path)

    init = next((e for e in events
                 if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result_event = next((e for e in reversed(events) if e.get("type") == "result"), {})
    model = init.get("model") or ""
    version = str(init.get("qwen_code_version") or "")

    # tool_use_id -> (text, is_error, images)
    results: Dict[str, Tuple[str, bool, int]] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        for block in _blocks(event):
            if block.get("type") == "tool_result":
                text, images = schema.render_content(block.get("content"))
                results[block.get("tool_use_id", "")] = (text, bool(block.get("is_error")),
                                                        images)
    denied = {str(d["tool_use_id"]) for d in result_event.get("permission_denials") or []
              if isinstance(d, dict) and d.get("tool_use_id")}

    # background-task bookkeeping, keyed by the delegating tool_use_id. ``send_message``
    # resumes a background agent under the same id: each resume emits another task_started
    # and, when that run ends, another task_notification carrying that run's own usage
    # (79 sub-agents in 67 logs), so notifications are kept one per run, never merged
    tasks: Dict[str, dict] = {}
    for event in events:
        if event.get("type") == "system" and event.get("subtype") in (
                "task_started", "task_notification"):
            data = event.get("data") or {}
            task = tasks.setdefault(str(data.get("tool_use_id") or ""),
                                    {"launches": 0, "runs": []})
            for key in ("task_id", "description", "subagent_type"):
                if data.get(key) is not None:
                    task[key] = data[key]
            if event.get("subtype") == "task_started":
                task["launches"] += 1
                continue
            run: Dict[str, Any] = {"status": data.get("status") or "",
                                   "line": event["__line__"]}
            if isinstance(data.get("usage"), dict):
                run["usage"] = data["usage"]
            task["runs"].append(run)

    # scopes: None = main agent, otherwise the tool_use_id of the delegating agent call
    scopes: Dict[Optional[str], List[dict]] = {}
    for event in events:
        if event.get("type") in ("assistant", "user") or (
                event.get("type") == "system" and event.get("subtype") == "retry"):
            scopes.setdefault(event.get("parent_tool_use_id"), []).append(event)

    unknown_blocks: Dict[str, int] = {}
    counters = {"usage_events": 0, "retries": 0}

    def build(sequence: List[dict], main: bool) -> List[dict]:
        steps: List[dict] = []
        current: Optional[dict] = None
        for event in sequence:
            kind = event.get("type")
            if kind == "system":                       # retry: the open attempt is abandoned
                counters["retries"] += 1
                if current is not None:
                    current["extra"]["interrupted_by_retry"] = event.get("data") or {}
                current = None
                continue
            blocks = _blocks(event)
            if kind == "user":
                current = None  # tool results close the inference that issued them
                text = "\n".join(b.get("text", "") for b in blocks
                                 if b.get("type") == "text").strip()
                if text:
                    step = schema.message_step(len(steps) + 1, "user", text)
                    # the -p prompt is never echoed, so a user text is either a sub-agent's
                    # prompt or a notification the CLI injected into the main conversation
                    step["extra"] = {"record_kind": "harness_notification" if main
                                     else "delegated_prompt"}
                    steps.append(step)
                continue
            message = event.get("message") or {}
            if current is None:
                current = schema.agent_step(len(steps) + 1, model_name=message.get("model") or "")
                current["extra"] = {"source_lines": []}
                steps.append(current)
            current["extra"]["source_lines"].append(event["__line__"])
            for block in blocks:
                block_type = block.get("type")
                if block_type == "thinking":
                    current["reasoning_content"] = "\n".join(
                        t for t in (current.get("reasoning_content"), block.get("thinking"))
                        if t)
                elif block_type == "text":
                    current["message"] = (current["message"] + "\n"
                                          + (block.get("text") or "")).strip()
                elif block_type == "tool_use":
                    schema.add_tool_call(current, block.get("id", ""), block.get("name", ""),
                                         block.get("input") or {})
                else:
                    # never drop a block type silently
                    unknown_blocks[str(block_type)] = unknown_blocks.get(str(block_type), 0) + 1
                    current["extra"].setdefault("unparsed_blocks", []).append(
                        json.dumps(block, default=str))
            if _usage_reported(message.get("usage")):
                counters["usage_events"] += int(main)
                current["metrics"] = _step_metrics(message["usage"])
                if message.get("stop_reason"):
                    current["extra"]["stop_reason"] = message["stop_reason"]
                current = None                          # the usage event ends the inference
        for step in steps:
            if step["source"] != "agent":
                continue
            for call in step.get("tool_calls") or []:
                found_result = results.get(call["tool_call_id"])
                if found_result is not None:
                    schema.add_observation(
                        step, call["tool_call_id"], found_result[0], is_error=found_result[1],
                        images=found_result[2] or None,
                        permission_denied=True if call["tool_call_id"] in denied else None)
            schema.finalize(step)
        return steps

    steps_by_scope: Dict[Optional[str], List[dict]] = {
        scope: schema.placeholder_steps(
            build(sequence, scope is None),
            "no conversation events in the log" if scope is None
            else "no event of this subagent was streamed")
        for scope, sequence in scopes.items()}
    steps_by_scope.setdefault(None, schema.placeholder_steps(
        [], "no conversation events in the log"))

    # which scope issued each tool call, so nested delegation embeds at the right level
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
            # a sub-agent whose delegating call is missing hangs off the main agent
            children.setdefault(owner.get(scope), []).append(scope)

    session_id = init.get("session_id") or result_event.get("session_id")
    gaps_seen: Dict[str, bool] = {}

    def embed(scope: Optional[str]) -> List[dict]:
        """Envelopes for the sub-agents launched from ``scope``, linked to their calls."""
        subagents: List[dict] = []
        for child in children.get(scope, []):
            sub_steps = steps_by_scope[child]
            trajectory_id = "sub-" + str(child)
            task = tasks.get(child, {})
            runs = task.get("runs") or []
            arguments = call_args.get(child, {})
            streamed = any(s["source"] == "agent" for s in sub_steps)
            sub_extra: Dict[str, Any] = {
                "scope": "subagent", "delegating_tool_call_id": child,
                "source_format": SOURCE_FORMAT,
                "subagent_type": task.get("subagent_type") or arguments.get("subagent_type", ""),
                "description": task.get("description") or arguments.get("description", ""),
                # only background launches emit system/task_started
                "background": bool(task),
                # the last run's status is the sub-agent's final state
                "status": runs[-1]["status"] if runs else "",
                # the cost of all its runs together; ``runs`` keeps each one
                "reported_usage": _sum_usage(r.get("usage") for r in runs),
                "internals_streamed": streamed,
            }
            if task:
                # a run killed with the process leaves a launch without a notification
                sub_extra["resumed"] = max(task["launches"] - 1, 0)
                sub_extra["runs"] = runs
            # an agent call that errored (e.g. "Cannot use working_dir") never started one:
            # its prompt is all there is, and nothing is missing
            launch_failed = not task and not streamed and results.get(child, ("", False))[1]
            if launch_failed:
                sub_extra["status"] = "launch_failed"
            sub_gaps = []
            if not streamed and not launch_failed:
                sub_gaps.append("subagent_internals_not_streamed")
            if task:
                sub_gaps.append("subagent_result_not_streamed")
            for gap in sub_gaps:
                gaps_seen[gap] = True
            sub_extra["known_gaps"] = sub_gaps
            subagents.append(schema.envelope(
                session_id=session_id, agent_name=AGENT_NAME, agent_version=version,
                model_name=model, steps=sub_steps, trajectory_id=trajectory_id,
                subagents=embed(child),
                final_metrics={"total_steps": len(sub_steps)}, extra=sub_extra))
            for step in steps_by_scope.get(scope, []):
                if any(c["tool_call_id"] == child for c in step.get("tool_calls") or []):
                    schema.attach_subagent_ref(step, child, trajectory_id)
        return subagents

    main_steps = steps_by_scope[None]
    subagents = embed(None)

    # calls without any result (the process died mid-call) are listed, never invented
    unanswered = [call["tool_call_id"]
                  for steps in steps_by_scope.values() for step in steps
                  for call in step.get("tool_calls") or [] if call["tool_call_id"] not in results]

    system_counts: Dict[str, int] = {}
    for event in events:
        if event.get("type") in ("system", "stream_event"):
            key = (str(event.get("subtype")) if event.get("type") == "system"
                   else "stream:" + str((event.get("event") or {}).get("type")))
            system_counts[key] = system_counts.get(key, 0) + 1

    usage = result_event.get("usage") or {}
    if result_event:
        final = {"total_prompt_tokens": usage.get("input_tokens") or 0,
                 "total_completion_tokens": usage.get("output_tokens") or 0,
                 "total_cached_tokens": usage.get("cache_read_input_tokens") or 0}
    else:
        # no result event: sum what the streamed inferences reported themselves
        streamed = [s.get("metrics") or {} for steps in steps_by_scope.values() for s in steps]
        final = {"total_prompt_tokens": sum(m.get("prompt_tokens", 0) for m in streamed),
                 "total_completion_tokens": sum(m.get("completion_tokens", 0) for m in streamed),
                 "total_cached_tokens": sum(m.get("cached_tokens", 0) for m in streamed)}
    final["total_steps"] = len(main_steps)

    agent_turns = sum(1 for s in main_steps if s["source"] == "agent")
    notifications = sum(1 for s in main_steps if s["source"] == "user")
    known_gaps = ["no_per_step_timestamps", "no_initial_user_prompt"]
    if not result_event:
        known_gaps.append("no_result_event")
    known_gaps.extend(sorted(gaps_seen))
    if notifications:
        known_gaps.append("num_turns_excludes_continuation_turns")
    if found["stderr"] or found["stray"]:
        known_gaps.append("stderr_interleaved")
    if unanswered:
        known_gaps.append("tool_calls_without_result")

    trajectory_extra: Dict[str, Any] = {
        "source_format": SOURCE_FORMAT,
        "source_file": path.name,
        "parser_version": schema.PARSER_VERSION,
        "cwd": init.get("cwd", ""),
        "permission_mode": init.get("permission_mode", ""),
        "outcome": result_event.get("subtype") or "missing",
        "is_error": result_event.get("is_error"),
        "error": ((result_event.get("error") or {}).get("message")
                  if isinstance(result_event.get("error"), dict) else result_event.get("error")),
        "duration_ms": result_event.get("duration_ms"),
        "duration_api_ms": result_event.get("duration_api_ms"),
        "reported_num_turns": result_event.get("num_turns"),
        "parsed_agent_turns": agent_turns,
        "reported_usage_events": counters["usage_events"],
        "provider_retries": counters["retries"],
        "harness_notifications": notifications,
        "system_event_counts": system_counts,
        "final_message": schema.truncate(result_event.get("result"), 4000)[0],
        "known_gaps": known_gaps,
    }
    if denied:
        trajectory_extra["permission_denials"] = sorted(denied)
    if unanswered:
        trajectory_extra["unanswered_tool_calls"] = unanswered
    if found["stderr"]:
        trajectory_extra["stderr_diagnostics"] = found["stderr"]
    if found["repaired"]:
        trajectory_extra["repaired_lines"] = found["repaired"]
    if found["stray"]:
        trajectory_extra["stray_lines"] = found["stray"]
    if unknown_blocks:
        trajectory_extra["unparsed_block_types"] = unknown_blocks
    meta_path = sidecar_path(path)
    if meta_path.is_file():
        try:
            trajectory_extra["harness_meta"] = json.loads(
                meta_path.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            trajectory_extra["harness_meta_error"] = f"{meta_path.name} is not valid JSON"
    if extra:
        trajectory_extra.update(extra)

    return schema.envelope(
        session_id=session_id,
        agent_name=AGENT_NAME,
        agent_version=version,
        model_name=model,
        steps=main_steps,
        subagents=subagents,
        final_metrics=final,
        extra=trajectory_extra,
        tool_definitions=[{"type": "function", "function": {"name": name}}
                          for name in init.get("tools") or []],
    )
