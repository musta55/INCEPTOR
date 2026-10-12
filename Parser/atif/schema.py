"""ATIF v1.7 envelope construction, truncation policy, and a dependency-free validator.

Reference: Parser/ATIF-v1.7-RFC.md (harbor-framework RFC 0001).
Everything our project needs beyond the standard lives in `extra` objects, so the
output stays valid against Harbor's official validator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "ATIF-v1.7"
PARSER_VERSION = "1.2.0"

#: Tool output above this many characters is truncated in the ATIF file. The full
#: length is always recorded in the observation's `extra.original_chars`, and the
#: untruncated text is always recoverable from the raw log by `tool_call_id`
#: (`trajparse output <bug> <agent> <call_id>`), so nothing is lost, only moved.
#:
#: The default keeps 96% of this corpus's tool results complete; the 4% that are not
#: are multi-megabyte Gradle/emulator logs (the largest single result is 24M chars).
#: The CLI overrides this with --max-output / --full.
OUTPUT_LIMIT = 200_000

SOURCES = ("system", "user", "agent")


def truncate(value: Any, limit: Optional[int] = None) -> "tuple[str, int]":
    """Return (possibly truncated text, original length in characters).

    ``limit`` defaults to the module's ``OUTPUT_LIMIT`` *at call time*, so a caller that
    changes ``schema.OUTPUT_LIMIT`` (the CLI's --max-output, the truncation tests) changes
    every parser's cap."""
    if limit is None:
        limit = OUTPUT_LIMIT
    if value is None:
        return "", 0
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return text, len(text)
    keep_tail = 1000
    head = text[: limit - keep_tail]
    tail = text[-keep_tail:]
    return f"{head}\n...[truncated {len(text) - limit} chars]...\n{tail}", len(text)


def envelope(
    *,
    session_id: Optional[str],
    agent_name: str,
    agent_version: str,
    model_name: str,
    steps: List[dict],
    final_metrics: Optional[dict] = None,
    extra: Optional[dict] = None,
    trajectory_id: str = "",
    subagents: Optional[List[dict]] = None,
    tool_definitions: Optional[List[dict]] = None,
) -> dict:
    traj: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "agent": {
            "name": agent_name,
            "version": agent_version or "unknown",
            "model_name": model_name or "",
        },
        "steps": steps,
    }
    if session_id:
        traj["session_id"] = session_id
    if trajectory_id:
        traj["trajectory_id"] = trajectory_id
    if tool_definitions:
        traj["agent"]["tool_definitions"] = tool_definitions
    if final_metrics:
        traj["final_metrics"] = final_metrics
    if subagents:
        traj["subagent_trajectories"] = subagents
    if extra:
        traj["extra"] = extra
    return traj


def agent_step(step_id: int, *, timestamp: str = "", model_name: str = "") -> dict:
    """A fresh agent step representing exactly one LLM inference."""
    step: Dict[str, Any] = {"step_id": step_id, "source": "agent", "message": "",
                            "llm_call_count": 1}
    if timestamp:
        step["timestamp"] = timestamp
    if model_name:
        step["model_name"] = model_name
    return step


def message_step(step_id: int, source: str, message: str, timestamp: str = "") -> dict:
    step: Dict[str, Any] = {"step_id": step_id, "source": source, "message": message}
    if timestamp:
        step["timestamp"] = timestamp
    return step


def add_tool_call(step: dict, call_id: str, name: str, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        arguments = {"raw": arguments}
    step.setdefault("tool_calls", []).append(
        {"tool_call_id": call_id, "function_name": name, "arguments": arguments}
    )


def add_observation(step: dict, call_id: str, content: Any, **extra: Any) -> None:
    text, original = truncate(content)
    result: Dict[str, Any] = {"source_call_id": call_id, "content": text}
    meta = {k: v for k, v in extra.items() if v is not None}
    if original > len(text):
        meta["original_chars"] = original
        meta["truncated"] = True
    if meta:
        result["extra"] = meta
    step.setdefault("observation", {"results": []})["results"].append(result)


def attach_subagent_ref(step: dict, call_id: str, trajectory_id: str) -> None:
    """Link a delegating tool call to its embedded subagent trajectory.

    The ref goes on the call's existing observation result, beside the tool's own output
    (the RFC allows ``content`` next to ``subagent_trajectory_ref``), so a reader that
    indexes results by ``source_call_id`` sees both; without a result it gets its own."""
    ref = {"trajectory_id": trajectory_id}
    results = step.setdefault("observation", {"results": []})["results"]
    for result in results:
        if result.get("source_call_id") == call_id:
            result.setdefault("subagent_trajectory_ref", []).append(ref)
            return
    results.append({"source_call_id": call_id, "subagent_trajectory_ref": [ref]})


def render_content(value: Any) -> "tuple[str, int]":
    """Tool output as text, plus the number of images it carried.

    Tool results may be a list of content parts (Anthropic ``text`` / ``image`` /
    ``tool_reference``, OpenAI ``input_text`` / ``input_image``). Text parts are kept
    verbatim; an image's base64 payload is replaced by a placeholder naming its media type
    and size, because it is opaque binary and would otherwise fill the truncation budget
    with noise. Unknown parts are kept as JSON, never dropped."""
    if value is None:
        return "", 0
    if isinstance(value, str):
        return value, 0
    parts = value if isinstance(value, list) else [value]
    texts: List[str] = []
    images = 0
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, dict):
            texts.append(str(part))
            continue
        kind = part.get("type") or part.get("__type__") or ""
        if kind in ("image", "input_image"):
            images += 1
            source = part.get("source") if isinstance(part.get("source"), dict) else {}
            url = str(part.get("image_url") or "")
            media = source.get("media_type") or (url[5:].split(";", 1)[0]
                                                 if url.startswith("data:") else "image")
            size = len(str(source.get("data") or url.split(",", 1)[-1]))
            texts.append(f"[image: {media}, {size:,} base64 chars omitted]")
        elif kind == "tool_reference":
            texts.append(f"[tool_reference: {part.get('tool_name', '')}]")
        elif "text" in part:
            texts.append(str(part.get("text") or ""))
        else:
            texts.append(json.dumps(part, default=str))
    return "\n".join(t for t in texts if t), images


