# Inceptor

Inceptor is a browser-based tool for exploring the trajectories of program-repair agents. It
reads raw agent logs and labels every step with an **action category** (search, read, edit,
build, test, …) and a **phase** (planning, localization, repair, validation). Its views let you
move from a run's phases to its individual steps and files, and compare agents and repeated
runs on the same bug.

- **Tool:** [inceptor-tool.vercel.app](https://inceptor-tool.vercel.app/#). It runs in the
  browser with nothing to install.
- **Demo video:** [youtube.com/watch?v=A2dEy6_VhUM](https://www.youtube.com/watch?v=A2dEy6_VhUM)
- **Lookup tables:** [`Lookup tables/Inceptor lookup tables.xlsx`](Lookup%20tables/Inceptor%20lookup%20tables.xlsx),
  expanded with this [prompt](Lookup%20tables/Heuristic%20Expansion%20Prompt.md)
- **Annotation workbook** (sets, lookup-table construction, evaluation):
  [`Lookup tables/annotation_workbook.xlsx`](Lookup%20tables/annotation_workbook.xlsx)

---

## Architecture

<p align="center">
  <img src="Dataset/Case%20Study/architecture.drawio.png" alt="Inceptor's architecture" width="800">
</p>

Converters turn each agent's log into ATIF. The classification engine then labels every step
using the lookup tables, the phase rules and any custom rules the user adds. The labels are
kept in the browser's storage (IndexedDB) and drive the dashboard's three views: corpus
exploration, trajectory inspection and comparison. Everything runs in the browser: the Python
engine runs through Pyodide, and the dashboard is written in JavaScript.

---

## Data

| What | Where |
|---|---|
| 450 trajectories (50 Android bugs × 3 agents × 3 runs), converted to [ATIF v1.7](Parser/ATIF-v1.7-RFC.md) | [`Parser/data/atif/original/`](Parser/data/atif/original/) |
| Example datasets to upload: raw logs plus `outcomes.csv`, 25 bugs each | [`Dataset/demo/`](Dataset/demo/) (`dataset1`, `dataset2`) |
| Case-study screenshots (Bug 84) | [`Dataset/Case Study/`](Dataset/Case%20Study/) |

The agents are Claude Code (Opus 5), Codex (GPT-5.6-Sol) and Qwen Code (Qwen3.6-35B-A3B). Each
ran three times on each of the 50 bugs. Each patch was checked with the bug's test suite.

---

## Code

| Component | Where |
|---|---|
| Log parsers (6 agents + ATIF) and the classification engine (Python) | [`Parser/atif/`](Parser/atif/) |
| Lookup tables as code | [`Parser/atif/lookup.py`](Parser/atif/lookup.py) |
| Dashboard (HTML/JS; the engine runs in the browser via Pyodide) | [`Parser/viewer/`](Parser/viewer/) |
| Ground-truth and split scripts | `Parser/make_ground_truth.py`, `Parser/make_splits.py`, `Parser/score_ground_truth.py` |
| Tests | [`Parser/tests/`](Parser/tests/) |

Run it locally (Python 3.9 or later, no dependencies):

```bash
git clone https://github.com/musta55/INCEPTOR.git
cd INCEPTOR/Parser
python3 -m atif.cli serve --open                 # dashboard on http://127.0.0.1:8765/
python3 -m atif.cli analyze LOG                  # label one log from the command line
python3 -m unittest discover -s tests -t .       # run the tests
```

See [`Parser/README.md`](Parser/README.md) for all commands and the data formats.

---

## Evaluation

The full process is recorded in the annotation workbook,
[`Lookup tables/annotation_workbook.xlsx`](Lookup%20tables/annotation_workbook.xlsx):

| Step | Workbook tab |
|---|---|
| Pilot set (3 trajectories) and test set (12 trajectories): every step with both annotators' labels and the agreed label | *Annotation for Pilot + test set* |
| Lookup tables drafted on the pilot set, and the annotators' agreement on it | *Pilot Look up table*, *Pilot agreement* |
| Lookup tables expanded on the development set (339 trajectories) with this [prompt](Lookup%20tables/Heuristic%20Expansion%20Prompt.md) | *Final lookup table*, *Justification for Heurisitic Ex* |
| Phase definitions | *Phase Definition* |
| Inceptor's labels vs. the agreed labels on the test set | *Evaluation scores* |

On the 557 test steps, Inceptor assigns the correct action category to 99.6% of steps and the
correct phase to 89.0% (macro-F1 0.82).

---

## Case Study: Bug 84

These are Inceptor's views of the nine runs on Bug 84. Claude and Codex pass the bug's tests in
all three runs. Qwen passes only in run 3.

**The three agents, run 1.** Both passing runs spend most of their steps on localization.
Claude alternates several repair phases with localization and validation. Codex localizes,
edits once and then validates.

![Claude, Codex and Qwen on Bug 84, run 1](Dataset/Case%20Study/3_agents_run.png)

**Claude, runs 1–3.** It passes every run, but uses 52–67 steps and a different number of
repair phases each time.

![Claude's three runs on Bug 84](Dataset/Case%20Study/claude3.png)

**Codex, runs 1–3.** It follows the same short pattern every time: 21–24 steps, one edit,
then a build.

![Codex's three runs on Bug 84](Dataset/Case%20Study/codex3.png)

**Qwen, runs 1–3.** Its outcome changes across runs. In the failing run 2 it explores almost the
same files as Claude, but its edits and checks differ.

![Qwen's three runs on Bug 84](Dataset/Case%20Study/qwen3.png)

---

## License

Inceptor is released under the [MIT License](LICENSE).
