# Phase taxonomy v5: phases from the Final lookup tables, with outcome subphases

**Status.** Implemented and tested. Version 3 (2026-10-10) assigned phases with a table and
grouping rules; version 4 (2026-10-14) with the codebook's lookup tables alone; version 5
(2026-10-17) with the **Final lookup tables** (§3, §6): the tab "Final lookup table" of
`Ground Truth/annotation_workbook.xlsx`, drafted by two authors on the pilot (T01, T03, T05) and
expanded on the 339 development trajectories, with two development steps for every entry in
the tab "Lookup justification". The tables are frozen before evaluation-set labelling (§9).

**Code.**
- `atif/lookup.py`: the three tables word for word (action, target, phase) and the code that
  applies them (`classify`, `target`, `rows`);
- `atif/phase.py`: the anchor, the phase table (`table`, `follow`), subphases, metrics and
  invariants;
- `atif/taxonomy.py`: the finer action *kinds* (`kind`, `KINDS`) that the verdicts, outcomes,
  flags and baselines read;
- `atif/codebook.py`: codebook version 4 in its words: Tables 1–4 (now baseline B5), Table 5
  (outcomes) and Table 6 (flags), which still apply;
- `atif/rules.py`: the viewer's Lookup tables page: the built-in rows (L1–L15, the general
  rule LG, F1), the ready-made rows and the user's own rows (`trajectiers-tables/1`);
- `atif/baselines.py`: baselines B1, B3, B4 (the grouping rules of version 3) and B5 (Table 4
  of version 4);
- `atif/view.py` and `viewer/`: the viewer draws phases → subphases, attempts, the first fix,
  each action's category with the table entry that gave it, and its phase-table row
  ([View data contract.md](View%20data%20contract.md), `trajview/3`);
- `atif/agreement.py` and `score_ground_truth.py`: the evaluation of §9;
- `tests/test_phase.py`, `tests/test_rules.py`, `tests/test_view.py`, `tests/test_agreement.py`.

Run `python3 -m atif.cli phases 18 --runs 1` for an outline.

**Replaces:**
- §6–11 of `Technical report v2 (draft).md` (archived in `../Inspection/plans-and-reports-before-phase-taxonomy-2026-10-11.tar.gz`).

**Annotator-facing version.** The workbook tab "Final lookup table" is the master; this file
is the tool spec, and `atif/lookup.py` holds the tables word for word. [Annotation
Codebook.docx](Annotation%20Codebook.docx) (v4.0) still describes the tables of version 4.

`atif/segment.py` (segments and purposes) is kept unchanged as baseline B3.

**Merges.** This scheme merges our earlier scheme with the "Action Classification" and
"Phase Assignment" sections of the V2 analysis plan (`Writing/APR Trajectory Analysis V2.md`).
§1 lists what was taken from V2 and what was not.

---

## 1. Why the change

- **Two labels for one judgement.** The segment level had its own vocabulary of eight goals.
  The purpose level had seven labels that almost matched them: orient/orientation,
  locate/localization, attempt/repair, and so on. Raters were asked to make nearly the same
  judgement twice.
- **What v3 keeps.** One judgement for humans, the **phase**, and one computed refinement,
  the **subphase**.
  - A subphase has no goal label. It inherits its phase and carries only an **outcome**.
  - So the 25 old segment types collapse into phase × outcome.
- **Why a unit below the phase is still needed.** An outcome stored only on the phase would
  lose sequences such as "blocked twice, then passed", or "searched the wrong files, then
  found the right one".

**Taken from V2:**
- the `shell_edit` and `diff` categories;
- excluding polls from effort counts;
- classifying reads by file kind: docs and build files go to Understanding, code goes to
  Localization;
- a pre-fix build without a test counts as Understanding;
- the phase-count metric names.

**Not taken from V2:**
- **The single split at the first edit.** Phases recur. On the 450 `original` runs, V2's
  rule labels 1,949 actions as validation that are really inside fix loops, and 493 that are
  re-localization (§11).
