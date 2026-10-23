# View data contract (`trajview/3`, `trajview-overview/3`)

This file is the interface between the Parser (producer, `atif/view.py`) and the viewer
(consumer, `Parser/viewer/`). Version 3 replaces the purposes, segments and loops of version 2
with the phase taxonomy (`Phase taxonomy.md`, `atif/phase.py`): phases → subphases, repair
attempts and per-trajectory metrics.

- **Producer:** `python3 -m atif.cli view --all` (run `python3 -m atif.cli convert --config original
  --runs 1 2 3 --all` first). Options: `--config original` (exactly one configuration),
  `--runs 1 2 3`, `--overview-run 1`, `--path Parser/viewer`, and bug ids instead of `--all`
  (`view 8 18` rewrites those bug files; the overview is always rewritten for every bug).
- **Files:**

  | file | statement | schema | page |
  |---|---|---|---|
  | `viewer/data/overview.js` | `window.TRAJ_OVERVIEW = {...};` | `trajview-overview/3` | `index.html` |
  | `viewer/data/bugs/bug-<id>.js` | `window.TRAJ_BUG = {...};` | `trajview/3` | `bug.html#bug=<id>` |

  Both are JavaScript statements, not JSON, so the pages work from `file://`, where `fetch()` of
  a local file is blocked. `bug.html` loads a bug file by injecting a `<script>` tag.
  `view.read_js(path)` loads either one back into Python.
- **Scope:** one prompt configuration (`original` by default). The overview holds one run
  (`--overview-run`, default 1) of every bug x agent as summaries; a bug file holds every run
  (`--runs`, default 1 2 3) of every agent of that bug in full.
- **Rule:** the viewer must ignore fields it does not know. Fields marked *extra* below are
  written today but are not needed by the viewer. The viewer refuses a file of another schema
  and says how to regenerate it.

## Bug file: `trajview/3`

```jsonc
window.TRAJ_BUG = {
  "schema": "trajview/3",
  "generated_by": "atif <parser_version>",
  "bug": "18",                                 // string
  "app": "es.usc.citius.servando.calendula",   // app package pooled over the bug's logs, or null
  "config": "original",
  "runs": [1, 2, 3],                           // ints, the runs this file covers
  "agents": ["claude", "codex", "qwen"],       // canonical order
  "outcome_source": "a_apr_test_results",
  "vocab": { /* see "Vocabulary" */ },
  "trajectories": [ /* one per converted (agent, run), agents in order, then by run */ ]
}
```

A run that was not converted is simply absent from `trajectories` (the viewer shows the cell
as "not converted").

### Trajectory

