"""Phase lookup tests (``atif.phase``, ``atif.lookup``, ``taxonomy.kind``).

Each row of the Final lookup tables' phase table (``Parser/Phase taxonomy.md``) is pinned on a
small synthetic trajectory built with the helpers of ``test_segment``; the action and target
tables on single calls and paths; the invariant test phases every trajectory of ``Dataset/``
original/run1, parsed from the raw logs.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import unittest

from atif import baselines, lookup, phase, project, rules, segment, taxonomy
from tests.test_segment import (ENV_FAILS, HAVE_DATASET, PATCH, SRC, TEST, TEST_FAILS,
                                TEST_PASSES, _call, _run1, _sh, _traj)

OTHER = "app/src/main/java/com/x/Bar.java"
BUILD = "./gradlew assembleDebug"
BUILD_PASSES = "> Task :app:assembleDebug\n\nBUILD SUCCESSFUL in 9s\nProcess exited with code 0"


def _edit(path: str = SRC) -> dict:
    return _call("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}, "ok")


def _read(path: str = SRC) -> dict:
    return _call("Read", {"file_path": path}, "class Foo {}")


def _outline(result: dict) -> list:
    """(phase, [(outcome, evidence, start, end, n_events), ...]) per phase span."""
    return [(s["phase"], [(sp["outcome"], sp["evidence"], sp["start"], sp["end"], sp["n_events"])
                          for sp in s["subphases"]]) for s in result["phases"]]


def _flags(result: dict, span: int = -1, sub: int = -1) -> list:
    return result["phases"][span]["subphases"][sub]["flags"]


def _phased(calls: list, **options) -> dict:
    return phase.phases(_traj(calls), "1", **options)


# ----------------------------------------------------------------------------- invariants
@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class CorpusPhaseTests(unittest.TestCase):
    """Every trajectory of original/run1 satisfies the spec's invariants."""

    @classmethod
    def setUpClass(cls):
        cls.results = [(key, phase.phases(t, key.bug)) for key, t in _run1()]

    def test_original_run1_satisfies_the_invariants(self):
        self.assertEqual(len(self.results), 150)        # check_hierarchy ran on each

    def test_phase_counts_add_up_to_tool_actions(self):
        for key, r in self.results:
            m = r["metrics"]
            self.assertEqual(sum(m[f"{p}_actions"] for p in phase.PHASES), m["tool_actions"],
                             key)

    def test_the_tables_leave_at_most_one_percent_to_their_catch_alls(self):
        # other is a category of the table (write_stdin, sleep, curl); what must stay rare is
        # a step no entry names: "any other tool" or "any other program"
        for agent in ("claude", "codex", "qwen"):
            items = [a["lookup_item"] for key, r in self.results if key.agent == agent
                     for a in r["actions"]]
            rest = sum(i in ("any other tool", "any other program") for i in items)
            self.assertLessEqual(rest / len(items), 0.01, agent)

    def test_every_action_gets_a_category_and_a_phase_table_row(self):
        for key, r in self.results:
            self.assertTrue({a["category"] for a in r["actions"]} <= set(lookup.CATEGORIES), key)
            self.assertTrue(set(r["table_row"]) <= rules.BUILTIN_IDS, key)


