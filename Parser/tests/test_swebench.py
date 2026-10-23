"""SWE-bench adapters (``atif.swebench``, ``sweagent``, ``openhands``, ``miniswe``) and the
SWE-bench project (``atif.project``).  The documents are cut-down copies of published runs:
SWE-bench Verified submissions (SWE-agent 0.x and 1.x, OpenHands, live-SWE-agent),
Hugging Face's ``nebius/SWE-agent-trajectories`` and ``nebius/SWE-rebench-openhands-
trajectories``, and Harbor's OpenHands event stream."""
import json
import tempfile
import unittest
from pathlib import Path

from atif import detect, phase, project, schema, swebench, taxonomy, upload, verdict

ISSUE = "<uploaded_files>\n/testbed\n</uploaded_files>\nI've uploaded a python code repository " \
        "in the directory /testbed. Consider the following PR description: ..."


def sweagent1():
    """SWE-agent 1.x: actions as strings, the same calls in the history."""
    steps = [
        ("str_replace_editor view /testbed/astropy/modeling/separable.py", "code", "view",
         {"command": "view", "path": "/testbed/astropy/modeling/separable.py"}),
        ("str_replace_editor create /testbed/reproduce_issue.py --file_text 'print(1)'", "File created",
         "create", {"command": "create", "path": "/testbed/reproduce_issue.py", "file_text": "print(1)"}),
        ("cd /testbed && python reproduce_issue.py",
         "Traceback (most recent call last):\n  File \"reproduce_issue.py\"\nAssertionError: wrong matrix",
         "bash", {"command": "cd /testbed && python reproduce_issue.py"}),
        ("str_replace_editor str_replace /testbed/astropy/modeling/separable.py --old_str '= 1' --new_str '= right'",
         "edited", "str_replace", {"command": "str_replace", "path": "/testbed/astropy/modeling/separable.py",
                                   "old_str": "= 1", "new_str": "= right"}),
        ("cd /testbed && python -m pytest astropy/modeling/tests/test_separable.py -q",
         "........\n8 passed in 0.52s", "bash",
         {"command": "cd /testbed && python -m pytest astropy/modeling/tests/test_separable.py -q"}),
        ("submit", "diff --git a/astropy/modeling/separable.py", "submit", {}),
    ]
    history = [{"role": "system", "content": "SETTING: ...", "agent": "main", "message_type": "system_prompt"},
               {"role": "user", "content": [{"type": "text", "text": ISSUE}], "agent": "main",
                "message_type": "observation"}]
    trajectory = []
    for k, (action, out, sub, args) in enumerate(steps):
        name = "submit" if action == "submit" else "bash" if sub == "bash" else "str_replace_editor"
        history.append({"role": "assistant", "content": "thinking", "thought": "thinking", "action": action,
                        "agent": "main", "message_type": "action",
                        "tool_calls": [{"id": f"t{k}", "type": "function",
                                        "function": {"name": name, "arguments": json.dumps(args)}}]})
        history.append({"role": "tool", "content": [{"type": "text", "text": out}], "agent": "main",
                        "message_type": "observation", "tool_call_ids": [f"t{k}"]})
        trajectory.append({"action": action, "observation": out, "response": "thinking", "thought": "thinking",
                           "state": "{'working_dir': '/testbed', 'diff': ''}", "execution_time": 0.1})
    return {"trajectory": trajectory, "history": history, "environment": "astropy__astropy-12907",
            "info": {"swe_agent_version": "1.0.1", "exit_status": "submitted", "submission": "diff ..."}}