```jsonc
{
  "id": "bug-18/codex/original/run2",          // "bug-<id>/<agent>/<config>/run<k>"
  "bug": "18", "agent": "claude|codex|qwen", "config": "original", "run": 2,
  "app": "es.usc.citius.servando.calendula",   // same as the file's app
  "model": "gpt-5.6-sol",                      // extra: the log's model name, or null
  "n_actions": 20,                             // tool calls = len(actions)
  "n_steps": 17,                               // agent steps (LLM turns) in the ATIF file
  "anchor": 9,                                 // the first fix: action index of the first edit of
                                               //   app source, or null when there is none

  "outcome": {                                 // from the outcome CSVs (atif.outcomes.outcome_for)
    "pass": true,                              // this (agent, config, run, bug); null if missing
    "by_run": {"1": true, "2": true, "3": false},          // same config, every run
    "by_config": {"original": true, "perfect": true, ...}  // extra: same run, the 17 configs
  },
  "badges": {                                  // process facts (atif.outcomes.phase_badges)
    "self_claims_pass": false,                 // the final message claims the tests pass
    "reproduced_before_fix": false,            // always false since Reproduction was dropped (2026-10-19)
    "test_modified": false,                    // a subphase has the test_modified flag
    "repeated_failure": false,                 // a subphase has the repeated_failure flag
    "blocked_checks": 0,                       // subphases with outcome blocked
    "final_repair_outcome": "succeeded",       // outcome / evidence of the last Repair subphase,
    "final_repair_evidence": "build",          //   null without a Repair phase
    "last_test_verdict": "pass|fail|none",     // verdict of the last test run
    "self_report": "claims_build_only"         // extra: reports_failure | claims_suite_pass | claims_target_pass |
                                               //   claims_unit_tests | claims_build_only | no_test_claim | empty
  },
  "badge_steps": {                             // extra: the first action of each subphase behind a badge
    "reproduced_before_fix": [], "test_modified": [], "repeated_failure": [],
    "blocked_checks": [], "final_repair": [23], "last_test_verdict": [12]
  },
  "stats": {
    "n_phases": 4,                             // phase spans
    "n_subphases": 5,
    "n_attempts": 1,                           // repair attempts (edits and the run that checks them)
    "n_failed_actions": 2,                     // verdict fail or the log's own error flag
    "anchor": 9,                               // same as the trajectory's anchor
    "duration_s": 312.4,                       // first to last step timestamp; null without timestamps
    "reported_duration_s": 304.1               // extra: the log's own duration_ms / 1000, or null
  },
  "metrics": { /* atif.phase.metrics, verbatim (Phase taxonomy.md §8): <phase>_actions (polls left
                  out), env_actions, n_attempts, n_failed_attempts, n_blocked_attempts,
                  attempts_to_first_pass, repair_cycles, reentries {phase: n},
                  reproduced_before_fix, actions_to_first_found, target_source,
                  blocked_subphases, <flag>_subphases, tool_errors, reverts, self_reviews,
                  final_{repair,validation}_{outcome,evidence}; {} for a trajectory without
                  tool calls */ },

  "actions": [ /* Action, ordered by i */ ],
  "targets": { "source": "final_patch", // the Localization target files: developer_fix | final_patch | none
               "files": ["app/src/…/Foo.java"] },   // repository paths, sorted (<= 12)
  "phases": [ /* Phase span */ ],
  "attempts": [ /* Attempt */ ]
}
```

Claude and Qwen steps carry no timestamps, so their `duration_s` and every action's `ts` are null;
the viewer then draws the timeline over the action index only.

### Action (one per tool call)

```jsonc
{
  "i": 7,                          // action index, 1-based; actions[k].i == k + 1
  "step": 6,                       // ATIF step id of the LLM turn that issued the call
  "scope": "main",                 // or "sub-<delegating call id>" for a sub-agent's call
  "tool": "Bash",                  // the raw tool name
  "category": "test",              // action category (vocab.categories, the action table of the
                                   //   Final lookup tables, atif/lookup.py)
  "item": "gradlew test tasks",    // extra: the action table's entry that gave the category
  "phase": "localization",         // final phase: the phase span the action is in
  "row": "L6",                     // the phase table's row that gave the phase (L1-L15, LG for
                                   //   the general rule), or "user" for a phase row of the user's
  "own_patch": true,               // only when true: it reads back files the agent already changed
  "file_role": "source, test",     // the targets of the files it works on (the target table:
                                   //   source, test, docs, build, other, outside), comma-
                                   //   separated, in table order; "" for none
  "target": "./run_pipeline.sh …", // <= 200 chars, whitespace-collapsed
  "verdict": "pass|fail|none",     // of a build / test run
  "fail_kind": "test|build|env|exit|null",
  "evidence": "build_ok",          // extra, only with a verdict (or "no_test_evidence"): the marker
                                   //   that decided it (atif.verdict: results, gradle_tests, build_ok,
                                   //   build_fail, exit, pytest, ...)
  "evidence_line": "BUILD SUCCESSFUL in 1m 55s",   // extra, when a line shows it: the result's
                                   //   line with that marker (<= 200 chars), so the verdict can be
                                   //   checked although "result" keeps only the first 300 chars
  "failed_raw": false,             // the log's own error flag on the tool result
  "reverts": true,                 // only when the action undoes changes (git checkout / restore / ...)
  "ts": "2026-…" | null,
  "thought": "…",                  // <= 300 chars: reasoning or narration of the issuing turn
                                   //   (parallel calls of one turn repeat it)
  "thought_source": "reasoning|narration|none",   // extra
  "result": "…",                   // <= 300 chars of the tool result; the full thought and
                                   //   result are in the ATIF (corpus packs, or the upload's own)
  "call_id": "toolu_…",
  "edits": ["app/src/…/Foo.java"], // extra, only on edits: files written (<= 6, each <= 200 chars)
  "files": ["app/src/…/Foo.java"], // extra: repository files the action names (atif.segment.enrich,
                                   //   folders left out; <= 12); a search's "-name Foo.java" gives the name only
  "found": ["app/src/…/Bar.java"], // extra, only on searches: repository files its output lists, a
                                   //   path that starts its line (grep -rn / rg / find / grep -l; <= 20)
  "n_found": 36,                   // extra, only when a search lists more files than "found" keeps
  "tests": ["CardBrowserTest"],    // extra, only on test runs: what it tests, by name: its --tests /
                                   //   -e class filters, else the test or scratch files it names,
                                   //   else "task testDebugUnitTest" (the suite), "dry run of x.patch"
                                   //   or "the app on a device (adb)"
  "step_outcome": "succeeded",     // extra: the outcome this step itself shows (atif.phase.step_outcomes):
                                   //   a Localization step that touches a target file; an edit of a
                                   //   judged repair attempt (the attempt's outcome); a decisive run
                                   //   (its result in its phase). Absent = unchecked
  "step_evidence": "test",         // extra, with step_outcome: test | build | target_file
  "cmd": "rg -n Foo app/src"       // extra, only when it differs from target: the shell command
                                   //   (<= 200 chars); Claude's Bash target is its description
}
```

