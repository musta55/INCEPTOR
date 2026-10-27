# Parser — unified agent trajectories

Converts the raw logs in `../Dataset/` from Claude Code, Codex CLI and Qwen Code into one
schema ([ATIF v1.7](ATIF-v1.7-RFC.md)), then derives the action categories, the phases and
their outcome subphases ([Phase taxonomy.md](<Phase%20taxonomy.md>)), the viewer data and the
manual-annotation kit.

Runs on the system Python 3.9+, no dependencies (Harbor's official validator runs through `uv`).

## The corpus

50 Android UI bugs, three agents, 3 runs each: 3 × 50 × 3 = **450 trajectories**, every one
with an APR outcome.

```
Dataset/a_apr_test_results/<agent>_run<k>.csv        outcomes: bug_id + one column per configuration, 1 = APR pass
Dataset/p_claude_results/claude_original_run<k>/claude_logs/bug-<id>_output.txt    claude-agent-sdk dump
Dataset/o_codex_results/codex_original_run<k>/codex/log-bug-<id>/logs/codex-session-rollout-*.jsonl
Dataset/q_qwen_results/qwen_original_run<k>/qwen/bug-<id>.log    Qwen Code stream-json (+ bug-<id>.meta.json)
```

Models: Claude Code `claude-opus-5`, Codex CLI 0.138.0 `gpt-5.6-sol`, Qwen Code 0.24.2
`qwen/qwen3.6-35b-a3b`.

## Commands

Every command takes the same selection flags: bug ids (`8 18`, or `--all`, not both), `--config NAME` (default `original`), `--runs K… | all` (default `1 2 3`) and `--agent claude|codex|qwen` (repeatable; default all three). Bug ids
may come anywhere on the line except straight after `--config` or `--runs`, which take several
values.

```bash
cd Parser
python3 -m atif.cli list                                # agent x run matrix + APR pass counts
python3 -m atif.cli convert --all                       # original, runs 1-3, 3 agents: 450 trajectories
python3 -m atif.cli convert 18 --runs 1                 # one bug, run 1
python3 -m atif.cli validate                            # re-validate the converted files of the selection
python3 -m atif.cli validate --from-raw                 # convert in memory and validate; writes only the report
python3 -m atif.cli validate --harbor                   # plus Harbor's official validator
python3 -m atif.cli phases 18 --runs 1                  # phases -> subphases outline, with outcomes
python3 -m atif.cli view --all                          # viewer data: overview.js, corpus packs, engine
python3 -m atif.cli segment 18 --runs 1                 # purposes -> segments outline (baseline B3)
python3 -m atif.cli actions 18                          # categories, phases and the phase sequence
python3 -m atif.cli audit 18 --agent qwen               # how much of each raw log survived conversion
python3 -m atif.cli output 8 codex <call_id> --run 2    # one tool result in full, from the raw log
python3 -m atif.cli serve --open                        # viewer + its engine (uploads, rules) on http://127.0.0.1:8765/
python3 -m atif.cli engine                              # the hosted viewer's engine: viewer/engine/atif.zip
python3 -m atif.cli analyze LOG [--rules rules.json]    # one log of any agent (or ATIF), outside the corpus
python3 -m atif.cli view --all --rules rules.json       # the corpus viewer under your own rules
python3 -m unittest discover -s tests -t .
```

`convert` and `validate` run in parallel (`--jobs N`, default up to 8) and print one progress line
and a summary table, not a line per file. `--max-output N` / `--full` set the tool-output cap.

Harbor's validator needs Python 3.12 and pydantic, so `validate --harbor` starts **one** `uv`
process for the whole selection. The module can also be run directly from `Parser/`:

```bash
uv run --python 3.12 --no-project --with harbor python -m atif.harbor_check data/atif/original
uv run --python 3.12 --no-project --with harbor python -m atif.harbor_check --from-raw --all
```

## Output

```
data/atif/<config>/run<k>/bug-<id>_<agent>.atif.json     ATIF v1.7, one step per LLM inference
data/annotation/<config>/run<k>/bug-<id>_actions.csv     one row per action, all agents: category, phase, own_phase,
                                                         subphase (+ outcome, evidence), attempt; manual columns blank
data/annotation/<config>/run<k>/bug-<id>_actions.jsonl   the same rows, for scripts
data/reading/<config>/run<k>/bug-<id>_<agent>.md         TAR transcript, for reading a run end to end
data/validation/<validator>-<source>[-<selection>].json   validator summary (+ -failures.csv)
```

Only `data/atif/original/` is kept in the repository (the viewer data and the ground-truth
scripts read it); the annotation sheets, reading views and validation reports are rebuilt by
`convert` and `validate` when needed.

A validation report is named after what it covers: `atif-raw.json` / `harbor-raw.json` (or
`-converted`) for the whole corpus, otherwise with the
selection appended, e.g. `atif-converted-original-r123.json` for the default `validate` or
`harbor-raw-all-r2-qwen-bug18.json`, so a narrower run never overwrites a wider one. Each summary
also records its `selection`.

Every converted trajectory's root `extra` carries `bug_id, agent, config, run, raw_log` (relative to
the dataset) and `dataset`; Codex and Qwen trajectories also carry the harness sidecar as
`extra.harness_meta`. Annotation rows carry `config` and `run` columns, and the phase taxonomy's
labels; the older mid/high ladder and `edit_role` are no longer exported (category and file_role
replace them). The flat files of the earlier one-run corpus (with Gemini CLI) that used to sit
directly under `data/atif/`, `data/annotation/` and `data/reading/` are archived in
`Inspection/earlier-corpus-flat-outputs-2026-10-11.tar.gz`.