- **The first edit of any file as the anchor.** We anchor on the first edit of application
  source, because test and toolchain edits can come before the fix.
- **Actions with no phase.** In V2, plan, sub-agent and other actions get no phase. Here
  every action gets exactly one, so the phase counts add up to the action total.

**Dropped from our earlier scheme:**
- the Environment purpose. Environment work now goes with the run it enables, and shows up
  as the outcome `blocked`, the flag `environment_workaround` and the count `env_actions`;
- Review, which is folded into Validation.

Orientation is renamed Understanding.

## 2. Levels

| Level | Unit | Vocabulary | Assigned by | Human role |
|---|---|---|---|---|
| L0 action | one tool call | tool + arguments + result | ATIF | none |
| L1 category | one tool call | 17 categories in 6 families (§3) | tool registry + shell program parsing | raters correct wrong categories (`category_fix`) |
| **Phase** | a contiguous span; phases may recur | 5 phases (§5) | passes P1–P4 (§6) | **two blind raters** |
| **Subphase** | a contiguous stretch of one phase span with one outcome | 4 outcomes + evidence (§7) | outcome runs (§7) | audited by one author against the verdicts |

The nesting is strict. Every action is in exactly one subphase, and every subphase is in
exactly one phase span. Every action also keeps `own_phase`, its phase before smoothing (P4),
so a lookup inside a fix loop stays visible as *nested*.

## 3. L1: action categories (the action table)

Every tool call gets one of 11 categories from the action table (`lookup.classify`): search,
read, orient, edit, build, test, diff, vcs, plan, sub-agent, other. A **native tool** gives its
category directly (Claude's Read, Edit, Write, Agent; Codex's update_plan, write_stdin; Qwen's
read_file, grep_search, glob, edit, write_file, agent and its coordination tools). An edit tool
on a file outside the repository is other. A **shell runner** (Bash, exec_command,
run_shell_command) has its command line split into simple commands at `;`, `&&`, `||`, `|`,
`&` and line breaks (heredoc bodies, `bash -c '…'` and wrappers such as `timeout` are looked
through). Each simple command is looked up in the Shell Commands column, and the programs of
the "(ignored)" row are skipped (`cd`, `echo`, a program after a pipe, `mkdir`, writes to
`/tmp`, …). The line takes the highest category on it: edit > build > test > search > read >
diff > vcs > orient > other. A line of ignored programs only is other.

The table's own entries (`lookup.ACTION_TABLE`) decide; a few distinctions they make:
`./gradlew` with a test, check, lint or checkstyle task is test, with `tasks` or `--version`
orient, with any other task build; `javac` alone is build, `javac` with `java`, `java <class>`,
`jshell`, `xmllint`, `adb`, `patch --dry-run` and `git apply --check` are test; `git status`
is diff; `git checkout/restore/reset/stash` (not `stash list`), `cp`/`mv` onto a repository
file, `rm` of one, and a Python script that writes one are edit; `curl`, `sleep`, `ps` and any
other Python script are other.

Each action keeps the entry that decided it (`lookup_item`, the viewer's "Why <category>").

**Kinds.** The taxonomy's finer labels (`mid_level`, 15, and `kind`, 17: read_file,
search_code, …, run_test, device_ops, wait_process) stay underneath. The verdict parser, the
polls of background runs, the attempts' judging runs, the outcomes, the flags and the baselines
read them, because they say what a run reported (a test run, a build, a poll of either). The
category decides only the phase. A user's category row sets both.

**Beyond the table** (for logs the corpus does not have). The shell tools of other agents
(OpenHands' `execute_bash`, mini-swe-agent's `bash`) are shell runners. A tool the table does
not name, and that the corpus agents never called, gets the category of what the taxonomy says
it does (Claude Code's `Grep`: search; OpenHands' `str_replace_editor`: edit or read). The four
tools the corpus agents called that the table leaves out (`update_goal`, `get_goal`,
`record_artifact`, a made-up `run_shell`) are other, the table's "any other tool". In a
SWE-bench project, a program the Android table sends to other takes the taxonomy's kind
(`pytest`, `python reproduce.py`: test).

