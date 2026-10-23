"""The Final lookup tables: a tool call -> an action category, a file -> a target, and the
category, the target and the position -> a phase.

The tables are the tab "Final lookup table" of the annotation workbook
(``Ground Truth/annotation_workbook.xlsx``).  Two authors drafted them on the pilot (T01, T03,
T05); they were then expanded on the 339 development trajectories (2026-10-17), and the tab
"Lookup justification" gives two development steps for every entry it added or changed.  The
texts in the first section are the workbook's, word for word; the code after them applies them,
and nothing else decides a category or a phase.  Nothing is fitted.

action table   a tool call -> one of CATEGORIES.  A native tool gives its category directly; a
               shell runner's command line is split into simple commands, each looked up in
               the Shell Commands column (programs of the "(ignored)" row are skipped), and the
               line takes the highest category on it (``ORDER``).
target table   a file -> one of TARGETS (``target``).
phase table    rows 1-15 (``PHASE_TABLE``), tried in order; the first that matches the action's
               category, its target files and its position (before, at or after the first edit
               of a source file; at the start of the trajectory) gives the phase, or says that
               the step takes the phase of the previous step.  No row matching: the general
               rule (``GENERAL_RULE``), the phase of the previous step.  ``atif.phase``
               resolves "previous" and builds the phases' outcomes on top.

Beyond the tables, for logs the corpus does not have (each is said where it applies):

* the shell tools of other agents (``taxonomy.SHELL_TOOLS``: OpenHands' ``execute_bash``,
  mini-swe-agent's ``bash``) are shell runners, like Bash;
* a tool the table does not name, and that the corpus agents never called, gets the
  category of what it does in the taxonomy's tool vocabulary (Claude Code's ``Grep`` is
  search, OpenHands' ``str_replace_editor`` edit or read); a tool nobody knows, and the four
  the corpus agents called that the table leaves out (``TABLE_OTHER_TOOLS``), are other, the
  table's "any other tool";
* in a SWE-bench project (``atif.project``), whose tests are Python's, a program the Android
  table sends to other (``python3 <any other script>``, "any other program") takes the
  category of what the taxonomy says it does (``pytest``, ``python -m pytest``: test), and the
  targets follow the project's file roles.
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import project, taxonomy

VERSION = "Final lookup table"
VERSION_DATE = "2026-10-17"

# --------------------------------------------------------------------------- #
# The tables, word for word

#: the action categories, in the order of the action table
CATEGORIES = ("search", "read", "orient", "edit", "build", "test", "diff", "vcs", "plan",
              "sub-agent", "other")
#: Action to Action Category Mapping Table: (category, shell commands, native tools)
ACTION_TABLE = [
    ("search", "find, grep, rg; jar tf, unzip -l", "grep_search (Qwen), glob (Qwen)"),
    ("read", "sed -n, nl -ba, cat <file>; head <file>, tail <file>, awk <file>; javap; "
             "unzip -p; aapt2 dump", "Read (Claude), read_file (Qwen)"),
    ("orient", "pwd, ls; which, wc, stat, file, du, readlink; /usr/libexec/java_home; "
               "java -version, javac -version; gradlew tasks, gradle --version", ""),
    ("edit", "apply_patch; printf ... >> file, cat > file <<EOF; sed -i, perl -i, "
             "patch -p1 < file; cp, mv onto a repository file; rm of a repository file; "
             "git checkout, git restore, git reset, git stash; python3 script that writes a "
             "repository file",
     "Edit (Claude), Write (Claude), edit (Qwen), write_file (Qwen)"),
    ("build", "gradlew, gradle <any other task>; javac (without java); aapt2 compile, "
              "aapt2 link, aapt package, jar cf", ""),
    ("test", "javac + java, xmllint; java <class>, jshell; gradlew test tasks (test…, "
             "…UnitTest, checkstyle, lint); adb; patch --dry-run, git apply --check", ""),
    ("diff", "git diff, git status, diff -u; cmp", ""),
    ("vcs", "git log, git show, git ls-files, git check-ignore, git rev-parse, git branch, "
            "git stash list; git ls-tree, git remote, git blame, git config, git tag, "
            "git add, git commit, git init, git cat-file, git hash-object, git check-attr, "
            "git update-index; any other git subcommand", ""),
    ("plan", "", "update_plan (Codex)"),
    ("sub-agent", "", "agent (Qwen), Agent (Claude)"),
    ("other", "curl, ping; git clone, git ls-remote; sleep, pkill, ps, pgrep; sdkmanager; "
              "python3 <any other script>; a line made only of ignored programs; any other "
              "program",
     "write_stdin (Codex); list_agents, send_message, task_stop, tool_call, tool_search "
     "(Qwen); Edit, Write, edit, write_file on a file outside the repository (/tmp); any "
     "other tool"),
]
#: the three rows of the action table that are not categories
SHELL_RUNNER_ROW = ("(shell runner)", "Bash (Claude), exec_command (Codex), "
                                      "run_shell_command (Qwen)")
IGNORED_ROW = ("(ignored)", "cd, echo, printf, sort, xxd; head, tail without a file; "
                            "VAR=$(...) ; any program after a pipe |; mkdir (anywhere); rm and "
                            "cat > on files outside the repository (/tmp); export, set, true, "
                            "exit, :, mktemp, seq, basename, dirname, shasum, strings; test, "
                            "[ ], for, if, case, while; shell function definitions; chmod, ln; "
                            "cp, mv, unzip, printf >, sed -i, perl -i, patch on files outside "
                            "the repository")
COMPOUND_ROW = ("(several programs on one line)", "Take the highest category on the line: "
                "edit > build > test > search > read > diff > vcs > orient > other")
#: the highest category of a line wins (``COMPOUND_ROW``)
ORDER = ("edit", "build", "test", "search", "read", "diff", "vcs", "orient", "other")

#: the phases, in the viewer's order (the workbook's names, lower case).  Reproduction was
#: dropped on 2026-10-19: rows L6 and L7 (a test run, or an edit of a test file, before the
#: first fix) are Localization
PHASES = ("planning", "localization", "repair", "validation")
PREVIOUS = "(previous step's phase)"
#: Action Category to Phases Mapping Table: (id, phase or PREVIOUS, action category,
#: target file, position/rules); the first row that matches counts
PHASE_TABLE = [
    ("L1", "planning", "plan", "any", "Anywhere"),
    ("L2", "planning", "orient, other, vcs, diff", "any",
     "At the start of the trajectory (no earlier step has a phase)"),
    ("L3", "planning", "read, search", "docs only", "Before the first edit of a source file"),
    ("L4", "planning", "build", "any", "Before the first edit of a source file"),
    ("L5", "localization", "search, read, sub-agent", "any (not docs only)",
     "Before the first edit of a source file"),
    ("L6", "localization", "test", "any", "Before the first edit of a source file"),
    ("L7", "localization", "edit", "test file", "Before the first edit of a source file"),
    ("L8", "repair", "edit", "source file", "Anywhere"),
    ("L9", "localization", "search, read", "source file the agent has not changed",
     "After the first edit of a source file, when the next edit of a source file comes before "
     "the next build, test or diff"),
    ("L10", "validation", "search, read", "source file the agent has not changed",
     "After the first edit of a source file, when a build, test or diff (or the end of the "
     "trajectory) comes before the next edit of a source file"),
    ("L11", "validation", "search, read",
     "file the agent has changed, or a file that is not a source file",
     "After the first edit of a source file"),
    ("L12", "validation", "build, test, diff, vcs", "any", "After the first edit of a source file"),
    ("L13", "validation", "edit", "any file in the repository that is not a source file",
     "After the first edit of a source file"),
    ("L14", PREVIOUS, "orient, other", "any", "Anywhere after the start"),
    ("L15", PREVIOUS, "vcs, diff", "any", "Before the first edit of a source file, after the "
                                           "start"),
]
GENERAL = "LG"
GENERAL_RULE = ("If an action category cannot be mapped to a specific phase, it should be "
                "assigned to the phase of the previous step.")
#: the phase of a step that has no previous step to take it from (the general rule at the
#: very first action: an edit of a build file, say); the phase table's start row says Planning
START_PHASE = "planning"

#: the targets, in the order of the File to Target File Mapping Table
TARGETS = ("source", "test", "docs", "build", "other", "outside")
#: File to Target File Mapping Table: (target, its name in the table, files)
TARGET_TABLE = [
    ("source", "source file", "the app's code and resources inside the repository: everything "
     "under a module's src/ or res/ folder and AndroidManifest.xml, except test files (also "
     "the same path under a wrong root, e.g. /home/user/app/src/main/...)"),
    ("test", "test file", "src/test/, src/androidTest/, files named *Test.java or *Tests.java"),
    ("docs", "docs", "README, AGENTS.md, CLAUDE.md, CHANGELOG, LICENSE, *.md and *.txt outside "
                     "src/"),
    ("build", "build file", "*.gradle, *.kts, *.properties (gradle.properties, "
                            "local.properties), gradlew, proguard rules"),
    ("other", "other repository file", "patch files (*.patch, *.diff), screenshots and logs, "
     "build/ outputs, the agent's own folders (.verify/, .sim/, .test-home/), programs at the "
     "repository root (Sim.java), HARNESS"),
    ("outside", "outside the repository", "/tmp, ~/.gradle caches, the Android SDK, the JDK"),
]
TARGET_NAME = {t: name for t, name, _ in TARGET_TABLE}

#: what each category is, in a few words, for the viewer's legends and tooltips
CATEGORY_TEXT = {
    "search": "looks for files or for text in files",
    "read": "prints a file, or part of one",
    "orient": "looks around without reading a file's content",
    "edit": "changes a file in the repository, or puts one back",
    "build": "compiles without running anything",
    "test": "runs tests, a program or the app to see how the code behaves",
    "diff": "compares versions: the agent's changes",
    "vcs": "inspects the git repository, changing no file",
    "plan": "records or updates a plan",
    "sub-agent": "hands work to a sub-agent",
    "other": "anything else: waiting, the web, a script, a coordination tool",
}
#: the family of each category, for grouping in the viewer (not part of the tables)
CATEGORY_FAMILY = {"search": "inspect", "read": "inspect", "orient": "inspect",
                   "diff": "inspect", "vcs": "inspect", "edit": "modify", "build": "execute",
                   "test": "execute", "plan": "coordinate", "sub-agent": "coordinate",
                   "other": "other"}
#: what each phase is, for the viewer (the phase table read by phase)
PHASE_TEXT = {
    "planning": ("getting ready: the plan, the task, the docs and the untouched project",
                 "a plan anywhere; the opening steps (ls, pwd, git status); reading only docs, "
                 "or building, before the first edit of a source file",
                 "before the first edit of a source file, and a plan anywhere"),
    "localization": ("finding the code to change",
                     "searching and reading code (a sub-agent too), running tests or writing a "
                     "test before the first edit of a source file; after it, reading a source "
                     "file it has not changed when it changes code again before the next build, "
                     "test or diff", "anywhere"),
    "repair": ("changing the app's code", "every edit of a source file",
               "from the first edit of a source file on"),
    "validation": ("checking the patch",
                   "every build, test, diff and git command after the first edit of a source "
                   "file; re-reading the files it changed, or other files; reading code it did "
                   "not change before a build, test or diff; editing a file that is not a "
                   "source file", "after the first edit of a source file only"),
}

# --------------------------------------------------------------------------- #
# Native tools (the Native tools column)

#: tool -> (category, the table's item)
NATIVE: Dict[str, Tuple[str, str]] = {
    "grep_search": ("search", "grep_search (Qwen)"), "glob": ("search", "glob (Qwen)"),
    "Read": ("read", "Read (Claude)"), "read_file": ("read", "read_file (Qwen)"),
    "Edit": ("edit", "Edit (Claude)"), "Write": ("edit", "Write (Claude)"),
    "edit": ("edit", "edit (Qwen)"), "write_file": ("edit", "write_file (Qwen)"),
    "update_plan": ("plan", "update_plan (Codex)"),
    "agent": ("sub-agent", "agent (Qwen)"), "Agent": ("sub-agent", "Agent (Claude)"),
    "write_stdin": ("other", "write_stdin (Codex)"),
    "list_agents": ("other", "list_agents (Qwen)"),
    "send_message": ("other", "send_message (Qwen)"),
    "task_stop": ("other", "task_stop (Qwen)"),
    "tool_call": ("other", "tool_call (Qwen)"),
    "tool_search": ("other", "tool_search (Qwen)"),
}
#: the tools the corpus agents called that the table does not name: "any other tool", so
#: other, not what the taxonomy says they do (``update_goal`` records the goal's status)
TABLE_OTHER_TOOLS = {"update_goal", "get_goal", "record_artifact", "run_shell"}
#: the native edit tools: on a file outside the repository they are other
EDIT_TOOLS = {"Edit", "Write", "edit", "write_file"}
#: argument keys naming a native tool's file, in lookup order
PATH_KEYS = ("file_path", "absolute_path", "path")
#: the taxonomy's kind of a tool or program the table does not name -> its category
KIND_CATEGORY = {"read_file": "read", "search_code": "search", "orient": "orient",
                 "vcs": "vcs", "diff": "diff", "web": "other", "edit_file": "edit",
                 "shell_edit": "edit", "build": "build", "run_test": "test",
                 "device_ops": "test", "run_shell": "other", "env_setup": "other",
                 "plan": "plan", "delegate": "sub-agent", "wait_process": "other",
                 "other": "other"}
#: a category set by a row of the user's -> (the taxonomy kind, the mid-level the verdict
#: parser reads), so that a run counted as test gets a test verdict
CATEGORY_KIND = {"search": ("search_code", "search_code"), "read": ("read_file", "read_file"),
                 "orient": ("orient", "orient"), "edit": ("edit_file", "edit_file"),
                 "build": ("build", "build"), "test": ("run_test", "run_test"),
                 "diff": ("diff", "vcs"), "vcs": ("vcs", "vcs"), "plan": ("plan", "plan"),
                 "sub-agent": ("delegate", "delegate"), "other": ("other", "other")}

# --------------------------------------------------------------------------- #
# Shell command lines: simple commands

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_KEYWORDS = {"do", "then", "else", "elif", "{", "}", "!", "done", "fi", "esac", "time"}
_WRAPPERS = {"sudo", "nohup", "env", "command", "builtin", "exec", "stdbuf", "nice"}
_REDIRECT = re.compile(r"(?<![<>&\d])(\d?)(>>|>)(?!&)\s*(\S+)")
_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")


def _strip_heredocs(cmd: str) -> Tuple[str, List[str]]:
    """(the command line without its heredoc bodies, the bodies)."""
    out, bodies, lines, i = [], [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        ends = [m.group(2) for m in _HEREDOC.finditer(line)]
        i += 1
        for end in ends:
            body = []
            while i < len(lines) and lines[i].strip() != end:
                body.append(lines[i])
                i += 1
            bodies.append("\n".join(body))
            i += 1
    return "\n".join(out), bodies


def _segments(cmd: str) -> List[Tuple[str, bool]]:
    """Split at unquoted ``; && || | & ( ) $( `` and line breaks: (text, after a pipe)."""
    segs: List[Tuple[str, bool]] = []
    buf: List[str] = []
    quote: Optional[str] = None
    state = {"after_pipe": False}

    def flush(next_after_pipe: bool) -> None:
        text = "".join(buf).strip()
        if text:
            segs.append((text, state["after_pipe"]))
        buf.clear()
        state["after_pipe"] = next_after_pipe

    i = 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(cmd):
                buf.append(cmd[i:i + 2])
                i += 2
                continue
            if c == quote:
                quote = None
            buf.append(c)
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < len(cmd):
            buf.append(" " if cmd[i + 1] == "\n" else cmd[i:i + 2])
            i += 2
            continue
        two = cmd[i:i + 2]
        if two in ("&&", "||", "$("):
            flush(False)
            i += 2
            continue
        if c == "|":
            flush(True)
            i += 1
            continue
        if c in ";\n()`":
            flush(False)
            i += 1
            continue
        if c == "&" and not (i > 0 and cmd[i - 1] in "<>") and cmd[i + 1:i + 2] != ">":
            flush(False)
            i += 1
            continue
        if c == "#" and (not buf or buf[-1] in " \t"):          # a comment, to the line end
            j = cmd.find("\n", i)
            i = len(cmd) if j < 0 else j
            continue
        buf.append(c)
        i += 1
    flush(False)
    return segs


def simple_commands(cmd: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The simple commands of a command line (``prog``: the program's base name, ``args``,
    ``after_pipe``, ``writes``: the files it redirects into, ``text``) and its heredoc
    bodies.  Leading keywords, assignments and wrappers (``sudo``, ``timeout 60``,
    ``xargs -I{}``) are looked through."""
    body, heredocs = _strip_heredocs(cmd)
    out: List[Dict[str, Any]] = []
    for text, after_pipe in _segments(body):
        unquoted = _QUOTED.sub(" Q ", text)
        writes = [m.group(3).strip("\"'") for m in _REDIRECT.finditer(unquoted)
                  if m.group(3) not in ("/dev/null", "&1", "&2", "Q")]
        writes += [q.strip("\"'") for q in re.findall(
            r"(?<![<>&\d])\d?>>?\s*(\"[^\"]+\"|'[^']+')", text)]
        held: List[str] = []

        def hold(m: "re.Match[str]") -> str:
            held.append(m.group(0))
            return f"\x00{len(held) - 1}\x00"
        clean = _QUOTED.sub(hold, text)
        clean = _REDIRECT.sub(" ", clean)
        clean = re.sub(r"\d?<<-?\s*\S+", " ", clean)
        clean = re.sub(r"\d?<\s*\S+", " ", clean)
        clean = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], clean)
        try:
            toks = shlex.split(clean, posix=True)
        except ValueError:
            toks = clean.split()
        while toks:
            t = toks[0]
            if t in _KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
                toks = toks[1:]
                continue
            if t in _WRAPPERS:
                toks = toks[1:]
                while toks and (toks[0].startswith("-") or re.match(r"^[A-Za-z_]\w*=", toks[0])):
                    toks = toks[1:]
                continue
            if t == "timeout":
                toks = toks[1:]
                while toks and (toks[0].startswith("-") or re.match(r"^\d+[smh]?$", toks[0])):
                    toks = toks[1:]
                continue
            if t == "xargs":
                toks = toks[1:]
                while toks and toks[0].startswith("-"):
                    opt = toks[0]
                    toks = toks[1:]
                    if opt in ("-I", "-n", "-P", "-d", "-L", "-E") and toks:
                        toks = toks[1:]
                continue
            break
        if not toks:
            continue
        out.append({"prog": toks[0].rsplit("/", 1)[-1], "path": toks[0], "args": toks[1:],
                    "after_pipe": after_pipe, "writes": writes, "text": text})
    return out, heredocs


