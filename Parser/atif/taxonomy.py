"""Action taxonomy: ATIF tool calls -> mid-level actions -> L1 categories, file roles.

Deliberately uses only the *action* side of the trajectory (tool name, arguments,
result status). Thought text is not consulted anywhere here, because it is absent
for most actions in this corpus -- see ``Parser/Log audit and collection spec.md``.

low      : one ATIF ``tool_call``
mid      : one of MID_LEVEL -- what the agent did; the verdict parser and ``atif.segment``
           (baseline B3) read it
category : one of CATEGORIES -- ``mid`` refined for the phase taxonomy (``atif.phase``):
           ``shell_edit`` and ``diff`` split out, ``mid`` itself unchanged.  See
           ``category()``.
edit_role: what an edit is for (source, test, toolchain); the first edit of application
           source is the phase anchor (``first_source_edit``), so a ``build.gradle`` or
           test-script edit made to get the bug to reproduce does not end reproduction.

Phases are assigned by ``atif.phase``.  The older high-level ladder and the "rule v2"
phases that used to be computed here were removed on 2026-10-11 (nothing read them).

Agent-specific names (tool names, argument keys) live in one section, "Agent vocabularies"
below; every rule after it is agent-neutral.

Known deviations:

* An edit made from the shell is recognised when the command writes a project file inside
  the checkout (``apply_patch`` heredocs, ``cat``/``tee``/``echo``/``printf`` redirected
  into the file, ``sed -i``, ``perl -i``, a Python script whose write target is a string
  literal) or applies a patch (``git apply``, ``patch``).  ``cp``/``mv`` onto a source file,
  Python writes to computed paths, and writes to files other than code, resources and
  build scripts (``PROJECT_FILE``) are not.  A command that both edits and runs something
  (Codex's ``apply_patch <<'PATCH' ... PATCH`` followed by ``./gradlew test``) keeps the
  mid-level of its run (``KIND_PRIORITY``); it carries its ``edit_files`` and ``edit_role``
  and can be the phase anchor, but it is not an ``edit_file`` action.
"""
from __future__ import annotations

import functools
import json
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

MID_LEVEL = ("read_file", "search_code", "orient", "edit_file", "build", "run_test",
             "device_ops", "env_setup", "vcs", "plan", "delegate", "wait_process",
             "web", "run_shell", "other")
#: the purpose vocabulary of ``atif.segment`` (baseline B3)
PHASES = ("orientation", "localization", "reproduction", "environment", "repair",
          "validation", "review")
#: what an edited file is for (``file_role``)
EDIT_ROLES = ("source", "test", "toolchain")
#: L1 categories of the phase taxonomy (``atif.phase``; ``Parser/Phase taxonomy.md`` §3):
#: MID_LEVEL refined by two splits taken from the V2 analysis plan.  ``shell_edit`` is a
#: change made by a plain shell command (``sed -i``, a redirect, a Python write, ``git
#: apply``, ``patch``, and the git commands that change the working tree), which cannot be
#: replayed the way an editor or ``apply_patch`` edit can; ``diff`` is ``git diff`` /
#: ``diff``, split from the rest of ``vcs`` (status, log, show, ...), which only inspects
#: the repository.  ``mid_level`` is unchanged, so ``atif.segment`` (baseline B3) still
#: reads its 15 labels.
CATEGORIES = ("read_file", "search_code", "orient", "vcs", "diff", "web",
              "edit_file", "shell_edit",
              "build", "run_test", "device_ops", "run_shell",
              "env_setup",
              "plan", "delegate", "wait_process",
              "other")
#: every category belongs to one family; the phase rules read the family, the file role
#: and the verdict, so a new category never needs a new phase rule
CATEGORY_FAMILY: Dict[str, str] = {
    "read_file": "inspect", "search_code": "inspect", "orient": "inspect", "vcs": "inspect",
    "diff": "inspect", "web": "inspect",
    "edit_file": "modify", "shell_edit": "modify",
    "build": "execute", "run_test": "execute", "device_ops": "execute", "run_shell": "execute",
    "env_setup": "configure",
    "plan": "coordinate", "delegate": "coordinate", "wait_process": "coordinate",
    "other": "other",
}
#: what a file an action reads, searches or edits is for (``object_role``)
OBJECT_ROLES = ("source", "test", "toolchain", "harness", "docs")


# --------------------------------------------------------------------------- #
# Agent vocabularies
#
# The only agent-specific names the rules read: the raw tool names (ATIF ``function_name``)
# and argument keys of Claude Code (claude-opus-5), Codex CLI 0.138 (gpt-5.6-sol) and Qwen
# Code 0.24 (qwen3.6-35b-a3b), as surveyed over all 7,900 logs of the corpus.  A tool that
# is not listed here is ``other``.  The rules below read tool names and argument keys only
# through these tables, so porting them to another agent means replacing the tables (and
# the result-text markers of ``atif.verdict``).

