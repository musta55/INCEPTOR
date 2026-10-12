"""Real outcomes, and process facts ("badges") read from the trajectory itself.

Outcome: ``Dataset/a_apr_test_results/<agent>_run<k>.csv`` (``OUTCOME_SOURCE``), one file per
agent and run, one row per bug, one column per prompt configuration: ``bug_id`` followed by
the 17 configs of ``corpus.CONFIGS``, each cell ``1`` (the harness's APR check passed) or
``0``.  3 agents x 3 runs x 17 configs x 50 bugs = 7,650 outcomes, one per trajectory of the
17 configs.  The harness compiled the patched app and ran the instrumentation tests; the
verdict is not the agent's own claim.  ``file_method_screen`` (``corpus.EXTRA_CONFIGS``)
has no column, so its trajectories have no outcome.

``outcome_for`` gives one trajectory's outcome with the same bug's outcome in the other runs
of its config (``by_run``) and in the other configs of its run (``by_config``).

Badges, each one backed by concrete action indices (``badge_steps``):

self_claims_pass       the final assistant message claims that the bug-exposing test or the
                       suite passes (``self_report`` in claims_suite_pass/claims_target_pass)
reproduced_before_fix  a test ran and failed (verdict fail, fail_kind test) before the first
                       source edit
edits_test_script      an edit_file action wrote a file under reproducing_script_project/ or
                       androidTest/
edits_harness          an edit_file action wrote run_pipeline.sh
env_blocked_runs       build/run_test runs (a background run and its polls count once) whose
                       verdict is fail with fail_kind env
last_test_verdict      the verdict of the last run_test run that produced one (pass/fail);
                       none when no test run ever produced a verdict

``phase_badges`` gives the badges of the viewer (``trajview/3``) from a phase result
(``atif.phase.phases``), so that they agree with the subphases the viewer draws; each one is
backed by the first action of the subphases behind it:

self_claims_pass, self_report, last_test_verdict   as above
reproduced_before_fix  a Reproduction subphase succeeded (the bug's test failed before the fix)
test_modified          a subphase carries the test_modified flag
repeated_failure       a subphase carries the repeated_failure flag
blocked_checks         subphases whose outcome is blocked
final_repair_outcome,  outcome and evidence of the last Repair subphase (None without one):
final_repair_evidence  unchecked = the final change was never run; succeeded on build = it
                       compiles, but no test judged it

Known deviations: files changed from the shell (``echo ... >> gradle.properties``,
``cp gradle-wrapper.jar reproducing_script_project/...``, ``sed -i``) do not count as edits
for the two edit badges; a sub-agent's edits count only when the log records the sub-agent's
own steps (the parsers embed them as ``subagent_trajectories``).  The self-report classifier
is a regular-expression reading of English text, checked by eye on the 150 final messages of
the earlier one-run corpus, not against labels, and not yet re-checked on this corpus.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import taxonomy
from .corpus import AGENTS, CONFIGS, DEFAULT_CONFIG, RUNS

OUTCOME_SOURCE = "a_apr_test_results"
_OUTCOME_FILE = re.compile(r"^(%s)_run(\d+)\.csv$" % "|".join(AGENTS))
SELF_REPORTS = ("reports_failure", "claims_suite_pass", "claims_target_pass",
                "claims_unit_tests", "claims_build_only", "no_test_claim", "empty")
PASS_CLAIMS = ("claims_suite_pass", "claims_target_pass")

OutcomeTable = Dict[Tuple[str, str, int, str], Optional[bool]]


def _flag(value: Optional[str]) -> Optional[bool]:
    value = (value or "").strip().lower()
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    return None


def load(dataset: Path) -> OutcomeTable:
    """{(agent, config, run, bug_id): pass} from every ``<agent>_run<k>.csv``.

    Every config column of a file is read (the 17 of ``CONFIGS`` today); a blank or
    unreadable cell gives None, a missing row or file gives no key at all."""
    out: OutcomeTable = {}
    folder = Path(dataset) / OUTCOME_SOURCE
    if not folder.is_dir():
        return out
    for path in sorted(folder.iterdir()):
        match = _OUTCOME_FILE.match(path.name)
        if not match:
            continue
        agent, run = match.group(1), int(match.group(2))
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                bug = str(row.pop("bug_id", "") or "").strip()
                if not bug:
                    continue
                for config, value in row.items():
                    if config:
                        out[(agent, config.strip(), run, bug)] = _flag(value)
    return out


def outcome_for(table: OutcomeTable, agent: str, bug_id: str, config: str = DEFAULT_CONFIG,
                run: int = 1) -> Dict[str, Any]:
    """``pass`` for one trajectory, plus ``by_run`` (same config, runs "1".."3") and
    ``by_config`` (same run, the 17 configs).  None where the CSVs have no value, which is
    always the case for ``file_method_screen``."""
    bug, run = str(bug_id), int(run)
    return {
        "pass": table.get((agent, config, run, bug)),
        "by_run": {str(r): table.get((agent, config, r, bug)) for r in RUNS},
        "by_config": {c: table.get((agent, c, run, bug)) for c in CONFIGS},
    }


# --------------------------------------------------------------------------- #
# self-report: what the final message claims about testing

_F = re.I | re.S
#: first match wins, in this order
_SELF_REPORT_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("reports_failure", (
        r"\b\d+ passed, [1-9]\d* failed", r"\bpass=\d+ fail=[1-9]",
        r"still (?:has )?(?:one |an? )?(?:unstable )?(?:fail|failing)",
        r"(?<!hard-)fail(?:ed|s)? in this (?:environment|sandbox|emulator)",
        r"could not (?:be )?(?:fully )?(?:validat|verif|get a clean pass)", r"\bflaky\b",
        "❌", r"all tests failed", r"not (?:be )?(?:fully )?validated",
        r"unable to (?:run|verify|validate)", r"(?:test|suite|script)\S* (?:still )?fails\b",
        r"except the flaky", r"\bFAIL\*\*")),
    ("claims_suite_pass", (
        r"all (?:\d+ )?(?:of the )?(?:tests?|test cases?|scripts?)(?: \w+){0,3} (?:now )?pass",
        r"\b(?:[2-9]|\d{2,}) passed, 0 failed", r"\bpass=\d+ fail=0", r"OK \([2-9] tests\)",
        r"(?:full|entire|whole) (?:test )?suite[^.\n]{0,80}?pass",
        r"all other tests[^.\n]{0,40}pass", r"run_pipeline\.sh all[^\n]{0,80}pass",
        r"(?:all|every) (?:\w+ ){0,3}tests? (?:\w+ ){0,3}pass(?:ed|es)? successfully",
        r"test suite[^.\n]{0,40}(?:passes|passed|pass\b)", r"no regressions",
        r"tests? passed(?:,| and)? including")),
    ("claims_target_pass", (
        r"Script\d+\w*`?\)?[^\n]{0,60}?(?:pass|OK \(1 test\))",
        r"bug-exposing test[^\n]{0,60}?pass", r"reproduc\w+ (?:test|script)[^\n]{0,80}?pass",
        r"\b1 passed, 0 failed", r"OK \(1 test\)")),
    ("claims_unit_tests", (r"unit tests? pass",)),
    ("claims_build_only", (
        r"build (?:succeeds|succeeded|successful|passed|passes)", r"BUILD SUCCESSFUL",
        r"compiles? (?:successfully|without errors)", r"verified (?:for|by) compil")),
)


def classify_self_report(text: str) -> Tuple[str, str]:
    """(label, evidence) for an agent's final message; labels in SELF_REPORTS.

    Strict on purpose: a failure report outranks any pass claim in the same message, and
    "build successful" or "unit tests pass" are not claims that the UI tests pass."""
    if not text or not text.strip():
        return "empty", ""
    for label, patterns in _SELF_REPORT_RULES:
        for pattern in patterns:
            match = re.search(pattern, text, _F)
            if match:
                return label, match.group(0)
    return "no_test_claim", ""


def _message_text(message: Any) -> str:
    """A step's message as plain text (ATIF allows a string or a list of content parts)."""
    if isinstance(message, list):
        return "\n".join(str(part.get("text") or "") for part in message
                         if isinstance(part, dict) and part.get("type") == "text").strip()
    return str(message or "").strip()


