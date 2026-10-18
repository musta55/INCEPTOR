"""OpenHands -> ATIF.

Source formats (``atif.swebench`` dispatches here):

``openhands_messages``  the LLM messages of a run, as SWE-bench submissions publish them
    (``trajs/<instance>.json``): a list of ``{"role", "content"}`` with OpenAI tool calls on
    assistant messages and ``tool`` messages answering them by ``tool_call_id``; or a dataset
    row whose ``trajectory`` is that list (``nebius/SWE-rebench-openhands-trajectories``:
    ``instance_id``, ``repo``, ``model_patch``, ``exit_status``).  It is
    recognised by the system prompt ("You are OpenHands agent") or by OpenHands' shell tool
    ``execute_bash``.  Shell output ends with ``[The command completed with exit code N.]``,
    which the verdict parser reads.

``openhands_events``  OpenHands' event stream (``--save-trajectory-path``, the GUI's export,
    or the ``history`` of an evaluation row ``{"instance_id", "history", "test_result",
    ...}``): action events (``action``: run, read, edit, write, run_ipython, browse, think,
    finish, message, ...) and observation events whose ``cause`` is the action's ``id``.
    An action names the tool call it came from in ``tool_call_metadata`` (``function_name``,
    ``tool_call_id``, the model response ``id``, shared by parallel calls); an action without
    it gets the tool OpenHands would have called.  A shell observation's exit code is in
    ``extras.metadata.exit_code``.  Bookkeeping events (recall, condensation, agent state
    changes) are skipped.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import project, swebench

MESSAGES_FORMAT = "openhands_messages"
EVENTS_FORMAT = "openhands_events"
AGENT_NAME = "openhands"

#: the tool OpenHands calls for each action kind, when the event does not say
ACTION_TOOL = {"run": "execute_bash", "read": "str_replace_editor",
               "edit": "str_replace_editor", "write": "str_replace_editor",
               "run_ipython": "execute_ipython_cell", "browse": "browser",
               "browse_interactive": "browser", "think": "think", "finish": "finish",
               "delegate": "delegate", "task_tracking": "task_tracker"}
#: events that are not the agent's actions
SKIPPED = {"recall", "condensation", "condensation_request", "change_agent_state", "null",
           "agent_state_changed"}
#: event arguments that describe the event rather than the call
_EVENT_KEYS = {"thought", "is_input", "blocking", "hidden", "confirmation_state",
               "security_risk", "impl_source", "is_confirmed", "include_extra",
               "wait_for_response", "image_urls", "file_urls", "kwargs", "outputs"}


# --------------------------------------------------------------------------- messages
def _messages(obj: Any) -> Optional[List[dict]]:
    messages = obj.get("trajectory") if isinstance(obj, dict) else obj
    if not (isinstance(messages, list) and messages and all(
            isinstance(m, dict) and "role" in m for m in messages)):
        return None
    tools = {(c.get("function") or {}).get("name") for m in messages
             for c in m.get("tool_calls") or []}
    system = swebench.text_of(messages[0].get("content")) \
        if messages[0].get("role") == "system" else ""
    return messages if tools and ("OpenHands" in system[:2000] or "execute_bash" in tools) \
        else None


def is_messages(obj: Any) -> bool:
    return _messages(obj) is not None


def parse_messages(obj: Any, *, source_file: str = "") -> dict:
    row = obj if isinstance(obj, dict) else {}
    obj = _messages(obj) or []
    builder = swebench.Builder(str(row.get("model_name") or ""))
    results: Dict[str, Tuple[Any, Dict[str, Any]]] = {}
    for message in obj:
        if message.get("role") == "tool" and message.get("tool_call_id"):
            results[message["tool_call_id"]] = (swebench.text_of(message.get("content")), {})
    texts: List[str] = []
    commands: List[str] = []
    for message in obj:
        role, text = message.get("role"), swebench.text_of(message.get("content"))
        if role in ("system", "user"):
            builder.message(role, text)
            texts.append(text)
        elif role == "assistant":
            calls = []
            for k, call in enumerate(message.get("tool_calls") or []):
                function = call.get("function") or {}
                args = swebench.json_args(function.get("arguments"))
                calls.append((call.get("id") or f"call_{len(builder.steps)}_{k}",
                              function.get("name") or "", args))
                commands.append(str(args.get("command") or ""))
            builder.turn(text, calls, results)
    proj = project.make(project.SWEBENCH, swebench.find_roots(texts[:3], commands),
                        swebench.instance_id(row.get("instance_id"),
                                             source_file.split(".json")[0]))
    return builder.envelope(agent=AGENT_NAME, version="", source_format=MESSAGES_FORMAT,
                            source_file=source_file, proj=proj,
                            extra={"exit_status": row.get("exit_status"),
                                   "submission": (row.get("model_patch") or "")[:20000]})


# --------------------------------------------------------------------------- events
def _events(obj: Any) -> Optional[List[dict]]:
    events = obj.get("history") if isinstance(obj, dict) else obj
    if isinstance(events, list) and events and all(isinstance(e, dict) for e in events) and \
            any("action" in e for e in events) and \
            all(("action" in e or "observation" in e) and "source" in e for e in events):
        return events
    return None


def is_events(obj: Any) -> bool:
    return _events(obj) is not None


def _call_args(event: dict, name: str) -> dict:
    """The arguments of the call behind an action event."""
    raw = event.get("args") or {}
    args = {k: v for k, v in raw.items() if k not in _EVENT_KEYS} if isinstance(raw, dict) \
        else {"raw": raw}
    kind = event.get("action")
    if name == "str_replace_editor":
        if kind == "read":
            args["command"] = "view"
        elif kind == "write":
            args.setdefault("command", "create")
            if "content" in args:
                args.setdefault("file_text", args.pop("content"))
        elif not args.get("command"):
            args["command"] = "str_replace"
    return args


def parse_events(obj: Any, *, source_file: str = "") -> dict:
    events = _events(obj) or []
    row = obj if isinstance(obj, dict) else {}
    by_cause: Dict[str, dict] = {}
    for event in events:
        if "observation" in event and event.get("cause") is not None:
            by_cause.setdefault(str(event["cause"]), event)
    model = str(((row.get("metadata") or {}).get("llm_config") or {}).get("model") or "")
    builder = swebench.Builder(model)
    texts: List[str] = []
    commands: List[str] = []
    turn: Optional[dict] = None                   # the open model turn: one response id

    def close() -> None:
        nonlocal turn
        if turn:
            builder.turn(turn["thought"], turn["calls"], turn["results"],
                         timestamp=turn["timestamp"])
        turn = None

    for event in events:
        kind = event.get("action")
        if kind is None or kind in SKIPPED:
            continue
        if kind in ("system", "message"):
            close()
            text = str(event.get("message") or (event.get("args") or {}).get("content") or "")
            source = "system" if kind == "system" else \
                "user" if event.get("source") == "user" else "agent"
            if source == "agent":
                builder.turn(text, [], timestamp=str(event.get("timestamp") or ""))
            else:
                builder.message(source, text, str(event.get("timestamp") or ""))
                texts.append(text)
            continue
        meta = event.get("tool_call_metadata") or {}
        response = str((meta.get("model_response") or {}).get("id") or f"event-{event.get('id')}")
        if turn is None or turn["response"] != response:
            close()
            thought = str((event.get("args") or {}).get("thought") or "")
            turn = {"response": response, "thought": thought, "calls": [], "results": {},
                    "timestamp": str(event.get("timestamp") or "")}
        name = str(meta.get("function_name") or ACTION_TOOL.get(kind, kind))
        call_id = str(meta.get("tool_call_id") or f"event_{event.get('id')}")
        args = _call_args(event, name)
        commands.append(str(args.get("command") or ""))
        turn["calls"].append((call_id, name, args))
        observation = by_cause.get(str(event.get("id")))
        if observation is not None:
            extras = observation.get("extras") or {}
            meta_out: Dict[str, Any] = {}
            code = (extras.get("metadata") or {}).get("exit_code") if isinstance(
                extras.get("metadata"), dict) else extras.get("exit_code")
            if isinstance(code, int) and code >= 0:
                meta_out["exit_code"] = code
            if observation.get("observation") == "error":
                meta_out["is_error"] = True
            turn["results"][call_id] = (str(observation.get("content") or ""), meta_out)
    close()
    instance = row.get("instance") if isinstance(row.get("instance"), dict) else {}
    proj = project.make(project.SWEBENCH, swebench.find_roots(texts[:3], commands),
                        swebench.instance_id(row.get("instance_id"), instance.get("instance_id"),
                                             source_file.split(".json")[0]))
    return builder.envelope(agent=AGENT_NAME, version=str(row.get("version") or ""),
                            source_format=EVENTS_FORMAT, source_file=source_file, proj=proj)
