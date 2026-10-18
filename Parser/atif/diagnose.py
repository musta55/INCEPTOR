"""The steps of a trajectory that the lookup tables do not recognise, and the rows that would.

A step is unrecognised when the action table (``atif.lookup``) falls through to a catch-all:

``tool``     its tool is in no table (the Native tools column, ``taxonomy.TOOL_MAP``,
             ``SHELL_TOOLS``, ``EDITOR_TOOLS``, ``WRAPPER_TOOLS``), so it counts as ``other``
             ("any other tool");
``program``  it runs shell commands whose category came out ``other`` and a program in them
             is in no list (the Shell Commands column and the taxonomy's programs:
             ``taxonomy.PROGRAM_KIND``, Gradle, Python, adb, ``.sh`` scripts, ...).

A step one of the user's action rows matched (a ``category`` row) counts as recognised; a
``shell_tool`` row makes its tool known, and its commands are then checked like Bash's.  A
phase is never unrecognised on its own: it comes from the step's category and target (the
phase table), so an unrecognised step, being other, takes the phase of the previous step
(row 14).  The report counts those steps (``n_follow``).

Each group gets a suggested row from fixed name rules (no learning, no model), so the same
upload always gets the same suggestions and the user decides:

* a tool with a string argument named like a shell command (``command``, ``cmd``,
  ``script``, ...) whose values look like command lines is a **shell tool** (a ``shell_tool``
  row: its commands are then read with the Shell Commands column, like Bash's);
* otherwise a word of the tool's name gives its category (``KEYWORDS``: ``write_file`` is
  edit, ``list_dir`` orient, ``finish`` other, ...);
* a program gets its category from ``PROGRAM_HINTS`` (``cargo test`` test, ``tsc`` build,
  ``awk`` read, ...); with no hint there is no suggestion.

    unrecognized(acts, table_rows, report) -> {"n_actions", "n_unrecognized", "n_follow",
                                               "groups": [...]}

``acts`` are the analysed rows of ``rules.phases`` (its ``actions``), ``table_rows`` its
``table_row`` and ``report`` its ``rules`` (to know which steps the user's rows matched).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import lookup, taxonomy

#: argument keys that may hold a shell command, in lookup order
COMMAND_KEYS = ("command", "cmd", "commands", "script", "shell_command", "bash_command",
                "cmdline", "command_line", "keystrokes", "input")
#: words of a tool name that say it runs commands
SHELL_WORDS = {"bash", "shell", "terminal", "exec", "execute", "run", "cmd", "command",
               "console", "sh", "zsh", "powershell", "cli", "process"}
#: (category, words of a tool name), tried in this order; the first category with a word
#: in the name is suggested
KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("other", ("finish", "submit", "done", "exit", "stop", "complete", "end", "answer",
               "respond", "reply", "final", "ask", "message", "notify", "attempt")),
    ("sub-agent", ("agent", "delegate", "subagent", "spawn", "handoff", "task")),
    ("test", ("test", "tests", "pytest", "unittest")),
    ("build", ("build", "compile", "lint")),
    ("other", ("web", "browse", "browser", "fetch", "url", "http", "internet", "google",
               "download")),
    ("plan", ("plan", "todo", "todos", "think", "thought", "reflect", "note", "notes")),
    ("edit", ("edit", "write", "replace", "patch", "create", "insert", "modify",
              "apply", "save", "append", "rename", "delete", "remove", "str")),
    ("search", ("search", "grep", "find", "glob", "locate", "rg", "ripgrep",
                "lookup", "symbol", "symbols", "definition", "references")),
    ("orient", ("list", "ls", "dir", "directory", "tree", "structure", "explore", "pwd")),
    ("read", ("read", "view", "open", "cat", "show", "get", "content", "contents",
              "file", "load", "peek", "scroll", "goto")),
    ("other", ("wait", "sleep", "poll", "await", "kill", "stdin")),
]
#: a program, or a program with its first argument, and the category it suggests
PROGRAM_HINTS: Dict[str, str] = {
    **{p: "test" for p in ("jest", "mocha", "vitest", "karma", "rspec", "phpunit",
                               "nose2", "nosetests", "ava", "tap", "unittest", "behave",
                               "cucumber", "playwright", "cypress", "bats")},
    **{p: "build" for p in ("gcc", "g++", "cc", "c++", "clang", "clang++", "tsc", "rustc",
                            "kotlinc", "scalac", "msbuild", "xcodebuild", "bazel", "buck",
                            "meson", "scons", "webpack", "vite", "esbuild", "rollup",
                            "sbt", "lein", "swiftc", "go build", "cargo build",
                            "cargo check", "npm run", "yarn build", "pnpm build")},
    **{p: "other" for p in ("conda", "apt", "yum", "dnf", "apk", "pipx", "gem", "nvm",
                                "pyenv", "rustup", "sdk", "uv", "poetry", "virtualenv",
                                "touch", "rmdir", "install", "yarn install",
                                "yarn add", "pnpm install", "pnpm add", "go get",
                                "go mod", "cargo add", "bundle install", "composer install")},
    **{p: "test" for p in ("cargo test", "go test", "npm test", "yarn test", "pnpm test",
                               "dotnet test", "mix test", "swift test", "bazel test",
                               "make test", "make check", "bun test", "deno test",
                               "flutter test", "dart test", "sbt test", "rake test")},
    **{p: "read" for p in ("awk", "jq", "xxd", "od", "strings", "hexdump", "yq",
                                "zcat", "gunzip", "bzcat", "xmllint")},
    **{p: "search" for p in ("locate", "ctags", "fzf", "ugrep", "sg")},
    **{p: "orient" for p in ("date", "basename", "dirname", "realpath", "readlink", "id",
                             "hostname", "nproc", "free", "lsof", "column", "type")},
}
#: programs whose first argument says what they do (``cargo test``, ``npm install``)
FAMILIES = {"cargo", "go", "npm", "yarn", "pnpm", "bun", "deno", "dotnet", "bazel", "mix",
            "swift", "poetry", "uv", "sbt", "flutter", "dart", "gem", "bundle", "rake",
            "composer", "lein", "nx", "make"}
#: programs ``taxonomy._program_kind`` reads itself, beyond ``PROGRAM_KIND``
_HANDLED = {"adb", "bash", "sh", "zsh", "gradle", "gradlew", "mvn", "ant", "java", "java_home",
            "patch", taxonomy.PATCH_TOOL}
#: shell syntax that splits into words like a program: keywords, tests, no-ops
_SHELL_SYNTAX = {"for", "while", "until", "if", "then", "else", "elif", "fi", "do", "done",
                 "case", "esac", "function", "select", "in", "{", "}", "[", "[[", "]]", "test",
                 "true", "false", ":", "exit", "return", "read", "local", "declare", "shift",
                 "trap", "break", "continue", "let", "printf", "echo"}
EXAMPLES = 3
EXAMPLE_CHARS = 160
#: the phase-table rows that give the phase of the previous step
FOLLOW_ROWS = ("L14", "L15", lookup.GENERAL)


def _words(name: str) -> List[str]:
    """The words of a tool name: ``str_replace_editor`` -> str, replace, editor;
    ``ReadFile`` -> read, file."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "")
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def known_tool(name: str, shell_tools: set) -> bool:
    return name in lookup.NATIVE or name in taxonomy.TOOL_MAP or name in taxonomy.SHELL_TOOLS \
        or name in shell_tools or name in taxonomy.EDITOR_TOOLS or name in taxonomy.WRAPPER_TOOLS


