# Are the raw logs good enough for TAR annotation?

Audit of `Inspection/bug-8` for all three agents, plus what the native sources would add, plus the
collection recipe I'd use from here. Companion to `Parsing plan.md` (archived in `../Inspection/plans-and-reports-before-phase-taxonomy-2026-10-11.tar.gz`).

## 1. Bottom line

| Agent | Is this the original raw log? | Good enough for Action + Result | Good enough for **Thought** |
|---|---|---|---|
| **Codex** | **Yes** — native `~/.codex/sessions/.../rollout-*.jsonl` | Yes, best of the three | **No** — chain of thought is encrypted |
| **Gemini** | Yes, but the *thinnest* native output — `--output-format stream-json` | Yes | **No** — the stream format has no thought event |
| **Claude Code** | **No** — a `repr()` dump of `claude-agent-sdk` objects, several layers removed from the native log | Yes | Partly — 5 of 28 actions |

So: your instinct is right about Claude Code, and half-right about Gemini. We can start building
the parser/schema/taxonomy on these logs today (that work is unaffected — ATIF absorbs richer input
without a schema change), but **we should not start manual TAR annotation on this corpus**, because
the T is absent for 74% of the actions across the three agents. One re-collection pass fixes most of
it, and for Claude Code the better log may already be sitting on the collection machine.

## 2. Measured TAR coverage on bug-8

Thought = `reasoning_content` (real CoT). Narration = the agent's user-facing prose before the
action, which is a weak substitute for T. Result = a matched tool observation.

| Agent | Inferences | Actions | T: real CoT | T: narration only | T: none | R present | Per-step timestamps | Per-step tokens |
|---|---|---|---|---|---|---|---|---|
| Claude Code (main) | 14 | 13 | 5 | 4 | 4 | 13/13 | **0** | **0** |
| Claude Code (Explore subagent) | 14 | 15 | **0** | 0 | 15 | 15/15 | **0** | **0** |
| Codex | 30 | 47 | **0** | 20 | 27 | 47/47 | 30 | 30 |
| Gemini | 22 | 21 | **0** | 21 | 0 | 21/21 | 22 | 0 |

Results are complete everywhere — the R of TAR is fine in all three logs. The A is fine. **T is the
problem**, in a different way per agent.

Two measurement notes that matter for the parser:

- The Claude repr dump emits **one message per content block**, so one inference spans several
  `AssistantMessage` lines (thinking, then text, then each tool_use). My first pass counted 26 steps;
  coalescing consecutive assistant messages until the next tool-result message yields **14**, which
  matches the log's own `ResultMessage.num_turns = 14`. The POC is now fixed and re-validated. In the
  native JSONL this is not a heuristic at all — `requestId` groups the blocks explicitly.
- Codex's step count is recoverable only because each encrypted `reasoning` item still marks an
  inference boundary. We get the *shape* of thinking (30 inferences, 27 actions taken with no visible
  thought) without its content.

## 3. Per-agent detail

### Codex — keep the format, fix one config flag

`session_meta` / `turn_context` / `response_item` / `event_msg` is the real rollout schema, and it is
rich: sandbox policy, approval policy, model, `cli_version`, git state, the full base instructions,
per-turn `last_token_usage`, and `task_complete` as an explicit terminal event.

The single gap: all 30 `reasoning` items are `{"summary": [], "content": null, "encrypted_content": "gAAAA…"}`.
Encrypted CoT is a server-side policy; what the CLI *can* log is the **reasoning summary**. Codex
exposes this as a config/CLI override (`model_reasoning_summary`, alongside `model_reasoning_effort`);
I could not confirm the exact allowed values from the current docs, so treat this as a two-minute
experiment on the collection machine rather than my word:

```bash
codex exec -c model_reasoning_summary="detailed" -c model_reasoning_effort="high" "fix the failing test" 
# then check the newest rollout:
grep -o '"type": "reasoning"' -c ~/.codex/sessions/<Y>/<M>/<D>/rollout-*.jsonl
python3 -c 'import json;[print(json.loads(l)["payload"].get("summary")) for l in open("<rollout>") if "\"reasoning\"" in l]'
```

If `summary` comes back populated, re-collect with that flag and Codex's T problem is solved.

One more thing to pin down: **the rollout schema is version-dependent.** Your log is CLI `0.114.0`
(`response_item` payloads). Rollouts written by a newer CLI on this machine (`0.150.0-alpha.8`) use a
different shape — `event_msg/item_completed` wrapping typed items (`AgentMessage`, `UserMessage`). So
record `cli_version` per run (we already carry it into ATIF `extra`) and freeze one CLI version for
the whole dataset, or the parser needs a version dispatch.

### Gemini — right agent, wrong output channel

Your file matches the documented `--output-format stream-json` event set exactly (`init`, `message`,
`tool_use`, `tool_result`, `error`, `result`), so it *is* native. But that channel is a UI stream,
and it is lossy in three ways:

1. **No thought events.** The documented event list has none. Meanwhile Gemini CLI's own session
   history — `~/.gemini/tmp/<project_hash>/chats/` — is documented to save "assistant thoughts and
   reasoning summaries (when available)" along with every tool input/output and token stats. That's
   the file we actually want.
2. **Model identity is a routing alias.** `"model": "auto-gemini-3"` — we don't know which model
   served each step. The `result` event carries a per-model token breakdown, and OTEL traces carry
   per-call model attribution; the stream's `init` does not.
