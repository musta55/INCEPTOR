# Phase taxonomy v3: phases with outcome subphases

**Status.** Implemented and tested, 2026-10-10; G7 changed on 2026-10-11 (§10). Not frozen yet: the constants are frozen
before test-set labelling starts (§9).

**Code.**
- `atif/phase.py`: phases, subphases, metrics and invariants;
- `atif/taxonomy.py`: `category`, `object_role`, `CATEGORIES`, `CATEGORY_FAMILY`;
- `atif/baselines.py`: baselines B1 and B3;
- `atif/codebook.py`: the codebook's lookup tables, quoted by the workbooks and the viewer;
- `atif/view.py` and `viewer/`: the viewer draws phases → subphases, attempts and the first
  fix ([View data contract.md](View%20data%20contract.md), `trajview/3`);
- `atif/agreement.py` and `score_ground_truth.py`: the evaluation of §9;
- `tests/test_phase.py`, `tests/test_view.py`, `tests/test_agreement.py`.

Run `python3 -m atif.cli phases 18 --runs 1` for an outline.

**Replaces:**
- §6–11 of `Technical report v2 (draft).md` (archived in `../Inspection/plans-and-reports-before-phase-taxonomy-2026-10-11.tar.gz`).

**Annotator-facing version.** [Annotation Codebook.docx](Annotation%20Codebook.docx) (v3.0)
holds the same lookup tables and grouping rules in plain words. It is the master for the
annotators; this file is the tool spec. Rule names correspond as follows:

| Codebook rule | Tool rule |
|---|---|
| G1 | the anchor |
| G2 | P1 table |
| G3 | T6 |
| G4 | K1 |
| G5 | P3 |
| G6 | T9 / K2 and T8 / K3 |
| G7 | A1 |

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

## 3. L1: action categories

`mid_level` (15 labels) is unchanged. `category` refines it, without changing it, through
`taxonomy.category`:

| Family | Categories | Refinement of `mid_level` |
|---|---|---|
| inspect | read_file, search_code, orient, vcs, diff, web | `diff` = `git diff`, `diff`, `cmp`. A git call that also reads or searches (Codex chains `sed -n '1,330p' F.java; git log`) takes the read/search label. `vcs` = the remaining git inspection (status, log, show, blame, ls-files, …) |
| modify | edit_file, shell_edit | `shell_edit` = an edit made by a plain shell command (`sed -i`, `perl -i`, a redirect or Python write into a project file, `git apply`, `patch`), and `git checkout/restore/stash/reset/clean/revert` (with `reverts = True`). `edit_file` = editor tools and Codex's `apply_patch` (replayable) |
| execute | build, run_test, device_ops, run_shell | none |
| configure | env_setup | none |
| coordinate | plan, delegate, wait_process | none |
| other | other | none |

In a pipeline, stages after the first (`git log | head`) are output filters. They are not
reads of a file.

**Admission rule.** A category exists only if some phase rule, outcome rule or RQ metric
separates it from every other category. Two categories that no rule and no metric separates
are merged. Every category belongs to one family, and the phase rules read only the category
or family, the file role and the verdict. So a new category never needs a new phase rule.

**Adding an agent** means adding rows to the tool registry (`taxonomy.TOOL_MAP`, plus the
argument keys in "Agent vocabularies"). A tool that is not listed becomes `other`. Two gates
apply per agent:
- at most 1% of actions are `other` (`atif.cli phases` prints the share);
- leave-one-agent-out agreement with the full registry is at least 95%.

## 4. Terms