### Phase span, subphase, attempt (from `atif.phase`)

```jsonc
// Phase span: contiguous; together they cover 1..n_actions exactly once. A phase may recur.
{ "id": "p3", "phase": "repair", "start": 23, "end": 33, "n_actions": 11,
  "subphases": [ /* Subphase, contiguous, covering the span exactly once */ ] }

// Subphase: a maximal stretch of the span with one outcome (run-length encoded)
{ "id": "p3.1",                                // unique within the trajectory
  "outcome": "succeeded|failed|blocked|unchecked",   // vocab.phase_outcomes[phase]
  "evidence": "test|build|target_file|none",   // the strongest check behind the outcome
  "start": 23, "end": 33, "n_actions": 11,
  "n_events": 1,                               // checks (decisive runs or attempts) merged into it
  "n_attempts": 1,                             // repair attempts among them
  "checks": [33],                              // the actions that decided the outcome (<= 5): each
                                               //   run, an attempt's judging run (which may come
                                               //   after the subphase: an edit-only stretch of an
                                               //   attempt is judged by the build or test after it),
                                               //   in Localization the actions that touch a patch file
  "flags": ["environment_workaround"],         // vocab.flags (codebook Table 6)
  "own_phases": {"repair": 11} }               // the phases of its actions, counted (one phase
                                               //   since the lookup tables: nothing is absorbed)

// Attempt: app-source edits up to the run that judges them (the first decisive run after the
// edits, which the phase table puts in the validation span that follows); in action order, disjoint
{ "id": 1, "start": 23, "end": 33,             // first edit .. judging run (or last edit)
  "edits": [23, 26, 27], "judge": 33,          // judge is null for an attempt never run
  "outcome": "succeeded|failed|blocked|unchecked", "evidence": "test|build|none" }
```

**Outcome colours.** succeeded green ✓, failed red ✗, blocked dark slate ⊘ (the environment
stopped the check), unchecked light grey ○ (no check); the glyph always goes with the colour.
The phases are planning pink, localization blue, repair violet and validation amber, so no
phase shares a hue with an outcome. Only Validation shows its outcome as a verdict; the
viewer draws Localization and Repair as their files (at most five dots: grey = read or
searched, never edited; teal, copper, magenta, olive = edited, one colour per localization ->
repair cycle) and leaves Planning blank. The viewer shows subphases only as
the outcomes of their phase (a phase whose checks changed has an outcome history, ✗ → ✓); its
Trajectory view nests phases → categories (consecutive actions of one category) → steps. The same four outcomes are used in every
phase; what they mean in each phase is the codebook's Table 6, carried in `vocab.text.outcomes`.

## Overview file: `trajview-overview/3`

