"""The codebook's lookup tables, word for word (Annotation Codebook.docx §8 and §10).

The .docx is the master: change it first, then these.  ``make_ground_truth.py`` writes them
into the annotators' reference tabs, and ``atif.view`` exports them to the viewer, so the
workbooks, the viewer and the codebook use the same words.
"""

PHASE_TEXT = {      # Table 1: phase -> (the agent is..., typical rows, where)
    "understanding": ("getting oriented before the work",
                      "the opening ls, pwd, plan and git status; reading README, AGENTS.md or build "
                      "files; building the untouched project to see whether it compiles; looking "
                      "into a library in the Gradle cache", "before the first fix only"),
    "localization": ("finding the code to change",
                     "searching and reading app or test code; git blame or show of code; a "
                     "sub-agent asked to find or read", "anywhere"),
    "reproduction": ("trying to see the bug before the fix",
                     "running the bug's test or driving the app on a device; the builds, "
                     "environment commands and test or build-file edits that get that run going",
                     "before the first fix only"),
    "repair": ("changing the app's code and checking each change",
               "editing app source, then building or running the test that judges the edit; "
               "short lookups between edits", "from the first fix on"),
    "validation": ("checking the patch outside an attempt",
                   "more builds and tests without a new edit; writing or editing tests; git diff "
                   "and re-reading its own changed files; cleanup", "after the first fix only"),
}
CATEGORY_TEXT = {   # Table 2: category -> (family, the action..., tools and shell programs)
    "read_file": ("inspect", "opens a file to read it",
                  "Read / – / read_file; cat, sed -n, head, tail, nl, less, javap"),
    "search_code": ("inspect", "searches for text or file names",
                    "Grep, Glob / – / grep_search, glob; rg, grep, find, fd, ag; a git command "
                    "chained with a read or search"),
    "orient": ("inspect", "looks around without reading a file",
               "LS; ls, pwd, tree, which, env, stat, wc"),
    "vcs": ("inspect", "inspects the git repository, changing nothing",
            "git status, log, show, blame, ls-files, rev-parse, remote"),
    "diff": ("inspect", "compares versions, usually its own changes", "git diff; diff, cmp"),
    "web": ("inspect", "fetches from the internet", "WebFetch, WebSearch / web_search / –; curl, wget"),
    "edit_file": ("modify", "changes a file with an editor tool or a patch",
                  "Edit, MultiEdit, Write / apply_patch / edit, write_file"),
    "shell_edit": ("modify", "changes a file with a plain shell command, or undoes changes",
                   "sed -i, perl -i, echo or cat > file, a Python script that writes a file, "
                   "git apply, patch; git checkout, restore, stash, reset, clean"),
    "build": ("execute", "compiles without running tests",
              "./gradlew assembleDebug or any non-test task; mvn, ant, make, javac"),
    "run_test": ("execute", "runs tests or the benchmark's check",
                 "./gradlew test…, check, connected…AndroidTest; adb … instrument; run_pipeline.sh"),
    "device_ops": ("execute", "drives a device or emulator",
                   "adb install, adb shell input / screencap / uiautomator, emulator"),
    "run_shell": ("execute", "runs any other program", "python3 script.py, java -jar, other programs"),
    "env_setup": ("configure", "changes the machine or toolchain, not the project",
                  "chmod, rm, cp, mv, unzip, tar, sdkmanager, java_home, brew, pip; a command made "
                  "only of cd, export, mkdir; a write to a file outside the project"),
    "plan": ("coordinate", "records or updates a plan",
             "TodoWrite, plan mode / update_plan / update_goal, get_goal"),
    "delegate": ("coordinate", "hands work to a sub-agent", "Agent, Task / – / agent"),
    "wait_process": ("coordinate", "waits for or stops a process or sub-agent",
                     "TaskOutput, TaskStop, Monitor / write_stdin / list_agents, send_message, "
                     "task_stop; sleep, kill, ps"),
    "other": ("other", "anything else",
              "AskUserQuestion, Skill, ToolSearch / view_image / tool_search, skill, "
              "record_artifact; unknown tools"),
}
RULES = [           # Table 4
    ("G1", "Mark the first fix",
     "Find the first row that changes app source (edit_file or shell_edit with file role "
     "source). fix_stage shows it. Understanding and reproduction happen only before it; repair "
     "and validation only from it on; localization anywhere."),
    ("G2", "Give each row its phase",
     "Use Table 5 (codebook §8.4): the row's category and file role, and whether it comes before "
     "or after the first fix."),
    ("G3", "Preparation goes with the run it prepares",
     "A build, environment command, build-file or harness edit, harness or log read, or look "
     "into a toolchain location takes the phase of the next test or device run in the same "
     "stretch of execution work. With no such run: understanding before the first fix, "
     "validation after."),
    ("G4", "An attempt keeps its judging run",
     "From an app-source edit to the first run that judges it (a test with a result, or a "
     "failing build), the rows are repair, including builds, git diff and test or build-file "
     "edits in between. A passing build judges the attempt only if the agent edits again before "
     "any test. Lookups inside an attempt keep localization: a single lookup row joins repair "
     "again (G7), and two or more lookup rows form a localization stretch."),
    ("G5", "Neutral rows follow the work around them",
     "ls, pwd, a plan update, git status or log, web, reading docs or build files: the row takes "
     "the phase of the row before it. At the start of the trajectory these rows are "
     "understanding."),
    ("G6", "A delegation is one block",
     "A delegate row and all its sub_agent = yes rows take one phase: repair if the sub-agent "
     "changes app source or is asked to, else localization. A wait takes the phase of the run it "
     "waits for."),
    ("G7", "A single row does not start a phase",
     "One row between two stretches of the same phase joins them, unless it is a repair row or "
     "contains a test result or a failed build. Two or more rows always keep their own phase, "
     "however short the stretch."),
    ("G8", "Ask the question behind the rules",
     "Would someone describing the agent's work say it left the phase here? G7 decides by size: "
     "one row joins the stretch around it, two or more rows start their own. If you depart from "
     "it, say why in notes."),
]
OUTCOME_ROWS = [    # Table 6: phase, check, succeeded, failed, blocked, unchecked
    ("understanding", "a build of the untouched project (optional)", "it builds", "–",
     "the build was stopped", "no build (usual)"),
    ("localization", "reading a file the agent's own patch changes", "it read such a file",
     "it read none of them", "–", "the agent changed no app file"),
    ("reproduction", "a test or app run before the fix", "the test fails as reported",
     "the test passes", "the run stopped before the test ran", "no run gave a result"),
    ("repair", "the run that judges an attempt", "it passes, or the code compiles",
     "tests fail, or the change does not compile", "the environment stopped the run",
     "the change was never run"),
    ("validation", "more runs on the patch", "it passes, or the code compiles",
     "tests fail, or the change does not compile", "the environment stopped the run",
     "nothing was run"),
]
FLAG_TEXT = {       # Table 7
    "test_modified": "changes test code or the benchmark's test script",
    "environment_workaround": "changes build files, or changes environment settings and runs "
                              "again after a failure",
    "repeated_failure": "repeats a run that failed, the same way, with nothing changed in between",
    "repeated_reads": "reads one file three or more times",
    "manual_ui_check": "drives the app on a device (taps, screenshots): a check with no "
                       "automatic result",
}
CHANGE_KINDS = ["new category", "category definition", "new phase", "phase definition",
                "new grouping rule", "grouping rule change", "lookup table row", "other"]
