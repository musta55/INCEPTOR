"""Corpus layout, outcome table and CLI plumbing, checked against Dataset/ itself.

Plain unittest so it runs on the system interpreter:
    python3 -m unittest discover -s tests -t .
The expected numbers are the corpus's own (3 agents x 17 configs x 3 runs x 50 bugs, plus
the 250 logs of file_method_screen); the outcome spot checks were read off the CSVs by hand.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from atif import cli, corpus, outcomes  # noqa: E402

DATASET = HERE.parent.parent / "Dataset"
EXTRA_RUNS = {"claude": (1, 2), "codex": (1, 2), "qwen": (1,)}   # file_method_screen on disk


def _quiet(func, *args, **kwargs):
    """Run a CLI entry point with its stdout and stderr captured; returns (code, stdout)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = func(*args, **kwargs)
    return code, out.getvalue() + err.getvalue()


@unittest.skipUnless(DATASET.is_dir(), "Dataset/ not present")
class CorpusLayoutTests(unittest.TestCase):
    def test_fifty_bugs_sorted_numerically(self):
        ids = corpus.all_bug_ids(DATASET)
        self.assertEqual(len(ids), 50)
        self.assertEqual(ids, sorted(ids, key=int))
        self.assertEqual(ids[:3], ["8", "18", "44"])

    def test_run_folders(self):
        runs = corpus.available_runs(DATASET)
        expected = {(a, c, r) for a in corpus.AGENTS for c in corpus.CONFIGS for r in corpus.RUNS}
        expected |= {(a, "file_method_screen", r) for a, rs in EXTRA_RUNS.items() for r in rs}
        self.assertEqual(set(runs), expected)
        self.assertEqual(len(runs), 3 * 17 * 3 + 5)

    def test_every_log_on_disk(self):
        found = list(corpus.iter_logs(DATASET))
        self.assertEqual(len(found), 7900)
        self.assertEqual(len({key for key, _ in found}), 7900)
        self.assertEqual(Counter(key.agent for key, _ in found),
                         {"claude": 2650, "codex": 2650, "qwen": 2600})
        per_run = Counter((key.agent, key.config, key.run) for key, _ in found)
        self.assertEqual(set(per_run.values()), {50})
        self.assertEqual(sum(1 for _ in corpus.iter_logs(DATASET, configs=corpus.CONFIGS)), 7650)
        self.assertEqual(sum(1 for _ in corpus.iter_logs(
            DATASET, configs=corpus.EXTRA_CONFIGS)), 250)

    def test_filters(self):
        found = list(corpus.iter_logs(DATASET, agents=["qwen"], configs=["original"],
                                      runs=[2], bugs=["18", "8", "999999"]))
        self.assertEqual([k for k, _ in found], [corpus.Key("qwen", "original", 2, "8"),
                                                 corpus.Key("qwen", "original", 2, "18")])
        self.assertEqual(list(corpus.iter_logs(DATASET, configs=["file_method_screen"],
                                               agents=["qwen"], runs=[3])), [])

    def test_run_dir_names_with_overlapping_configs(self):
        cases = {
            "codex_causing_screen_description_run1": ("codex", "causing_screen_description", 1),
            "codex_causing_screen_description_screenshot_run1":
                ("codex", "causing_screen_description_screenshot", 1),
            "claude_caus_man_screen_description_screenshot_xml_run3":
                ("claude", "caus_man_screen_description_screenshot_xml", 3),
            "qwen_file_method_screen_run1": ("qwen", "file_method_screen", 1),
            "qwen_file_method_no_screen_run2": ("qwen", "file_method_no_screen", 2),
        }
        for name, expected in cases.items():
            self.assertEqual(corpus.parse_run_dir(name), expected, name)
        for name in ("RERUN_SUBSTITUTIONS.txt", "codex_original", "gemini_original_run1",
                     "claude__run1"):
            self.assertIsNone(corpus.parse_run_dir(name), name)
        on_disk = {c for _, c, _ in corpus.available_runs(DATASET)}
        self.assertEqual(on_disk, set(corpus.CONFIGS + corpus.EXTRA_CONFIGS))

    def test_log_paths(self):
        logs = corpus.logs_for(DATASET, "8")
        self.assertEqual(sorted(logs), list(corpus.AGENTS))
        self.assertEqual(logs["claude"].name, "bug-8_output.txt")
        self.assertTrue(logs["codex"].name.startswith("codex-session-rollout-"))
        self.assertEqual(logs["codex"].suffix, ".jsonl")
        self.assertEqual(logs["qwen"].name, "bug-8.log")
        self.assertEqual(logs["qwen"].parent,
                         corpus.run_dir(DATASET, "qwen", "original", 1))
        self.assertIn("claude_reference_run3",
                      str(corpus.log_path(DATASET, "claude", "reference", 3, "18")))
        self.assertIsNone(corpus.log_path(DATASET, "codex", "original", 1, "999999"))
        self.assertIsNone(corpus.log_path(DATASET, "qwen", "file_method_screen", 2, "8"))

    def test_largest_codex_rollout_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = corpus.run_dir(tmp, "codex", "original", 1) / "log-bug-8" / "logs"
            logs.mkdir(parents=True)
            (logs / "codex-session-rollout-a.jsonl").write_text("{}\n")
            (logs / "codex-session-rollout-b.jsonl").write_text("{}\n" * 50)
            (logs / "run-meta.json").write_text("{}" * 500)
            self.assertEqual(corpus.log_path(tmp, "codex", "original", 1, "8").name,
                             "codex-session-rollout-b.jsonl")

    def test_sidecars(self):
        qwen = corpus.sidecar_meta(DATASET, corpus.Key("qwen", "original", 1, "8"))
        self.assertEqual(qwen["model"], "qwen/qwen3.6-35b-a3b")
        self.assertIn("exit_code", qwen)
        codex = corpus.sidecar_meta(DATASET, corpus.Key("codex", "original", 1, "8"))
        self.assertEqual(codex["model"], "gpt-5.6-sol")
        self.assertIsNone(corpus.sidecar_meta(DATASET, corpus.Key("claude", "original", 1, "8")))

    def test_ids_and_output_paths(self):
        key = corpus.Key("codex", "title_ob", 2, "1130")
        self.assertEqual(corpus.traj_id(key), "bug-1130/codex/title_ob/run2")
        self.assertEqual(corpus.atif_path(Path("data"), key),
                         Path("data/atif/title_ob/run2/bug-1130_codex.atif.json"))
        self.assertEqual(corpus.annotation_path(Path("data"), "title_ob", 2, "1130", "jsonl"),
                         Path("data/annotation/title_ob/run2/bug-1130_actions.jsonl"))