```jsonc
window.TRAJ_OVERVIEW = {
  "schema": "trajview-overview/3",
  "generated_by": "atif <parser_version>",
  "config": "original",
  "run": 1,                                    // the run summarised in "agents"
  "runs": [1, 2, 3],                           // the runs of the bug files (and of by_run)
  "agents": ["claude", "codex", "qwen"],
  "outcome_source": "a_apr_test_results",
  "models": {"claude": "claude-opus-5", "codex": "gpt-5.6-sol", "qwen": "qwen/qwen3.6-35b-a3b"},
  "vocab": { /* see "Vocabulary" */ },
  "bugs": [                                    // every bug of the dataset, sorted by numeric id
    { "bug": "8", "app": "de.koelle.christian.trickytripper",
      "page": true,                            // viewer/data/bugs/bug-8.js exists
      "by_run": {                              // every agent, straight from the outcome CSVs
        "claude": {"1": true, "2": true, "3": true}, "codex": {...}, "qwen": {"1": false, "2": true, "3": true} },
      "agents": {                              // agents whose overview run is converted
        "claude": {
          "id": "bug-8/claude/original/run1",
          "pass": true, "by_run": {"1": true, "2": true, "3": true},
          "model": "claude-opus-5",
          "n_actions": 40, "n_steps": 39,
          "strip":     [["localization", 1, 10], ["repair", 11, 30], ...],     // [phase, start, end] per span
          "sub_strip": [["succeeded", 1, 10, "localization", "target_file"], ...],  // [outcome, start, end,
                                                                                   //   phase, evidence] per subphase
          "stats":   { /* as in trajview/3 */ },
          "badges":  { /* as in trajview/3 */ },
          "metrics": { /* as in trajview/3 */ },
          "subphases": { "by_outcome": {"succeeded": 3, "unchecked": 2},
                         "by_phase":   {"repair": {"succeeded": 1}, ...} }   // phase -> outcome -> count
        } } } ] }
```

`strip` and `sub_strip` are in action order and each covers `1..n_actions` exactly once. No
action, thought or result text is in the overview.

## Vocabulary (`vocab`, the same in both files)

```jsonc
{ "categories": ["search", "read", "orient", "edit", "build", "test", "diff", "vcs", "plan",
                 "sub-agent", "other"],                       // the action table, in its order
  "category_family": {"search": "inspect", ...},             // inspect | modify | execute | coordinate | other
  "phases": ["planning", "localization", "repair", "validation"],
  "outcomes": ["succeeded", "failed", "blocked", "unchecked"],
  "phase_outcomes": {"planning": ["unchecked", "succeeded", "blocked"], ...},  // the outcomes each phase can have
  "evidence": ["test", "build", "target_file", "none"],
  "flags": ["test_modified", "environment_workaround", "repeated_failure", "repeated_reads", "manual_ui_check"],
  "verdicts": ["pass", "fail", "none"],
  "fail_kinds": ["test", "build", "env", "exit"],
  "file_roles": ["source", "test", "docs", "build", "other", "outside"],  // the target table
  "text": {                                                  // atif/lookup.py and atif/codebook.py
    "phases":     {"repair": {"doing": "…", "typical": "…", "where": "…"}, ...},      // the phase table by phase
    "categories": {"read": {"family": "inspect", "does": "…", "tools": "…"}, ...},   // tools: the action
                                                             //   table's two columns, word for word
    "outcomes":   {"repair": {"check": "…", "succeeded": "…", "failed": "…",
                              "blocked": "…", "unchecked": "…"}, ...},                  // Table 5 ("–" = cannot occur)
    "flags":      {"test_modified": "…", ...} },                                        // Table 6
  "tables": { /* the lookup tables in plain words (atif.rules.tables); see "Lookup tables" below */ },
  "lookup": { /* everything the built-in tables hold, for the Lookup tables page (atif.rules.contents):
                 "version" ("Final lookup table"), "version_date", "actions" [{type, family, does,
                 shell, native, tools: [{agent, names}], other_agents}], "shell_tools" [{agent,
                 names}], "ignored", "compound", "targets" [{target, name, files}],
                 "targets_swebench", "phases" [{n: 1-15, id: "L1".."L15", phase, categories,
                 target, position}], "general", "same" */ } }
```

The lists are written from `atif.phase`, `atif.taxonomy` and `atif.codebook` at export time,
so the viewer takes them from the data; it has short labels for the ones it knows and shows
unknown ones humanised.