# --------------------------------------------------------------------------- #
# Inside or outside the repository

#: a path through the checkout: ``.../bug-<id>`` (the run folders of every agent are named so)
_CHECKOUT = re.compile(r"/bug-\d+(?=/|$)")
#: the app's own tree under a wrong root (``/home/user/app/src/main/...``)
_APP_TREE = re.compile(r"/src/(main|test|androidTest)/")
_SCRATCH_ROOT = re.compile(r"^(/tmp|/private/tmp|/var/folders)")


def _checkout_end(path: str) -> Optional[int]:
    """Where the checkout part of an absolute path ends, or None when it names none: the
    folder the run was started in (``project.Project.checkout``); a log that names none, a
    ``bug-<id>`` folder outside /tmp; a SWE-bench project, a repository root."""
    proj = project.current()
    if proj.swebench:
        for root in proj.roots:
            if path == root or path.startswith(root + "/"):
                return len(root)
        return None
    if proj.checkout:              # the folder the run was started in
        inside = path == proj.checkout or path.startswith(proj.checkout + "/")
        return len(proj.checkout) if inside else None
    if _SCRATCH_ROOT.match(path):
        return None                # a copy of the checkout in /tmp is outside the repository
    m = _CHECKOUT.search(path)
    return m.end() if m else None


