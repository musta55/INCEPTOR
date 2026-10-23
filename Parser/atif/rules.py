"""Lookup tables: the Final lookup tables built in, ready-made rows, and the user's own rows.

The phases come from the Final lookup tables (``atif.lookup``; the annotation workbook's tab
"Final lookup table", 2026-10-17): the action table gives a step its category, the target
table gives a file its target, and the phase table gives a step its phase.  The viewer's
Lookup tables page (``viewer/tables.html``) shows them in three tiers:

``BUILTIN``  the phase table's rows 1-15 (ids L1-L15), its general rule (LG) and the
             repeated-reads flag F1.  They define what a phase is, so every analysis applies
             them as they are; a table file cannot switch them off or change them.  The action
             and target tables are built in too, and their contents are in ``contents()``.
``OPTIONAL`` O1-O4, ready-made rows a user may add (none is added by default) and remove.
``custom``   rows the user writes, each a row of one table:
             the action table (``category``): steps whose command, target or tool matches
             some text count as a category;
             the target table (``file_role``): files whose path matches some text are a target
             (source, test, docs, build, other, outside);
             the phase table (``phase``): steps whose command, target or tool matches some
             text take a phase, or the phase of the previous step;
             the action table (``shell_tool``): a tool that runs shell commands, named exactly
             in ``match``, whose command is the argument ``value`` (``command``, ``script``);
             its commands are then read with the Shell Commands column like those of Bash.
             This is how an agent the tables do not know gets its shell actions read
             (``atif.diagnose`` finds such tools in an upload).

A table file (``python3 -m atif.cli analyze / view --rules FILE``, the page's Export) is
JSON::

    {"schema": "trajectiers-tables/1",
     "optional": [{"id": "O2"}, {"id": "O4"}],
     "custom": [
        {"kind": "category", "field": "target", "match": "lint", "value": "build"},
        {"kind": "phase", "field": "tool", "match": "update_plan", "value": "follow"},
        {"kind": "file_role", "match": "src/sharedTest/", "value": "test"}]}

Older files are read: those of the rule format (``trajectiers-rules/1`` and ``/2``), whose
entries for the grouping rules of codebook version 3 (G1-G7 and their ``settings``) are
ignored, and those written for codebook version 4, whose values are mapped to the Final
tables' (the category ``run_test`` is test, ``read_file`` read; the role ``toolchain`` is the
target build, ``harness`` and ``output`` other; the phase ``understanding`` is planning).  Only
the repeated-reads number must stay 3.

A row matches an action (or, for ``file_role``, a file path) by case-insensitive text, or by
a regular expression when ``"regex": true``, and then:

``category``   counts the action as another category, before verdicts and phases are worked
               out (so ``test`` makes its result a test verdict);
``phase``      replaces the action's phase-table value (``follow``: the phase of the previous
               step).  It never breaks the invariants: an edit of a source file stays Repair,
               and the first fix bounds the pre-only and post-only phases
               (``phase.override_problem``); such a match is reported as skipped;
``file_role``  gives every file whose path matches a target, which moves the first fix, the
               reads' phases and the flags;
``shell_tool`` makes the tool a shell tool for the whole analysis, before any other row.

Ready-made rows apply first, then the user's rows in order; for one action, the last
matching row of a table wins.  Nothing is fitted: a table file is the user's explicit choice,
recorded with the result it produced.  (The module keeps its older name, ``rules``, and the
word "rule set" for a table file, so that existing files and calls keep working.)
"""
from __future__ import annotations

import contextlib
import functools
import re
import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import lookup, phase, project, taxonomy, verdict

SCHEMA = "trajectiers-tables/1"
OLD_SCHEMAS = ("trajectiers-rules/1", "trajectiers-rules/2")
KINDS = ("category", "phase", "file_role", "shell_tool")
#: the table each kind of row extends: 2 the action table, 3 the target table, 4 the phase
#: table (the numbers older files and the viewer use)
TABLE_OF = {"category": 2, "file_role": 3, "phase": 4, "shell_tool": 2}
#: what a row's text is looked for in: the command or target, the tool name, both, or the
#: programs a shell command runs (each with its first argument: ``make``, ``cargo test``),
#: where plain text matches a whole program name, not part of one
FIELDS = ("target", "tool", "any", "program")
#: the argument key a shell-tool row may name (``command``, ``cmd``, ``script``)
_ARG_KEY = re.compile(r"^[A-Za-z_][\w.-]{0,63}$")
FOLLOW = phase.FOLLOW
#: the grouping rules of codebook version 3 and the built-in rows of version 4 (Table 4,
#: follow); older files may name them, and they are ignored
LEGACY_IDS = {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "FW"} | {f"P{n}" for n in range(1, 12)}
#: the values of codebook version 4's tables, in the Final tables' words
OLD_VALUES = {
    "category": dict(lookup.KIND_CATEGORY),
    "file_role": {"toolchain": "build", "harness": "other", "output": "other"},
    "phase": {"understanding": "planning", "reproduction": "localization"},
}