def _acts(step: dict) -> bool:
    """Whether a step calls a tool other than a plan update (taxonomy mid-level ``plan``:
    Codex's update_plan, Claude Code's TodoWrite), which records intent and acts on nothing."""
    return any(taxonomy.mid_level(call) != "plan" for call in step.get("tool_calls") or [])


def final_message(trajectory: dict) -> str:
    """The agent's closing text: the messages of the main trajectory's agent steps after its
    last step that calls a tool, joined; else the log's own final result
    (``extra.final_message``, e.g. Claude's ``ResultMessage.result``).

    Several messages can follow the last tool call: Qwen Code answers a sub-agent's
    "Background agent ... completed" notice (a user step, skipped) after its summary, and
    the summary must not be lost to that follow-up.  A step that only updates the plan is
    not a tool call here, so Codex's closing note next to its last update_plan ("Build
    succeeded. I'm closing out ...") is kept.  A run cut off mid-work ends in a tool call,
    so the narration beside that call is not a closing message."""
    steps = [s for s in trajectory.get("steps", []) if s.get("source") == "agent"]
    last_tool = max((k for k, s in enumerate(steps) if _acts(s)), default=-1)
    texts = (_message_text(s.get("message")) for s in steps[last_tool + 1:])
    text = "\n".join(t for t in texts if t)
    return text or str((trajectory.get("extra") or {}).get("final_message") or "")


