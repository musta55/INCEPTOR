"""What an execution action's result says: pass, fail or none, and why it failed.

The log's own error flag (``failed`` in the annotation sheet) is exit-code based, and
this benchmark's ``run_pipeline.sh`` exits 0 when the instrumented test *fails*, so the
flag misses most test failures.  The verdict is therefore read from the result text.

verdict    pass | fail | none
fail_kind  test   the test executed and failed (or the app crashed under it)
           build  the project's own code does not compile
           env    the toolchain or sandbox stopped the run: SandboxDenied, wrong JDK,
                  plugin/keystore/SDK/lock problems, command not found, nothing ran
           exit   a non-zero exit with no recognisable signature
           None   unless verdict == fail
evidence   which marker decided it (``results``, ``script``, ``junit_ok``,
           ``gradle_tests``, ``build_ok``, ``exit``, ...), for auditing

Rules, in order (first match wins):

1. Only executing or polling actions get a verdict (``EXEC_MIDS``).  Reads, searches and
   ``git`` never do, although ``git diff``, ``grep`` over an old log, or ``sed`` of
   ``run_pipeline.sh`` print the very markers parsed below.
2. ``Results: N passed, M failed``: M > 0 is a test failure, N = M = 0 means nothing ran
   (env), otherwise pass.  Then ``>>> ScriptX: PASSED|FAILED``, then JUnit/instrumentation
   failure markers (``FAILURES!!!``, ``Tests run: N, Failures: M>0``, process crashed).
3. Gradle failures (``BUILD FAILED``, ``Execution failed for task``, ...) are ``build`` only
   with a compiler signature inside the "What went wrong" block; plugin, keystore, JDK,
   SDK, lock and daemon failures are ``env``; "There were failing tests" is ``test``.
4. A non-zero exit is ``env`` if the output carries an environment signature, else ``exit``.
5. Passes: ``OK (N tests)``, ``Tests run: N, Failures: 0``, per-test ``> testX PASSED``
   lines, and an executed Gradle unit-test task (``> Task :app:testDebugUnitTest``)
   followed by ``BUILD SUCCESSFUL`` are test evidence.  ``BUILD SUCCESSFUL`` or exit 0
   alone are not: for a ``run_test`` action (or a poll of one) they give ``none``, since a
   ``| head -60`` can cut the output before the test result; for every other action they
   give ``pass``.
6. A background run still in progress, and anything unrecognised, give ``none``.

Known deviations: the markers are Gradle's and JUnit's, plus those of the earlier corpus's
harness (run_pipeline.sh, AndroidJUnitRunner), which this corpus no longer runs; another
harness needs its own.  A run in progress is recognised by Codex's ``Process running with
session ID``; Qwen Code's ``Background shell ... started`` carries no verdict marker and gives
``none`` by rule 6.  ``fail_kind`` env vs exit is a word list over
the first 400 characters for exit-0 results, so a command that echoes an error message it
handled is still read as an env failure.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

VERDICTS = ("pass", "fail", "none")
FAIL_KINDS = ("test", "build", "env", "exit")
#: the mid-level types that execute something or poll something that executes
EXEC_MIDS = ("build", "run_test", "device_ops", "run_shell", "env_setup", "wait_process")

RE_RESULTS = re.compile(r"Results:\s*(\d+)\s+passed,\s*(\d+)\s+failed")
RE_SCRIPT = re.compile(r">>>\s*\S+:\s*(PASSED|FAILED)")
RE_JUNIT_FAIL = re.compile(r"FAILURES!!!|Tests run:\s*\d+,\s*Failures:\s*[1-9]"
                           r"|INSTRUMENTATION_(FAILED|RESULT: shortMsg=Process crashed)"
                           r"|Process crashed")
RE_JUNIT_OK = re.compile(r"\bOK \(\d+ tests?\)")
RE_JUNIT_RUN_OK = re.compile(r"Tests run:\s*[1-9]\d*,\s*Failures:\s*0\b(?!,\s*Errors:\s*[1-9])")
RE_GRADLE_TEST_PASSED = re.compile(r"^\S+ > \S+ PASSED\s*$", re.M)
RE_GRADLE_TEST_FAILED = re.compile(r"^\S+ > \S+ FAILED\s*$", re.M)
RE_GRADLE_TEST_TASK = re.compile(r"^> Task :(?:[\w-]+:)*(?:test\w*UnitTest|test)\s*$", re.M)
RE_BUILD_FAIL = re.compile(r"BUILD FAILED|FAILURE: Build failed|Compilation failed|: error: "
                           r"|error: cannot find symbol|Execution failed for task")
RE_BUILD_OK = re.compile(r"BUILD SUCCESSFUL")
RE_ENV_FAIL = re.compile(
    r"blocked by policy|JAVA_HOME is set to an invalid|SandboxDenied|Operation not permitted"
    r"|command not found|No such file or directory|Permission denied|not installed"
    r"|Unable to locate a Java Runtime|Could not (find|resolve|determine)"
    r"|Unsupported class file major version|requires Java|Error: Could not"
    r"|device (offline|not found)|no devices/emulators found")
#: signatures that make a Gradle "BUILD FAILED" an environment problem, not a code problem
RE_ENV_IN_BUILD = re.compile(
    r"Operation not permitted|Could not determine java version|Unsupported class file major"
    r" version|requires Java|JAVA_HOME|\.lock|SDK location not found|failed to find target"
    r"|Could not (?:resolve|download|GET|HEAD)|license(?:s)? (?:for|have not been accepted)"
    r"|NDK|Unable to (?:start|find) the daemon|Permission denied|java\.net\.|UnknownHost"
    r"|timed? ?out")
RE_WRONG = re.compile(r"What went wrong:\s*(.{0,500})", re.S)
RE_RUNNING = re.compile(r"Process running with session ID")
#: exit-status lines: Codex's ``Process exited with code N``, Qwen Code's ``Exit Code: N``
#: footer and ``Command exited with code: N``; Claude Code prints ``Exit code N`` only on
#: failure, where the result's error flag already says so
RE_EXIT = re.compile(r"(?:Process exited with code|exited with code:?|Exit Code:)\s*(\d+)")
RE_TESTS_FAILED = re.compile(r"There were failing tests")
#: a Gradle failure counts as a *code* build failure only with a compiler signature
RE_COMPILE = re.compile(r"Compilation failed|Compilation error|\.(?:java|kt):\d+: error:"
                        r"|error: cannot find symbol|^e: .*\.kt", re.M)
RE_COMPILE_BUT_ENV = re.compile(r"javax/xml/bind|JAXBException|Unable to make field"
                                r"|Unsupported class file major version")

#: evidence labels that do not show a test result
_NO_TEST_EVIDENCE = ("build_ok", "exit")
#: Qwen Code wraps a failing or silent command's output in an envelope that starts by
#: echoing the command (``Command: ...`` up to ``Directory: ...``); the echo is the agent's
#: own text, so a ``grep "BUILD FAILED"`` in it is not a build failure
_COMMAND_ECHO = re.compile(r"\ACommand: [\s\S]*?^Directory: [^\n]*\n?", re.M)


def strip_echo(text: str) -> str:
    """The result text without the agent's echoed command (``_COMMAND_ECHO``)."""
    return _COMMAND_ECHO.sub("", text, count=1) if text.startswith("Command: ") else text