#: tools that run a shell command; the command is classified by the program it runs
SHELL_TOOLS = {
    "Bash",                       # Claude Code
    "exec_command",               # Codex CLI
    "shell",                      # Codex CLI before exec_command (command as an argv list)
    "run_shell_command",          # Qwen Code
}
#: argument keys holding a shell tool's command, in lookup order: ``cmd`` (Codex),
#: ``command`` (Claude Code, Qwen Code), ``input`` (the body of Codex's apply_patch tool)
SHELL_COMMAND_KEYS = ("cmd", "command", "input")
#: argument key of a shell tool's working directory (Codex)
WORKDIR_KEY = "workdir"
#: argument keys naming the file or directory a tool acts on, in lookup order
PATH_KEYS = ("file_path", "path", "notebook_path")
#: argument keys that describe what a non-file tool acts on, for ``action_target``
TARGET_KEYS = ("pattern", "query", "prompt", "message", "description")
#: Codex's patch tool (``*** Update File:`` bodies); run through the shell it is a patch too
PATCH_TOOL = "apply_patch"
#: tools that call another tool named in their arguments: Qwen Code's ``tool_call`` bridge
#: takes ``{"name": <tool>, "arguments": {...}}`` and runs that tool (its 29 calls in the
#: corpus returned the named tool's result: "Message queued", "Recorded artifact", ...)
WRAPPER_TOOLS: Dict[str, Tuple[str, str]] = {"tool_call": ("name", "arguments")}
#: argument keys holding a delegation's instruction (Claude Code ``Agent``, Qwen ``agent``)
DELEGATE_PROMPT_KEYS = ("prompt", "description")
#: argument key of the sub-agent type, and the types that have no edit tool: Claude Code's
#: and Qwen Code's built-in ``Explore`` agent is read-only, so it never edits
SUBAGENT_TYPE_KEY = "subagent_type"
READ_ONLY_SUBAGENTS = ("Explore",)
#: Codex runs a long command in the background: the call returns ``Process running with
#: session ID N`` and ``write_stdin(session_id=N)`` polls it
SESSION_STARTED = re.compile(r"session ID (\d+)")
SESSION_ID_KEY = "session_id"

#: every non-shell tool of the corpus, with a short reason where the mapping is not obvious
TOOL_MAP: Dict[str, str] = {
    # Claude Code (Bash, Read, Edit, Write and Agent: all but 5 of its 82,418 calls)
    "Read": "read_file", "NotebookRead": "read_file", "Grep": "search_code",
    "Glob": "search_code", "LS": "orient", "Edit": "edit_file", "MultiEdit": "edit_file",
    "Write": "edit_file", "NotebookEdit": "edit_file", "TodoWrite": "plan",
    "ExitPlanMode": "plan", "EnterPlanMode": "plan", "Agent": "delegate", "Task": "delegate",
    "TaskOutput": "wait_process", "TaskStop": "wait_process",
    "Monitor": "wait_process",     # watches a background task's output, like TaskOutput
    "WebFetch": "web", "WebSearch": "web", "AskUserQuestion": "other", "Skill": "other",
    "ToolSearch": "other", "SlashCommand": "other",
    # Codex CLI (exec_command, write_stdin and update_plan; patches arrive as exec_command
    # heredocs, the apply_patch tool itself is not called in this corpus)
    "apply_patch": "edit_file", "write_stdin": "wait_process", "web_search": "web",
    "view_image": "other", "update_plan": "plan",
    # Qwen Code
    "read_file": "read_file", "grep_search": "search_code", "glob": "search_code",
    "edit": "edit_file",           # old_string -> new_string in file_path
    "write_file": "edit_file",
    "agent": "delegate",           # launches a sub-agent; its steps are spliced like Claude's
    # the background-agent controls: the main agent waits on a delegate it launched, as
    # Claude Code does with TaskOutput / TaskStop and a shell does with ps / kill
    "list_agents": "wait_process",   # "Listed N background agent(s)." (2,612 of 2,625)
    "send_message": "wait_process",  # "send your findings now" to a running agent: 318
                                     # queued, 88 resumed a finished one, 289 bad params
    "task_stop": "wait_process",     # cancels an agent (59) or a background shell (10)
    "update_goal": "plan",         # records the goal's status and reason; acts on nothing
    "get_goal": "plan",
    "tool_search": "other",        # looks up tool schemas, like Claude Code's ToolSearch
    "skill": "other",              # like Claude Code's Skill
    "record_artifact": "other",    # registers a file as a deliverable; acts on nothing
    "zoom_image": "other",         # views a screenshot region, like Codex's view_image
    # names Qwen invented: the registry rejected every call ("Tool ... not found"), so
    # nothing ran; as shell tools they would count as failed builds and test runs
    "run_shell": "other", "try_shell_command": "other", "list_files": "other",
}


# --------------------------------------------------------------------------- #
# shell commands

#: A shell command is classified by the program it runs, not by substrings anywhere in
#: the line -- ``sed -n '1,220p' src/androidTest/Script18.java`` is a file read, not a
#: test run, and ``rm -rf .gradle-local`` is cleanup, not a build.
PROGRAM_KIND: Dict[str, str] = {
    "sed": "read_file", "cat": "read_file", "head": "read_file", "tail": "read_file",
    "less": "read_file", "more": "read_file", "nl": "read_file", "bat": "read_file",
    "rg": "search_code", "grep": "search_code", "egrep": "search_code",
    "ag": "search_code", "ack": "search_code", "find": "search_code", "fd": "search_code",
    "ls": "orient", "pwd": "orient", "tree": "orient", "df": "orient", "du": "orient",
    "which": "orient", "whoami": "orient", "uname": "orient", "env": "orient",
    "printenv": "orient", "stat": "orient", "file": "orient", "wc": "orient",
    "git": "vcs",
    "adb": "device_ops", "emulator": "device_ops", "avdmanager": "device_ops",
    "gradle": "build", "gradlew": "build", "mvn": "build", "make": "build",
    "javac": "build", "ant": "build", "ninja": "build", "cmake": "build",
    "pytest": "run_test", "junit": "run_test", "ctest": "run_test", "tox": "run_test",
    "java_home": "env_setup", "sdkmanager": "env_setup", "brew": "env_setup",
    "apt-get": "env_setup", "chmod": "env_setup", "chown": "env_setup",
    "rm": "env_setup", "cp": "env_setup", "mv": "env_setup", "ln": "env_setup",
    "jenv": "env_setup", "npm": "env_setup", "pip": "env_setup", "pip3": "env_setup",
    "curl": "web", "wget": "web",
    "kill": "wait_process", "pkill": "wait_process", "pgrep": "wait_process",
    "ps": "wait_process", "sleep": "wait_process", "wait": "wait_process",
    "timeout": "wait_process",
    "javap": "read_file", "keytool": "env_setup", "unzip": "env_setup",
    "tar": "env_setup", "zip": "env_setup", "open": "other", "defaults": "env_setup",
}
#: Leading segments that only set things up for the segment that follows.
PREFIX_NOISE = {"cd", "export", "set", "unset", "source", ".", "mkdir", "pushd", "popd",
                "true", "eval"}
