"""Rule sets, uploads and the local server (``atif.rules``, ``atif.upload``, ``atif.serve``).

The default rule set must reproduce ``atif.phase`` exactly (checked on original/run1); each
kind of custom rule and each setting is pinned on a small synthetic trajectory built with
the helpers of ``test_segment``; an upload is analysed from a raw log of every agent.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path

from atif import corpus, phase, rules, serve, upload, view
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

    def test_mandatory_rules_cannot_be_named_switched_off_or_removed(self):
        for ruleset in ({"optional": [{"id": "G4"}]}, {"optional": ["G1"]},
                        {"settings": {"keep_attempts": False}},
                        {"settings": {"smoothing": False}},
                        {"optional": [{"id": "G7", "value": 2}]},
                        {"optional": [{"id": "F1", "value": 5}]},
                        {"custom": [{"id": "G2", "kind": "phase", "match": "x",
                                     "value": "repair"}]}):
            with self.assertRaises(rules.RuleError, msg=ruleset):
                rules.normalize(ruleset)
        self.assertEqual([r["id"] for r in rules.mandatory()],
                         [f"G{k}" for k in range(1, 8)] + ["F1"])
        self.assertEqual([r["id"] for r in rules.OPTIONAL], ["O1", "O2", "O3", "O4"])

    def test_older_files_that_restate_the_mandatory_rules_are_read(self):
        old = [{"settings": {"keep_attempts": True, "smoothing": True, "absorb_max": 1,
                             "repeated_reads": 3}},
               {"optional": [{"id": "G7", "value": 1}, {"id": "F1", "value": 3}, {"id": "O2"}]}]
        self.assertEqual(rules.normalize(old[0])["optional"], [])
        self.assertEqual(rules.normalize(old[1])["optional"], [{"id": "O2"}])

    def test_bad_rule_sets_are_refused_with_a_message(self):
        bad = [
            {"settings": {"absorb_max": 0}},
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
            "Actions whose tool name contains “update_plan” follow the work around them.",
            "Actions whose command or target contains “lint” count as build.",
            "Files whose path contains “sharedTest/” are test files."])

    def test_builtin_sentences_fill_in_the_numbers(self):
        listed = rules.builtin(rules.normalize({"optional": [{"id": "O3"}]}))
        g7 = next(r for r in listed if r["id"] == "G7")
        self.assertIn("at most 1 action", g7["sentence"])
        self.assertEqual({r["id"]: r["on"] for r in listed if not r["mandatory"]},
                         {"O1": False, "O2": False, "O3": True, "O4": False})
        self.assertTrue(all(r["on"] for r in listed if r["mandatory"]))
        self.assertTrue(all("{n}" not in r["sentence"] for r in rules.builtin()))


class RuleTests(unittest.TestCase):
    def test_default_rule_set_is_atif_phase(self):
        a, b = phase.phases(_traj(_calls()), "1"), _phases()
        self.assertEqual(a["phase"], b["phase"])
        self.assertEqual(a["metrics"], b["metrics"])

    def test_mandatory_rules_always_apply(self):
        traj = _traj(_calls())
        b = rules.phases(traj, "1", {"optional": [], "custom": []})
        self.assertEqual(phase.phases(traj, "1")["phase"], b["phase"])
        self.assertTrue(b["attempts"])                     # G4
        self.assertEqual(len(b["rules"]["mandatory"]), 8)

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
                 _call("Read", {"file_path": "README.md"}, "# App"),
                 _sh("./gradlew ktlintCheck", LINT_OUT)] + _calls()
        base = rules.phases(_traj(calls), "1", None)
        r = rules.phases(_traj(calls), "1", {"optional": [{"id": "O1"}, {"id": "O3"}]})
        self.assertEqual((base["phase"][1], r["phase"][1]), ("localization", "understanding"))
        self.assertEqual(r["actions"][2]["category"], "build")
        report = {o["id"]: o for o in r["rules"]["optional"]}
        self.assertEqual(report["O3"]["matched"], [2])
        self.assertIn(3, report["O1"]["matched"])
        self.assertNotIn("matched", report["O2"])          # not added: did not run
        shared = [_sh("apply_patch <<'P'\n*** Begin Patch\n*** Update File: "
                      "app/src/sharedTest/java/FooTest.java\n@@\n-a\n+b\n*** End Patch\nP",
                      "Success")] + _calls()
        self.assertEqual(rules.phases(_traj(shared), "1", None)["anchor"], 1)
        self.assertEqual(rules.phases(_traj(shared), "1", {"optional": [{"id": "O2"}]})["anchor"], 6)

    def test_category_rule_changes_the_category_and_the_verdict(self):
        base = _phases()["actions"][3]
        self.assertEqual((base["category"], base["verdict"]), ("build", "pass"))
        r = _phases(_rule(kind="category", match="lint", value="run_test"))
        lint = r["actions"][3]
        self.assertEqual(lint["category"], "run_test")
        self.assertEqual(r["rules"]["custom"][0]["matched"], [4])

    def test_phase_rule_applies_and_survives_smoothing(self):
        r = _phases(_rule(kind="phase", match="rg -n", value="understanding"))
        self.assertEqual(r["phase"][1], "understanding")
        self.assertEqual(r["rules"]["custom"][0]["matched"], [2])

    def test_phase_rule_never_breaks_the_first_fix(self):
        r = _phases(_rule(kind="phase", match="git status", value="reproduction"))
        rep = r["rules"]["custom"][0]
        self.assertEqual(rep["matched"], [])
        self.assertEqual(rep["skipped"][0]["i"], 9)
        self.assertIn("before the first fix", rep["skipped"][0]["why"])
        r = _phases(_rule(kind="phase", match="apply_patch", value="validation"))
        self.assertTrue(all(s["why"].startswith("an edit of app source")
                            for s in r["rules"]["custom"][0]["skipped"]))

    def test_follow_rule_takes_the_phase_before(self):
        r = _phases(_rule(kind="phase", field="tool", match="update_plan", value="follow"))
        self.assertEqual(r["phase"][2], r["phase"][1])

    def test_file_role_rule_moves_the_first_fix(self):
        self.assertEqual(_phases()["anchor"], 5)
        r = _phases(_rule(kind="file_role", match="Foo.java", value="test"))
        self.assertIsNone(r["anchor"])                   # no app source is edited any more
        self.assertNotIn("source", r["actions"][0]["file_roles"])
        # the swap is undone afterwards
        self.assertEqual(_phases()["anchor"], 5)

    def test_disabled_rule_does_nothing(self):
        ruleset = _rule(kind="phase", match="rg -n", value="understanding", enabled=False)
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

    def _post(self, body: dict):
        req = urllib.request.Request(self.base + "/api/analyze", json.dumps(body).encode(),
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
                         [f"G{k}" for k in range(1, 8)] + ["F1"])
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

    def test_errors_are_400_with_a_message(self):
        self.assertEqual(self._post({"name": "a", "text": "nope"})[0], 400)
        status, res = self._post({"name": "a", "text": "nope",
                                  "rules": _rule(kind="phase", match="x", value="y")})
        self.assertEqual(status, 400)
        self.assertIn("phase must be one of", res["error"])


if __name__ == "__main__":
    unittest.main()
