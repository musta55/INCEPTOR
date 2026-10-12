# Ground-truth scores (2026-10-11)

Labelled tabs: A1 0/15; A2 0/15

Tool: `atif.phase` with ABSORB_MAX=1, on `Ground Truth/atif/`.

Sequence distance: Levenshtein distance between the phase sequences (the order of the stretches, ignoring their lengths), divided by the longer sequence, mean over trajectories (0 = same order); the mean number of edits is in brackets. Same sequence: share of trajectories whose phase sequences are identical.

## 1. Agreement between the annotators (the ceiling)

No tab is labelled in both workbooks yet.

Rows to settle in the adjudication meeting: 0 (`disagreements.csv`, no tool labels in it).

## 2. The tool against each annotator (no reference yet)

Before adjudication the tool is compared with each annotator separately; the scored comparison is against the reference workbook (`--reference`).

## 3. Action categories (Table 2)

| workbook | rows | rows with a category_fix | accuracy of the categories | most frequent fixes |
|---|---|---|---|---|
| A1 | 0 | 0 | – | – |
| A2 | 0 | 0 | – | – |

On the tabs both labelled, A1 fixed 0 rows and A2 0; both fixed 0, with the same category on 0. Rows only one annotator fixed go to the adjudication meeting like phase disagreements.

## 4. Subphase outcomes (audit)

Wrote `data/ground_truth/subphase_audit.xlsx` with 95 subphases. Fill in `correct` (1 / 0) and run this script again.