| Term | Definition |
|---|---|
| file role (`taxonomy.object_role`) | `harness` (the benchmark's check script, `run_pipeline.sh`), `docs` (README, CHANGELOG, LICENSE, `*.md`, `*.txt`, …), then `file_role`: `toolchain` (`*.gradle`, `*.kts`, `*.properties`, wrapper files), `test` (`test/`, `androidTest/`, `reproducing_script_project/`), `source` (everything else) |
| source edit | an action whose `edit_role` is source: an edit tool, a shell write, or a command that writes source on its way to a run (`apply_patch … && ./gradlew test`) |
| anchor | the first source edit; if it lies inside an edit delegation, the delegating call. Actions before it are *pre-fix*, the rest *post-fix* |
| run result (`phase.run_result`) | of a build or test run, or of a poll of one: `pass` (a test run passed), `test_fail` (a test executed and failed), `build_fail` (compile error), `blocked` (environment or other failure), `build_pass` (a build passed: **weak**, it shows the code compiles, not that the bug is fixed) |
| decisive run | a run whose result is `pass`, `test_fail`, `build_fail` or `blocked` |
| execution stretch | consecutive execution, configure and wait actions, toolchain/harness/test edits, harness or log reads (R2 of `segment.enrich`; a `/dev/null` redirect is not a toolchain path), and interleaved orient/plan/git actions |
| attempt (K1) | a block of source edits checked by one run. Its judging run is the first decisive run at or after its first edit. A passing build judges it weakly when the agent edits again before any decisive run, so edit → build → edit is two attempts, and edit → build → test is one |

## 5. The five phases

| Phase | Definition | Where |
|---|---|---|
| **Understanding** | getting oriented before the work: the opening listing, planning, git status/log and reading of docs or build files, and pre-fix builds that check the project compiles | pre-fix only |
| **Localization** | finding the code to change: reading and searching source and test code (including `git blame`/`show` of code), and read-only delegation | anywhere |
| **Reproduction** | trying to observe the failure before the fix: a test or device run, with the builds, environment commands and test or toolchain edits that get it running | pre-fix only |
| **Repair** | changing application source and judging each change: every attempt, from its first edit to its judging run | post-fix |
| **Validation** | checking the patch outside an attempt: further builds and tests, writing regression tests, reading back the diff and one's own files, and cleanup | post-fix only |

## 6. Phase assignment: four deterministic passes

**P1. Table** (`phase.table`, `phase.resolve_markers`):

| # | Action | Pre-fix | Post-fix |
|---|---|---|---|
| T1 | source edit | Repair (the anchor) | Repair |
| T2 | run_test, device_ops | Reproduction | Validation |
| T3 | test-file edit | Reproduction | Validation |
| T4 | read/search of source or test code (or naming no path); vcs/orient touching code | Localization | Localization; **Validation** when it comes after the last source edit and touches only files the agent edited |
| T5 | diff | neutral | Validation |
| T6 | preparatory: build, env_setup, toolchain/harness edit, R2 probe or a look into a toolchain location (`~/.gradle`, `~/.m2`, the SDK, the JDK) | the phase of the next T2 run in its execution stretch; if none, Understanding | the same; if none, Validation |
| T7 | orient, plan, vcs, web, run_shell, other; read/search of docs, build files or paths outside the checkout; a pre-fix revert | neutral | neutral |
| T8 | wait_process (K3) | the phase of the run it polls; else of the action before it | the same (a run started pre-fix and polled post-fix → Validation) |
| T9 | delegate call + its spliced sub-agent actions, as one block (K2) | Repair if a sub-agent action edits source or the instruction asks for a change (`segment.delegated_edit`), else Localization | the same |

**P2. K1.** Every action from an attempt's first edit to its judging run is Repair, except
lookups (Localization or neutral), which keep their phase.

**P3. Neutral actions.** A neutral action takes the phase of the action before it. The
neutral actions that open the trajectory are Understanding. So planning calls interleaved
with searches (Codex calls `update_plan` 690 times in 150 runs) stay in Localization.

**P4. Smoothing** (`phase.smooth`), to a fixed point:
- **A1.** A span of `ABSORB_MAX` = 1 action between two spans of the same phase joins them.
  Two spans are never absorbed: a Repair span (every source edit stays in Repair) and a
  span holding a decisive run (its check would vanish from the subphases). Any span of two
  or more actions keeps its phase.

So a lookup of two or more actions inside an attempt is a Localization span between two
Repair spans, and the attempt's outcome appears in both (the subphases of both Repair spans
carry it).

**Constant.** It is named and swept in §11, and frozen before test-set labelling. Nothing
is fitted. Two constants were dropped:
- `K1_GAP_MAX` (from the plan): no value of it, from 0 to 5, changed any final phase.
- `REPAIR_GAP_MAX` = 10, with its rule A2 (the spans between two Repair spans joined Repair
  when they held at most 10 actions), was removed on 2026-10-11, and `ABSORB_MAX` went from
  3 to 1 (§10).

**Invariants** (`phase.check_hierarchy`, raised as errors):
- phase spans and subphases are contiguous and cover every action exactly once;
- every source edit is in Repair;
- Understanding and Reproduction occur only pre-fix;
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
| Understanding | a build of the untouched project (optional) | it builds | — | the build was stopped (any pre-fix build failure: not the agent's doing) | no build |
| Localization | reading a target file (a file the agent's own patch changes) | a target file was read | the agent changed files but read none of them in this span | — | the agent changed no app file |
| Reproduction | a test or device run before the fix | test fails (bug seen) | test passes | the run stopped before the test executed | no run gave a result |
| Repair | the attempt's judging run | test passes (test) or build passes (build) | test fails (test) or the change does not compile (build) | environment stopped the run | the change was never run |
| Validation | further runs on the patch | as Repair | as Repair | as Repair | nothing was run (for example, only the diff was read back) |

**Procedure** (`phase.subphases`):
1. List the span's **events**:
   - each attempt's range (Repair);
   - each decisive run;
   - a passing build (weak; not in Reproduction).
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

The context claim holds at subphase level. The same event, "the target test fails", is
`succeeded` in Reproduction and `failed` in Repair or Validation.

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
| understanding_actions … validation_actions | per phase; together they equal `tool_actions` (V2's names; V2's cleanup is part of validation, and reproduction is new) |
| env_actions | env_setup, R2 probes, toolchain edits and runs failed by the environment, wherever they are |
| n_attempts, n_failed_attempts, n_blocked_attempts | from K1, by attempt outcome |
| attempts_to_first_pass | the first attempt that succeeded with test evidence |
| repair_cycles | number of Repair spans |
| reentries | per phase: spans beyond the first |
| reproduced_before_fix | some Reproduction subphase succeeded |
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
- Round 1 is T01–T06: one pass and one fail per agent, 255 actions. The lookup tables and
  rules may change in this round.
- The codebook is then frozen (v3.1).
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
- **B2:** the P1 table alone, `phase.assign(..., keep_rules=False, smoothing=False)`,
  Graphectory-style per-action tags;
- **B3:** the old purposes, mapped to phases. Review becomes Validation, and Environment has
  no counterpart;
- optionally, an LLM condition.

**Ablations:** without K1, and without P4.

**Subphases** follow mechanically from L1, the verdicts and K1. One author checks every
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

## 11. Evidence (2026-10-11, with the single-action G7)

**Scope.** All 7,650 trajectories with an outcome (17 configs × 3 runs × 3 agents), parsed
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
