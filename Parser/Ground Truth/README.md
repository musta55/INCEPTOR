# Ground Truth: phase annotation kit (codebook v3.0)

Built on 2026-10-10 by `python3 make_ground_truth.py` (run from `Parser/`). The procedure,
lookup tables and grouping rules are in [Annotation Codebook.docx](../Annotation%20Codebook.docx).

| File | What it is |
|---|---|
| `annotator_1.xlsx`, `annotator_2.xlsx` | One workbook per annotator. Each holds the same tabs: Start here, the reference tabs (Phases, Action categories, Grouping rules, Outcomes and flags), one tab per trajectory (T01–T15) and Codebook changes. The annotator fills `phase`, `category_fix` and `notes`. The workbooks are blind: no automatic phase, subphase or outcome, and no pass/fail |
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
the workbooks. After the round-1 meeting, update the reference tabs of the filled workbooks
by hand, or rebuild and then copy the round-1 labels across.

**On Google Drive** this kit lives in Trajectory Annotation Kit / Ground Truth. There, the
Tracker is a Google Sheet, which replaces `tracker.xlsx`; annotators keep their copies in the
Annotator 1 and Annotator 2 folders. The previous Drive kit and both annotator copies of it
were moved to "Archive - segment and purpose kit (Oct 8)".

The previous local kits (the segment/purpose kit of 2026-10-07 and the older
`Annotation kit/`) are archived in `Inspection/annotation-kits-before-2026-10-10.tar.gz`.