#: Wrappers to look through to find the real program.
WRAPPERS = {"sudo", "time", "nohup", "nice", "env", "xargs", "command", "exec"}
#: Which segment of a compound command names the action. Highest priority wins.
KIND_PRIORITY = ("run_test", "build", "device_ops", "env_setup", "edit_file", "vcs",
                 "search_code", "read_file", "web", "wait_process", "orient",
                 "run_shell")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SPLIT = re.compile(r"&&|\|\||;|\n|\|")
_TEST_TASK = re.compile(r"\b(test|check|connectedAndroidTest|androidTest|instrument)\b",
                        re.IGNORECASE)
#: Gradle task names that run tests.  ``\btest\b`` above misses the variant-specific
#: tasks (``:app:testDebugUnitTest``, ``connectedFossDebugAndroidTest``), which are
#: one word; ``assembleAndroidTest`` / ``compileDebugAndroidTestJavaWithJavac`` only
#: compile the test APK and stay ``build``.
_TEST_TASK_NAME = re.compile(r"^(?:test|check|connectedCheck|deviceCheck|test\w*UnitTest"
                             r"|connected\w*AndroidTest)$")
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_PATCH_HEADER = re.compile(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+?)\s*$", re.M)
#: the same header as a quoted shell word: ``{ printf '%s\n' '*** Begin Patch'
#: '*** Update File: a/B.xml' ...; } | apply_patch``
_PATCH_HEADER_QUOTED = re.compile(
    r"(['\"])\*\*\* (?:Update|Add|Delete) File:\s*([^'\"\n]+?)\s*\1")
#: files whose change from the shell counts as an edit of the project: code, resources and
#: build scripts.  Logs, patch files, notes and scratch output (``> build.log``,
#: ``> fix.patch``) are not, wherever they are written.
PROJECT_FILE = re.compile(r"\.(?:java|kt|kts|xml|gradle|properties|pro|json)$")
#: programs that write their input to a file named by a redirect (``tee``: by argument)
_WRITERS = {"cat", "tee", "echo", "printf"}
_PYTHON = {"python", "python3", "py"}
#: a checkout path: ``.../bug-<id>/...`` (the run folders of every agent are named so)
_CHECKOUT = re.compile(r"(?:^|/)bug-\d+(?:/|$)")
#: Python file writes whose target is a literal or a name bound to one
_PY_OPEN = re.compile(r"\bopen\(\s*([^,()]+?)\s*,\s*(?:mode\s*=\s*)?['\"]([rwabxt+]+)['\"]")
_PY_WRITE_TEXT = re.compile(r"(Path\(\s*['\"][^'\"]+['\"]\s*\)|[A-Za-z_]\w*)"
                            r"\.write_(?:text|bytes)\(")
