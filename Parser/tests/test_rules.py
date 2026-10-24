"""Rule sets, uploads, the local server and the in-browser engine (``atif.rules``,
``atif.upload``, ``atif.serve``, ``atif.engine``).

The default rule set must reproduce ``atif.phase`` exactly (checked on original/run1); each
kind of custom rule and each setting is pinned on a small synthetic trajectory built with
the helpers of ``test_segment``; an upload is analysed from a raw log of every agent.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path

from atif import corpus, engine, lookup, phase, rules, serve, upload, view
from tests.test_segment import (DATASET, HAVE_DATASET, PATCH, SRC, TEST, TEST_FAILS,
                                TEST_PASSES, _call, _run1, _sh, _traj)

LINT = "./gradlew lint"
LINT_OUT = "> Task :app:lint\n\nBUILD SUCCESSFUL in 3s\nProcess exited with code 0"


def _calls() -> list:
    """read, search, plan, lint, fix (PATCH), test fails, fix, test passes, git status."""
    return [
        _sh(f"sed -n '1,40p' {SRC}", "class Foo {}"),
        _sh("rg -n Foo app/src", f"{SRC}:3: class Foo"),
        _call("update_plan", {"plan": [{"step": "fix", "status": "in_progress"}]}, "ok"),
        _sh(LINT, LINT_OUT),
        _sh(PATCH, "Success"),
        _sh(TEST, TEST_FAILS),
        _sh(PATCH, "Success"),
        _sh(TEST, TEST_PASSES),
        _sh("git status --short", f" M {SRC}"),
    ]


def _phases(ruleset=None, calls=None) -> dict:
    return rules.phases(_traj(calls or _calls()), "1", ruleset)


def _rule(**kw) -> dict:
    return {"custom": [dict({"field": "target"}, **kw)]}


class NormalizeTests(unittest.TestCase):
    def test_defaults(self):
        r = rules.normalize(None)
        self.assertEqual(r["optional"], [])                # optional rules: none by default
        self.assertEqual(r["custom"], [])
        self.assertEqual(rules.normalize(rules.default_ruleset()), r)

    def test_built_in_rows_cannot_be_named_switched_off_or_removed(self):
        for ruleset in ({"optional": [{"id": "L4"}]}, {"optional": ["LG"]},
                        {"optional": [{"id": "F1", "value": 5}]},
                        {"settings": {"repeated_reads": 2}},
                        {"custom": [{"id": "L2", "kind": "phase", "match": "x",
                                     "value": "repair"}]}):
            with self.assertRaises(rules.RuleError, msg=ruleset):
                rules.normalize(ruleset)
        self.assertEqual([r["id"] for r in rules.mandatory()],
                         [f"L{k}" for k in range(1, 16)] + ["LG", "F1"])
        self.assertEqual([r["table"] for r in rules.mandatory()][:16], [4] * 16)
        self.assertEqual([r["id"] for r in rules.OPTIONAL], ["O1", "O2", "O3", "O4"])

    def test_older_rule_files_are_read_without_their_grouping_rules(self):
        old = [{"schema": "trajectiers-rules/1",
                "settings": {"keep_attempts": False, "smoothing": False, "absorb_max": 3,
                             "repeated_reads": 3}},
               {"schema": "trajectiers-rules/2",
                "optional": [{"id": "G7", "value": 1}, {"id": "G4"}, {"id": "F1", "value": 3},
                             {"id": "O2"}]}]
        self.assertEqual(rules.normalize(old[0]), rules.normalize(None))
        self.assertEqual(rules.normalize(old[1])["optional"], [{"id": "O2"}])
        self.assertEqual(rules.normalize(old[1])["schema"], rules.SCHEMA)

    def test_files_of_codebook_version_4_are_read_in_the_final_tables_words(self):
        v4 = {"optional": [{"id": "P4"}, "FW"], "custom": [
            {"kind": "category", "match": "lint", "value": "run_test"},
            {"kind": "file_role", "match": "gradle/", "value": "toolchain"},
            {"kind": "file_role", "match": ".log", "value": "output"},
            {"kind": "phase", "match": "README", "value": "understanding"}]}
        r = rules.normalize(v4)
        self.assertEqual(r["optional"], [])               # Table 4 and follow: built in no more
        self.assertEqual([x["value"] for x in r["custom"]], ["test", "build", "other", "planning"])

    def test_bad_rule_sets_are_refused_with_a_message(self):
        bad = [
            {"schema": "trajectiers-rules/9"},
            {"settings": {"nope": 1}},
            {"optional": [{"id": "X9"}]},
            {"optional": "G7"},
            _rule(kind="colour", match="x", value="repair"),
            _rule(kind="phase", match=" ", value="repair"),
            _rule(kind="phase", match="x", value="debugging"),
            _rule(kind="category", match="x", value="repair"),
            _rule(kind="phase", match="(", regex=True, value="repair"),
            {"custom": [{"id": "A", "kind": "phase", "match": "x", "value": "repair"},
                        {"id": "A", "kind": "phase", "match": "y", "value": "repair"}]},
        ]
        for ruleset in bad:
            with self.assertRaises(rules.RuleError, msg=ruleset):
                rules.normalize(ruleset)

    def test_sentences(self):
        r = rules.normalize({"custom": [
            {"kind": "phase", "field": "tool", "match": "update_plan", "value": "follow"},
            {"kind": "category", "match": "lint", "value": "build"},
            {"kind": "file_role", "match": "sharedTest/", "value": "test"}]})["custom"]
        self.assertEqual([rules.describe(x) for x in r], [
            "Steps whose tool contains “update_plan” take the phase of the step before.",
            "Steps whose command contains “lint” are build.",
            "Files whose path contains “sharedTest/” are test files."])
        self.assertEqual(len(rules.tables()["phases"]), len(rules.BUILTIN) - 2)   # L1-L15
        self.assertEqual([a["type"] for a in rules.tables()["actions"]], list(lookup.CATEGORIES))
        self.assertEqual(rules.describe(rules.normalize({"custom": [
            {"kind": "file_role", "match": "/tmp/", "value": "outside"}]})["custom"][0]),
            "Files whose path contains “/tmp/” are outside the repository.")

    def test_builtin_sentences_fill_in_the_numbers(self):
        listed = rules.builtin(rules.normalize({"optional": [{"id": "O3"}]}))
        f1 = next(r for r in listed if r["id"] == "F1")
        self.assertIn("3 or more times", f1["sentence"])
        l6 = next(r for r in listed if r["id"] == "L6")
        self.assertEqual(l6["sentence"], "test, before the first edit of a source file → "
                                         "localization.")
        l14 = next(r for r in listed if r["id"] == "L14")
        self.assertIn("→ the phase of the previous step", l14["sentence"])
        lg = next(r for r in listed if r["id"] == "LG")
        self.assertEqual(lg["sentence"], lookup.GENERAL_RULE)
        self.assertEqual({r["id"]: r["on"] for r in listed if not r["mandatory"]},
                         {"O1": False, "O2": False, "O3": True, "O4": False})
        self.assertTrue(all(r["on"] for r in listed if r["mandatory"]))
        self.assertTrue(all("{n}" not in r["sentence"] for r in rules.builtin()))


class RuleTests(unittest.TestCase):
    def test_default_rule_set_is_atif_phase(self):
        a, b = phase.phases(_traj(_calls()), "1"), _phases()
        self.assertEqual(a["phase"], b["phase"])
        self.assertEqual(a["metrics"], b["metrics"])

    def test_built_in_rows_always_apply(self):
        traj = _traj(_calls())
        b = rules.phases(traj, "1", {"optional": [], "custom": []})
        self.assertEqual(phase.phases(traj, "1")["phase"], b["phase"])
        self.assertTrue(b["attempts"])
        self.assertEqual(len(b["rules"]["mandatory"]), 17)        # L1-L15, LG, F1

    def test_web_lookups_rule(self):
        calls = [_call("Read", {"file_path": SRC}, "class Foo"), _sh("ls", "app"),
                 _call("WebSearch", {"query": "android fragment manager"}, "results"),
                 _sh("ls", "app")] + _calls()
        base = rules.phases(_traj(calls), "1", None)
        r = rules.phases(_traj(calls), "1", {"optional": ["O4"]})
        self.assertEqual(r["phase"][2], "localization")
        self.assertEqual({o["id"]: o.get("matched") for o in r["rules"]["optional"]}["O4"], [3])
        self.assertEqual(base["phase"][2], base["phase"][1])

    def test_ready_made_optional_rules(self):
        calls = [_call("Read", {"file_path": SRC}, "class Foo"),
                 _sh(f"cat README.md {SRC}", "# App"),
                 _sh("./gradlew ktlintCheck", LINT_OUT)] + _calls()
        base = rules.phases(_traj(calls), "1", None)
        r = rules.phases(_traj(calls), "1", {"optional": [{"id": "O1"}, {"id": "O3"}]})
        # docs and code in one read is not docs only (row 5); O3 makes it planning
        self.assertEqual((base["phase"][1], r["phase"][1]), ("localization", "planning"))
        self.assertEqual(r["actions"][2]["category"], "build")
        report = {o["id"]: o for o in r["rules"]["optional"]}
        self.assertEqual(report["O3"]["matched"], [2])
        self.assertIn(3, report["O1"]["matched"])
        self.assertNotIn("matched", report["O2"])          # not added: did not run
        shared = [_sh("apply_patch <<'P'\n*** Begin Patch\n*** Update File: "
                      "app/src/sharedTest/java/FooHelper.java\n@@\n-a\n+b\n*** End Patch\nP",
                      "Success")] + _calls()
        self.assertEqual(rules.phases(_traj(shared), "1", None)["anchor"], 1)
        self.assertEqual(rules.phases(_traj(shared), "1", {"optional": [{"id": "O2"}]})["anchor"], 6)

    def test_category_rule_changes_the_category_and_the_verdict(self):
        # ./gradlew lint is a test task in the action table; its verdict is read as the
        # taxonomy reads it (a build's), until a row of the user's says otherwise
        base = _phases()["actions"][3]
        self.assertEqual((base["category"], base["verdict"], base["mid_level"]),
                         ("test", "pass", "build"))
        as_test = _phases(_rule(kind="category", match="lint", value="test"))["actions"][3]
        self.assertEqual((as_test["category"], as_test["mid_level"], as_test["lookup_item"]),
                         ("test", "run_test", "your rule R1"))
        r = _phases(_rule(kind="category", match="lint", value="build"))
        lint = r["actions"][3]
        self.assertEqual((lint["category"], lint["mid_level"], lint["lookup_item"]),
                         ("build", "build", "your rule R1"))
        self.assertEqual(r["phase"][3], "planning")        # a build before the fix: row 4
        self.assertEqual(r["rules"]["custom"][0]["matched"], [4])

    def test_phase_row_replaces_the_table_value(self):
        r = _phases(_rule(kind="phase", match="rg -n", value="planning"))
        self.assertEqual(r["phase"][1], "planning")
        self.assertEqual(r["table_row"][1], "user")
        self.assertEqual(r["rules"]["custom"][0]["matched"], [2])
        self.assertEqual(r["rules"]["custom"][0]["table"], 4)

    def test_phase_rule_never_breaks_the_first_fix(self):
        r = _phases(_rule(kind="phase", match="gradlew lint", value="validation"))
        rep = r["rules"]["custom"][0]
        self.assertEqual(rep["matched"], [])
        self.assertEqual(rep["skipped"][0]["i"], 4)
        self.assertIn("from the first fix on", rep["skipped"][0]["why"])
        r = _phases(_rule(kind="phase", match="apply_patch", value="validation"))
        self.assertTrue(all(s["why"].startswith("an edit of a source file")
                            for s in r["rules"]["custom"][0]["skipped"]))

    def test_a_reproduction_row_of_an_older_file_is_localization(self):
        r = _phases(_rule(kind="phase", match="git status", value="reproduction"))
        self.assertEqual(r["rules"]["custom"][0]["value"], "localization")
        self.assertEqual(r["phase"][8], "localization")

    def test_follow_rule_takes_the_phase_before(self):
        r = _phases(_rule(kind="phase", field="tool", match="update_plan", value="follow"))
        self.assertEqual(r["phase"][2], r["phase"][1])

    def test_file_role_rule_moves_the_first_fix(self):
        self.assertEqual(_phases()["anchor"], 5)
        r = _phases(_rule(kind="file_role", match="Foo.java", value="test"))
        self.assertIsNone(r["anchor"])                   # no app source is edited any more
        self.assertNotIn("source", r["actions"][0]["target_kinds"])
        # the swap is undone afterwards
        self.assertEqual(_phases()["anchor"], 5)

    def test_disabled_rule_does_nothing(self):
        ruleset = _rule(kind="phase", match="rg -n", value="planning", enabled=False)
        self.assertEqual(_phases(ruleset)["phase"], _phases()["phase"])


@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class CorpusRuleTests(unittest.TestCase):
    def test_default_rule_set_reproduces_original_run1(self):
        for key, traj in _run1():
            a, b = phase.phases(traj, key.bug), rules.phases(traj, key.bug, None)
            self.assertEqual((a["phase"], a["own_phase"], a["metrics"]),
                             (b["phase"], b["own_phase"], b["metrics"]), key)


@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class UploadTests(unittest.TestCase):
    def test_each_agent_s_raw_log(self):
        for agent in corpus.AGENTS:
            path = corpus.log_path(DATASET, agent, "original", 1, "18")
            res = upload.analyze_path(path, outcome=True)
            t = res["trajectory"]
            view.check_view(t, name=agent)
            self.assertEqual((res["source"]["agent"], res["source"]["bug"]), (agent, "18"))
            self.assertTrue(res["source"]["bug_inferred"])
            self.assertIs(t["outcome"]["pass"], True)
            self.assertEqual(res["schema"], upload.SCHEMA)

    def test_an_atif_file(self):
        path = corpus.log_path(DATASET, "codex", "original", 1, "18")
        first = upload.analyze_path(path)
        from atif import detect
        text = json.dumps(detect.parse(path, extra={"bug_id": "18"}))
        res = upload.analyze(text, "x.atif.json")
        self.assertEqual(res["source"]["format"], "atif")
        self.assertEqual(res["trajectory"]["phases"], first["trajectory"]["phases"])

    def test_a_json_array_of_events(self):
        path = corpus.log_path(DATASET, "qwen", "original", 1, "18")
        events = [json.loads(line) for line in path.read_text().splitlines()
                  if line.startswith("{")]
        res = upload.analyze(json.dumps(events, indent=2), "bug-18.json")
        self.assertEqual(res["trajectory"]["phases"],
                         upload.analyze_path(path)["trajectory"]["phases"])

    def test_not_a_trajectory(self):
        for text in ("", "hello world", '{"a": 1}'):
            with self.assertRaises(upload.UploadError):
                upload.analyze(text, "x.txt")


class PackTests(unittest.TestCase):
    """Corpus packs (``view.write_packs``), re-run in the viewer under a user's rules
    (``upload.reanalyze`` / ``corpus_request``)."""
    VIEWER = Path(__file__).resolve().parent.parent / "viewer"

    def _pack(self, run: int = 1, bug: str = "18") -> dict:
        path = view.pack_file(self.VIEWER, run, bug)
        if not path.is_file():
            self.skipTest(f"{path.name} not written (python3 -m atif.cli view --all)")
        return json.loads(gzip.decompress(path.read_bytes()))

    def test_default_rules_give_the_exported_views(self):
        pack = self._pack()
        if not HAVE_DATASET:
            self.skipTest("Dataset/ not present")
        exported, _views, _missing = view.build_bug(self.VIEWER.parent / "data", DATASET, "18",
                                                    runs=[1])
        got = upload.reanalyze(pack)["views"]
        for t in exported["trajectories"]:
            mine = {k: v for k, v in got[t["agent"]].items() if k not in ("outcome", "app", "rule_hits")}
            self.assertEqual(mine, {k: v for k, v in t.items() if k not in ("outcome", "app")})

    def test_summary_and_rule_hits(self):
        res = upload.corpus_request({"packs": [self._pack()], "summary": True,
                                     "rules": {"optional": [{"id": "O3"}]}})
        views = res["packs"][0]["views"]
        self.assertEqual(set(views), {"claude", "codex", "qwen"})
        self.assertIn("sub_strip", views["claude"])
        self.assertNotIn("actions", views["claude"])
        self.assertTrue(any(v["rule_hits"].get("O3") for v in views.values()))
        self.assertTrue([r for r in res["vocab"]["rules"] if r["id"] == "O3"][0]["on"])

    def test_errors_are_data(self):
        self.assertIn("expected", upload.corpus_request({})["error"])
        self.assertIn("not a corpus pack", upload.corpus_request({"packs": [{}]})["error"])
        res = upload.corpus_request({"packs": [], "rules": {"optional": [{"id": "L1"}]}})
        self.assertIn("built-in", res["error"])

    def test_packs_are_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(__file__).resolve().parent.parent / "data"
            if not corpus.atif_path(out, corpus.Key("claude", "original", 1, "18")).is_file():
                self.skipTest("data/atif not converted")
            first = view.write_packs(out, Path(tmp), runs=[1], bug_ids=["18"])
            data = view.pack_file(Path(tmp), 1, "18").read_bytes()
            view.write_packs(out, Path(tmp), runs=[1], bug_ids=["18"])
            self.assertEqual(first["files"], 1)
            self.assertEqual(data, view.pack_file(Path(tmp), 1, "18").read_bytes())


class EngineTests(unittest.TestCase):
    """The zip the hosted Analyze page runs with Pyodide (``viewer/engine/atif.zip``)."""
    VIEWER = Path(__file__).resolve().parent.parent / "viewer"

    def test_the_viewer_ships_the_current_package(self):
        self.assertTrue(engine.current(self.VIEWER),
                        "viewer/engine/atif.zip is older than atif/: run python3 -m atif.cli engine")

    def test_the_zip_is_deterministic_and_leaves_out_the_server(self):
        self.assertEqual(engine.build(), engine.build())
        self.assertIn("atif/upload.py", engine.sources())
        self.assertFalse({"atif/cli.py", "atif/serve.py", "atif/harbor_check.py"}
                         & set(engine.sources()))

    def test_the_zipped_package_runs_on_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            zipped = Path(tmp) / "atif.zip"
            zipped.write_bytes(engine.build())
            code = ("import sys, json; sys.path.insert(0, sys.argv[1]); from atif import upload; "
                    "print(json.dumps(upload.request({'name': 'a', 'text': 'nope'})))")
            out = subprocess.run([sys.executable, "-I", "-c", code, str(zipped)],
                                 capture_output=True, text=True, cwd=tmp)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("error", json.loads(out.stdout))

    def test_request_answers_errors_as_data(self):
        self.assertIn("expected", upload.request("not a dict")["error"])
        self.assertIn("error", upload.request({"name": "a", "text": "nope"}))
        res = upload.request({"name": "a", "text": "nope",
                              "rules": _rule(kind="phase", match="x", value="y")})
        self.assertIn("phase must be one of", res["error"])


@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        viewer = Path(__file__).resolve().parent.parent / "viewer"
        class Quiet(serve.Handler):
            def log_message(self, *args):
                pass
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(viewer)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _post(self, body: dict, route: str = "/api/analyze"):
        req = urllib.request.Request(self.base + route, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_rules_and_static_page(self):
        with urllib.request.urlopen(self.base + "/api/rules") as r:
            info = json.load(r)
        self.assertEqual(info["default"]["optional"], [])
        self.assertEqual([b["id"] for b in info["mandatory"]],
                         [f"L{k}" for k in range(1, 16)] + ["LG", "F1"])
        self.assertEqual(len(info["tables"]["phases"]), 15)
        self.assertEqual(info["file_roles"], list(lookup.TARGETS))
        self.assertEqual([b["id"] for b in info["optional"]], ["O1", "O2", "O3", "O4"])
        with urllib.request.urlopen(self.base + "/analyze.html") as r:
            self.assertIn(b"page-analyze.js", r.read())

    def test_analyze(self):
        text = corpus.log_path(DATASET, "qwen", "original", 1, "18").read_text()
        status, res = self._post({"name": "bug-18.log", "text": text,
                                  "rules": _rule(kind="phase", match="rg", value="localization")})
        self.assertEqual(status, 200)
        self.assertEqual(res["source"]["agent"], "qwen")
        self.assertEqual(res["rules"]["custom"][0]["id"], "R1")

    def test_corpus(self):
        if not view.pack_file(Path(__file__).resolve().parent.parent / "viewer", 1, "18").is_file():
            self.skipTest("packs not written")
        status, res = self._post({"rules": None, "summary": True,
                                  "paths": ["data/atif/run1/bug-18.json.gz"]}, "/api/corpus")
        self.assertEqual(status, 200, res)
        self.assertEqual(res["packs"][0]["bug"], "18")
        for bad in ("../atif/upload.py", "data/atif/run1/../../index.html", "data/bugs/bug-18.js"):
            status, res = self._post({"paths": [bad]}, "/api/corpus")
            self.assertEqual(status, 400)
            self.assertIn("not a corpus pack path", res["error"])

    def test_errors_are_400_with_a_message(self):
        self.assertEqual(self._post({"name": "a", "text": "nope"})[0], 400)
        status, res = self._post({"name": "a", "text": "nope",
                                  "rules": _rule(kind="phase", match="x", value="y")})
        self.assertEqual(status, 400)
        self.assertIn("phase must be one of", res["error"])


if __name__ == "__main__":
    unittest.main()