@unittest.skipUnless(DATASET.is_dir(), "Dataset/ not present")
class OutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = outcomes.load(DATASET)

    def test_table_size_and_keys(self):
        bugs = corpus.all_bug_ids(DATASET)
        self.assertEqual(len(self.table), 3 * 3 * 17 * 50)
        self.assertEqual(set(self.table), {(a, c, r, b) for a in corpus.AGENTS
                                           for c in corpus.CONFIGS for r in corpus.RUNS
                                           for b in bugs})
        self.assertNotIn(None, set(self.table.values()))

    def test_spot_checks(self):
        self.assertIs(self.table[("claude", "manifesting_screen_description_screenshot_xml",
                                  1, "8")], False)
        self.assertIs(self.table[("qwen", "original", 1, "8")], False)
        self.assertIs(self.table[("codex", "reference", 2, "8")], False)
        self.assertIs(self.table[("qwen", "original", 1, "18")], True)
        self.assertIs(self.table[("claude", "original", 1, "8")], True)

    def test_every_cell_matches_the_csvs(self):
        folder = DATASET / outcomes.OUTCOME_SOURCE
        cells = 0
        for agent in corpus.AGENTS:
            for run in corpus.RUNS:
                with (folder / f"{agent}_run{run}.csv").open(newline="") as handle:
                    rows = list(csv.reader(handle))
                self.assertEqual(tuple(rows[0][1:]), corpus.CONFIGS)
                for row in rows[1:]:
                    for config, value in zip(rows[0][1:], row[1:]):
                        self.assertEqual(self.table[(agent, config, run, row[0])],
                                         value.strip() == "1")
                        cells += 1
        self.assertEqual(cells, 7650)

    def test_outcome_for(self):
        result = outcomes.outcome_for(self.table, "codex", "8", "reference", 2)
        self.assertIs(result["pass"], False)
        self.assertEqual(set(result["by_run"]), {"1", "2", "3"})
        self.assertEqual(result["by_run"]["2"], result["pass"])
        self.assertEqual(list(result["by_config"]), list(corpus.CONFIGS))
        self.assertEqual(result["by_config"]["reference"], result["pass"])
        default = outcomes.outcome_for(self.table, "qwen", 18)
        self.assertIs(default["pass"], True)
        extra = outcomes.outcome_for(self.table, "claude", "8", "file_method_screen", 1)
        self.assertIsNone(extra["pass"])
        self.assertEqual(set(extra["by_run"].values()), {None})


