"""Baselines for the phase taxonomy (``Parser/Phase taxonomy.md`` §9).

B1  the V2 analysis plan's phase assignment ("APR Trajectory Analysis V2", Action
    Classification and Phase Assignment): one split at the first edit of any file.
B3  the old purpose layer (``atif.segment``), its labels mapped to the five phases.
B4  the grouping rules of codebook version 3 (G1-G7), which ``atif.phase`` applied until the
    lookup tables of version 4 replaced them (2026-10-14).
B5  the phase lookup of codebook version 4 (Table 4, rows P1-P11, and *follow*), which
    ``atif.phase`` applied until the Final lookup tables replaced it (2026-10-17).

B4 and B5 read the action kinds of codebook versions 3 and 4 (``taxonomy.KINDS``), their own
first fix (the first edit whose role is source, ``legacy_source_edit``; an edit delegation
starts it) and their own file roles (``taxonomy.object_role``), as those versions did.

Each returns one label per action, or None where the method gives the action no phase.  The
phase called Understanding in codebook versions 3 and 4 is the Final tables' Planning.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import phase, project, segment, taxonomy
from .phase import (DECISIVE, LOCALIZATION, PLANNING, REPAIR, REPRODUCTION, VALIDATION, _EDITS,
                    _outside, _probe, _spans, attempts, run_result)

#: the phase codebook versions 3 and 4 called Understanding
UNDERSTANDING = PLANNING
#: the pre-only phases of codebook versions 3 and 4
PRE_ONLY = {UNDERSTANDING, REPRODUCTION}


def legacy_source_edit(a: dict) -> bool:
    """The first-fix edit of codebook versions 3 and 4: an edit whose role is source (an edit
    tool, a shell write, or a command that writes source on its way to a run)."""
    return a.get("edit_role") == "source"


def legacy_context(acts: List[dict], targets: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The per-trajectory facts of codebook versions 3 and 4: delegation blocks, the anchor
    (an edit delegation starts the fix), the last source edit and the files the agent edits."""
    segment.enrich(acts)
    blocks: List[Tuple[int, int, str]] = []
    block_of: Dict[int, int] = {}
    i = 0
    while i < len(acts):
        if acts[i]["mid_level"] == "delegate":                     # K2
            j = segment.delegated_scopes(acts, i)
            edits = any(legacy_source_edit(acts[x]) for x in range(i, j)) \
                or segment.delegated_edit(acts[i])
            blocks.append((i, j, REPAIR if edits else LOCALIZATION))
            for x in range(i, j):
                block_of[x] = len(blocks) - 1
            i = j
            continue
        i += 1
    first = next((x for x, a in enumerate(acts) if legacy_source_edit(a)), len(acts))
    for start, end, ph in blocks:                    # an edit delegation starts the fix
        if ph == REPAIR and start < first:
            first = start
        if start <= first < end:
            first = start
    last = max((x for x, a in enumerate(acts) if legacy_source_edit(a)), default=-1)
    edited = set(f for a in acts if a["kind"] in _EDITS for f in a["files"])
    return {"blocks": blocks, "block_of": block_of, "anchor": first, "last_src": last,
            "edited": edited}

#: V2's action categories, from our L1 categories
V2_CATEGORY: Dict[str, str] = {
    "search_code": "search", "read_file": "read", "edit_file": "edit",
    "shell_edit": "shell_edit", "build": "build", "run_test": "test", "device_ops": "test",
    "diff": "diff", "orient": "setup", "vcs": "setup", "env_setup": "setup",
    "plan": "plan", "delegate": "sub-agent", "wait_process": "poll",
    "web": "other", "run_shell": "other", "other": "other",
}
#: V2 reads count as localization only for code files
V2_CODE = (".java", ".kt", ".xml")
#: the old purposes, as phases; environment has no counterpart
B3_PHASE: Dict[str, Optional[str]] = {
    "orientation": PLANNING, "localization": phase.LOCALIZATION,
    "reproduction": phase.REPRODUCTION, "repair": phase.REPAIR,
    "validation": phase.VALIDATION, "review": phase.VALIDATION, "environment": None,
}