## Invariants the viewer may rely on

`view.check_view` raises during export when one is broken (and `phase.check_hierarchy` before
it, on the phase result):

1. `actions[k].i == k + 1`, and `len(actions) == n_actions`.
2. Phase spans are contiguous and cover `1..n_actions` exactly once; each has at least one subphase.
3. Subphases inside a span are contiguous and cover that span exactly once; two neighbouring
   subphases of a span never have the same outcome.
4. Every action's `phase` is the phase of the span it is in.
5. Every span `phase`, subphase `outcome` (within `vocab.phase_outcomes` of its phase),
   `evidence` and `flag`, and every action `category` and `phase` is in `vocab`.
6. Attempts lie within `1..n_actions`, with `start <= end`; `anchor` is null or within `1..n_actions`.
7. Every source edit is in Repair; Repair and Validation occur only from the anchor on (`phase.check_hierarchy`).

## Viewer deep links (`bug.html`)

`bug.html#bug=<id>&t=<agent>-r<k>&i=<action>&v=trajectory|timeline|fingerprint&lvl=phases|categories|steps&fp=agents|runs&speed=1|2|4|8|16&details=0&play=1&theme=auto|light|dark`
— all but `bug` optional. `play=1` starts the playhead on open; `details=0` keeps the action details
closed while the cursor is set. Older links keep working: `lvl=purposes` opens `phases`,
`lvl=subphases` and `lvl=segments` open `categories`, `v=compare` opens the fingerprint.
`index.html#tab=stats&q=<search>&ag=<agent>&oc=pass|fail|mixed&sort=actions|failures` (links of the
earlier `ag=<agent>:pass|fail` and `f=allpass|disagree` filters still open). An upload's page is
`analyze.html#u=<id>`; the Lookup tables page takes `tables.html#draft=<row JSON>&back=<page>`
(`rules.html` redirects there, hash included).

## Lookup tables in the vocabulary

`vocab.rules` lists the built-in rows (`atif.rules.BUILTIN`: the phase table's rows L1–L15, its
general rule LG and the repeated-reads flag F1; `mandatory: true`, always `on`; F1 carries its
fixed `value`; L-rows carry `table: 4`, `n`, `phase`, `categories`, `target` and `position`) and
then every ready-made row
(`atif.rules.OPTIONAL`: O1–O4, `mandatory: false`, `on` when added, `kind`, `table`):
`{id, title, text, sentence, mandatory, on, table, value?, kind?}`, where `sentence` is `text`
with the number filled in. `vocab.tables` is the summary in plain words (`atif.rules.tables`:
`actions` [{type, does, examples}], `phases` [{id, n, phase, categories, target, position}],
`same`), and
`vocab.lookup` everything the built-in tables hold (`atif.rules.contents`, above), which the
Lookup tables page shows. Data built with `view --rules FILE` also carries `vocab.custom_rules`:
the file's own rows, each with its `sentence`. A table file is
`{"schema": "trajectiers-tables/1", "optional": [...], "custom": [...]}`; `trajectiers-rules/1`
and `/2` files are read too, without their version-3 grouping rules, and so are files written
for codebook version 4 (their values mapped: run_test → test, toolchain → build, understanding
→ planning; their ids P1–P11 and FW ignored). A row of `custom` is
`{id, kind, field, match, regex, value, enabled}`: kind `category` (a category), `phase`
(a phase or `follow`) or `file_role` (a target; field `path`), whose `field` is `target` (the command or
target), `tool`, `any` or `program` (the programs of a shell command, each with its first
argument; plain text matches a whole program name: `make`, `cargo test`); or kind `shell_tool`
(field `tool`): the tool named exactly in `match` runs shell commands, given in its argument
`value`, and its commands are read like Bash's.

## Single upload: `trajview-single/1`