class FinalMessageTests(unittest.TestCase):
    """badges() reads the closing message from generic ATIF structure, for any agent."""

    @staticmethod
    def _trajectory(steps, final=""):
        return {"steps": [dict(step, step_id=k + 1) for k, step in enumerate(steps)],
                "extra": {"final_message": final} if final else {}}

    @staticmethod
    def _call(name, call_id="a", **arguments):
        return {"tool_call_id": call_id, "function_name": name, "arguments": arguments}

    def test_text_after_the_last_tool_call(self):
        trajectory = self._trajectory([
            {"source": "user", "message": "fix the bug"},
            {"source": "agent", "message": "Let me look.", "tool_calls": [self._call("Read")]},
            {"source": "agent", "message": "All 3 tests now pass."},
            {"source": "agent", "message": ""},
        ])
        self.assertEqual(outcomes.final_message(trajectory), "All 3 tests now pass.")

    def test_summary_survives_a_follow_up_to_a_subagent_notice(self):
        # Qwen (bug-136/qwen/original/run1): summary, the sub-agent's completion notice,
        # then a short follow-up that is also the log's own final result
        trajectory = self._trajectory([
            {"source": "agent", "message": "Build successful. Let me stop the explorer.",
             "tool_calls": [self._call("task_stop")]},
            {"source": "agent", "message": "The bug is fixed and the project compiles "
                                           "successfully. Here's a summary: ..."},
            {"source": "user", "message": 'Background agent "Explore: ..." completed.'},
            {"source": "agent", "message": "The exploration agent's findings confirm the fix."},
        ], final="The exploration agent's findings confirm the fix.")
        text = outcomes.final_message(trajectory)
        self.assertTrue(text.startswith("The bug is fixed"), text)
        self.assertTrue(text.endswith("confirm the fix."), text)
        self.assertNotIn("Let me stop", text)
        self.assertEqual(outcomes.classify_self_report(text)[0], "claims_build_only")

    def test_note_beside_the_last_plan_update_counts(self):
        # Codex (bug-130/codex/original/run2): the build claim sits beside update_plan, the
        # summary after it; a plan update alone is not a tool call that ends the run's work
        trajectory = self._trajectory([
            {"source": "agent", "message": "", "tool_calls": [
                self._call("exec_command", cmd="./gradlew assembleDebug")]},
            {"source": "agent", "message": "Both product flavors compile successfully.",
             "tool_calls": [self._call("update_plan", plan=[])]},
            {"source": "agent", "message": "**Fixed**\n- the slide now ..."},
        ])
        self.assertEqual(outcomes.final_message(trajectory), "Both product flavors compile "
                         "successfully.\n**Fixed**\n- the slide now ...")
        trajectory["steps"][1]["tool_calls"].append(self._call("Read", "b"))
        self.assertEqual(outcomes.final_message(trajectory), "**Fixed**\n- the slide now ...")

    def test_summary_in_the_same_step_as_a_plan_update(self):
        trajectory = self._trajectory([
            {"source": "agent", "message": "", "tool_calls": [self._call("exec_command")]},
            {"source": "agent", "message": "**Fixed** ... OK (1 test)",
             "tool_calls": [self._call("update_plan", "b")]},
        ])
        self.assertEqual(outcomes.final_message(trajectory), "**Fixed** ... OK (1 test)")

    def test_narration_beside_the_last_tool_call_is_not_a_closing_message(self):
        # a run cut off mid-work (bug-1202/qwen/perfect/run2, error_during_execution): the
        # last text shares its step with a tool call, or is followed by more tool calls
        last = [
            {"source": "agent", "message": "", "tool_calls": [self._call("agent")]},
            {"source": "agent", "message": "The exploration agent is still working. I'll wait.",
             "tool_calls": [self._call("list_agents", "b")]},
            {"source": "agent", "message": ""},
            {"source": "user", "message": 'Background agent "Explore: ..." was cancelled.'},
        ]
        earlier = [
            {"source": "agent", "message": "The agent is still running. Let me wait.",
             "tool_calls": [self._call("list_agents")]},
            {"source": "agent", "message": "", "tool_calls": [self._call("list_agents", "b")]},
        ]
        for steps in (last, earlier):
            self.assertEqual(outcomes.final_message(self._trajectory(steps)), "")
            self.assertEqual(outcomes.final_message(self._trajectory(steps, "BUILD SUCCESSFUL")),
                             "BUILD SUCCESSFUL")
        self.assertEqual(outcomes.badges(self._trajectory(last), [], None)[0]["self_report"],
                         "empty")

    def test_self_report_is_strict(self):
        classify = outcomes.classify_self_report
        self.assertEqual(classify("All 5 tests pass.")[0], "claims_suite_pass")
        self.assertEqual(classify("Build successful.")[0], "claims_build_only")
        self.assertEqual(classify("4 passed, 1 failed; all others pass")[0], "reports_failure")
        self.assertEqual(classify("")[0], "empty")

    def test_content_parts(self):
        trajectory = self._trajectory([
            {"source": "agent", "message": [{"type": "text", "text": "Fixed; OK (1 test)"},
                                            {"type": "image", "source": {"path": "x.png"}}]},
        ])
        self.assertEqual(outcomes.classify_self_report(outcomes.final_message(trajectory))[0],
                         "claims_target_pass")


