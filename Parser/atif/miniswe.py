"""mini-swe-agent -> ATIF.

Source format: the ``<instance>.traj.json`` that mini-swe-agent writes (and live-SWE-agent,
which is built on it), one JSON object:

    trajectory_format   ``mini-swe-agent-1``
    info                ``exit_status``, ``submission`` (the diff), ``model_stats``,
                        ``mini_version``, ``config``
    messages            system, the task (user), then alternating assistant turns and the
                        environment's replies (user)

mini-swe-agent has one tool, the shell: each assistant turn holds exactly one fenced
``bash`` block (its ``action_regex``, by default ``` ```bash\s*\n(.*?)\n``` ```; other fenced
blocks are explanation), and the next user message is its output, ``<returncode>N</returncode>
<output>...</output>`` (the verdict parser reads the return code).  A turn whose block is
missing or doubled gets a format-error reply and no command; it is kept as a step without a
call.  An assistant message with OpenAI ``tool_calls`` (later versions) is read from those.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from . import project, swebench

SOURCE_FORMAT = "mini_swe_agent"
AGENT_NAME = "mini-swe-agent"

#: mini-swe-agent's default ``action_regex``; a run's config may give its own
ACTION_REGEX = r"```bash\s*\n(.*?)\n```"


def _action_pattern(info: dict) -> "re.Pattern[str]":
    config = info.get("config") if isinstance(info.get("config"), dict) else {}
    given = (config.get("agent") or {}).get("action_regex") if isinstance(
        config.get("agent"), dict) else None
    try:
        return re.compile(given if isinstance(given, str) and given else ACTION_REGEX, re.S)
    except re.error:
        return re.compile(ACTION_REGEX, re.S)


def is_mini(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("messages"), list) and (
        str(obj.get("trajectory_format") or "").startswith("mini-swe-agent")
        or bool((obj.get("info") or {}).get("mini_version")))


def _model(obj: dict) -> str:
    for message in obj.get("messages") or []:
        response = ((message.get("extra") or {}).get("response") or {}) \
            if isinstance(message.get("extra"), dict) else {}
        if isinstance(response, dict) and response.get("model"):
            return str(response["model"])
    config = (obj.get("info") or {}).get("config") or {}
    return str(((config.get("model") or {}) if isinstance(config, dict) else {}).get("model_name")
               or "")


def parse_object(obj: dict, *, source_file: str = "") -> dict:
    info = obj.get("info") or {}
    messages = [m for m in obj.get("messages") or [] if isinstance(m, dict)]
    builder = swebench.Builder(_model(obj))
    block = _action_pattern(info)
    texts: List[str] = []
    commands: List[str] = []
    k = 0
    while k < len(messages):
        message = messages[k]
        role, text = message.get("role"), swebench.text_of(message.get("content"))
        if role != "assistant":
            if role in ("system", "user") and (k < 2 or not texts):
                builder.message(role, text)
                texts.append(text)
            k += 1
            continue
        reply = messages[k + 1] if k + 1 < len(messages) and \
            messages[k + 1].get("role") in ("user", "tool") else None
        calls: List[Tuple[str, str, dict]] = []
        results: Dict[str, Tuple[Any, Dict[str, Any]]] = {}
        thought = text
        if message.get("tool_calls"):
            for n, call in enumerate(message["tool_calls"]):
                function = call.get("function") or {}
                calls.append((call.get("id") or f"call_{k}_{n}", function.get("name") or "bash",
                              swebench.json_args(function.get("arguments"))))
            outputs = [m for m in messages[k + 1:k + 1 + len(calls)] if m.get("role") == "tool"]
            for (call_id, _n, _a), output in zip(calls, outputs):
                results[call_id] = (swebench.text_of(output.get("content")), {})
        else:
            blocks = list(block.finditer(text))
            if len(blocks) == 1:
                calls = [(f"call_{k}", "bash", {"command": blocks[0].group(1).strip()})]
                thought = text[:blocks[0].start()].strip()
                if reply is not None:
                    results[calls[0][0]] = (swebench.text_of(reply.get("content")), {})
        commands += [str(args.get("command") or "") for _id, _n, args in calls]
        builder.turn(thought, calls, results)
        k += 1
    proj = project.make(project.SWEBENCH, swebench.find_roots(texts, commands),
                        swebench.instance_id(obj.get("instance_id"),
                                             source_file.split(".traj")[0]))
    return builder.envelope(
        agent=AGENT_NAME, version=str(info.get("mini_version") or ""),
        source_format=SOURCE_FORMAT, source_file=source_file, proj=proj,
        extra={"exit_status": info.get("exit_status"),
               "submission": (info.get("submission") or "")[:20000],
               "model_stats": info.get("model_stats")})
