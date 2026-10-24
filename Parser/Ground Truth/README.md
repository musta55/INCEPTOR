# Ground Truth: phase annotation kit (codebook v4)

Built by `python3 make_ground_truth.py` (run from `Parser/`). The procedure is in
`Trajectory Annotation Procedure.docx` and the codebook with the lookup tables in
[Annotation Codebook.docx](../Annotation%20Codebook.docx).

| File | What it is |
|---|---|
| `annotation_workbook.xlsx` | The one workbook (tabs below) |
| `atif/T<nn>_bug-<id>_<agent>.atif.json` | The full trajectory behind each of T01–T15 |
| `tracker.xlsx` | One row per trajectory: agent, bug, actions, and a done column per annotator |

**Workbook tabs.**
- **Start here**: how to fill in the workbook.
- **Annotation**: every action of T01–T15, one row each: `A1 phase`, `A1 category_fix`,
  `A1 notes`, the same `A2 …` columns, the agreed `Final Phase` and `Final Category`, then the
  ATIF columns. Phase marks are sparse; a row takes the phase above it.
- **Lookup table creation**, **Pilot table check**: the lookup tables drafted and checked on the
  pilot set T01, T03 and T05.
- **Pilot agreement**: A1 vs A2 on the pilot set (live formulas over Annotation).
- **Final lookup table**: the action, target and phase tables, word for word as
  `atif/lookup.py` holds them. **Lookup justification**: the development steps behind each
  entry added on the development set (`../data/splits/`, built by `make_splits.py`).
- **Phases**: the phase definitions. **Action lookup (depricated)**, **Phase lookup
  (depricated)**: the version 4 tables the Final tables replaced.
- **Evaluation scores**: RQ1 (A1 vs A2 before adjudication: agreement, Cohen's kappa,
  Krippendorff's alpha) and RQ2 (the tool vs `Final Phase`: accuracy, macro precision, recall
  and F1, sequence distance) on T02, T04 and T06–T15 (12 trajectories, 557 actions).

**Sample.** The frame is configuration `original`, run 1: 3 agents × 50 bugs = 150
trajectories. Each agent got 5 trajectories, split by its APR pass rate (Claude 4 pass + 1
fail, Codex 4 + 1, Qwen 2 + 3), drawn at random within each stratum with seed 20261010, no app
twice for one agent, no bug twice, and bug 18 (the codebook's worked example) excluded. The
sampling record, with the outcomes, is `../ground_truth_sample.csv`.

**Do not run `make_ground_truth.py --overwrite`.** It replaces the workbook. Rebuild only the
reference tabs with `--workbook-only --labels FILLED.xlsx:K`, or update them by hand.

**On Google Drive** the kit lives in Trajectory Annotation Kit / Ground Truth, where the Tracker
is a Google Sheet and the annotators keep their copies in the Annotator 1 and Annotator 2
folders.
