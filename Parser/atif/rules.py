"""Rule sets: mandatory rules, optional rules, and the user's own (custom) rules.

Three tiers, each shown as one plain sentence per rule in the viewer (Rules popover; Rules
card of ``viewer/analyze.html``):

``MANDATORY``  G1-G7 of the codebook (Table 4) and the repeated-reads flag F1: the first fix,
               the phase table, preparation, attempts, neutral rows, sub-agents, short
               interruptions.  They define what a phase is and give the corpus its results,
               so every analysis applies them, with their fixed numbers: a rule set cannot
               switch them off, remove them or change their numbers.
``OPTIONAL``   O1-O4, ready-made rules a user may add (none is added by default) and remove.
``custom``     rules the user writes: set the phase or the category of the actions whose
               command, target or tool matches some text, or the role of the files whose path
               does.

A rule set (``python3 -m atif.cli analyze / view --rules FILE``, the Analyze page's
Export) is JSON::

    {"schema": "trajectiers-rules/2",
     "optional": [{"id": "O2"}, {"id": "O4"}],
     "custom": [
        {"kind": "category", "field": "target", "match": "lint", "value": "build"},
        {"kind": "phase", "field": "tool", "match": "update_plan", "value": "follow"},
        {"kind": "file_role", "match": "src/sharedTest/", "value": "test"}]}

``optional`` lists the optional rules that are added.  Older files are still read when they
only restate the mandatory rules: ``{"id": "G7", "value": 1}`` / ``{"id": "F1", "value": 3}``
entries (G7 and F1 were optional, with a number, for part of 2026-10-11) and the
``settings`` of ``trajectiers-rules/1``; one that switches a mandatory rule off or changes
its number is refused.

A custom or ready-made rule matches an action (or, for ``file_role``, a file path) by
case-insensitive text, or by a regular expression when ``"regex": true``, and then:

``category``   counts the action as another L1 category, before verdicts and phases are
               worked out (so ``run_test`` makes its result a test verdict);
``phase``      puts the action in a phase (``follow``: let it take the phase of the work
               around it, rule G5).  It replaces the table's phase (P1) and survives K1 and
               G7, but it never breaks a mandatory rule: an edit of app source stays Repair,
               and the first fix bounds the pre-only and post-only phases (G1,
               ``phase.override_problem``); such a match is reported as skipped;
``file_role``  gives every file whose path matches a role (source, test, toolchain, harness,
               docs), which moves the first fix, the lookups' phases and the flags.

Ready-made rules apply first, then custom rules in order; for one action, the last matching
rule of a kind wins.  Nothing is fitted: a rule set is the user's explicit choice, recorded
with the result it produced.
"""
from __future__ import annotations

import contextlib
import functools
import re
import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import phase, taxonomy, verdict

SCHEMA = "trajectiers-rules/2"
KINDS = ("category", "phase", "file_role")
FIELDS = ("target", "tool", "any")
FOLLOW = "follow"
#: the L1 category an override sets -> the mid-level the verdict parser and the segmenter
#: read (``taxonomy.category`` refines a mid-level into these two)
_MID_OF = {"shell_edit": "edit_file", "diff": "vcs"}
_EDITS = ("edit_file", "shell_edit")

#: Always applied, in the codebook's order; not part of any rule set.  ``{n}`` in a sentence
#: is the rule's fixed number.
MANDATORY: List[Dict[str, Any]] = [
    {"id": "G1", "title": "First fix",
     "text": "The first edit of the app's source code is the first fix: understanding and "
             "reproduction come only before it, repair and validation only after it."},
    {"id": "G2", "title": "Phase from the action",
     "text": "Each action gets a phase based on what it does, thoughts of the agent and observation of the results."},
    {"id": "G3", "title": "Preparation joins its run",
     "text": "A build or setup command belongs to the test run it prepares."},
    {"id": "G4", "title": "Attempts",
     "text": "Code edit and then run the code means an repair attempt"},
    {"id": "G5", "title": "Neutral actions follow",
     "text": "Neutral actions, such as ls, plan updates or git status is considered as "
             "previous phase"},
    {"id": "G6", "title": "Sub-agents",
     "text": "A sub-agent's work counts as one block: repair if it edits app code, otherwise "
             "localization."},
    {"id": "G7", "title": "Short interruptions", "value": phase.ABSORB_MAX,
     "text": "A stretch of at most {n} action between two stretches of the same phase joins "
             "them."},
    {"id": "F1", "title": "Repeated reads", "value": phase.REPEATED_READS,
     "text": "Reading the same file {n} or more times in a row is considered as repeated "
             "reads."},
]
MANDATORY_IDS = {r["id"] for r in MANDATORY}

