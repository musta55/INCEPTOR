# Ground Truth: phase annotation kit (codebook v4.0)

Built on 2026-10-10 by `python3 make_ground_truth.py` (run from `Parser/`); the workbook was
rewritten for codebook version 4 on 2026-10-14 with `make_ground_truth.py --workbook-only`.
The procedure and the lookup tables are in [Annotation Codebook.docx](../Annotation%20Codebook.docx).

| File | What it is |
|---|---|
| `annotation_workbook.xlsx` | The one workbook. Tabs: Start here; Annotation (all 15 trajectories, one row per action, with the columns `A1 phase`, `A1 category_fix`, `A1 notes` for annotator 1 and the same `A2 …` columns for annotator 2, then the given columns); the reference tabs Phases, Action lookup and Phase lookup; Codebook changes. Each annotator works in a copy and fills only their own columns. The workbook is blind: no automatic phase, subphase or outcome, and no pass/fail. The A1 columns of T01–T05 carry the round-1 labels annotator 1 made with version 3 |
| `annotator_1_Mustahid.xlsx` | Annotator 1's version 3 workbook (one tab per trajectory), whose labels were copied into the A1 columns |
| `atif/T<nn>_bug-<id>_<agent>.atif.json` | The full trajectory behind each tab |
| `tracker.xlsx` | One row per tab: round, agent, bug, actions, and a done column per annotator |

**Sample.** The frame is configuration `original`, run 1: 3 agents × 50 bugs = 150
trajectories. Each agent gets 5 trajectories, split by its APR pass rate:

| Agent | Passed | Sample |
|---|---|---|
| Claude | 44 / 50 | 4 pass + 1 fail |
| Codex | 42 / 50 | 4 pass + 1 fail |
| Qwen | 25 / 50 | 2 pass + 3 fail (ties go to fail) |

Other rules of the draw:
- simple random within each stratum, with seed 20261010;
- no app twice for one agent, and no bug twice in the sample;
- bug 18 is excluded, because it is the codebook's worked example.

The draw gives 15 trajectories and 630 actions. The sampling record, which includes the
outcomes, is `../ground_truth_sample.csv`, kept outside this folder.

**Rounds.**
- **Round 1** is T01–T06 (255 actions): one passing and one failing trajectory per agent.
  The codebook may change during this round.
- **Round 2** is T07–T15 (375 actions), annotated after the codebook is frozen.

**Do not run `make_ground_truth.py --overwrite` after annotation has started.** It replaces
the workbook (never an annotator's own copy). After the round-1 meeting, rebuild the reference
tabs with `--workbook-only --labels FILLED.xlsx:K`, or update them by hand.

**On Google Drive** this kit lives in Trajectory Annotation Kit / Ground Truth. There, the
Tracker is a Google Sheet, which replaces `tracker.xlsx`; annotators keep their copies in the
Annotator 1 and Annotator 2 folders. The previous Drive kit and both annotator copies of it
were moved to "Archive - segment and purpose kit (Oct 8)".

The previous local kits (the segment/purpose kit of 2026-10-07 and the older
`Annotation kit/`) are archived in `Inspection/annotation-kits-before-2026-10-10.tar.gz`.
