# TraceView — Project Summary

A reference description of the `agent-traj-visualization` repository (app name: **TraceView**),
written to be portable into other projects. All paths are relative to the repository root.
**§13 records the 2026-08-03 session update**: newly verified upstream data sources and the
research plan built on them (proposal: `Explainable Provenance and Trajectory Analysis.docx`);
where §13 conflicts with §11–12, §13 wins.

---

## 1. What it is

A Streamlit application for **manually labeling and visualizing step-by-step agent trajectories**
(SWE-agent / AutoCodeRover style) as directed graphs over `Thought`, `Action`, and `Result` nodes.

The research question it serves: *where does a coding agent stay aligned, where does it loop, and
where does it diverge or break down?* The tool answers that by making a human annotate the
**semantic relations between consecutive trajectory elements**, then rendering those annotations
as a colored graph.

Entry point: `traceview.py` (thin shim) → `traceview_app/app.py:main()`.
Run with `uv sync && uv run streamlit run traceview.py`. Requires Python >= 3.14.

Core dependencies actually used: `streamlit`, `streamlit-agraph`, `pandas`.
(`pyproject.toml` also declares `google-genai`, `dotenv`, `plotly`, `jsonlines`, `tqdm` — none are
imported anywhere in `traceview_app/` or `tools/`; leftovers from an abandoned LLM-labeling branch.)

---

## 2. Four routes

State key `traceview_route` in `st.session_state`; default route is **Labeling**.

| Route | Module | Purpose |
|---|---|---|
| `Labeling` | `traceview_app/labeling/` | Ingest a raw trace, label it, export it |
| `Overview` | `traceview_app/overview/` | Table of all available runs with outcome/flag summaries |
| `Analysis` | `traceview_app/analysis/` | The interactive graph (Iteration or Detailed mode) |
| `Inspector` | `traceview_app/analysis/inspector_ui.py` | Node detail, inline or as a separate page |

---

## 3. The central architectural idea

**The labeler and the viewer are decoupled by a file format, not by an in-memory object.**

Everything a user uploads is normalized into the exact same on-disk layout the bundled
AutoCodeRover dataset uses. The viewer therefore has one code path for both bundled and
user-generated runs. The join key is **filename stem + row position** — there are no explicit ids
linking a CSV row to a trajectory step; row index *is* the step index.

```
autocoderover_csv/
  actions_categories/<stem>.csv   # iteration,category  — one row per step
  thought_action/<stem>.csv       # single column `label` — row index = source step
  thought_thought/<stem>.csv
  action_action/<stem>.csv
  result_thought/<stem>.csv
  result_action/<stem>.csv
reconstructed_autocoderover/<stem>.txt   # Iteration N / Thought: / Action: / Result: blocks
data/json/results.json                   # patch outcomes, bundled dataset only
data/json/labeler_viewer_exports.json    # generated, git-ignored; metadata for uploaded runs
```

The bundled dataset is **40** hand-labeled AutoCodeRover tasks (a `ls` of `autocoderover_csv/*/`
shows 44 because local, git-ignored `*-labeled` test exports sit in the same directories).
**Nothing in the repository regenerates them** — see §11 for verified upstream provenance.

---

## 4. Pipeline: raw trace → interactive graph

### Stage 1 — Ingest & parse (`traceview_app/trajectory/parsers.py`)

Dispatch by file suffix (`parse_trajectory_bytes`, parsers.py:249):

| Input | Parser | How one step is formed |
|---|---|---|
| `.traj`, `.json` | `parse_sweagent_trajectory_payload` (:21) | one entry of the `trajectory` list = one step. thought = `thought` ‖ `response`; action = `action`; result = `observation` ‖ `result` |
| `.jsonl` | `parse_jsonl_trace_bytes` (:86) | event stream. `kind=="completion"` events accumulate into a pending-thought buffer; the next `kind=="exec"` event closes the step and supplies action + result |
| `.log`, `.txt` | `parse_text_trace_bytes` (:171) | regex split on `\b(Iteration\|Step)\s+(\d+)\b`, then section extraction of `Thought:` / `Action:` / `Result:\|Observation:` |
| `.zip` | `parse_trajectory_zip` (:284) | recurses over members with supported suffixes |

All converge on `ParsedTrajectory{task_id, source_name, steps}` where each step is
`TrajectoryStep(step_index, thought, action, result)` (`traceview_app/shared/models.py`).