def _build_kind(text: str) -> str:
    match = RE_WRONG.search(text)
    context = match.group(1) if match else text[-1500:]
    if RE_TESTS_FAILED.search(context):
        return "test"
    if RE_COMPILE_BUT_ENV.search(context) or RE_ENV_IN_BUILD.search(context):
        return "env"
    if RE_COMPILE.search(context) or (not match and RE_COMPILE.search(text)):
        return "build"
    return "env"


def _read(text: str, failed: bool, command: str) -> Tuple[str, Optional[str], str]:
    """(verdict, fail_kind, evidence) before the run_test evidence rule is applied."""
    results = RE_RESULTS.findall(text)
    if results:
        passed, failures = map(int, results[-1])
        if failures > 0:
            return "fail", "test", "results"
        return ("fail", "env", "results_empty") if passed == 0 else ("pass", None, "results")
    scripts = RE_SCRIPT.findall(text)
    if scripts:
        return ("fail", "test", "script") if "FAILED" in scripts else ("pass", None, "script")
    if RE_JUNIT_FAIL.search(text):
        return "fail", "test", "junit_fail"
    if RE_BUILD_FAIL.search(text):
        return "fail", _build_kind(text), "build_fail"
    if failed:
        return "fail", ("env" if RE_ENV_FAIL.search(text) else "exit"), "exit"
    if RE_JUNIT_OK.search(text) or RE_JUNIT_RUN_OK.search(text):
        return "pass", None, "junit_ok"
    if RE_RUNNING.search(text) and not RE_EXIT.search(text):
        return "none", None, "running"
    if RE_BUILD_OK.search(text):
        if RE_GRADLE_TEST_FAILED.search(text):
            return "fail", "test", "gradle_tests"
        if RE_GRADLE_TEST_PASSED.search(text) or RE_GRADLE_TEST_TASK.search(text):
            return "pass", None, "gradle_tests"
        return "pass", None, "build_ok"
    if RE_ENV_FAIL.search(text[:400]) and "logcat" not in command:
        return "fail", "env", "env_head"       # environment errors surface at the head
    codes = RE_EXIT.findall(text)
    if codes:
        return ("fail", "exit", "exit") if int(codes[-1]) != 0 else ("pass", None, "exit")
    return "none", None, ""