def _lookup_rows() -> List[Dict[str, Any]]:
    """The phase table, one entry per row, and its general rule: the table's words and one
    plain sentence."""
    out = []
    for n, (rid, ph, cats, target, where) in enumerate(lookup.PHASE_TABLE, 1):
        to = "the phase of the previous step" if ph == lookup.PREVIOUS else ph
        on = "" if target == "any" else f" on {target}"
        out.append({"id": rid, "n": n, "table": 4, "title": f"Rule {n}", "phase": ph,
                    "categories": cats, "target": target, "position": where,
                    "text": f"{cats}{on}, {where[0].lower() + where[1:]} → {to}."})
    out.append({"id": lookup.GENERAL, "n": None, "table": 4, "title": "General rule",
                "text": lookup.GENERAL_RULE})
    return out


#: Always applied, in the table's order; not part of any table file.  ``{n}`` in a sentence
#: is the fixed number.
BUILTIN: List[Dict[str, Any]] = _lookup_rows() + [
    {"id": "F1", "table": 0, "title": "Repeated reads", "value": phase.REPEATED_READS,
     "text": "Reading the same file {n} or more times consecutively is considered as repeated "
             "reads."},
]
BUILTIN_IDS = {r["id"] for r in BUILTIN}
MANDATORY = BUILTIN                 # the name of the built-in tier until 2026-10-14
MANDATORY_IDS = BUILTIN_IDS

#: Ready-made rows a user may add (none is added by default) and remove; each is a row of
#: the same shape as a user's own.
OPTIONAL: List[Dict[str, Any]] = [
    {"id": "O1", "title": "Lint is a build, not a test",
     "text": "Gradle lint and static-analysis tasks (lint, ktlint, detekt, checkstyle, "
             "spotbugs, pmd) count as builds.",
     "rule": {"kind": "category", "field": "target", "regex": True, "value": "build",
              "match": r"gradlew?\b[^|;&]*\b\w*(?:lint|detekt|checkstyle|spotbugs|pmd)\w*"}},
    {"id": "O2", "title": "Shared test code",
     "text": "Files under sharedTest/ or tests/ are test files: changing them is localization "
             "before the first fix and validation after.",
     "rule": {"kind": "file_role", "field": "path", "regex": True, "value": "test",
              "match": r"(?:^|/)(?:sharedTest|testFixtures|tests)/"}},
    {"id": "O3", "title": "Project docs are planning",
     "text": "A step that names README, AGENTS.md, CONTRIBUTING or the agent's instruction "
             "file is planning, wherever it comes and whatever else it reads.",
     "rule": {"kind": "phase", "field": "target", "regex": True, "value": "planning",
              "match": r"(?:^|[\s/'\"])(?:README|CONTRIBUTING|AGENTS|CLAUDE|QWEN|GEMINI)\b"
                       r"[\w.-]*"}},
    {"id": "O4", "title": "Web lookups are localization",
     "text": "Web searches and fetches (WebSearch, WebFetch, web_search, curl, wget) are "
             "localization, instead of taking the phase of the previous step.",
     "rule": {"kind": "phase", "field": "any", "regex": True, "value": "localization",
              "match": r"^(?:WebFetch|WebSearch|web_search|web_fetch)\b|\s(?:curl|wget)\s"}},
]
OPTIONAL_BY_ID = {r["id"]: r for r in OPTIONAL}

#: ``lookup.target`` and ``taxonomy.file_role`` are swapped while a rule set with file-role
#: rows runs; the lock keeps two analyses from seeing each other's targets
_LOCK = threading.RLock()


class RuleError(ValueError):
    """A rule set that cannot be applied, with a message for the user."""