#: Ready-made rules a user may add (none is added by default) and remove; each is a
#: matching rule of the same shape as a custom one.
OPTIONAL: List[Dict[str, Any]] = [
    {"id": "O1", "title": "Lint is a build, not a test",
     "text": "Gradle lint and static-analysis tasks (lint, ktlint, detekt, checkstyle, "
             "spotbugs, pmd) count as builds.",
     "rule": {"kind": "category", "field": "target", "regex": True, "value": "build",
              "match": r"gradlew?\b[^|;&]*\b\w*(?:lint|detekt|checkstyle|spotbugs|pmd)\w*"}},
    {"id": "O2", "title": "Shared test code",
     "text": "Files under sharedTest/ or tests/ are test files. Then, it will fall under validation phase.",
     "rule": {"kind": "file_role", "field": "path", "regex": True, "value": "test",
              "match": r"(?:^|/)(?:sharedTest|testFixtures|tests)/"}},
    {"id": "O3", "title": "Project docs are orientation",
     "text": "Reading README, AGENTS.md, CONTRIBUTING or the agent's instruction file before "
             "the first fix is understanding.",
     "rule": {"kind": "phase", "field": "target", "regex": True, "value": "understanding",
              "match": r"(?:^|[\s/'\"])(?:README|CONTRIBUTING|AGENTS|CLAUDE|QWEN|GEMINI)\b"
                       r"[\w.-]*"}},
    {"id": "O4", "title": "Web lookups are localization",
     "text": "Web searches and fetches (WebSearch, WebFetch, web_search, curl, wget) are "
             "localization, instead of following the work around them.",
     "rule": {"kind": "phase", "field": "any", "regex": True, "value": "localization",
              "match": r"^(?:WebFetch|WebSearch|web_search|web_fetch)\b|\s(?:curl|wget)\s"}},
]
OPTIONAL_BY_ID = {r["id"]: r for r in OPTIONAL}

#: ``taxonomy.file_role`` / ``object_role`` are swapped while a rule set with file-role
#: rules runs; the lock keeps two analyses from seeing each other's roles
_LOCK = threading.RLock()


class RuleError(ValueError):
    """A rule set that cannot be applied, with a message for the user."""


# ----------------------------------------------------------------------------- the rule set
def default_ruleset() -> Dict[str, Any]:
    return {"schema": SCHEMA, "optional": [], "custom": []}


def mandatory() -> List[Dict[str, Any]]:
    """The mandatory rules as the viewer shows them."""
    return [{**r, "sentence": r["text"].replace("{n}", str(r.get("value", ""))),
             "mandatory": True, "on": True} for r in MANDATORY]