def verdict(mid: str, text: str, failed: Optional[bool] = False, command: str = "",
            effective_mid: Optional[str] = None) -> Tuple[str, Optional[str], str]:
    """(verdict, fail_kind, evidence) for one action.

    ``mid`` is the action's own mid-level type; ``effective_mid`` is the type of the
    command it polls when it is a ``wait_process`` on a background session."""
    if mid not in EXEC_MIDS:
        return "none", None, ""
    result, kind, evidence = _read(strip_echo(text or ""), bool(failed), command or "")
    if result == "pass" and (effective_mid or mid) == "run_test" \
            and evidence in _NO_TEST_EVIDENCE:
        return "none", None, "no_test_evidence"
    return result, kind, evidence


def attach(rows: List[dict]) -> List[dict]:
    """Set ``verdict``, ``fail_kind``, ``verdict_evidence`` and ``effective_mid`` on
    annotated rows (``taxonomy.annotate``, which resolves ``waits_on``)."""
    by_index: Dict[int, dict] = {r["action_index"]: r for r in rows}
    for row in rows:
        started = by_index.get(row.get("waits_on")) if row.get("waits_on") else None
        row["effective_mid"] = started["mid_level"] if started else row["mid_level"]
        row["verdict"], row["fail_kind"], row["verdict_evidence"] = verdict(
            row["mid_level"], row.get("result") or "", row.get("failed"),
            row.get("command") or "", row["effective_mid"])
    return rows


# --------------------------------------------------------------------------- #
# error signatures, for "the same failure again" (atif.segment, stuck detection)

# Codex's output header, and Qwen Code's envelope footer
_NOISE = re.compile(r"Chunk ID: \w+|Wall time: [\d.]+ seconds|Original token count: \d+"
                    r"|^Error: \(none\)$|^Exit Code: \d+$|^Signal: .*$|^Background PIDs: .*$"
                    r"|^Process Group PGID: .*$|^Output: \(empty\)$"
                    r"|Process exited with code \d+|^Output:\s*$", re.M)
_FAILED_TEST = re.compile(r">>>\s*(\S+):\s*FAILED|^\S+ > (\S+) FAILED\s*$", re.M)
_FAILED_LIST = re.compile(r"Failed tests:\s*([^\n]+)")
_EXCEPTION = re.compile(r"\b((?:[a-z]\w*\.)+[A-Z]\w*(?:Exception|Error|Failure))\b")
_ERROR_LINE = re.compile(r"(SandboxDenied[^\n]{0,80}|[^\n]*\b(?:error|Error|ERROR)\b:?[^\n]{0,100}"
                         r"|[^\n]*Exception[^\n]{0,100}|Could not[^\n]{0,100}"
                         r"|[^\n]*(?:not permitted|not found|not installed|Permission denied)"
                         r"[^\n]{0,60}|[^\n]*FAILED[^\n]{0,60})")


def _normalise(message: str) -> str:
    message = re.sub(r"(?:~|\.{0,2})?/[\w.\-+/@]+", "<path>", message)
    message = re.sub(r"\b[0-9a-f]{7,}\b", "<hex>", message)
    message = re.sub(r"\d+", "N", message)
    return re.sub(r"\s+", " ", message).strip()[:120]


def error_signature(text: str, fail_kind: Optional[str]) -> str:
    """``<fail_kind>:<normalised key message>`` of a failing result.

    test       the names of the failing tests (``>>> Script18: FAILED``, ``Failed tests:``,
               Gradle ``Class > method FAILED``), else the first exception class; names
               survive ``| tail`` vs ``| grep`` changes, a stack trace does not
    otherwise  the first line of Gradle's "What went wrong:" block, else the first line
               that looks like an error, else the first output line
    Paths, hex ids and numbers are masked so that ``/tmp/gradle-1`` vs ``/tmp/gradle-2``
    or a different PID do not make the same error look new."""
    body = _NOISE.sub("", strip_echo((text or "").replace("\\n", "\n")))  # escaped newlines
    if fail_kind == "test":
        names = sorted({a or b for a, b in _FAILED_TEST.findall(body)}
                       | {n.strip() for line in _FAILED_LIST.findall(body)
                          for n in re.split(r"[,\s]+", line) if n.strip()})
        if names:
            return "test:" + ",".join(names)[:120]
        exception = _EXCEPTION.search(body)
        return "test:" + (exception.group(1) if exception else "")
    match = RE_WRONG.search(body)
    if match:
        lines = [line for line in match.group(1).splitlines() if line.strip()]
        message = lines[0] if lines else ""
    else:
        match = _ERROR_LINE.search(body)
        lines = [line for line in body.splitlines() if line.strip()]
        message = match.group(0) if match else (lines[0] if lines else "")
    return f"{fail_kind or 'none'}:{_normalise(message)}"
