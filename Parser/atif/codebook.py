"""The codebook's lookup tables, word for word (Annotation Codebook.docx §8, version 4).

Since 2026-10-17 the categories and phases come from the Final lookup tables
(``atif.lookup``), which replace Tables 1-4 below; those stay word for word as the baseline B5
(``atif.baselines.table_v4``) reads them.  Table 5 (the phase outcomes) and Table 6 (the
flags) still apply; Table 5 names the first phase Planning, the Final tables' name for what
version 4 called Understanding.

The .docx is the master: change it first, then these.  ``atif.phase`` implements Table 4 and
``atif.taxonomy`` Tables 2 and 3; ``make_ground_truth.py`` writes the tables into the
annotation workbook's reference tabs, ``atif.rules`` shows them on the viewer's Lookup tables
page and ``atif.view`` exports them, so the codebook, the workbook, the engine and the viewer
use the same words.  Version 4 (2026-10-14) replaced the grouping rules G1-G8 of version 3
with the phase lookup table and its one convention, *follow*.
"""

#: the codebook version these tables are, as the viewer names it
VERSION = "4"
VERSION_DATE = "2026-10-14"
FOLLOW = "follow"

PHASE_TEXT = {      # Table 1: phase -> (the agent is..., typical rows, where)
    "understanding": ("getting oriented: the task, the repository and its toolchain",
                      "the opening rows, before any code is searched, run or changed (ls, pwd, a "
                      "plan, git status, reading README or AGENTS.md); building the untouched "
                      "project", "before the first fix only"),
    "localization": ("finding the code to change",
                     "searching, listing and reading app or test code it has not changed; git "
                     "blame, show or log of code; reading library code; a sub-agent sent to find "
                     "code", "anywhere"),
    "reproduction": ("trying to see the bug before changing the code",
                     "running a test or the benchmark's check; driving the app on a device; "
                     "writing or editing a test", "before the first fix only"),
    "repair": ("changing the app's code",
               "every edit of app source code or resources, and every undo of such an edit",
               "from the first fix on"),
    "validation": ("checking the patch",
                   "every build and test run after the first fix, including the one right after "
                   "an edit; git diff; re-reading the files it changed; writing or editing tests "
                   "after the fix", "from the first fix on"),
}

#: Table 2a: category -> (family, the action..., Claude Code, Codex, Qwen Code tools)
ACTION_TOOLS = {
    "read_file": ("inspect", "opens a file to read it", "Read, NotebookRead", "–", "read_file"),
    "search_code": ("inspect", "searches for text or file names", "Grep, Glob", "–",
                    "grep_search, glob"),
    "orient": ("inspect", "looks around without reading a file", "LS", "–", "–"),
    "vcs": ("inspect", "inspects the git repository, changing nothing", "–", "–", "–"),
    "diff": ("inspect", "compares versions, usually its own changes", "–", "–", "–"),
    "web": ("inspect", "fetches from the internet", "WebFetch, WebSearch", "web_search", "–"),
    "edit_file": ("modify", "changes a file with an editor tool or a patch",
                  "Edit, MultiEdit, Write, NotebookEdit", "apply_patch", "edit, write_file"),
    "shell_edit": ("modify", "changes a file from the shell, or undoes changes", "–", "–", "–"),
    "build": ("execute", "compiles without running tests", "–", "–", "–"),
    "run_test": ("execute", "runs tests or the benchmark's check", "–", "–", "–"),
    "device_ops": ("execute", "drives a device or emulator", "–", "–", "–"),
    "run_shell": ("execute", "runs any other program", "–", "–", "–"),
    "env_setup": ("configure", "changes the machine or toolchain, not the project", "–", "–", "–"),
    "plan": ("coordinate", "records or updates a plan", "TodoWrite, EnterPlanMode, ExitPlanMode",
             "update_plan", "update_goal, get_goal"),
    "delegate": ("coordinate", "hands work to a sub-agent", "Agent, Task", "–", "agent"),
    "wait_process": ("coordinate", "waits for or stops a process or sub-agent",
                     "TaskOutput, TaskStop, Monitor", "write_stdin",
                     "list_agents, send_message, task_stop"),
    "other": ("other", "anything else", "AskUserQuestion, Skill, ToolSearch, SlashCommand",
              "view_image", "tool_search, skill, record_artifact, zoom_image; tool names the "
              "agent made up (run_shell, list_files)"),
}
#: the shell tools of Table 2a, whose command is looked up in Table 2b
SHELL_TOOLS_ROW = ("Bash", "exec_command, shell", "run_shell_command")

