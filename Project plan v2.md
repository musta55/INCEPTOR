# Project plan v2 — validated hierarchical segmentation of APR agent trajectories

**Status:** 2026-09-30. Replaces the methodology, RQs and milestones of the August proposal
([CSCI775 proposal](CSCI775-Mustahid_Hasan-Fall_2026_Proposal.pdf)).

**What stays from the proposal:**
- the problem: trajectories are long, heterogeneous and costly to read;
- the multi-granularity goal;
- the deliverables: tool, report, replication package.

**What changes:**
- **Corpus.** We drop validating a TAR annotator against Bouzenia & Pradel's 120 labelled
  trajectories (old RQ1). The project now works on our own Android corpus.
- **Novelty.** It moves from "multi-granularity" in general to *automatic, outcome-aware
  segmentation*. Section 2 explains why.

Supporting documents:
- [Related study - existing tools.md](Related%20works/Related%20study%20-%20existing%20tools.md) — 19-tool survey;
- [Parser/Segmentation spec.md](Parser/Segmentation%20spec.md) — how segments and purposes are built;
- [Parser/Annotation codebook.md](Parser/Annotation%20codebook.md) — level definitions and the manual protocol;
- [Parser/View data contract.md](Parser/View%20data%20contract.md) — tool output format.

---

## 1. Data (facts the plan depends on)

| | |
|---|---|
| Corpus | 50 Android APR bugs × Claude Code, Codex, Gemini CLI = **150 trajectories, ~5,400 tool calls** |
| Task setting | `code_localization_tests`: bug report + one failing UI test + "Good Starting Points". The logs match this config best: agents' own pass claims agree on Codex 49/50, Claude 39/50, Gemini 36/50 |
| Format | normalised to **ATIF v1.7**, validated by our validator and Harbor's; 100% text retention measured by `atif.cli audit` |
| Outcomes | `Inspection/Dataset/APR_results/test_results_<agent>.csv`, 4 configs × 50 bugs. For our config, all tests pass in **Claude 40/50, Codex 45/50, Gemini 39/50**. Bugs 1198, 1202, 1205 fail for every agent |
| Superseded | `results-localization-codex/test_results_run_*.csv` (0/50 pass) is **not** an outcome. On the Codex host, `run_pipeline.sh` dies at `jenv local 11` before printing results, so all 50 rows record 0 test results |

**Caveats that shape every analysis:**
- Each agent ran on a different machine, so environment failures are partly host effects.
- Failures are few: 26 failing runs in total, and only 5 for Codex.
- There is one run per bug and agent.
- Thought text is missing for most actions.

---

## 2. Novelty — what we claim, and what we no longer claim

The survey of 19 tools shows that "multiple levels of abstraction" is already claimed by
IBM Explorer, SeaView, Graphectory, Langfuse and ProcGrep. Every existing hierarchy is
either **structural** (spans, calls, subagents, experiment scopes) or a **per-step phase
tag** from fixed rules (Graphectory, ATO, Mindwalk). Our earlier per-action phase rule
repeats Graphectory's before/after-patch idea.

**Claims (tool-level, each tested head-to-head):**

1. **C1 — Outcome-aware segmentation.**
   - **What the tool does:** it automatically partitions a trajectory into contiguous,
     strictly nested segments (steps → higher-level actions → purposes). Each segment has a
     type and an outcome read from the result text.
   - **What is new:** it is context-aware. The same failing test is *reproduced* before the
     first source edit and *fix failed* after it.
   - **Why no existing tool has it:** none produces contiguous multi-step units, and
     clustering cannot recover this distinction (48/59 conflated, see §5).