def optional(added: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Every optional rule, with ``on`` when it is in ``added`` (default: none)."""
    chosen = {o["id"] for o in added or []}
    return [{**{k: v for k, v in r.items() if k != "rule"}, "kind": r["rule"]["kind"],
             "sentence": r["text"], "mandatory": False, "on": r["id"] in chosen}
            for r in OPTIONAL]


def builtin(ruleset: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Mandatory rules, then the optional ones (each with ``on``) of a normalised rule set
    (default: the defaults); ``vocab.rules`` of the viewer data."""
    return mandatory() + optional((ruleset or {}).get("optional"))


def _regex(rule: Dict[str, Any]) -> "re.Pattern[str]":
    text = str(rule.get("match") or "")
    try:
        return _compile(text, bool(rule.get("regex")))
    except re.error as exc:
        raise RuleError(f"rule {rule.get('id') or ''}: bad regular expression {text!r} ({exc})")


@functools.lru_cache(maxsize=256)
def _compile(text: str, regex: bool) -> "re.Pattern[str]":
    return re.compile(text if regex else re.escape(text), re.IGNORECASE)


def _fixed(rid: str, value: Any) -> None:
    """A rule file that names G7 or F1 (optional rules with a number until 2026-10-11) is
    accepted while it asks for the fixed number, and refused otherwise."""
    rule = next(r for r in MANDATORY if r["id"] == rid)
    if value is not None and value != rule["value"]:
        raise RuleError(f"{rid} ({rule['title'].lower()}) is a mandatory rule with the fixed "
                        f"number {rule['value']}; it cannot be set to {value}")


def _from_settings(settings: Dict[str, Any]) -> None:
    """Check a ``trajectiers-rules/1`` ``settings`` object: it may only restate the
    mandatory rules."""
    known = {"keep_attempts", "smoothing", "absorb_max", "repeated_reads"}
    unknown = set(settings) - known
    if unknown:
        raise RuleError(f"unknown setting {sorted(unknown)[0]!r}")
    if settings.get("keep_attempts") is False:
        raise RuleError("G4 (attempts) is a mandatory rule and cannot be switched off")
    if settings.get("smoothing") is False:
        raise RuleError("G7 (short interruptions) is a mandatory rule and cannot be "
                        "switched off")
    _fixed("G7", settings.get("absorb_max"))
    _fixed("F1", settings.get("repeated_reads"))


def normalize(ruleset: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A checked copy of a rule set (``None``: the defaults).  Raises RuleError, naming the
    rule, for an attempt to change a mandatory rule, an unknown optional rule, an unknown
    kind, field or value, an empty match or a bad regular expression."""
    ruleset = ruleset or {}
    if not isinstance(ruleset, dict):
        raise RuleError("a rule set is a JSON object")
    given = ruleset.get("optional") or []
    if not isinstance(given, list):
        raise RuleError("optional is a list of {\"id\": ...}")
    if ruleset.get("settings"):
        _from_settings(ruleset["settings"])
    added = set()
    for entry in given:
        rid = entry if isinstance(entry, str) else entry.get("id") \
            if isinstance(entry, dict) else None
        if rid in ("G7", "F1"):
            _fixed(rid, entry.get("value") if isinstance(entry, dict) else None)
            continue                                   # mandatory now: always applied
        if rid in MANDATORY_IDS:
            raise RuleError(f"{rid} is a mandatory rule: it is always applied and cannot be "
                            f"listed, switched off or removed")
        if rid not in OPTIONAL_BY_ID:
            raise RuleError(f"unknown optional rule {rid!r}")
        added.add(rid)
    chosen = [{"id": r["id"]} for r in OPTIONAL if r["id"] in added]     # catalog order
    custom = []
    for n, rule in enumerate(ruleset.get("custom") or [], 1):
        if not isinstance(rule, dict):
            raise RuleError(f"custom rule {n} is not an object")
        rid = str(rule.get("id") or f"R{n}")
        if rid in MANDATORY_IDS or rid in OPTIONAL_BY_ID:
            raise RuleError(f"custom rule {n}: the id {rid} belongs to a built-in rule")
        custom.append(_custom(rule, rid))
    ids = [r["id"] for r in custom]
    if len(set(ids)) != len(ids):
        raise RuleError("two custom rules share an id")
    return {"schema": SCHEMA, "optional": chosen, "custom": custom}


def _custom(rule: Dict[str, Any], rid: str) -> Dict[str, Any]:
    kind = rule.get("kind")
    if kind not in KINDS:
        raise RuleError(f"rule {rid}: kind must be one of {', '.join(KINDS)}")
    field = "path" if kind == "file_role" else rule.get("field") or "target"
    if kind != "file_role" and field not in FIELDS:
        raise RuleError(f"rule {rid}: field must be one of {', '.join(FIELDS)}")
    match = str(rule.get("match") or "")
    if not match.strip():
        raise RuleError(f"rule {rid}: the text to match is empty")
    value = rule.get("value")
    allowed = {"category": taxonomy.CATEGORIES,
               "phase": phase.PHASES + (FOLLOW,),
               "file_role": taxonomy.OBJECT_ROLES}[kind]
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
    """One plain sentence for a custom rule (the viewer builds the same words)."""
    how = "matches" if rule.get("regex") else "contains"
    quoted = f"“{rule['match']}”"
    if rule["kind"] == "file_role":
        return f"Files whose path {how} {quoted} are {rule['value']} files."
    subject = {"target": "Actions whose command or target", "tool": "Actions whose tool name",
               "any": "Actions whose tool, command or target"}[rule["field"]]
    if rule["kind"] == "category":
        return f"{subject} {how} {quoted} count as {rule['value']}."
    if rule["value"] == FOLLOW:
        return f"{subject} {how} {quoted} follow the work around them."
    return f"{subject} {how} {quoted} belong to {rule['value']}."


# ----------------------------------------------------------------------------- matching
def _subject(row: dict, field: str) -> str:
    target = " ".join(x for x in (row.get("cmd") or row.get("command") or "",
                                  row.get("target") or "") if x)
    if field == "tool":
        return row.get("tool") or ""
    if field == "any":
        return f"{row.get('tool') or ''} {target}"
    return target


@contextlib.contextmanager
def _file_roles(rules: List[Dict[str, Any]]) -> Iterator[None]:
    """Swap the taxonomy's role functions for ones that apply the file-role rules first.
    ``file_role`` decides an edit's role (source, test, toolchain): a harness rule maps to
    toolchain, as the harness script already does, and a docs rule keeps the built-in role."""
    if not rules:
        yield
        return
    compiled = [(_regex(r), r["value"]) for r in rules]
    file_role, object_role = taxonomy.file_role, taxonomy.object_role

    def role_of(path: str) -> Optional[str]:
        found = None
        for pattern, value in compiled:
            if pattern.search(str(path)):
                found = value
        return found

    def new_file_role(path: str) -> str:
        role = role_of(path)
        if role in ("source", "test", "toolchain"):
            return role
        return "toolchain" if role == "harness" else file_role(path)

    def new_object_role(path: str) -> str:
        return role_of(path) or object_role(path)

    taxonomy.file_role, taxonomy.object_role = new_file_role, new_object_role
    try:
        yield
    finally:
        taxonomy.file_role, taxonomy.object_role = file_role, object_role


def _recategorize(row: dict, category: str) -> None:
    row["category"] = category
    row["mid_level"] = _MID_OF.get(category, category)
    row["reverts"] = False
    if category not in _EDITS:
        row["edit_files"], row["edit_role"] = [], ""
    elif not row.get("edit_role"):
        row["edit_role"] = taxonomy.edit_role(row.get("edit_files") or [])


def prepare(trajectory: dict, bug_id: str, rules: List[Dict[str, Any]]
            ) -> Tuple[List[dict], Dict[str, List[int]]]:
    """``segment.prepare`` with the category rules applied between the taxonomy and the
    verdicts.  Returns (rows, {rule id: action indexes it recategorised})."""
    rows = taxonomy.annotate(trajectory)
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
            if chosen["value"] != row["category"]:
                _recategorize(row, chosen["value"])
    taxonomy.resolve_waits(rows)
    verdict.attach(rows)
    for row in rows:
        row["bug_id"] = str(bug_id)
        row["args"] = row.get("arguments") or {}
    return rows, hits


def phases(trajectory: dict, bug_id: str, ruleset: Optional[Dict[str, Any]] = None,
           targets: Optional[List[str]] = None) -> Dict[str, Any]:
    """``phase.phases`` under a rule set.  The result also carries ``rules``: the normalised
    rule set, the mandatory rules, every optional rule (``on`` or not) and every custom
    rule, each with its sentence and, when it ran, the actions it changed (``matched``)
    and, for phase rules, those it could not change (``skipped``, with why)."""
    ruleset = normalize(ruleset)
    on = _active(ruleset)
    by_kind = {k: [r for r in on if r["kind"] == k] for k in KINDS}
    with _LOCK, _file_roles(by_kind["file_role"]):
        acts, cat_hits = prepare(trajectory, bug_id, by_kind["category"])
        wanted: Dict[int, str] = {}
        owner: Dict[int, str] = {}
        for x, a in enumerate(acts):
            for rule in by_kind["phase"]:
                if _regex(rule).search(_subject(a, rule["field"])):
                    wanted[x] = phase.NEUTRAL if rule["value"] == FOLLOW else rule["value"]
                    owner[x] = rule["id"]
        result = phase.assign(acts, targets, overrides=wanted)    # G7, F1: fixed numbers
        result["actions"] = acts
        phase.check_hierarchy(acts, result, name=f"bug-{bug_id}")
        role_hits = _file_hits(acts, by_kind["file_role"])
        for a in acts:                       # the viewer's file_role, under the role rules
            a["file_roles"] = taxonomy.action_roles(a)
    status = result.get("overrides") or {}

    def hits(rule: Dict[str, Any]) -> Dict[str, list]:
        """The actions a matching rule changed, and those it could not (phase rules)."""
        out: Dict[str, list] = {"matched": [], "skipped": []}
        if rule["kind"] == "category":
            out["matched"] = cat_hits.get(rule["id"], [])
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
        item = {**rule, "sentence": describe(rule), "matched": [], "skipped": []}
        if rule["enabled"]:
            item.update(hits(rule))
        custom_report.append(item)
    result["rules"] = {"schema": SCHEMA, "ruleset": ruleset, "mandatory": mandatory(), "optional": optional_report,
                       "custom": custom_report}
    return result


def _file_hits(acts: List[dict], rules: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    """{file-role rule id: actions that touch or edit a file whose path it matches}."""
    out: Dict[str, List[int]] = {r["id"]: [] for r in rules}
    for a in acts:
        paths = list(a.get("files") or []) + list(a.get("edit_files") or [])
        for rule in rules:
            pattern = _regex(rule)
            if any(pattern.search(p) for p in paths):
                out[rule["id"]].append(a["action_index"])
    return out