The viewer gets this from `atif.upload.request` (an upload from the corpus page, and again on an
upload's page, `analyze.html#u=<id>`), run in the browser by Pyodide (`viewer/engine/`) or
answered by `POST /api/analyze` of `python3 -m atif.cli serve`; `analyze --json FILE` writes the
same object. A request with `"atif": true` also gets `"atif"`: the trajectory as ATIF, which the
viewer keeps beside the upload for the details panel's full texts and raw JSON.

```jsonc
{ "schema": "trajview-single/1", "generated_by": "atif <parser_version>",
  "trajectory": { /* one trajview/3 trajectory; id "upload/<agent>/<file name>", config
                     "upload", run 1, outcome {"pass": true|false|null, "by_run": {"1": ...}};
                     a SWE-bench run also has "project": "swebench" */ },
  "vocab": { /* as above, for the table file used */ },
  "rules": { "schema": "trajectiers-tables/1", "ruleset": {"optional": [...], "custom": [...]},
             "mandatory": [...], "optional": [ /* as vocab.rules; an added ready-made rule also
                                                 has matched / skipped */ ],
             "custom": [ { /* the row */ "table": 4, "sentence": "...", "matched": [3, 9],
                           "skipped": [{"i": 12, "why": "validation happens only from the first fix on"}] } ] },
  "source": { "name": "...", "format": "claude_code_stream_json|claude_agent_sdk_repr|codex_rollout_jsonl|qwen_stream_json|atif"
                               "|sweagent_traj|sweagent_chat|openhands_messages|openhands_events|mini_swe_agent",
              "agent": "claude", "model": "...", "bug": "18", "bug_inferred": true,
              "project": "android|swebench", "repo_root": "/testbed" /* swebench only, else null */,
              "steps": 40 },
  "warnings": ["..."],
  "unrecognized": {                       // steps no lookup table recognises (atif.diagnose)
    "n_actions": 9, "n_unrecognized": 8,  // all steps; those whose lookup fell through
    "n_follow": 8,                        // of them, those that took the phase of the step before
    "groups": [ { "kind": "tool|program", "key": "run_terminal_cmd",   // or "cargo test"
                  "n": 3, "n_follow": 3, "category": "other",  // what they count as now
                  "examples": [{"i": 4, "text": "./gradlew assembleDebug"}],   // <= 3
                  "suggest": { "row": { /* a row of the table file: kind category (field tool
                                           or program) or shell_tool */ },
                               "why": "its argument “command” holds command lines" } | null } ] } }
```

A SWE-bench run (`source.project = "swebench"`: a SWE-agent, OpenHands or mini-swe-agent log,
or an ATIF file whose task names the repository folder; `atif.project`) is analysed with Python
conventions and kept apart from the corpus: its `bug` is the SWE-bench instance id when the log
or the file name gives one (`astropy__astropy-12907`, never a corpus bug), it has no `app`, the
upload's page does not compare it with the corpus runs, and the Statistics tab counts it in its own
group per agent ("yours · SWE-bench").

The viewer keeps each such result in the browser (IndexedDB) with the file itself and its ATIF,
and analyses it again whenever the table rows change (or the engine's tables do: the cache key
carries their version).

## Corpus packs: `trajectiers-pack/1`

`view` also writes `viewer/data/atif/run<k>/bug-<id>.json.gz`: one bug's converted ATIF in one
run, gzipped with no timestamp (an unchanged corpus rewrites every file byte for byte).

```jsonc
{ "schema": "trajectiers-pack/1", "bug": "18", "config": "original", "run": 1,
  "trajectories": { "claude": { /* ATIF */ }, "codex": { ... }, "qwen": { ... } } }
```

When the user has added rows (`tables.html`, kept in `localStorage['tv-rules']`),
the viewer re-runs packs with `atif.upload.corpus_request` (in the browser worker, which fetches
and gunzips them, or `POST /api/corpus {"rules", "summary", "paths": [...]}` of `serve`, which
reads only paths of this form inside the viewer directory):

```jsonc
{ "schema": "trajectiers-corpus/1", "vocab": { /* for the rule set */ },
  "packs": [ { "bug": "18", "config": "original", "run": 1,
               "views": { "claude": { /* a trajview/3 trajectory, or with "summary": true its
                                          overview form; plus "rule_hits": {"O3": 2, "R1": 5} */ } } } ] }
```

The outcome (`outcome`, `pass`, `by_run`) and the app name do not depend on the rules; the viewer
keeps those of the exported files. Under the default rules a pack gives exactly the exported view
(`tests/test_rules.py`, `PackTests`). The run-1 summaries under a rule set are cached in IndexedDB.