class PhaseRuleTests(unittest.TestCase):
    """The phase table, one row or behaviour per test."""

    def test_reproduction_repair_and_validation(self):
        r = _phased([_call("Bash", {"command": f"sed -n 1,40p {OTHER}"}, "x"),
                     _call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(r), [
            ("localization", [("failed", "target_file", 1, 1, 1)]),
            ("reproduction", [("succeeded", "test", 2, 2, 1)]),
            ("repair", [("succeeded", "test", 3, 3, 1)]),
            ("validation", [("succeeded", "test", 4, 4, 1)])])
        self.assertEqual(r["table_row"], ["L5", "L6", "L8", "L12"])
        self.assertTrue(r["metrics"]["reproduced_before_fix"])

    def test_the_same_failing_test_succeeds_before_the_fix_and_fails_after(self):
        r = _phased([_call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual([(s["phase"], sp[0]) for s, (_, sps) in zip(r["phases"], _outline(r))
                          for sp in sps],
                         [("reproduction", "succeeded"), ("repair", "failed"),
                          ("validation", "failed")])

    def test_a_fix_verify_loop_alternates_repair_and_validation(self):
        # every run after the first fix is validation; the run decides its attempt too
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _read(OTHER), _edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(r), [
            ("repair", [("failed", "test", 1, 1, 1)]),
            ("validation", [("failed", "test", 2, 2, 1)]),
            ("localization", [("failed", "target_file", 3, 3, 1)]),
            ("repair", [("failed", "test", 4, 4, 1)]),
            ("validation", [("failed", "test", 5, 5, 1)]),
            ("repair", [("succeeded", "test", 6, 6, 1)]),
            ("validation", [("succeeded", "test", 7, 7, 1)])])
        self.assertEqual(r["phases"][0]["subphases"][0]["n_attempts"], 1)
        self.assertEqual((r["metrics"]["n_attempts"], r["metrics"]["n_failed_attempts"],
                          r["metrics"]["attempts_to_first_pass"]), (3, 2, 3))

    def test_a_patch_that_does_not_compile_fails_with_build_evidence(self):
        compile_error = ("Foo.java:3: error: cannot find symbol\nFAILURE: Build failed with "
                         "an exception.\n* What went wrong:\nExecution failed for task "
                         "':app:compileDebugJavaWithJavac'.\n> Compilation failed\n"
                         "BUILD FAILED in 2s\nProcess exited with code 1")
        r = _phased([_edit(), _call("Bash", {"command": BUILD}, compile_error)])
        self.assertEqual(_outline(r), [("repair", [("failed", "build", 1, 1, 1)]),
                                       ("validation", [("failed", "build", 2, 2, 1)])])

    def test_an_unchanged_rerun_of_the_same_failure_is_flagged(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("repair", [("failed", "test", 1, 1, 1)]),
                                       ("validation", [("failed", "test", 2, 3, 2)])])
        self.assertEqual(_flags(r), ["repeated_failure"])
        self.assertEqual(_flags(r, 0), [])

    def test_a_changed_rerun_after_an_environment_failure_is_a_workaround(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, ENV_FAILS),
                     _call("Bash", {"command": "JAVA_HOME=/opt/jdk17 " + TEST}, ENV_FAILS)])
        self.assertEqual(_outline(r), [("repair", [("blocked", "test", 1, 1, 1)]),
                                       ("validation", [("blocked", "test", 2, 3, 2)])])
        self.assertNotIn("repeated_failure", _flags(r))
        self.assertIn("environment_workaround", _flags(r))
        self.assertEqual(r["metrics"]["n_blocked_attempts"], 1)

    def test_a_build_file_edit_before_the_fix_takes_the_previous_phase(self):
        # no row has an edit of a build file before the first fix: the general rule gives the
        # previous step's phase, and the very first step's is planning
        r = _phased([_edit("app/build.gradle"), _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("planning", [("unchecked", "none", 1, 1, 0)]),
                                       ("reproduction", [("succeeded", "test", 2, 2, 1)])])
        self.assertEqual(r["table_row"], ["LG", "L6"])
        self.assertIn("environment_workaround", _flags(r, 0))
        self.assertIsNone(r["anchor"])

    def test_a_build_before_the_fix_is_planning(self):
        r = _phased([_call("Bash", {"command": BUILD}, ENV_FAILS), _read()], targets=[SRC])
        self.assertEqual(r["table_row"], ["L4", "L5"])
        self.assertEqual(_outline(r), [("planning", [("blocked", "build", 1, 1, 1)]),
                                       ("localization", [("succeeded", "target_file", 2, 2, 1)])])

    def test_a_plan_is_planning_anywhere_and_the_opening_steps_are_planning(self):
        plan = _call("update_plan", {"plan": [{"step": "x", "status": "in_progress"}]}, "ok")
        r = _phased([_call("Bash", {"command": "git status --short"}, ""), plan,
                     _read(OTHER), plan, _read(OTHER), _call("Bash", {"command": "ls app"}, ""),
                     _read()], targets=[SRC])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("planning", 1, 2), ("localization", 3, 3), ("planning", 4, 4),
                          ("localization", 5, 7)])
        self.assertEqual(r["table_row"], ["L2", "L1", "L5", "L1", "L5", "L14", "L5"])
        self.assertEqual(r["metrics"]["actions_to_first_found"], 6)

    def test_localization_is_unchecked_without_any_target(self):
        r = _phased([_read()])
        self.assertEqual(_outline(r), [("localization", [("unchecked", "none", 1, 1, 1)])])
        self.assertEqual(r["metrics"]["target_source"], "none")

    def test_reading_only_docs_before_the_fix_is_planning(self):
        r = _phased([_read("README.md"), _read()])
        self.assertEqual(r["phase"], [phase.PLANNING, phase.LOCALIZATION])
        self.assertEqual(r["table_row"], ["L3", "L5"])
        # a build file is not docs: reading it before the fix is localization
        mid = _phased([_read(OTHER), _read("app/build.gradle"), _read("README.md")])
        self.assertEqual(mid["phase"], ["localization", "localization", "planning"])
        self.assertEqual(mid["table_row"], ["L5", "L5", "L3"])
        both = _phased([_call("Bash", {"command": f"cat README.md {SRC}"}, "x")])
        self.assertEqual(both["table_row"], ["L5"])           # docs and code: not docs only

    def test_reading_an_output_of_a_run_follows_it(self):
        shot = _call("Read", {"file_path": ".verify/s1.png"}, "[image]")
        r = _phased([_edit(), _call("Bash", {"command": "adb shell screencap -p /sdcard/s1.png"}, ""),
                     shot])
        self.assertEqual(lookup.target(".verify/s1.png"), "other")
        self.assertEqual(r["phase"], ["repair", "validation", "validation"])
        self.assertEqual(r["table_row"], ["L8", "L12", "L11"])

    def test_a_dev_null_redirect_is_not_a_toolchain_probe(self):
        r = _phased([_call("Bash", {"command": "rg -n Foo app/src 2>/dev/null"}, "x")])
        self.assertEqual(r["phase"], ["localization"])

    def test_a_search_of_the_gradle_cache_before_the_fix_is_localization(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": 'find ~/.gradle ~/.m2 -iname "*x*"'}, ""),
                     _read()], targets=[SRC])
        self.assertEqual(r["phase"], ["localization"] * 3)
        self.assertEqual(r["table_row"], ["L5", "L5", "L5"])
        self.assertEqual(r["actions"][1]["target_kinds"], ["outside"])

    def test_git_before_the_fix_takes_the_previous_phase_and_after_it_validates(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": f"git log -p -- {SRC}"}, "commit"),
                     _call("Bash", {"command": "git status --short"}, ""), _edit(),
                     _call("Bash", {"command": "git status --short"}, "")])
        self.assertEqual(r["table_row"], ["L5", "L15", "L15", "L8", "L12"])
        self.assertEqual(r["phase"], ["localization"] * 3 + ["repair", "validation"])

    def test_reading_back_the_patch_is_validation(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES),
                     _call("Bash", {"command": "git diff"}, "diff"), _read()])
        self.assertEqual(_outline(r), [("repair", [("succeeded", "test", 1, 1, 1)]),
                                       ("validation", [("succeeded", "test", 2, 4, 1)])])
        self.assertEqual(r["table_row"][2:], ["L12", "L11"])
        self.assertTrue(r["actions"][3]["own_patch"])
        self.assertEqual(r["metrics"]["self_reviews"], 2)

    def test_reading_back_a_changed_file_is_validation(self):
        r = _phased([_edit(), _read(), _read(OTHER), _edit(OTHER),
                     _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(r["phase"], ["repair", "validation", "localization", "repair",
                                      "validation"])
        self.assertEqual(r["table_row"], ["L8", "L11", "L9", "L8", "L12"])
        self.assertEqual([a["own_patch"] for a in r["actions"]], [False, True, False, False,
                                                                  False])

    def test_reading_unchanged_code_after_the_fix_looks_ahead(self):
        # rows 9 and 10: the next decisive step after the read says what it was for
        def rows(calls):
            return _phased(calls)["table_row"]
        self.assertEqual(rows([_edit(), _read(OTHER), _edit(OTHER)]), ["L8", "L9", "L8"])
        self.assertEqual(rows([_edit(), _read(OTHER), _call("Bash", {"command": BUILD},
                                                            BUILD_PASSES), _edit(OTHER)]),
                         ["L8", "L10", "L12", "L8"])
        self.assertEqual(rows([_edit(), _read(OTHER)]), ["L8", "L10"])   # the end decides
        self.assertEqual(rows([_edit(), _read(OTHER), _call("Bash", {"command": "ls"}, ""),
                               _edit(OTHER)]), ["L8", "L9", "L14", "L8"])

    def test_a_passing_build_decides_only_when_nothing_after_it_does(self):
        only = _phased([_edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES)])
        self.assertEqual(_outline(only), [("repair", [("succeeded", "build", 1, 1, 1)]),
                                          ("validation", [("succeeded", "build", 2, 2, 1)])])
        both = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES),
                        _call("Bash", {"command": BUILD}, BUILD_PASSES),
                        _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(both), [("repair", [("succeeded", "test", 1, 1, 1)]),
                                          ("validation", [("succeeded", "test", 2, 4, 2)])])

    def test_an_edit_after_a_passing_build_starts_a_new_attempt(self):
        build = _call("Bash", {"command": BUILD}, BUILD_PASSES)
        cycles = _phased([_edit(), build, _edit(OTHER), build])
        self.assertEqual([s["phase"] for s in cycles["phases"]],
                         ["repair", "validation", "repair", "validation"])
        self.assertEqual(cycles["metrics"]["n_attempts"], 2)
        tested = _phased([_edit(), build, _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(tested), [("repair", [("succeeded", "test", 1, 1, 1)]),
                                            ("validation", [("succeeded", "test", 2, 3, 1)])])

    def test_a_search_without_matches_is_not_a_tool_error(self):
        miss = _call("Bash", {"command": "rg -n Nothing app/src"}, "Process exited with code 1",
                     error=True)
        bad = _call("Bash", {"command": "rg -n '(' app/src"},
                    "regex parse error: unclosed group", error=True)
        self.assertEqual(_phased([miss])["metrics"]["tool_errors"], 0)
        self.assertEqual(_phased([bad])["metrics"]["tool_errors"], 1)

    def test_driving_the_app_is_a_manual_ui_check(self):
        r = _phased([_edit(), _call("Bash", {"command": "adb shell input tap 400 900"}, "")])
        self.assertIn("manual_ui_check", _flags(r))

    def test_editing_tests_or_the_harness_is_test_modified(self):
        test = _edit("app/src/test/java/com/x/FooTest.java")
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES), test])
        self.assertEqual(_flags(r), ["test_modified"])
        self.assertIn("test_modified", _flags(_phased([_edit("run_pipeline.sh")])))

    def test_an_edit_never_run_is_unchecked(self):
        r = _phased([_read(), _edit()])
        self.assertEqual(_outline(r)[-1], ("repair", [("unchecked", "none", 2, 2, 1)]))

    def test_a_poll_follows_its_run(self):
        r = _phased([_sh(TEST, "Process running with session ID 7"),
                     _call("write_stdin", {"session_id": 7, "chars": ""}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("reproduction", [("succeeded", "test", 1, 2, 1)])])
        self.assertEqual(r["metrics"]["tool_actions"], 1)

    def test_a_patch_and_its_run_in_one_command_are_one_attempt(self):
        r = _phased([_sh(f"{PATCH}\n{TEST}", TEST_PASSES)])
        self.assertEqual(_outline(r), [("repair", [("succeeded", "test", 1, 1, 1)])])

    def test_a_sub_agent_is_localization_and_its_own_edit_is_the_first_fix(self):
        # the sub-agent call before the fix is row 5; the edit its sub-agent makes is row 8
        sub = _traj([_edit()], prefix="sub_", trajectory_id="sub-1")
        r = phase.phases(_traj([_read(OTHER),
                                _call("Agent", {"prompt": "Fix the bug in Foo.java",
                                                "subagent_type": "general-purpose"},
                                      "done", ref="sub-1"),
                                _call("Agent", {"prompt": "Check the fix"}, "ok")],
                               subagents=(sub,)), "1")
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("localization", 1, 2), ("repair", 3, 4)])
        self.assertEqual(r["table_row"], ["L5", "L5", "L8", "LG"])
        self.assertEqual(r["anchor"], 3)

    def test_every_action_names_its_table_row(self):
        r = _phased([_read(), _edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertTrue(set(r["table_row"]) <= {row[0] for row in lookup.PHASE_TABLE})


class NoGroupingTests(unittest.TestCase):
    """Nothing moves an action after the phase table: the grouping rules of codebook version
    3 are baseline B4 (``baselines.grouping_rules``) and its Table 4 baseline B5."""
    LONG = [_edit()] + [_read(OTHER)] * 5 + [_call("Bash", {"command": TEST}, TEST_FAILS)]
    SHORT = [_edit(), _read(OTHER), _call("Bash", {"command": TEST}, TEST_PASSES)]

    def test_a_single_lookup_between_an_edit_and_its_run_validates(self):
        r = _phased(self.SHORT)
        self.assertEqual(r["phase"], ["repair", "validation", "validation"])
        self.assertEqual(r["phase"], r["own_phase"])

    def test_a_long_lookup_before_a_run_is_validation(self):
        r = _phased(self.LONG)
        self.assertEqual(_outline(r), [("repair", [("failed", "test", 1, 1, 1)]),
                                       ("validation", [("failed", "test", 2, 7, 1)])])

    def test_a_long_lookup_before_the_next_edit_is_localization(self):
        r = _phased(self.LONG[:-1] + [_edit(OTHER)])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("repair", 1, 1), ("localization", 2, 6), ("repair", 7, 7)])

    def test_a_single_build_between_two_reads_keeps_its_phase(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": BUILD}, BUILD_PASSES), _read()])
        self.assertEqual([s["phase"] for s in r["phases"]],
                         ["localization", "planning", "localization"])

    def test_a_review_between_two_attempts_is_validation(self):
        r = _phased([_edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES),
                     _call("Bash", {"command": "git diff"}, "diff --git a/x b/x"),
                     _edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES)])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("repair", 1, 1), ("validation", 2, 3), ("repair", 4, 4),
                          ("validation", 5, 5)])

    def test_b4_applies_the_version_3_grouping_rules(self):
        def b4(calls):
            return baselines.grouping_rules(segment.prepare(_traj(calls), "1"))
        self.assertEqual(b4(self.SHORT), ["repair"] * 3)
        self.assertEqual(b4(self.LONG), ["repair"] + ["localization"] * 5 + ["repair"])

    def test_b5_applies_the_version_4_phase_lookup(self):
        def b5(calls):
            return baselines.table_v4(segment.prepare(_traj(calls), "1"))
        self.assertEqual(b5(self.SHORT), ["repair", "localization", "validation"])
        self.assertEqual(b5([_edit("app/build.gradle"), _read("README.md"), _read()]),
                         ["planning", "planning", "localization"])