def sweagent0():
    """SWE-agent 0.x: the windowed interface; edit acts on the open file; a demonstration
    of another task sits in the history."""
    steps = [("create reproduce.py", "[File: /astropy__astropy/reproduce.py (1 lines total)]", "reproduce.py"),
             ("edit 1:1\nfrom astropy.modeling import models\nend_of_edit", "File updated.", "reproduce.py"),
             ("python reproduce.py", "Traceback (most recent call last):\nValueError: bad", "reproduce.py"),
             ("open astropy/modeling/separable.py 240", "[File: separable.py]", "/astropy__astropy/astropy/modeling/separable.py"),
             ("edit 245:245\n        cright[...] = right\nend_of_edit", "File updated.", "/astropy__astropy/astropy/modeling/separable.py"),
             ("search_dir \"_cstack\" astropy", "Found 3 matches", "/astropy__astropy/astropy/modeling/separable.py"),
             ("submit", "", "n/a")]
    return {"environment": "swe_main",
            "history": [{"role": "user", "content": "(Current directory: /marshmallow-code__marshmallow)",
                         "agent": "primary", "is_demo": True}],
            "trajectory": [{"action": a, "observation": o, "response": "", "thought": "t",
                            "state": json.dumps({"open_file": f, "working_dir": "/astropy__astropy"})}
                           for a, o, f in steps],
            "info": {"exit_status": "submitted"}}


def chat_row():
    """Hugging Face's SWE-agent chat export, as a dataset row."""
    footer = "\n(Open file: {})\n(Current directory: /lexicon)\nbash-$"
    return {"instance_id": "AnalogJ__lexicon-336", "model_name": "swe-agent-llama-70b", "target": False,
            "exit_status": "submitted", "generated_patch": "diff ...",
            "trajectory": [
                {"role": "system", "system_prompt": "SETTING: ...", "text": "", "mask": False, "cutoff_date": ""},
                {"role": "user", "text": "ISSUE: Memset provider ..." + footer.format("n/a"), "mask": False},
                {"role": "ai", "text": "Let's open it.\n\n```\nopen lexicon/providers/memset.py 144\n```", "mask": False},
                {"role": "user", "text": "[File: /lexicon/lexicon/providers/memset.py]" +
                 footer.format("/lexicon/lexicon/providers/memset.py"), "mask": False},
                {"role": "ai", "text": "Fix it.\n\n```\nedit 138:138\n    x = 1\nend_of_edit\n```", "mask": False},
                {"role": "user", "text": "File updated." + footer.format("/lexicon/lexicon/providers/memset.py"),
                 "mask": False}]}