def in_repo(path: str, cwd_in_repo: bool = True) -> bool:
    """Whether a path names a file inside the repository under repair: a path through the
    checkout, the app's own tree under a wrong root, or a relative path while the command
    runs in the checkout."""
    if not path:
        return False
    p = path.strip("\"'")
    if _checkout_end(p) is not None:
        return True
    if not project.current().swebench and p.startswith("/") and _APP_TREE.search(p) \
            and not _SCRATCH_ROOT.match(p) and "/caches/" not in p:
        return True
    if p.startswith(("/", "~", "$")):
        return False
    return cwd_in_repo


def repo_rel(path: str) -> str:
    """A path relative to the repository when it lies inside it, else the path."""
    p = path.strip("\"'")
    end = _checkout_end(p)
    if end is not None:
        return p[end:].lstrip("/")
    m = re.search(r"/((?:[\w.-]+/)?src/(?:main|test|androidTest)/.*)$", p)
    if m and p.startswith("/") and in_repo(p):
        return m.group(1)
    return p[2:] if p.startswith("./") else p


# --------------------------------------------------------------------------- #
# The target table

_TEST = re.compile(r"(^|/)(src/(test|androidTest)\w*/|test/|tests/|androidTest/)"
                   r"|Tests?\.(java|kt)$")
