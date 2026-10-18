"""Agreement measures (``atif/agreement.py``) and the ground-truth scorer
(``score_ground_truth.py``).

The measures are pinned on small sequences whose values were worked out by hand; the scorer
is checked on a synthetic workbook laid out like a trajectory tab of the kit, and on the kit
itself when ``Ground Truth/`` is present.

Run from ``Parser/``: ``python3 -m unittest discover -s tests -t .``
"""
from __future__ import annotations

import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from atif import agreement, phase, view  # noqa: E402

A, B, C = "localization", "repair", "validation"


class MeasureTests(unittest.TestCase):

    def test_kappa_by_hand(self):
        # observed 3/4; expected (2*1 + 2*3) / 16 = 1/2; kappa = (0.75 - 0.5) / 0.5
        self.assertAlmostEqual(agreement.kappa([A, A, B, B], [A, B, B, B]), 0.5)
        self.assertEqual(agreement.kappa([A, A, A], [A, A, A]), 1.0)
        self.assertAlmostEqual(agreement.accuracy([A, A, B, B], [A, B, B, B]), 0.75)

    def test_a_missing_label_disagrees(self):
        self.assertEqual(agreement.accuracy([A, B], [None, B]), 0.5)
        self.assertAlmostEqual(agreement.compare([([A, B], [None, B])])["coverage"], 0.5)

    def test_boundaries_and_tolerance(self):
        self.assertEqual(agreement.boundaries([A, A, B, B, A]), [2, 4])
        self.assertEqual(agreement.match_boundaries([A, A, B, B], [A, B, B, B], tol=0), (0, 1, 1))
        self.assertEqual(agreement.match_boundaries([A, A, B, B], [A, B, B, B], tol=1), (1, 1, 1))
        # one-to-one: one hypothesis boundary can match only one of two reference boundaries
        self.assertEqual(agreement.match_boundaries([A, A, B, C], [A, A, C, C], tol=1), (1, 2, 1))
        self.assertEqual(agreement.prf(0, 0, 0)["f1"], 1.0)
        self.assertAlmostEqual(agreement.prf(1, 2, 1)["f1"], 2 / 3)

    def test_window_diff_by_hand(self):
        # n = 6, two reference stretches: k = round(6 / 4) = 2, windows i = 0..3; the
        # boundary counts differ at i = 1 (ref 1, hyp 0) and i = 3 (ref 0, hyp 1)
        ref, hyp = [A, A, A, B, B, B], [A, A, A, A, B, B]
        self.assertAlmostEqual(agreement.window_diff(ref, hyp), 0.5)
        self.assertEqual(agreement.window_diff(ref, ref), 0.0)

    def test_sequence_distance_by_hand(self):
        U = "understanding"
        self.assertEqual(agreement.stretch_sequence([A, A, B, A]), [A, B, A])
        self.assertEqual(agreement.levenshtein([A, B, C], [A, U, B, C]), 1)       # one insertion
        self.assertEqual(agreement.levenshtein([A, B, C], [C, B, A]), 2)          # two relabels
        self.assertEqual(agreement.levenshtein([], [A, B]), 2)
        # lengths do not matter, only the order of the stretches
        self.assertEqual(agreement.sequence_distance([A, A, A, B], [A, B, B, B]), (0, 0.0))
        self.assertEqual(agreement.sequence_distance([A, B, C], [A, U, B, C]), (1, 0.25))
        m = agreement.compare([([A, B, C, C], [A, U, B, C]), ([A, B], [A, B])])
        self.assertEqual(m["sequence"], {"edit_distance": 0.5, "normalized": 0.125, "identical": 0.5})

    def test_compare_pools_over_trajectories(self):
        m = agreement.compare([([A, A, B, B], [A, B, B, B]), ([C, C], [C, C])])
        self.assertEqual((m["trajectories"], m["actions"]), (2, 6))
        self.assertAlmostEqual(m["accuracy"], 5 / 6)
        self.assertEqual(m["boundary_tol0"]["f1"], 0.0)
        self.assertEqual(m["boundary_tol1"]["f1"], 1.0)
        self.assertAlmostEqual(m["window_diff"], (agreement.window_diff([A, A, B, B], [A, B, B, B]) + 0) / 2)

    def test_per_label_and_confusion(self):
        pairs = [([A, A, B, B], [A, B, B, B])]
        self.assertEqual(agreement.confusion(pairs), {(A, A): 1, (A, B): 1, (B, B): 2})
        per = agreement.per_label(pairs, [A, B, C])
        self.assertEqual((per[A]["precision"], per[A]["recall"], per[A]["support"]), (1.0, 0.5, 2))
        self.assertAlmostEqual(per[B]["precision"], 2 / 3)
        self.assertTrue(math.isnan(per[C]["f1"]))

    def test_bootstrap_is_reproducible(self):
        pairs = [([A, B], [A, B]), ([A, B], [B, B]), ([A, A, B], [A, B, B])]
        one = agreement.bootstrap(pairs, agreement.pooled_kappa, reps=200)
        self.assertEqual(one, agreement.bootstrap(pairs, agreement.pooled_kappa, reps=200))
        self.assertLessEqual(one[0], one[1])
        self.assertTrue(math.isnan(agreement.bootstrap(pairs[:1], agreement.pooled_kappa)[0]))