2. **C2 — Failure and inefficiency spans, surfaced and visible.** The tool flags:
   - blocked reproduction;
   - stuck repetition (same command, same error);
   - environment wrestling;
   - failed fix–verify loops;
   - abandoned attempts;
   - test-oracle and harness edits.

   The viewer shows each flagged span as a block, a timeline overlay and a Sankey path.
   Existing detectors are near-silent on this corpus:
   - AgentDiff-style stagnant loops fire in 0/6/0% of runs (Claude/Codex/Gemini);
   - Mindwalk's EditsAfterLastVerify fires in 0/0/4%.
3. **C3 — It beats re-implemented baselines on human ground truth.** This is the
   "outperforms existing tools" claim. It is an evaluation result, but it is the evidence
   for C1 and C2:
   - against Graphectory-style phase runs, ProcGrep-style BPE, fixed windows and K-means
     typing, on segment boundaries, types and outcomes;
   - against the existing detectors, on flag precision and recall;
   - in a small analyst study against a step-list viewer.

**No longer claimed as novelty:**
- ATIF ingestion — Inspect Scout already imports ATIF.
- Pattern mining in itself — Graphectory already mines phase strings.
- Agreement metrics in themselves — those are evaluation.

Pattern statistics stay in the tool, but as *views of C2*, not as a contribution.

---

## 3. Research questions (new)

| RQ | Question | Data | Metrics |
|---|---|---|---|
| **RQ1 Segmentation validity** | How accurately does the automatic pipeline recover human-annotated segments (boundaries, types, outcomes) and purposes, compared with baselines from existing tools and with human–human agreement? | test set, 15 trajectories, 2 raters | boundary F1 (one-to-one, tol 0/±1), WindowDiff; κ for type, outcome and purpose; human κ as ceiling |
| **RQ2 Surfacing failure and inefficiency** | How precisely does the tool flag failure and inefficient spans, compared with human judgement and with existing detectors? | test set + ~30 sampled flag instances | per-flag precision and recall |
| **RQ3 Behavioural insight** | Which segment-level behaviours separate passing from failing runs, and how do the three agents differ, at each level? | all 150 trajectories | effect sizes, Fisher / Mann-Whitney with Holm correction; reported as exploratory (26 failures) and same-bug controlled |
| **RQ4 Usefulness** | Do analysts find the failure cause of a run faster and more accurately with the viewer than with a step-list baseline? | 5–8 participants, forensics tasks (Graphectory-style) | task accuracy, time, SUS |

---

## 4. Method

**Pipeline**, all deterministic and in `Parser/atif/`:

1. Convert each raw log to ATIF.
2. Assign each tool call a mid-level category.
3. Parse a verdict and failure kind from each result.
4. Assign a per-action phase with the state-based rule.
5. Segment with rules R1–R11.
6. Type each segment with the codebook.
7. Overlay loops.
8. Attach outcome and badges.
9. Export the `trajview/1` dataset to the viewer.

**LLM variant (M4, optional).** An LLM pass handles only what the rules cannot see:
- intent shifts inside long localization runs;
- natural-language segment names.

Every label must cite its step ids. The LLM runs at temperature 0, its model version is
recorded, and it is scored on the same test set as the rules.

**Baselines (RQ1/RQ2):**
- **Graphectory-style:** per-command phase tag, then run-length segments.
- **BPE (ProcGrep-style):** K fixed in advance at 10/20/40 merges, run-collapsed atoms,
  leave-bug-out fitting, support ≥ 10%. It is a co-occurrence floor, not "discovered
  procedures". At ProcGrep's K = 192 our corpus is too small: 43% of merges never occur in
  held-out bugs, and independent halves share only 23% of their vocabulary.
- **Trivial floors:** mid-level run-length, fixed windows, random boundaries with the same
  count.
- **Clustering:** K-means on segment features, agglomerative on edit distance.
- **Detectors:** AgentDiff stagnant loop, Mindwalk EditsAfterLastVerify, the
  claude-session-visualizer recovery rule.