_BUILD = re.compile(r"(\.gradle|\.kts|\.properties|(^|/)gradlew(\.bat)?|\.pro|proguard[^/]*|"
                    r"gradle-wrapper\.jar|\.toml|\.java-version)$")
_DOCS = re.compile(r"(^|/)(README|LICENSE|CHANGELOG|CONTRIBUT\w*|NOTICE|AUTHORS|AGENTS)[^/]*$|"
                   r"\.(md|rst|txt|adoc)$", re.I)
_OUTPUT = re.compile(r"\.(png|jpe?g|webp|gif|log)$|(^|/)build/|(^|/)\.verify/|_output\.txt$",
                     re.I)
_PATCH = re.compile(r"\.(patch|diff)$|(^|/)HARNESS$")
_SOURCE_EXT = re.compile(r"\.(java|kt|xml|json|aidl|svg|html|js|css)$|(^|/)src/|(^|/)res/")
#: a SWE-bench file role (``project.swebench_role``) -> its target
_SWEBENCH_TARGET = {"source": "source", "test": "test", "toolchain": "build"}


def target(path: str) -> str:
    """The target of a file (TARGETS), or "" for no path."""
    p = (path or "").strip("\"'")
    if not p:
        return ""
    if not in_repo(p, True):
        return "outside"
    rel = repo_rel(p)
    if _OUTPUT.search(rel) or _PATCH.search(rel):
        return "other"
    if _DOCS.search(rel) and not re.search(r"(^|/)src/", rel):
        return "docs"
    proj = project.current()
    if proj.swebench:
        return _SWEBENCH_TARGET[project.swebench_role(rel, proj)]
    if _BUILD.search(rel):
        return "build"
    if re.search(r"(^|/)\.[^/.][^/]*/", rel):
        return "other"             # the agent's own hidden folders (.sim/, .verify/, .git/)
    if _TEST.search(rel):
        return "test"
    if re.search(r"(^|/)(src|res)/|AndroidManifest\.xml$", rel) or rel in ("", ".", "app", "src"):
        return "source"
    if "/" in rel and _SOURCE_EXT.search(rel):
        return "source"
    if "/" not in rel and re.search(r"\.(java|kt)$", rel):
        return "other"             # a scratch program at the repository root (Sim.java)
    if "/" in rel:
        return "source"
    return "other"


