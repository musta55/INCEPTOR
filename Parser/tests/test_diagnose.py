"""What the viewer shows to make an outcome checkable, and the diagnosis of unrecognised steps
(``atif.verdict.evidence_line``, subphase ``checks``, ``atif.rules`` shell-tool and program
rows, ``atif.diagnose``, ``atif.upload`` with ``atif``).

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import gzip
import json
import unittest
from pathlib import Path

from atif import diagnose, project, rules, upload, verdict
from tests.test_segment import PATCH, SRC, TEST, TEST_FAILS, TEST_PASSES, _call, _sh, _traj

PACKS = Path(__file__).resolve().parent.parent / "viewer" / "data" / "atif" / "run1"
BUILD_OK = ("> Task :app:compileDebugJavaWithJavac\nNote: Some input files use unchecked "
            "operations.\n\nBUILD SUCCESSFUL in 1m 55s\n89 actionable tasks: 89 executed")


def _unknown_agent() -> dict:
    """An ATIF trajectory of an agent no table knows: a shell tool, an editor, a lister."""
    calls = [
        _call("list_dir", {"relative_workspace_path": "app/src"}, "main/"),
        _call("run_terminal_cmd", {"command": "./gradlew assembleDebug"}, BUILD_OK),
        _call("search_replace", {"file_path": SRC, "old_string": "a", "new_string": "b"}, "ok"),
        _call("run_terminal_cmd", {"command": "cargo test --all"}, "test result: ok"),
        _call("mystery_tool", {"x": 1}, "ok"),
    ]
    return {**_traj(calls), "schema_version": "ATIF-v1.6"}


class EvidenceLineTests(unittest.TestCase):
    def test_the_deciding_line_of_a_build(self):
        v = verdict.verdict("build", BUILD_OK)
        self.assertEqual(v, ("pass", None, "build_ok"))
        self.assertEqual(verdict.evidence_line(BUILD_OK, v[2]), "BUILD SUCCESSFUL in 1m 55s")

    def test_a_failing_test_names_the_test(self):
        v = verdict.verdict("run_test", TEST_FAILS)
        self.assertEqual(verdict.evidence_line(TEST_FAILS, v[2]),
                         "com.x.FooTest > testBar FAILED")

    def test_a_gradle_test_pass_shows_the_task_and_the_build(self):
        v = verdict.verdict("run_test", TEST_PASSES)
        self.assertEqual(v[2], "gradle_tests")
        self.assertEqual(verdict.evidence_line(TEST_PASSES, v[2]),
                         "> Task :app:testDebugUnitTest … BUILD SUCCESSFUL in 6s")

    def test_a_compile_error_and_an_environment_failure(self):
        compiled = "/x/A.java:12: error: cannot find symbol\nBUILD FAILED in 3s"
        self.assertEqual(verdict.evidence_line(compiled, "build_fail"),
                         "/x/A.java:12: error: cannot find symbol")
        env = "* What went wrong:\n  Could not determine java version from '21'.\nBUILD FAILED"
        self.assertEqual(verdict.evidence_line(env, "build_fail"),
                         "What went wrong: Could not determine java version from '21'.")

    def test_no_marker_gives_nothing(self):
        self.assertEqual(verdict.evidence_line("whatever", "exit"), "")
        self.assertEqual(verdict.evidence_line("whatever", ""), "")


class ChecksTests(unittest.TestCase):
    def test_edit_only_repair_names_the_run_that_judged_it(self):
        """Edits, a read in between, then a build: the repair subphases before the read hold
        no run, and their deciding action is the build after them."""
        calls = [_sh(f"sed -n '1,40p' {SRC}", "class Foo {}"), _sh(PATCH, "Success"),
                 _sh(f"sed -n '1,40p' app/src/main/java/com/x/Bar.java", "class Bar {}"),
                 _sh(PATCH, "Success"), _sh(TEST, TEST_PASSES)]
        result = rules.phases(_traj(calls), "1")
        subs = [(s["outcome"], s["start"], s["end"], s["checks"])
                for p in result["phases"] for s in p["subphases"] if p["phase"] == "repair"]
        self.assertTrue(subs)
        for outcome, start, end, checks in subs:
            self.assertEqual(checks, [5], (outcome, start, end))

    def test_bug_18_claude_run_1(self):
        """The case the user asked about: #33's build judges the repair spans before it."""
        path = PACKS / "bug-18.json.gz"
        if not path.exists():
            self.skipTest("no corpus packs (python3 -m atif.cli view --all)")
        pack = json.load(gzip.open(path))
        view = upload.reanalyze(pack)["views"]["claude"]
        a = view["actions"][32]
        self.assertEqual((a["verdict"], a["evidence_line"]), ("pass", "BUILD SUCCESSFUL in 1m 55s"))
        repair = [s for p in view["phases"] if p["phase"] == "repair" for s in p["subphases"]]
        self.assertEqual([s["checks"] for s in repair], [[33], [33], [33]])


