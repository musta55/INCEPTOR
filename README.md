# Inceptor

A trace exploration dashboard for the trajectories of **automated program repair (APR) agents**.
Inceptor turns the raw log of a coding agent into a sequence of **phases** (planning,
localization, repair, validation), **action categories** and **steps**. You can then inspect one
run, compare agents on the same bug, and compare the runs of one agent. Every action is labelled
by deterministic, human-readable **lookup tables**, which the user can extend in the browser.

- **Tool:** [inceptor-tool.vercel.app](https://inceptor-tool.vercel.app/#)
- **Demo video:** [youtube.com/watch?v=A2dEy6_VhUM](https://www.youtube.com/watch?v=A2dEy6_VhUM)
- **Lookup tables (Excel):** [`Lookup tables/Inceptor lookup tables.xlsx`](Lookup%20tables/Inceptor%20lookup%20tables.xlsx)

---

## Dataset

### Corpus

- 50 Android UI bugs, each repaired by three agents: Claude Code (`claude-opus-5`), Codex CLI
  (`gpt-5.6-sol`) and Qwen Code (`qwen3.6-35b-a3b`).
- 17 prompt configurations × 3 runs, so 7,650 trajectories in total. Each has an APR outcome:
  the harness compiled the patched app and ran the bug's tests.
- The dashboard and the evaluation use the `original` configuration: 3 agents × 50 bugs × 3 runs
  = 450 trajectories.
- The raw logs (about 3 GB) are not in this repository. The converted trajectories are, in
  [ATIF v1.7](Parser/ATIF-v1.7-RFC.md), at `Parser/data/atif/original/run<k>/bug-<id>_<agent>.atif.json`.

### Example datasets (ready to upload)

- **Location:** [`Dataset/demo/`](Dataset/demo/). It holds `dataset1` and `dataset2`, 25 bugs
  each, with 3 agents × 3 runs per bug.
- **Layout:** `<dataset>/bug-<id>/<agent>/run<n>/<log file>` (each run's raw log, as the agent
  wrote it), plus an `outcomes.csv` (`bug, agent, run1, run2, run3`, pass / fail).
- **In the dashboard:** it opens with `dataset1` already loaded. Upload `dataset2` from the
  **Upload** page to see new bugs added to the corpus.

---

## Lookup Tables

**Location:** [`Lookup tables/Inceptor lookup tables.xlsx`](Lookup%20tables/Inceptor%20lookup%20tables.xlsx)

| Tab | Content |
|---|---|
| **Final lookup table** | The three tables Inceptor applies to every action (below) |
| **Lookup justification** | Why each entry was added or changed, with two development steps that show it |

The tables are:

1. **Action → category.** Shell commands and native tools map to 11 categories: search, read,
   orient, edit, build, test, diff, vcs, plan, sub-agent and other. A command line that runs
   several programs takes the highest category on the line.
2. **File → target.** Each file gets a target: source file, test file, docs, build file, other
   repository file, or outside the repository.
3. **Category → phase.** Rows L1–L15 map an action to a phase, and the first row that matches
   wins. A row checks the action's category, its target files and its position: the first
   step, or before or after the first edit of a source file. Rows L14 and L15 and the general
   rule give the previous step's phase.

The same tables are in the code, word for word ([`Parser/atif/lookup.py`](Parser/atif/lookup.py)),
and on the dashboard's **Lookup tables** page. That page is also where users add rows of their
own; their rows take priority over the built-in ones.

---

## Manual Annotation and Evaluation

| Item | Location |
|---|---|
| Annotation codebook | [`Parser/Annotation Codebook.docx`](Parser/Annotation%20Codebook.docx) |
| Annotation procedure | [`Parser/Ground Truth/Trajectory Annotation Procedure.docx`](Parser/Ground%20Truth/Trajectory%20Annotation%20Procedure.docx) |
| Annotation workbook (labels, lookup-table history, scores) | [`Parser/Ground Truth/annotation_workbook.xlsx`](Parser/Ground%20Truth/annotation_workbook.xlsx) |
| Annotated trajectories T01–T15 | [`Parser/Ground Truth/atif/`](Parser/Ground%20Truth/atif/) |
| Sample and splits | [`Parser/ground_truth_sample.csv`](Parser/ground_truth_sample.csv), [`Parser/data/splits/splits.csv`](Parser/data/splits/splits.csv) |

**Process.**

1. **Pilot.** The lookup tables were drafted and checked on 3 trajectories (T01, T03, T05;
   73 actions). Two annotators agreed on 82.2% of actions (κ = 0.74).
2. **Expansion.** The tables were extended on the development trajectories. Each added entry is
   in the *Lookup justification* tab.
3. **Evaluation.** Two annotators labelled 12 trajectories independently (T02, T04, T06–T15;
   4 per agent, 557 actions) and then agreed on a final label for each action.

**Results** (the workbook's *Evaluation scores* tab; means weighted by actions):

| | Measure | Claude Code | Codex | Qwen Code | Mean |
|---|---|---|---|---|---|
| **RQ1** annotator 1 vs annotator 2 | agreement / Cohen's κ | 98.4% / 0.97 | 87.6% / 0.81 | 89.7% / 0.85 | **94.1% / 0.91** |
| **RQ2** Inceptor vs final labels | accuracy / macro-F1 | 95.7% / 0.88 | 82.5% / 0.82 | 80.1% / 0.65 | **89.0% / 0.81** |

---

## Tool

### Use it online

Open [inceptor-tool.vercel.app](https://inceptor-tool.vercel.app/#). The analysis engine runs
in your browser (Python via Pyodide), so uploads never leave your machine. The dashboard has
four pages:

| Page | What it shows |
|---|---|
| **Corpus Overview** | Every bug × agent with its runs and outcomes; filters, search, and a Statistics tab |
| **Upload** | Upload a dataset folder or log files; group runs into a comparison |
| **Analyze** | One trajectory or comparison: the **Trajectory** tab (phases → categories → steps), **Fingerprint** and **Comparison** |
| **Lookup tables** | The built-in tables; add rows of your own, and see the steps no table recognized |

**Logs it reads:** Claude Code, Codex CLI and Qwen Code; SWE-agent, OpenHands and
mini-swe-agent (SWE-bench runs); and any agent's [ATIF](Parser/ATIF-v1.7-RFC.md) trajectory.
It recognizes the format from the file's content.

### Run it locally

You need Python 3.9 or later; the tool has no other dependencies.

```bash
git clone https://github.com/musta55/INCEPTOR.git
cd INCEPTOR/Parser
python3 -m atif.cli serve --open            # dashboard + engine on http://127.0.0.1:8765/
```

### Command line

```bash
cd Parser
python3 -m atif.cli analyze LOG [--rules tables.json]   # phases of one log of any agent
python3 -m atif.cli convert --all                       # raw logs -> ATIF (needs the raw Dataset/)
python3 -m atif.cli view --all                          # rebuild the dashboard data and engine
python3 -m unittest discover -s tests -t .              # 271 tests
```

The ground-truth scripts need `openpyxl` (`pip install openpyxl`):

```bash
python3 make_ground_truth.py --help     # build the annotation kit
python3 make_splits.py --help           # pilot / development / evaluation split
python3 score_ground_truth.py --help    # agreement and accuracy from filled workbooks
python3 make_demo.py                    # rebuild Dataset/demo (needs the raw Dataset/)
python3 make_seed.py                    # rebuild the dashboard's preloaded example from dataset1
```

### Repository Structure

```
INCEPTOR/
├── README.md
├── Lookup tables/
│   └── Inceptor lookup tables.xlsx      Final lookup table + justification
├── Dataset/
│   └── demo/                            dataset1, dataset2: example uploads with outcomes.csv
└── Parser/
    ├── README.md                        Full technical documentation
    ├── atif/                            Python package: parsers -> ATIF, lookup tables, phases, engine
    │   ├── claude.py, codex.py, qwen.py, sweagent.py, openhands.py, miniswe.py   log parsers
    │   ├── lookup.py                    the Final lookup tables
    │   ├── phase.py, verdict.py         phases, outcomes, step verdicts
    │   ├── upload.py, rules.py          analysis of an upload; user rows
    │   ├── view.py, serve.py, cli.py    dashboard data, local server, command line
    │   └── agreement.py, baselines.py   evaluation metrics and baselines
    ├── viewer/                          the dashboard (static HTML/JS, deployed to Vercel)
    │   ├── index.html, upload.html, analyze.html, tables.html
    │   ├── engine/atif.zip              the atif package, run in the browser by Pyodide
    │   └── data/                        overview, corpus packs, preloaded example dataset
    ├── data/
    │   ├── atif/original/               450 converted trajectories (ATIF v1.7)
    │   └── splits/                      pilot / development / evaluation record
    ├── Ground Truth/                    annotation workbook, procedure, T01–T15
    ├── Annotation Codebook.docx
    ├── Phase taxonomy.md                phase definitions and rules
    ├── View data contract.md            the dashboard's data format
    ├── ATIF-v1.7-RFC.md                 trajectory format
    ├── make_ground_truth.py, make_splits.py, score_ground_truth.py
    ├── make_demo.py, make_seed.py
    └── tests/
```

---

## License

Research use only.
