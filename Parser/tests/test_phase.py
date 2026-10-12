"""Phase taxonomy v3 tests (``atif.phase``, ``taxonomy.category``, ``taxonomy.object_role``).

Each rule of ``Parser/Phase taxonomy.md`` is pinned on a small synthetic trajectory built
with the helpers of ``test_segment``; the invariant test phases every trajectory of
``Dataset/`` original/run1, parsed from the raw logs.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import unittest

from atif import phase, taxonomy
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

    def test_registry_leaves_at_most_one_percent_other(self):
        for agent in ("claude", "codex", "qwen"):
            cats = [a["category"] for key, r in self.results if key.agent == agent
                    for a in r["actions"]]
            self.assertLessEqual(cats.count("other") / len(cats), 0.01, agent)


class PhaseRuleTests(unittest.TestCase):
    def test_reproduction_then_repair(self):
        r = _phased([_call("Bash", {"command": f"sed -n 1,40p {OTHER}"}, "x"),
                     _call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(r), [
            ("localization", [("failed", "target_file", 1, 1, 1)]),
            ("reproduction", [("succeeded", "test", 2, 2, 1)]),
            ("repair", [("succeeded", "test", 3, 4, 1)])])
        self.assertTrue(r["metrics"]["reproduced_before_fix"])

    def test_the_same_failing_test_succeeds_before_the_fix_and_fails_after(self):
        r = _phased([_call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual([(s["phase"], sp[0]) for s, (_, sps) in zip(r["phases"], _outline(r))
                          for sp in sps],
                         [("reproduction", "succeeded"), ("repair", "failed")])

    def test_a_fix_verify_loop_is_one_repair_phase_with_outcome_runs(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _read(OTHER), _edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _edit(), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(r), [("repair", [("failed", "test", 1, 5, 2),
                                                   ("succeeded", "test", 6, 7, 1)])])
        self.assertEqual(r["phases"][0]["subphases"][0]["n_attempts"], 2)
        self.assertEqual((r["metrics"]["n_attempts"], r["metrics"]["n_failed_attempts"],
                          r["metrics"]["attempts_to_first_pass"]), (3, 2, 3))

    def test_a_patch_that_does_not_compile_fails_with_build_evidence(self):
        compile_error = ("Foo.java:3: error: cannot find symbol\nFAILURE: Build failed with "
                         "an exception.\n* What went wrong:\nExecution failed for task "
                         "':app:compileDebugJavaWithJavac'.\n> Compilation failed\n"
                         "BUILD FAILED in 2s\nProcess exited with code 1")
        r = _phased([_edit(), _call("Bash", {"command": BUILD}, compile_error)])
        self.assertEqual(_outline(r), [("repair", [("failed", "build", 1, 2, 1)])])

    def test_an_unchanged_rerun_of_the_same_failure_is_flagged_across_phases(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_FAILS),
                     _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("repair", [("failed", "test", 1, 2, 1)]),
                                       ("validation", [("failed", "test", 3, 3, 1)])])
        self.assertEqual(_flags(r), ["repeated_failure"])
        self.assertEqual(_flags(r, 0), [])

    def test_a_changed_rerun_after_an_environment_failure_is_a_workaround(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, ENV_FAILS),
                     _call("Bash", {"command": "JAVA_HOME=/opt/jdk17 " + TEST}, ENV_FAILS)])
        self.assertEqual(_outline(r), [("repair", [("blocked", "test", 1, 2, 1)]),
                                       ("validation", [("blocked", "test", 3, 3, 1)])])
        self.assertNotIn("repeated_failure", _flags(r))
        self.assertIn("environment_workaround", _flags(r))
        self.assertEqual(r["metrics"]["n_blocked_attempts"], 1)

    def test_a_build_file_edit_serves_the_run_it_enables(self):
        # environment work is not a phase: it goes with the failing test it gets running
        r = _phased([_edit("app/build.gradle"), _call("Bash", {"command": TEST}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("reproduction", [("succeeded", "test", 1, 2, 1)])])
        self.assertIn("environment_workaround", _flags(r))
        self.assertIsNone(r["anchor"])

    def test_a_prefix_build_check_without_a_test_is_understanding(self):
        r = _phased([_call("Bash", {"command": BUILD}, ENV_FAILS), _read()], targets=[SRC])
        self.assertEqual(_outline(r), [("understanding", [("blocked", "build", 1, 1, 1)]),
                                       ("localization", [("succeeded", "target_file", 2, 2, 1)])])

    def test_opening_neutral_actions_are_understanding_and_later_ones_follow_lookups(self):
        plan = _call("update_plan", {"plan": [{"step": "x", "status": "in_progress"}]}, "ok")
        r = _phased([plan, _call("Bash", {"command": "git status --short"}, ""),
                     _read(OTHER), plan, _read(OTHER), plan, _read()], targets=[SRC])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("understanding", 1, 2), ("localization", 3, 7)])
        self.assertEqual(r["metrics"]["actions_to_first_found"], 6)

    def test_localization_is_unchecked_without_any_target(self):
        r = _phased([_read()])
        self.assertEqual(_outline(r), [("localization", [("unchecked", "none", 1, 1, 1)])])
        self.assertEqual(r["metrics"]["target_source"], "none")

    def test_docs_and_build_files_are_not_localization(self):
        self.assertEqual(phase.UNDERSTANDING, _phased([_read("README.md"), _read()])
                         ["phases"][0]["phase"])
        self.assertEqual(_outline(_phased([_read("app/build.gradle")])),
                         [("understanding", [("unchecked", "none", 1, 1, 0)])])

    def test_a_dev_null_redirect_is_not_a_toolchain_probe(self):
        r = _phased([_call("Bash", {"command": "rg -n Foo app/src 2>/dev/null"}, "x")])
        self.assertEqual(r["phase"], ["localization"])

    def test_a_look_into_the_gradle_cache_is_toolchain_work(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": 'find ~/.gradle ~/.m2 -iname "*x*"'}, ""),
                     _read()], targets=[SRC])
        self.assertEqual(r["own_phase"], ["localization", "understanding", "localization"])
        self.assertEqual(r["phase"], ["localization"] * 3)       # G7 joins the one-row detour

    def test_reading_back_the_diff_is_validation_without_a_check(self):
        r = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES),
                     _call("Bash", {"command": "git diff"}, "diff"), _read()])
        self.assertEqual(_outline(r), [("repair", [("succeeded", "test", 1, 2, 1)]),
                                       ("validation", [("unchecked", "none", 3, 4, 0)])])
        self.assertEqual(r["metrics"]["self_reviews"], 2)

    def test_a_passing_build_decides_only_when_nothing_after_it_does(self):
        only = _phased([_edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES)])
        self.assertEqual(_outline(only), [("repair", [("succeeded", "build", 1, 2, 1)])])
        both = _phased([_edit(), _call("Bash", {"command": TEST}, TEST_PASSES),
                        _call("Bash", {"command": BUILD}, BUILD_PASSES),
                        _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(both), [("repair", [("succeeded", "test", 1, 2, 1)]),
                                          ("validation", [("succeeded", "test", 3, 4, 1)])])

    def test_an_edit_after_a_passing_build_starts_a_new_attempt(self):
        build = _call("Bash", {"command": BUILD}, BUILD_PASSES)
        cycles = _phased([_edit(), build, _edit(OTHER), build])
        self.assertEqual(_outline(cycles), [("repair", [("succeeded", "build", 1, 4, 2)])])
        self.assertEqual(cycles["metrics"]["n_attempts"], 2)
        tested = _phased([_edit(), build, _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(_outline(tested), [("repair", [("succeeded", "test", 1, 3, 1)])])

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

    def test_a_poll_takes_the_phase_and_verdict_of_its_run(self):
        r = _phased([_sh(TEST, "Process running with session ID 7"),
                     _call("write_stdin", {"session_id": 7, "chars": ""}, TEST_FAILS)])
        self.assertEqual(_outline(r), [("reproduction", [("succeeded", "test", 1, 2, 1)])])
        self.assertEqual(r["metrics"]["tool_actions"], 1)

    def test_a_patch_and_its_run_in_one_command_are_one_attempt(self):
        r = _phased([_sh(f"{PATCH}\n{TEST}", TEST_PASSES)])
        self.assertEqual(_outline(r), [("repair", [("succeeded", "test", 1, 1, 1)])])

    def test_an_edit_delegation_is_repair_and_moves_the_anchor(self):
        sub = _traj([_edit()], prefix="sub_", trajectory_id="sub-1")
        r = phase.phases(_traj([_read(OTHER),
                                _call("Agent", {"prompt": "Fix the bug in Foo.java",
                                                "subagent_type": "general-purpose"},
                                      "done", ref="sub-1")], subagents=(sub,)), "1")
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("localization", 1, 1), ("repair", 2, 3)])
        self.assertEqual(r["anchor"], 2)


class KeepAndSmoothingTests(unittest.TestCase):
    LONG = [_edit()] + [_read(OTHER)] * 5 + [_call("Bash", {"command": TEST}, TEST_FAILS)]

    def test_a_short_lookup_inside_the_attempt_is_nested_in_repair(self):
        r = _phased([_edit(), _read(OTHER), _call("Bash", {"command": TEST}, TEST_PASSES)])
        self.assertEqual(r["phase"], ["repair"] * 3)
        self.assertEqual(r["own_phase"], ["repair", "localization", "repair"])
        self.assertEqual(_outline(r), [("repair", [("succeeded", "test", 1, 3, 1)])])

    def test_a_long_lookup_inside_an_attempt_is_its_own_localization_span(self):
        r = _phased(self.LONG)
        self.assertEqual(_outline(r), [("repair", [("failed", "test", 1, 1, 1)]),
                                       ("localization", [("failed", "target_file", 2, 6, 1)]),
                                       ("repair", [("failed", "test", 7, 7, 1)])])
        self.assertEqual(r["own_phase"][1:6], ["localization"] * 5)

    def test_a1_absorbs_a_single_interruption_without_a_decisive_run(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": BUILD}, BUILD_PASSES), _read()])
        self.assertEqual([s["phase"] for s in r["phases"]], ["localization"])
        self.assertEqual(r["own_phase"], ["localization", "understanding", "localization"])
        kept = _phased([_read(OTHER), _call("Bash", {"command": BUILD}, ENV_FAILS), _read()])
        self.assertEqual([s["phase"] for s in kept["phases"]],
                         ["localization", "understanding", "localization"])

    def test_two_actions_between_spans_of_one_phase_keep_their_phase(self):
        r = _phased([_read(OTHER), _call("Bash", {"command": BUILD}, BUILD_PASSES),
                     _call("Bash", {"command": BUILD}, BUILD_PASSES), _read()])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("localization", 1, 1), ("understanding", 2, 3), ("localization", 4, 4)])

    def test_validation_between_two_attempts_stays_validation(self):
        # bug-2587 claude: after the first attempt is judged, the agent reviews its diff and
        # checks git status before a second edit; the old repair-gap rule (A2) made it repair
        r = _phased([_edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES),
                     _call("Bash", {"command": "git diff"}, "diff --git a/x b/x"),
                     _call("Bash", {"command": "git diff --stat"}, "1 file changed"),
                     _edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES)])
        self.assertEqual([(s["phase"], s["start"], s["end"]) for s in r["phases"]],
                         [("repair", 1, 2), ("validation", 3, 4), ("repair", 5, 6)])

    def test_a_single_review_action_between_two_attempts_joins_repair(self):
        r = _phased([_edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES),
                     _call("Bash", {"command": "git diff"}, "diff --git a/x b/x"),
                     _edit(), _call("Bash", {"command": BUILD}, BUILD_PASSES)])
        self.assertEqual([s["phase"] for s in r["phases"]], ["repair"])
        self.assertEqual(r["own_phase"][2], "validation")

    def test_b2_switches_keep_rules_and_smoothing_off(self):
        r = _phased(self.LONG, keep_rules=False, smoothing=False)
        self.assertEqual(r["phase"], ["repair"] + ["localization"] * 5 + ["validation"])


class CategoryTests(unittest.TestCase):
    def _cat(self, command: str, tool: str = "exec_command") -> tuple:
        key = "cmd" if tool == "exec_command" else "command"
        row = {"tool": tool, "arguments": {key: command}}
        row["mid_level"] = taxonomy.mid_level({"function_name": tool,
                                               "arguments": row["arguments"]})
        return taxonomy.category(row)

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
        self.assertEqual(taxonomy.category(row), ("edit_file", False))

    def test_every_category_has_a_family(self):
        self.assertEqual(set(taxonomy.CATEGORIES), set(taxonomy.CATEGORY_FAMILY))
        self.assertTrue(set(taxonomy.MID_LEVEL) <= set(taxonomy.CATEGORIES))

    def test_object_roles(self):
        self.assertEqual([taxonomy.object_role(p) for p in (
            SRC, "app/src/androidTest/java/x/FooTest.java", "app/build.gradle",
            "run_pipeline.sh", "README.md", "/v/runs/c_run1/bug-1/CHANGELOG")],
            ["source", "test", "toolchain", "harness", "docs", "docs"])


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