3. **Lossy results.** 47 assistant messages arrive as `delta` fragments totalling only 5.7 KB of
   text, one `tool_result` (the `replace` edit) has no `output` field at all, and all 21 results are
   `status: "success"` — I can't tell from one log whether failures are even representable. Against
   that, one `run_shell_command` output is **9.2 MB** of the 11.3 MB file, so the format is
   simultaneously too thin and too fat.

Fix: keep the stream-json (it's a good action/result backbone), **and** copy the session file from
`~/.gemini/tmp/<hash>/chats/` after each run, **and** turn on OTEL to a file
(`GEMINI_TELEMETRY_ENABLED=true`, `GEMINI_TELEMETRY_TRACES_ENABLED=true`, `GEMINI_TELEMETRY_OUTFILE=<path>`,
`GEMINI_TELEMETRY_LOG_PROMPTS=true`) for per-call model, latency and token spans.

### Claude Code — the native log exists and is much better; it may still be recoverable

What you have is the SDK's Python objects printed with `repr()`. It parses cleanly (89/89 lines via
`ast.parse`, no `eval` needed) but it is missing things the native log has. I verified this by
inspecting a real native session JSONL on this machine (712 lines, 306 assistant entries, 47 thinking
blocks):

| Field in native `~/.claude/projects/<slug>/<session-id>.jsonl` | Why it matters | In your dump? |
|---|---|---|
| `timestamp` per entry (ms) | any temporal analysis: step latency, think/act time split | **no** |
| `requestId` | ground truth for grouping blocks into one inference (groups of 1–4 observed) | **no** |
| `message.usage` per assistant message (incl. cache creation/read, `iterations`) | per-step cost/token metrics | **no**, only a run total |
| `effort` per assistant entry | records the reasoning-effort setting per step | **no** |
| `uuid` / `parentUuid` | the real message **DAG** — retries, branches, rewinds; the dump is flattened to a list | **no** |
| `isSidechain` + `sourceToolAssistantUUID` | explicit subagent linkage (I had to infer it from `parent_tool_use_id`) | inferred |
| `toolUseResult` | **structured** tool results, not just the text blob — typed per tool | **no** |
| `file-history-delta` / `file-history-snapshot` | every file edit with backups — free patch extraction | **no** |
| `system` entries with `level`/`error`/`retryAttempt`/`retryInMs` | API failures and retries, i.e. harness flaws | **no** |
| the initial user prompt | your dump starts at `init`, so the task prompt is absent (14 agent steps, 0 user steps) | **no** |
| `gitBranch`, `version`, `cwd` | run provenance | partly (`init` only) |

Claude Code writes that JSONL **regardless** of how you drive it, including via the SDK. Your session
is `291bf389-2868-458d-a065-dc34d0d9be8e` with cwd `/Volumes/Dumpy/buggyLocNoTests/bug-8`, so on the
collection machine look for:

```bash
ls ~/.claude/projects/*buggyLocNoTests*/291bf389-2868-458d-a065-dc34d0d9be8e.jsonl
# or, across everything:
find ~/.claude/projects -name '291bf389-*.jsonl'
```

If those files survive, **your existing Claude runs are recoverable at full fidelity without re-running
anything.** That's the first thing I'd check, before any re-collection.

Second gap, which re-collection *does* have to fix: thinking is recorded only when the model emits it.
5 of 13 main-scope actions have CoT, and the Explore subagent has none at all across 15 actions. Set a
thinking budget explicitly for the run (and decide whether subagent delegation should stay on at all —
a subagent with no visible thought is 15 unannotatable actions in a 28-action trajectory).

## 4. The form I'd want — one directory per run

```
runs/<benchmark>/<bug-id>/<agent>/<run-idx>/
  raw/                     # every native artifact, byte-for-byte, never edited
  meta.json                # agent, cli_version, model id (resolved, not an alias), flags/config,
                           #   prompt template id + the exact prompt text, buggy-repo git sha,
                           #   start/end time, machine, sandbox + approval policy
  outcome.json             # build ok?, failing test passes?, patch plausible/correct (human verdict)
  patch.diff               # git diff of the workspace after the run
  atif/trajectory.json     # generated by our parser; regenerable, never hand-edited
```

`raw/` per agent:

- **Codex**: `rollout-*.jsonl` (+ the `codex exec --json` stdout if you script it), config.toml used.
- **Claude Code**: `~/.claude/projects/<slug>/<session-id>.jsonl` **as the primary**, the SDK
  stream dump as a secondary, and the SDK `ResultMessage`.
- **Gemini**: `--output-format stream-json` stdout, `~/.gemini/tmp/<hash>/chats/<session>.json`, and
  the OTEL outfile.

Three invariants that make the corpus comparable across agents: the **same prompt text** for all
three agents (bug-8 already looks consistent — good), the prompt **inside** the log or in `meta.json`,
and **one frozen CLI version per agent** for the whole dataset.

## 5. What I'd do next, in order

1. **Recover, don't re-run**: check the collection machine for the native Claude JSONLs and the Gemini
   `chats/` files for the runs you already did. Cheapest possible win.
2. **Run the Codex reasoning-summary experiment** above (one toy task, 2 minutes).
3. **One control task, all three agents, everything enabled** → convert → look at the TAR coverage
   table again. If real CoT covers most actions, freeze the setup and scale collection.
4. **In parallel, I build phases 1–3 of `Parsing plan.md`** on the current logs.
   Nothing there is wasted by re-collection: richer input adds fields to the same ATIF envelope, and
   the parsers dispatch on `source_format` anyway. The one thing to hold back is manual annotation.
