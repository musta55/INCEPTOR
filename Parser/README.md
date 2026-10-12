# Parser — unified agent trajectories

Converts the raw logs in `../Dataset/` from Claude Code, Codex CLI and Qwen Code into one
schema ([ATIF v1.7](ATIF-v1.7-RFC.md)), then derives the action categories, the phases and
their outcome subphases ([Phase taxonomy.md](Phase%20taxonomy.md)), the viewer data and the
manual-annotation kit.

Runs on the system Python 3.9+, no dependencies (Harbor's official validator runs through `uv`).

## The corpus

50 Android UI bugs, three agents, 17 prompt configurations, 3 runs each:
3 × 17 × 3 × 50 = **7,650 trajectories**, every one with an APR outcome. An 18th configuration,
`file_method_screen` (Claude and Codex runs 1–2, Qwen run 1; 250 logs), has no outcome column; it
is converted only when named and stays out of every default and statistic.

```
Dataset/a_apr_test_results/<agent>_run<k>.csv        outcomes: bug_id + 17 config columns, 1 = APR pass
Dataset/p_claude_results/claude_<config>_run<k>/claude_logs/bug-<id>_output.txt    claude-agent-sdk dump
Dataset/o_codex_results/codex_<config>_run<k>/codex/log-bug-<id>/logs/codex-session-rollout-*.jsonl
Dataset/q_qwen_results/qwen_<config>_run<k>/qwen/bug-<id>.log    Qwen Code stream-json (+ bug-<id>.meta.json)
```

Configurations, in CSV order: `original`, `perfect`, `reference`, `title_ob`, `ob_omitted`,
`eb_omitted`, `s2r_omitted`, `file_method_no_screen`, and `{causing,manifesting,caus_man}_screen_description`
each alone, `_screenshot` and `_screenshot_xml`. Models: Claude Code `claude-opus-5`, Codex CLI 0.138.0
`gpt-5.6-sol`, Qwen Code 0.24.2 `qwen/qwen3.6-35b-a3b`. Some Claude run1/run2 transcripts are reruns;
see `Dataset/p_claude_results/{RERUN,RETEST}_SUBSTITUTIONS.txt`.

## Commands

Every command takes the same selection flags: bug ids (`8 18`, or `--all`, not both), `--config
NAME… | all` (default `original`, for `list` every config; `all` = the 17 with outcomes), `--runs
K… | all` (default `1 2 3`) and `--agent claude|codex|qwen` (repeatable; default all three). Bug ids
may come anywhere on the line except straight after `--config` or `--runs`, which take several
values.

```bash
cd Parser
python3 -m atif.cli list                                # agent x config x run matrix + APR pass counts
python3 -m atif.cli convert --all                       # original, runs 1-3, 3 agents: 450 trajectories
python3 -m atif.cli convert 18 --config all --runs 1    # one bug, every config, run 1
python3 -m atif.cli validate                            # re-validate the converted files of the selection
python3 -m atif.cli validate --from-raw --config all    # all 7,650 converted in memory; writes only the report
python3 -m atif.cli validate --harbor                   # plus Harbor's official validator
python3 -m atif.cli phases 18 --runs 1                  # phases -> subphases outline, with outcomes
python3 -m atif.cli view --all                          # viewer data: viewer/data/overview.js + bugs/bug-<id>.js
python3 -m atif.cli segment 18 --runs 1                 # purposes -> segments outline (baseline B3)
python3 -m atif.cli actions 18                          # categories, phases and the phase sequence
python3 -m atif.cli audit 18 --agent qwen               # how much of each raw log survived conversion
python3 -m atif.cli output 8 codex <call_id> --run 2    # one tool result in full, from the raw log
python3 -m atif.cli serve --open                        # viewer + Analyze page on http://127.0.0.1:8765/
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
uv run --python 3.12 --no-project --with harbor python -m atif.harbor_check --from-raw --config all --all
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

A validation report is named after what it covers: `atif-raw.json` / `harbor-raw.json` (or
`-converted`) for the whole corpus (17 configs × 3 runs × 3 agents × 50 bugs), otherwise with the
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

The viewer (`viewer/index.html`, then a bug's `viewer/bug.html`) opens from `file://` with no
server. It shows the `original` configuration: the overview holds run 1 of every bug × agent, and
each bug page holds runs 1–3 as phases → subphases → steps, with the repair attempts and the
first fix marked; its tooltips quote the codebook. The data format is
[View data contract.md](View%20data%20contract.md) (`trajview/3`); `python3 -m atif.cli view --all`
rewrites it after `convert`.

**Analyze a log, with your own rules.** `python3 -m atif.cli serve` starts a local server
(standard library only, this machine only) that serves the viewer and its third page,
`analyze.html`. Drop one log of Claude Code, Codex CLI or Qwen Code, or an ATIF file, on it: the
agent is recognised from the content, the bug id from the log's paths, and the trajectory is
shown with the bug page's Trajectory and Timeline views. Raw logs are read as the agents wrote
them: Codex's rollout JSONL, Qwen Code's stream-json, and for Claude Code its stream-json or
session transcript JSONL (or the SDK dump of the corpus); a JSON array of events works too.
Its Rules card has three tiers, one sentence per rule: **mandatory** rules (codebook G1–G7 and
the repeated-reads flag F1, with fixed numbers), always applied, with no way to switch them off,
remove them or change them, in the page or in a rules file; four **optional** rules (O1 lint is a
build, O2 shared test code, O3 project docs are orientation, O4 web lookups are localization),
none added by default, each added or removed with one click; and **custom** rules:
set the phase or the category of actions whose command, target or tool contains some text, or
the role of files whose path does. Each matching rule reports the actions it changed; one that
would break a mandatory rule (say, the first-fix boundary of G1) is listed as skipped. "+ Rule from this action" in the details panel starts a rule from an
action. Export the rules as `rules.json` and apply them to the corpus pages with
`view --all --rules rules.json`, or to one log with `analyze`. The rule set format is in
`atif/rules.py`; the default rule set reproduces `atif.phase` exactly (`tests/test_rules.py`).
The overview and bug pages show the rules they were built with under **Rules**.

Manual annotation runs on `Ground Truth/`, built by `python3 make_ground_truth.py`:
- 15 trajectories of `original`/run 1, 5 per agent, split by each agent's pass rate;
- one workbook per annotator, with a tab per trajectory.

The procedure, lookup tables and grouping rules are in
[Annotation Codebook.docx](Annotation%20Codebook.docx) (v3.0).

Scoring (codebook §11.1, spec §9): download each annotator's filled workbook from Drive, then

```bash
python3 score_ground_truth.py --annotator a1.xlsx --annotator a2.xlsx       # before adjudication
python3 score_ground_truth.py --annotator a1.xlsx --annotator a2.xlsx --reference reference.xlsx
```

It reports the annotators' agreement (kappa with a bootstrap CI over trajectories, boundary F1
exact and ±1, WindowDiff, and the Levenshtein distance between the phase sequences), the tool, baselines B1–B3 and the ablations against the reference
(round 2 = scored set, round 1 = development set), per-phase F1, a confusion matrix, results by
agent, the category accuracy, and the subphase-outcome precision. It writes into
`data/ground_truth/`: `tool_labels.csv` (the tool's labels for the 630 rows), `rows.csv` (every
workbook beside them), `disagreements.csv` (for the adjudication meeting, without tool labels),
`scores.json`, `report.md`, and once `subphase_audit.xlsx` (fill in `correct`, then run again).
The automated labels of every trajectory are also in `data/annotation/` (columns `phase`,
`own_phase`, `subphase`, `subphase_outcome`, `subphase_evidence`, `attempt`). The tool's phase rules are in
[Phase taxonomy.md](Phase%20taxonomy.md). The conversion pipeline is explained in
`Technical report.md`, which was written for the earlier corpus and is archived, with the
other plans of September, in `../Inspection/plans-and-reports-before-phase-taxonomy-2026-10-11.tar.gz`.

