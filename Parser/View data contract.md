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
    "reproduced_before_fix": false,            // a Reproduction subphase succeeded
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
    "n_attempts": 1,                           // repair attempts (rule K1 / G4)
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
  "category": "run_test",          // L1 action category (vocab.categories, codebook Table 2)
  "phase": "reproduction",         // final phase: the phase span the action is in
  "own_phase": "localization",     // only when it differs from phase: the phase before smoothing
                                   //   (a single row between two stretches of one phase joins them, G7)
  "file_role": "source, test",     // roles of the files it touches (codebook Table 3), comma-
                                   //   separated; "outside" for paths outside the checkout; "" for none
  "target": "./run_pipeline.sh …", // <= 200 chars, whitespace-collapsed
  "verdict": "pass|fail|none",     // of a build / test run
  "fail_kind": "test|build|env|exit|null",
  "failed_raw": false,             // the log's own error flag on the tool result
  "reverts": true,                 // only when the action undoes changes (git checkout / restore / ...)
  "ts": "2026-…" | null,
  "thought": "…",                  // <= 300 chars: reasoning or narration of the issuing turn
                                   //   (parallel calls of one turn repeat it)
  "thought_source": "reasoning|narration|none",   // extra
  "result": "…",                   // <= 300 chars of the tool result
  "call_id": "toolu_…",
  "edits": ["app/src/…/Foo.java"], // extra, only on edits: files written (<= 6, each <= 200 chars)
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
  "flags": ["environment_workaround"],         // vocab.flags (codebook Table 7)
  "own_phases": {"repair": 8, "localization": 3} }   // own phase of its actions, counted

// Attempt: app-source edits up to the run that judges them (rule K1 / G4); in action order,
// disjoint
{ "id": 1, "start": 23, "end": 33,             // first edit .. judging run (or last edit)
  "edits": [23, 26, 27], "judge": 33,          // judge is null for an attempt never run
  "outcome": "succeeded|failed|blocked|unchecked", "evidence": "test|build|none" }
```

**Outcome colours.** succeeded green ✓, failed red ✗, blocked purple ⊘ (the environment
stopped the check), unchecked grey ○ (no check). The same four outcomes are used in every
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
{ "categories": ["read_file", "search_code", "orient", "vcs", "diff", "web", "edit_file", "shell_edit",
                 "build", "run_test", "device_ops", "run_shell", "env_setup", "plan", "delegate",
                 "wait_process", "other"],
  "category_family": {"read_file": "inspect", ...},          // inspect | modify | execute | configure | coordinate | other
  "phases": ["understanding", "localization", "reproduction", "repair", "validation"],
  "outcomes": ["succeeded", "failed", "blocked", "unchecked"],
  "phase_outcomes": {"understanding": ["unchecked", "succeeded", "blocked"], ...},  // the outcomes each phase can have
  "evidence": ["test", "build", "target_file", "none"],
  "flags": ["test_modified", "environment_workaround", "repeated_failure", "repeated_reads", "manual_ui_check"],
  "verdicts": ["pass", "fail", "none"],
  "fail_kinds": ["test", "build", "env", "exit"],
  "file_roles": ["source", "test", "toolchain", "harness", "docs", "outside"],
  "text": {                                                  // the codebook's words (atif/codebook.py)
    "phases":     {"repair": {"doing": "…", "typical": "…", "where": "…"}, ...},      // Table 1
    "categories": {"read_file": {"family": "inspect", "does": "…", "tools": "…"}, ...},  // Table 2
    "outcomes":   {"repair": {"check": "…", "succeeded": "…", "failed": "…",
                              "blocked": "…", "unchecked": "…"}, ...},                  // Table 6 ("–" = cannot occur)
    "flags":      {"test_modified": "…", ...} } }                                       // Table 7
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
   `evidence` and `flag`, and every action `category`, `phase` and `own_phase` is in `vocab`.
6. Attempts lie within `1..n_actions`, with `start <= end`; `anchor` is null or within `1..n_actions`.
7. Every source edit is in Repair; Understanding and Reproduction occur only before the anchor,
   Repair and Validation only from it on (`phase.check_hierarchy`).

## Viewer deep links (`bug.html`)

`bug.html#bug=<id>&t=<agent>-r<k>&i=<action>&v=trajectory|timeline|fingerprint&lvl=phases|subphases|steps&fp=agents|runs&speed=1|2|4|8|16&details=0&play=1&theme=auto|light|dark`
— all but `bug` optional. `play=1` starts the playhead on open; `details=0` keeps the action details
closed while the cursor is set. Older links keep working: `lvl=purposes` opens `phases`,
`lvl=segments` opens `subphases`, `v=compare` opens the fingerprint.
`index.html#tab=stats&q=<search>&f=allpass|anyfail|disagree|flaky&ag=<agent>:pass|fail&sort=actions|failures`.

## Rules in the vocabulary

`vocab.rules` lists the mandatory rules (`atif.rules.MANDATORY`, G1–G7 and F1, `mandatory: true`,
always `on`; G7 and F1 carry their fixed `value`) and then every optional rule
(`atif.rules.OPTIONAL`: O1–O4, `mandatory: false`, `on` when added, `kind`):
`{id, title, text, sentence, mandatory, on, value?, kind?}`, where `sentence` is `text` with the
number filled in. Data built with `view --rules FILE` also carries
`vocab.custom_rules`: the rule set's own rules, each with its `sentence`.

## Single upload: `trajview-single/1`

The Analyze page (`analyze.html`) gets this from `POST /api/analyze` of `python3 -m atif.cli
serve` (`atif.upload.analyze`); `analyze --json FILE` writes the same object.

```jsonc
{ "schema": "trajview-single/1", "generated_by": "atif <parser_version>",
  "trajectory": { /* one trajview/3 trajectory; id "upload/<agent>/<file name>", config
                     "upload", run 1, outcome {"pass": true|false|null, "by_run": {"1": ...}} */ },
  "vocab": { /* as above, for the rule set used */ },
  "rules": { "schema": "trajectiers-rules/2", "ruleset": {"optional": [...], "custom": [...]},
             "mandatory": [...], "optional": [ /* as vocab.rules; an added ready-made rule also
                                                 has matched / skipped */ ],
             "custom": [ { /* the rule */ "sentence": "...", "matched": [3, 9],
                           "skipped": [{"i": 12, "why": "reproduction happens only before the first fix"}] } ] },
  "source": { "name": "...", "format": "claude_code_stream_json|claude_agent_sdk_repr|codex_rollout_jsonl|qwen_stream_json|atif",
              "agent": "claude", "model": "...", "bug": "18", "bug_inferred": true, "steps": 40 },
  "warnings": ["..."] }
```