# --------------------------------------------------------------------------- #
# The action table: shell programs

_GIT_DIFF = {"diff": "git diff", "status": "git status", "diff-files": "git diff",
             "diff-index": "git diff"}
_GIT_UNDO = {"checkout", "restore", "reset", "stash", "apply", "revert", "clean"}
_GIT_VCS = {"log", "show", "ls-files", "check-ignore", "rev-parse", "branch", "ls-tree",
            "remote", "blame", "config", "tag", "add", "commit", "init", "cat-file",
            "hash-object", "check-attr", "update-index"}
_TEST_TASK = re.compile(r"(^|:)(test\w*|connected\w*AndroidTest|check|checkstyle|lint\w*|"
                        r"\w*UnitTest)$", re.I)
_INFO_TASK = re.compile(r"(^|:)tasks$")
_ORIENT = {"pwd", "ls", "which", "wc", "stat", "file", "du", "readlink", "java_home"}
_OTHER = {"sleep", "pkill", "pgrep", "ps", "curl", "ping", "sdkmanager"}
_IGNORED = {"cd", "echo", "printf", "true", "false", ":", "set", "exit", "export", "unset",
            "source", ".", "mktemp", "seq", "for", "while", "if", "case", "until", "local",
            "return", "break", "continue", "shift", "declare", "trap", "read", "test", "[",
            "[[", "tr", "sort", "uniq", "cut", "xxd", "od", "paste", "jq", "md5",
            "md5sum", "shasum", "strings", "column", "fold", "rev", "xargs", "eval", "env",
            "basename", "dirname", "{", "}", "do", "done", "then", "fi", "else"}
_GRADLE_VALUE_OPTIONS = {"--tests", "-p", "--project-dir", "-x", "--exclude-task", "-I",
                         "--init-script", "-b", "--build-file", "-c", "--settings-file",
                         "--console", "-g", "--gradle-user-home"}
#: a shell item: (category or None for an ignored program, the table's item, target paths)
Item = Tuple[Optional[str], str, List[str]]


def _paths(args: List[str]) -> List[str]:
    return [a for a in args if not a.startswith("-") and not a.startswith(("s/", "s|", "s#"))
            and ("/" in a or re.search(r"\.\w{1,6}$", a))]


def _git_sub(args: List[str]) -> Tuple[str, List[str]]:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return (args[i] if i < len(args) else ""), args[i + 1:]


def _python_writes_repo(body: str, cwd_in: bool) -> bool:
    for m in re.finditer(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]", body):
        if in_repo(m.group(1), cwd_in):
            return True
    if re.search(r"open\(\s*(p|path|f|fn|P)\s*,\s*['\"][wa]", body) or ".write_text(" in body:
        for m in re.finditer(r"""(?:^|\s)(?:p|path|f|fn|P)\s*=\s*(?:pathlib\.)?(?:Path\()?"""
                             r"""['"]([^'"]+)['"]""", body, re.M):
            if in_repo(m.group(1), cwd_in):
                return True
    return False


def _gradle(args: List[str]) -> Item:
    tasks, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in _GRADLE_VALUE_OPTIONS:
            skip = True
            continue
        if a.startswith("-") or a.startswith("2>") or "=" in a or "." in a or "*" in a:
            continue
        tasks.append(a)
    if any(_TEST_TASK.search(t) for t in tasks):
        return ("test", "gradlew test tasks", [])
    if (tasks and all(_INFO_TASK.search(t) for t in tasks)) \
            or (not tasks and any(a in ("--version", "-v") for a in args)):
        return ("orient", "gradlew tasks, gradle --version", [])
    return ("build", "gradlew, gradle <any other task>", [])


def _swebench_item(c: Dict[str, Any], item: Item) -> Item:
    """A SWE-bench project: a program the Android table sends to other takes the category of
    what the taxonomy says it does (``pytest``: test)."""
    if item[0] != "other" or item[1] not in ("python3 <any other script>", "any other program"):
        return item
    kind = taxonomy._program_kind(c["text"])
    category = KIND_CATEGORY.get(kind, "other")
    return item if category == "other" else (category, f"{c['prog']} (a SWE-bench project)",
                                             [])


def shell_items(line: str) -> List[Item]:
    """The table's item for every simple command of a command line, in order."""
    cmds, heredocs = simple_commands(line)
    patch_files = re.findall(r"\*\*\* (?:Update|Add|Delete) File: (\S+)", line)
    functions = set(re.findall(r"(?:^|[\s;{])([A-Za-z_]\w*)\s*\(\)\s*\{", line))
    found: List[Item] = []
    cwd_in = True
    variables: Dict[str, str] = {}
    java_runs = any(c["prog"] in ("java", "jshell") and not any(
        a in ("-version", "--version") for a in c["args"]) for c in cmds)
    swebench = project.current().swebench
    for c in cmds:
        item = _item(c, cmds, heredocs, patch_files, functions, variables, java_runs, cwd_in)
        if c["prog"] == "cd" and item[1] == "IGN-cd":
            cwd_in = item[2][0] if item[2] else cwd_in
            item = (None, "IGN-cd", [])
        if isinstance(item, list):              # ``sh -c '<script>'``
            found.extend(item)
            continue
        found.append(_swebench_item(c, item) if swebench else item)
    return found