def first_edit_split(acts: List[dict]) -> List[Optional[str]]:
    """B1.  Before the first edit (``edit`` or ``shell_edit``, any file): setup, build and
    test understand; a read understands when no file it reads is code, else it locates;
    search and diff locate.  Edits repair wherever they are.  After the first edit: build,
    test, search, read and diff validate, and setup is cleanup, which we fold into
    validation.  Plan, sub-agent and other actions get no phase, and polls are dropped."""
    cats = [V2_CATEGORY.get(a["kind"], "other") for a in acts]
    first = next((k for k, c in enumerate(cats) if c in ("edit", "shell_edit")), len(acts))
    out: List[Optional[str]] = []
    for k, (a, c) in enumerate(zip(acts, cats)):
        if c in ("edit", "shell_edit"):
            out.append(phase.REPAIR)
        elif c in ("plan", "sub-agent", "other", "poll"):
            out.append(None)
        elif k > first:
            out.append(phase.VALIDATION)
        elif c in ("setup", "build", "test"):
            out.append(PLANNING)
        elif c == "read":
            files = a.get("files") or []
            code = not files or any(f.endswith(V2_CODE) for f in files)
            out.append(phase.LOCALIZATION if code else PLANNING)
        else:                                    # search, diff
            out.append(phase.LOCALIZATION)
    return out


def old_purposes(acts: List[dict], hierarchy: dict) -> List[Optional[str]]:
    """B3: each action's purpose in ``segment.segment(...)["hierarchy"]``, as a phase."""
    by_index = {}
    for p in hierarchy["purposes"]:
        for k in range(p["start"], p["end"] + 1):
            by_index[k] = B3_PHASE[p["label"]]
    return [by_index.get(a["action_index"]) for a in acts]


# ----------------------------------------------------------------------------- B4
# The grouping rules of codebook version 3 (G1-G7), which ``atif.phase`` applied until
# 2026-10-14: Table 5 of that codebook with neutral, preparatory and wait markers (P1), the
# keep rules (K1 an attempt keeps its judging run, K2 a delegation is one block, K3 a poll
# takes its run's phase), neutral actions following the action before them (P3), and the
# smoothing of single-action interruptions (P4, A1).
_NEUTRAL, _PREP, _WAIT = "neutral", "prep", "wait"
_V3_LOOKUP = {LOCALIZATION, _NEUTRAL, UNDERSTANDING}


def grouping_rules(acts: List[dict], targets: Optional[List[str]] = None,
                   absorb_max: int = 1) -> List[str]:
    """B4: the phase of every action under the grouping rules of codebook version 3."""
    if not acts:
        return []
    ctx = legacy_context(acts, targets)
    ph = _v3_markers(acts, _v3_table(acts, ctx), ctx)
    ph = _v3_keep_attempts(ph, attempts(acts, legacy_source_edit))
    return _v3_smooth(acts, _v3_neutral(ph), absorb_max)


def _v3_lookup(a: dict, x: int, ctx: dict, unknown: str) -> str:
    """T4 / T7: an inspection of source or test code locates; one of docs, build files
    or the harness, or of paths outside the checkout only, is neutral.  ``unknown`` is the
    phase of an inspection that names no path (``rg pattern`` locates, ``git status``
    does not)."""
    pre = x < ctx["anchor"]
    roles = {taxonomy.object_role(f) for f in a["files"]}
    outside = _outside(a)
    code_outside = any(o.endswith((".java", ".kt", ".xml")) for o in outside)
    if not (a["files"] or outside) and unknown != LOCALIZATION:
        return unknown
    if roles & {"source", "test"} or code_outside or not (a["files"] or outside):
        if not pre and x > ctx["last_src"] >= 0 and a["files"] \
                and set(a["files"]) <= ctx["edited"]:
            a["_own_read"] = True
            return VALIDATION                       # reading back one's own patch
        return LOCALIZATION
    return _NEUTRAL