Outcomes come from `Dataset/a_apr_test_results/` (`atif.outcomes`): the harness compiled the patched
app and ran the bug's instrumentation tests, so the verdict is not the agent's own claim.

The viewer (`viewer/`) is Inceptor, a trace exploration dashboard. It has four pages; the
header links Corpus Overview (`index.html`), Upload (`upload.html`) and Lookup tables
(`tables.html`), and each trajectory, bug or comparison opens on the Analyze page
(`analyze.html`). The Corpus Overview holds the uploaded runs, bug × agent (an Agent filter, an
Outcome filter, a search where a bug id such as `8` or `bug8` matches exactly that bug, and a
Statistics tab). The Analyze page has three tabs: Trajectory (phases → categories, consecutive
actions of one category → steps, each phase with its outcome, with the repair attempts and the
first fix marked; its tooltips quote the codebook), Fingerprint and, for a bug or a group,
Comparison. The only identifier shown for an action is its number (`#12`). A step's details panel
shows the line of the output that decided its verdict (`BUILD SUCCESSFUL in 1m 55s`), the
actions that decided its phase's outcome as links (the edits of a repair attempt are judged by
the build or test after them), why it got its phase (the phase lookup's row), the step's full
thought and result, and its raw ATIF JSON (read from the
corpus packs, so not from `file://`). Corpus bugs can be removed
from view (kept in the browser, with Restore). The data format is
[View data contract.md](<View%20data%20contract.md>) (`trajview/3`); `python3 -m atif.cli view --all`
rewrites it after `convert`, together with the corpus packs (`viewer/data/atif/run<k>/bug-<id>.json.gz`,
the converted ATIF, about 11 MB) and the engine zip.

**Lookup tables, one set of rows for every trajectory.** Categories and phases come from the
Final lookup tables (`atif/lookup.py`, word for word the tab "Final lookup table" of
`Ground Truth/annotation_workbook.xlsx`, 2026-10-17): the action table turns a tool call into
one of 11 categories (a shell command program by program, the highest category on the line
winning), the target table gives every file a target (source, test, docs, build, other,
outside), and the phase table (rows 1–15, the first that matches) turns the category, the
targets and the position (the first step, before or after the first edit of a source file)
into a phase: planning, localization, repair or validation (reproduction was dropped on
2026-10-19; rows 6 and 7, a test or a test-file edit before the first fix, are localization). Rows 14 and 15 and
the general rule give the previous step's phase. There are no grouping rules. The phases'
outcomes still read the runs' verdicts through the taxonomy's finer action kinds. `tables.html` (Lookup tables)
shows the built-in tables and is the only place where rows are added, and every page
applies them to every trajectory: the corpus packs and the uploads. With rows
added, the corpus is re-run from its packs by the analysis engine (about 4 s for the 150 run-1
trajectories in the browser, then cached per set of rows), and each row shows how many corpus
actions it changed. The engine is this package: on the hosted viewer
(https://inceptor-tool.vercel.app) it runs in the browser with Pyodide (CPython in WebAssembly,
about 10 MB from cdn.jsdelivr.net on the first visit), from `viewer/engine/atif.zip`, which
`view` and `engine` rewrite and `tests/test_rules.py` checks is current; locally,
`python3 -m atif.cli serve` starts a server (standard library only, this machine only) that
answers the same calls with native Python. A page opened from `file://` cannot start the engine
and shows the built-in tables. The page names the tables (Final lookup table, 2026-10-17) and
has three sections, action lookup, target files and phase lookup, each with the user's rows, a
form to add one, and the table word for word in a collapsed block (Category | Shell commands |
Native tools with the shell runners, the ignored programs and the several-programs rule; the
target table; phase rows 1–15 and the general rule), whose rows have **Change…** to start a row
of the user's from them. Two tiers: the **built-in** rows, always applied and never changed
(the viewer no longer offers the ready-made rows O1–O4: the Final tables cover them, and a table
file that lists some keeps only its own rows); and **your rows**, which win over the
built-in ones (between two of yours, the later): an action row gives steps whose command, tool
or program matches a category (and reads their runs as that category's), a *shell tool* row
makes an unknown agent's tool a shell tool (its commands are then read like Bash's), a target row
gives files whose path contains some text a target, a phase row gives matching steps a phase. A
match that would break the first fix (an edit of a source file is always repair; repair and
validation only from the first fix on) is skipped. A step's details
panel says why it got its category (the action table's entry) and its phase (the phase table's
row). "+ Row from this action" in the details panel of any trajectory opens the page
with a row started from that action. `view --all --rules tables.json` writes the viewer data
with a table file and `analyze --rules` applies one to a log (older `rules.json` files are read
too; their grouping rules are ignored). The format is in `atif/rules.py`; with no rows added it
reproduces `atif.phase` exactly (`tests/test_rules.py`). The grouping rules of codebook
version 3 are baseline B4 and the phase lookup of version 4 (rows P1–P11) baseline B5
(`atif/baselines.py`); table files written for version 4 are read with their values mapped
(run_test → test, toolchain → build, understanding → planning).

**Uploads.** The Upload page (`upload.html`) takes a dataset folder or log files. A folder is
read as `<dataset>/<bug>/<agent>/run<n>/<files>` (`TV.uploads.scan`, `viewer/uploads.js`): the
folders name each trajectory's bug, agent and run, and in a run folder the first file the engine
reads is the trajectory (metadata and sandbox logs beside it are passed over). An optional CSV
anywhere in the folder gives the outcomes: a `bug`, an `agent` and an `outcome` column (pass /
fail, 1 / 0), with a `run` column or one column per run (`run1`, `run2`…) when they differ.
Files cannot say how they are related, so for them the page asks: **separate** trajectories,
**one bug, several agents**, or **one agent, several runs**, and checks the choice (one agent
only for runs, distinct run numbers, one bug); a comparison opens as `analyze.html#g=<id>` with
its members in a bar and the **Fingerprint** tab, and `upload.html#g=<id>` edits it. The
Corpus Overview opens with the example dataset already in it and shows only uploads, in one
table (`TV.uploads.layout`): a new
agent is a new column, a new bug a new row at the bottom, and an upload is its cell's next run
(one dot per run); Statistics summarizes the same runs by agent. A run that is already there (the same bug, agent and run, or the same file uploaded before) waits for
the user's choice: **replace** it, or **add** this one as run n+1. Each upload is kept in the
browser (IndexedDB, with its ATIF; a comparison and the run in the table are written on the
record; ticking bugs on the Corpus Overview deletes them) and has its own page
(`analyze.html#u=<id>`; a bug's runs: `analyze.html#b=<bug>`, whose Fingerprint shows the
bug's agents in one run or one agent's runs). `make_demo.py`
lays the corpus out as two such folders (`Dataset/demo/dataset1`, `dataset2`: 25 bugs each, with
`outcomes.csv`) to demonstrate the upload. `make_seed.py` analyses `dataset1` in advance under the
default tables (`viewer/data/seed/`: one file with every run's analysis, and per run its log and
ATIF, fetched only when the details panel or another rule set needs them); the first time a
browser lists the uploads, `TV.uploads.seed` adds those 225 runs as if the folder had been
uploaded, so the dashboard opens with 25 bugs and `dataset2` is left to upload. They are
ordinary uploads from then on (deleted, analysed again); when every bug is deleted, the empty
Corpus Overview offers **Load the example dataset**. **Unrecognized steps** (`atif/diagnose.py`): a step whose tool is in no table
(it counts as `other`) or whose shell command runs a program in no table (`run_shell`) takes
the phase of the step before it; the upload's page and the Lookup tables page list them, grouped
by tool or program, each with a suggested row from fixed name rules (a tool whose `command`
argument holds command lines is a shell tool, `list_dir` is orient, `cargo test` is run_test,
...), which one click adds. The corpus agents have none (`tests/test_diagnose.py`). The agent
and format are recognised from the content, never the file name:

| Agent          | Log                                                                                                                                                                                                         | Versions read                                | Files                                  |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | -------------------------------------- |
| Claude Code    | stream-json, session transcript JSONL, Claude Agent SDK dump                                                                                                                                                | 2.1.181–2.1.283 (corpus)                    | `.jsonl` `.json` `.log` `.txt` |
| Codex CLI      | session rollout JSONL                                                                                                                                                                                       | 0.138 (corpus); the older `shell` tool too | `.jsonl`                             |
| Qwen Code      | stream-json                                                                                                                                                                                                 | 0.24 (corpus)                                | `.jsonl` `.log` `.json`          |
| any agent      | one ATIF trajectory (e.g. Harbor's `agent/trajectory.json`, written for 34 agents)                                                                                                                        | ATIF v1.x; checked on v1.2, v1.5, v1.6, v1.7 | `.json`                              |
| SWE-agent      | a SWE-bench run's `<instance>.traj`, or a row of Hugging Face's SWE-agent chat export (`nebius/SWE-agent-trajectories`)                                                                                 | 0.x and 1.x (SWE-bench Verified submissions) | `.traj` `.json`                    |
| OpenHands      | the run's messages (SWE-bench submissions' `trajs/<instance>.json`, `nebius/SWE-rebench-openhands-trajectories` rows) or its event stream (`--save-trajectory-path`, an evaluation row's `history`) | CodeAct 2.x                                  | `.json`                              |
| mini-swe-agent | `<instance>.traj.json` (live-SWE-agent too)                                                                                                                                                               | 1.13–1.14                                   | `.json`                              |
| Markdown       | a transcript rather than a log: SpecStory's export (`.specstory/history/*.md`) of a Claude Code, Codex CLI or other session, in either tool markup (`<tool-use>` blocks or `[external_agent_tool_call]` blocks), or Claude Code's `/export` | SpecStory Markdown v2.1                      | `.md` `.txt`                         |

A JSON array of events works too. A Markdown transcript names its agent (SpecStory's session
header, else its model), keeps fewer inputs than a log (an edit's path is read from its result)
and no sub-agent steps; what it lacks is listed in `extra.known_gaps`. Categories need the agent's tool names, which live in the
"Agent vocabularies" tables of `atif/taxonomy.py`: Claude Code, Codex CLI and Qwen Code are
checked on the corpus; OpenHands, Terminus-2, mini-swe-agent and Trae Agent on published Harbor
ATIF runs (`tests/test_parsers.py`, `ForeignAgentTests`), and Gemini CLI shares Qwen Code's names.
Any other agent's shell commands are read when its shell tool has one of these names; its other
tools count as `other`. The rules were built for Android repair (paths relative to a `bug-<id>`
checkout; Gradle, Maven, make and pytest runs), so another kind of project gets its categories and
phases but fewer build and test verdicts.

**SWE-bench runs** are kept apart from the Android corpus. The SWE-agent, OpenHands and
mini-swe-agent adapters (`atif/sweagent.py`, `openhands.py`, `miniswe.py`, sharing
`atif/swebench.py`) convert a run to ATIF and record a SWE-bench project in `extra.project`
(`atif/project.py`): the repository root the task names (`/testbed`, `/workspace/<repo>`,
`/<repo>`), and the instance id when the log or file name gives one. No bug id or outcome is
needed. While such a trajectory is analysed, paths are read relative to that root, Python's test
conventions apply (`tests/`, `test_*.py`, `conftest.py`; pytest's and unittest's summaries and
tracebacks decide a test run), a script the agent writes at the repository root or outside it
(`reproduce_issue.py`, `/tmp/repro.py`) is its reproduction script (test code, but not a
`test_modified` change), running it is a test run, and running an editing script of its own
(`python edit_file.py <file> ...`, as live-SWE-agent does) edits the file it names. An ATIF file
whose task names the repository folder gets the same project. Every other trajectory, the
corpus included, is read exactly as before (`tests/test_swebench.py`). On the dashboard such a run is
an upload like any other: its agent is a column of the corpus table and its instance id a row.
Agentless
and AutoCodeRover are fixed pipelines, not agents, and are not read.

Manual annotation runs on `Ground Truth/` (the codebook, the procedure and one workbook):

- `make_ground_truth.py` drew the 15 trajectories T01–T15 of `original`/run 1 (5 per agent,
  split by each agent's pass rate; the record is `ground_truth_sample.csv`), wrote their ATIF
  to `Ground Truth/atif/` and built `annotation_workbook.xlsx`: one Annotation sheet with every
  action, three columns per annotator (`A1 …`, `A2 …`), the agreed `Final Phase` and
  `Final Category`, and the ATIF columns (full command, shell command, result, …);
  `--workbook-only --labels FILE:K` rewrites it and copies labels in.
- `make_splits.py` split `original`/runs 1–3 into `data/splits/`: the pilot set (T01, T03, T05),
  the development set the lookup tables were expanded on, and a held-out set (`splits.csv`).
- The workbook's tabs record the process: Lookup table creation and Pilot table check (the
  pilot), Pilot agreement (A1 vs A2 on the pilot, live formulas), Final lookup table (what
  `atif/lookup.py` holds word for word) and Lookup justification (the development steps behind
  each added entry), and Evaluation scores: RQ1, A1 vs A2 before adjudication, and RQ2, the tool
  vs `Final Phase`, on T02, T04 and T06–T15 (12 trajectories, 557 actions).

The procedure and the lookup tables are in
[Annotation Codebook.docx](<Annotation%20Codebook.docx>) and
`Ground Truth/Trajectory Annotation Procedure.docx`.

`score_ground_truth.py` scores the kit from the annotators' filled workbooks:

```bash
python3 score_ground_truth.py --annotator a1.xlsx --annotator a2.xlsx       # before adjudication
python3 score_ground_truth.py --annotator a1.xlsx --annotator a2.xlsx --reference reference.xlsx
```

It reports the annotators' agreement (kappa with a bootstrap CI over trajectories, boundary F1
exact and ±1, WindowDiff, and the Levenshtein distance between the phase sequences), the tool, baselines B1, B3, B4 and B5 and the ablations against the reference,
per-phase F1, a confusion matrix, results by
agent, the category accuracy, and the subphase-outcome precision. It writes into
`data/ground_truth/`: `tool_labels.csv`, `rows.csv` (every
workbook beside them), `disagreements.csv` (for the adjudication meeting, without tool labels),
`scores.json`, `report.md`, and once `subphase_audit.xlsx` (fill in `correct`, then run again).
The tool's phase rules are in [Phase taxonomy.md](<Phase%20taxonomy.md>).

## Modules

| Module                                   | Responsibility                                                                                                                                      |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `atif/schema.py`                       | ATIF envelope, truncation policy, dependency-free validator                                                                                         |
| `atif/claude.py`                       | `claude-agent-sdk` `repr()` dump → ATIF (AST-based, no `eval`)                                                                               |
| `atif/codex.py`                        | Codex rollout JSONL → ATIF                                                                                                                         |
| `atif/qwen.py`                         | Qwen Code `stream-json` → ATIF                                                                                                                   |
| `atif/markdown.py`                     | Markdown transcripts → ATIF: SpecStory's export of any agent, Claude Code's `/export`                                                              |
| `atif/detect.py`                       | which parser a file needs, from its content                                                                                                         |
| `atif/corpus.py`                       | the dataset layout: find any (agent, config, run, bug) log, output paths                                                                            |
| `atif/outcomes.py`                     | APR outcomes per (agent, config, run, bug); badges read from the trajectory                                                                         |
| `atif/lookup.py`                       | the Final lookup tables, word for word, and the code that applies them: action → category, file → target, phase-table rows 1–15                  |
| `atif/taxonomy.py`                     | the finer action kinds (`kind`, `mid_level`) the verdicts, outcomes, flags and baselines read, file roles of codebook v4, and the tool registry |
| `atif/phase.py`                        | phases → outcome subphases, metrics, invariants ([Phase taxonomy.md](<Phase%20taxonomy.md>))                                                        |
| `atif/baselines.py`                    | baselines B1 (V2 first-edit split), B3 (old purposes as phases), B4 (v3 grouping rules), B5 (v4 Table 4)                                            |
| `atif/codebook.py`                     | codebook version 4, word for word: Tables 1–4 (baseline B5), the outcome and flag tables the viewer quotes                                         |
| `atif/agreement.py`                    | kappa, boundary F1 with tolerance, WindowDiff, bootstrap CIs (`score_ground_truth.py`)                                                            |
| `atif/view.py`                         | viewer data `trajview/3` ([View data contract.md](<View%20data%20contract.md>))                                                                    |
| `atif/rules.py`                        | lookup tables: the built-in contents in plain words (`contents`), ready-made rows, the user's action / shell-tool / file-role / phase rows        |
| `atif/upload.py`                       | one uploaded log or ATIF text → `trajview-single/1` (`analyze.html`, `analyze`); corpus packs re-run under a rule set (`corpus_request`)   |
| `atif/diagnose.py`                     | an upload's unrecognized steps (unknown tools and programs), grouped, each with a suggested lookup-table row                                        |
| `atif/serve.py`                        | local server for the viewer and its engine: `/api/rules`, `/api/analyze`, `/api/corpus` (`serve`)                                           |
| `atif/engine.py`                       | this package zipped for the viewer to run in the browser with Pyodide (`engine`)                                                                  |
| `atif/verdict.py`, `atif/segment.py` | result verdicts; purposes → segments → loops (kept as baseline B3)                                                                                |
| `atif/tar.py`                          | TAR iteration rows, annotation CSV, reading views                                                                                                   |
| `atif/audit.py`                        | per-record-type retention measurement, independent of the parsers                                                                                   |
| `atif/harbor_check.py`                 | Harbor's official validator over many files, in one process                                                                                         |
| `atif/cli.py`                          | `trajparse` commands                                                                                                                              |

## Design decisions worth knowing

- **One ATIF step = one LLM inference**, per the ATIF one-LLM-per-step convention. A step
  may carry several tool calls; the annotation export keeps that grouping in
  `parallel_calls_in_step` rather than flattening it away.
- Each agent's step boundary is recovered from its own format. Claude Code: one step per API
  response `message_id` (tool results can arrive between two blocks of one response); dumps
  without message ids fall back to ending a step at the next tool-result `UserMessage`
  (`extra.step_boundary` = `message_id` / `user_message`). Codex: the `token_count` event that
  follows every model response; rollouts without per-response counts fall back to one step per
  `reasoning` item (`extra.step_boundary` = `token_count` / `reasoning`). Qwen Code: one event per
  content block, and an inference closes at its one usage-bearing event, at the next tool result
  of its scope, or at a provider retry. Sub-agent work (Claude's and Qwen's task delegation) is
  embedded as `subagent_trajectories`.
- **Nothing is dropped silently, and it is measured rather than asserted.**
  `atif.cli audit` re-reads each raw log with its own code and reports, per record type,
  how much text reached the ATIF file.
- Tool output above 200,000 characters is truncated head+tail, flagged
  `observation.results[].extra.truncated`, with the original length in `original_chars`.
  The full text is always recoverable: `atif.cli output <bug> <agent> <call_id> --config … --run …`.
- Codex's system prompt, sandbox rules and project AGENTS.md are carried as `system`/`user`
  steps tagged `extra.record_kind`, so the context the agent acted under is in the file.
- Every trajectory records what its source format cannot express, in
  `extra.known_gaps`.
- The taxonomy never reads thought text. It cannot: thought is absent for many actions.