## Modules

| Module | Responsibility |
|---|---|
| `atif/schema.py` | ATIF envelope, truncation policy, dependency-free validator |
| `atif/claude.py` | `claude-agent-sdk` `repr()` dump → ATIF (AST-based, no `eval`) |
| `atif/codex.py` | Codex rollout JSONL → ATIF |
| `atif/qwen.py` | Qwen Code `stream-json` → ATIF |
| `atif/detect.py` | which parser a file needs, from its content |
| `atif/corpus.py` | the dataset layout: find any (agent, config, run, bug) log, output paths |
| `atif/outcomes.py` | APR outcomes per (agent, config, run, bug); badges read from the trajectory |
| `atif/taxonomy.py` | L1 `category`, file roles and the tool registry (the mid-level labels it refines are what baseline B3 reads) |
| `atif/phase.py` | phases → outcome subphases, metrics, invariants ([Phase taxonomy.md](Phase%20taxonomy.md)) |
| `atif/baselines.py` | baselines B1 (V2 first-edit split) and B3 (old purposes as phases) |
| `atif/codebook.py` | the codebook's lookup tables, word for word, for the workbooks and the viewer |
| `atif/agreement.py` | kappa, boundary F1 with tolerance, WindowDiff, bootstrap CIs (`score_ground_truth.py`) |
| `atif/view.py` | viewer data `trajview/3` ([View data contract.md](View%20data%20contract.md)) |
| `atif/rules.py` | rule sets: the built-in rules in plain words, their settings, custom phase / category / file-role rules |
| `atif/upload.py` | one uploaded log or ATIF text → `trajview-single/1` (Analyze page, `analyze`) |
| `atif/serve.py` | local server for the viewer and the Analyze page (`serve`) |
| `atif/verdict.py`, `atif/segment.py` | result verdicts; purposes → segments → loops (kept as baseline B3) |
| `atif/tar.py` | TAR iteration rows, annotation CSV, reading views |
| `atif/audit.py` | per-record-type retention measurement, independent of the parsers |
| `atif/harbor_check.py` | Harbor's official validator over many files, in one process |
| `atif/cli.py` | `trajparse` commands |

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
  `extra.known_gaps` — see [Log audit and collection spec.md](Log%20audit%20and%20collection%20spec.md).
- The taxonomy never reads thought text. It cannot: thought is absent for many actions.