#: Table 2b: category -> the shell programs (and arguments) that give it
ACTION_SHELL = {
    "run_test": "./gradlew, gradle, mvn or ant with a test task (test, check, testDebugUnitTest, "
                "connected…AndroidTest); adb shell am instrument; run_pipeline.sh and other .sh "
                "scripts named test, pipeline or script; pytest; java -cp or junit",
    "build": "./gradlew, gradle, mvn or ant with any other task (assembleDebug, "
             "compileDebugJavaWithJavac, clean, build); make, javac, ninja, cmake",
    "device_ops": "adb (install, shell input, screencap, uiautomator, logcat, devices), emulator, "
                  "avdmanager",
    "shell_edit": "a command that writes a project file: sed -i, perl -i, echo, printf or cat "
                  "with > file, tee file, a Python script that writes a file, git apply, patch; "
                  "a git command that undoes changes: git checkout, restore, stash, reset, clean, "
                  "revert",
    "edit_file": "apply_patch run from the shell (Codex)",
    "diff": "git diff; diff, cmp, colordiff",
    "vcs": "git status, log, show, blame, ls-files, ls-tree, rev-parse, remote, branch, config, "
           "check-ignore, add",
    "search_code": "rg, grep, egrep, ag, ack, find, fd",
    "read_file": "cat, sed -n, head, tail, less, more, nl, bat, javap",
    "orient": "ls, pwd, tree, which, whoami, uname, env, printenv, stat, file, wc, df, du",
    "web": "curl, wget",
    "env_setup": "chmod, chown, rm, cp, mv, ln, unzip, tar, zip, keytool, java_home, jenv, "
                 "sdkmanager, brew, apt-get, pip, npm, defaults; java without a class path; a "
                 "command made only of cd, export and mkdir; a write to a file outside the project",
    "wait_process": "sleep, kill, pkill, pgrep, ps, wait, timeout",
    "run_shell": "python3 script.py, java -jar, bash script.sh, and every program not listed here",
}

#: Table 2c: how a shell command gets one category
COMPOUND_STEPS = [
    "Look inside bash -c '…' and sh -c '…': the script is the command.",
    "Split the command at &&, ||, ;, | and line breaks. Skip the parts that only set up (cd, "
    "export, mkdir, source, set, a variable assignment) and every part after a pipe: | head and "
    "| grep only filter the output.",
    "Look up each remaining part in Table 2b.",
    "The command takes the first category in this list that one of its parts has: run_test, "
    "build, device_ops, env_setup, an edit (shell_edit or edit_file), vcs, search_code, "
    "read_file, web, wait_process, orient, run_shell.",
    "Three refinements: a git command chained with a search or read counts as that search or "
    "read; a git diff anywhere makes the command diff; a git command that undoes changes makes "
    "it shell_edit.",
    "A command made only of setup parts (cd, export, mkdir) is env_setup.",
]