class WorkbookReaderTests(unittest.TestCase):
    """A tab laid out as make_ground_truth.py writes it: header, then one row per action."""

    def _book(self, marks, fixes=None, n_actions=None):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "T01 claude bug-1"
        ws.append(["phase", "category_fix", "notes", "step", "sub_agent", "fix_stage", "category"])
        for k, mark in enumerate(marks):
            ws.append([mark, (fixes or {}).get(k), None, k + 1, None, "pre-fix", "read_file"])
        path = Path(self.tmp.name) / "book.xlsx"
        wb.save(path)
        return path, [{"tab": "T01", "actions": n_actions or len(marks)}]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_phase_holds_until_the_next_one(self):
        import score_ground_truth as sgt
        path, sample = self._book(["Localization", None, "repair", None, "repair"], {3: "build"})
        tabs, problems = sgt.read_workbook(path, sample)
        self.assertEqual(problems, [])
        self.assertEqual(tabs["T01"]["status"], "complete")
        self.assertEqual(tabs["T01"]["phase"], [A, A, B, B, B])
        self.assertEqual(tabs["T01"]["category_fix"], ["", "", "", "build", ""])

    def test_incomplete_and_empty_tabs_are_reported(self):
        import score_ground_truth as sgt
        path, sample = self._book([None, "repair", "fixing"])
        tabs, problems = sgt.read_workbook(path, sample)
        self.assertEqual(tabs["T01"]["status"], "incomplete")
        self.assertTrue(any("not a phase" in p for p in problems))
        self.assertTrue(any("first row has no phase" in p for p in problems))
        path, sample = self._book([None, None])
        self.assertEqual(sgt.read_workbook(path, sample)[0]["T01"]["status"], "empty")

    def test_a_tab_with_rows_added_is_refused(self):
        import score_ground_truth as sgt
        path, sample = self._book(["repair"] * 4, n_actions=3)
        tabs, problems = sgt.read_workbook(path, sample)
        self.assertEqual(tabs["T01"]["status"], "invalid")
        self.assertTrue(any("action rows" in p for p in problems))

    def _one_sheet(self, a1, a2, n_t02=2):
        """The version 4 workbook: every trajectory on the Annotation sheet."""
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Annotation"
        ws.append(["trajectory", "bug_id", "agent", "action", "A1 phase", "A1 category_fix",
                   "A1 notes", "A2 phase", "A2 category_fix", "A2 notes", "step", "category"])
        for k, (m1, m2) in enumerate(zip(a1, a2), 1):
            ws.append(["T01", "bug-1", "claude", k, m1, None, None, m2, "NEW" if k == 2 else None,
                       None, k, "read_file"])
        for k in range(1, n_t02 + 1):
            ws.append(["T02", "bug-2", "qwen", k, None, None, None, None, None, None, k, "build"])
        path = Path(self.tmp.name) / "one.xlsx"
        wb.save(path)
        return path, [{"tab": "T01", "actions": len(a1)}, {"tab": "T02", "actions": 3}]

    def test_the_one_sheet_workbook_gives_each_annotator_their_columns(self):
        import score_ground_truth as sgt
        path, sample = self._one_sheet(["localization", None, "repair"], ["repair", None, None])
        one, problems = sgt.read_workbook(path, sample, 1)
        self.assertEqual(one["T01"]["phase"], [A, A, B])
        two, _ = sgt.read_workbook(path, sample, 2)
        self.assertEqual(two["T01"]["phase"], [B, B, B])
        self.assertEqual(two["T01"]["category_fix"], ["", "NEW", ""])
        self.assertEqual(one["T02"]["status"], "invalid")       # 2 rows for 3 actions
        self.assertTrue(any("T02" in p for p in problems))


KIT = HERE.parent / "Ground Truth"
ANNOTATION = HERE.parent / "data" / "annotation" / "original" / "run1"


@unittest.skipUnless((KIT / "atif").is_dir() and (HERE.parent / "ground_truth_sample.csv").is_file(),
                     "Ground Truth kit not present")
class KitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import score_ground_truth as sgt
        cls.sample = sgt.load_sample()
        cls.tool = sgt.tool_labels(cls.sample)

    def test_every_method_labels_every_row(self):
        self.assertEqual(len(self.tool), 15)
        self.assertEqual(sum(e["actions"] for e in self.sample), 630)
        for e in self.sample:
            for method in ("tool", "B1", "B3", "B4", "B5"):
                self.assertEqual(len(self.tool[e["tab"]][method]), e["actions"], (e["tab"], method))
            self.assertTrue(set(self.tool[e["tab"]]["tool"]) <= set(phase.PHASES))

    @unittest.skipUnless(ANNOTATION.is_dir(), "data/annotation/original/run1 not present")
    def test_the_annotation_sheets_carry_the_same_phases(self):
        for e in self.sample:
            with (ANNOTATION / f"bug-{e['bug']}_actions.csv").open(newline="") as handle:
                sheet = [r["phase"] for r in csv.DictReader(handle) if r["agent"] == e["agent"]]
            self.assertEqual(sheet, self.tool[e["tab"]]["tool"], e["tab"])

    def test_the_viewer_draws_the_same_phases(self):
        bug_file = HERE.parent / "viewer" / "data" / "bugs" / "bug-{}.js"
        for e in self.sample:
            path = Path(str(bug_file).format(e["bug"]))
            if not path.is_file():
                continue
            data = view.read_js(path)
            traj = next(t for t in data["trajectories"] if t["agent"] == e["agent"] and t["run"] == 1)
            self.assertEqual([a["phase"] for a in traj["actions"]], self.tool[e["tab"]]["tool"], e["tab"])


if __name__ == "__main__":
    unittest.main()