class KindTests(unittest.TestCase):
    """The taxonomy's action kinds, which the verdicts, outcomes, flags and baselines read."""

    def _cat(self, command: str, tool: str = "exec_command") -> tuple:
        key = "cmd" if tool == "exec_command" else "command"
        row = {"tool": tool, "arguments": {key: command}}
        row["mid_level"] = taxonomy.mid_level({"function_name": tool,
                                               "arguments": row["arguments"]})
        return taxonomy.kind(row)

    def test_git_diff_and_reverts_are_split_from_vcs(self):
        self.assertEqual(self._cat("git status --short && git diff"), ("diff", False))
        self.assertEqual(self._cat("git -C app --no-pager diff HEAD"), ("diff", False))
        self.assertEqual(self._cat("git checkout -- ."), ("shell_edit", True))
        self.assertEqual(self._cat("git stash && git stash pop"), ("shell_edit", True))
        self.assertEqual(self._cat("git stash list"), ("vcs", False))
        self.assertEqual(self._cat("git log --oneline | head -5"), ("vcs", False))

    def test_a_git_call_that_also_reads_is_a_read(self):
        self.assertEqual(self._cat(f"sed -n '1,330p' {SRC}; git log -3"), ("read_file", False))
        self.assertEqual(self._cat("rg -n Foo app/src; git status"), ("search_code", False))

    def test_shell_writes_are_shell_edits_and_patches_are_edits(self):
        self.assertEqual(self._cat(f"sed -i 's/a/b/' {SRC}"), ("shell_edit", False))
        self.assertEqual(self._cat(PATCH), ("edit_file", False))
        self.assertEqual(self._cat("{ printf '%s\\n' '*** Begin Patch' "
                                   "'*** Update File: app/src/main/res/values/a.xml' "
                                   "'*** End Patch'; } | apply_patch"), ("edit_file", False))
        self.assertEqual(self._cat("diff -u /tmp/a.java /tmp/b.java"), ("diff", False))

    def test_editor_tools_keep_their_mid_level(self):
        row = {"tool": "Edit", "arguments": {"file_path": SRC}, "mid_level": "edit_file"}
        self.assertEqual(taxonomy.kind(row), ("edit_file", False))

    def test_every_kind_has_a_family_and_a_category(self):
        self.assertEqual(set(taxonomy.KINDS), set(taxonomy.KIND_FAMILY))
        self.assertTrue(set(taxonomy.MID_LEVEL) <= set(taxonomy.KINDS))
        self.assertEqual(set(lookup.KIND_CATEGORY), set(taxonomy.KINDS))
        self.assertTrue(set(lookup.KIND_CATEGORY.values()) <= set(lookup.CATEGORIES))

    def test_object_roles(self):
        self.assertEqual([taxonomy.object_role(p) for p in (
            SRC, "app/src/androidTest/java/x/FooTest.java", "app/build.gradle",
            "run_pipeline.sh", "README.md", "/v/runs/c_run1/bug-1/CHANGELOG")],
            ["source", "test", "toolchain", "harness", "docs", "docs"])