def _item(c: Dict[str, Any], cmds, heredocs, patch_files, functions, variables, java_runs,
          cwd_in) -> Any:
    """One simple command's item.  ``cd`` returns ("IGN-cd" with [cwd_in after it])."""
    prog, args, text = c["prog"], c["args"], c["text"]
    for m in re.finditer(r"(?:^|\s)([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|\S+)", text):
        variables[m.group(1)] = m.group(2).strip("\"'")
    if prog.startswith("$"):
        name = prog.strip("${}")
        value = variables.get(name, "")
        if name.upper() == "ADB" or value.endswith("/adb"):
            prog = "adb"
        elif name.upper().startswith("AAPT") or "aapt" in value:
            prog = "aapt2"
        else:
            return (None, "IGN-var", [])
    if prog in functions or prog.endswith("()"):
        return (None, "IGN-function", [])
    if c["after_pipe"] and prog not in ("apply_patch", "patch", "javac", "java"):
        return (None, "IGN-pipe:" + prog, [])      # | head, | grep filter the output
    if prog == "cd":
        dest = args[0] if args else "~"
        dest = re.sub(r"\$\{?(\w+)\}?", lambda m: variables.get(m.group(1), m.group(0)), dest)
        if dest in ("$(pwd)", "-"):
            return (None, "IGN-cd", [cwd_in])
        if dest.startswith(("/", "~", "$")):
            return (None, "IGN-cd", [_checkout_end(dest) is not None])
        return (None, "IGN-cd", [cwd_in])
    writes = c["writes"]
    # writes by redirection
    if writes and prog in ("echo", "printf", "cat", "tee"):
        inside = [w for w in writes if in_repo(w, cwd_in)]
        if inside:
            label = "printf ... >> file" if prog in ("printf", "echo") else "cat > file <<EOF"
            return ("edit", label, inside)
        return (None, "IGN-scratch:" + prog + " >", writes)
    if prog == "tee":
        inside = [a for a in args if not a.startswith("-") and in_repo(a, cwd_in)]
        return ("edit", "cat > file <<EOF", inside) if inside else (None, "IGN-scratch:tee", [])
    # git
    if prog == "git":
        sub, rest = _git_sub(args)
        if sub in _GIT_DIFF:
            return ("diff", _GIT_DIFF[sub], [])
        if sub == "grep":
            return ("search", "git grep", [])
        if sub == "stash" and (not rest or rest[0] in ("list", "show")):
            return ("vcs", "git stash list", [])
        if sub == "apply" and any(a in ("--check", "--stat", "--numstat") for a in rest):
            return ("test", "patch --dry-run, git apply --check", [])
        if sub in _GIT_UNDO:
            files = [a for a in rest if not a.startswith("-")
                     and a not in ("HEAD", "--", "push", "pop")]
            return ("edit", "git checkout, git restore, git reset, git stash", files)
        if sub in ("clone", "ls-remote", "fetch"):
            return ("other", "git clone, git ls-remote", [])
        if sub in _GIT_VCS:
            return ("vcs", "git " + sub, _paths(rest))
        return ("vcs", "any other git subcommand", [])
    # edits
    if prog == "apply_patch":
        return ("edit", "apply_patch", patch_files)
    if prog in ("sed", "perl") and any(re.match(r"^-\w*i", a) or a.startswith("--in-place")
                                       for a in args):
        files = [f for f in _paths(args) if not re.match(r"^'?s[/|#]", f)]
        inside = [f for f in files if in_repo(f, cwd_in)]
        return ("edit", prog + " -i", inside) if inside \
            else (None, "IGN-scratch:" + prog + " -i", files)
    if prog == "patch":
        files = [a for a in args if not a.startswith("-")]
        if any(a in ("--dry-run", "--check") for a in args):
            return ("test", "patch --dry-run, git apply --check", [])
        if files and not in_repo(files[0], cwd_in):
            return (None, "IGN-scratch:patch", files)
        return ("edit", "patch", []) if cwd_in else (None, "IGN-scratch:patch", [])
    if prog in ("cp", "mv"):
        given = [a for a in args if not a.startswith("-")]
        dest = given[-1] if given else ""
        if len(given) >= 2 and in_repo(dest, cwd_in) and not dest.endswith("/") and dest != ".":
            return ("edit", "cp, mv onto a repository file", [dest])
        return (None, "IGN-scratch:" + prog, given)
    if prog in ("rm", "mkdir", "ln", "chmod"):
        given = [a for a in args if not a.startswith("-")]
        inside = [a for a in given if in_repo(a, cwd_in)]
        if prog == "rm" and inside:
            return ("edit", "rm of a repository file", inside)
        return (None, "IGN-scratch:" + prog, given)
    if prog == "python3":
        body = "\n".join(heredocs) + "\n" + text
        if _python_writes_repo(body, cwd_in):
            return ("edit", "python3 script that writes a repository file", [])
        return ("other", "python3 <any other script>", [])
    # build and test
    if prog in ("gradlew", "gradle"):
        return _gradle(args)
    if prog == "javac":
        if any(a in ("-version", "--version") for a in args):
            return ("orient", "java -version, javac -version", [])
        return ("test", "javac + java", []) if java_runs else ("build", "javac (without java)", [])
    if prog in ("java", "jshell"):
        if any(a in ("-version", "--version") for a in args):
            return ("orient", "java -version, javac -version", [])
        return ("test", "jshell" if prog == "jshell" else "java <class>", [])
    if prog == "xmllint":
        return ("test", "xmllint", [])
    if prog == "adb":
        return ("test", "adb", [])
    if prog in ("aapt", "aapt2", "jar"):
        if prog == "jar" and args and re.match(r"^-?t", args[0]):
            return ("search", "jar tf, unzip -l", [])
        if prog in ("aapt", "aapt2") and args and args[0] in ("dump", "d", "list", "l"):
            return ("read", "aapt2 dump", [])
        return ("build", "aapt2 compile, aapt2 link, aapt package, jar cf", [])
    if prog == "unzip":
        if any(re.match(r"^-[A-Za-z]*[lZv]", a) for a in args):
            return ("search", "jar tf, unzip -l", [])
        if any(re.match(r"^-[A-Za-z]*[pc]", a) for a in args):
            return ("read", "unzip -p", [])
        return (None, "IGN-scratch:unzip", [])
    # search, read, diff, orient
    if prog == "find":
        dirs = []
        for a in args:
            if a.startswith(("-", "(", "!", "\\")):
                break
            dirs.append(a)
        names = [args[i + 1] for i, a in enumerate(args[:-1])
                 if a in ("-name", "-iname", "-path", "-ipath", "-wholename")]
        docs = names and all(re.search(r"(README|AGENTS|CLAUDE|CHANGELOG|CONTRIBUT)|\.md$", n,
                                       re.I) for n in names)
        return ("search", "find", names if docs else (dirs or ["."]))
    if prog in ("grep", "rg"):
        given = _paths(args[1:]) if args else []
        if prog == "rg" and "--files" in args:
            given = _paths(args)
        return ("search", prog, given or ["."])
    if prog == "sed":
        return ("read", "sed -n", _paths(args))
    if prog == "nl":
        return ("read", "nl -ba", _paths(args))
    if prog == "cat":
        given = _paths(args)
        return ("read", "cat <file>", given) if given else (None, "IGN-cat", [])
    if prog in ("head", "tail"):
        given = [a for a in args if not a.startswith("-") and not re.match(r"^\+?\d+$", a)]
        return ("read", "head <file>, tail <file>, awk <file>", given) if given \
            else (None, "IGN-" + prog, [])
    if prog == "awk":
        given = [a for a in args[1:] if not a.startswith("-") and re.search(r"[/.]", a)]
        return ("read", "head <file>, tail <file>, awk <file>", given) if given \
            else (None, "IGN-" + prog, [])
    if prog == "javap":
        return ("read", "javap", [])
    if prog in ("diff", "cmp"):
        return ("diff", "cmp" if prog == "cmp" else "diff -u", [])
    if prog in _ORIENT:
        return ("orient", "/usr/libexec/java_home" if prog == "java_home" else prog,
                _paths(args))
    if prog in _OTHER:
        return ("other", prog, [])
    if prog in ("sh", "bash", "zsh") and args and args[0] in ("-c", "-lc"):
        return shell_items(args[1] if len(args) > 1 else "")
    if prog in _IGNORED:
        return (None, "IGN-" + prog, [])
    # parser noise: file names, options and arithmetic left after splitting
    if re.search(r"[.*+=:<>]|^-|^\d", prog) or prog in ("null", "HARNESS", "GIT_DIR"):
        return (None, "IGN-noise", [])
    return ("other", "any other program", [])


