"""Segmenter, verdict and taxonomy tests.

Each rule is pinned on a small synthetic trajectory (ATIF-shaped, built by ``_traj``) or on
the pure function that implements it; the agent vocabularies are pinned on the tool calls
the corpus actually contains.  The invariant tests segment real trajectories of
``Dataset/`` (config ``original``, run 1, parsed from the raw logs, so no prior ``convert``
is needed), and the three real examples below were checked by reading the trajectory:

* codex original/run1 bug-44, action 8: one ``exec_command`` that applies an
  ``apply_patch <<'PATCH'`` to TagsHelper.java and TagsHelperTest.java and then runs
  ``./gradlew :omniNotes:testDebugUnitTest``;
* claude original/run2 bug-1640, action 8: a ``python3 - <<'PY'`` script that rewrites
  app/src/main/res/values/strings.xml with ``open(..., 'w')``; the first source edit;
* qwen original/run1 bug-1568: ``edit`` of FileArrayAdapter.java at action 5, then
  ``patch -p1 --dry-run`` (15), ``patch -p1 < patch.patch`` (21) and
  ``sed -i 's/Fuling/Fülling/' .../FileArrayAdapter.java`` (22).

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import collections
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from atif import corpus, detect, outcomes, segment, tar, taxonomy, verdict  # noqa: E402

DATASET = HERE.parent.parent / "Dataset"
HAVE_DATASET = DATASET.is_dir()

_CACHE: dict = {}


# ----------------------------------------------------------------------------- helpers
def _trajectory(agent: str, bug: str, config: str = "original", run: int = 1) -> dict:
    key = corpus.Key(agent, config, run, str(bug))
    if key not in _CACHE:
        _CACHE[key] = detect.parse(corpus.log_path(DATASET, *key), extra={"bug_id": key.bug})
    return _CACHE[key]


def _segmented(agent: str, bug: str, config: str = "original", run: int = 1) -> dict:
    key = ("seg", agent, str(bug), config, run)
    if key not in _CACHE:
        _CACHE[key] = segment.segment(_trajectory(agent, bug, config, run), str(bug))
    return _CACHE[key]


def _run1() -> list:
    """(Key, trajectory) for every agent and bug of original/run1."""
    return [(key, _trajectory(key.agent, key.bug))
            for key, _path in corpus.iter_logs(DATASET, configs=["original"], runs=[1])]


def _call(tool: str, args: dict = None, result: str = "", *, error=None, ref: str = None) -> dict:
    return {"tool": tool, "args": args or {}, "result": result, "error": error, "ref": ref}


def _sh(command: str, result: str = "", **kwargs) -> dict:
    """A Codex shell call."""
    return _call("exec_command", {"cmd": command}, result, **kwargs)


def _traj(calls: list, subagents: tuple = (), prefix: str = "call_",
          trajectory_id: str = None) -> dict:
    """An ATIF trajectory with one agent step per call, each with its observation."""
    steps = []
    for k, c in enumerate(calls, 1):
        call_id = f"{prefix}{k}"
        result = {"source_call_id": call_id, "content": c["result"]}
        if c["error"] is not None:
            result["extra"] = {"is_error": c["error"]}
        if c["ref"]:
            result["subagent_trajectory_ref"] = [{"trajectory_id": c["ref"]}]
        steps.append({"step_id": k, "source": "agent", "message": "",
                      "tool_calls": [{"tool_call_id": call_id, "function_name": c["tool"],
                                      "arguments": c["args"]}],
                      "observation": {"results": [result]}})
    out = {"steps": steps, "subagent_trajectories": list(subagents)}
    if trajectory_id:
        out["trajectory_id"] = trajectory_id
    return out


def _mid(command: str, tool: str = "exec_command", **args) -> str:
    key = "cmd" if tool == "exec_command" else "command"
    return taxonomy.mid_level({"function_name": tool, "arguments": dict(args, **{key: command})})


def _edits(command: str, **args) -> list:
    return taxonomy.edited_files({"function_name": "exec_command",
                                  "arguments": dict(args, cmd=command)})


def _shape(result: dict) -> list:
    """(start, end, type, outcome, host purpose, flags) per segment."""
    return [((s["start"], s["end"]), s["type"], s["outcome"], s["purpose_host"],
             sorted(s["flags"])) for s in result["segments"]]


SRC = "app/src/main/java/com/x/Foo.java"
PATCH = (f"apply_patch <<'PATCH'\n*** Begin Patch\n*** Update File: {SRC}\n@@\n-  a();\n"
         "+  b() | c;\n*** End Patch\nPATCH")
TEST = "./gradlew testDebugUnitTest"
TEST_FAILS = ("com.x.FooTest > testBar FAILED\n    java.lang.AssertionError\n\n"
              "FAILURE: Build failed with an exception.\n\n* What went wrong:\n"
              "Execution failed for task ':app:testDebugUnitTest'.\n"
              "> There were failing tests. See the report at: file:///r/index.html\n\n"
              "BUILD FAILED in 4s\nProcess exited with code 1")
TEST_PASSES = ("> Task :app:testDebugUnitTest\n\nBUILD SUCCESSFUL in 6s\n"
               "4 actionable tasks: 4 executed\nProcess exited with code 0")
ENV_FAILS = ("* What went wrong:\nCould not determine java version from '24'.\n\n"
             "BUILD FAILED in 1s\nProcess exited with code 1")


# ----------------------------------------------------------------------------- invariants
@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class CorpusInvariantTests(unittest.TestCase):
    """Every trajectory of original/run1 segments without violating the contract."""

    def test_original_run1_partitions_cleanly(self):
        counted = collections.Counter()
        for key, _trajectory in _run1():
            result = _segmented(key.agent, key.bug)          # segment() checks the tree
            acts, tree = result["actions"], result["hierarchy"]
            steps = [x for p in tree["purposes"] for s in p["segments"] for x in s["steps"]]
            self.assertEqual(steps, list(range(1, len(acts) + 1)), corpus.traj_id(key))
            view_actions = [{"i": a["action_index"], "mid": a["mid_level"]} for a in acts]
            segment.check_hierarchy(tree, len(acts), view_actions, name=corpus.traj_id(key))
            for row in acts:
                self.assertIn(row["verdict"], verdict.VERDICTS)
                self.assertIn(row["fail_kind"], verdict.FAIL_KINDS + (None,))
                if row["edit_role"]:
                    self.assertIn(row["edit_role"], taxonomy.EDIT_ROLES)
            counted[key.agent] += 1
        self.assertEqual(dict(counted), {"claude": 50, "codex": 50, "qwen": 50})

    def test_every_tool_of_the_corpus_has_a_mapping(self):
        known = set(taxonomy.TOOL_MAP) | taxonomy.SHELL_TOOLS | set(taxonomy.WRAPPER_TOOLS)
        other = collections.Counter()
        total = collections.Counter()
        for key, _trajectory in _run1():
            for row in _segmented(key.agent, key.bug)["actions"]:
                self.assertIn(row["tool"], known, corpus.traj_id(key))
                total[key.agent] += 1
                other[key.agent] += row["mid_level"] == "other"
        for agent in corpus.AGENTS:
            self.assertLess(other[agent] / total[agent], 0.02, agent)

    def test_subagent_actions_stay_in_their_delegation(self):
        seen = collections.Counter()
        for key, _trajectory in _run1():
            result = _segmented(key.agent, key.bug)
            acts = result["actions"]
            owner = {x: j for j, s in enumerate(result["segments"]) for x in s["idx"]}
            calls = {a["delegates_to"]: k for k, a in enumerate(acts) if a.get("delegates_to")}
            for k, row in enumerate(acts):
                if row["scope"] == "main":
                    continue
                self.assertTrue(row["scope"].startswith("sub-"), corpus.traj_id(key))
                self.assertEqual(owner[k], owner[calls[row["scope"]]], corpus.traj_id(key))
                self.assertEqual(result["segments"][owner[k]]["kind"], "delegate")
                seen[key.agent] += 1
        self.assertGreater(seen["claude"], 0)

    def test_every_passing_trajectory_edits_the_source(self):
        """APR pass means the source was patched, by a tool or from the shell."""
        table = outcomes.load(DATASET)
        for key, _trajectory in _run1():
            if table.get((key.agent, key.config, key.run, key.bug)):
                self.assertIsNotNone(_segmented(key.agent, key.bug)["first_source_edit"],
                                     corpus.traj_id(key))

    def test_checker_rejects_a_gap_and_an_unknown_type(self):
        tree = {"purposes": [{"id": "p1", "label": "repair", "start": 1, "end": 3, "segments": [
            {"id": "s1", "type": "fix_attempt_passed", "kind": "fix_attempt",
             "purpose": "repair", "outcome": "succeeded", "start": 1, "end": 1,
             "steps": [1], "flags": []},
            {"id": "s2", "type": "invented_type", "kind": "exec", "purpose": "repair",
             "outcome": "succeeded", "start": 3, "end": 3, "steps": [3], "flags": []}]}],
            "loops": [{"type": "stuck_segment", "ended": "failed", "segment_ids": ["s9"]}]}
        with self.assertRaises(ValueError) as caught:
            segment.check_hierarchy(tree, 3)
        message = str(caught.exception)
        self.assertIn("starts at 3, expected 2", message)
        self.assertIn("invented_type", message)
        self.assertIn("unknown segment s9", message)

    def test_vocabulary_is_closed(self):
        self.assertNotIn("planning", taxonomy.PHASES)
        self.assertEqual(segment.VOCAB["purposes"],
                         ["orientation", "localization", "reproduction", "environment",
                          "repair", "validation", "review"])


# ----------------------------------------------------------------------------- vocabularies
class VocabularyTests(unittest.TestCase):
    """The agent tables: every tool of the corpus maps to a mid-level type."""

    def _mid(self, tool: str, **args) -> str:
        return taxonomy.mid_level({"function_name": tool, "arguments": args})

    def test_qwen_tools(self):
        cases = {"read_file": "read_file", "grep_search": "search_code", "glob": "search_code",
                 "edit": "edit_file", "write_file": "edit_file", "agent": "delegate",
                 "list_agents": "wait_process", "send_message": "wait_process",
                 "task_stop": "wait_process", "update_goal": "plan", "get_goal": "plan",
                 "tool_search": "other", "skill": "other", "record_artifact": "other",
                 "zoom_image": "other", "run_shell": "other", "try_shell_command": "other",
                 "list_files": "other"}
        for tool, mid in cases.items():
            self.assertEqual(self._mid(tool), mid, tool)
        self.assertEqual(self._mid("run_shell_command", command="./gradlew assembleDebug"),
                         "build")

    def test_claude_and_codex_tools(self):
        cases = {"Read": "read_file", "Edit": "edit_file", "Write": "edit_file",
                 "Agent": "delegate", "TaskOutput": "wait_process", "TaskStop": "wait_process",
                 "Monitor": "wait_process", "ToolSearch": "other", "write_stdin": "wait_process",
                 "update_plan": "plan", "view_image": "other", "apply_patch": "edit_file"}
        for tool, mid in cases.items():
            self.assertEqual(self._mid(tool), mid, tool)
        self.assertEqual(self._mid("Bash", command="git diff"), "vcs")
        self.assertEqual(self._mid("exec_command", cmd="rg -n Foo app/src"), "search_code")

    def test_gemini_is_gone(self):
        self.assertNotIn("gemini", corpus.AGENTS)
        for tool in ("generalist", "replace", "read_many_files", "list_directory",
                     "search_file_content", "google_web_search", "web_fetch", "save_memory"):
            self.assertEqual(self._mid(tool), "other", tool)

    def test_tool_call_bridge_is_labelled_as_the_tool_it_ran(self):
        call = {"function_name": "tool_call",
                "arguments": {"name": "send_message",
                              "arguments": {"task_id": "Explore-call_1", "message": "status?"}}}
        self.assertEqual(taxonomy.mid_level(call), "wait_process")
        self.assertEqual(taxonomy.action_target(call), "status?")
        shell = {"function_name": "tool_call",
                 "arguments": {"name": "run_shell_command", "arguments": {"command": TEST}}}
        self.assertEqual(taxonomy.mid_level(shell), "run_test")
        self.assertEqual(taxonomy.shell_command(shell), TEST)
        self.assertEqual(taxonomy.mid_level({"function_name": "tool_call",
                                             "arguments": {"query": "x"}}), "other")

    def test_unknown_and_garbled_tools_are_other(self):
        for tool in ("some_new_tool_2030", 'grep -n "x" a.java\n</parameter>'):
            self.assertEqual(self._mid(tool), "other")


# ----------------------------------------------------------------------------- shell edits
class ShellEditTests(unittest.TestCase):
    """Edits made from the shell: recognised when they write a project file in the
    checkout, never for read-only commands, scratch files or non-project files."""

    def test_writes_into_the_project_are_edits(self):
        cases = {
            f"cat > {SRC} <<'EOF'\nclass Foo {{}}\nEOF": [SRC],
            f"cat <<'EOF' > {SRC}\nclass Foo {{}}\nEOF": [SRC],
            f"echo '' >> {SRC}": [SRC],
            f"printf 'x' | tee {SRC}": [SRC],
            f"sed -i 's/a/b/' {SRC}": [SRC],
            f"sed -i '' 's/a/b/' {SRC} && sed -n '1,5p' {SRC}": [SRC],
            f"perl -0pi -e 's/a/b/g' {SRC} && grep -n b {SRC}": [SRC],
            f"perl -i -ne 'print unless $. == 4' {SRC}": [SRC],
            f"python3 - <<'EOF'\np='{SRC}'\ns=open(p).read()\nopen(p,'w').write(s)\nEOF": [SRC],
            f"python3 -c \"from pathlib import Path; Path('{SRC}').write_text('x')\"": [SRC],
            "cd /h/runs/qwen_original_run1/bug-84 && sed -i 's/0/1/g' u/src/A.java u/src/B.java":
                ["u/src/A.java", "u/src/B.java"],
            "python3 - <<'EOF'\nwith open('/v/runs/claude_original_run3/bug-2677/app/res/a.xml',"
            " 'w') as f:\n    f.write('x')\nEOF":
                ["/v/runs/claude_original_run3/bug-2677/app/res/a.xml"],
            PATCH: [SRC],
            "{ printf '%s\\n' '*** Begin Patch' '*** Update File: app/src/main/res/values/s.xml'"
            " '@@'; sed -n '18,43s/^/-/p' x; } | apply_patch": ["app/src/main/res/values/s.xml"],
        }
        for command, files in cases.items():
            self.assertEqual(_mid(command), "edit_file", command)
            self.assertEqual(_edits(command), files, command)

    def test_patch_tools_are_edits_with_unknown_files(self):
        for command in ("patch -p1 < fix.patch", "git apply fix.patch",
                        "grep -rl foo app/src | xargs sed -i 's/foo/bar/'"):
            self.assertEqual(_mid(command), "edit_file", command)
            self.assertEqual(_edits(command), [], command)

    def test_read_only_commands_are_not_edits(self):
        cases = {f"cat {SRC}": "read_file", f"cat {SRC} 2>/dev/null": "read_file",
                 f"sed -n '1,220p' {SRC}": "read_file", f"sed 's/a/b/' {SRC}": "read_file",
                 f"grep -n Foo {SRC}": "search_code", f"perl -ne 'print if /a/' {SRC}": "run_shell",
                 "python3 - <<'EOF'\nprint(open('a.xml').read())\nEOF": "run_shell",
                 "git apply --check fix.patch": "vcs",
                 "patch -p1 --dry-run < fix.patch": "run_shell",
                 "git show HEAD:app/A.java > /tmp/orig.java": "vcs",
                 f"rg -n '\\*\\*\\* Update File: {SRC}' notes.txt": "search_code"}
        for command, mid in cases.items():
            self.assertEqual(_mid(command), mid, command)
            self.assertEqual(_edits(command), [], command)

    def test_scratch_and_non_project_writes_are_not_edits(self):
        cases = {"cat > /tmp/T.java <<'EOF'\nclass T {}\nEOF": "env_setup",
                 "sed -i 's/a/b/' /tmp/X.java": "env_setup",
                 "sed -i 's|a/app|app|g' bug-1215-fix.patch": "env_setup",
                 "cd /tmp/t171 && perl -pi -e 's/x/y/' T.java": "env_setup",
                 "cd /v/runs/claude_original_run3/bug-54/.sim && cat > src/A.java <<'EOF'\nx\nEOF":
                     "env_setup",
                 "cat > .verify/prefs.xml <<'EOF'\nx\nEOF": "env_setup",
                 "echo hi > notes.txt": "run_shell",
                 "./gradlew testDebugUnitTest 2>&1 | tee build.log": "run_test",
                 "cd /tmp/a && patch -p1 < /tmp/fix.patch": "env_setup"}
        for command, mid in cases.items():
            self.assertEqual(_mid(command), mid, command)
            self.assertEqual(_edits(command), [], command)
        self.assertEqual(_edits(f"sed -i 's/a/b/' {SRC}", workdir="/tmp/scratch"), [])
        self.assertEqual(_edits(f"sed -i 's/a/b/' {SRC}",
                                workdir="/u/runs/codex_original_run1/bug-44"), [SRC])

    def test_a_patch_and_its_run_in_one_command_anchor_the_phases(self):
        """Codex 0.138 often patches and tests in one call; the call keeps the mid-level of
        its run, carries the edit, and is the phase anchor."""
        rows = taxonomy.annotate(_traj([_sh("rg -n Foo app/src"),
                                        _sh(PATCH + "\n" + TEST, TEST_PASSES)]))
        self.assertEqual([(r["mid_level"], r["edit_role"]) for r in rows],
                         [("search_code", ""), ("run_test", "source")])
        self.assertEqual(rows[1]["edit_files"], [SRC])
        self.assertEqual(taxonomy.first_source_edit(rows), 1)

    @unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
    def test_real_shell_edits(self):
        rows = _segmented("codex", "44")["actions"]
        self.assertEqual((rows[7]["mid_level"], rows[7]["edit_role"]), ("run_test", "source"))
        package = "it/feio/android/omninotes/utils/"
        self.assertEqual(rows[7]["edit_files"],
                         [f"omniNotes/src/main/java/{package}TagsHelper.java",
                          f"omniNotes/src/test/java/{package}TagsHelperTest.java"])
        self.assertEqual(_segmented("codex", "44")["first_source_edit"], 8)
        result = _segmented("claude", "1640", run=2)
        self.assertEqual((result["actions"][7]["mid_level"], result["actions"][7]["edit_files"]),
                         ("edit_file", ["app/src/main/res/values/strings.xml"]))
        self.assertEqual(result["first_source_edit"], 8)
        result = _segmented("qwen", "1568")
        self.assertEqual(result["first_source_edit"], 5)
        self.assertEqual([result["actions"][i - 1]["mid_level"] for i in (5, 15, 21, 22)],
                         ["edit_file", "run_shell", "edit_file", "edit_file"])
        self.assertEqual(result["actions"][21]["edit_files"],
                         ["app/src/main/java/io/lerk/lrkFM/adapter/FileArrayAdapter.java"])


# ----------------------------------------------------------------------------- delegation
class DelegationTests(unittest.TestCase):
    """R3a: a delegate call and every action spliced in after it are one block; a
    read-only sub-agent never makes it an edit delegation."""

    PROMPT = ("I need to find the code that shows the Undo snackbar. The fix should make "
              "the queue update its list.")

    def _claude(self, kind: str = "Explore", nested: bool = False) -> dict:
        inner = _traj([_call("Read", {"file_path": SRC}, "x")], prefix="n_",
                      trajectory_id="sub-s_2")
        sub_calls = [_call("Bash", {"command": "rg -n Undo app/src"}, "x")]
        if nested:
            sub_calls.append(_call("Agent", {"prompt": "read Foo", "subagent_type": "Explore"},
                                   "done", ref="sub-s_2"))
        sub = _traj(sub_calls + [_call("Read", {"file_path": SRC}, "x")], prefix="s_",
                    trajectory_id="sub-call_2", subagents=(inner,) if nested else ())
        return _traj([_call("Bash", {"command": "ls"}, "app"),
                      _call("Agent", {"description": "Find", "prompt": self.PROMPT,
                                      "subagent_type": kind}, "report", ref="sub-call_2"),
                      _call("Read", {"file_path": SRC}, "x")], subagents=(sub,))

    def test_subagent_actions_are_spliced_after_their_call(self):
        rows = taxonomy.actions(self._claude())
        self.assertEqual([(r["scope"], r["tool"]) for r in rows],
                         [("main", "Bash"), ("main", "Agent"), ("sub-call_2", "Bash"),
                          ("sub-call_2", "Read"), ("main", "Read")])
        result = segment.segment(self._claude(), "1")
        self.assertEqual([((s["start"], s["end"]), s["kind"], s["purpose"])
                          for s in result["segments"]],
                         [((1, 1), "explore", "orientation"), ((2, 4), "delegate", "localization"),
                          ((5, 5), "explore", "localization")])
        self.assertEqual(result["segments"][1]["label"],
                         "Delegated exploration (2 sub-agent actions)")

    def test_nested_delegation_is_one_block(self):
        result = segment.segment(self._claude(nested=True), "1")
        self.assertEqual([r["scope"] for r in result["actions"]],
                         ["main", "main", "sub-call_2", "sub-call_2", "sub-s_2", "sub-call_2",
                          "main"])
        self.assertEqual([((s["start"], s["end"]), s["kind"]) for s in result["segments"]],
                         [((1, 1), "explore"), ((2, 6), "delegate"), ((7, 7), "explore")])

    def test_read_only_subagents_never_edit(self):
        explore = segment.segment(self._claude("Explore"), "1")["segments"][1]
        general = segment.segment(self._claude("general-purpose"), "1")["segments"][1]
        self.assertEqual((explore["purpose"], explore["type"]),
                         ("localization", "delegated_exploration"))
        self.assertEqual((general["purpose"], general["type"]), ("repair", "delegated_edit"))
        self.assertFalse(segment.delegated_edit({"args": {"prompt": self.PROMPT,
                                                          "subagent_type": "Explore"}}))
        self.assertTrue(segment.delegated_edit({"args": {"prompt": "Update 4 Java files to "
                                                                    "implement X",
                                                          "subagent_type": "fork"}}))
        self.assertFalse(segment.delegated_edit({"args": {"prompt": "Search the code for X"}}))

    def test_background_agent_without_logged_steps_is_an_opaque_delegate(self):
        """Qwen Code's background sub-agents stream only their prompt (known gap
        ``subagent_internals_not_streamed``): the delegation is the call alone."""
        sub = {"trajectory_id": "sub-call_1",
               "steps": [{"step_id": 1, "source": "user", "message": self.PROMPT}]}
        trajectory = _traj([_call("agent", {"description": "Explore", "prompt": self.PROMPT,
                                            "subagent_type": "Explore"},
                                  "Background agent launched", ref="sub-call_1"),
                            _call("list_agents", {}, "Listed 1 background agent."),
                            _call("send_message", {"task_id": "Explore-call_1",
                                                   "message": "Send your findings now."},
                                  "Message queued for Explore"),
                            _call("read_file", {"file_path": "/r/runs/q_run1/bug-1/" + SRC}, "x")],
                           subagents=(sub,))
        result = segment.segment(trajectory, "1")
        self.assertEqual([r["mid_level"] for r in result["actions"]],
                         ["delegate", "wait_process", "wait_process", "read_file"])
        first = result["segments"][0]
        self.assertEqual((first["kind"], first["n"], first["purpose"]),
                         ("delegate", 1, "localization"))


# ----------------------------------------------------------------------------- whole rules
class WorkedExampleTests(unittest.TestCase):
    """One synthetic Codex trajectory through every level: plan, locate, reproduce, a failed
    fix attempt, a look-up between attempts, a passing fix attempt, the diff, the plan."""

    def setUp(self):
        other = SRC.replace("Foo", "Bar")
        self.result = segment.segment(_traj([
            _call("update_plan", {"plan": [{"step": "find", "status": "in_progress"}]}, "ok"),
            _sh("rg -n Foo app/src", SRC + ":10: Foo"),
            _sh(f"sed -n '1,80p' {SRC}", "class Foo {}"),
            _sh(TEST, TEST_FAILS),
            _sh(PATCH, "Success. Updated the following files:\nM " + SRC),
            _sh(TEST, TEST_FAILS),
            _sh(f"sed -n '1,40p' {SRC}", "class Foo {}"),
            _sh(f"sed -n '1,40p' {other}", "class Bar {}"),
            _sh(PATCH, "Success. Updated the following files:\nM " + SRC),
            _sh(TEST, TEST_PASSES),
            _sh("git diff", "diff --git a/x b/x"),
            _call("update_plan", {"plan": [{"step": "find", "status": "completed"}]}, "ok"),
        ]), "1")

    def test_segments(self):
        self.assertEqual(_shape(self.result), [
            ((1, 3), "targeted_lookup", "completed", "localization", []),
            # a failing run also sets the log's error flag: tool_errors (R8)
            ((4, 4), "reproduction_succeeded", "succeeded", "reproduction", ["tool_errors"]),
            ((5, 6), "fix_attempt_failed", "failed", "repair",
             ["retried_after_detour", "tool_errors"]),
            ((7, 8), "targeted_lookup", "completed", "repair", []),       # nested (R9a)
            ((9, 10), "fix_attempt_passed", "succeeded", "repair", []),
            ((11, 11), "review_patch", "completed", "review", []),
            ((12, 12), "orientation_planning", "completed", "orientation", []),
        ])
        self.assertEqual(self.result["first_source_edit"], 5)

    def test_purposes_phases_and_loops(self):
        self.assertEqual([(p["label"], p["start"], p["end"])
                          for p in self.result["hierarchy"]["purposes"]],
                         [("localization", 1, 3), ("reproduction", 4, 4), ("repair", 5, 10),
                          ("review", 11, 11), ("orientation", 12, 12)])
        loops = self.result["hierarchy"]["loops"]
        self.assertEqual([(l["type"], l["start"], l["end"], l["iterations"],
                           l["failed_iterations"], l["ended"], l["segment_ids"]) for l in loops],
                         [("fix_verify_loop", 5, 10, 2, 1, "passed", ["s3", "s4", "s5"])])


class StuckRuleTests(unittest.TestCase):
    """Fix 1: stuck = the same full command failing again with the same error, unchanged."""

    def _run_cmd(self, command: str) -> str:
        return segment.run_cmd({"cmd": command, "tool": "exec_command", "args": {}})

    def test_env_assignments_are_kept_and_only_output_filters_dropped(self):
        a = self._run_cmd("GRADLE_USER_HOME=/tmp/g1 ./gradlew assembleDebug")
        b = self._run_cmd("GRADLE_USER_HOME=/tmp/g2 ./gradlew assembleDebug")
        self.assertNotEqual(a, b)
        self.assertEqual(self._run_cmd(f"{TEST} 2>&1 | tail -30"),
                         self._run_cmd(f"{TEST}  2>&1 | grep -A 5 \"Assert|Err\""))
        self.assertNotEqual(self._run_cmd("export JAVA_HOME=$(/usr/libexec/java_home -v 11) && ./gradlew test"),
                            self._run_cmd("export JAVA_HOME=$(/usr/libexec/java_home -v 17) && ./gradlew test"))

    def test_splitting_respects_quotes_substitutions_and_heredocs(self):
        self.assertEqual([s for s, _ in taxonomy.split_commands('grep -E "A|B" x.log | tail -5')],
                         ['grep -E "A|B" x.log', "tail -5"])
        self.assertEqual(len(taxonomy.split_commands(
            "export JAVA_HOME=$(/usr/libexec/java_home -v 17 | head -1) && ./gradlew build")), 2)
        patch = "apply_patch <<'PATCH'\n*** Begin Patch\n+a(); b() | c;\n*** End Patch\nPATCH\nls"
        self.assertEqual([s.split("\n")[0] for s, _ in taxonomy.split_commands(patch)],
                         ["apply_patch <<'PATCH'", "ls"])

    def test_identical_rerun_with_identical_error_is_stuck(self):
        result = segment.segment(_traj([_sh("rg -n Foo app/src", "x"),
                                        _sh("./gradlew assembleDebug", ENV_FAILS),
                                        _sh("./gradlew assembleDebug", ENV_FAILS)]), "1")
        s = result["segments"][1]
        self.assertEqual(((s["start"], s["end"]), s["outcome"], s["type"]),
                         ((2, 3), "looped", "stuck_repeating_failure"))
        self.assertIn("stuck_repeating_command", s["flags"])
        self.assertEqual([l["type"] for l in result["hierarchy"]["loops"]], ["stuck_segment"])

    def test_changed_env_prefix_is_env_wrestling_not_stuck(self):
        fails = "error: no toolchain\nProcess exited with code 1"
        result = segment.segment(_traj([
            _sh(f"GRADLE_USER_HOME=/tmp/g{k} ./gradlew assembleDebug", fails) for k in (1, 2, 3)]),
            "1")
        s = result["segments"][0]
        self.assertEqual((s["outcome"], s["fail_kinds"]), ("failed", {"exit": 3}))
        self.assertNotIn("stuck_repeating_command", s["flags"])
        self.assertIn("env_wrestling", s["flags"])

    def test_polls_of_one_background_run_are_one_run(self):
        result = segment.segment(_traj([
            _sh(TEST, "Process running with session ID 7"),
            _call("write_stdin", {"session_id": 7, "chars": ""},
                  "Process running with session ID 7"),
            _call("write_stdin", {"session_id": 7, "chars": ""}, TEST_FAILS),
            _call("write_stdin", {"session_id": 7, "chars": ""}, TEST_FAILS)]), "1")
        acts = result["actions"]
        self.assertEqual([a["waits_on"] for a in acts], [None, 1, 1, 1])
        self.assertEqual([a["verdict"] for a in acts], ["none", "none", "fail", "fail"])
        self.assertEqual(len(result["segments"]), 1)
        self.assertNotIn("stuck_repeating_command", result["segments"][0]["flags"])
        self.assertEqual(result["segments"][0]["type"], "reproduction_succeeded")

    def test_a_change_between_the_runs_breaks_the_repeat(self):
        acts = [{"mid_level": m, "run_key": k, "key": k, "end": i, "pos": i}
                for i, (m, k) in enumerate([("run_test", "x"), ("env_setup", "rm"), ("run_test", "x")])]
        runs = [{"pos": 0, "end": 0, "run_key": "x", "key": "x", "sig": "env:e"},
                {"pos": 2, "end": 2, "run_key": "x", "key": "x", "sig": "env:e"}]
        self.assertEqual(segment.strict_repeats(acts, runs), ({}, 1))
        acts[1]["mid_level"] = "read_file"
        self.assertEqual(segment.strict_repeats(acts, runs), ({"x": 2}, 0))

    def test_different_error_signature_is_progress(self):
        a = verdict.error_signature("* What went wrong:\nPlugin [id: 'x'] not found", "env")
        b = verdict.error_signature("* What went wrong:\nCould not determine java version", "env")
        c = verdict.error_signature("* What went wrong:\nPlugin [id: 'x'] not found\n/tmp/a1/b", "env")
        self.assertNotEqual(a, b)
        self.assertEqual(a, c)


class ReproductionTests(unittest.TestCase):
    """Fix 2: a test failing before the first source edit is a reproduction."""

    def setUp(self):
        self.trajectory = _traj([_call("Bash", {"command": "rg -n Foo app/src"}, SRC),
                                 _call("Bash", {"command": TEST}, TEST_FAILS),
                                 _call("Edit", {"file_path": "/v/runs/c_run1/bug-1/" + SRC,
                                                "old_string": "a", "new_string": "b"}, "ok"),
                                 _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.result = segment.segment(self.trajectory, "1")

    def test_pre_anchor_test_failure_is_a_reproduction(self):
        self.assertEqual(_shape(self.result), [
            ((1, 1), "targeted_lookup", "completed", "localization", []),
            ((2, 2), "reproduction_succeeded", "succeeded", "reproduction", ["tool_errors"]),
            ((3, 4), "fix_attempt_passed", "succeeded", "repair", []),
        ])
        self.assertEqual(self.result["segments"][1]["outcome_detail"], "reproduced")

    def test_badge_agrees_with_segments(self):
        badges, steps = outcomes.badges(self.trajectory, self.result["actions"],
                                        self.result["first_source_edit"])
        self.assertTrue(badges["reproduced_before_fix"])
        self.assertEqual(steps["reproduced_before_fix"], [2])
        self.assertEqual(badges["last_test_verdict"], "pass")


class CodebookTests(unittest.TestCase):
    """The tool applies the codebook: types by Q1-Q11 in order (§3.3), and K1 keeps a single
    lookup between an edit and its judging run inside the attempt (§3.2)."""

    def test_executed_test_decides_the_type_before_toolchain_work(self):
        # Q4 before Q6: a toolchain edit followed by the failing test is a reproduction
        result = segment.segment(_traj([
            _call("Edit", {"file_path": "app/build.gradle", "old_string": "a", "new_string": "b"}),
            _call("Bash", {"command": TEST}, TEST_FAILS)]), "1")
        s = result["segments"][0]
        self.assertEqual((s["kind"], s["type"], s["purpose"], s["flags"]),
                         ("toolchain_fix", "reproduction_succeeded", "reproduction",
                          ["edits_toolchain", "tool_errors"]))
        self.assertIsNone(result["first_source_edit"])

    def test_single_lookup_stays_inside_the_attempt(self):
        result = segment.segment(_traj([
            _call("Edit", {"file_path": SRC, "old_string": "a", "new_string": "b"}),
            _call("Bash", {"command": "rg -n Foo app/build"}, "x"),
            _call("Bash", {"command": TEST}, TEST_PASSES)]), "1")
        self.assertEqual([(s["start"], s["end"], s["type"]) for s in result["segments"]],
                         [(1, 3, "fix_attempt_passed")])


class VerdictTests(unittest.TestCase):
    def test_run_test_pass_needs_test_evidence(self):
        """Fix 3: ``./gradlew test | head -60`` can cut the output before the result."""
        self.assertEqual(verdict.verdict("run_test", "BUILD SUCCESSFUL in 3s"),
                         ("none", None, "no_test_evidence"))
        self.assertEqual(verdict.verdict("build", "BUILD SUCCESSFUL in 3s")[0], "pass")
        self.assertEqual(verdict.verdict("run_test", "Process exited with code 0")[0], "none")
        for text in ("=== Results: 5 passed, 0 failed ===", ">>> Script18: PASSED",
                     "OK (1 test)", "Tests run: 3,  Failures: 0"):
            self.assertEqual(verdict.verdict("run_test", text)[0], "pass", text)
        self.assertEqual(verdict.verdict("wait_process", "BUILD SUCCESSFUL",
                                         effective_mid="run_test")[0], "none")

    def test_gradle_unit_test_task_counts_as_evidence(self):
        self.assertEqual(verdict.verdict("run_test", "> Task :omniNotes:testFossDebugUnitTest\n\n"
                                         "BUILD SUCCESSFUL in 9s"), ("pass", None, "gradle_tests"))

    def test_only_executing_actions_get_a_verdict(self):
        """Fix 4: reads, searches and git print the same markers (``cat build.log``,
        ``git diff``, ``grep`` over old logs)."""
        for mid in ("vcs", "read_file", "search_code", "orient", "edit_file", "delegate"):
            self.assertEqual(verdict.verdict(mid, "OK (1 test)\nResults: 1 passed, 0 failed"),
                             ("none", None, ""), mid)

    @unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
    def test_reads_of_build_output_get_no_verdict_in_the_corpus(self):
        seen = 0
        for key, _trajectory in _run1():
            for row in _segmented(key.agent, key.bug)["actions"]:
                if row["mid_level"] in ("vcs", "read_file", "search_code") and \
                        ("BUILD FAILED" in row["result"] or "BUILD SUCCESSFUL" in row["result"]):
                    seen += 1
                    self.assertEqual(row["verdict"], "none")
        self.assertGreater(seen, 0, "expected reads of build output carrying verdict markers")

    def test_failure_kinds(self):
        self.assertEqual(verdict.verdict("run_test", ">>> Script1: FAILED")[:2], ("fail", "test"))
        self.assertEqual(verdict.verdict("run_test", TEST_FAILS)[:2], ("fail", "test"))
        self.assertEqual(verdict.verdict("build", "* What went wrong:\nExecution failed for task "
                                         "':app:compileDebugJavaWithJavac'.\n> Compilation failed")[:2],
                         ("fail", "build"))
        self.assertEqual(verdict.verdict("build", ENV_FAILS)[:2], ("fail", "env"))
        self.assertEqual(verdict.verdict("run_test", "Results: 0 passed, 0 failed")[:2],
                         ("fail", "env"))

    def test_exit_status_lines_of_each_agent(self):
        self.assertEqual(verdict.verdict("build", "Process exited with code 0")[0], "pass")
        qwen = ("Command: ./gradlew assembleDebug | grep -E \"BUILD FAILED|error:\"\n"
                "Directory: (root)\nOutput: (empty)\nError: (none)\nExit Code: {}\n"
                "Signal: (none)\nProcess Group PGID: 12")
        # the echoed command is the agent's text: its "BUILD FAILED" is not a build failure
        self.assertEqual(verdict.verdict("build", qwen.format(0)), ("pass", None, "exit"))
        self.assertEqual(verdict.verdict("build", qwen.format(1)), ("fail", "exit", "exit"))
        self.assertEqual(verdict.verdict("run_shell", "Command exited with code: 2")[:2],
                         ("fail", "exit"))

    def test_error_signature_ignores_the_qwen_envelope(self):
        envelope = ("Command: git show HEAD:{}\nDirectory: (root)\nOutput: fatal: path "
                    "'x' exists on disk\nError: (none)\nExit Code: 128\nSignal: (none)\n"
                    "Process Group PGID: {}")
        a = verdict.error_signature(envelope.format("a.gradle", 1), "exit")
        b = verdict.error_signature(envelope.format("b.gradle", 2), "exit")
        self.assertEqual(a, b)
        self.assertNotIn("Command", a)


class TaxonomyFixTests(unittest.TestCase):
    """Fix 5 and fix 6."""

    def test_apply_patch_heredoc_is_an_edit_with_its_files(self):
        command = ("apply_patch <<'PATCH'\n*** Begin Patch\n*** Update File: app/src/main/A.java\n"
                   "@@\n-x;\n+y | z;\n*** Add File: app/src/main/B Space.java\n+q\n*** End Patch\nPATCH")
        self.assertEqual(_mid(command), "edit_file")
        self.assertEqual(_edits(command), ["app/src/main/A.java", "app/src/main/B Space.java"])
        rows = taxonomy.annotate(_traj([_sh("rg -n x app"), _sh(command, "Success.")]))
        self.assertEqual((rows[1]["mid_level"], rows[1]["edit_role"]), ("edit_file", "source"))
        self.assertEqual(taxonomy.first_source_edit(rows), 1)

    def test_gradle_test_tasks_are_test_runs(self):
        self.assertEqual(_mid("./gradlew :omniNotes:testFossDebugUnitTest 2>&1 | tail -20"),
                         "run_test")
        self.assertEqual(_mid("./gradlew :app:connectedReleaseFlavorDebugAndroidTest"), "run_test")
        self.assertEqual(_mid("./gradlew assemble assembleAndroidTest"), "build")
        self.assertEqual(_mid("./gradlew :app:compileDebugAndroidTestJavaWithJavac"), "build")
        self.assertEqual(_mid(f"cd /h/runs/qwen_original_run1/bug-18 && {TEST} 2>&1 | tail -60",
                              tool="run_shell_command"), "run_test")
        # an assignment whose $(...) holds spaces is still a prefix, not the program
        self.assertEqual(_mid("JAVA_HOME=$(/usr/libexec/java_home -v 1.8) ./gradlew clean "
                              "assembleDebug 2>&1 | tail -30", tool="Bash"), "build")

    def test_bash_c_scripts_and_quoted_alternations(self):
        self.assertEqual(_mid("bash -lc 'export X=1; ./run_pipeline.sh Script1'"), "run_test")
        self.assertEqual(_mid('rg -n "jenv|gradle|androidTest" run_pipeline.sh'), "search_code")
        self.assertEqual(_edits(f"bash -lc \"sed -i 's/a/b/' {SRC}\""), [SRC])

    def test_edit_roles(self):
        self.assertEqual(taxonomy.file_role("/x/buggy/bug-18/Calendula/build.gradle"), "toolchain")
        self.assertEqual(taxonomy.file_role("run_pipeline.sh"), "toolchain")
        self.assertEqual(taxonomy.file_role("reproducing_script_project/app/src/androidTest/"
                                            "java/S18.java"), "test")
        self.assertEqual(taxonomy.file_role("reproducing_script_project/app/build.gradle"),
                         "toolchain")
        self.assertEqual(taxonomy.file_role("app/src/test/java/com/x/FooTest.java"), "test")
        self.assertEqual(taxonomy.file_role("/Users/u/test/buggy/bug-7/app/src/main/A.java"),
                         "source")

    @unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
    def test_annotation_rows_carry_the_phase_taxonomy(self):
        rows = tar.iterations(_trajectory("codex", "44"), bug_id="44", agent="codex")
        for column in ("category", "file_role", "phase", "own_phase", "subphase",
                       "subphase_outcome", "attempt", "verdict", "fail_kind"):
            self.assertIn(column, tar.AUTO_COLUMNS)
            self.assertIn(column, rows[0])
        for column in ("mid_level", "high_level", "edit_role"):        # the v2 ladder is gone
            self.assertNotIn(column, rows[0])
        for column in tar.MANUAL_COLUMNS:
            self.assertEqual(rows[0][column], "")
        # action 8 applies a patch to TagsHelper.java and its test, then runs the tests
        self.assertEqual((rows[7]["file_role"], rows[7]["phase"], rows[7]["attempt"]),
                         ("source, test", "repair", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
