"""Fidelity tests: the ATIF output must account for everything in the raw log.

Plain unittest so it runs on the system interpreter:  python3 -m unittest discover -s tests -t .
The fixtures are real logs of Dataset/ (bug 18, config ``original``, run 1, unless a test
needs a log with a particular quirk, which it names).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from atif import audit, claude, codex, corpus, detect, qwen, schema, tar, taxonomy  # noqa: E402

DATASET = HERE.parent.parent / "Dataset"
BUG = "18"
CONFIG = "original"
RUN = 1


def _raw_logs():
    return corpus.logs_for(DATASET, BUG, CONFIG, RUN)


def _log(agent: str, config: str, run: int, bug: str) -> Path:
    path = corpus.log_path(DATASET, agent, config, run, bug)
    if path is None:
        raise unittest.SkipTest(f"{agent}/{config}/run{run}/bug-{bug} is not in the dataset")
    return path


def _all_steps(trajectory: dict):
    """Steps of the trajectory and of every embedded subagent, at any depth."""
    for step in trajectory.get("steps", []):
        yield step
    for sub in trajectory.get("subagent_trajectories") or []:
        yield from _all_steps(sub)


class DetectionTests(unittest.TestCase):
    def test_every_log_is_recognised(self):
        expected = {"claude": claude.SOURCE_FORMAT, "codex": codex.SOURCE_FORMAT,
                    "qwen": qwen.SOURCE_FORMAT}
        logs = _raw_logs()
        self.assertEqual(set(logs), set(expected))
        for agent, path in logs.items():
            self.assertEqual(detect.detect(path), expected[agent], f"{agent}: {path}")

    def test_detection_on_a_sample_of_the_corpus(self):
        expected = {"claude": claude.SOURCE_FORMAT, "codex": codex.SOURCE_FORMAT,
                    "qwen": qwen.SOURCE_FORMAT}
        ids = corpus.all_bug_ids(DATASET)[:5]
        for config in (CONFIG, "caus_man_screen_description_screenshot_xml"):
            for bug_id in ids:
                for agent, path in corpus.logs_for(DATASET, bug_id, config, 2).items():
                    self.assertEqual(detect.detect(path), expected[agent],
                                     f"bug-{bug_id}/{agent}/{config}")

    def test_formats_are_never_confused(self):
        """One synthetic line of each format, plus look-alikes that must not match."""
        samples = {
            "claude": ("AssistantMessage(content=[TextBlock(text='hi')], model='m', "
                       "parent_tool_use_id=None)\n", claude.SOURCE_FORMAT),
            "codex": ('{"timestamp":"t","type":"session_meta","payload":{"id":"x"}}\n',
                      codex.SOURCE_FORMAT),
            "qwen": ('{"type":"system","subtype":"init","session_id":"s","uuid":"u",'
                     '"qwen_code_version":"0.24.2"}\n', qwen.SOURCE_FORMAT),
            # a log whose head is lost is still Qwen (assistant events carry the scope)
            "qwen_headless": ('Retrying provider attempt (0 buffered tool call(s) discarded).\n'
                              '{"type":"assistant","uuid":"u","session_id":"s",'
                              '"parent_tool_use_id":null,"message":{"content":[]}}\n',
                              qwen.SOURCE_FORMAT),
            # Claude Code's own raw JSON: stream-json, a transcript, a stream whose head
            # was lost (a user event looks like Qwen's until the assistant names its model)
            "claude_stream_json": ('{"type":"system","subtype":"init","session_id":"s",'
                                   '"claude_code_version":"2.1"}\n', claude.JSON_SOURCE_FORMAT),
            "claude_transcript": ('{"type":"user","parentUuid":null,"isSidechain":false,'
                                  '"sessionId":"s","message":{"role":"user","content":"hi"}}\n',
                                  claude.JSON_SOURCE_FORMAT),
            "claude_headless": ('{"type":"user","uuid":"u","session_id":"s",'
                                '"parent_tool_use_id":null,"message":{"content":[]}}\n'
                                '{"type":"assistant","uuid":"u","session_id":"s",'
                                '"parent_tool_use_id":null,"message":{"model":"claude-opus-5",'
                                '"content":[]}}\n', claude.JSON_SOURCE_FORMAT),
            "plain_text": ("just some stderr\n", None),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (text, expected) in samples.items():
                path = Path(tmp) / f"{name}.log"
                path.write_text(text, encoding="utf-8")
                self.assertEqual(detect.detect(path), expected, name)


class SchemaTests(unittest.TestCase):
    def test_all_trajectories_validate(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            self.assertEqual(schema.validate(trajectory, agent), [])

    def test_step_ids_are_sequential_and_sources_valid(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            for index, step in enumerate(trajectory["steps"], 1):
                self.assertEqual(step["step_id"], index, agent)
                self.assertIn(step["source"], schema.SOURCES)
                self.assertIn("message", step)

    def test_every_tool_call_has_a_result_or_a_subagent_ref(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            for step in _all_steps(trajectory):
                results = {r.get("source_call_id")
                           for r in (step.get("observation") or {}).get("results", [])}
                for call in step.get("tool_calls") or []:
                    self.assertIn(call["tool_call_id"], results,
                                  f"{agent} step {step['step_id']}: unmatched tool call")

    def test_validator_enforces_harbors_same_step_rule(self):
        """Harbor rejects a result whose call is declared in another step; so must we."""
        first = schema.agent_step(1)
        schema.add_tool_call(first, "c1", "Read", {})
        second = schema.agent_step(2)
        schema.add_observation(second, "c1", "late result")
        trajectory = schema.envelope(session_id="s", agent_name="a", agent_version="1",
                                     model_name="m", steps=[first, second])
        self.assertTrue(any("another step" in e for e in schema.validate(trajectory)))


class NoDataLossTests(unittest.TestCase):
    """Counts in the ATIF file must equal counts taken straight from the raw log."""

    def test_claude_tool_calls_and_inferences(self):
        path = _raw_logs()["claude"]
        messages = claude.read_messages(path)
        raw_calls = sum(1 for m in messages for b in claude._blocks(m)
                        if b["__type__"] == "ToolUseBlock")
        trajectory = claude.parse(path)
        self.assertEqual(len(taxonomy.actions(trajectory)), raw_calls)
        # one step per API response: the SDK stamps every block with its message_id
        message_ids = {m["message_id"] for m in messages
                       if m["__type__"] == "AssistantMessage" and m.get("message_id")
                       and m.get("parent_tool_use_id") is None}
        agent_steps = sum(1 for s in trajectory["steps"] if s["source"] == "agent")
        self.assertTrue(message_ids)
        self.assertEqual(agent_steps, len(message_ids))
        self.assertEqual(trajectory["extra"]["step_boundary"], "message_id")

    def test_claude_streamed_tool_results_do_not_split_an_inference(self):
        """With this SDK a tool runs while its response is still streaming, so a tool
        result can sit between two tool_use blocks of one response. Those blocks are one
        inference; the old rule ("a UserMessage closes the turn") split them."""
        path = _raw_logs()["claude"]
        trajectory = claude.parse(path)
        by_id = Counter(m["message_id"] for m in claude.read_messages(path)
                        if m["__type__"] == "AssistantMessage" and m.get("message_id"))
        for step in trajectory["steps"]:
            message_id = (step.get("extra") or {}).get("message_id")
            if message_id:
                self.assertEqual(len(step["extra"]["source_lines"]), by_id[message_id])

    def test_codex_tool_calls_and_step_boundaries(self):
        path = _raw_logs()["codex"]
        events = codex.read_events(path)
        payloads = [e.get("payload") or {} for e in events]
        raw_calls = sum(1 for p in payloads if p.get("type") in codex.CALL_TYPES)
        responses = sum(1 for p in payloads
                        if p.get("type") == "token_count" and codex._last_usage(p))
        trajectory = codex.parse(path)
        self.assertEqual(len(taxonomy.actions(trajectory)), raw_calls)
        agent_steps = [s for s in trajectory["steps"] if s["source"] == "agent"]
        self.assertEqual(len(agent_steps), responses,
                         "one agent step per token_count (one per model response)")
        self.assertEqual(trajectory["extra"]["step_boundary"], "token_count")
        for step in agent_steps:
            self.assertIn("metrics", step, "every response reports its own usage")

    def test_qwen_tool_calls_and_step_boundaries(self):
        path = _raw_logs()["qwen"]
        events, _ = qwen.read_events(path)
        raw_calls = sum(1 for e in events if e.get("type") == "assistant"
                        for b in e["message"].get("content") or [] if b.get("type") == "tool_use")
        usage_events = sum(1 for e in events
                           if e.get("type") == "assistant" and e.get("parent_tool_use_id") is None
                           and qwen._usage_reported(e["message"].get("usage")))
        trajectory = qwen.parse(path)
        self.assertEqual(len(taxonomy.actions(trajectory)), raw_calls)
        agent_steps = [s for s in trajectory["steps"] if s["source"] == "agent"]
        interrupted = [s for s in agent_steps if "interrupted_by_retry" in (s.get("extra") or {})]
        unfinished = [s for s in agent_steps if "metrics" not in s
                      and "interrupted_by_retry" not in (s.get("extra") or {})]
        # every completed inference ends with exactly one usage-bearing event
        self.assertEqual(len(agent_steps) - len(interrupted) - len(unfinished), usage_events)
        self.assertEqual(trajectory["extra"]["reported_usage_events"], usage_events)
        # num_turns counts the same inferences, minus abandoned attempts, as long as no
        # background-agent notification restarted the conversation
        if not trajectory["extra"]["harness_notifications"]:
            self.assertEqual(len(agent_steps) - len(interrupted),
                             trajectory["extra"]["reported_num_turns"])

    def test_qwen_retry_keeps_the_abandoned_attempt_as_its_own_step(self):
        path = _log("qwen", "original", 1, "365")
        trajectory = qwen.parse(path)
        interrupted = [s for s in trajectory["steps"]
                       if "interrupted_by_retry" in (s.get("extra") or {})]
        self.assertEqual(len(interrupted), 1)
        self.assertNotIn("tool_calls", interrupted[0])
        agent_steps = sum(1 for s in trajectory["steps"] if s["source"] == "agent")
        self.assertEqual(agent_steps, trajectory["extra"]["reported_usage_events"] + 1)

    def test_token_totals_match_the_raw_log(self):
        codex_traj = codex.parse(_raw_logs()["codex"])
        raw_max = 0
        for event in codex.read_events(_raw_logs()["codex"]):
            info = ((event.get("payload") or {}).get("info") or {})
            total = info.get("total_token_usage") or {}
            raw_max = max(raw_max, total.get("input_tokens") or 0)
        self.assertEqual(codex_traj["final_metrics"]["total_prompt_tokens"], raw_max)

        qwen_traj = qwen.parse(_raw_logs()["qwen"])
        events, _ = qwen.read_events(_raw_logs()["qwen"])
        result = next(e for e in events if e.get("type") == "result")
        self.assertEqual(qwen_traj["final_metrics"]["total_prompt_tokens"],
                         result["usage"]["input_tokens"])
        self.assertEqual(qwen_traj["final_metrics"]["total_completion_tokens"],
                         result["usage"]["output_tokens"])

    def test_qwen_sidecar_is_attached(self):
        path = _raw_logs()["qwen"]
        trajectory = qwen.parse(path)
        meta = json.loads(qwen.sidecar_path(path).read_text(encoding="utf-8"))
        self.assertEqual(trajectory["extra"]["harness_meta"], meta)
        self.assertEqual(trajectory["agent"]["model_name"], meta["model"])


class QwenQuirkTests(unittest.TestCase):
    """The stream-json quirks that only Qwen logs have."""

    def test_foreground_subagent_is_embedded_and_spliced(self):
        path = _log("qwen", "caus_man_screen_description", 1, "1138")
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        subs = trajectory["subagent_trajectories"]
        self.assertEqual(len(subs), 1)
        sub = subs[0]
        self.assertEqual(sub["extra"]["scope"], "subagent")
        self.assertTrue(sub["extra"]["internals_streamed"])
        self.assertEqual(sub["steps"][0]["source"], "user")       # the delegated prompt
        # sub-agent events: every one with parent_tool_use_id set
        events, _ = qwen.read_events(path)
        sub_calls = sum(1 for e in events
                        if e.get("type") == "assistant"
                        and e.get("parent_tool_use_id") == sub["extra"]["delegating_tool_call_id"]
                        for b in e["message"]["content"] if b.get("type") == "tool_use")
        rows = taxonomy.actions(trajectory)
        delegating = [i for i, r in enumerate(rows) if r["delegates_to"]]
        self.assertEqual(len(delegating), 1)
        index = delegating[0]
        self.assertEqual(rows[index]["tool"], "agent")
        spliced = [r for r in rows if r["scope"] == sub["trajectory_id"]]
        self.assertEqual(len(spliced), sub_calls)
        self.assertEqual(rows[index + 1]["scope"], sub["trajectory_id"],
                         "the sub-agent's actions must follow its delegating call")
        self.assertEqual(rows[0]["scope"], "main")
        self.assertIn("main", [r["scope"] for r in rows[index + 1 + sub_calls:]])
        # the delegating call keeps the tool's own output next to the ref
        call_result = rows[index]["result"]
        self.assertTrue(call_result.strip())

    def test_background_subagent_records_what_was_not_streamed(self):
        path = _log("qwen", "caus_man_screen_description", 1, "1130")
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        sub = trajectory["subagent_trajectories"][0]
        self.assertTrue(sub["extra"]["background"])
        self.assertFalse(sub["extra"]["internals_streamed"])
        self.assertEqual(sub["extra"]["subagent_type"], "Explore")
        self.assertGreater(sub["extra"]["reported_usage"]["tool_uses"], 0)
        for gap in ("subagent_internals_not_streamed", "subagent_result_not_streamed",
                    "num_turns_excludes_continuation_turns"):
            self.assertIn(gap, trajectory["extra"]["known_gaps"])
        notes = [s for s in trajectory["steps"]
                 if (s.get("extra") or {}).get("record_kind") == "harness_notification"]
        self.assertTrue(notes and notes[0]["message"].startswith("Background agent"))

    def test_resumed_background_subagent_keeps_every_run(self):
        # send_message resumes the Explore agent: two task_started and two task_notification
        # events share one tool_use_id; the first run (42 tool uses) must not be overwritten
        path = _log("qwen", "caus_man_screen_description", 1, "1255")
        events, _ = qwen.read_events(path)
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        sub = trajectory["subagent_trajectories"][0]
        tool_use_id = sub["extra"]["delegating_tool_call_id"]
        task_events = [e for e in events if e.get("type") == "system"
                       and (e.get("data") or {}).get("tool_use_id") == tool_use_id]
        notifications = [e["data"] for e in task_events if e["subtype"] == "task_notification"]
        launches = sum(1 for e in task_events if e["subtype"] == "task_started")
        self.assertEqual((launches, len(notifications)), (2, 2))
        self.assertEqual(sub["extra"]["resumed"], 1)
        self.assertEqual([r["usage"] for r in sub["extra"]["runs"]],
                         [n["usage"] for n in notifications])
        self.assertEqual(sub["extra"]["runs"][0]["usage"]["total_tokens"], 455764)
        for key in ("total_tokens", "tool_uses", "duration_ms"):
            self.assertEqual(sub["extra"]["reported_usage"][key],
                             sum(n["usage"][key] for n in notifications))
        self.assertEqual(sub["extra"]["status"], notifications[-1]["status"])

    def test_nested_delegation_embeds_in_its_own_parent(self):
        path = _log("qwen", "causing_screen_description_screenshot", 1, "1138")
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        streamed = [s for s in trajectory["subagent_trajectories"]
                    if s["extra"]["internals_streamed"]]
        self.assertTrue(streamed)
        nested_calls = [c for s in streamed[0]["steps"] for c in s.get("tool_calls") or []
                        if c["function_name"] == "agent"]
        self.assertTrue(nested_calls, "the sub-agent itself delegates")

    def test_a_log_without_a_result_event(self):
        path = _log("qwen", "original", 3, "1138")
        events, found = qwen.read_events(path)
        self.assertFalse(any(e.get("type") == "result" for e in events))
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        extra = trajectory["extra"]
        self.assertEqual(extra["outcome"], "missing")
        self.assertIn("no_result_event", extra["known_gaps"])
        self.assertIn("Operation cancelled.", [d["message"] for d in extra["stderr_diagnostics"]])
        self.assertEqual(extra["harness_meta"]["exit_code"], -15)
        # the totals fall back to the sum of what each inference reported
        steps = [s for s in _all_steps(trajectory) if s.get("metrics")]
        self.assertEqual(trajectory["final_metrics"]["total_prompt_tokens"],
                         sum(s["metrics"]["prompt_tokens"] for s in steps))

    def test_non_json_lines_are_tolerated_and_split_events_rejoined(self):
        """Qwen's stderr shares the file. A stderr line written while a >64 KiB event was
        being flushed splits that event in two; the halves are rejoined."""
        path = _log("qwen", "caus_man_screen_description", 1, "84")
        events, found = qwen.read_events(path)
        self.assertEqual(len(found["repaired"]), 2)
        self.assertEqual(found["stray"], [])
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        nonempty = sum(1 for line in lines if line.strip())
        own_line_stderr = sum(1 for d in found["stderr"] if not d.get("inside_json_event"))
        continuation_lines = sum(r["joined_lines"] - 1 for r in found["repaired"])
        # every physical line is an event, a stderr line, or the second half of an event
        self.assertEqual(len(events) + own_line_stderr + continuation_lines + len(found["stray"]),
                         nonempty)
        trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        report = audit.audit(path, trajectory)
        self.assertEqual(report["totals"]["found"], report["totals"]["blocks"])

    def test_split_event_and_stray_line_on_a_synthetic_log(self):
        head = ('{"type":"assistant","uuid":"a","session_id":"s","parent_tool_use_id":null,'
                '"message":{"model":"m","content":[{"type":"text","text":"abc def')
        tail = (' ghi"}],"usage":{"input_tokens":5,"output_tokens":2}}}')
        text = "\n".join([
            '{"type":"system","subtype":"init","session_id":"s","uuid":"u","model":"m",'
            '"qwen_code_version":"0.24.2","tools":[]}',
            head + "Retrying provider attempt (0 buffered tool call(s) discarded).",
            tail,
            "something unexpected",
            '{"type":"result","subtype":"success","session_id":"s","num_turns":1,'
            '"usage":{"input_tokens":5,"output_tokens":2},"result":"done"}',
        ]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bug-0.log"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(detect.detect(path), qwen.SOURCE_FORMAT)
            trajectory = qwen.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        self.assertEqual(trajectory["steps"][0]["message"], "abc def ghi")
        extra = trajectory["extra"]
        self.assertEqual(extra["repaired_lines"], [{"line": 2, "joined_lines": 2}])
        self.assertEqual(extra["stray_lines"], [{"line": 4, "text": "something unexpected"}])
        self.assertEqual(extra["stderr_diagnostics"][0]["line"], 2)
        self.assertNotIn("harness_meta", extra)

    def test_raw_tool_names_and_arguments_are_kept(self):
        """Qwen sometimes emits a garbled tool name (an unparsed XML tool call); it is kept
        verbatim, never normalised."""
        path = _raw_logs()["qwen"]
        events, _ = qwen.read_events(path)
        raw = [(b["id"], b["name"], b["input"]) for e in events if e.get("type") == "assistant"
               for b in e["message"]["content"] if b.get("type") == "tool_use"]
        parsed = [(c["tool_call_id"], c["function_name"], c["arguments"])
                  for s in _all_steps(qwen.parse(path)) for c in s.get("tool_calls") or []]
        self.assertEqual(sorted(raw, key=lambda r: r[0]), sorted(parsed, key=lambda r: r[0]))


class ClaudeQuirkTests(unittest.TestCase):
    def test_a_corrupted_line_is_recovered_not_fatal(self):
        path = _log("claude", "caus_man_screen_description", 1, "1255")
        trajectory = claude.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        damaged = trajectory["extra"]["damaged_lines"]
        self.assertEqual([d["kind"] for d in damaged], ["recovered"])
        self.assertEqual(damaged[0]["dropped_from_field"], "tool_use_result")
        self.assertIn("corrupted_source_line", trajectory["extra"]["known_gaps"])
        report = audit.audit(path, trajectory)
        self.assertEqual(report["totals"]["found"], report["totals"]["blocks"])

    def test_a_log_cut_before_its_result(self):
        path = _log("claude", "caus_man_screen_description_screenshot", 2, "130")
        trajectory = claude.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        extra = trajectory["extra"]
        self.assertEqual(extra["outcome"], "missing")
        self.assertIn("no_result_message", extra["known_gaps"])
        # the last call never got a result: it is listed, not given an invented one
        self.assertTrue(extra["unanswered_tool_calls"])
        last_call = [c for s in trajectory["steps"] for c in s.get("tool_calls") or []][-1]
        self.assertIn(last_call["tool_call_id"], extra["unanswered_tool_calls"])

    def test_subagent_actions_are_spliced_at_the_delegating_call(self):
        trajectory = claude.parse(_log("claude", CONFIG, RUN, "271"))
        self.assertTrue(trajectory.get("subagent_trajectories"))
        rows = taxonomy.actions(trajectory)
        delegating = [i for i, r in enumerate(rows) if r["delegates_to"]]
        self.assertTrue(delegating, "expected a delegating call")
        for index in delegating:
            target = rows[index]["delegates_to"]
            self.assertEqual(rows[index + 1]["scope"], target,
                             "the subagent's actions must follow its delegating call")
            self.assertTrue(rows[index]["result"].strip(),
                            "the delegating call keeps the subagent's report as its result")
        self.assertEqual(rows[0]["scope"], "main")
        self.assertIn("main", [r["scope"] for r in rows[delegating[0] + 2:]])
        sub = trajectory["subagent_trajectories"][0]
        self.assertTrue(sub["extra"]["subagent_type"])

    def test_background_agent_task_keeps_the_clis_usage_report(self):
        # the TaskNotificationMessage's usage is the CLI's own cost report of a background
        # agent; it differs from the Agent tool's structured result, so both are kept
        path = _log("claude", "caus_man_screen_description", 1, "1138")
        trajectory = claude.parse(path)
        self.assertEqual(schema.validate(trajectory), [])
        notified = {claude._data(m)["task_id"]: claude._data(m)
                    for m in claude.read_messages(path)
                    if m["__type__"] == "TaskNotificationMessage"
                    and isinstance(claude._data(m).get("usage"), dict)}
        self.assertTrue(notified)
        tasks = {t["task_id"]: t for t in trajectory["extra"]["background_tasks"]}
        for task_id, data in notified.items():
            self.assertEqual(tasks[task_id]["usage"], data["usage"])
            self.assertEqual(tasks[task_id]["subagent_type"], "Explore")
        self.assertEqual(tasks["a280113f016951541"]["usage"]["total_tokens"], 66895)


class RetentionTests(unittest.TestCase):
    """Nothing text-bearing in a raw log may vanish in conversion."""

    def test_every_raw_text_block_survives_conversion(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            report = audit.audit(path, trajectory)
            totals = report["totals"]
            self.assertGreater(totals["blocks"], 0, agent)
            self.assertEqual(
                totals["found"], totals["blocks"],
                f"{agent}: {totals['blocks'] - totals['found']} block(s) lost: "
                + "; ".join(f"{m['record_type']}.{m['field']}" for m in report["missing"][:5]))

    def test_codex_context_blocks_are_captured(self):
        """The system prompt, sandbox rules and AGENTS.md are context the agent acted
        under; they were silently dropped until an audit of bug-8 caught it."""
        trajectory = codex.parse(_raw_logs()["codex"])
        kinds = {(s.get("extra") or {}).get("record_kind") for s in trajectory["steps"]}
        self.assertIn("agent_system_prompt", kinds)
        self.assertIn("sandbox_instructions", kinds)
        for step in trajectory["steps"]:
            if (step.get("extra") or {}).get("record_kind"):
                self.assertIn(step["source"], ("system", "user"))
                self.assertTrue(step["message"].strip())

    def test_context_steps_do_not_pollute_the_action_analysis(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            for step in _all_steps(trajectory):
                if (step.get("extra") or {}).get("record_kind"):
                    self.assertNotIn("tool_calls", step, agent)

    def test_images_become_placeholders_not_base64(self):
        path = _log("codex", "caus_man_screen_description_screenshot", 1, "1130")
        trajectory = codex.parse(path)
        with_images = [r for s in trajectory["steps"]
                       for r in (s.get("observation") or {}).get("results", [])
                       if (r.get("extra") or {}).get("images")]
        self.assertTrue(with_images)
        for result in with_images:
            self.assertIn("[image: image/png", result["content"])
            self.assertNotIn("base64,", result["content"])

    def test_truncated_results_declare_their_original_size(self):
        original = schema.OUTPUT_LIMIT
        try:
            schema.OUTPUT_LIMIT = 2000
            for agent, path in _raw_logs().items():
                trajectory = detect.parse(path)
                truncated = 0
                for step in _all_steps(trajectory):
                    for result in (step.get("observation") or {}).get("results", []):
                        meta = result.get("extra") or {}
                        if meta.get("truncated"):
                            truncated += 1
                            self.assertGreater(meta["original_chars"], len(result["content"]))
                self.assertGreater(truncated, 0, f"{agent}: nothing exceeded 2,000 chars")
        finally:
            schema.OUTPUT_LIMIT = original

    def test_full_output_is_recoverable_from_the_raw_log(self):
        """Truncation moves text out of the ATIF file; it must not destroy it."""
        original = schema.OUTPUT_LIMIT
        try:
            schema.OUTPUT_LIMIT = 2000
            for agent, path in _raw_logs().items():
                trajectory = detect.parse(path)
                truncated = {r["source_call_id"]: r["extra"]["original_chars"]
                             for s in _all_steps(trajectory)
                             for r in (s.get("observation") or {}).get("results", [])
                             if (r.get("extra") or {}).get("truncated")}
                self.assertTrue(truncated, agent)
                inventory = audit.INVENTORIES[detect.detect(path)](path)
                raw = {b["call_id"]: b for b in inventory
                       if b["call_id"] and b["field"] in ("output", "content")}
                for call_id, chars in truncated.items():
                    self.assertEqual(len(raw[call_id]["text"]), chars, f"{agent} {call_id}")
        finally:
            schema.OUTPUT_LIMIT = original


class SufficiencyTests(unittest.TestCase):
    """The granularity ladder must be computable from the ATIF file alone, and must not
    depend on any content that truncation removes. This is the claim the pipeline makes:
    ATIF is a sufficient representation for the analysis, not just a convenient one."""

    def _labels(self, trajectory):
        return [(r["action_index"], r["tool"], r["mid_level"], r["kind"], r["edit_role"],
                 r["failed"]) for r in taxonomy.annotate(trajectory)]

    def test_labels_are_invariant_to_output_truncation(self):
        original = schema.OUTPUT_LIMIT
        try:
            for agent, path in _raw_logs().items():
                schema.OUTPUT_LIMIT = 10 ** 12
                full = self._labels(detect.parse(path))
                schema.OUTPUT_LIMIT = 500          # far below any real tool output
                tiny = self._labels(detect.parse(path))
                self.assertEqual(full, tiny,
                                 f"{agent}: labels change when tool output is truncated")
                self.assertTrue(full)
        finally:
            schema.OUTPUT_LIMIT = original

    def test_ladder_reads_no_field_outside_the_atif_document(self):
        """Classification is a pure function of the trajectory dict: a trajectory loaded
        from disk, with no access to the raw log, must label identically."""
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            round_tripped = json.loads(json.dumps(trajectory, default=str))
            self.assertEqual(self._labels(trajectory), self._labels(round_tripped))


class TaxonomyTests(unittest.TestCase):
    def test_shell_commands_are_classified_by_command_not_tool_name(self):
        cases = {
            "sed -n '1,220p' app/Main.java": "read_file",
            "rg -n 'setRunningActionMode' app/src": "search_code",
            "./gradlew clean assembleDebug": "build",
            "adb shell am instrument -w -e class edu.sage.Script8 x/y": "run_test",
            "adb devices": "device_ops",
            "export JAVA_HOME=$(/usr/libexec/java_home -v 1.8)": "env_setup",
            "git diff -- app/Main.java": "vcs",
            "ls -la": "orient",
        }
        for command, expected in cases.items():
            call = {"function_name": "exec_command", "arguments": {"cmd": command}}
            self.assertEqual(taxonomy.mid_level(call), expected, command)

    def test_compound_commands_are_classified_by_the_program_they_run(self):
        """Regressions found by reading bug-18 by hand."""
        cases = {
            # a path containing androidTest does not make a read into a test run
            "sed -n '1,220p' reproducing/app/src/androidTest/java/Script18.java": "read_file",
            "find reproducing/app/src/androidTest/java -maxdepth 2 -type f": "search_code",
            "rg -n 'Script18|stock' reproducing/app/src/androidTest": "search_code",
            "sed -n '1,260p' run_pipeline.sh": "read_file",
            # .gradle-local is not a gradle invocation
            "rm -rf .android-home .gradle-local": "env_setup",
            # the pipe target must not outrank the distinctive act
            "git diff -- A.java B.java | sed -n '1,220p'": "vcs",
            # a multi-line setup script ending in a test run is a test run
            "mkdir -p /tmp/fakebin\ncat > /tmp/fakebin/jenv <<'EOF'\nexit 0\nEOF\n"
            "chmod +x /tmp/fakebin/jenv\nexport PATH=/tmp/fakebin:$PATH\n"
            "./run_pipeline.sh Script18": "run_test",
            # but the same setup without the run is setup
            "mkdir -p /tmp/fakebin\nchmod +x /tmp/fakebin/jenv": "env_setup",
            "cat .java-version && /usr/libexec/java_home -V | sed -n '1,120p'": "env_setup",
            "./gradlew clean assembleDebug": "build",
            "./gradlew connectedAndroidTest": "run_test",
            # regressions from the segmenter review (fix 5): variant test tasks are one
            # word, so \btest\b missed them; a patch heredoc is an edit, not a shell command
            "./gradlew :app:testDebugUnitTest": "run_test",
            "./gradlew :omniNotes:testFossDebugUnitTest 2>&1 | tail -20": "run_test",
            "./gradlew assemble assembleAndroidTest": "build",
            "apply_patch <<'PATCH'\n*** Begin Patch\n*** Update File: a/B.java\n@@\n-x;\n"
            "+y;\n*** End Patch\nPATCH": "edit_file",
            # a | inside quotes is not a pipe
            'rg -n "Script1213|jenv|gradle|androidTest" reproducing_script_project -S':
                "search_code",
        }
        for command, expected in cases.items():
            call = {"function_name": "exec_command", "arguments": {"cmd": command}}
            self.assertEqual(taxonomy.mid_level(call), expected,
                             f"{command[:60]!r}")

    def test_every_action_gets_a_known_label(self):
        for agent, path in _raw_logs().items():
            for row in taxonomy.annotate(detect.parse(path)):
                self.assertIn(row["mid_level"], taxonomy.MID_LEVEL, agent)
                if row["mid_level"] == "edit_file":
                    self.assertIn(row["edit_role"], taxonomy.EDIT_ROLES, agent)

    def test_unknown_tools_do_not_silently_become_a_known_action(self):
        call = {"function_name": "some_new_tool_2030", "arguments": {}}
        self.assertEqual(taxonomy.mid_level(call), "other")


class AnnotationExportTests(unittest.TestCase):
    def test_rows_carry_the_inference_boundary_and_blank_manual_columns(self):
        for agent, path in _raw_logs().items():
            trajectory = detect.parse(path)
            rows = tar.iterations(trajectory, bug_id=BUG, agent=agent)
            self.assertTrue(rows, agent)
            for row in rows:
                for column in tar.MANUAL_COLUMNS:
                    self.assertEqual(row[column], "")
                self.assertGreaterEqual(row["parallel_calls_in_step"], 1)
                self.assertIn(row["thought_source"], ("reasoning", "narration", "none"))
            self.assertEqual([r["action_index"] for r in rows],
                             list(range(1, len(rows) + 1)))

    def test_multi_call_inferences_are_preserved_not_flattened_away(self):
        """Claude and Qwen issue parallel calls in one response; the export must keep them
        grouped. (Codex 0.138 issued at most one call per response in this corpus.)"""
        for agent in ("claude", "qwen"):
            trajectory = detect.parse(_raw_logs()[agent])
            rows = tar.iterations(trajectory, bug_id=BUG, agent=agent)
            by_step = Counter((r["scope"], r["step_id"]) if "scope" in r else r["step_id"]
                              for r in rows)
            self.assertTrue(any(count > 1 for count in by_step.values()),
                            f"{agent} issues parallel calls; the export must keep them grouped")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ----------------------------------------------------------------------------- Claude raw JSON
def _json_block_of(block: dict) -> dict:
    """An SDK block as a stream-json content block (``TextBlock`` -> ``{"type": "text"}``)."""
    name = block["__type__"][:-len("Block")] if block["__type__"].endswith("Block") \
        else block["__type__"]
    kind = "".join("_" + c.lower() if c.isupper() else c for c in name).lstrip("_")
    return {"type": kind, **{k: v for k, v in block.items() if not k.startswith("__")}}


def stream_json_of(messages: list) -> str:
    """Claude Code's ``--output-format stream-json`` for the messages of an SDK dump: what
    the CLI printed before the SDK turned each event into an object."""
    lines = []
    for m in messages:
        kind = m["__type__"]
        if kind == "SystemMessage" or kind in claude.TASK_CLASSES:
            event = dict(m.get("data") or {"type": "system", "subtype": m.get("subtype")})
        elif kind in ("AssistantMessage", "UserMessage"):
            content = m.get("content")
            if not isinstance(content, str):
                content = [_json_block_of(b) for b in content or [] if isinstance(b, dict)]
            event = {"type": "assistant" if kind == "AssistantMessage" else "user",
                     "uuid": m.get("uuid"), "session_id": m.get("session_id"),
                     "parent_tool_use_id": m.get("parent_tool_use_id"),
                     "message": {"role": "assistant" if kind == "AssistantMessage" else "user",
                                 "content": content}}
            if kind == "AssistantMessage":
                event["message"].update(id=m.get("message_id"), model=m.get("model"),
                                        usage=m.get("usage"), stop_reason=m.get("stop_reason"))
                event["error"] = m.get("error")
            elif "tool_use_result" in m:
                event["tool_use_result"] = m["tool_use_result"]
        elif kind == "ResultMessage":
            event = {"type": "result", **{k: v for k, v in m.items() if not k.startswith("__")}}
        else:
            continue
        lines.append(json.dumps(event, default=str))
    return "\n".join(lines) + "\n"


@unittest.skipUnless(DATASET.is_dir(), "Dataset/ not present")
class ClaudeJsonTests(unittest.TestCase):
    """Claude Code's raw JSON gives the same trajectory as the SDK dump of the same run."""

    def test_stream_json_matches_the_sdk_dump(self):
        logs = list(corpus.iter_logs(DATASET, agents=["claude"], configs=["original"], runs=[1]))
        self.assertEqual(len(logs), 50)
        compared = 0
        with tempfile.TemporaryDirectory() as tmp:
            for key, path in logs:
                messages = [m for m in claude.read_messages(path) if "__recovered__" not in m]
                if len(messages) != sum(1 for line in path.open() if line.strip()):
                    continue                     # a damaged dump: nothing to compare against
                out = Path(tmp) / f"bug-{key.bug}.jsonl"
                out.write_text(stream_json_of(messages), encoding="utf-8")
                self.assertEqual(detect.detect(out), claude.JSON_SOURCE_FORMAT, key)
                a, b = claude.parse(path), claude.parse(out)
                for field in ("steps", "subagent_trajectories", "final_metrics", "agent"):
                    self.assertEqual(json.dumps(a.get(field), default=str),
                                     json.dumps(b.get(field), default=str).replace(
                                         claude.JSON_SOURCE_FORMAT, claude.SOURCE_FORMAT),
                                     f"bug-{key.bug}: {field}")
                compared += 1
                self.assertEqual(b["extra"]["source_format"], claude.JSON_SOURCE_FORMAT)
        self.assertGreaterEqual(compared, 45)              # nearly every dump is intact

    def test_transcript_without_init(self):
        events = [
            {"type": "user", "parentUuid": None, "isSidechain": False, "sessionId": "s",
             "cwd": "/w/bug-18", "version": "2.1.0",
             "message": {"role": "user", "content": "fix the bug"}},
            {"type": "assistant", "parentUuid": "a", "isSidechain": False, "sessionId": "s",
             "cwd": "/w/bug-18", "message": {"id": "msg_1", "model": "claude-opus-5",
             "content": [{"type": "tool_use", "id": "toolu_1", "name": "Read",
                          "input": {"file_path": "/w/bug-18/app/Foo.java"}}]}},
            {"type": "user", "parentUuid": "b", "isSidechain": True, "sessionId": "s",
             "message": {"role": "user", "content": "sub-agent chatter"}},
            {"type": "user", "parentUuid": "c", "isSidechain": False, "sessionId": "s",
             "cwd": "/w/bug-18", "toolUseResult": {"stdout": "class Foo"},
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_1", "content": "class Foo"}]}},
            {"type": "summary", "summary": "fixed"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
            self.assertEqual(detect.detect(path), claude.JSON_SOURCE_FORMAT)
            t = claude.parse(path)
        calls = [c for s in t["steps"] for c in s.get("tool_calls") or []]
        self.assertEqual([c["function_name"] for c in calls], ["Read"])
        self.assertEqual(t["extra"]["cwd"], "/w/bug-18")
        self.assertEqual(t["agent"]["model_name"], "claude-opus-5")


class ForeignAgentTests(unittest.TestCase):
    """ATIF written by Harbor for agents outside the corpus: their tool vocabularies
    (``taxonomy.SHELL_TOOLS``, ``EDITOR_TOOLS``, ``TOOL_MAP``) and results that carry no
    ``source_call_id``.  The shapes are those of Harbor's published trajectories."""

    @staticmethod
    def _traj(calls, loose=False):
        steps = []
        for k, (name, args, out) in enumerate(calls, 1):
            cid = f"c{k}"
            steps.append({"step_id": k, "source": "agent", "message": "",
                          "tool_calls": [{"tool_call_id": cid, "function_name": name, "arguments": args}],
                          "observation": {"results": [{"content": out} if loose else
                                                      {"source_call_id": cid, "content": out}]}})
        return {"schema_version": "ATIF-v1.6", "session_id": "s", "agent": {"name": "x", "version": "1"},
                "steps": steps}

    def _cats(self, traj):
        return [(r["kind"], r["result"]) for r in taxonomy.annotate(traj)]

    def test_openhands(self):
        rows = self._cats(self._traj([
            ("str_replace_editor", {"command": "view", "path": "/stage"}, "dir listing"),
            ("str_replace_editor", {"command": "view", "path": "/stage/a.py"}, "code"),
            ("str_replace_editor", {"command": "str_replace", "path": "/stage/a.py",
                                    "old_str": "a", "new_str": "b"}, "edited"),
            ("execute_bash", {"command": "grep -rn foo /stage"}, "a.py:1: foo\n[The command completed with exit code 0.]"),
            ("task_tracker", {"command": "plan", "task_list": []}, "ok"),
            ("think", {"thought": "hm"}, "ok")]))
        self.assertEqual([c for c, _ in rows], ["orient", "read_file", "edit_file", "search_code", "plan", "plan"])

    def test_terminus_keystrokes_and_loose_results(self):
        traj = self._traj([("bash_command", {"keystrokes": "cat notes.txt\n", "duration": 0.1}, "hello"),
                           ("mark_task_complete", {}, "")], loose=True)
        rows = self._cats(traj)
        self.assertEqual(rows[0], ("read_file", "hello"))
        self.assertEqual(rows[1][0], "other")

    def test_trae_and_mini_swe_agent(self):
        rows = self._cats(self._traj([
            ("bash", {"command": "sed -n '1,20p' app.py"}, "x"),
            ("str_replace_based_edit_tool", {"command": "create", "path": "/testbed/t.py", "file_text": "x"}, "ok"),
            ("bash_command", {"command": "ls -la"}, "<returncode>0</returncode>\n<output>\n.</output>")]))
        self.assertEqual([c for c, _ in rows], ["read_file", "edit_file", "orient"])
        self.assertEqual(taxonomy.shell_command({"function_name": "str_replace_editor",
                                                 "arguments": {"command": "view", "path": "/a"}}), "")