def known_program(name: str) -> bool:
    name = name.lstrip("({!").rstrip(");}")         # a subshell or a group: (find . ...)
    return not name or name in _SHELL_SYNTAX or name in taxonomy.PROGRAM_KIND or name in _HANDLED or name in taxonomy._PYTHON \
        or name in taxonomy.PREFIX_NOISE or name in taxonomy.WRAPPERS \
        or name in taxonomy.DIFF_PROGRAMS or name in taxonomy._WRITERS \
        or name.endswith((".sh", ".bash"))


def _command_like(value: Any) -> bool:
    """A string that reads as a shell command line, not a sub-command word (``view``)."""
    return isinstance(value, str) and bool(re.search(r"\s|[/|;&>]", value.strip()))


def suggest_tool(name: str, samples: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The suggested row for an unknown tool, given the arguments of some of its calls, with
    ``why`` in words; None when no rule applies."""
    words = set(_words(name))
    for key in COMMAND_KEYS:
        values = [args.get(key) for args in samples if isinstance(args, dict) and key in args]
        if values and sum(map(_command_like, values)) * 2 >= len(values) \
                and (words & SHELL_WORDS or not words & {"edit", "editor", "view", "read",
                                                         "write", "replace", "file"}):
            return {"row": {"kind": "shell_tool", "field": "tool", "match": name,
                            "value": key},
                    "why": f"its argument “{key}” holds command lines"}
    for category, keys in KEYWORDS:
        hit = next((w for w in keys if w in words), None)
        if hit:
            return {"row": {"kind": "category", "field": "tool", "match": name,
                            "value": category},
                    "why": f"its name has the word “{hit}”"}
    return None


def suggest_program(key: str) -> Optional[Dict[str, Any]]:
    """The suggested row for an unknown program (``key``: ``tsc`` or ``cargo test``)."""
    category = PROGRAM_HINTS.get(key) or PROGRAM_HINTS.get(key.split(" ")[0])
    if not category:
        return None
    return {"row": {"kind": "category", "field": "program", "match": key, "value": category},
            "why": "a common " + {"test": "test runner", "build": "compiler or build tool",
                                  "other": "installer or set-up tool",
                                  "read": "file viewer", "search": "search tool",
                                  "orient": "system query"}.get(category, "program")}


def _program_key(name: str, tokens: List[str]) -> str:
    first = next((t for t in tokens[1:] if not t.startswith("-")), "")
    return f"{name} {first}" if name in FAMILIES and first and \
        re.fullmatch(r"[\w:.-]+", first) else name


def _example(a: dict) -> Dict[str, Any]:
    text = a.get("cmd") or a.get("target") or ""
    if not text and a.get("arguments"):
        text = " ".join(f"{k}={v}" for k, v in list(a["arguments"].items())[:3])
    return {"i": a["action_index"], "text": " ".join(str(text).split())[:EXAMPLE_CHARS]}


def unrecognized(acts: List[dict], table_rows: Optional[List[str]] = None,
                 report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The unrecognised steps of analysed rows, grouped by tool or program (most steps
    first), each group with ``n``, ``category`` (what the steps count as now), ``n_follow``,
    ``examples`` and ``suggest`` ({row, why} or None)."""
    report = report or {}
    rows = list(report.get("optional") or []) + list(report.get("custom") or [])
    by_user = {i for r in rows if r.get("kind") == "category" for i in r.get("matched") or []}
    shell_tools = {r["match"] for r in report.get("custom") or []
                   if r.get("kind") == "shell_tool" and r.get("enabled", True)}
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    total = follow = 0
    for x, a in enumerate(acts):
        if a["action_index"] in by_user:
            continue
        tool = taxonomy.resolve_call({"function_name": a["tool"],
                                      "arguments": a.get("arguments") or {}})["function_name"]
        key: Optional[Tuple[str, str]] = None
        if a["category"] == "other" and not known_tool(tool, shell_tools):
            key = ("tool", tool)
        elif a["category"] == "other" and a.get("cmd"):
            unknown = [(n, t) for n, t, _s in taxonomy.simple_commands(a["cmd"])
                       if not known_program(n)]
            if unknown:
                key = ("program", _program_key(*unknown[0]))
        if key is None:
            continue
        total += 1
        row = table_rows[x] if table_rows and x < len(table_rows) else None
        follow += row in FOLLOW_ROWS
        g = groups.setdefault(key, {"kind": key[0], "key": key[1], "n": 0, "n_follow": 0,
                                    "category": a["category"], "examples": [], "_args": []})
        g["n"] += 1
        g["n_follow"] += row in FOLLOW_ROWS
        if len(g["examples"]) < EXAMPLES:
            g["examples"].append(_example(a))
        if key[0] == "tool" and len(g["_args"]) < 20:
            g["_args"].append(a.get("arguments") or {})
    out = []
    for g in sorted(groups.values(), key=lambda g: (g["kind"] != "tool", -g["n"], g["key"])):
        args = g.pop("_args")
        g["suggest"] = suggest_tool(g["key"], args) if g["kind"] == "tool" \
            else suggest_program(g["key"])
        out.append(g)
    return {"n_actions": len(acts), "n_unrecognized": total, "n_follow": follow,
            "groups": out}