def _v3_table(acts: List[dict], ctx: dict) -> List[str]:
    """P1: one phase, or a _NEUTRAL / _PREP / _WAIT marker, per action (spec §6, T1-T9)."""
    out: List[str] = []
    for x, a in enumerate(acts):
        a.pop("_own_read", None)
        cat, pre = a["kind"], x < ctx["anchor"]
        if x in ctx["block_of"]:
            phase = ctx["blocks"][ctx["block_of"][x]][2]                       # T9
        elif legacy_source_edit(a):
            phase = REPAIR                                                     # T1
        elif cat in _EDITS:
            if a.get("reverts"):
                phase = _NEUTRAL if pre else REPAIR
            elif a.get("edit_role") == "test":
                phase = REPRODUCTION if pre else VALIDATION                    # T3
            else:
                phase = _PREP                                                   # T6
        elif cat == "wait_process":
            phase = _WAIT                                                       # T8
        elif cat in ("run_test", "device_ops"):
            phase = REPRODUCTION if pre else VALIDATION                        # T2
        elif cat in ("build", "env_setup") or _probe(a):
            phase = _PREP                                                       # T6
        elif cat == "diff":
            phase = _NEUTRAL if pre else VALIDATION                             # T5
        elif cat in ("read_file", "search_code"):
            phase = _v3_lookup(a, x, ctx, LOCALIZATION)                     # T4 / T7
        elif cat in ("vcs", "orient"):              # git blame / show HEAD:F.java locate
            phase = _v3_lookup(a, x, ctx, _NEUTRAL)                          # T4 / T7
        else:
            phase = _NEUTRAL                                                    # T7
        out.append(phase)
    return out


def _v3_stretch_member(a: dict) -> bool:
    """An action that can sit inside an execution stretch on the way to its run."""
    return a["cls"] == "EXEC" or (a["kind"] in _EDITS and not legacy_source_edit(a)) \
        or a["kind"] in ("orient", "plan", "other", "vcs", "diff")


def _v3_markers(acts: List[dict], ph: List[str], ctx: dict) -> List[str]:
    """T6: a preparatory action takes the phase of the next test or device run in its
    execution stretch (else Understanding before the anchor, Validation after).
    T8 / K3: a poll takes the phase of the run it polls, else of the action before it."""
    out = list(ph)
    for x, phase in enumerate(out):
        if phase != _PREP:
            continue
        pre = x < ctx["anchor"]
        found = None
        for y in range(x + 1, len(acts)):
            b = acts[y]
            if y in ctx["block_of"] or legacy_source_edit(b) or not _v3_stretch_member(b):
                break
            if segment.eff_mid(acts, b) in ("run_test", "device_ops"):
                found = REPRODUCTION if y < ctx["anchor"] else VALIDATION
                break
        out[x] = found or (UNDERSTANDING if pre else VALIDATION)
    for x, phase in enumerate(out):
        if phase != _WAIT:
            continue
        w = acts[x].get("waits_pos")
        polled = out[w] if w is not None and w < x else (out[x - 1] if x else UNDERSTANDING)
        if x >= ctx["anchor"] and polled in PRE_ONLY:
            polled = VALIDATION             # a run started before the fix, polled after it
        out[x] = polled
    return out


def _v3_keep_attempts(ph: List[str], tries: List[dict]) -> List[str]:
    """K1: every action from an attempt's first edit to its judging run is Repair, except
    lookups, which keep their own phase: a single lookup joins the repair span again (A1),
    a longer one stays a localization span inside the attempt."""
    out = list(ph)
    for at in tries:
        for x in range(at["start"], at["end"] + 1):
            if out[x] not in _V3_LOOKUP:
                out[x] = REPAIR
    return out


def _v3_neutral(ph: List[str]) -> List[str]:
    """P3: a neutral action (orienting, planning, inspecting git, reading docs or build
    files) takes the phase of the action before it; the neutral actions that open the
    trajectory are Understanding.  Planning calls interleaved with lookups (Codex's
    ``update_plan``) therefore stay in the lookup's phase."""
    out = list(ph)
    for x, phase in enumerate(out):
        if phase == _NEUTRAL:
            out[x] = out[x - 1] if x else UNDERSTANDING
    return out


def _v3_smooth(acts: List[dict], ph: List[str], absorb_max: int,
           locked: Optional[Set[int]] = None) -> List[str]:
    """P4 (A1), to a fixed point: a span of at most ``absorb_max`` actions (1: a single
    action) between two spans of the same phase joins them; a longer span keeps its phase.
    Two spans are never absorbed: a Repair span, because every source edit stays in Repair,
    and a span that holds a decisive run, because its check would vanish from the
    subphases.  Nor is a span that holds a ``locked`` position (a user rule's phase)."""
    out = list(ph)
    decisive = [run_result(acts, a) in DECISIVE or x in (locked or ())
                for x, a in enumerate(acts)]
    changed = True
    while changed:
        changed = False
        spans = _spans(out)
        for k in range(1, len(spans) - 1):
            phase, lo, hi = spans[k]
            if spans[k - 1][0] == spans[k + 1][0] and hi - lo <= absorb_max \
                    and phase != REPAIR and not any(decisive[lo:hi]):
                out[lo:hi] = [spans[k - 1][0]] * (hi - lo)
                changed = True
                break
    return out