Robustness: parse failures are collected into a warnings list rather than raised (:273); runs are
deduped by `trajectory.key`; 25 MB per-file cap (`labeling/state.py:39`); non-string JSON values are
coerced via `json.dumps` (`trajectory/common.py:16`).

Also supported: pasting raw text (becomes `pasted-trace.txt`) and loading a local
`sweagent_claude4_trajs/` folder if it exists.

### Stage 2 — Relation-candidate enumeration (`trajectory/relationships.py:36`)

Automatic. Crosses the 5 families of `REL_SPECS` (`shared/constants.py:58`) with every step, using a
fixed step offset:

| Family | src → dst | offset |
|---|---|---|
| `thought_action` | T → A | 0 (same step) |
| `thought_thought` | T → T | +1 |
| `action_action` | A → A | +1 |
| `result_thought` | R → T | +1 |
| `result_action` | R → A | +1 |

For N steps this yields ~5N−4 candidates (offset families have no candidate on the last step). Each
`RelationCandidate` carries a stable key `"{trajectory.key}|{family}|{source_step}"`, the source and
target node ids, and both evidence texts.

**The app decides which pairs could be related; the human decides what the relation is.**

### Stage 3 — Human labeling

See §6.

### Stage 4 — Export (`trajectory/exports.py:289 write_viewer_dataset_files`)

"Send to overview" writes, into the repo itself:

- `actions_categories/<stem>-labeled.csv`
- 5 × `<family>/<stem>-labeled.csv` (rows sorted by `source_step`, so row index = source step)
- `reconstructed_autocoderover/<stem>-labeled.txt`, regenerated in canonical block format
  (`reconstructed_log_text`, :212)
- a record in `data/json/labeler_viewer_exports.json` tagging the run
  `{agent_name: "uploaded", scored: false, source_name, task_id}`

Filename collisions are avoided by `unique_viewer_dataset_filename` (:248), which appends `-2`, `-3`, …

Alternative exits: **Download annotations JSON** (`annotation_json_bytes`, :103 — full records with
evidence text) and **Download viewer CSV zip** (`viewer_csv_zip_bytes`, :179).

Round-tripping: an exported run can be reopened for editing. `labeling/resume_export.py` re-parses
the generated `.txt` back into steps, then zips CSV rows onto freshly enumerated candidates sorted by
`(source_step, target_step, source_node, target_node)`.

### Stage 5 — Render (`analysis/view_context.py:37` → `analysis/graph_builder.py`)

`build_view_context` loads the CSVs (`@st.cache_data`), parses the reconstructed log back into
`{iteration: {thought, action, result}}`, resolves patch status, applies sidebar filters to produce
`edge_records`, then builds `streamlit_agraph` Node/Edge lists.

**Detailed mode** (`graph_builder.py:262`): three nodes per step (`T{i}`, `A{i}`, `R{i}`) laid out in
horizontal time order with fixed y-lanes. Semantic edges from the CSVs; optional gray structural
`T→A→R→T'` edges (`add_detailed_structural_flow_edges`, :186) which are suppressed when any relation
filter is active.

**Iteration mode** (:332, the default): one node per step labeled `I{i}` + category, plus
cross-iteration `action_action` edges and gray chronological edges between adjacent nodes.

---

## 5. How Thought / Action / Result are categorized

Two distinct kinds of categorization, and only one of them is semantic.

**Node type (T/A/R) is structural and fully automatic.** Nothing classifies text as a thought vs.
an action. Assignment comes from *where the text sat in the source format*: the `thought` key of a
SWE-agent step, a `completion` vs. `exec` event in JSONL, or the `Thought:` header in a text log.
Node ids are then just `T{i}` / `A{i}` / `R{i}` (`shared/node_ids.py:20`).

**Action category is semantic and 100% human.** Eight fixed options (`shared/constants.py:47`):

```
Explore · Locate · Search · Reproduce · Generate fix · Run tests · Refactor · Explain
```

They drive action-node color (`CATEGORY_COLOR`, :157 — looked up lowercased, so `"Generate Fix"`
matches) and Iteration-mode node labels.

**Relation labels are human, and constrained per family** (`RELATION_LABEL_OPTIONS_BY_FAMILY`, :124).
This is the sharpest design decision in the taxonomy — the option set is scoped to what is
semantically meaningful for that edge type:

| Family | Allowed labels |
|---|---|
| `thought_action` | Alignment, Misalignment |
| `thought_thought` | Follow-up, Refinement, Redundancy, Divergence, Contradiction |
| `action_action` | Follow-up, Refinement, Repetition, Divergence |
| `result_thought` | Follow-up, Refinement, No influence, Misinterpretation |
| `result_action` | Informative, Triggering, No influence |

The 12 labels collapse into 5 analytic/visual buckets (`REL_COLOR` :91, plus the set constants :168):

| Bucket | Labels | Color |
|---|---|---|
| good flow | Alignment, Follow-up, Refinement, Informative, Triggering | `#54A24B` green |
| divergence | Divergence | `#F58518` orange |
| loop-ish (`LOOPISH_RELS`) | Redundancy, Repetition | `#7F3C8D` purple |
| bad (`BAD_RELS`) | Misalignment, Misinterpretation, Contradiction | `#E45756` red |
| no influence (`NOINF_RELS`) | No influence | `#9E9E9E` gray |

Those three sets power the sidebar filters, the Overview "flagged relations" column, and the
labeling Issues tab.

Label normalization (`overview/data.py:33 normalize_rel`): trim, `_`/`-` → space, collapse
whitespace, capitalize first character.

---

## 6. The labeling workflow (user-facing)

Four stages driven by one state key (`labeling/router.py`):
`ingest → annotating → complete → workspace`.

1. **Ingest** (`labeling/ingest_ui.py:75`) — drop files, paste raw text, or load the local folder.
2. **"Annotating"** — a transition screen only. The progress bar is hard-coded to `0.68`, the screen
   `sleep(0.8)`s and auto-advances (:158, :173). The row reading *"Classifying node types — done"*
   just reports `N thoughts, N actions, N results`; **no classification runs here**.
3. **Completion summary** (`labeling/summary_ui.py`) — coverage metrics (iterations, graph nodes,
   action-label ratio, relationship-label ratio) plus four tabs: Summary (relation distribution),
   Behavior (per-iteration status), Action Categories, Issues (bad-relation check). Review only;
   everything stays editable.
4. **Single-run workspace** (`labeling/workspace_ui.py`) — the actual work, deliberately sequenced:
   - **Actions first**: one row per iteration showing an action preview, a "View" popover with the
     full T/A/R text, and a category selectbox (`workspace_action_ui.py:71`).
   - **Then relationships**, one family at a time via a sidebar selector, with source/target previews
     and an evidence popover (`workspace_relationship_ui.py:73`).
   - The relationship step is hard-gated on the action step (`workspace_ui.py:98`); export is gated
     on both (`workspace_sidebar.py:123`).
   - Sidebar carries live progress bars, a compact legend scoped to the current family, navigation
     between the two passes, and the three export controls.

Label storage: two `st.session_state` dicts keyed by
`"{trajectory.key}|{family}|{source_step}"` (relations) and `"{trajectory.key}|action|{step}"`
(actions). Widget keys are versioned by `LABELER_EDITOR_VERSION = "v4"`. Labels invalid for a family
are dropped on family switch (`discard_invalid_family_labels`).

---

## 7. Automated vs. manual

**Automated**
- Trace parsing and T/A/R splitting across 4 input formats
- Relation-candidate enumeration (which pairs exist)
- Label normalization and per-family validity enforcement
- All file writing: CSVs, reconstructed log, metadata JSON, collision-free filenames
- Graph layout, node/edge coloring, relation filtering
- Per-iteration behavior classification into bad / loop-ish / no influence / labeled / unlabeled
  (`summary_ui.py:90`)
- Bad-relation issue detection; `first_flagged_iteration` in Overview
- Patch-status reduction from `results.json` via a fixed priority list
  (`overview/data.py:335 derive_primary_patch_status`) and PASS / FAIL / UNSCORED styling of the
  terminal result node (`graph_builder.py:40`)
- GitHub PR URL derived from an `owner__repo-N` filename stem, plus a live GitHub API lookup for the
  linked bug-report issue, cached 24 h (`overview/data.py:304`)

**Manual**
- Every semantic judgment: the 8 action categories, all 12 relation labels

**There is no auto-labeling, no LLM pass, and no heuristic pre-fill anywhere in the codebase.**

---

## 8. Patch outcome handling

`data/json/results.json` maps outcome categories → lists of task ids. A task may match several; they
are reduced to one primary status by priority order (resolved > test_timeout > test_errored >
no_apply > no_generation > install_fail > reset_failed > applied > generated > with_logs > UNKNOWN).

- `RESOLVED` → green `PASS`, final result node enlarged
- `UNKNOWN` → gray `UNSCORED`
- anything else → red `FAIL`