**Gate.** At most 1% of each agent's actions may fall to the catch-all entries "any other
tool" or "any other program" (`tests/test_phase.py`); other itself is a category of the table.

## 4. Terms

| Term | Definition |
|---|---|
| target (`lookup.target`) | the target table, checked in this order: outside the repository (`/tmp`, `~/.gradle`, the SDK, the JDK); other repository file (patches, screenshots, logs, `build/` outputs, the agent's own hidden folders, a program at the repository root); docs (README, AGENTS.md, `*.md`, `*.txt` outside `src/`); build file (`*.gradle`, `*.kts`, `*.properties`, `gradlew`, proguard rules); test file (`src/test/`, `src/androidTest/`, `*Test.java`); source file (everything under a module's `src/` or `res/`, `AndroidManifest.xml`, also under a wrong root) |
| repository | the folder the run was started in (the log's `extra.cwd`, `project.Project.checkout`); a log that records none: any `bug-<id>` folder outside `/tmp`; a SWE-bench project: its repository roots |
| an action's targets | the files of the table entry that decided its category (or the native tool's file); else every path it names |
| source edit | an action of category edit with a source-file target (an edit whose file is unknown counts as source) |
| anchor | the first source edit, the first fix. Actions before it are *pre-fix*, the rest *post-fix* |
| run result (`phase.run_result`) | of a build or test run, or of a poll of one: `pass` (a test run passed), `test_fail` (a test executed and failed), `build_fail` (compile error), `blocked` (environment or other failure), `build_pass` (a build passed: **weak**, it shows the code compiles, not that the bug is fixed) |
| decisive run | a run whose result is `pass`, `test_fail`, `build_fail` or `blocked` |
| attempt (K1) | a block of source edits checked by one run. Its judging run is the first decisive run at or after its first edit. A passing build judges it weakly when the agent edits again before any decisive run, so edit → build → edit is two attempts, and edit → build → test is one |

## 5. The five phases

| Phase | Definition | Where |
|---|---|---|
| **Planning** | getting ready: a plan; the opening steps (ls, pwd, git status); reading only docs, or building the untouched project, before the first fix. Codebook versions 3 and 4 called it Understanding | pre-fix, and a plan anywhere |
| **Localization** | finding the code to change: searching and reading code (and a sub-agent), running tests or writing a test before the first fix; after it, reading a source file the agent has not changed when it changes code again before the next build, test or diff | anywhere |
| **Repair** | changing the app's code: every edit of a source file | post-fix |
| **Validation** | checking the patch: every build, test, diff and git command after the first fix; re-reading changed or non-source files; reading unchanged code before a build, test or diff; editing a non-source file | post-fix only |

## 6. Phase assignment: the phase table

**The phase table** (`lookup.rows`, `phase.table`). Each action gets the phase of the **first**
row that matches its category, its targets and its position:

| Row | Phase | Category | Target file | Position / rules |
|---|---|---|---|---|
| L1 | Planning | plan | any | anywhere |
| L2 | Planning | orient, other, vcs, diff | any | at the start of the trajectory (the first action) |
| L3 | Planning | read, search | docs only | before the first fix |
| L4 | Planning | build | any | before the first fix |
| L5 | Localization | search, read, sub-agent | any (not docs only) | before the first fix |
| L6 | Localization | test | any | before the first fix |
| L7 | Localization | edit | test file | before the first fix |
| L8 | Repair | edit | source file | anywhere (the first one is the anchor) |
| L9 | Localization | search, read | source file the agent has not changed | after the first fix, when the next source edit comes before the next build, test or diff |
| L10 | Validation | search, read | source file the agent has not changed | after the first fix, when a build, test or diff (or the end) comes before the next source edit |
| L11 | Validation | search, read | a file the agent has changed, or not a source file | after the first fix |
| L12 | Validation | build, test, diff, vcs | any | after the first fix |
| L13 | Validation | edit | a repository file that is not a source file | after the first fix |
| L14 | previous step's phase | orient, other | any | after the start |
| L15 | previous step's phase | vcs, diff | any | before the first fix, after the start |