# --------------------------------------------------------------------------- #
# badges

_TEST_SCRIPT_PATH = re.compile(r"(?:^|/)(?:reproducing_script_project|androidTest)/")


def badges(trajectory: dict, actions: List[dict],
           first_source_edit: Optional[int]) -> Tuple[Dict[str, Any], Dict[str, List[int]]]:
    """(badges, badge_steps) for one trajectory; ``actions`` are ``segment.prepare`` rows."""
    label, _evidence = classify_self_report(final_message(trajectory))
    anchor = first_source_edit if first_source_edit is not None else 10 ** 9
    by_index = {a["action_index"]: a for a in actions}
    steps: Dict[str, List[int]] = {"reproduced_before_fix": [], "edits_test_script": [],
                                   "edits_harness": [], "env_blocked_runs": [],
                                   "last_test_verdict": []}
    # one verdict per run: a background run's polls report for the command that started it
    runs: Dict[int, dict] = {}
    for a in actions:
        if a["mid_level"] == "edit_file":
            files = a.get("edit_files") or []
            if any(_TEST_SCRIPT_PATH.search(f) for f in files):
                steps["edits_test_script"].append(a["action_index"])
            if any(f.rsplit("/", 1)[-1] == "run_pipeline.sh" for f in files):
                steps["edits_harness"].append(a["action_index"])
        start = a.get("waits_on") if a["mid_level"] == "wait_process" else a["action_index"]
        if start is None or a.get("verdict") not in ("pass", "fail"):
            continue
        mid = by_index[start]["mid_level"] if start in by_index else a["mid_level"]
        runs[start] = {"mid": mid, "verdict": a["verdict"], "fail_kind": a.get("fail_kind"),
                       "at": a["action_index"]}
    tests = [(start, run) for start, run in sorted(runs.items()) if run["mid"] == "run_test"]
    for start, run in tests:
        if start < anchor and run["verdict"] == "fail" and run["fail_kind"] == "test":
            steps["reproduced_before_fix"].append(run["at"])
    for start, run in sorted(runs.items()):
        if run["mid"] in ("build", "run_test") and run["verdict"] == "fail" \
                and run["fail_kind"] == "env":
            steps["env_blocked_runs"].append(run["at"])
    last = tests[-1][1] if tests else None
    if last:
        steps["last_test_verdict"] = [last["at"]]
    result = {
        "self_claims_pass": label in PASS_CLAIMS,
        "reproduced_before_fix": bool(steps["reproduced_before_fix"]),
        "edits_test_script": bool(steps["edits_test_script"]),
        "edits_harness": bool(steps["edits_harness"]),
        "env_blocked_runs": len(steps["env_blocked_runs"]),
        "last_test_verdict": last["verdict"] if last else "none",
        "self_report": label,
    }
    return result, steps


def phase_badges(trajectory: dict, result: Dict[str, Any]
                 ) -> Tuple[Dict[str, Any], Dict[str, List[int]]]:
    """(badges, badge_steps) of the viewer, from a phase result (``atif.phase.phases``)."""
    old, old_steps = badges(trajectory, result["actions"], result["anchor"])
    subs = [(s["phase"], sp) for s in result["phases"] for sp in s["subphases"]]
    steps: Dict[str, List[int]] = {
        "reproduced_before_fix": [sp["start"] for p, sp in subs
                                  if p == "reproduction" and sp["outcome"] == "succeeded"],
        "test_modified": [sp["start"] for _, sp in subs if "test_modified" in sp["flags"]],
        "repeated_failure": [sp["start"] for _, sp in subs
                             if "repeated_failure" in sp["flags"]],
        "blocked_checks": [sp["start"] for _, sp in subs if sp["outcome"] == "blocked"],
        "final_repair": [],
        "last_test_verdict": old_steps["last_test_verdict"],
    }
    final = next((sp for p, sp in reversed(subs) if p == "repair"), None)
    if final is not None:
        steps["final_repair"] = [final["start"]]
    return {
        "self_claims_pass": old["self_claims_pass"],
        "reproduced_before_fix": bool(steps["reproduced_before_fix"]),
        "test_modified": bool(steps["test_modified"]),
        "repeated_failure": bool(steps["repeated_failure"]),
        "blocked_checks": len(steps["blocked_checks"]),
        "final_repair_outcome": final["outcome"] if final else None,
        "final_repair_evidence": final["evidence"] if final else None,
        "last_test_verdict": old["last_test_verdict"],
        "self_report": old["self_report"],
    }, steps