#: Table 3: file role -> (files, how Table 4 uses it).  Roles are checked in this order.
ROLE_TEXT = {
    "output": ("what a run produced: screenshots (.png, .jpg), logs (.log), build/reports, "
               "build/outputs, build/test-results, the agent's own log (bug-<id>_output.txt)",
               "reading it follows the row above: it belongs to the run that made it"),
    "harness": ("run_pipeline.sh, the benchmark's check script",
                "running it is run_test; reading or changing it follows the row above"),
    "docs": ("README, CHANGELOG, LICENSE, CONTRIBUTING, AGENTS.md, .md, .rst, .txt",
             "reading it follows the row above (at the start: understanding)"),
    "toolchain": ("build files: .gradle, .kts, .properties, .pro, the Gradle wrapper, "
                  ".java-version", "reading or changing it follows the row above"),
    "test": ("test/, androidTest/, reproducing_script_project/",
             "changing it is reproduction before the fix and validation after"),
    "source": ("the app's code and resources: everything in the project not listed above",
               "reading or searching it is localization; changing it is repair"),
    "outside": ("paths outside the project: the Gradle cache (~/.gradle), ~/.m2, the Android "
                "SDK, the JDK, /tmp", "reading it follows the row above, unless it is a copy of "
                "app code (.java, .kt, .xml): then it counts as source"),
}

#: Table 4: (id, the row..., before the first fix, from the first fix on).  Use the first
#: row that matches.
PHASE_LOOKUP = [
    ("P1", "changes app source: edit_file or shell_edit of a source file (an undo is P2)",
     "– (the first such row is the first fix)", "repair"),
    ("P2", "undoes changes: shell_edit with git checkout, restore, stash, reset or clean",
     FOLLOW, "repair"),
    ("P3", "changes a test file", "reproduction", "validation"),
    ("P4", "changes a toolchain, harness, docs or outside file", FOLLOW, FOLLOW),
    ("P5", "runs tests or the benchmark's check, or drives a device: run_test, device_ops",
     "reproduction", "validation"),
    ("P6", "builds: build", "understanding", "validation"),
    ("P7", "reads, searches or lists app or test code: read_file, search_code or orient on "
           "source or test files; a search that names no file; git blame, show or log of a code "
           "file", "localization", "localization, or validation when own_patch = yes"),
    ("P8", "compares versions: diff", FOLLOW, "validation"),
    ("P9", "reads, searches or lists docs, toolchain, harness, output or outside files",
     FOLLOW, FOLLOW),
    ("P10", "hands work to a sub-agent: delegate", "localization",
     "repair when it asks the sub-agent to change code, else localization"),
    ("P11", "anything else: vcs (git status, log, rev-parse …), orient, plan, web, env_setup, "
            "run_shell, wait_process, other", FOLLOW, FOLLOW),
]
#: Table 4 read by phase: (phase, the action categories that lead to it, the Table 4 rows,
#: where it can occur).  The same content as PHASE_LOOKUP, grouped the other way round.
PHASE_CATEGORIES = [
    ("understanding",
     "build (before the first fix); read_file, search_code, orient of docs, build files, logs or "
     "paths outside the project, and every follow row (plan, orient, vcs, env_setup, web, "
     "wait_process, other) while nothing comes before it",
     "P6, P9, P11 (follow at the start)",
     "before the first fix only: it opens the trajectory or checks the untouched project; it "
     "never comes back after the first fix"),
    ("localization",
     "read_file, search_code, orient of app or test code (or a search that names no file); vcs "
     "with git blame, show or log of a code file; delegate (unless it asks for a code change "
     "after the first fix)",
     "P7, P10",
     "anywhere, before and after the first fix; after it, rereading only files the agent "
     "already changed is validation instead (own_patch = yes)"),
    ("reproduction",
     "run_test, device_ops; edit_file or shell_edit of a test file",
     "P3, P5",
     "before the first fix only: after it, the same actions are validation"),
    ("repair",
     "edit_file or shell_edit of app source; shell_edit that undoes changes (git checkout, "
     "restore, stash, reset, clean); delegate that asks for a code change",
     "P1, P2, P10",
     "from the first fix on: the first edit of app source is the first fix; nothing before it "
     "is repair"),
    ("validation",
     "build, run_test, device_ops, diff; edit_file or shell_edit of a test file; read_file, "
     "search_code of files the agent already changed (own_patch = yes)",
     "P3, P5, P6, P7, P8",
     "from the first fix on only: before it, the same actions are understanding, reproduction "
     "or localization"),
    ("follow (no phase of its own)",
     "plan, orient, vcs (status, log, rev-parse), web, env_setup, run_shell, wait_process, "
     "other; reads of docs, build files, logs or outside paths; edits of build or config files; "
     "diff before the first fix",
     "P2 and P8 before the first fix, P4, P9, P11",
     "takes the phase of the row above; at the very start of a trajectory, understanding"),
]
FOLLOW_TEXT = ("follow: the row takes the phase of the row directly above it in the same "
               "trajectory; the rows at the start, with no phase above them, are understanding. "
               "Sub-agent rows (sub_agent = yes) are looked up like any other row.")