**General rule** (LG). A step no row matches takes the phase of the previous step (an edit of
a build file or docs before the first fix; a sub-agent after it). The very first step, with no
previous step, is Planning.

Rows 9 and 10 look ahead to the next decisive step; every other row reads only the action and
what came before it. On the 339 development trajectories the split agrees with the purpose the
agent's thought states on 90% of 118 hand-labelled reads.

**Nothing else.** No rule moves an action after the table: there is no attempt rule (the build
or test right after an edit is Validation, and it still decides the attempt's outcome, §7), no
delegation block (a sub-agent's spliced actions are looked up like any other, so its first
source edit is the first fix), no wait rule (a poll is other and takes the previous step's
phase, normally its run's) and no smoothing (a single action can form a span). The grouping
rules of version 3 are baseline B4 (`baselines.grouping_rules`) and the phase lookup of version
4 (P1–P11 and follow) is baseline B5 (`baselines.table_v4`), which reproduces the version-4
engine on all 10,796 actions of the pilot, development and evaluation sets.

**User rows** (`atif/rules.py`). The viewer's Lookup tables page adds rows to the three tables:
a category row counts matching steps as a category (and reads their runs as that category's),
a target row gives matching paths a target, and a phase row replaces the table's value for
matching steps (or gives them the previous step's phase). A row never breaks an invariant
(`phase.override_problem`): such a match is reported as skipped. Files written for version 4
are read with their values mapped (run_test → test, toolchain → build, understanding →
planning); their Table 4 ids are ignored.

**Invariants** (`phase.check_hierarchy`, raised as errors):
- phase spans and subphases are contiguous and cover every action exactly once;
- every source edit is in Repair;
- Planning occurs anywhere: a plan is Planning wherever it comes. (Reproduction, pre-fix only,
  was dropped on 2026-10-19: rows L6 and L7 are Localization);
- Repair and Validation occur only post-fix;
- adjacent subphases of a span never share an outcome;
- every phase, outcome and flag is in the vocabulary.

## 7. Subphases: one per outcome run

**One question per stretch, the same in every phase:** did the check in this stretch show
that the phase's goal was reached? There are four answers (`phase.OUTCOMES`):

| Outcome | Meaning |
|---|---|
| succeeded | the check says yes |
| failed | the check says no |
| blocked | a check was attempted, but the environment stopped it, so it says nothing about the agent's work |
| unchecked | no check was attempted |

The **evidence** attribute records the strongest check behind an outcome: `test`, `build`,
`target_file` or `none`. A passing build makes a patch *compilable*, a passing test makes it
*plausible*: the standard APR levels.

| Phase | The check | succeeded | failed | blocked | unchecked |
|---|---|---|---|---|---|
| Planning | a build of the untouched project (optional) | it builds | — | the build was stopped (any pre-fix build failure: not the agent's doing) | no build |
| Localization | reading a target file (a file the agent's own patch changes) | a target file was read | the agent changed files but read none of them in this span | — | the agent changed no app file |
| Repair | the attempt's judging run | test passes (test) or build passes (build) | test fails (test) or the change does not compile (build) | environment stopped the run | the change was never run |
| Validation | further runs on the patch | as Repair | as Repair | as Repair | nothing was run (for example, only the diff was read back) |

**Procedure** (`phase.subphases`):
1. List the span's **events**:
   - each attempt's range (Repair);
   - each decisive run;
   - a passing build (weak).
2. Give each event its outcome and evidence.
3. Every other action belongs to the next event. Actions after the last event join it. A
   passing build decides only when no other event follows it in the span.
4. Merge consecutive events with the same outcome into one subphase (run-length encoding).
   Keep the counts `n_events` and `n_attempts`; the evidence is the strongest of the merged
   events.

Localization has one subphase per span. The search length is the metric
`actions_to_first_found`.

**Target files** for Localization are the source files of the agent's own patch. This corpus
has no developer-fix file list, so Localization "succeeded" means that the agent read the code
it went on to change. That measures focus, not whether the agent found the developer's fix
location. The `targets` argument can override the set for a corpus that has such a list;
`metrics.target_source` records which set was used.

The context claim held at subphase level while Reproduction existed (until 2026-10-19): the
same event, "the target test fails", was `succeeded` in Reproduction and is `failed` in Repair
or Validation.

**Flags** (`phase.FLAGS`). Each flag is a behaviour, not a result, and each serves a research
question:

| Flag | Meaning | Serves |
|---|---|---|
| test_modified | edits test code or the harness script | testing behaviour; validity (was the bug-revealing test altered?) |
| environment_workaround | edits build files, or, next to a failed run, changes environment settings (env_setup) or re-runs the same command with a changed environment (another `JAVA_HOME`). A changed re-run is detected against the previous decisive run in any phase | environment trouble vs repair mistakes (RQ-T4) |
| repeated_failure | a decisive run repeats the previous one (in any phase): both failed, same full command, same error signature, nothing edited or set up in between (K4) | unproductive loops (RQ2) |
| repeated_reads | one file read three or more times in the subphase | inefficiency (RQ2) |
| manual_ui_check | drives the app on a device (`adb shell input`, `screencap`, `uiautomator`): a check with no automatic verdict | how agents validate UI bugs |

Behaviours too common to point at a stretch are per-run counts instead (§8): `tool_errors`
(4,801 subphases under the old flag), `self_reviews` (8,322) and `reverts` (116). `nested`
is a structural property, which the subphase records as `own_phases`.

## 8. Metrics per trajectory (`phase.metrics`)

Polls are excluded from every count.

| Metric | Definition |
|---|---|
| tool_actions | actions without polls |
| planning_actions … validation_actions | per phase; together they equal `tool_actions` (V2's names; V2's cleanup is part of validation, and reproduction is new) |
| env_actions | env_setup, R2 probes, toolchain edits and runs failed by the environment, wherever they are |
| n_attempts, n_failed_attempts, n_blocked_attempts | from K1, by attempt outcome |
| attempts_to_first_pass | the first attempt that succeeded with test evidence |
| repair_cycles | number of Repair spans |
| reentries | per phase: spans beyond the first |
| reproduced_before_fix | always false since Reproduction was dropped (2026-10-19) |
| actions_to_first_found | tool actions before the first touch of a target file (RQ-T2) |
| blocked_subphases, `<flag>_subphases` | counts |
| tool_errors, self_reviews, reverts | per-run counts of failed lookups or edits (no-match searches excluded), diffs or reads of own files after the last fix, and reverts |
| final_repair_outcome / _evidence, final_validation_outcome / _evidence | the last subphase of that phase |

## 9. Evaluation

**Sample** (`make_ground_truth.py`; codebook §3). The frame is `original`, run 1: 150
trajectories. Each agent gets 5, split by its APR pass rate (largest remainder, ties to
fail):

| Agent | Passed | Sample |
|---|---|---|
| Claude | 44 / 50 | 4 pass + 1 fail |
| Codex | 42 / 50 | 4 pass + 1 fail |
| Qwen | 25 / 50 | 2 pass + 3 fail |

The draw uses seed 20261010, never gives one agent two bugs of the same app or repeats a bug,
and excludes bug 18 (the worked example). It yields 15 trajectories and 630 actions.

**Rounds.**
- Round 1 is T01–T06: one pass and one fail per agent, 255 actions. The lookup tables may
  change in this round (version 4 is such a change, 2026-10-14).
- The codebook is then frozen (v4.1).
- Round 2 is T07–T15: 375 actions. The tool is scored on round 2 only, so the score is not
  circular.

**What the raters label.**
- **The phase:** they write it on the first row of each stretch.
- **`category_fix`:** only where the L1 category is wrong. Its rate over the 630 rows is the
  accuracy of the registry, which replaces the separate L1 audit.
- **Codebook-change proposals:** logged in the workbook.

**Measures.** Per-action κ (human–human κ is the ceiling), phase boundary F1 at tolerance 0
and ±1, WindowDiff, and the edit distance between phase sequences (`atif/agreement.py`).
- κ and accuracy are pooled over all rows of the set. A baseline's unlabelled row counts as a
  disagreement, and its coverage is reported.
- Boundaries are matched one-to-one within the tolerance; precision, recall and F1 come from
  pooled counts.
- WindowDiff uses k = half the mean reference stretch length, averaged over trajectories.
- The sequence distance is the Levenshtein distance between the two phase sequences (the
  order of the stretches, ignoring their lengths), divided by the longer sequence and averaged
  over trajectories; the share of identical sequences is reported beside it.
- 95% intervals come from a bootstrap over trajectories (2,000 resamples, seed 20261010).

`python3 score_ground_truth.py --annotator A1.xlsx --annotator A2.xlsx [--reference R.xlsx]`
computes all of them and writes `data/ground_truth/`.

**Baselines** (`atif/baselines.py`):
- **B1:** V2's first-edit split;
- **B3:** the old purposes, mapped to phases. Review becomes Validation, and Environment has
  no counterpart;
- **B4:** the grouping rules of codebook version 3 (`baselines.grouping_rules`): the
  version-3 table, then preparation, attempts, delegation blocks, polls, neutral actions and
  single-action smoothing. B2 (version 3's table alone) and the ablations without K1 and
  without P4 are gone: the tool itself is now a table, and B4 holds every version-3 rule;
- optionally, an LLM condition.

**Subphases** follow mechanically from L1, the verdicts and the attempts. One author checks every
subphase of the 15 trajectories against the verdict columns and reports precision per
outcome.

## 10. Changes from the approved plan, made during implementation

Each change came from reading real trajectories.

| Change | Reason |
|---|---|
| T7 actions are neutral everywhere, not "Understanding pre-fix" | Codex interleaves `update_plan` with searches, and A1 then folded 411 lookups into Understanding |
| A git call that also reads or searches is labelled by the read/search, and vcs/orient touching code locates | Codex chains source reads with `git log`, and the old priority labelled them git inspection |
| Understanding can have outcomes (succeeded / blocked by a build check) | a pre-fix build check that fails for environment reasons should not read as if nothing happened |
| `K1_GAP_MAX` dropped | no effect on any final phase, from 0 to 5 |
| Repetition (now the flag `repeated_failure`) is checked against the previous decisive run in any phase | a failed judging run re-run unchanged lands in Validation, and a per-span check missed it |
| A passing build closes an attempt when the agent edits again | otherwise edit → build → edit → build counted as one attempt |
| A `/dev/null` redirect is not a toolchain probe; a no-match search is not a tool error | both were false positives |
| 15 outcomes and 7 classes became 4 outcomes plus evidence; 10 flags became 5 | the old list mixed four questions: result, evidence strength, cause and behaviour. `stuck` and `searching` were behaviours, and `builds` / `breaks_build` were evidence levels |
| A look into `~/.gradle`, `~/.m2` or the SDK counts as preparation (T6) even when R2 misses it | the codebook's worked example (bug-18 Claude, row 16) showed rule G3 and the tool disagreeing |
| 2026-10-11, after the round-1 manual check: A1 absorbs only a single action (`ABSORB_MAX` 3 → 1), and A2 (repair gaps up to 10 actions join Repair) is removed; codebook G7 says the same | A2 hid validation and localization work inside Repair (re-reading the diff and checking git status between two attempts); 7.3% of actions change phase, and phase spans per trajectory go from 3.84 to 5.18 (450 trajectories) |

## 11. Evidence

### 11.0b Version 5 (2026-10-17, the Final lookup tables)

- **Fidelity.** The engine reproduces the reference implementation of the tables (the scripts
  that built the tab, run on the workbook rows) on all 10,425 pilot and development actions:
  category, phase-table row and phase.
- **Pilot.** 73/73 Final Phase labels and 73/73 categories of T01, T03, T05 (the tables were
  built on them, so this is a consistency check, not an accuracy estimate). On the same
  actions B5 (version 4) gets 62/73 and B4 (version 3) 46/73.
- **Annotator 1's labels** (630 actions of T01–T15, made under codebook version 4 before the
  tables): the Final tables agree on 547 (86.8%), B5 on 576 (91.4%). The differences are the
  tables' deliberate choices: a plan is Planning anywhere (13), reads of changed or non-source
  files and git commands after the first fix are Validation (23), searches before the fix are
  Localization (8). Only the held-out evaluation set (E01–E12) can show which agrees better
  with labels made under the Final tables.
- **Change against version 4** (pilot, development and evaluation sets, 10,796 actions): 16.5%
  of actions change phase, mostly localization → validation (922) and between localization and
  planning (432). Phase shares: Planning 4.0 → 5.7%, Localization 48.7 → 40.5%, Repair 15.0 →
  13.0%, Validation 32.1 → 40.5%. Mean phase spans per trajectory: Claude 7.5 → 6.7, Qwen 8.2 →
  5.1, Codex 4.9 → 9.3, of which 4.5 are Planning spans (Codex calls `update_plan` between
  steps, and row 1 makes each call Planning).

### 11.0 Version 4 (2026-10-14, lookup tables; `original`, runs 1–3, 450 trajectories)

| Agent | Understanding | Localization | Reproduction | Repair | Validation | Spans per trajectory |
|---|---|---|---|---|---|---|
| Claude | 0.9% | 56.6% | 0.4% | 19.3% | 22.8% | 6.97 |
| Codex | 17.8% | 45.0% | 0.0% | 10.0% | 27.1% | 4.77 |
| Qwen | 0.8% | 52.1% | 0.0% | 12.2% | 34.9% | 7.91 |
| All | 4.6% | 52.4% | 0.2% | 14.7% | 28.1% | 6.55 (B4: 5.18) |

Shares of tool actions, polls excluded. The tables give the same phase as the version-3 grouping
rules (B4) on 80.1% of actions; most of the difference is the build or test right after an edit
(Repair → Validation, 458 run-1 actions). The categories, verdicts and the anchor are unchanged.
Against annotator 1's round-1 labels (T01–T05, 213 actions, labelled with version 3): the tables
93.9% (κ 0.91), B4 90.1% (κ 0.85). The subsections below are the version-3 evidence.

**Version 3 (2026-10-11, grouping rules with the single-action G7).** **Scope.** All 7,650 trajectories with an outcome (17 configs × 3 runs × 3 agents), parsed
from the raw logs:
- **0 invariant violations.** 3 logs contain no tool call.
- **Registry coverage:** `other` is 0.00% of actions for Claude, 0.31% for Codex and 0.11%
  for Qwen.
- **Tests:** `tests/test_phase.py`, `tests/test_view.py` and `tests/test_agreement.py`, with
  the rest of the suite, pass.

### 11.1 Where the effort goes (share of tool actions, polls excluded)

| Agent | Understanding | Localization | Reproduction | Repair | Validation |
|---|---|---|---|---|---|
| Claude | 5.1% | 56.6% | 2.4% | 24.6% | 11.3% |
| Codex | 20.5% | 40.9% | 0.6% | 20.9% | 17.2% |
| Qwen | 2.5% | 57.3% | 0.0% | 16.5% | 23.7% |

Codex's Understanding share is real: it opens with `update_plan` and a call that looks for
AGENTS.md and checks git status. With the old G7 (A1 up to 3 actions, A2) Repair held more:
28.5% for Claude, 22.3% for Codex and 22.0% for Qwen, the difference being mostly lookups
inside attempts.

### 11.2 Subphase outcomes

| Phase | Spans | >1 subphase | succeeded | failed | blocked | unchecked |
|---|---|---|---|---|---|---|
| Understanding | 4,964 | 0.7% | 90 | — | 229 | 4,680 |
| Localization | 14,104 | — | 11,808 | 1,929 | — | 367 |
| Reproduction | 391 | 3.3% | 36 | 34 | 66 | 272 |
| Repair | 10,226 | 2.0% | 5,520 | 554 | 2,892 | 1,467 |
| Validation | 8,459 | 7.0% | 1,457 | 417 | 1,489 | 5,814 |

- **Total:** 39,121 subphases. Medians per trajectory: 4 phase spans and 4 subphases.
- **Repair evidence:** succeeded (build) 5,189 against succeeded (test) 331. The agents
  mostly confirm a fix by compiling it. Repair spans count an attempt split by a lookup
  twice, so these are span counts, not attempt counts.
- **Flags:** repeated_reads 2,114, environment_workaround 1,013, test_modified 490,
  manual_ui_check 299, repeated_failure 86.
- **Mean per run** (attempts do not depend on G7):

  | Agent | Attempts | Failed attempts | Blocked attempts |
  |---|---|---|---|
  | Claude | 1.14 | 0.04 | 0.16 |
  | Codex | 1.06 | 0.06 | 0.33 |
  | Qwen | 1.26 | 0.07 | 0.48 |

### 11.3 Baselines (`original`, runs 1–3, 450 trajectories)

Agreement is per action, without polls, and counts only actions the baseline labels.

| Baseline | Coverage | Agreement | κ | Boundary F1 (tol 0) | Main disagreement (baseline → ours) |
|---|---|---|---|---|---|
| B1 V2 first-edit split | 92.6% | 72.8% | 0.59 | 0.39 | 1,242 actions V2 calls validation are re-localization; 1,174 are in fix loops (Repair) |
| B2 P1 table only | 100% | 88.1% | 0.82 | 0.64 | what K1 and A1 add: 1,029 validation→repair, 243 localization→repair |
| B3 old purposes | 91.3% | 77.0% | 0.64 | 0.48 | old "review" was mostly lookups (858→localization); 394 opening lookups of AGENTS.md/docs → understanding; 390 old repair → localization |

These are agreements between methods, not accuracy. Accuracy needs the human labels (RQ1),
scored with `score_ground_truth.py` (§9).

### 11.4 Sensitivity (450 trajectories)

Each cell gives the share of actions whose phase changes against the default, then the
phase spans per trajectory. The default (`ABSORB_MAX` = 1) gives 5.18 spans per trajectory.

| Constant | Values |
|---|---|
| ABSORB_MAX | 0: 3.4% / 7.18 · **1: — / 5.18** · 2: 2.8% / 4.50 · 3: 4.7% / 4.21 · 4: 6.0% / 4.07 · 5: 7.3% / 3.95 |

The old setting (3, with A2) moved 7.3% of actions away from the current one.

### 11.5 Subphase outcome vs harness outcome (all 7,650)

Harness pass rate, by the outcome and evidence of the run's last Repair subphase:

| Last Repair subphase | Harness pass |
|---|---|
| succeeded (build) | 77% (3,111 / 4,032) |
| succeeded (test) | 75% (187 / 251) |
| blocked (build) | 65% (957 / 1,465) |
| failed (build) | 65% (33 / 51) |
| failed (test) | 59% (80 / 136) |
| unchecked | 58% (619 / 1,076) |
| blocked (test) | 57% (165 / 292) |
| no Repair at all | 3% (12 / 344) |

The agent's own passing tests do not predict the harness better than a compiling build. That
is a finding for RQ3, and it is why the CLAIM✗ badge matters.

## 12. Known limits

1. **Reproduction is rare in this corpus.** Agents almost never run a test before editing.
   The phase stays in the vocabulary, but its counts are small.
2. **Most checks are builds, or are blocked.** The agents mostly cannot run the
   instrumentation tests (environment), so Repair outcomes are mostly succeeded (build) or
   blocked. This reflects the corpus, not the taxonomy.
3. **The target set** is the agent's own patch, because this corpus has no developer-fix file
   list. So Localization outcomes measure focus, not correct localization.
4. **Mixed shell calls** (`ls && find AGENTS.md && rg Foo`) get one label from their files.
   Calls like this are a small share of actions, but they exist.
5. **Verdict markers** are corpus-specific (`run_pipeline.sh`, Gradle, JUnit). Subphase
   outcomes are only as accurate as the verdicts, which is why they are audited.