# ----------------------------------------------------------------------------- the rule set
def default_ruleset() -> Dict[str, Any]:
    return {"schema": SCHEMA, "optional": [], "custom": []}


def mandatory() -> List[Dict[str, Any]]:
    """The built-in rows (the phase table, its general rule, F1) as the viewer shows them:
    always applied."""
    return [{**r, "sentence": r["text"].replace("{n}", str(r.get("value", ""))),
             "mandatory": True, "on": True} for r in BUILTIN]


def optional(added: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Every ready-made row, with ``on`` when it is in ``added`` (default: none)."""
    chosen = {o["id"] for o in added or []}
    return [{**{k: v for k, v in r.items() if k != "rule"}, "kind": r["rule"]["kind"],
             "table": TABLE_OF[r["rule"]["kind"]], "sentence": r["text"], "mandatory": False,
             "on": r["id"] in chosen} for r in OPTIONAL]


def builtin(ruleset: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The built-in rows, then the ready-made ones (each with ``on``) of a normalised table
    file (default: the defaults); ``vocab.rules`` of the viewer data."""
    return mandatory() + optional((ruleset or {}).get("optional"))


SAME = "the step takes the phase of the previous step (the first step of a trajectory: planning)"


def tables() -> Dict[str, Any]:
    """The tables in short, for the viewer's legends: ``actions`` (type, what it is,
    examples), ``phases`` (id, n, phase, categories, target, position) and ``same``."""
    return {
        "actions": [{"type": cat, "does": lookup.CATEGORY_TEXT[cat],
                     "examples": "; ".join(x for x in (shell, native) if x)}
                    for cat, shell, native in lookup.ACTION_TABLE],
        "phases": [{k: r[k] for k in ("id", "n", "phase", "categories", "target", "position")}
                   for r in BUILTIN if r["table"] == 4 and r["n"]],
        "same": SAME,
    }


#: the agents of the table's Native tools column, as the table names them
_TABLE_AGENTS = {"Claude": "Claude Code", "Codex": "Codex CLI", "Qwen": "Qwen Code"}
#: the shell tools beyond the corpus, and whose they are (``taxonomy.SHELL_TOOLS``)
_OTHER_SHELL_AGENTS = {"execute_bash": "OpenHands", "bash": "mini-swe-agent, Trae Agent",
                       "bash_command": "Terminus-2", "shell": "Codex CLI (older)"}


def _by_agent(cell: str) -> List[Dict[str, Any]]:
    """The tool names of a Native tools cell, by agent: ``Read (Claude), read_file (Qwen)``."""
    out: Dict[str, List[str]] = {}
    for m in re.finditer(r"([\w ,]+?)\s*\((Claude|Codex|Qwen)\)", cell or ""):
        names = [x.strip() for x in m.group(1).split(",") if re.fullmatch(r"\w+", x.strip())]
        if names:
            out.setdefault(_TABLE_AGENTS[m.group(2)], []).extend(names)
    return [{"agent": a, "names": n} for a, n in out.items()]


def contents() -> Dict[str, Any]:
    """Everything the built-in tables hold, for the viewer's Lookup tables page:

    ``version``     the tables' name and date
    ``actions``     the action table, per category: ``shell`` and ``native`` (its two columns,
                    word for word), ``does`` (a few words), ``family``, ``tools`` (the native
                    tools by agent) and ``other_agents`` (tools of agents outside the corpus
                    that count as it, beyond the table)
    ``shell_tools`` the shell runners, by agent; ``ignored`` and ``compound``: the table's rows
                    for the programs it skips and for a line of several programs
    ``targets``     the target table: target, its name, which files
    ``phases``      the phase table's rows in order (``n``: 1-15), word for word
    ``general``     its general rule; ``same``: what "the phase of the previous step" means"""
    named = {n for _, _, native in lookup.ACTION_TABLE for x in _by_agent(native)
             for n in x["names"]} | lookup.TABLE_OTHER_TOOLS | set(taxonomy.SHELL_TOOLS)
    beyond: Dict[str, List[str]] = {}
    for tool, kind in list(taxonomy.TOOL_MAP.items()) + [
            (t, "edit_file") for t in taxonomy.EDITOR_TOOLS]:
        if tool not in named:
            beyond.setdefault(lookup.KIND_CATEGORY.get(kind, "other"), []).append(tool)
    shell = [{"agent": _TABLE_AGENTS[m.group(2)], "names": [m.group(1)]} for m in
             re.finditer(r"(\w+) \((Claude|Codex|Qwen)\)", lookup.SHELL_RUNNER_ROW[1])]
    shell += [{"agent": _OTHER_SHELL_AGENTS.get(t, "other agents"), "names": [t]}
              for t in sorted(taxonomy.SHELL_TOOLS) if not any(t in x["names"] for x in shell)]
    return {
        "version": lookup.VERSION, "version_date": lookup.VERSION_DATE,
        "actions": [{"type": cat, "family": lookup.CATEGORY_FAMILY[cat],
                     "does": lookup.CATEGORY_TEXT[cat], "shell": shell_cell,
                     "native": native, "tools": _by_agent(native),
                     "other_agents": beyond.get(cat, [])}
                    for cat, shell_cell, native in lookup.ACTION_TABLE],
        "shell_tools": shell, "ignored": lookup.IGNORED_ROW[1],
        "compound": lookup.COMPOUND_ROW[1],
        "targets": [{"target": t, "name": name, "files": files}
                    for t, name, files in lookup.TARGET_TABLE],
        "targets_swebench": "SWE-bench runs (Python repositories): tests/ and test_*.py files, "
                            "and a script the agent writes at the repository root or outside "
                            "it (/tmp/repro.py), are test files; setup.py, pyproject.toml, "
                            "tox.ini and the like are build files.",
        "phases": [{k: r[k] for k in ("id", "n", "phase", "categories", "target", "position")}
                   for r in BUILTIN if r["table"] == 4 and r["n"]],
        "general": lookup.GENERAL_RULE, "same": SAME,
    }


def _regex(rule: Dict[str, Any]) -> "re.Pattern[str]":
    text = str(rule.get("match") or "")
    try:
        return _compile(text, bool(rule.get("regex")), rule.get("field") == "program")
    except re.error as exc:
        raise RuleError(f"rule {rule.get('id') or ''}: bad regular expression {text!r} ({exc})")


@functools.lru_cache(maxsize=256)
def _compile(text: str, regex: bool, program: bool = False) -> "re.Pattern[str]":
    if program and not regex:            # a whole program name, at the start of a line
        return re.compile(r"(?m)^" + re.escape(text.strip()) + r"(?=\s|$)", re.IGNORECASE)
    return re.compile(text if regex else re.escape(text), re.IGNORECASE)


def _fixed(rid: str, value: Any) -> None:
    """A file that names F1 is accepted while it asks for the fixed number, and refused
    otherwise."""
    rule = next(r for r in BUILTIN if r["id"] == rid)
    if value is not None and value != rule["value"]:
        raise RuleError(f"{rid} ({rule['title'].lower()}) is built in with the fixed number "
                        f"{rule['value']}; it cannot be set to {value}")


def _from_settings(settings: Dict[str, Any]) -> None:
    """Check the ``settings`` of a ``trajectiers-rules/1`` file: the grouping-rule settings
    of codebook version 3 are ignored; the repeated-reads number must stay the built-in one."""
    known = {"keep_attempts", "smoothing", "absorb_max", "repeated_reads"}
    unknown = set(settings) - known
    if unknown:
        raise RuleError(f"unknown setting {sorted(unknown)[0]!r}")
    _fixed("F1", settings.get("repeated_reads"))


def normalize(ruleset: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A checked copy of a table file (``None``: the defaults), in the current schema.
    Raises RuleError, naming the row, for an unknown schema or ready-made row, a change to a
    built-in row, an unknown kind, field or value, an empty match or a bad regular
    expression.  The version-3 grouping rules an older file names are ignored."""
    ruleset = ruleset or {}
    if not isinstance(ruleset, dict):
        raise RuleError("a table file is a JSON object")
    schema = ruleset.get("schema")
    if schema not in (None, SCHEMA) + OLD_SCHEMAS:
        raise RuleError(f"unknown schema {schema!r}: expected {SCHEMA}")
    given = ruleset.get("optional") or []
    if not isinstance(given, list):
        raise RuleError("optional is a list of {\"id\": ...}")
    if ruleset.get("settings"):
        _from_settings(ruleset["settings"])
    added = set()
    for entry in given:
        rid = entry if isinstance(entry, str) else entry.get("id") \
            if isinstance(entry, dict) else None
        if rid == "F1":
            _fixed(rid, entry.get("value") if isinstance(entry, dict) else None)
            continue                                   # built in: always applied
        if rid in LEGACY_IDS:
            continue                                   # a version-3 grouping rule: gone
        if rid in BUILTIN_IDS:
            raise RuleError(f"{rid} is a built-in rule of the phase table: it is always "
                            f"applied and cannot be listed, switched off or removed")
        if rid not in OPTIONAL_BY_ID:
            raise RuleError(f"unknown ready-made rule {rid!r}")
        added.add(rid)
    chosen = [{"id": r["id"]} for r in OPTIONAL if r["id"] in added]     # catalog order
    custom = []
    for n, rule in enumerate(ruleset.get("custom") or [], 1):
        if not isinstance(rule, dict):
            raise RuleError(f"rule {n} is not an object")
        rid = str(rule.get("id") or f"R{n}")
        if rid in BUILTIN_IDS or rid in OPTIONAL_BY_ID:
            raise RuleError(f"rule {n}: the id {rid} belongs to a built-in or ready-made rule")
        custom.append(_custom(rule, rid))
    ids = [r["id"] for r in custom]
    if len(set(ids)) != len(ids):
        raise RuleError("two rules share an id")
    return {"schema": SCHEMA, "optional": chosen, "custom": custom}


def _custom(rule: Dict[str, Any], rid: str) -> Dict[str, Any]:
    kind = rule.get("kind")
    if kind not in KINDS:
        raise RuleError(f"rule {rid}: kind must be one of {', '.join(KINDS)}")
    field = "path" if kind == "file_role" else "tool" if kind == "shell_tool" \
        else rule.get("field") or "target"
    if kind != "file_role" and field not in FIELDS:
        raise RuleError(f"rule {rid}: field must be one of {', '.join(FIELDS)}")
    match = str(rule.get("match") or "")
    if not match.strip():
        raise RuleError(f"rule {rid}: the text to match is empty")
    value = rule.get("value")
    if kind == "shell_tool":
        if not isinstance(value, str) or not _ARG_KEY.match(value):
            raise RuleError(f"rule {rid}: a shell tool's value is the argument that holds its "
                            f"command, such as command or cmd")
        return {"id": rid, "kind": kind, "field": field, "match": match.strip(),
                "regex": False, "value": value,
                "enabled": rule.get("enabled", True) is not False}
    allowed = {"category": lookup.CATEGORIES,
               "phase": phase.PHASES + (FOLLOW,),
               "file_role": lookup.TARGETS}[kind]
    value = OLD_VALUES[kind].get(value, value)       # a value of codebook version 4
    if value not in allowed:
        raise RuleError(f"rule {rid}: {kind} must be one of {', '.join(allowed)}")
    item = {"id": rid, "kind": kind, "field": field, "match": match,
            "regex": bool(rule.get("regex")), "value": value,
            "enabled": rule.get("enabled", True) is not False}
    _regex(item)
    return item


def _active(ruleset: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The matching rules that run: the added ready-made ones, then the enabled custom ones."""
    ready = [{**OPTIONAL_BY_ID[o["id"]]["rule"], "id": o["id"], "enabled": True}
             for o in ruleset["optional"] if "rule" in OPTIONAL_BY_ID[o["id"]]]
    return ready + [r for r in ruleset["custom"] if r["enabled"]]


def describe(rule: Dict[str, Any]) -> str:
    """One plain sentence for a user's row (the viewer builds the same words:
    ``TV.ruleSentence``)."""
    how = "matches" if rule.get("regex") else "contains"
    quoted = f"“{rule['match']}”"
    if rule["kind"] == "file_role":
        return f"Files whose path {how} {quoted} are {TARGET_PHRASE.get(rule['value'], rule['value'])}."
    if rule["kind"] == "shell_tool":
        return (f"The tool {quoted} runs shell commands (its argument “{rule['value']}”); "
                f"they are read like Bash commands.")
    if rule["field"] == "program" and not rule.get("regex"):
        if rule["kind"] == "category":
            return f"Steps that run {quoted} are {rule['value']}."
        if rule["value"] == FOLLOW:
            return f"Steps that run {quoted} take the phase of the step before."
        return f"Steps that run {quoted} belong to {rule['value']}."
    subject = {"target": "Steps whose command", "tool": "Steps whose tool",
               "any": "Steps whose command or tool",
               "program": "Steps whose programs"}[rule["field"]]
    if rule["kind"] == "category":
        return f"{subject} {how} {quoted} are {rule['value']}."
    if rule["value"] == FOLLOW:
        return f"{subject} {how} {quoted} take the phase of the step before."
    return f"{subject} {how} {quoted} belong to {rule['value']}."


#: a target in a row's sentence: "Files whose path contains … are <phrase>."
TARGET_PHRASE = {"source": "source files", "test": "test files", "docs": "docs",
                 "build": "build files", "other": "other repository files",
                 "outside": "outside the repository"}


# ----------------------------------------------------------------------------- matching
def programs(command: str) -> str:
    """The programs a shell command runs, one per line, each with its first argument that is
    not an option (``make all``, ``cargo test``, ``npm run``): what a ``program`` row reads."""
    out = []
    for name, tokens, _segment in taxonomy.simple_commands(command or ""):
        first = next((t for t in tokens[1:] if not t.startswith("-")), "")
        out.append(f"{name} {first}".strip())
    return "\n".join(out)


def _subject(row: dict, field: str) -> str:
    target = " ".join(x for x in (row.get("cmd") or row.get("command") or "",
                                  row.get("target") or "") if x)
    if field == "tool":
        return row.get("tool") or ""
    if field == "program":
        return programs(row.get("cmd") or row.get("command") or "")
    if field == "any":
        return f"{row.get('tool') or ''} {target}"
    return target


@contextlib.contextmanager
def _file_roles(rules: List[Dict[str, Any]]) -> Iterator[None]:
    """Swap the target table (``lookup.target``) for one that applies the file-role rows
    first, and the taxonomy's edit roles (``taxonomy.file_role``: source, test, toolchain,
    which the flags read) to match: a build row is toolchain, the other targets keep the
    built-in role."""
    if not rules:
        yield
        return
    compiled = [(_regex(r), r["value"]) for r in rules]
    target, file_role = lookup.target, taxonomy.file_role

    def role_of(path: str) -> Optional[str]:
        found = None
        for pattern, value in compiled:
            if pattern.search(str(path)):
                found = value
        return found

    def new_target(path: str) -> str:
        if not str(path or "").strip("\"' "):
            return ""
        return role_of(path) or target(path)

    def new_file_role(path: str) -> str:
        role = {"source": "source", "test": "test", "build": "toolchain"}.get(role_of(path) or "")
        return role or file_role(path)

    lookup.target, taxonomy.file_role = new_target, new_file_role
    try:
        yield
    finally:
        lookup.target, taxonomy.file_role = target, file_role


@contextlib.contextmanager
def _shell_tools(rules: List[Dict[str, Any]]) -> Iterator[None]:
    """Make the tools of the shell-tool rows shell tools (``taxonomy.SHELL_TOOLS``), with
    their command arguments looked up after the built-in keys, for one analysis."""
    tools = [r["match"] for r in rules if r["match"] not in taxonomy.SHELL_TOOLS]
    keys = taxonomy.SHELL_COMMAND_KEYS
    extra = tuple(dict.fromkeys(r["value"] for r in rules if r["value"] not in keys))
    taxonomy.SHELL_TOOLS.update(tools)
    taxonomy.SHELL_COMMAND_KEYS = keys + extra
    try:
        yield
    finally:
        taxonomy.SHELL_TOOLS.difference_update(tools)
        taxonomy.SHELL_COMMAND_KEYS = keys


def _recategorize(row: dict, category: str, rid: str) -> None:
    """Count a row as ``category`` (``lookup.set_category``): its kind and mid-level follow,
    and only an edit keeps its edited files."""
    lookup.set_category(row, category, f"your rule {rid}")
    row["reverts"] = False
    if category != "edit":
        row["edit_files"], row["edit_role"] = [], ""
    elif not row.get("edit_role"):
        row["edit_role"] = taxonomy.edit_role(row.get("edit_files") or [])


def prepare(trajectory: dict, bug_id: str, rules: List[Dict[str, Any]]
            ) -> Tuple[List[dict], Dict[str, List[int]]]:
    """``segment.prepare`` with the category rows applied between the action table and the
    verdicts.  Returns (rows, {rule id: action indexes it recategorised})."""
    rows = taxonomy.annotate(trajectory)
    lookup.annotate(rows)
    hits: Dict[str, List[int]] = {r["id"]: [] for r in rules}
    for row in rows:
        row["cmd"] = taxonomy.shell_command({"function_name": row["tool"],
                                             "arguments": row.get("arguments") or {}})
        chosen = None
        for rule in rules:
            if _regex(rule).search(_subject(row, rule["field"])):
                chosen = rule
        if chosen is not None:
            hits[chosen["id"]].append(row["action_index"])
            if (chosen["value"], lookup.CATEGORY_KIND[chosen["value"]][1]) \
                    != (row["category"], row["mid_level"]):     # the run is read as it, too
                _recategorize(row, chosen["value"], chosen["id"])
    taxonomy.resolve_waits(rows)
    verdict.attach(rows)
    for row in rows:
        row["bug_id"] = str(bug_id)
        row["args"] = row.get("arguments") or {}
    return rows, hits


def phases(trajectory: dict, bug_id: str, ruleset: Optional[Dict[str, Any]] = None,
           targets: Optional[List[str]] = None) -> Dict[str, Any]:
    """``phase.phases`` under a table file.  The result also carries ``rules``: the
    normalised file, the built-in rows (``mandatory``, the name the viewer reads), every
    ready-made row (``on`` or not) and every user row, each with its sentence and, when it
    ran, the actions it changed (``matched``) and, for phase rows, those it could not change
    (``skipped``, with why)."""
    ruleset = normalize(ruleset)
    on = _active(ruleset)
    by_kind = {k: [r for r in on if r["kind"] == k] for k in KINDS}
    with _LOCK, project.use(trajectory), _file_roles(by_kind["file_role"]), \
            _shell_tools(by_kind["shell_tool"]):
        acts, cat_hits = prepare(trajectory, bug_id, by_kind["category"])
        wanted: Dict[int, str] = {}
        owner: Dict[int, str] = {}
        for x, a in enumerate(acts):
            for rule in by_kind["phase"]:
                if _regex(rule).search(_subject(a, rule["field"])):
                    wanted[x] = phase.NEUTRAL if rule["value"] == FOLLOW else rule["value"]
                    owner[x] = rule["id"]
        result = phase.assign(acts, targets, overrides=wanted)    # F1: fixed number
        result["actions"] = acts
        phase.check_hierarchy(acts, result, name=f"bug-{bug_id}")
        role_hits = _file_hits(acts, by_kind["file_role"])
    status = result.get("overrides") or {}

    def hits(rule: Dict[str, Any]) -> Dict[str, list]:
        """The actions a matching rule changed, and those it could not (phase rules)."""
        out: Dict[str, list] = {"matched": [], "skipped": []}
        if rule["kind"] == "category":
            out["matched"] = cat_hits.get(rule["id"], [])
        elif rule["kind"] == "shell_tool":
            out["matched"] = [a["action_index"] for a in acts if a["tool"] == rule["match"]]
        elif rule["kind"] == "file_role":
            out["matched"] = role_hits.get(rule["id"], [])
        else:
            for x, rid in owner.items():
                if rid == rule["id"]:
                    index = acts[x]["action_index"]
                    if status.get(x):
                        out["skipped"].append({"i": index, "why": status[x]})
                    else:
                        out["matched"].append(index)
        return out

    by_id = {r["id"]: r for r in on}
    optional_report = []
    for item in optional(ruleset["optional"]):
        if item["on"] and item["id"] in by_id:
            item.update(hits(by_id[item["id"]]))
        optional_report.append(item)
    custom_report = []
    for rule in ruleset["custom"]:
        item = {**rule, "table": TABLE_OF[rule["kind"]], "sentence": describe(rule),
                "matched": [], "skipped": []}
        if rule["enabled"]:
            item.update(hits(rule))
        custom_report.append(item)
    result["rules"] = {"schema": SCHEMA, "ruleset": ruleset, "mandatory": mandatory(),
                       "optional": optional_report, "custom": custom_report}
    return result


def _file_hits(acts: List[dict], rules: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """{file-role rule id: actions that touch or edit a file whose path it matches}."""
    out: Dict[str, List[int]] = {r["id"]: [] for r in rules}
    for a in acts:
        paths = list(a.get("files") or []) + list(a.get("edit_files") or []) \
            + list(a.get("targets") or [])
        for rule in rules:
            pattern = _regex(rule)
            if any(pattern.search(p) for p in paths):
                out[rule["id"]].append(a["action_index"])
    return out
