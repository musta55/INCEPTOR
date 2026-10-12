"""Viewer data tests (``trajview/3``, ``trajview-overview/3``; ``View data contract.md``).

The contract tests build the view of every trajectory of ``Dataset/`` original/run1 (parsed
from the raw logs, so no prior ``convert`` is needed); the export test writes into a
temporary viewer directory from the converted files in ``data/atif/original/run1``.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from atif import codebook, corpus, detect, outcomes, phase, taxonomy, view  # noqa: E402

DATASET = HERE.parent.parent / "Dataset"
DATA = HERE.parent / "data"
HAVE_DATASET = DATASET.is_dir()
HAVE_CONVERTED = (DATA / "atif" / "original" / "run1" / "bug-18_claude.atif.json").is_file()

_VIEWS: list = []


def _run1_views() -> list:
    """The trajview/3 object of every agent and bug of original/run1 (built once)."""
    if not _VIEWS:
        table = outcomes.load(DATASET)
        for key, path in corpus.iter_logs(DATASET, configs=["original"], runs=[1]):
            trajectory = detect.parse(path, extra={"bug_id": key.bug})
            _VIEWS.append(view.trajectory_view(trajectory, key=key, app=None,
                                               outcome_table=table))
    return _VIEWS


def _covers(pieces: list, n: int) -> bool:
    """[label, start, end, ...] pieces in order cover 1..n exactly once."""
    pos = 1
    for piece in pieces:
        if piece[1] != pos or piece[2] < piece[1]:
            return False
        pos = piece[2] + 1
    return pos == n + 1


@unittest.skipUnless(HAVE_DATASET, "Dataset/ not present")
class ContractTests(unittest.TestCase):
    """Every view of original/run1 keeps the contract's invariants (``check_view`` runs
    inside ``trajectory_view``); the summaries and badges agree with the subphases."""

    def test_every_view_is_built(self):
        views = _run1_views()
        self.assertEqual(len(views), 150)
        for obj in views:
            self.assertEqual(obj["n_actions"], len(obj["actions"]), obj["id"])
            self.assertEqual(obj["stats"]["n_subphases"],
                             sum(len(s["subphases"]) for s in obj["phases"]), obj["id"])

    def test_summary_strips_cover_the_trajectory(self):
        for obj in _run1_views():
            summary = view.summary_view(obj)
            self.assertTrue(_covers(summary["strip"], obj["n_actions"]), obj["id"])
            self.assertTrue(_covers(summary["sub_strip"], obj["n_actions"]), obj["id"])
            self.assertEqual(sum(summary["subphases"]["by_outcome"].values()),
                             obj["stats"]["n_subphases"], obj["id"])
            self.assertNotIn("actions", summary)

    def test_badges_agree_with_the_subphases(self):
        for obj in _run1_views():
            badges, metrics = obj["badges"], obj["metrics"]
            if not metrics:                                 # no tool call at all
                continue
            self.assertEqual(badges["reproduced_before_fix"], metrics["reproduced_before_fix"])
            self.assertEqual(badges["blocked_checks"], metrics["blocked_subphases"])
            self.assertEqual(badges["test_modified"], metrics["test_modified_subphases"] > 0)
            self.assertEqual(badges["repeated_failure"],
                             metrics["repeated_failure_subphases"] > 0)
            self.assertEqual(badges["final_repair_outcome"], metrics["final_repair_outcome"])
            starts = {sp["start"] for s in obj["phases"] for sp in s["subphases"]}
            for key in ("reproduced_before_fix", "test_modified", "repeated_failure",
                        "blocked_checks", "final_repair"):
                self.assertTrue(set(obj["badge_steps"][key]) <= starts, (obj["id"], key))

    def test_attempts_are_ordered_and_judged_inside_their_range(self):
        for obj in _run1_views():
            last = 0
            for at in obj["attempts"]:
                self.assertGreater(at["start"], last, obj["id"])
                self.assertEqual(at["start"], at["edits"][0], obj["id"])
                if at["judge"] is not None:
                    self.assertEqual(at["end"], at["judge"], obj["id"])
                else:
                    self.assertEqual(at["outcome"], "unchecked", obj["id"])
                last = at["end"]

    def test_check_view_rejects_a_broken_view(self):
        obj = next(v for v in _run1_views() if len(v["phases"]) > 1)
        gap = copy.deepcopy(obj)
        gap["phases"][1]["start"] += 1
        with self.assertRaises(ValueError):
            view.check_view(gap)
        word = copy.deepcopy(obj)
        word["phases"][0]["subphases"][0]["outcome"] = "looped"
        with self.assertRaises(ValueError):
            view.check_view(word)
        label = copy.deepcopy(obj)
        label["actions"][0]["phase"] = "orientation"
        with self.assertRaises(ValueError):
            view.check_view(label)


class VocabTests(unittest.TestCase):
    """The vocabulary the viewer reads, and the codebook's words for it."""

    def test_vocab_matches_the_taxonomy(self):
        v = view.vocab()
        self.assertEqual(v["phases"], list(phase.PHASES))
        self.assertEqual(v["outcomes"], list(phase.OUTCOMES))
        self.assertEqual(v["flags"], list(phase.FLAGS))
        self.assertEqual(v["categories"], list(taxonomy.CATEGORIES))
        self.assertEqual(set(v["category_family"]), set(taxonomy.CATEGORIES))

    def test_text_quotes_every_table_row_of_the_codebook(self):
        text = view.vocab()["text"]
        self.assertEqual(set(text["phases"]), set(phase.PHASES))
        self.assertEqual(set(text["categories"]), set(taxonomy.CATEGORIES))
        self.assertEqual(set(text["flags"]), set(phase.FLAGS))
        self.assertEqual(set(text["outcomes"]), set(phase.PHASES))
        for row in codebook.OUTCOME_ROWS:
            self.assertEqual(text["outcomes"][row[0]]["check"], row[1])
            self.assertEqual([text["outcomes"][row[0]][o] for o in phase.OUTCOMES], list(row[2:]))


@unittest.skipUnless(HAVE_DATASET and HAVE_CONVERTED, "Dataset/ or converted original/run1 missing")
class ExportTests(unittest.TestCase):

    def test_export_writes_both_files_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = view.export(DATA, DATASET, Path(tmp), runs=[1], overview_run=1,
                                  bug_ids=["18"])
            self.assertEqual(summary["bug_files"], 1)
            bug = view.read_js(view.bug_file(Path(tmp), "18"))
            overview = view.read_js(view.overview_file(Path(tmp)))
        self.assertEqual(bug["schema"], view.SCHEMA)
        self.assertEqual(overview["schema"], view.OVERVIEW_SCHEMA)
        self.assertEqual([t["agent"] for t in bug["trajectories"]], list(corpus.AGENTS))
        row = next(b for b in overview["bugs"] if b["bug"] == "18")
        self.assertTrue(row["page"])
        self.assertEqual(set(row["agents"]), set(corpus.AGENTS))
        self.assertEqual(len(overview["bugs"]), 50)


if __name__ == "__main__":
    unittest.main()