class RowKindTests(unittest.TestCase):
    def test_a_shell_tool_row_reads_its_commands(self):
        before = rules.phases(_unknown_agent(), "1")
        self.assertEqual(before["actions"][1]["category"], "other")
        rs = {"custom": [{"kind": "shell_tool", "match": "run_terminal_cmd", "value": "command"}]}
        after = rules.phases(_unknown_agent(), "1", rs)
        self.assertEqual(after["actions"][1]["category"], "build")
        self.assertEqual(after["actions"][1]["verdict"], "pass")
        self.assertEqual(after["rules"]["custom"][0]["matched"], [2, 4])
        self.assertNotIn("run_terminal_cmd", __import__("atif.taxonomy").taxonomy.SHELL_TOOLS)

    def test_a_shell_tool_needs_an_argument_name(self):
        with self.assertRaises(rules.RuleError):
            rules.normalize({"custom": [{"kind": "shell_tool", "match": "x", "value": "a b"}]})

    def test_a_program_row_matches_whole_program_names(self):
        rs = {"custom": [{"kind": "shell_tool", "match": "run_terminal_cmd", "value": "command"},
                         {"kind": "category", "field": "program", "match": "cargo test",
                          "value": "test"},
                         {"kind": "category", "field": "program", "match": "test",
                          "value": "build"}]}
        acts = rules.phases(_unknown_agent(), "1", rs)["actions"]
        self.assertEqual(acts[3]["category"], "test")          # "test" is not a program here
        self.assertEqual(rules.describe(rules.normalize(rs)["custom"][1]),
                         "Steps that run “cargo test” are test.")


class DiagnoseTests(unittest.TestCase):
    def test_unknown_tools_get_suggested_rows(self):
        result = rules.phases(_unknown_agent(), "1")
        report = diagnose.unrecognized(result["actions"], result["table_row"], result["rules"])
        self.assertEqual(report["n_unrecognized"], 5)
        by_key = {g["key"]: g for g in report["groups"]}
        self.assertEqual(by_key["run_terminal_cmd"]["suggest"]["row"],
                         {"kind": "shell_tool", "field": "tool", "match": "run_terminal_cmd",
                          "value": "command"})
        self.assertEqual(by_key["search_replace"]["suggest"]["row"]["value"], "edit")
        self.assertEqual(by_key["list_dir"]["suggest"]["row"]["value"], "orient")
        self.assertIsNone(by_key["mystery_tool"]["suggest"])

    def test_approving_the_suggestions_recognises_the_steps(self):
        text = json.dumps(_unknown_agent())
        first = upload.analyze(text, "u.json")["unrecognized"]
        rows = [g["suggest"]["row"] for g in first["groups"] if g["suggest"]]
        second = upload.analyze(text, "u.json", ruleset={"custom": rows})["unrecognized"]
        self.assertEqual([(g["kind"], g["key"]) for g in second["groups"]],
                         [("tool", "mystery_tool"), ("program", "cargo test")])
        rows.append(next(g["suggest"]["row"] for g in second["groups"] if g["suggest"]))
        third = upload.analyze(text, "u.json", ruleset={"custom": rows})["unrecognized"]
        self.assertEqual([g["key"] for g in third["groups"]], ["mystery_tool"])

    def test_the_corpus_agents_have_no_unrecognised_steps(self):
        packs = sorted(PACKS.glob("bug-*.json.gz"))[:15]
        if not packs:
            self.skipTest("no corpus packs (python3 -m atif.cli view --all)")
        for path in packs:
            pack = json.load(gzip.open(path))
            for agent, t in pack["trajectories"].items():
                result = rules.phases(t, str(pack["bug"]))
                with project.use(t):
                    report = diagnose.unrecognized(result["actions"], result["table_row"],
                                                   result["rules"])
                self.assertEqual(report["groups"], [], f"{path.name} {agent}")

    def test_an_upload_keeps_its_atif_when_asked(self):
        text = json.dumps(_unknown_agent())
        self.assertNotIn("atif", upload.analyze(text, "u.json"))
        got = upload.request({"name": "u.json", "text": text, "atif": True})
        self.assertEqual(len(got["atif"]["steps"]), len(_unknown_agent()["steps"]))


if __name__ == "__main__":
    unittest.main()