_PY_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(?:Path\(\s*)?['\"]([^'\"\n]+)['\"]", re.M)
_PY_LITERAL = re.compile(r"^(?:Path\(\s*)?['\"]([^'\"\n]+)['\"]\s*\)?$")


def patch_files(text: str) -> List[str]:
    """Files named by the ``*** Update File:`` / ``*** Add File:`` / ``*** Delete File:``
    headers of an apply_patch body, in order, each once."""
    found = _PATCH_HEADER.findall(text) + [m.group(2)
                                            for m in _PATCH_HEADER_QUOTED.finditer(text)]
    return [f for k, f in enumerate(found) if f not in found[:k]]


def _inside(path: str, cwd_inside: bool) -> bool:
    """Whether a path named in a command lies in the project inside the bug checkout: a
    path through a ``bug-<id>`` folder is, another absolute path, ``~`` or a ``$VAR`` path is
    not, and a relative path is wherever the command's working directory is.  A hidden
    folder is not part of the project (``.gradle/``, and scratch folders such as ``.sim/``
    and ``.verify/`` that agents create inside the checkout)."""
    match = _CHECKOUT.search(path)
    if match:
        path, cwd_inside = path[match.end():], True
    elif path.startswith(("/", "~", "$")):
        return False
    return cwd_inside and not any(part.startswith(".") and part not in (".", "..")
                                  for part in path.split("/"))


def _project_file(path: str, cwd_inside: bool) -> bool:
    return bool(PROJECT_FILE.search(path)) and _inside(path, cwd_inside)


def _redirect_targets(tokens: List[str]) -> List[str]:
    """Files a segment's standard output is redirected to (``> f``, ``>> f``, ``>f``);
    ``2>``, ``&>``, ``>&2`` and ``/dev/null`` are not file writes of the content."""
    out: List[str] = []
    for k, token in enumerate(tokens):
        match = re.match(r"^1?(>>?)(.*)$", token)
        if not match:
            continue
        target = match.group(2) or (tokens[k + 1] if k + 1 < len(tokens) else "")
        if target and not target.startswith(("&", ">")) and target != "/dev/null":
            out.append(target)
    return out


def _in_place_files(args: List[str], code_switches: str,
                    value_switches: str) -> Optional[List[str]]:
    """Operands of ``sed``/``perl`` when a ``-i`` switch makes them edit in place, else
    None.  Switches are read one character at a time (``-pi``, ``-0pi``, ``-i.bak``,
    ``-ni``); ``-i``'s backup suffix is the rest of its cluster, or, for BSD ``sed -i ''``
    / ``-i .bak``, the next argument; a switch in ``code_switches`` (``-e``) takes the
    program text, one in ``value_switches`` a value; the first other operand is the
    program when no ``-e`` gave one."""
    in_place, code, files = False, False, []
    k = 0
    while k < len(args):
        token = args[k]
        if token.startswith("--"):
            in_place = in_place or token.startswith("--in-place")
            if token in ("--expression", "--file"):
                code = True
                k += 1
        elif token.startswith("-") and len(token) > 1:
            cluster, c = token[1:], 0
            while c < len(cluster):
                char = cluster[c]
                if char == "i":
                    in_place = True
                    if c == len(cluster) - 1 and k + 1 < len(args) and \
                            (args[k + 1] == "" or re.fullmatch(r"\.\w+", args[k + 1])):
                        k += 1                       # BSD sed: -i '' / -i .bak
                    break                            # the rest is the backup suffix
                if char in code_switches:
                    code = True
                    if c == len(cluster) - 1:
                        k += 1                       # the program is the next argument
                    break
                if char in value_switches:
                    if c == len(cluster) - 1:
                        k += 1
                    break
                if char == "0" and code_switches == "eE":   # perl -0777: a record separator
                    while c + 1 < len(cluster) and cluster[c + 1].isdigit():
                        c += 1
                c += 1
        elif not code:
            code = True                              # the program, or perl's script file
        else:
            files.append(token)
        k += 1
    return files if in_place else None


def _sed_files(args: List[str]) -> Optional[List[str]]:
    """Files ``sed -i`` rewrites in place, or None when it does not edit in place."""
    return _in_place_files(args, "ef", "l")


def _perl_files(args: List[str]) -> Optional[List[str]]:
    """Files ``perl -i`` (``-pi -e``, ``-0pi``, ``-i -ne``, ``-pi.bak``) rewrites in place,
    or None when it does not edit in place."""
    return _in_place_files(args, "eE", "MmIxCdDF")


def _python_writes(tokens: List[str], segment: str) -> Optional[List[str]]:
    """Literal paths a ``python - <<EOF`` or ``python -c '...'`` script opens for writing
    (``open(p, 'w')``, ``Path(p).write_text(...)``, ``p`` bound to a string literal), or
    None when the script writes no file.  A computed path is not resolved."""
    if "-c" in tokens and tokens.index("-c") + 1 < len(tokens):
        body = tokens[tokens.index("-c") + 1]
    elif "\n" in segment and "<<" in segment.split("\n", 1)[0]:
        body = segment.split("\n", 1)[1]
    else:
        return None
    targets = [m.group(1) for m in _PY_OPEN.finditer(body)
               if set(m.group(2)) & set("wax+")]
    targets += [m.group(1) for m in _PY_WRITE_TEXT.finditer(body)]
    if not targets:
        return None
    bound: Dict[str, List[str]] = {}
    for m in _PY_ASSIGN.finditer(body):
        bound.setdefault(m.group(1), []).append(m.group(2))
    out: List[str] = []
    for expr in targets:
        literal = _PY_LITERAL.match(expr.strip())
        out += [literal.group(1)] if literal else bound.get(expr.strip(), [])
    return out


def _applies_patch(name: str, tokens: List[str]) -> bool:
    """``git apply <patch>`` or ``patch -p1 < x.patch``, not a dry run or a listing."""
    if name == "git":
        return len(tokens) > 1 and tokens[1] == "apply" and not any(
            t in ("--check", "--stat", "--numstat", "--summary") for t in tokens[2:])
    return name == "patch" and not any(t in ("--dry-run", "-C", "--check") for t in tokens)


def _program(segment: str) -> Tuple[str, List[str]]:
    """(program name, tokens from the program on), looking through assignments and
    WRAPPERS."""
    tokens = _tokenize(segment)
    while tokens and (_ASSIGNMENT.match(tokens[0]) or tokens[0] in WRAPPERS):
        depth = tokens[0].count("$(") - tokens[0].count(")")
        tokens.pop(0)
        while depth > 0 and tokens:      # JAVA_HOME=$(java_home -v 17) splits into words
            depth -= tokens[0].count(")") - tokens[0].count("$(")
            tokens.pop(0)
    if not tokens:
        return "", []
    return tokens[0].rsplit("/", 1)[-1].lstrip("./"), tokens


def segment_writes(segment: str) -> Optional[List[str]]:
    """Paths one simple command writes, as written in the command, or None when it writes
    no file: a writer's redirect (``cat > f <<EOF``, ``echo x >> f``, ``tee f``), ``sed -i``
    and ``perl -i`` operands, and a Python script's literal write targets."""
    name, tokens = _program(segment)
    if name in _WRITERS:
        found = _redirect_targets(tokens[1:])
        if name == "tee":
            found += [t for t in tokens[1:] if not t.startswith(("-", ">"))
                      and t not in found and not tokens[tokens.index(t) - 1].startswith(">")]
        return found or None
    if name == "sed":
        return _sed_files(tokens[1:])
    if name == "perl":
        return _perl_files(tokens[1:])
    if name in _PYTHON:
        return _python_writes(tokens, segment)
    return None


def _cd(segment: str, cwd_inside: bool) -> bool:
    """The working directory after a ``cd``/``pushd`` segment: inside the checkout or not."""
    tokens = _tokenize(segment)
    if len(tokens) > 1 and tokens[0] in ("cd", "pushd") \
            and not tokens[1].startswith(("-", "$", "`")):  # cd "$(...)": not known, kept
        return _inside(tokens[1], cwd_inside)
    return cwd_inside


def split_commands(text: str) -> List[Tuple[str, str]]:
    """Split a shell command line into top-level simple commands (``_split_commands``,
    cached: the rules ask about the same command many times)."""
    return list(_split_commands(text))


@functools.lru_cache(maxsize=8192)
def _split_commands(text: str) -> Tuple[Tuple[str, str], ...]:
    """Split a shell command line into top-level simple commands.

    Returns ``[(segment, separator_that_follows)]`` with separators ``&&``, ``||``,
    ``;``, ``|`` and newline (``""`` after the last segment).  Unlike a regex split it
    does not cut inside quotes (``grep -E "A|B"``), inside ``$(...)`` or backticks
    (``JAVA_HOME=$(/usr/libexec/java_home -v 17)``), or inside a heredoc body (an
    ``apply_patch <<'PATCH'`` body is Java source full of ``;`` and ``|``), and it drops
    ``#`` comments, whose apostrophes would otherwise open a quote.  Bare ``( ... )``
    subshells are not treated as nesting, as before.  If the text ends inside an
    unclosed quote it falls back to the old regex split, so it never loses text.
    """
    out: List[Tuple[str, str]] = []
    buf: List[str] = []
    pending: List[str] = []                       # heredoc delimiters seen on this line
    stack: List[str] = []                         # open "'", '"', "`" and "$(" contexts
    i, n = 0, len(text)

    def flush(sep: str) -> None:
        segment = "".join(buf).strip()
        if segment:
            out.append((segment, sep))
        elif out and sep:                         # empty segment: keep the later sep
            out[-1] = (out[-1][0], sep)
        buf.clear()

    while i < n:
        ch = text[i]
        top = stack[-1] if stack else ""
        if top == "'":                            # single quotes: nothing is special
            buf.append(ch)
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(text[i:i + 2])
            i += 2
            continue
        if top in ('"', "`"):
            if ch == top:
                stack.pop()
            elif text.startswith("$(", i):
                stack.append("$(")
                buf.append("$(")
                i += 2
                continue
            elif ch == "`" and top == '"':
                stack.append("`")
            buf.append(ch)
            i += 1
            continue
        # unquoted, either at top level or inside $( ... )
        if ch in ("'", '"', "`"):
            stack.append(ch)
            buf.append(ch)
            i += 1
            continue
        if text.startswith("$(", i):
            stack.append("$(")
            buf.append("$(")
            i += 2
            continue
        if top == "$(":
            if ch == ")":
                stack.pop()
            buf.append(ch)
            i += 1
            continue
        if ch == "#" and (not buf or buf[-1][-1:] in (" ", "\t", "\n", ";", "&", "|", "(")):
            while i < n and text[i] != "\n":     # comment: skip to the end of the line
                i += 1
            continue
        if ch == "<" and not text.startswith("<<<", i):
            match = _HEREDOC.match(text, i)
            if match:
                pending.append(match.group(3))
                buf.append(match.group(0))
                i = match.end()
                continue
        if ch == "\n":
            j = i + 1
            for delimiter in pending:             # heredoc bodies belong to this segment
                while j < n:
                    end = text.find("\n", j)
                    end = n if end < 0 else end
                    line = text[j:end]
                    buf.append("\n" + line)
                    j = end + 1
                    if line.strip() == delimiter:
                        break
            if pending:
                i = j - 1                         # the newline after the delimiter line
                pending = []
            flush("\n")
            i += 1
            continue
        two = text[i:i + 2]
        if two in ("&&", "||"):
            flush(two)
            i += 2
            continue
        if ch in (";", "|"):
            flush(ch)
            i += 1
            continue
        buf.append(ch)
        i += 1
    if stack:                                     # unbalanced: the old behaviour
        return tuple((part.strip(), "") for part in _SPLIT.split(text) if part.strip())
    flush("")
    return tuple(out)


def _tokenize(segment: str) -> List[str]:
    """Split a shell segment into tokens, keeping quoted paths (which contain spaces,
    e.g. /Applications/Android Studio.app/...) as single tokens.  A fresh list each call:
    ``_program`` consumes it."""
    if "<<" in segment and "\n" in segment:       # heredoc: only the command line counts
        segment = segment.split("\n", 1)[0]
    return list(_shlex_tokens(segment))


@functools.lru_cache(maxsize=8192)
def _shlex_tokens(segment: str) -> Tuple[str, ...]:
    try:
        return tuple(shlex.split(segment, posix=True))
    except ValueError:                      # unbalanced quotes, heredoc bodies
        return tuple(segment.split())


def _runs_gradle_tests(tokens: List[str]) -> bool:
    args = " ".join(tokens)
    if _TEST_TASK.search(args):
        return True
    for token in tokens:
        if token.startswith("-"):
            continue
        if _TEST_TASK_NAME.match(token.rsplit(":", 1)[-1]):
            return True
    return False


def _program_kind(segment: str, cwd_inside: bool = True) -> str:
    """Mid-level kind of one simple command.  ``cwd_inside``: whether the command runs in
    the bug checkout, so that a relative path it writes is a project file."""
    name, tokens = _program(segment)
    if not tokens:
        return ""
    raw = tokens[0]
    args = " ".join(tokens[1:])
    if name in PREFIX_NOISE:
        return "noise"
    if name in ("adb",):
        return "run_test" if "instrument" in args else "device_ops"
    if name in ("bash", "sh", "zsh") and len(tokens) > 2 and re.fullmatch(r"-\w*c", tokens[1]):
        return _shell_kind(tokens[2], cwd_inside)  # bash -lc '<script>': classify the script
    if name == PATCH_TOOL:
        return "edit_file"          # Codex's patch tool, invoked through the shell
    if _applies_patch(name, tokens):
        return "edit_file" if cwd_inside else "env_setup"
    writes = segment_writes(segment)
    if writes is not None:          # a shell write: an edit when it changes a project file
        if any(_project_file(p, cwd_inside) for p in writes) or (
                not writes and name in ("sed", "perl") and cwd_inside):
            return "edit_file"      # (``... | xargs sed -i``: the files come from stdin)
        if name in ("cat", "tee", "sed", "perl") and (name != "tee" or
                                                      _redirect_targets(tokens[1:])):
            return "env_setup"      # writing a file from the shell, not reading one
    if name in ("gradle", "gradlew", "mvn", "ant"):
        return "run_test" if _runs_gradle_tests(tokens[1:]) else "build"
    if name in _PYTHON:
        return "run_test" if "pytest" in args or "unittest" in args else "run_shell"
    if name.endswith(".sh") or name.endswith(".bash"):
        return "run_test" if re.search(r"test|pipeline|script", name, re.IGNORECASE) \
            else "run_shell"
    if name == "java_home" or raw.endswith("java_home"):
        return "env_setup"
    if name == "java":
        return "run_test" if "-cp" in args or "junit" in args.lower() else "env_setup"
    return PROGRAM_KIND.get(name, "run_shell")


def _shell_kind(command: str, cwd_inside: bool = True) -> str:
    # split on the raw text: a multi-line script separates its commands by newlines,
    # so normalising whitespace first would collapse it into one segment
    text = str(command).strip()
    if not text:
        return "run_shell"
    kinds: List[str] = []
    for segment, _sep in split_commands(text):
        kind = _program_kind(segment, cwd_inside)
        if kind == "noise":
            cwd_inside = _cd(segment, cwd_inside)
        elif kind:
            kinds.append(kind)
    if not kinds:
        return "env_setup"          # the whole command was cd/export/mkdir
    for kind in KIND_PRIORITY:
        if kind in kinds:
            return kind
    return "run_shell"


def shell_edits(command: str, cwd_inside: bool = True) -> List[str]:
    """Project files a shell command writes, as named in it: the headers of an
    ``apply_patch`` body, and the project files of every ``segment_writes``, with ``cd``
    followed.  ``git apply`` / ``patch`` edit files the command does not name."""
    text = str(command).strip()
    files: List[str] = []
    segments = split_commands(text) if text else []
    if any(_program(s)[0] == PATCH_TOOL for s, _sep in segments):
        files += patch_files(text)
    for segment, _sep in segments:
        name, tokens = _program(segment)
        if name in ("bash", "sh", "zsh") and len(tokens) > 2 and re.fullmatch(r"-\w*c", tokens[1]):
            files += [f for f in shell_edits(tokens[2], cwd_inside) if f not in files]
            continue
        if name in PREFIX_NOISE:
            cwd_inside = _cd(segment, cwd_inside)
            continue
        for path in segment_writes(segment) or []:
            if _project_file(path, cwd_inside) and path not in files:
                files.append(path)
    return files


def resolve_call(call: dict) -> dict:
    """The call a wrapper tool (``WRAPPER_TOOLS``) made on the agent's behalf, else the
    call itself.  The row keeps the raw tool name; its label is that of the tool that ran."""
    keys = WRAPPER_TOOLS.get(call.get("function_name", ""))
    if keys:
        args = call.get("arguments") or {}
        inner, inner_args = args.get(keys[0]), args.get(keys[1])
        if isinstance(inner, str) and inner and inner not in WRAPPER_TOOLS:
            return {"function_name": inner,
                    "arguments": inner_args if isinstance(inner_args, dict) else {}}
    return call


def shell_command(call: dict) -> str:
    args = resolve_call(call).get("arguments") or {}
    for key in SHELL_COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
    return ""


def _workdir_inside(call: dict) -> bool:
    """Whether a shell call starts in the bug checkout (always, unless its working
    directory argument says otherwise)."""
    workdir = (call.get("arguments") or {}).get(WORKDIR_KEY)
    return _inside(workdir, True) if isinstance(workdir, str) and workdir else True


def mid_level(call: dict) -> str:
    """Classify one tool call. Shell tools are classified by their command string."""
    call = resolve_call(call)
    name = call.get("function_name", "")
    if name in SHELL_TOOLS:
        return _shell_kind(shell_command(call), _workdir_inside(call))
    return TOOL_MAP.get(name, "other")


#: git sub-commands that change the working tree or the index: a revert, so a shell edit
GIT_REVERTS = {"checkout", "restore", "stash", "reset", "clean", "revert"}
#: ``git stash`` sub-commands that only look
GIT_STASH_READS = {"list", "show"}
#: git options that take a value as the next word (``git -C app diff``)
_GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
#: programs that compare files, like ``git diff``
DIFF_PROGRAMS = {"diff", "cmp", "colordiff"}


def simple_commands(command: str) -> List[Tuple[str, List[str], str]]:
    """(program, tokens, segment text) of each simple command of a shell command line
    that does something: set-up segments (``PREFIX_NOISE``) and the later stages of a
    pipeline (``git log | head``: ``head`` filters output, it reads no file) are skipped,
    and ``bash -c '<script>'`` is looked into."""
    out: List[Tuple[str, List[str], str]] = []
    piped = False
    for segment, sep in split_commands(str(command).strip()) if command else []:
        name, tokens = _program(segment)
        if piped:
            pass
        elif name in ("bash", "sh", "zsh") and len(tokens) > 2 and re.fullmatch(r"-\w*c", tokens[1]):
            out += simple_commands(tokens[2])
        elif name and name not in PREFIX_NOISE:
            out.append((name, tokens, segment))
        piped = sep == "|"
    return out


def git_subcommand(tokens: List[str]) -> Tuple[str, str]:
    """(sub-command, its first argument) of a ``git`` command's tokens, skipping global
    options: ``git -C app --no-pager diff HEAD`` -> ("diff", "HEAD")."""
    k = 1
    while k < len(tokens) and tokens[k].startswith("-"):
        k += 2 if tokens[k] in _GIT_VALUE_OPTIONS else 1
    sub = tokens[k] if k < len(tokens) else ""
    return sub, tokens[k + 1] if k + 1 < len(tokens) else ""


def category(row: dict) -> Tuple[str, bool]:
    """(L1 category from CATEGORIES, whether the action reverts changes) of an annotated
    row.  Refines ``mid_level`` without changing it:

    * an ``edit_file`` made by a shell tool is ``shell_edit``, unless it runs Codex's
      ``apply_patch`` (a patch body that can be replayed); editor tools stay ``edit_file``;
    * a ``vcs`` command that runs a working-tree-changing git sub-command (GIT_REVERTS) is
      a ``shell_edit`` that reverts; one that runs ``git diff`` is ``diff``; one that also
      searches or reads files (Codex chains ``sed -n '1,330p' F.java; git log``, which
      KIND_PRIORITY labels ``vcs``) is ``search_code`` / ``read_file``; the rest stays
      ``vcs``;
    * a ``run_shell`` command made only of DIFF_PROGRAMS is ``diff``.
    """
    mid = row["mid_level"]
    call = resolve_call({"function_name": row.get("tool", ""),
                         "arguments": row.get("arguments") or {}})
    if call.get("function_name") not in SHELL_TOOLS or mid not in ("edit_file", "vcs",
                                                                    "run_shell"):
        return mid, False
    command = shell_command(call)
    programs = simple_commands(command)
    if mid == "edit_file":                       # ``{ printf ...; } | apply_patch``: any stage
        patch = any(name == PATCH_TOOL for name, _, _ in programs) or any(
            _program(segment)[0] == PATCH_TOOL for segment, _ in split_commands(command))
        return ("edit_file" if patch else "shell_edit"), False
    if mid == "vcs":
        subs = [git_subcommand(tokens) for name, tokens, _ in programs if name == "git"]
        if any(sub in GIT_REVERTS and not (sub == "stash" and arg in GIT_STASH_READS)
               for sub, arg in subs):
            return "shell_edit", True
        if any(sub == "diff" for sub, _ in subs):
            return "diff", False
        kinds = {_program_kind(segment, _workdir_inside(call)) for name, _, segment in programs
                 if name != "git"}
        return next((k for k in ("search_code", "read_file") if k in kinds), "vcs"), False
    if programs and all(name in DIFF_PROGRAMS for name, _, _ in programs):
        return "diff", False
    return mid, False


# --------------------------------------------------------------------------- #
# edit roles and the source-edit anchor

#: harness and build configuration: editing these gets the project to build or the test
#: to run, it does not repair the application
TOOLCHAIN_FILES = {"run_pipeline.sh", "local.properties", "gradle.properties",
                   "gradle-wrapper.properties", "gradle-wrapper.jar", "gradlew",
                   "gradlew.bat", ".java-version"}
TOOLCHAIN_SUFFIXES = (".gradle", ".kts", ".pro", ".properties")
#: the benchmark's reproducing test project, instrumented tests, and unit tests
TEST_PATH = re.compile(r"(?:^|/)(?:reproducing_script_project|androidTest|test)/")
_IN_REPO = re.compile(r"/bug-\d+/(.*)$")


def repo_path(path: str) -> str:
    """A path relative to the bug checkout when it lies inside one (``.../bug-18/app/x``
    -> ``app/x``), so that a ``/test/`` somewhere in the checkout's own location cannot
    make a source file look like a test."""
    path = str(path).strip().strip("'\"")
    match = _IN_REPO.search(path)
    if match:
        return match.group(1)
    return path[2:] if path.startswith("./") else path


def edited_files(call: dict) -> List[str]:
    """Paths an edit call writes: the tool's path argument, the ``*** Update File:`` /
    ``*** Add File:`` / ``*** Delete File:`` headers of an ``apply_patch`` body (patch tool
    or shell heredoc), or, for any shell command, the project files it writes
    (``shell_edits``)."""
    call = resolve_call(call)
    name = call.get("function_name", "")
    args = call.get("arguments") or {}
    if name == PATCH_TOOL:
        return patch_files(str(args.get("input") or args.get("patch") or ""))
    if name in SHELL_TOOLS:
        return shell_edits(shell_command(call), _workdir_inside(call))
    for key in PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def file_role(path: str) -> str:
    """toolchain (build config, wrapper, harness), test (reproducing project,
    androidTest, unit tests) or source.  Toolchain is checked first, so the
    reproducing project's own ``build.gradle`` is toolchain, not test."""
    rel = repo_path(path)
    base = rel.rsplit("/", 1)[-1]
    if base in TOOLCHAIN_FILES or base.endswith(TOOLCHAIN_SUFFIXES):
        return "toolchain"
    if TEST_PATH.search(rel):
        return "test"
    return "source"


def edit_role(files: List[str]) -> str:
    """Role of one edit action.  An edit whose target is unknown counts as source
    (conservative: it ends reproduction rather than extending it)."""
    roles = {file_role(f) for f in files}
    if not roles or "source" in roles:
        return "source"
    return "test" if "test" in roles else "toolchain"


#: the benchmark's check script, named in the task prompt of every run
HARNESS_SCRIPTS = {"run_pipeline.sh"}
#: documentation and other non-code files: reading them is understanding the project, not
#: locating the fault (V2: "reads of non-source files ... count as understanding")
DOC_FILE = re.compile(r"(?:^|/)(?:README|LICENSE|CHANGELOG|CONTRIBUT\w*|NOTICE|AUTHORS)[^/]*$"
                      r"|\.(?:md|rst|txt|adoc)$", re.IGNORECASE)


def object_role(path: str) -> str:
    """Role of any file an action touches: harness, docs, then ``file_role`` (toolchain,
    test, source).  Unlike ``file_role``, which decides an edit's role and is kept as it
    is for ``atif.segment``, it tells the harness script and documentation apart."""
    rel = repo_path(path)
    if rel.rsplit("/", 1)[-1] in HARNESS_SCRIPTS:
        return "harness"
    if DOC_FILE.search(rel):
        return "docs"
    return file_role(rel)


def action_roles(row: dict) -> str:
    """The roles (``object_role``) of the files a prepared action touches, comma-separated,
    or ``outside`` when it names only paths outside the checkout; empty when it names no
    path.  The file_role column of the annotation workbooks and of the viewer."""
    roles = sorted({object_role(f) for f in row.get("files") or []})
    if not roles and [o for o in row.get("outside") or [] if not o.startswith("/dev/")]:
        roles = ["outside"]
    return ", ".join(roles)


def first_source_edit(rows: List[dict]) -> Optional[int]:
    """0-based position of the phase anchor, or None when the source is never edited: the
    first action whose ``edit_role`` is source -- an ``edit_file`` action, or a command
    that writes source on its way to a run (``annotate``)."""
    return next((k for k, r in enumerate(rows) if r.get("edit_role") == "source"), None)


def resolve_waits(rows: List[dict]) -> None:
    """Set ``waits_on`` (an action_index or None) on every row.

    Codex runs long commands in the background: the starting ``exec_command`` returns
    ``Process running with session ID N`` and later ``write_stdin(session_id=N)`` calls
    poll it, so the test verdict arrives in a poll.  A poll is attributed to the command
    that *started* the session, never to the previous poll.  Other agents' waits
    (``TaskOutput``, ``kill``, ``sleep``) carry no session id and stay None."""
    sessions: Dict[str, int] = {}
    for row in rows:
        row["waits_on"] = None
        if row["mid_level"] == "wait_process":
            sid = (row.get("arguments") or {}).get(SESSION_ID_KEY)
            if sid is not None:
                row["waits_on"] = sessions.get(str(sid).strip())
            continue
        match = SESSION_STARTED.search(row.get("result") or "")
        if match:
            sessions[match.group(1)] = row["action_index"]


def segments(phases: List[str]) -> List[Tuple[str, int]]:
    """Run-length encode a phase sequence: [(phase, number of actions), ...]."""
    out: List[Tuple[str, int]] = []
    for phase in phases:
        if out and out[-1][0] == phase:
            out[-1] = (phase, out[-1][1] + 1)
        else:
            out.append((phase, 1))
    return out


# --------------------------------------------------------------------------- #
# action extraction from a trajectory


def _failed(result: Optional[dict]) -> Optional[bool]:
    if result is None:
        return None
    meta = result.get("extra") or {}
    if meta.get("is_error") is True or meta.get("status") == "error":
        return True
    if meta.get("exit_code") is not None:
        return meta["exit_code"] != 0
    body = result.get("content") or ""
    if isinstance(body, str):
        if re.search(r"\bexited with code ([1-9]\d*)", body):
            return True
        if body.startswith(("exec_command failed", "Error:")):
            return True
    if meta.get("is_error") is False or meta.get("status") == "success":
        return False
    return False


def _content(result: Optional[dict]) -> str:
    body = (result or {}).get("content")
    if body is None:
        return ""
    return body if isinstance(body, str) else json.dumps(body, default=str)


def actions(trajectory: dict, scope: str = "main") -> List[dict]:
    """Flatten a trajectory into chronological low-level actions.

    Subagent actions are spliced in at the delegating call so the sequence stays in
    execution order rather than being appended at the end.
    """
    rows: List[dict] = []
    for step in trajectory.get("steps", []):
        results = {r.get("source_call_id"): r
                   for r in (step.get("observation") or {}).get("results", [])}
        thought = "reasoning" if step.get("reasoning_content") else (
            "narration" if (step.get("message") or "").strip() else "none")
        for position, call in enumerate(step.get("tool_calls") or []):
            result = results.get(call["tool_call_id"])
            rows.append({
                "scope": scope,
                "step_id": step["step_id"],
                "call_index_in_step": position,
                "parallel_calls_in_step": len(step["tool_calls"]),
                "timestamp": step.get("timestamp", ""),
                "tool": call.get("function_name", ""),
                "call_id": call.get("tool_call_id", ""),
                "mid_level": mid_level(call),
                "target": action_target(call),
                "command": shell_command(call)[:400],
                "failed": _failed(result),
                "thought_source": thought,
                "thought": (step.get("reasoning_content") or step.get("message") or "").strip(),
                "result_preview": _content(result)[:400],
                # full call arguments and result text, for the verdict parser and the
                # segmenter; the exporters select their columns and never write these
                "arguments": call.get("arguments") or {},
                "result": _content(result),
                "delegates_to": next((ref.get("trajectory_id")
                                      for ref in (result or {}).get("subagent_trajectory_ref", [])
                                      ), None) if result else None,
            })
    subagents = {sub.get("trajectory_id"): sub
                 for sub in trajectory.get("subagent_trajectories") or []}
    spliced: List[dict] = []
    for row in rows:
        spliced.append(row)
        target = row.get("delegates_to")
        if target and target in subagents:
            spliced.extend(actions(subagents[target], scope=target))
    # a subagent whose delegating call carries no ref would otherwise be lost
    seen = {r["scope"] for r in spliced}
    for trajectory_id, sub in subagents.items():
        if trajectory_id not in seen:
            spliced.extend(actions(sub, scope=trajectory_id))
    return spliced


def action_target(call: dict) -> str:
    """A short human-readable object of the action: a path, pattern, or command head."""
    call = resolve_call(call)
    args = call.get("arguments") or {}
    for key in PATH_KEYS + TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    command = shell_command(call)
    if command:
        return " ".join(command.split())[:200]
    if args:
        return str(next(iter(args.values())))[:200]
    return ""


def annotate(trajectory: dict) -> List[dict]:
    """Actions with their mid-level label, L1 ``category`` (and ``reverts``), edited files
    and their role, and the background session each poll waits on, in execution order."""
    rows = actions(trajectory)
    for index, row in enumerate(rows, 1):
        row["action_index"] = index
        call = resolve_call({"function_name": row["tool"], "arguments": row["arguments"]})
        shell = call.get("function_name") in SHELL_TOOLS
        files = edited_files(call) if row["mid_level"] == "edit_file" or shell else []
        if row["mid_level"] == "edit_file" or files:
            # files: also a run that writes project files on the way
            # (``apply_patch ... && ./gradlew test``), which keeps its mid-level but whose
            # edit can anchor the phases
            row["edit_files"] = [repo_path(f) for f in files]
            row["edit_role"] = edit_role(row["edit_files"])
        else:
            row["edit_files"], row["edit_role"] = [], ""
        row["category"], row["reverts"] = category(row)
    resolve_waits(rows)
    return rows