# --------------------------------------------------------------------------- #
# The action table: one tool call

def classify(tool: str, args: Dict[str, Any], line: str = "") -> Dict[str, Any]:
    """The category of one tool call (``line``: a shell tool's command).  Returns
    ``category``, ``item`` (the table's entry that decided it), ``targets`` (the paths of the
    deciding category's items, or the native tool's file) and ``all_targets`` (the paths of
    every search, read, edit and orient item of a shell line)."""
    args = args if isinstance(args, dict) else {}
    if tool in taxonomy.SHELL_TOOLS:
        line = line or str(args.get("command") or args.get("cmd") or "")
        items = shell_items(line)
        known = [x for x in items if x[0] is not None]
        if not known:
            return {"category": "other", "item": "a line made only of ignored programs",
                    "targets": [], "all_targets": None}
        best = min(known, key=lambda x: ORDER.index(x[0]))
        return {"category": best[0], "item": best[1],
                "targets": [t for x in known if x[0] == best[0] for t in x[2]],
                "all_targets": [t for x in known if x[0] in ("search", "read", "edit", "orient")
                                for t in x[2]]}
    path = next((str(args[k]) for k in PATH_KEYS if isinstance(args.get(k), str) and args[k]),
                "")
    if tool in EDIT_TOOLS and path and not in_repo(path):
        return {"category": "other", "item": "Edit, Write, edit, write_file on a file outside "
                                             "the repository (/tmp)",
                "targets": [path], "all_targets": None}
    if tool in NATIVE:
        category, item = NATIVE[tool]
        return {"category": category, "item": item, "targets": [path] if path else [],
                "all_targets": None}
    if tool in TABLE_OTHER_TOOLS:
        return {"category": "other", "item": "any other tool", "targets": [], "all_targets": None}
    # beyond the table: a tool of another agent, by what it does
    call = {"function_name": tool, "arguments": args}
    category = KIND_CATEGORY.get(taxonomy.mid_level(call), "other")
    if category == "other":
        return {"category": "other", "item": "any other tool", "targets": [], "all_targets": None}
    files = taxonomy.edited_files(call) if category == "edit" else ([path] if path else [])
    if category == "edit" and any(not in_repo(f) for f in files) and not any(
            in_repo(f) for f in files):
        return {"category": "other", "item": "an edit tool on a file outside the repository",
                "targets": files, "all_targets": None}
    return {"category": category, "item": f"{tool} (another agent's tool)", "targets": files,
            "all_targets": None}