def openhands_messages():
    def call(k, name, args):
        return {"id": f"toolu_{k}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    root = "/workspace/astropy__astropy__4.3"
    calls = [("str_replace_editor", {"command": "view", "path": root}, "dirs"),
             ("str_replace_editor", {"command": "create", "path": f"{root}/reproduce_issue.py", "file_text": "x"}, "ok"),
             ("execute_bash", {"command": f"cd {root} && python reproduce_issue.py"},
              "Traceback (most recent call last):\nAssertionError\n[The command completed with exit code 1.]"),
             ("str_replace_editor", {"command": "str_replace", "path": f"{root}/astropy/modeling/separable.py",
                                     "old_str": "1", "new_str": "right"}, "edited"),
             ("execute_bash", {"command": f"cd {root} && python -m pytest astropy/modeling/tests -q"},
              "3 passed in 0.1s\n[The command completed with exit code 0.]"),
             ("finish", {"message": "done"}, "")]
    messages = [{"role": "system", "content": [{"type": "text", "text": "You are OpenHands agent, a helpful AI assistant"}]},
                {"role": "user", "content": [{"type": "text", "text": f"<uploaded_files>\n{root}\n</uploaded_files>\n..."}]}]
    for k, (name, args, out) in enumerate(calls):
        messages.append({"role": "assistant", "content": [{"type": "text", "text": "step"}],
                         "tool_calls": [call(k, name, args)]})
        messages.append({"role": "tool", "content": [{"type": "text", "text": out}], "tool_call_id": f"toolu_{k}",
                         "name": name})
    return messages


def openhands_events():
    meta = lambda k, name: {"function_name": name, "tool_call_id": f"call_{k}", "model_response": {"id": f"r{k}"}}
    return {"instance_id": "django__django-11099", "history": [
        {"id": 0, "source": "agent", "action": "system", "args": {"content": "You are OpenHands agent"}, "message": "sys"},
        {"id": 1, "source": "user", "action": "message", "message": "<uploaded_files>\n/workspace/django__django__3.0\n</uploaded_files>"},
        {"id": 2, "source": "user", "action": "recall", "args": {}},
        {"id": 3, "source": "agent", "action": "read", "args": {"path": "/workspace/django__django__3.0/django/core/validators.py",
                                                                "thought": "look"}, "tool_call_metadata": meta(3, "str_replace_editor")},
        {"id": 4, "source": "agent", "observation": "read", "cause": 3, "content": "code"},
        {"id": 5, "source": "agent", "action": "edit", "args": {"path": "/workspace/django__django__3.0/django/core/validators.py",
                                                                "command": "str_replace", "old_str": "$", "new_str": "\\Z"},
         "tool_call_metadata": meta(5, "str_replace_editor")},
        {"id": 6, "source": "agent", "observation": "edit", "cause": 5, "content": "edited"},
        {"id": 7, "source": "agent", "action": "run", "args": {"command": "cd /workspace/django__django__3.0 && ./tests/runtests.py validators"},
         "tool_call_metadata": meta(7, "execute_bash")},
        {"id": 8, "source": "agent", "observation": "run", "cause": 7, "content": "Ran 4 tests in 0.01s\n\nOK",
         "extras": {"command": "...", "metadata": {"exit_code": 0}}},
        {"id": 9, "source": "agent", "action": "finish", "args": {"final_thought": "done"}}]}


def mini():
    def reply(code, out):
        return {"role": "user", "content": f"<returncode>{code}</returncode>\n<output>\n{out}</output>"}
    return {"trajectory_format": "mini-swe-agent-1", "instance_id": "astropy__astropy-12907",
            "info": {"exit_status": "Submitted", "submission": "diff", "mini_version": "1.14.2", "config": {}},
            "messages": [
                {"role": "system", "content": "Your response must contain exactly ONE bash code block"},
                {"role": "user", "content": "<pr_description>...</pr_description> Work in /testbed."},
                {"role": "assistant", "content": "THOUGHT: write a tool.\n\n```bash\ncat <<'EOF' > /testbed/edit_file.py\nimport sys\nEOF\n```"},
                reply(0, ""),
                {"role": "assistant", "content": "THOUGHT: the bug is\n```python\ncright = 1\n```\nfix it:\n\n"
                                                 "```bash\ncd /testbed && python /testbed/edit_file.py /testbed/astropy/modeling/separable.py 245 245 <<'EOF'\n    x\nEOF\n```"},
                reply(0, "Successfully edited"),
                {"role": "assistant", "content": "THOUGHT: two commands\n```bash\nls\n```\n```bash\npwd\n```"},
                {"role": "user", "content": "Please always provide EXACTLY ONE action in triple backticks"},
                {"role": "assistant", "content": "THOUGHT: test\n\n```bash\ncd /testbed && python -m pytest astropy/modeling -q\n```"},
                reply(0, "12 passed in 1.0s")]}


SAMPLES = {"sweagent_traj": sweagent1, "sweagent_chat": chat_row, "openhands_messages": openhands_messages,
           "openhands_events": openhands_events, "mini_swe_agent": mini}


class DetectTests(unittest.TestCase):
    def test_each_format_is_recognised(self):
        for fmt, make in SAMPLES.items():
            self.assertEqual(swebench.detect_document(make()), fmt)
        self.assertEqual(swebench.detect_document(sweagent0()), "sweagent_traj")
        self.assertEqual(swebench.detect_document(chat_row()["trajectory"]), "sweagent_chat")
        self.assertEqual(swebench.detect_document({"trajectory": openhands_messages()}), "openhands_messages")
        self.assertEqual(swebench.detect_document(openhands_events()["history"]), "openhands_events")

    def test_other_documents_are_not_claimed(self):
        atif = {"schema_version": "ATIF-v1.7", "steps": [{"step_id": 1, "source": "user", "message": "x"}]}
        claude = [{"type": "system", "subtype": "init", "claude_code_version": "2.1"},
                  {"type": "assistant", "message": {"role": "assistant", "content": []}}]
        for obj in (atif, claude, [], {}, [{"role": "user", "content": "hi"}]):
            self.assertIsNone(swebench.detect_document(obj))

    def test_detect_reads_files_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fmt, make in SAMPLES.items():
                path = Path(tmp) / f"{fmt}.json"
                path.write_text(json.dumps(make(), indent=1))
                self.assertEqual(detect.detect(path), fmt)
                minified = Path(tmp) / f"{fmt}.min.json"
                minified.write_text(json.dumps(make()))
                self.assertEqual(detect.detect(minified), fmt)
                self.assertEqual(detect.AGENT_OF_FORMAT[fmt], swebench.agent_of(fmt))


class AdapterTests(unittest.TestCase):
    def _parse(self, obj, name=""):
        trajectory = swebench.parse_document(obj, source_file=name)
        self.assertEqual(schema.validate(trajectory), [])
        return trajectory

    def _calls(self, trajectory):
        return [(c["function_name"], c["arguments"]) for s in trajectory["steps"] for c in s.get("tool_calls") or []]

    def test_sweagent1_uses_the_history_calls(self):
        t = self._parse(sweagent1())
        self.assertEqual(project.of(t), project.make(project.SWEBENCH, ["/testbed"], "astropy__astropy-12907"))
        calls = self._calls(t)
        self.assertEqual(calls[1], ("str_replace_editor", {"command": "create", "path": "/testbed/reproduce_issue.py",
                                                           "file_text": "print(1)"}))
        self.assertEqual(t["extra"]["tool_calls_from"], "history")
        self.assertEqual(t["agent"]["name"], "swe-agent")

    def test_sweagent1_action_strings_without_history(self):
        obj = sweagent1()
        obj["history"] = [m for m in obj["history"] if not m.get("tool_calls")]
        calls = self._calls(self._parse(obj))
        self.assertEqual(calls[3][1]["old_str"], "= 1")
        self.assertEqual(calls[2], ("bash", {"command": "cd /testbed && python reproduce_issue.py"}))

    def test_sweagent0_edits_name_the_open_file_and_skip_demos(self):
        t = self._parse(sweagent0())
        self.assertEqual(project.of(t).roots, ("/astropy__astropy",))
        calls = self._calls(t)
        self.assertEqual(calls[1], ("edit", {"path": "reproduce.py", "lines": "1:1",
                                             "text": "from astropy.modeling import models"}))
        self.assertEqual(calls[4][1]["path"], "/astropy__astropy/astropy/modeling/separable.py")
        self.assertEqual(calls[5], ("search_dir", {"pattern": "_cstack", "path": "astropy"}))

    def test_chat_export(self):
        t = self._parse(chat_row())
        proj = project.of(t)
        self.assertEqual((proj.roots, proj.instance_id), (("/lexicon",), "AnalogJ__lexicon-336"))
        self.assertEqual(self._calls(t), [("open", {"path": "lexicon/providers/memset.py", "line_number": "144"}),
                                          ("edit", {"path": "/lexicon/lexicon/providers/memset.py", "lines": "138:138",
                                                    "text": "    x = 1"})])
        outputs = [r["content"] for s in t["steps"] for r in (s.get("observation") or {}).get("results", [])]
        self.assertEqual(outputs[0], "[File: /lexicon/lexicon/providers/memset.py]")   # footer dropped

    def test_openhands_messages_and_row(self):
        t = self._parse(openhands_messages())
        self.assertEqual(project.of(t).roots, ("/workspace/astropy__astropy__4.3",))
        self.assertEqual(len(self._calls(t)), 6)
        row = {"instance_id": "PlasmaFAIR__sdf-xarray-24", "trajectory": openhands_messages(), "model_patch": "diff"}
        self.assertEqual(project.of(self._parse(row)).instance_id, "PlasmaFAIR__sdf-xarray-24")

    def test_openhands_events(self):
        t = self._parse(openhands_events())
        self.assertEqual(project.of(t), project.make(project.SWEBENCH, ["/workspace/django__django__3.0"],
                                                     "django__django-11099"))
        calls = self._calls(t)
        self.assertEqual([c[0] for c in calls], ["str_replace_editor", "str_replace_editor", "execute_bash", "finish"])
        self.assertEqual(calls[0][1], {"path": "/workspace/django__django__3.0/django/core/validators.py",
                                       "command": "view"})
        result = t["steps"][-2]["observation"]["results"][0]
        self.assertEqual(result["extra"], {"exit_code": 0})

    def test_mini_reads_the_bash_block_only(self):
        t = self._parse(mini())
        calls = self._calls(t)
        self.assertEqual(len(calls), 3)                       # the two-block turn ran nothing
        self.assertTrue(calls[1][1]["command"].startswith("cd /testbed && python /testbed/edit_file.py"))
        self.assertEqual(project.of(t).roots, ("/testbed",))


class ProjectTests(unittest.TestCase):
    """The SWE-bench project changes only what it should, and only while it is current."""

    def _rows(self, trajectory, proj=None):
        with project.use(proj or trajectory):
            return {r["action_index"]: r for r in verdict.attach(taxonomy.annotate(trajectory))}

    def test_roles_and_runs(self):
        proj = project.make(project.SWEBENCH, ["/testbed"])
        with project.use(proj):
            self.assertEqual([taxonomy.file_role(p) for p in (
                "/testbed/astropy/x.py", "/testbed/astropy/tests/test_x.py", "/testbed/reproduce_issue.py",
                "/testbed/setup.cfg", "/tmp/repro.py", "/testbed/conftest.py", "pkg/test_util.py")],
                ["source", "test", "test", "toolchain", "test", "test", "test"])
            self.assertEqual(taxonomy._shell_kind("cd /testbed && python reproduce_issue.py"), "run_test")
            self.assertEqual(taxonomy._shell_kind("python setup.py build_ext --inplace"), "build")
            self.assertEqual(taxonomy._shell_kind("python -c 'import astropy'"), "run_shell")
            self.assertEqual(taxonomy.shell_edits("cat > /testbed/astropy/x.py <<'EOF'\nx\nEOF"),
                             ["/testbed/astropy/x.py"])
        self.assertEqual(project.current(), project.DEFAULT)
        # the Android project reads the same paths as before
        self.assertEqual(taxonomy.file_role("/testbed/reproduce_issue.py"), "source")
        self.assertEqual(taxonomy._shell_kind("cd /testbed && python reproduce_issue.py"), "run_shell")
        self.assertEqual(taxonomy.shell_edits("cat > /testbed/astropy/x.py <<'EOF'\nx\nEOF"), [])

    def test_python_verdicts_only_for_swebench_test_runs(self):
        with project.use(project.make(project.SWEBENCH, ["/testbed"])):
            self.assertEqual(verdict.verdict("run_test", "== 1 failed, 3 passed in 0.2s =="), ("fail", "test", "pytest"))
            self.assertEqual(verdict.verdict("run_test", "Ran 2 tests in 0.0s\n\nOK"), ("pass", None, "unittest"))
            self.assertEqual(verdict.verdict("run_test", "Traceback (most recent call last):\nSyntaxError: x"),
                             ("fail", "build", "traceback"))
            self.assertEqual(verdict.verdict("run_shell", "Traceback (most recent call last):\nValueError: x"),
                             ("none", None, ""))
        self.assertEqual(verdict.verdict("run_test", "== 1 failed, 3 passed in 0.2s =="), ("none", None, ""))

    def test_phases_of_a_swebench_run(self):
        result = phase.phases(swebench.parse_document(sweagent1()), "0")
        labels = [(a["category"], result["phase"][x]) for x, a in enumerate(result["actions"])]
        self.assertEqual(labels, [("read", "localization"), ("edit", "localization"),
                                  ("test", "localization"), ("edit", "repair"),
                                  ("test", "validation"), ("other", "validation")])
        self.assertEqual(result["table_row"], ["L5", "L7", "L6", "L8", "L12", "L14"])
        # the Android table has no row for python: in a SWE-bench project the taxonomy's kind
        # of the program decides (python reproduce_issue.py runs the reproduction)
        self.assertEqual(result["actions"][2]["lookup_item"], "python (a SWE-bench project)")
        self.assertEqual(result["anchor"], 4)
        self.assertEqual(result["actions"][2]["verdict"], "fail")      # the issue reproduced

    def test_scratch_scripts_are_not_modified_tests(self):
        def flagged(obj):
            result = phase.phases(swebench.parse_document(obj), "0")
            return any("test_modified" in sp["flags"] for p in result["phases"] for sp in p["subphases"])
        self.assertFalse(flagged(sweagent1()))              # it writes reproduce_issue.py only
        obj = sweagent1()
        obj["history"] = [m for m in obj["history"] if not m.get("tool_calls")]
        obj["trajectory"][1]["action"] = "str_replace_editor create " \
            "/testbed/astropy/modeling/tests/test_separable.py --file_text 'x'"
        self.assertTrue(flagged(obj))                       # the repository's own tests
        with project.use(project.make(project.SWEBENCH, ["/testbed"])):
            self.assertEqual([project.scratch(p, project.current()) for p in (
                "reproduce.py", "test_fix.py", "/tmp/r.py", "conftest.py", "setup.py", "pkg/tests/test_a.py")],
                [True, True, True, False, False, False])

    def test_an_agents_own_edit_tool_edits(self):
        rows = self._rows(swebench.parse_document(mini()))
        self.assertEqual((rows[2]["kind"], rows[2]["edit_role"], rows[2]["edit_files"]),
                         ("shell_edit", "source", ["astropy/modeling/separable.py"]))

    def test_the_same_atif_without_a_project_is_android(self):
        trajectory = swebench.parse_document(sweagent1())
        trajectory["extra"].pop("project")
        result = phase.phases(trajectory, "0")
        self.assertEqual(result["actions"][2]["kind"], "run_shell")
        self.assertEqual((result["actions"][2]["category"], result["actions"][2]["lookup_item"]),
                         ("other", "any other program"))
        self.assertEqual(result["actions"][1]["edit_role"], "source")
        self.assertEqual(result["actions"][1]["category"], "other")    # /testbed is outside


class UploadTests(unittest.TestCase):
    def test_upload_of_a_swebench_run(self):
        r = upload.analyze(json.dumps(sweagent0()), "astropy__astropy-12907.traj")
        self.assertEqual((r["source"]["format"], r["source"]["agent"], r["source"]["project"]),
                         ("sweagent_traj", "swe-agent", "swebench"))
        self.assertEqual((r["source"]["bug"], r["source"]["repo_root"]), ("astropy__astropy-12907", "/astropy__astropy"))
        self.assertEqual(r["warnings"], [])
        self.assertEqual(r["trajectory"]["project"], "swebench")
        phases = [a["phase"] for a in r["trajectory"]["actions"]]
        self.assertEqual(phases[:3], ["localization"] * 3)
        self.assertEqual(phases[4], "repair")
        self.assertEqual(r["trajectory"]["anchor"], 5)

    def test_upload_without_a_root_warns(self):
        obj = mini()
        obj["messages"][1]["content"] = "Fix the bug."
        for m in obj["messages"]:
            if m["role"] == "assistant":
                m["content"] = m["content"].replace("cd /testbed && ", "").replace("/testbed/", "")
        r = upload.analyze(json.dumps(obj), "run.traj.json")
        self.assertEqual(r["source"]["project"], "swebench")
        self.assertTrue(r["warnings"] and "repository folder" in r["warnings"][0])

    def test_atif_of_a_swebench_task_gets_the_project(self):
        trajectory = swebench.parse_document(sweagent1())
        trajectory["extra"].pop("project")
        r = upload.analyze(json.dumps(trajectory), "trajectory.json")
        self.assertEqual((r["source"]["format"], r["source"]["project"], r["source"]["repo_root"]),
                         ("atif", "swebench", "/testbed"))

    def test_android_uploads_are_unchanged(self):
        atif = {"schema_version": "ATIF-v1.7", "session_id": "s", "agent": {"name": "claude-code", "version": "1"},
                "steps": [{"step_id": 1, "source": "agent", "message": "",
                           "tool_calls": [{"tool_call_id": "c", "function_name": "Read",
                                           "arguments": {"file_path": "/runs/bug-18/app/src/A.java"}}],
                           "observation": {"results": [{"source_call_id": "c", "content": "x"}]}}]}
        r = upload.analyze(json.dumps(atif), "x.json")
        self.assertEqual((r["source"]["project"], r["source"]["bug"]), ("android", "18"))
        self.assertNotIn("project", r["trajectory"])

    def test_unknown_files_name_the_new_agents(self):
        r = upload.request({"name": "x.json", "text": json.dumps({"hello": 1})})
        self.assertIn("SWE-agent, OpenHands or mini-swe-agent", r["error"])


if __name__ == "__main__":
    unittest.main()