**Viewer.** Six coordinated views over one shared state:
1. collapsible top-down;
2. timeline with playhead and loop overlays;
3. phase Sankey (split by agent, outcome or fail-heavy);
4. category × step fingerprint grid;
5. agent comparison aligned by LCS;
6. statistics and classification table.

Filters cover agent, outcome, purpose, segment type, outcome, flags and level. Filtered-out
items are greyed out.

---

## 5. Evidence so far (experiments of 2026-09-30, each re-checked independently)

- **The segment layer is feasible.**
  - 1,706 segments in 891 purposes, with 0 violations of the nesting invariants on 150
    trajectories.
  - Median per trajectory: 28 LLM steps → 10 segments → 6 purposes.
  - Weakness: 66% of purposes hold a single segment.
- **K-means is not the typing mechanism.** Without purpose features, silhouette is 0.34 and
  the clusters follow the dominant tool. With purpose features it re-finds the input label
  (NMI 0.91). It ignores order (30% of segments collide with a differently ordered one) and
  conflates reproduced with fix-failed (48/59). Silhouette has no peak for k = 4–30.
- **Chosen pipeline:** segment first; use clustering within a purpose only to suggest
  types; freeze a codebook; collect human labels; train or prompt a classifier.
- **Agent signatures differ sharply.**
  - Gemini reproduces the bug before fixing in about 43–46/50 runs; Codex tries in 46/50
    but is blocked by the environment in most; Claude never runs a test before its first
    edit.
  - Gemini edits test scripts in 12/50 runs. Most of these make the tests more robust, but
    in 1446 and 171 they change what the test expects.
- **Defects found and being fixed in the port:**
  - the raw `failed` flag only works for Codex;
  - the "stuck" detector is too loose (strict stuck: 4/50 Codex, not 31);
  - 4 Gemini reproductions were mislabelled;
  - some "pass" labels have no test evidence;
  - Codex heredoc `apply_patch` was missed as an edit.

---

## 6. Milestones

| # | Dates | Work | Deliverable |
|---|---|---|---|
| M1 ✓ | Aug 28 – Sep 29 | ATIF converters, dual validation, retention audit; 19-tool survey | `Parser/`, Technical report, related study |
| **M2** | **Sep 30 – Oct 5** | segmenter, verdict parser, outcomes and phase rule v2 in `atif/`, with regression tests; viewer v0 (6 views); segmentation spec and codebook; generate blind annotation sheets; both raters label the pilot (bug-18 × 3) | runnable prototype (`atif.cli view --all` + `viewer/index.html`), docs |
| M3 | Oct 6 – Oct 19 | pilot discussion → codebook v1 frozen; both raters label the test set (15 trajectories, 708 actions); adjudication; human κ | reference set, agreement table |
| M4 | Oct 20 – Nov 9 | implement baselines; optional LLM boundary and labelling pass; score everything on the test set; label ~30 flag instances for detector precision | RQ1 and RQ2 tables |
| M5 | Nov 10 – Nov 23 | RQ3 analysis with outcomes; Sankey and statistics views by outcome; same-bug agent comparison | RQ3 tables and figures |
| M6 | Nov 24 – Dec 7 | RQ4 analyst study; replication package; final report | tool, package, report |

**Rule:** no change to rules, thresholds or the codebook after test-set labelling starts.
They are tuned on the pilot only, and any later change is reported as a deviation.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Few failures (26), so RQ3 has low power | report effect sizes and same-bug contrasts; frame as exploratory; use the 4 configs in `APR_results` only as context |
| Host confound (different machine per agent) | label environment failures as `env`; compare process within an agent; state it as a threat |
| Rules tuned on the same bugs they are judged on | pilot (bug-18) used for tuning; test bugs held out; freeze before labelling |
| One annotator available | if a second rater is not available, double-label at least 5 test trajectories and report κ on those |
| Purpose layer compresses little | report it honestly; the segment layer carries the claim |
| Gemini subagent work is not logged | flag as a known gap; exclude delegated spans from boundary scoring |