class ActionTableTests(unittest.TestCase):
    """The action table (``lookup.classify``) on single calls: (category, entry)."""

    def _sh(self, command: str, tool: str = "Bash") -> tuple:
        found = lookup.classify(tool, {"command": command})
        return found["category"], found["item"]

    def _cat(self, command: str) -> str:
        return self._sh(command)[0]

    def test_native_tools(self):
        self.assertEqual(lookup.classify("Read", {"file_path": SRC})["category"], "read")
        self.assertEqual(lookup.classify("glob", {"pattern": "**/*.kt"})["category"], "search")
        self.assertEqual(lookup.classify("update_plan", {})["category"], "plan")
        self.assertEqual(lookup.classify("agent", {"prompt": "find x"})["category"], "sub-agent")
        self.assertEqual(lookup.classify("write_stdin", {"session_id": 1})["category"], "other")
        self.assertEqual(lookup.classify("Write", {"file_path": "/tmp/Sim.java"})["category"],
                         "other")                       # an edit outside the repository
        self.assertEqual(lookup.classify("update_goal", {"status": "x"})["item"], "any other tool")

    def test_tools_of_other_agents_count_as_what_they_do(self):
        self.assertEqual(lookup.classify("Grep", {"pattern": "x"})["category"], "search")
        self.assertEqual(lookup.classify("TodoWrite", {"todos": []})["category"], "plan")
        self.assertEqual(lookup.classify("str_replace_editor",
                                         {"command": "str_replace", "path": SRC})["category"],
                         "edit")
        self.assertEqual(lookup.classify("made_up_tool", {})["item"], "any other tool")

    def test_shell_programs(self):
        self.assertEqual(self._cat(f"sed -n '1,40p' {SRC}"), "read")
        self.assertEqual(self._cat(f"tail -40 {SRC}"), "read")
        self.assertEqual(self._cat("git log --oneline | tail -5"), "vcs")   # tail filters
        self.assertEqual(self._cat("./gradlew testDebugUnitTest"), "test")
        self.assertEqual(self._cat("./gradlew checkstyle"), "test")
        self.assertEqual(self._cat("./gradlew assembleDebug"), "build")
        self.assertEqual(self._cat("./gradlew tasks"), "orient")
        self.assertEqual(self._cat("javac -d out Foo.java"), "build")
        self.assertEqual(self._cat("javac -d out Foo.java && java -cp out Foo"), "test")
        self.assertEqual(self._cat("java -version"), "orient")
        self.assertEqual(self._cat("adb shell input tap 1 2"), "test")
        self.assertEqual(self._cat("ADB=$HOME/sdk/platform-tools/adb; $ADB devices"), "test")
        self.assertEqual(self._cat("git apply --check fix.patch"), "test")
        self.assertEqual(self._cat("git status --short"), "diff")
        self.assertEqual(self._cat("cmp a.txt b.txt"), "diff")
        self.assertEqual(self._cat("git blame -L 1,9 " + SRC), "vcs")
        self.assertEqual(self._cat("git ls-remote https://x/y.git"), "other")
        self.assertEqual(self._cat("sleep 30"), "other")
        self.assertEqual(self._cat("python3 -c 'print(1)'"), "other")
        self.assertEqual(self._sh("cd /tmp && echo hi"), ("other", "a line made only of ignored programs"))
        self.assertEqual(self._sh("whoami"), ("other", "any other program"))

    def test_edits_from_the_shell(self):
        self.assertEqual(self._cat(f"sed -i 's/a/b/' {SRC}"), "edit")
        self.assertEqual(self._cat("sed -i 's/a/b/' /tmp/x.java"), "other")     # ignored
        self.assertEqual(self._cat(PATCH), "edit")
        self.assertEqual(self._cat("git checkout -- ."), "edit")
        self.assertEqual(self._cat("git stash list"), "vcs")
        self.assertEqual(self._cat(f"cp /tmp/Foo.java {SRC}"), "edit")
        self.assertEqual(self._cat(f"rm {SRC}"), "edit")
        self.assertEqual(self._cat("rm -rf /tmp/build"), "other")
        self.assertEqual(self._cat(f"python3 - <<'EOF'\nopen('{SRC}', 'w').write('x')\nEOF"),
                         "edit")

    def test_the_highest_category_of_a_line_wins(self):
        self.assertEqual(self._cat(f"{PATCH}\n./gradlew testDebugUnitTest"), "edit")
        self.assertEqual(self._cat("./gradlew assembleDebug && adb install x.apk"), "build")
        self.assertEqual(self._cat(f"rg -n Foo app/src; git status"), "search")
        self.assertEqual(self._cat(f"git diff; sed -n 1,9p {SRC}"), "read")
        self.assertEqual(self._cat("ls; pwd; sleep 1"), "orient")

    def test_targets(self):
        self.assertEqual([lookup.target(p) for p in (
            SRC, "app/src/main/res/layout/a.xml", "app/src/main/AndroidManifest.xml",
            "app/src/test/java/x/FooTest.java", "app/build.gradle", "gradle.properties",
            "README.md", "AGENTS.md", "fix.patch", ".verify/s1.png", "Sim.java",
            "/tmp/Foo.java", "~/.gradle/caches/x.jar", "/home/u/app/src/main/java/x/A.java")],
            ["source", "source", "source", "test", "build", "build", "docs", "docs", "other",
             "other", "other", "outside", "outside", "source"])

    def test_the_checkout_is_the_folder_the_run_was_started_in(self):
        inside = "/w/runs/qwen_original_run3/bug-273/app/src/main/java/A.java"
        typo = "/w/runs-copy/qwen-original-run3/bug-273/fix.patch"
        with project.use({"extra": {"cwd": "/w/runs/qwen_original_run3/bug-273"}}):
            self.assertEqual((lookup.target(inside), lookup.target(typo)), ("source", "outside"))
        with project.use(None):                            # no cwd: any bug-<id> folder
            self.assertEqual((lookup.target(inside), lookup.target(typo)), ("source", "other"))
            self.assertEqual(lookup.target("/tmp/x/bug-273/app/src/main/A.java"), "outside")


class VocabularyTests(unittest.TestCase):
    def test_every_phase_uses_the_four_outcomes(self):
        self.assertEqual(set(phase.PHASE_OUTCOMES), set(phase.PHASES))
        used = set(o for outs in phase.PHASE_OUTCOMES.values() for o in outs)
        self.assertEqual(used, set(phase.OUTCOMES))
        self.assertEqual(len(phase.OUTCOMES), 4)
        self.assertEqual(len(phase.FLAGS), 5)

    def test_checker_rejects_a_repeated_outcome(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        sub = dict(r["phases"][0]["subphases"][0])
        r["phases"][0]["subphases"] = [dict(sub, _hi=sub["_lo"] + 1, id="p1.1"),
                                       dict(sub, _lo=sub["_lo"] + 1, id="p1.2")]
        with self.assertRaises(ValueError):
            phase.check_hierarchy(r["actions"], r)


if __name__ == "__main__":
    unittest.main()