def annotate(rows: Iterable[dict]) -> None:
    """Set ``category`` and ``lookup_item`` (the action table's entry) on prepared rows
    (``taxonomy.annotate``: tool, arguments), and ``_lookup`` (the deciding targets)."""
    for row in rows:
        args = row.get("arguments") or {}
        line = taxonomy.shell_command({"function_name": row["tool"], "arguments": args}) \
            if row["tool"] in taxonomy.SHELL_TOOLS else ""
        found = classify(row["tool"], args, line)
        row["category"], row["lookup_item"] = found["category"], found["item"]
        row["_lookup"] = found


def set_category(row: dict, category: str, item: str) -> None:
    """Count a row as ``category`` (a row of the user's): its taxonomy kind and mid-level
    follow, so that its verdict is read as that category's (a test run's, a build's)."""
    row["category"], row["lookup_item"] = category, item
    row["kind"], row["mid_level"] = CATEGORY_KIND[category]
    found = row.get("_lookup") or {}
    row["_lookup"] = {**found, "category": category, "item": item}


# --------------------------------------------------------------------------- #
# The phase table

def _targets(row: dict) -> List[str]:
    """The files an action works on: the deciding items' paths or the native tool's file;
    else every path the action names (``segment.enrich``: inside the repository, then
    outside)."""
    found = [t for t in (row.get("_lookup") or {}).get("targets") or [] if t]
    if found:
        return found
    paths = [taxonomy.repo_path(f) for f in row.get("files") or []]
    paths += [o for o in row.get("outside") or [] if not o.startswith("/dev/")]
    return [p.strip() for p in dict.fromkeys(",".join(paths).split(",")) if p.strip()]


def prepare(acts: List[dict]) -> int:
    """Per action: ``targets``, ``target_kinds`` (TARGETS of the targets), ``edit_targets``
    (the targets of an edit; an edit whose file is unknown counts as source) and
    ``source_edit``.  Returns the position of the first edit of a source file (the anchor),
    or ``len(acts)``."""
    first = len(acts)
    for x, a in enumerate(acts):
        tg = _targets(a)
        a["targets"] = tg
        a["target_kinds"] = sorted({target(t) for t in tg} - {""}, key=TARGETS.index)
        if a["category"] == "edit":         # a quoted empty path keeps its "" (no target)
            a["edit_targets"] = sorted({target(t) for t in tg} or {"source"}, key=_order)
        else:
            a["edit_targets"] = []
        a["source_edit"] = "source" in a["edit_targets"]
        if a["source_edit"] and first == len(acts):
            first = x
    return first


def action_targets(row: dict) -> str:
    """The targets of the files a prepared action works on (``prepare``), comma-separated,
    in table order; empty when it names no file.  The file-role column of the viewer and of
    the annotation sheets."""
    return ", ".join(row.get("target_kinds") or [])


def _order(t: str) -> int:
    return TARGETS.index(t) if t in TARGETS else len(TARGETS)


#: row id -> its phase, or None for the previous step's phase
ROW_PHASE: Dict[str, Optional[str]] = {rid: (None if phase == PREVIOUS else phase)
                                       for rid, phase, *_ in PHASE_TABLE}
ROW_PHASE[GENERAL] = None


def rows(acts: List[dict], anchor: int) -> List[Tuple[str, Optional[str]]]:
    """The phase table on prepared actions (``prepare``): per action, (row id, phase), the
    phase None when the row says the previous step's phase (L14, L15 and the general rule).
    Sets ``own_patch`` on the reads of row 11 that read back files the agent changed."""
    nxt = False                                   # look ahead (rows 9 and 10)
    ahead: List[bool] = [False] * len(acts)
    for x in range(len(acts) - 1, -1, -1):
        ahead[x] = nxt
        a = acts[x]
        if a["source_edit"]:
            nxt = True
        elif a["category"] in ("build", "test", "diff"):
            nxt = False
    out: List[Tuple[str, Optional[str]]] = []
    changed: Set[str] = set()
    for x, a in enumerate(acts):
        a["own_patch"] = False
        rid = _row(a, x, anchor, changed, ahead[x])
        out.append((rid, ROW_PHASE[rid]))
        if a["category"] == "edit":
            changed |= {repo_rel(t) for t in a["targets"]}
    return out


def _row(a: dict, x: int, anchor: int, changed: Set[str], next_edit_first: bool) -> str:
    cat = a["category"]
    before, after = x < anchor, x > anchor
    if cat == "plan":
        return "L1"
    if x == 0 and cat in ("orient", "other", "vcs", "diff"):
        return "L2"
    kinds = set(a["target_kinds"])
    found = a.get("_lookup") or {}
    every = found.get("all_targets")
    every = a["targets"] if every is None else every
    if before and cat in ("read", "search") and kinds == {"docs"} \
            and {target(t) for t in every} - {""} <= {"docs"}:
        return "L3"
    if before and cat == "build":
        return "L4"
    if before and cat in ("search", "read", "sub-agent"):
        return "L5"
    if before and cat == "test":
        return "L6"
    if before and cat == "edit" and a["edit_targets"] and set(a["edit_targets"]) <= {"test"}:
        return "L7"
    if cat == "edit" and a["source_edit"] and not before:
        return "L8"
    if after and cat in ("search", "read"):
        own = any(repo_rel(t) in changed for t in (every or a["targets"]))
        new = [repo_rel(t) for t in a["targets"] if target(t) == "source"
               and repo_rel(t) not in changed]
        if not own and new:
            return "L9" if next_edit_first else "L10"
        a["own_patch"] = own
        return "L11"
    if after and cat in ("build", "test", "diff", "vcs"):
        return "L12"
    if after and cat == "edit":
        return "L13"
    if cat in ("orient", "other"):
        return "L14"
    if before and cat in ("vcs", "diff"):
        return "L15"
    return GENERAL


def resolve(cells: List[Optional[str]]) -> List[str]:
    """The previous step's phase for every None (the start: ``START_PHASE``)."""
    out: List[str] = []
    for phase in cells:
        out.append(phase if phase is not None else (out[-1] if out else START_PHASE))
    return out