class SelectionTests(unittest.TestCase):
    def _select(self, argv, **kwargs):
        parser = cli.build_parser()
        args = parser.parse_args(argv)
        return cli.selection(args, **kwargs)

    def test_defaults(self):
        sel = self._select(["segment", "bug-8", "18"])
        self.assertEqual(sel, cli.Selection(corpus.AGENTS, ("original",), (1, 2, 3), ("8", "18")))
        self.assertIsNone(self._select(["validate"], default_all_bugs=True).bugs)
        with self.assertRaises(SystemExit):
            self._select(["segment"])

    def test_config_and_runs(self):
        sel = self._select(["convert", "--all", "--config", "all", "file_method_screen",
                            "--runs", "2", "1", "2", "--agent", "qwen"])
        self.assertEqual(sel.configs, corpus.CONFIGS + ("file_method_screen",))
        self.assertEqual(sel.runs, (1, 2))
        self.assertEqual(sel.agents, ("qwen",))
        self.assertIsNone(sel.bugs)
        with self.assertRaises(SystemExit):
            self._select(["convert", "8", "--config", "code_localization_tests"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.build_parser().parse_args(["convert", "8", "--agent", "gemini"])

    def test_flags_round_trip(self):
        sel = self._select(["convert", "8", "--config", "perfect", "--runs", "3",
                            "--agent", "codex"])
        self.assertEqual(self._select(["convert"] + cli.selection_flags(sel)), sel)

    def test_ids_anywhere_but_not_with_all(self):
        sel = self._select(["actions", "8", "--config", "original", "--agent", "qwen", "18",
                            "--runs", "1", "--agent", "qwen", "44"])
        self.assertEqual(sel, cli.Selection(("qwen",), ("original",), (1,), ("8", "18", "44")))
        self.assertEqual(self._select(["segment", "--runs", "2", "--agent", "codex", "8"]).bugs,
                         ("8",))
        with self.assertRaises(SystemExit):
            self._select(["segment", "--all", "8", "--runs", "1"])
        with self.assertRaises(SystemExit):     # an id straight after --runs is a run
            self._select(["segment", "--runs", "1", "18"])
        args = cli.build_parser().parse_args(["output", "--run", "2", "18", "codex", "call_1"])
        self.assertEqual((args.bug_id, args.agent, args.call_id, args.run),
                         ("18", "codex", "call_1", 2))

    def test_list_defaults_to_every_config(self):
        sel = self._select(["list"], default_all_bugs=True)
        self.assertEqual(sel.configs, corpus.CONFIGS + corpus.EXTRA_CONFIGS)
        self.assertEqual(self._select(["list", "--config", "perfect"],
                                      default_all_bugs=True).configs, ("perfect",))


class ReportNameTests(unittest.TestCase):
    """A narrower validation never overwrites the report of the whole corpus."""

    def _name(self, sel, dataset=None):
        return cli.report_name("atif", "raw", sel, dataset)

    def test_whole_corpus_keeps_the_plain_name(self):
        whole = cli.Selection(corpus.AGENTS, corpus.CONFIGS, corpus.RUNS, None)
        self.assertEqual(self._name(whole), "atif-raw")
        self.assertEqual(self._name(whole._replace(configs=tuple(reversed(corpus.CONFIGS)))),
                         "atif-raw")
        self.assertEqual(self._name(whole._replace(runs=(2,))), "atif-raw-all-r2")
        with_extra = whole._replace(configs=corpus.CONFIGS + corpus.EXTRA_CONFIGS)
        self.assertEqual(self._name(with_extra), "atif-raw-all+file_method_screen-r123")

    def test_selection_in_the_name(self):
        sel = cli.Selection(corpus.AGENTS, ("original",), (1, 2, 3), None)
        self.assertEqual(self._name(sel), "atif-raw-original-r123")
        self.assertEqual(self._name(cli.Selection(("qwen",), ("original",), (2,), ("18",))),
                         "atif-raw-original-r2-qwen-bug18")
        self.assertEqual(self._name(cli.Selection(("claude", "codex"), ("perfect", "original"),
                                                  (1,), ("8", "18"))),
                         "atif-raw-original+perfect-r1-claude+codex-bug8+18")
        many = cli.Selection(corpus.AGENTS, corpus.CONFIGS[:5], (1,),
                             tuple(str(b) for b in range(10)))
        self.assertRegex(self._name(many), r"^atif-raw-5configs-[0-9a-f]{6}-r1-10bugs-[0-9a-f]{6}$")
        other = many._replace(bugs=many.bugs[:9] + ("99",))
        self.assertNotEqual(self._name(many), self._name(other))
        self.assertEqual(cli.report_name("harbor", "converted", None), "harbor-files")

    @unittest.skipUnless(DATASET.is_dir(), "Dataset/ not present")
    def test_every_bug_named_is_every_bug(self):
        ids = tuple(corpus.all_bug_ids(DATASET))
        whole = cli.Selection(corpus.AGENTS, corpus.CONFIGS, corpus.RUNS, ids)
        self.assertEqual(self._name(whole, DATASET), "atif-raw")
        self.assertNotEqual(self._name(whole), "atif-raw")       # no dataset to compare with

    def test_covered(self):
        keys = [corpus.Key("codex", "perfect", 2, "18"), corpus.Key("claude", "original", 1, "8")]
        self.assertEqual(cli.covered(keys), cli.Selection(("claude", "codex"),
                                                          ("original", "perfect"), (1, 2),
                                                          ("8", "18")))


@unittest.skipUnless(DATASET.is_dir(), "Dataset/ not present")
class CliSmokeTests(unittest.TestCase):
    """convert one bug of original/run1 for Claude and Codex, then validate it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="trajparse-test-")
        cls.base = ["--dataset", str(DATASET), "--out", cls.tmp]
        cls.selection = ["8", "--runs", "1", "--agent", "claude", "--agent", "codex"]
        cls.code, cls.log = _quiet(cli.main, cls.base + ["convert"] + cls.selection
                                   + ["--jobs", "2"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_convert_writes_the_nested_layout(self):
        self.assertEqual(self.code, 0, self.log)
        out = Path(self.tmp)
        for agent in ("claude", "codex"):
            key = corpus.Key(agent, "original", 1, "8")
            trajectory = json.loads(corpus.atif_path(out, key).read_text())
            extra = trajectory["extra"]
            self.assertEqual((extra["bug_id"], extra["agent"], extra["config"], extra["run"],
                              extra["dataset"]), ("8", agent, "original", 1, "Dataset"))
            self.assertEqual(DATASET / extra["raw_log"], corpus.log_path(DATASET, *key))
            self.assertTrue(corpus.reading_path(out, key).is_file())
        with corpus.annotation_path(out, "original", 1, "8").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({r["agent"] for r in rows}, {"claude", "codex"})
        self.assertEqual({(r["config"], r["run"]) for r in rows}, {("original", "1")})
        self.assertTrue(corpus.annotation_path(out, "original", 1, "8", "jsonl").is_file())
        self.assertFalse(any((out / "atif").glob("*.atif.json")))     # nothing flat

    def _report(self, name):
        return json.loads((Path(self.tmp) / "validation" / f"{name}.json").read_text())

    def test_validate_converted_and_raw(self):
        code, log = _quiet(cli.main, self.base + ["validate"] + self.selection)
        self.assertEqual(code, 0, log)
        report = self._report("atif-converted-original-r1-claude+codex-bug8")
        self.assertEqual(report["totals"]["valid"], 2)
        self.assertEqual(report["by_agent_config"]["codex/original"]["valid"], 1)
        # a narrower run writes its own report and leaves the wider one alone
        code, log = _quiet(cli.main, self.base + ["validate", "8", "--runs", "1",
                                                  "--agent", "codex"])
        self.assertEqual(code, 0, log)
        self.assertEqual(self._report("atif-converted-original-r1-codex-bug8")["totals"]["valid"],
                         1)
        self.assertEqual(self._report("atif-converted-original-r1-claude+codex-bug8")
                         ["totals"]["valid"], 2)
        code, log = _quiet(cli.main, self.base + ["validate", "--from-raw", "--jobs", "1"]
                           + self.selection)
        self.assertEqual(code, 0, log)
        report = self._report("atif-raw-original-r1-claude+codex-bug8")
        self.assertEqual((report["source"], report["totals"]["valid"]), ("raw", 2))
        self.assertFalse((Path(self.tmp) / "validation" / "atif-raw.json").exists())

    @unittest.skipUnless(shutil.which("uv"), "uv not installed")
    def test_harbor_validator_in_one_process(self):
        # skip only when uv cannot provide harbor at all; any failure after that is a failure
        probe = subprocess.run(cli.HARBOR_CMD[:-2] + ["-c", "import harbor.utils."
                                                            "trajectory_validator"],
                               cwd=str(HERE.parent), capture_output=True, text=True)
        if probe.returncode != 0:
            self.skipTest("harbor not available to uv: " + probe.stderr.strip()[-200:])
        proc = subprocess.run(cli.HARBOR_CMD + ["--out", self.tmp, str(Path(self.tmp) / "atif")],
                              cwd=str(HERE.parent), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = self._report("harbor-converted-original-r1-claude+codex-bug8")
        self.assertEqual((report["validator"], report["totals"]["valid"]), ("harbor", 2))
        self.assertEqual(report["selection"]["agents"], ["claude", "codex"])

    def test_list_applies_the_selection(self):
        code, log = _quiet(cli.main, ["--dataset", str(DATASET), "list", "8", "18", "--config",
                                      "original", "perfect", "file_method_screen",
                                      "--agent", "qwen", "--runs", "1", "3"])
        self.assertEqual(code, 0, log)
        self.assertIn("total 10 logs (8 in the 17 outcome configs): qwen 10", log)
        self.assertNotIn("reference", log)

    def test_converting_one_agent_keeps_the_others_rows(self):
        code, log = _quiet(cli.main, self.base + ["convert", "8", "--runs", "1",
                                                  "--agent", "codex", "--jobs", "1"])
        self.assertEqual(code, 0, log)
        with corpus.annotation_path(Path(self.tmp), "original", 1, "8").open() as handle:
            agents = Counter(r["agent"] for r in csv.DictReader(handle))
        self.assertEqual(set(agents), {"claude", "codex"})


if __name__ == "__main__":
    unittest.main()