def placeholder_steps(steps: List[dict], what: str) -> List[dict]:
    """ATIF requires at least one step. A trajectory whose log holds nothing for it (a
    subagent that streamed no event, a log cut down to its ResultMessage) gets one system
    step saying so, tagged ``extra.record_kind = "placeholder"``, instead of an invalid file."""
    if steps:
        return steps
    step = message_step(1, "system", f"[{what}]")
    step["extra"] = {"record_kind": "placeholder"}
    return [step]


def finalize(step: dict) -> dict:
    """Drop empty scaffolding so the file stays readable."""
    if not step.get("reasoning_content"):
        step.pop("reasoning_content", None)
    if not step.get("tool_calls"):
        step.pop("tool_calls", None)
    if isinstance(step.get("message"), str):
        step["message"] = step["message"].strip()
    return step


# --------------------------------------------------------------------------- #
# validation


def validate(traj: dict, path: str = "<trajectory>") -> List[str]:
    """Structural validation of an ATIF trajectory. Returns a list of errors.

    Dependency-free, so it runs anywhere. Harbor's official validator is the
    authority on the schema itself; run it with `trajparse validate --harbor`.
    """
    errors: List[str] = []

    def err(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    if traj.get("schema_version") != SCHEMA_VERSION:
        err(f"schema_version is {traj.get('schema_version')!r}, expected {SCHEMA_VERSION!r}")
    agent = traj.get("agent")
    if not isinstance(agent, dict):
        err("missing agent object")
    else:
        for field in ("name", "version"):
            if not agent.get(field):
                err(f"agent.{field} is required")

    steps = traj.get("steps")
    if not isinstance(steps, list):
        err("steps must be a list")
        return errors
    if not steps:
        err("steps must not be empty")

    declared_calls = set()
    for index, step in enumerate(steps):
        step_calls = {call.get("tool_call_id") for call in step.get("tool_calls") or []}
        expected = index + 1
        if step.get("step_id") != expected:
            err(f"step {index}: step_id is {step.get('step_id')!r}, expected {expected}")
        if step.get("source") not in SOURCES:
            err(f"step {expected}: source {step.get('source')!r} not in {SOURCES}")
        if "message" not in step:
            err(f"step {expected}: message is required (may be empty)")
        if step.get("source") != "agent":
            for field in ("reasoning_content", "tool_calls", "metrics", "model_name"):
                if field in step:
                    err(f"step {expected}: {field} is only valid on agent steps")
        for call in step.get("tool_calls") or []:
            for field in ("tool_call_id", "function_name", "arguments"):
                if field not in call:
                    err(f"step {expected}: tool_call missing {field}")
            if not isinstance(call.get("arguments"), dict):
                err(f"step {expected}: tool_call arguments must be an object")
            call_id = call.get("tool_call_id")
            if call_id in declared_calls:
                err(f"step {expected}: duplicate tool_call_id {call_id!r}")
            declared_calls.add(call_id)
        results = (step.get("observation") or {}).get("results")
        if step.get("observation") is not None and not isinstance(results, list):
            err(f"step {expected}: observation.results must be a list")
        for result in results or []:
            ref = result.get("source_call_id")
            if ref is not None and ref not in declared_calls:
                err(f"step {expected}: observation references unknown call {ref!r}")
            elif ref is not None and ref not in step_calls:
                # Harbor's validator requires the call to be declared in the same step
                err(f"step {expected}: observation references call {ref!r} of another step")
            if "content" not in result and "subagent_trajectory_ref" not in result:
                err(f"step {expected}: observation result needs content or a subagent ref")

    embedded_ids = [sub.get("trajectory_id") for sub in traj.get("subagent_trajectories") or []]
    embedded = set(embedded_ids)
    if None in embedded or "" in embedded:
        err("every embedded subagent trajectory must set trajectory_id")
    if len(embedded) != len(embedded_ids):
        err("embedded subagent trajectory_ids must be unique")
    for step in steps:
        for result in (step.get("observation") or {}).get("results") or []:
            for ref in result.get("subagent_trajectory_ref") or []:
                if not ref.get("trajectory_id") and not ref.get("trajectory_path"):
                    err(f"step {step.get('step_id')}: subagent ref needs an id or a path")
                elif ref.get("trajectory_id") and ref["trajectory_id"] not in embedded:
                    err(f"step {step.get('step_id')}: unresolvable subagent ref "
                        f"{ref['trajectory_id']!r}")
    for sub in traj.get("subagent_trajectories") or []:
        errors.extend(validate(sub, f"{path}#{sub.get('trajectory_id')}"))
    return errors


def write(traj: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(traj, indent=1, default=str) + "\n", encoding="utf-8")
    return path