Uploaded runs are always `UNSCORED` — the app deliberately refuses to infer patch outcomes for
arbitrary logs. Detection of "is this an uploaded run" is by metadata lookup OR filename marker
(`-labeled`, `__eval_`) — see `USER_VIEWER_EXPORT_MARKERS`.

---

## 9. Module map

```
traceview.py                       # entrypoint shim
traceview_app/
  app.py                           # routing, dataset guard
  layout_ui.py                     # header, sidebar chrome, scroll helper
  shared/
    constants.py                   # paths, taxonomies, colors, REL_SPECS  ← the schema lives here
    models.py                      # ParsedTrajectory, TrajectoryStep, RelationCandidate, TypedDicts
    node_ids.py                    # T{i}/A{i}/R{i}/I{i} id construction + parsing
    formatting.py
  trajectory/                      # format-agnostic core, no Streamlit imports
    parsers.py                     # raw → ParsedTrajectory
    relationships.py               # candidate enumeration, label validity
    exports.py                     # ParsedTrajectory + labels → viewer files
    common.py                      # sentinels, text coercion
  labeling/                        # Labeling route (stateful, Streamlit-heavy)
    router.py state.py ingest_ui.py summary_ui.py
    workspace_ui.py workspace_action_ui.py workspace_relationship_ui.py
    workspace_sidebar.py workspace_shared.py common_ui.py resume_export.py
  analysis/                        # Analysis + Inspector routes
    route.py view_context.py graph_builder.py sidebar_ui.py
    inspector_ui.py iteration_ui.py iteration_context.py
  overview/
    data.py                        # ALL disk I/O + caching + patch/GitHub resolution
    ui.py
tools/create_evaluation_samples.py # regenerates the 8-step .traj fixtures in evaluation_samples/
docs/                              # evaluation_instructions.md, TraceView_Survey.csv, images/
```

Layering is clean: `trajectory/` is pure logic with no Streamlit dependency; `overview/data.py` owns
disk access and caching; UI modules never read files directly.

---

## 10. Known gaps and sharp edges

Worth carrying forward if this design is reused.

1. **The completeness gate is very weak.** `MIN_LABELS_TO_ADVANCE = 5` with
   `required = min(5, total)` (`workspace_shared.py:16,39`) means a 40-step run (~196 candidate
   edges) can be exported to Overview with **5 action labels and 5 relation labels**. Unlabeled
   actions export as the literal string `"Labeled trace"` (`VIEWER_EXPORT_CATEGORY`,
   `trajectory/common.py:11`) — not one of the 8 categories, so it silently falls back to the default
   blue in the graph and is dropped on resume by `_canonical_action_label`. The graph renders as if
   the run were fully labeled. **If collecting study data, tighten this first.**

2. **Iteration mode no longer aggregates.** `build_iterations` (`graph_builder.py:48`) emits one
   iteration per CSV row, so `I6` ≡ step 6. The two graph modes differ only in node granularity
   (3 vs. 1), not time granularity. The `start_step` / `end_step` / `steps` fields on
   `IterationRecord` imply run-length merging was once intended; the data model still carries that
   generality.

3. **Dark code.** `analysis/iteration_context.py` is a complete heuristic action-summarizer and
   file-mention extractor — the closest thing here to automatic categorization — switched off by
   `SHOW_DERIVED_ITERATION_CONTEXT = False` (:30), because uploaded logs come from inconsistent agent
   formats.

4. **Stale README references.** The README's Repository Layout lists `schema.txt` and
   `llm_label_demo.ipynb`, and the Evaluation Materials section points at
   `docs/evaluation_video_script.md` and a survey PDF. None of those files exist.

5. **Exports write into tracked source directories.** User data lands in `autocoderover_csv/` and
   `reconstructed_autocoderover/` next to the bundled dataset, distinguished only by the `-labeled`
   filename marker. `delete_user_viewer_export` guards on that marker, so a bundled task whose stem
   happened to contain `-labeled` would become deletable. Uploaded runs are also one `git add` away
   from being committed as dataset files.

6. **Position-based joins are brittle.** CSV row index = step index, with no id column. Any
   reordering, any row insertion, or a reconstructed log whose thought text contains a line like
   `Iteration 3` will silently misalign labels against steps.

7. **The "Annotating" screen is theater.** Fixed 68% progress, an 0.8 s sleep, and a "Classifying
   node types" row that classifies nothing. Harmless, but misleading if a reader assumes automated
   classification exists.