#: how the thought and the result enter (codebook §8.5): (topic, what to do)
EVIDENCE_TEXT = [
    ("follow rows", "When the step's thought says what a follow row is for, and that purpose is "
                    "the work of another phase (\"set JAVA_HOME so the test can run\": "
                    "reproduction), write that phase and note \"thought\"."),
    ("category", "The result corrects the category only when it shows that the command did "
                 "something other than its program says (a Python script that runs the tests is "
                 "run_test). Write the right category in category_fix."),
    ("departures", "Every other row takes the phase of its table row. Depart from it only when "
                   "the thought and the result together show that the row does the work of "
                   "another phase; write that phase and note \"departure:\" with the evidence."),
    ("results", "Whether a run passed or failed (verdict, fail_kind) never changes a row's "
                "phase. It decides the outcome, which the tool computes."),
]

OUTCOME_ROWS = [    # Table 5: phase, check, succeeded, failed, blocked, unchecked
    ("planning", "a build of the untouched project (optional)", "it builds", "–",
     "the build was stopped", "no build (usual)"),
    ("localization", "reading a file the agent's own patch changes", "it read such a file",
     "it read none of them", "–", "the agent changed no app file"),
    ("reproduction", "a test or app run before the fix", "the test fails as reported",
     "the test passes", "the run stopped before the test ran", "no run gave a result"),
    ("repair", "the first build or test after its edits", "it passes, or the code compiles",
     "tests fail, or the change does not compile", "the environment stopped the run",
     "the change was never run"),
    ("validation", "builds and tests of the patch", "it passes, or the code compiles",
     "tests fail, or the change does not compile", "the environment stopped the run",
     "nothing was run"),
]
FLAG_TEXT = {       # Table 6
    "test_modified": "changes test code or the benchmark's test script",
    "environment_workaround": "changes build files, or changes environment settings and runs "
                              "again after a failure",
    "repeated_failure": "repeats a run that failed, the same way, with nothing changed in between",
    "repeated_reads": "reads one file three or more times",
    "manual_ui_check": "drives the app on a device (taps, screenshots): a check with no "
                       "automatic result",
}
CHANGE_KINDS = ["action lookup row", "new category", "file role", "phase lookup row",
                "phase definition", "new phase", "other"]


def _category_text() -> dict:
    """category -> (family, the action..., its tools and shell programs in one line): Tables
    2a and 2b folded together for the viewer's tooltips."""
    out = {}
    for cat, (family, does, claude, codex, qwen) in ACTION_TOOLS.items():
        tools = [f"{agent}: {names}" for agent, names in
                 (("Claude Code", claude), ("Codex", codex), ("Qwen Code", qwen)) if names != "–"]
        if cat in ACTION_SHELL:
            tools.append(f"shell: {ACTION_SHELL[cat]}")
        out[cat] = (family, does, "; ".join(tools) or "–")
    return out


CATEGORY_TEXT = _category_text()   # category -> (family, the action..., tools and programs)