# ----------------------------------------------------------------------------- B5
# The phase lookup of codebook version 4 (Table 4, rows P1-P11, and its one convention
# *follow*), which ``atif.phase`` applied from 2026-10-14 to 2026-10-17.
_FOLLOW = "follow"
#: a git look at code (P7): blame, show or log, not status or rev-parse
_GIT_LOOK = re.compile(r"\bgit\b[^|;&\n]*\b(?:blame|show|log)\b")
#: kinds that look at files (P7, P9)
_LOOKS = ("read_file", "search_code", "orient", "vcs")


def _code_outside(paths: List[str]) -> bool:
    """A copy of app code outside the checkout (Table 3, outside): Java, Kotlin and XML in
    an Android project, Python too in a SWE-bench one."""
    suffixes = (".java", ".kt", ".xml") + ((".py",) if project.current().swebench else ())
    return any(p.endswith(suffixes) for p in paths)


def _looks_at_code(a: dict) -> bool:
    """P7: a read, search, listing or git look (blame, show, log) at app or test code, or a
    read or search that names no path at all (``rg pattern`` searches the code)."""
    if a["kind"] not in _LOOKS:
        return False
    if a["kind"] == "vcs" and not _GIT_LOOK.search(a.get("cmd") or ""):
        return False
    outside = _outside(a)
    if {taxonomy.object_role(f) for f in a["files"]} & {"source", "test"} \
            or _code_outside(outside):
        return True
    return a["kind"] in ("read_file", "search_code") and not a["files"] and not outside


def table_v4(acts: List[dict], targets: Optional[List[str]] = None) -> List[str]:
    """B5: the phase of every action under Table 4 of codebook version 4 (rows P1-P11, the
    first that matches) and *follow* (the phase of the row above; Understanding at the start,
    and never a pre-only phase after the first fix)."""
    if not acts:
        return []
    ctx = legacy_context(acts, targets)
    cells: List[str] = []
    changed: Set[str] = set()
    for x, a in enumerate(acts):
        cat, pre = a["kind"], x < ctx["anchor"]
        if a.get("reverts"):
            ph = _FOLLOW if pre else REPAIR                                    # P2
        elif legacy_source_edit(a):
            ph = REPAIR                                                        # P1
        elif cat in _EDITS and a.get("edit_role") == "test":
            ph = REPRODUCTION if pre else VALIDATION                           # P3
        elif cat in _EDITS:
            ph = _FOLLOW                                                       # P4
        elif cat in ("run_test", "device_ops"):
            ph = REPRODUCTION if pre else VALIDATION                           # P5
        elif cat == "build":
            ph = UNDERSTANDING if pre else VALIDATION                          # P6
        elif _looks_at_code(a):
            ph = LOCALIZATION                                                  # P7
            if not pre and a["files"] and set(a["files"]) <= changed:
                ph = VALIDATION
        elif cat == "diff":
            ph = _FOLLOW if pre else VALIDATION                                # P8
        elif cat in _LOOKS and (a["files"] or _outside(a)):
            ph = _FOLLOW                                                       # P9
        elif cat == "delegate":
            ph = REPAIR if not pre and segment.delegated_edit(a) else LOCALIZATION   # P10
        else:
            ph = _FOLLOW                                                       # P11
        if cat in _EDITS and a.get("edit_role") in ("source", "test"):
            changed.update(a["files"])
            changed.update(a.get("edit_files") or [])
        cells.append(ph)
    out: List[str] = []
    for x, ph in enumerate(cells):
        if ph == _FOLLOW:
            ph = out[-1] if out else UNDERSTANDING
            if x >= ctx["anchor"] and ph in PRE_ONLY:
                ph = VALIDATION
        out.append(ph)
    return out
