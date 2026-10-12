"""Measure how much of a raw log survives into its ATIF conversion.

Answers the only question that matters about a parser: *did it drop anything?*
For every text-bearing record in the raw log it asks whether that text can be found
in the converted trajectory, and reports the result per record type.

    python3 -m atif.cli audit 8

Deliberately independent of the parsers: the inventories below re-read the raw files
with their own code, so a parser bug cannot hide itself from the audit. They share only
the line readers (``claude.read_messages``, ``codex.read_events``, ``qwen.read_events``),
which decode lines and report what they could not decode; deciding which records carry
text, and extracting it, is done here.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

from . import claude, codex, detect, qwen

PROBE = 100          # characters of a block used to look it up in the converted file


def _norm(text: Any) -> str:
    return " ".join(str(text).split())


def _block(record_type: str, field: str, text: Any, *, call_id: str = "") -> Dict[str, Any]:
    return {"record_type": record_type, "field": field, "text": str(text or ""),
            "chars": len(str(text or "")), "call_id": call_id, "values": None}


def _leaves(node: Any) -> List[str]:
    """Scalar leaves of a nested value, as text (dict keys are structure, not content)."""
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in _leaves(value)]
    if isinstance(node, list):
        return [leaf for value in node for leaf in _leaves(value)]
    return [] if node is None else [str(node)]


def _args_block(record_type: str, arguments: Any, *, call_id: str = "") -> Dict[str, Any]:
    """Tool arguments are stored as a parsed object in ATIF, so comparing the raw
    JSON *text* would report a false miss. Compare the argument values instead -- every
    scalar leaf, so a nested argument (Codex's ``update_plan`` steps) is checked too."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = {"raw": arguments}
    if not isinstance(arguments, dict):
        arguments = {"raw": arguments}
    values = [v for v in _leaves(arguments) if v.strip()]
    text = json.dumps(arguments, default=str)
    return {"record_type": record_type, "field": "arguments", "text": text,
            "chars": len(text), "call_id": call_id, "values": values}


def _parts_text(content: Any) -> str:
    """The text-bearing parts of a tool result: strings, ``text`` parts, the name in a
    ``tool_reference``. Image parts carry base64 only and are not text (EXPECTED_DROPS)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    texts: List[str] = []
    for part in content if isinstance(content, list) else [content]:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict):
            kind = part.get("type") or part.get("__type__")
            if kind in ("image", "input_image"):
                continue
            if kind == "tool_reference":
                texts.append(str(part.get("tool_name") or ""))
            elif "text" in part:
                texts.append(str(part.get("text") or ""))
            else:
                texts.append(json.dumps(part, default=str))
    return "\n".join(t for t in texts if t)


def _text_bearing(blocks: List[dict]) -> List[dict]:
    """Drop blocks with nothing to look for: empty or whitespace-only text (Qwen streams
    ``"\\n\\n"`` text blocks between thinking and a tool call)."""
    return [b for b in blocks if _norm(b["text"])]


# --------------------------------------------------------------------------- #
# raw-log inventories, one per format


def inventory_codex(path: Path) -> List[dict]:
    blocks: List[dict] = []
    for event in codex.read_events(path):
        payload = event.get("payload") or {}
        kind, subtype = event.get("type"), payload.get("type")
        if kind == "session_meta":
            blocks.append(_block("session_meta", "base_instructions",
                                 codex.p_base_instructions(payload)))
        elif kind == "turn_context":
            blocks.append(_block("turn_context", "user_instructions",
                                 payload.get("user_instructions")))
        elif kind == "response_item" and subtype == "message":
            text = "\n".join(part.get("text", "") for part in (payload.get("content") or [])
                             if isinstance(part, dict))
            blocks.append(_block(f"message[{payload.get('role')}]", "content", text))
        elif kind == "response_item" and subtype in codex.CALL_TYPES:
            blocks.append(_args_block(subtype,
                                      payload.get("arguments") or payload.get("input"),
                                      call_id=payload.get("call_id", "")))
            blocks.append(_block(f"{subtype}.name", "name", payload.get("name")))
        elif kind == "response_item" and subtype in codex.OUTPUT_TYPES:
            blocks.append(_block("function_call_output", "output",
                                 _parts_text(payload.get("output")),
                                 call_id=payload.get("call_id", "")))
        elif kind == "event_msg" and subtype == "patch_apply_end":
            blocks.append(_args_block("patch_apply_end",
                                      {"files": sorted(payload.get("changes") or {})},
                                      call_id=payload.get("call_id", "")))
        elif kind == "event_msg" and subtype in ("agent_message", "user_message"):
            blocks.append(_block(subtype, "message", payload.get("message")))
        elif kind == "response_item" and subtype == "reasoning":
            text = codex._reasoning_text(payload)
            if text:
                blocks.append(_block("reasoning", "summary", text))
    return _text_bearing(blocks)


def inventory_claude(path: Path) -> List[dict]:
    blocks: List[dict] = []
    damaged: List[dict] = []
    for message in claude.read_messages(path, damaged):
        kind = message["__type__"]
        if kind == "ResultMessage":
            blocks.append(_block("ResultMessage", "result", message.get("result")))
            continue
        if kind in ("TaskStartedMessage", "TaskNotificationMessage"):
            data = message.get("data") if isinstance(message.get("data"), dict) else {}
            field = "description" if kind == "TaskStartedMessage" else "summary"
            blocks.append(_block(kind, field, data.get(field) or message.get(field)))
            continue
        if kind not in ("AssistantMessage", "UserMessage"):
            continue                       # system / progress metadata; counted in extra
        content = message.get("content")
        if isinstance(content, str):
            content = [{"__type__": "TextBlock", "text": content}]
        for part in content or []:
            if not isinstance(part, dict):
                continue
            block_type = part["__type__"]
            if block_type == "TextBlock":
                blocks.append(_block(block_type, "text", part.get("text")))
            elif block_type == "ThinkingBlock":
                blocks.append(_block(block_type, "thinking", part.get("thinking")))
            elif block_type == "ToolUseBlock":
                blocks.append(_args_block(block_type, part.get("input") or {},
                                          call_id=part.get("id", "")))
                blocks.append(_block("ToolUseBlock.name", "name", part.get("name")))
            elif block_type == "ToolResultBlock":
                blocks.append(_block(block_type, "content", _parts_text(part.get("content")),
                                     call_id=part.get("tool_use_id", "")))
            else:
                blocks.append(_block(block_type, "?", json.dumps(part, default=str)))
    for entry in damaged:
        if entry["kind"] == "unparsed":
            blocks.append(_block("unparsed_line", "preview", entry.get("preview")))
    return _text_bearing(blocks)


def inventory_qwen(path: Path) -> List[dict]:
    events, found = qwen.read_events(path)
    blocks: List[dict] = []
    for event in events:
        kind = event.get("type")
        if kind in ("assistant", "user"):
            content = (event.get("message") or {}).get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for part in content or []:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text":
                    blocks.append(_block(f"{kind}.text", "text", part.get("text")))
                elif part_type == "thinking":
                    blocks.append(_block("thinking", "thinking", part.get("thinking")))
                elif part_type == "tool_use":
                    blocks.append(_args_block("tool_use", part.get("input") or {},
                                              call_id=part.get("id", "")))
                    blocks.append(_block("tool_use.name", "name", part.get("name")))
                elif part_type == "tool_result":
                    blocks.append(_block("tool_result", "content",
                                         _parts_text(part.get("content")),
                                         call_id=part.get("tool_use_id", "")))
                else:
                    blocks.append(_block(str(part_type), "?", json.dumps(part, default=str)))
        elif kind == "result":
            blocks.append(_block("result", "result", event.get("result")))
            error = event.get("error")
            blocks.append(_block("result.error", "message",
                                 error.get("message") if isinstance(error, dict) else error))
        elif kind == "system" and event.get("subtype") == "task_started":
            blocks.append(_block("task_started", "description",
                                 (event.get("data") or {}).get("description")))
    for entry in found["stderr"]:
        blocks.append(_block("stderr_diagnostic", "message", entry.get("message")))
    for entry in found["stray"]:
        blocks.append(_block("stray_line", "text", entry.get("text")))
    return _text_bearing(blocks)


INVENTORIES = {
    codex.SOURCE_FORMAT: inventory_codex,
    claude.SOURCE_FORMAT: inventory_claude,
    qwen.SOURCE_FORMAT: inventory_qwen,
}

#: Raw content we deliberately do not carry into ATIF, with the reason.
EXPECTED_DROPS = {
    "reasoning.encrypted_content": "opaque ciphertext; presence recorded as "
                                   "extra.reasoning_encrypted",
    "image parts of tool results": "base64 payload; a placeholder names the media type and "
                                   "size, and the observation's extra.images counts them",
    "UserMessage.tool_use_result": "the Claude SDK's structured copy of the ToolResultBlock "
                                   "(stdout/stderr split, Edit's originalFile and patch); "
                                   "only the Agent tool's report (type, model, tokens) is kept, "
                                   "on the subagent trajectory",
    "SystemMessage(thinking_tokens) / TaskProgressMessage": "per-chunk progress estimates; "
                                   "counted in extra.system_event_counts",
    "qwen stream_event": "UI state (goal_state); counted in extra.system_event_counts",
    "codex response_item.message[assistant]": "the same text as its event_msg/agent_message",
}


def converted_strings(trajectory: dict) -> List[str]:
    """Every scalar value in the converted document, normalised to text.

    Numbers and booleans are included: tool arguments legitimately contain them
    (``{"timeout": 600000, "replace_all": false}``), and a strings-only haystack
    would report those arguments as lost when they are present.
    """
    out: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif node is not None:
            out.append(_norm(node))
    walk(trajectory)
    return out


def audit(raw_path: Path, trajectory: dict) -> dict:
    """Compare a raw log against its converted trajectory, block by block."""
    fmt = detect.detect(raw_path)
    if fmt is None:
        raise ValueError(f"{raw_path}: unrecognised format")
    blocks = INVENTORIES[fmt](Path(raw_path))
    haystack = "\n".join(converted_strings(trajectory))

    stored_by_call: Dict[str, int] = {}

    def collect(node: dict) -> None:
        for step in node.get("steps", []):
            for result in (step.get("observation") or {}).get("results", []):
                call_id = (result.get("source_call_id")
                           or (result.get("extra") or {}).get("orphan_call_id"))
                if call_id and "content" in result:
                    stored_by_call[call_id] = len(result.get("content") or "")
        for sub in node.get("subagent_trajectories") or []:
            collect(sub)
    collect(trajectory)

    per_type: Dict[str, Dict[str, Any]] = {}
    missing: List[dict] = []
    for block in blocks:
        normalised = _norm(block["text"])
        if block["values"] is not None:          # argument objects: check every value
            found = all(_norm(v)[:PROBE] in haystack for v in block["values"]) \
                if block["values"] else True
        else:
            probe = normalised[:min(PROBE, len(normalised))]
            found = bool(probe) and probe in haystack
        # only tool results are subject to truncation, so only they get a stored length
        stored = (stored_by_call.get(block["call_id"])
                  if block["call_id"] and block["field"] in ("output", "content") else None)
        row = per_type.setdefault(block["record_type"],
                                  {"blocks": 0, "found": 0, "raw_chars": 0,
                                   "stored_chars": 0, "truncated": 0})
        row["blocks"] += 1
        row["raw_chars"] += block["chars"]
        row["found"] += int(found)
        if stored is not None:
            row["stored_chars"] += stored
            row["truncated"] += int(stored < block["chars"])
        else:
            row["stored_chars"] += block["chars"] if found else 0
        if not found:
            missing.append({"record_type": block["record_type"], "field": block["field"],
                            "chars": block["chars"], "preview": normalised[:120]})
    totals = {
        "blocks": sum(r["blocks"] for r in per_type.values()),
        "found": sum(r["found"] for r in per_type.values()),
        "raw_chars": sum(r["raw_chars"] for r in per_type.values()),
        "stored_chars": sum(r["stored_chars"] for r in per_type.values()),
        "truncated": sum(r["truncated"] for r in per_type.values()),
    }
    return {"format": fmt, "per_type": per_type, "missing": missing, "totals": totals}


def render(report: dict, title: str) -> str:
    lines = [f"=== {title}  ({report['format']})"]
    lines.append(f"  {'record type':24} {'blocks':>7} {'found':>7} {'raw chars':>12} "
                 f"{'kept':>12} {'trunc':>6}")
    for name, row in sorted(report["per_type"].items(), key=lambda kv: -kv[1]["raw_chars"]):
        flag = "" if row["found"] == row["blocks"] else "  <-- MISSING"
        lines.append(f"  {name:24} {row['blocks']:7} {row['found']:7} {row['raw_chars']:12,} "
                     f"{row['stored_chars']:12,} {row['truncated']:6}{flag}")
    totals = report["totals"]
    kept = 100 * totals["stored_chars"] / totals["raw_chars"] if totals["raw_chars"] else 100
    lines.append(f"  {'TOTAL':24} {totals['blocks']:7} {totals['found']:7} "
                 f"{totals['raw_chars']:12,} {totals['stored_chars']:12,} {totals['truncated']:6}")
    lines.append(f"  blocks preserved: {totals['found']}/{totals['blocks']}"
                 f"  |  text kept: {kept:.1f}%"
                 f"  |  results truncated: {totals['truncated']}"
                 " (full text recoverable from the raw log by call_id)")
    if report["missing"]:
        lines.append("  MISSING blocks:")
        for entry in report["missing"][:10]:
            lines.append(f"    - {entry['record_type']}.{entry['field']} "
                         f"({entry['chars']:,} chars): {entry['preview'][:90]}")
    return "\n".join(lines)