---

## 11. Upstream dataset: verified provenance and reuse

Everything in this section was verified against the live GitHub API on 2026-08-01, not inferred.

### 11.1 Where the bundled data actually came from

| Artifact | Verified source |
|---|---|
| `reconstructed_autocoderover/*.txt` | `AutoCodeRoverSG/auto-code-rover` → `results/acr-run-1/` |
| `data/json/results.json` | `AutoCodeRoverSG/auto-code-rover` → `results/acr-run-3/new_eval_results/report.json` (**byte-identical**) |

Repo: <https://github.com/nus-apr/auto-code-rover> (redirects to `AutoCodeRoverSG/auto-code-rover`,
numeric id `783546882`). The run is AutoCodeRover **v20240408 + GPT-4-0125-preview** on
**SWE-bench-lite**, the release accompanying [arXiv:2404.05427](https://arxiv.org/abs/2404.05427)
(19% pass@1 ≈ 57/300).

Verification method for the trace source: the first assistant message of
`results/acr-run-1/applicable_patch/django__django-11133_2024-04-06_13-41-50/conversation_round_1.json`
is a literal substring of `reconstructed_autocoderover/django__django-11133.txt`; the corresponding
`acr-run-3` file is *not* (different wording — the runs are independent samples).

### 11.2 ⚠️ Data-integrity defect inherited from this mix

**The bundled trajectories are from `acr-run-1` but the PASS/FAIL scoring is from `acr-run-3`.**
The two runs differ (54 vs 57 resolved; only 46 tasks resolved in both).

Of the 40 bundled tasks, **3 display the wrong outcome**:

| Task | Truth for the shown trajectory (run-1) | What TraceView displays (run-3) |
|---|---|---|
| `pytest-dev__pytest-7432` | not resolved | **PASS** |
| `scikit-learn__scikit-learn-13241` | resolved | **FAIL** |
| `scikit-learn__scikit-learn-13497` | resolved | **FAIL** |

Fix by replacing `data/json/results.json` with `results/acr-run-1/new_eval_results/report.json`.
It is drop-in: identical key set (`resolved`, `generated`, `applied`, `no_apply`, …), which is
exactly the shape `derive_primary_patch_status` expects. **Do this before any reuse** — otherwise
every downstream correlation between labeled agent behavior and task success is contaminated.

### 11.3 The archives on GitHub — what is and isn't reusable

**Reusable — the AutoCodeRover repo's own `results/` tree.** Not tar archives; plain directories
committed to `main`, browsable and fetchable per-file via the GitHub API or a shallow clone:

```
results/
  acr-run-1/ acr-run-2/ acr-run-3/     # 3 independent SWE-bench-lite runs
  acr-val-only/ acr-val-sbfl/          # ablations (val-sbfl is the best: 66 resolved)
  swe-agent-results/                   # SWE-agent comparison traces
  examples/
```

Each run holds per-task directories named `<instance_id>_<YYYY-MM-DD_HH-MM-SS>`, bucketed by
outcome. For `acr-run-3`: `applicable_patch/` (242) + `raw_patch_but_unmatched/` (58) = **300 = the
full SWE-bench-lite split.**

**Only 40 of 300 are currently labeled — 260 tasks are available and untouched**, plus two further
full runs and two ablations if you want inter-run variation on identical task instances (a genuinely
strong experimental design: same task, same agent version, different sample).

**Not reusable — the SWE-bench experiments repo.** `swe-bench/experiments` hosts two AutoCodeRover
submissions (`evaluation/lite/20240530_autocoderover-v20240408`, `.../20240621_...`), but both
contain only `README.md`, `metadata.yaml`, `results/`. Their `metadata.yaml` says literally:

```yaml
assets:
  logs: s3://swe-bench-submissions/lite/20240530_autocoderover-v20240408/logs
  trajs: null
```

**`trajs: null`** — no trajectories. Do not plan around this repo for AutoCodeRover. (It *is* useful
for other agents whose submissions populate `trajs/`, if you want cross-agent comparison; formats
there are per-submitter and unconstrained — "any text based file format".)

### 11.4 Raw ACR per-task format → TAR mapping

A task directory contains:

| File | Content |
|---|---|
| `conversation_round_N.json` | list of `{role, content}` messages — **the trajectory itself** |
| `tool_call_layers.json` | tool calls **grouped by round** → aligns 1:1 with iterations |
| `tool_call_sequence.json` | same calls, flat, with `call_ok` success flags |
| `problem_statement.txt` | the GitHub issue text |
| `extracted_patch_1.diff`, `developer_patch.diff` | agent patch vs. gold patch |
| `meta.json`, `cost.json`, `info.log` | task metadata, token cost, full log |
| `agent_proxy_N.json`, `debug_agent_write_patch_1.json` | proxy/patch-writer sub-agent transcripts |

The TAR extraction rule, derived from the ACR conversation protocol:

| TraceView field | Source in `conversation_round_N.json` |
|---|---|
| **Thought** | `assistant` message content (prose reasoning, before the ```python block) |
| **Action** | the tool calls of that round — take from `tool_call_layers.json[N]` (structured, preferred) or parse the ```python block |
| **Result** | the following `user` message beginning `Result of <call>:` |

The terminal iteration is special: action `write_patch`, result taken from `extracted_patch_1.diff`
(the bundled files render `<Missing>` where this was absent).

`tool_call_layers.json` is the key convenience — it is *already* layer-grouped per conversation
round, so iteration boundaries need no heuristic recovery.

### 11.5 Two concrete ingestion routes

**Route A — write the missing converter (recommended).** The original reconstruction script was
never committed. Reimplement it as `tools/reconstruct_acr.py`: read a task dir, emit
`reconstructed_autocoderover/<instance_id>.txt` using the exact block format that
`exports.reconstructed_log_text` produces and `overview/data.parse_reconstructed_log` consumes:

```
Iteration N

Thought:
...

Action:
...

Result:
...
```

Then label in the app as normal. This matches the existing dataset shape exactly and needs **zero**
application changes.

**Route B — go through the uploader.** Convert each task dir to a SWE-agent-shaped JSON
(`{"instance_id": ..., "trajectory": [{"thought","action","observation"}, ...]}`) and drop it on the
Labeling page. `parse_sweagent_trajectory_payload` handles it as-is. Slightly more code than Route A
but keeps everything inside the supported upload path and gives you a portable intermediate format.

**Note on `.tar`:** TraceView's `SUPPORTED_TRAJECTORY_SUFFIXES` is `{.traj, .json, .jsonl, .log,
.txt}`, and only `.zip` gets archive handling (`parse_trajectory_zip`). **Tar/tar.gz is not
supported** — extract first, or add a `parse_trajectory_tar` mirroring the zip path (~15 lines,
`tarfile` has the same iteration API). Since the ACR data is plain directories, this is only needed
if you tar it up yourself for transport.

### 11.6 Licensing — check before publishing

The ACR repo's `LICENSE` on `main` is **SONAR Source-Available License v1.0**, and the commit that
introduced it (2025-02-26) is titled *"Update license to reflect long-standing non-commercial
terms"*. The GitHub API reports `NOASSERTION` — i.e. not a recognized OSI license. Licensing changed
three times after the April 2024 data was published (2024-05-17, 2024-07-15, 2025-02-26).

Academic use is likely fine and the arXiv paper is citable, but **confirm terms and cite both the
paper and the repo before redistributing any derived dataset.** Do not assume Apache/MIT. The
underlying SWE-bench task instances carry their own upstream repository licenses.

---

## 12. Planned extension: three-tier trajectory analysis

The intended direction is three levels of abstraction over the same trace.

| Tier | Artifact | Producer | Status |
|---|---|---|---|
| **0 — Raw** | ACR task dirs / SWE-agent `.traj` | upstream agent run | available, 300 tasks (§11.3) |
| **1 — TAR-labeled** | per-step Thought/Action/Result + action category + 12 relation labels | human (today) | 40/300 done |
| **2 — High-level activities** | segments spanning multiple iterations, each an *activity* | agent-assisted (planned) | not built |

### 12.1 What Tier 2 needs that doesn't exist yet

Tier 1 is deliberately **local**: every relation spans step *i* → step *i*(+1). Nothing in the schema
can express "steps 4–9 were one reproduction attempt that failed." That is precisely the gap Tier 2
fills, and it needs three new things:

1. **A segment model.** `IterationRecord` already carries `start_step` / `end_step` / `steps`
   (`shared/models.py`) but `build_iterations` collapses it to one step per record
   (§10.2). *That field set is the natural home for activity spans* — the aggregation was designed
   for and then rolled back. Restoring it is the cheapest structural path to Tier 2.
2. **An activity vocabulary**, distinct from the 8 step-level action categories. Step-level asks
   *"what did this action do?"*; activity-level asks *"what was the agent trying to accomplish, and
   did it get there?"* Expect something like: *reproduce the bug · localize the fault · gather
   context · form a hypothesis · implement a fix · verify · recover from failure · give up*, each
   with an outcome (succeeded / abandoned / looped).
3. **A persistence slot.** Adding `autocoderover_csv/activities/<stem>.csv` with
   `start_iteration,end_iteration,activity,outcome` would fit the existing conventions — but note it
   breaks the "row index = step index" assumption every other CSV relies on, so it needs explicit
   start/end columns rather than positional encoding.

### 12.2 Agent-assisted labeling — design constraints from this codebase

The repo is *well-shaped* for adding an LLM pass, and partly pre-wired for it:

- `google-genai` is already a declared dependency (currently unused — §1). The abandoned
  `llm_label_demo.ipynb` and `schema.txt` referenced in the README suggest this was started once.
- `trajectory/` is pure logic with no Streamlit imports — an `trajectory/auto_label.py` slots in
  cleanly beside `relationships.py` without touching UI code.
- `build_relation_candidates` already enumerates every candidate with **both evidence texts
  attached** (`source_text`, `target_text`). That is exactly the payload an LLM judge needs; a
  suggestion pass is a `map` over that list.
- Per-family option sets (`RELATION_LABEL_OPTIONS_BY_FAMILY`) give the model a **small constrained
  label space** (2–5 options), which is the single biggest accuracy lever — never prompt with all 12.

Recommended shape, given the research goal:

- **Suggest, never autofill.** Keep human labels and model labels in *separate* state dicts and
  separate export columns. If model output silently becomes ground truth, the dataset can no longer
  answer "how well does the agent judge agent behavior?" — which is likely a result worth reporting.
- **Pre-fill the selectbox default but mark it unconfirmed**, so agreement rate is measurable. The
  UI already round-trips a `current_label` through `option_index`, so this is a small change to
  `workspace_action_ui.py` / `workspace_relationship_ui.py`.
- **Use Tier 1 as ground truth for Tier 2.** The 40 already-labeled runs are a validation set for
  the activity segmenter — measure boundary agreement before scaling to the other 260.
- **Feed the model structure, not just prose.** `tool_call_layers.json` gives exact per-round tool
  calls and `call_ok` flags; a failed call is a strong signal for "recovery" activities and is far
  more reliable than asking a model to infer failure from log text.

### 12.3 Sequencing

1. Fix `results.json` → `acr-run-1` (§11.2). Cheap, and everything downstream depends on it.
2. Tighten the export gate (§10.1) before collecting any more human labels.
3. Write `tools/reconstruct_acr.py` (§11.5 Route A) and ingest the remaining 260 tasks.
4. Build the Tier-2 activity vocabulary against the 40 existing labeled runs *by hand first* — the
   vocabulary has to be validated by a human before it is worth automating.
5. Add the agent-assisted suggestion pass, measured against those human activity labels.

---

## 13. Session update (2026-08-03): verified sources and the resulting research plan

Everything below was verified against live GitHub APIs on 2026-08-02/03 while writing the
research proposal (`Explainable Provenance and Trajectory Analysis.docx`). Where this section
conflicts with §11–12, this section is current.

### 13.1 The Bouzenia & Pradel replication package is the better upstream (supersedes parts of §11)

`sola-st/llm-agents-study` — the replication package of the TAR study (arXiv:2506.18824) —
verified contents:

- **MIT license** (Copyright 2025 Islem Bouzenia) — unlike the ACR repo's source-available
  non-commercial license, this is freely reusable and redistributable with attribution.
- **40 labeled tasks × 3 agents** (`autocoderover_csv/`, `openhands_csv/`, `repairagent_csv/`),
  each in the same 6-CSV schema TraceView uses (`actions_categories/` with `iteration,category`
  + the 5 relation-family dirs with a single `label` column).
- `trajectories/<agent>/parsed/<family>/<task>`: paired component texts
  (`Thought at Iteration N: …` / `Action at Iteration N: …`), so every label rejoins its
  source/target text. The join is positional (CSV row = pair index, no id columns) — the same
  brittleness as §10.6; verify alignment before use.
- RepairAgent has **60** parsed trajectories (40 labeled + 20 unlabeled extras).
- `parsers/` — working parsers for all three agents' native formats (reusable for ingestion).
- `rq2_stats/` — resolved-vs-unresolved **unique-4-gram mining over action categories**,
  descriptive only (no significance tests, no effect sizes, categories-only). Any new mining
  claim must be positioned against this.
- README lists resolved/unresolved instance ids per agent → outcome labels without TraceView's
  `results.json`.

**TraceView's bundled dataset is a copy of this package's AutoCodeRover portion** — verified:
identical 40 task ids, identical label content (line-ending differences only). Consequences:
TraceView's bundle is not an independent dataset, and the §11.2 outcome-mismatch defect is moot
for any project that takes outcomes from this package or from the run-1 report directly.

### 13.2 Scale-up trajectory availability (extends §11.3)

| Agent | Verified source | Status |
|---|---|---|
| AutoCodeRover | `results/acr-run-1/` tree (§11.3) | 300 tasks, in-repo, available |
| OpenHands | `swe-bench/experiments` lite submissions `20240725_opendevin_codeact_v1.8_claude35sonnet` and `20241025_OpenHands-CodeAct-2.1-sonnet-20241022` | `trajs:` populated as **public S3 assets** (`s3://swe-bench-submissions/...`, no-sign-request); in-repo `results/` gives outcomes |
| RepairAgent | `sola-st/RepairAgent` | **code only** — `data/` holds bug metadata, no run archive, no Zenodo/Figshare link; largest public trajectory set is the 60 in the B&P package |

### 13.3 Reusable high-level activity vocabularies (input to §12's Tier 2)

- **Kimi-Dev** (arXiv:2509.23045): LLM-annotates SWE-agent turns into 5 stages — repo
  exploration, error reproduction via test script, code edit, test re-execution, edge-case
  checks. Never validated against humans.
- **Agentless** (arXiv:2407.01489): fixed localization–repair–validation workflow.
- **Graphectory** (arXiv:2512.02393): observes localization–patching–validation phase structure
  in resolved runs vs. chaotic/backtracking behavior in unresolved ones.
- **ReTrace** (arXiv:2511.11187): 4-phase taxonomy, but for reasoning traces, not tool-use.

None validates its stage assignments against human judgment — so for a new project the
contribution is **validation of a consolidated vocabulary, not invention of a new one**.

### 13.4 The finalized research plan (supersedes the §12 sketch)

Two committed artifacts: (1) a validated two-level annotation pipeline; (2) a **lightweight
standalone tool** — not a TraceView extension — with exactly three views (TAR trajectory with
agent-assisted labels; activity timeline with drill-down to sub-trajectories; statistics), a
JSON output contract, and TraceView-compatible CSV export.

- **RQ1 (annotation fidelity):** LLM annotator scored against the ~14K-pair ground truth;
  human inter-annotator agreement as ceiling. Serves as the checkpoint; the annotator
  configuration is frozen once agreement approaches the ceiling.
- **RQ2 (activity identification):** scored against a doubly-annotated reference subset
  (2 humans × 15–20 trajectories, adjudicated); human–human agreement is the ceiling;
  per-iteration Cohen's κ + windowed boundary F1 (+ Pk/WindowDiff). The activity codebook
  defines each activity by evidence rules over observable step features, entry/exit rules, and
  a partition constraint (every iteration in exactly one contiguous segment) — the constraint
  is what makes both automation and agreement measurement well-defined.
- **RQ3 (behavioral insight):** confirmatory (pre-registered B&P anti-patterns;
  chi-square/Fisher, effect sizes) + exploratory (activity orderings/transitions/outcomes,
  category n-grams n=2–4, relation motifs; ≥10% support threshold; Benjamini–Hochberg FDR).
  Per-agent tests committed only for the two 300-task corpora (ACR, OpenHands); RepairAgent
  (60) enters descriptively and pooled.
- **Datasets:** D1 = the B&P package; D2 = ACR run-1 + one OpenHands submission + RepairAgent's
  60 from D1. Deliberately nothing depends on author contact or unreleased data.
- **Annotator design:** two LLMs from different providers, temperature 0, per-family
  constrained label spaces, disagreement-triggered human review; no fine-tuning — ground truth
  is used only for few-shot exemplars and evaluation.
- **Milestones (Fall 2026):** M1 data foundation (Sep 14) → M2 TAR pipeline + RQ1 (Oct 5) →
  M3 activity codebook (Oct 19) → M4 segmentation + RQ2 (Nov 9) → M5 scale-up + RQ3 (Nov 23) →
  M6 tool + report (Dec 7); contingency to Dec 15.
