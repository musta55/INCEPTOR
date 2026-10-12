"""Phase taxonomy v3: action -> phase -> subphase.

Spec: ``Parser/Phase taxonomy.md``.  Every action is in exactly one subphase, every
subphase in exactly one phase span, and both are contiguous (``check_hierarchy``).

phase     one of PHASES, given to every action by four deterministic passes:
          P1  a table over the action's L1 category, the role of its files and whether it
              comes before the anchor (the first edit of application source);
          P2  keep rules: an attempt keeps its judging run (K1), a delegation is one block
              (K2), a poll takes the phase of its run (K3);
          P3  a neutral action after the anchor takes the phase of the action before it;
          P4  smoothing: a single action between two spans of the same phase joins them
              (A1); any longer stretch keeps its own phase.
subphase  a maximal stretch of one phase span with one outcome: succeeded, failed, blocked
          or unchecked, with the same meaning in every phase (did the check in the stretch
          show that the phase's goal was reached?).  The span's events (a decisive run, an
          attempt) get outcomes, every other action belongs to the event it leads to, and
          consecutive events with the same outcome merge (run-length encoding).  The
          ``evidence`` attribute records the strongest check behind the outcome.

Nothing is fitted: the constant below was set before any labels existed, swept in a
sensitivity analysis and frozen.  It was lowered from 3 to 1, and the old repair-gap rule
(A2: up to 10 actions between two repair spans joined repair) was removed, after the
round-1 manual check (codebook change of 2026-10-11): both hid validation and localization
work inside repair.  The segment and purpose layers of ``atif.segment`` are
not used; that module stays unchanged as baseline B3, and only its per-action helpers are
reused here.
"""
from __future__ import annotations

import collections
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import segment, taxonomy

PHASES = ("understanding", "localization", "reproduction", "repair", "validation")
UNDERSTANDING, LOCALIZATION, REPRODUCTION, REPAIR, VALIDATION = PHASES
#: phases that occur only before / only from the anchor on (``check_hierarchy``)
PRE_ONLY = {UNDERSTANDING, REPRODUCTION}
POST_ONLY = {REPAIR, VALIDATION}

#: one question per stretch, the same in every phase: did its check show that the phase's
#: goal was reached?  succeeded / failed: the check says yes / no; blocked: a check was
#: attempted but the environment stopped it, so it says nothing about the agent's work;
#: unchecked: no check was attempted
OUTCOMES = ("succeeded", "failed", "blocked", "unchecked")
#: the strongest check behind an outcome, strongest first: a test run, a build (the APR
#: distinction between a plausible and a compilable patch), the target file list
#: (Localization), or nothing
EVIDENCE = ("test", "build", "target_file", "none")
#: the outcomes each phase can have.  Understanding never fails (a pre-fix build failure is
#: not the agent's doing, so it is blocked); Localization is never blocked
PHASE_OUTCOMES: Dict[str, Tuple[str, ...]] = {
    UNDERSTANDING: ("unchecked", "succeeded", "blocked"),
    LOCALIZATION: ("succeeded", "failed", "unchecked"),
    REPRODUCTION: ("unchecked", "succeeded", "failed", "blocked"),
    REPAIR: ("unchecked", "succeeded", "failed", "blocked"),
    VALIDATION: ("unchecked", "succeeded", "failed", "blocked"),
}
#: behaviours worth surfacing, each needed by a research question (spec §7)
FLAGS = ("test_modified", "environment_workaround", "repeated_failure", "repeated_reads",
         "manual_ui_check")

#: A1: an interruption of at most this many actions joins the phase around it (G7)
ABSORB_MAX = 1
#: the repeated_reads flag: one file read at least this many times in a subphase
REPEATED_READS = 3

# P1 markers, resolved before P4
NEUTRAL = "neutral"
PREP = "prep"
WAIT = "wait"
_LOOKUP = {LOCALIZATION, NEUTRAL, UNDERSTANDING}

#: results of a run that decide an event; a passing build ("build_pass") is weak
DECISIVE = ("pass", "test_fail", "build_fail", "blocked")
#: run result -> outcome, per phase.  Before the fix a failing test is the goal
#: (Reproduction succeeded); after it, the same result is a failure
_RUN_OUTCOME: Dict[str, Dict[str, str]] = {
    UNDERSTANDING: {"build_pass": "succeeded", "pass": "succeeded", "build_fail": "blocked",
                    "blocked": "blocked", "test_fail": "blocked"},
    REPRODUCTION: {"test_fail": "succeeded", "pass": "failed", "build_fail": "blocked",
                   "blocked": "blocked"},
    REPAIR: {"pass": "succeeded", "build_pass": "succeeded", "test_fail": "failed",
             "build_fail": "failed", "blocked": "blocked"},
}
_RUN_OUTCOME[VALIDATION] = _RUN_OUTCOME[REPAIR]
_FAILURES = ("test_fail", "build_fail", "blocked")
_EDITS = ("edit_file", "shell_edit")


# ----------------------------------------------------------------------------- per action
def run_result(acts: List[dict], a: dict) -> Optional[str]:
    """What a run decided: ``pass`` (a test run passed), ``test_fail`` (a test executed and
    failed, whatever task ran it), ``build_fail`` (the code does not compile),
    ``blocked`` (the toolchain, sandbox or anything else stopped a build or test run),
    ``build_pass`` (a build passed: weak, it shows the code compiles, not that the bug is
    fixed), or None.  A poll counts as the run it polls (``segment.eff_mid``)."""
    mid, verdict = segment.eff_mid(acts, a), a["verdict"]
    if mid not in ("run_test", "build") or verdict not in ("pass", "fail"):
        return None
    if verdict == "fail":
        kind = a["fail_kind"]
        return "test_fail" if kind == "test" else "build_fail" if kind == "build" else "blocked"
    return "pass" if mid == "run_test" else "build_pass"


def run_evidence(acts: List[dict], a: dict) -> str:
    """The check a run is: ``test`` when it ran tests (or tried to), else ``build``."""
    return "test" if segment.eff_mid(acts, a) == "run_test" or a["fail_kind"] == "test" \
        else "build"


def _strongest(evidence: Iterable[str]) -> str:
    return min(evidence, key=EVIDENCE.index, default="none")


def source_edit(a: dict) -> bool:
    """An edit of application source: an edit tool or shell write whose role is source,
    or a command that writes source on its way to a run (``taxonomy.annotate``)."""
    return a.get("edit_role") == "source"


#: toolchain locations outside the project; ``segment.enrich`` (R2) misses ``~/.gradle`` and
#: ``~/.m2`` written without a trailing slash
_TOOLCHAIN_PLACE = re.compile(r"(?:^|/)\.(?:gradle|m2|android)(?:/|$)|JavaVirtualMachines"
                              r"|/Library/|/usr/lib/jvm|/opt/|sdk", re.IGNORECASE)
#: home-relative paths in a command (``segment.action_paths`` only finds absolute ones)
_HOME_PATH = re.compile(r"(?<![\w$])~/[\w.\-/+]*")


def _outside(a: dict) -> List[str]:
    """Paths outside the checkout, without devices (the ``/dev/null`` of a redirect is not
    a toolchain location, though ``segment.enrich`` counts it as one), plus home-relative
    paths named in the command."""
    paths = [o for o in a["outside"] if not o.startswith("/dev/")]
    return paths + [p for p in _HOME_PATH.findall(a.get("cmd") or "") if p not in paths]


def _probe(a: dict) -> bool:
    """R2 (``segment.enrich``): a look at the harness, logs, build output or toolchain
    locations, which is execution work (codebook rule G3); without the ``/dev/null`` false
    positive, and with the toolchain locations R2 misses."""
    if a.get("env_probe"):
        if _outside(a) or not a["outside"]:
            return True
        return any(os.path.basename(p) in segment.HARNESS_FILES or p.startswith("build/")
                   or "/build/outputs" in p or p.endswith((".log", ".png"))
                   for p in a["files"]) or bool(segment.ENV_HINT.search(a.get("cmd") or ""))
    return taxonomy.CATEGORY_FAMILY.get(a["category"]) == "inspect" and not a["files"] \
        and any(_TOOLCHAIN_PLACE.search(p) for p in _outside(a))


def _started(acts: List[dict], x: int) -> dict:
    w = acts[x].get("waits_pos")
    return acts[w] if w is not None else acts[x]


def _match(path: str, targets: Set[str]) -> bool:
    base = os.path.basename(path)
    return any(base == os.path.basename(t) and (path.endswith(t) or t.endswith(path))
               for t in targets)


# ----------------------------------------------------------------------------- context
def context(acts: List[dict], targets: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Per-trajectory facts the passes read: delegation blocks, the anchor, the last
    source edit, the files the agent edits, and the Localization target files."""
    segment.enrich(acts)
    blocks: List[Tuple[int, int, str]] = []
    block_of: Dict[int, int] = {}
    i = 0
    while i < len(acts):
        if acts[i]["mid_level"] == "delegate":                     # K2
            j = segment.delegated_scopes(acts, i)
            edits = any(source_edit(acts[x]) for x in range(i, j)) \
                or segment.delegated_edit(acts[i])
            blocks.append((i, j, REPAIR if edits else LOCALIZATION))
            for x in range(i, j):
                block_of[x] = len(blocks) - 1
            i = j
            continue
        i += 1
    first = next((x for x, a in enumerate(acts) if source_edit(a)), len(acts))
    for start, end, phase in blocks:                 # an edit delegation starts the fix
        if phase == REPAIR and start < first:
            first = start
        if start <= first < end:
            first = start
    last = max((x for x, a in enumerate(acts) if source_edit(a)), default=-1)
    edited = set(f for a in acts if a["category"] in _EDITS for f in a["files"])
    patch = set(f for a in acts if source_edit(a) for f in a.get("edit_files") or [])
    chosen = set(targets) if targets else patch
    previous_run: Dict[int, int] = {}            # each decisive run -> the one before it
    last_run: Optional[int] = None
    for x, a in enumerate(acts):
        if run_result(acts, a) in DECISIVE:
            if last_run is not None:
                previous_run[x] = last_run
            last_run = x
    return {"blocks": blocks, "block_of": block_of, "anchor": first, "last_src": last,
            "edited": edited, "targets": chosen, "previous_run": previous_run,
            "target_source": "developer_fix" if targets else "final_patch" if patch else "none"}


# ----------------------------------------------------------------------------- P1
def _lookup_phase(a: dict, x: int, ctx: dict, unknown: str) -> str:
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
    return NEUTRAL


def table(acts: List[dict], ctx: dict) -> List[str]:
    """P1: one phase, or a NEUTRAL / PREP / WAIT marker, per action (spec §6, T1-T9)."""
    out: List[str] = []
    for x, a in enumerate(acts):
        a.pop("_own_read", None)
        cat, pre = a["category"], x < ctx["anchor"]
        if x in ctx["block_of"]:
            phase = ctx["blocks"][ctx["block_of"][x]][2]                       # T9
        elif source_edit(a):
            phase = REPAIR                                                     # T1
        elif cat in _EDITS:
            if a.get("reverts"):
                phase = NEUTRAL if pre else REPAIR
            elif a.get("edit_role") == "test":
                phase = REPRODUCTION if pre else VALIDATION                    # T3
            else:
                phase = PREP                                                   # T6
        elif cat == "wait_process":
            phase = WAIT                                                       # T8
        elif cat in ("run_test", "device_ops"):
            phase = REPRODUCTION if pre else VALIDATION                        # T2
        elif cat in ("build", "env_setup") or _probe(a):
            phase = PREP                                                       # T6
        elif cat == "diff":
            phase = NEUTRAL if pre else VALIDATION                             # T5
        elif cat in ("read_file", "search_code"):
            phase = _lookup_phase(a, x, ctx, LOCALIZATION)                     # T4 / T7
        elif cat in ("vcs", "orient"):              # git blame / show HEAD:F.java locate
            phase = _lookup_phase(a, x, ctx, NEUTRAL)                          # T4 / T7
        else:
            phase = NEUTRAL                                                    # T7
        out.append(phase)
    return out


def _stretch_member(a: dict) -> bool:
    """An action that can sit inside an execution stretch on the way to its run."""
    return a["cls"] == "EXEC" or (a["category"] in _EDITS and not source_edit(a)) \
        or a["category"] in ("orient", "plan", "other", "vcs", "diff")


def resolve_markers(acts: List[dict], ph: List[str], ctx: dict) -> List[str]:
    """T6: a preparatory action takes the phase of the next test or device run in its
    execution stretch (else Understanding before the anchor, Validation after).
    T8 / K3: a poll takes the phase of the run it polls, else of the action before it."""
    out = list(ph)
    for x, phase in enumerate(out):
        if phase != PREP:
            continue
        pre = x < ctx["anchor"]
        found = None
        for y in range(x + 1, len(acts)):
            b = acts[y]
            if y in ctx["block_of"] or source_edit(b) or not _stretch_member(b):
                break
            if segment.eff_mid(acts, b) in ("run_test", "device_ops"):
                found = REPRODUCTION if y < ctx["anchor"] else VALIDATION
                break
        out[x] = found or (UNDERSTANDING if pre else VALIDATION)
    for x, phase in enumerate(out):
        if phase != WAIT:
            continue
        w = acts[x].get("waits_pos")
        polled = out[w] if w is not None and w < x else (out[x - 1] if x else UNDERSTANDING)
        if x >= ctx["anchor"] and polled in PRE_ONLY:
            polled = VALIDATION             # a run started before the fix, polled after it
        out[x] = polled
    return out


# ----------------------------------------------------------------------------- P2 (K1)
def attempts(acts: List[dict]) -> List[dict]:
    """K1.  An attempt is a block of source edits checked by one run.  Its judging run is
    the first decisive run at or after its first edit (an action that edits and runs,
    ``apply_patch ... && ./gradlew test``, judges itself), and its outcome comes from that
    run.  A passing build is a weak judge: when the agent edits again after one, with no
    decisive run in between, the build closed the attempt (``builds``) and the new edit
    starts the next one; edit -> build -> test stays one attempt, judged by the test.
    Without any judge the attempt is ``unchecked``."""
    out: List[dict] = []
    cur: Optional[dict] = None
    for x, a in enumerate(acts):
        if source_edit(a):
            if cur is not None and cur["judge"] is None and cur["weak"] is not None:
                cur["judge"] = cur["weak"]               # edit -> build passes -> edit
            if cur is None or cur["judge"] is not None:
                cur = {"id": len(out) + 1, "start": x, "edits": [], "judge": None,
                       "weak": None}
                out.append(cur)
            cur["edits"].append(x)
        if cur is None or cur["judge"] is not None:
            continue
        result = run_result(acts, a)
        if result in DECISIVE:
            cur["judge"] = x
        elif result == "build_pass" and cur["weak"] is None:
            cur["weak"] = x
    for at in out:
        at["last_edit"] = at["edits"][-1]
        judge = at["judge"] if at["judge"] is not None else at.pop("weak")
        at.pop("weak", None)
        at["judge"] = judge
        if judge is not None:
            at["outcome"] = _RUN_OUTCOME[REPAIR][run_result(acts, acts[judge])]
            at["evidence"] = run_evidence(acts, acts[judge])
            at["end"] = judge
            continue
        at["outcome"], at["evidence"], at["end"] = "unchecked", "none", at["last_edit"]
    return out


def keep_attempts(ph: List[str], tries: List[dict]) -> List[str]:
    """K1: every action from an attempt's first edit to its judging run is Repair, except
    lookups, which keep their own phase: a single lookup joins the repair span again (A1),
    a longer one stays a localization span inside the attempt."""
    out = list(ph)
    for at in tries:
        for x in range(at["start"], at["end"] + 1):
            if out[x] not in _LOOKUP:
                out[x] = REPAIR
    return out


def resolve_neutral(ph: List[str]) -> List[str]:
    """P3: a neutral action (orienting, planning, inspecting git, reading docs or build
    files) takes the phase of the action before it; the neutral actions that open the
    trajectory are Understanding.  Planning calls interleaved with lookups (Codex's
    ``update_plan``) therefore stay in the lookup's phase."""
    out = list(ph)
    for x, phase in enumerate(out):
        if phase == NEUTRAL:
            out[x] = out[x - 1] if x else UNDERSTANDING
    return out


# ----------------------------------------------------------------------------- P4
def _spans(ph: List[str]) -> List[List[Any]]:
    out: List[List[Any]] = []
    for x, phase in enumerate(ph):
        if out and out[-1][0] == phase:
            out[-1][2] = x + 1
        else:
            out.append([phase, x, x + 1])
    return out


def smooth(acts: List[dict], ph: List[str], absorb_max: int,
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


# ----------------------------------------------------------------------------- subphases
def _event_keys(acts: List[dict], lo: int, hi: int, phase: str,
                tries: List[dict]) -> List[Optional[tuple]]:
    """Each action's event in the span [lo, hi): ("attempt", id) inside an attempt's
    range (Repair), ("run", x) at a decisive run, ("weak", x) at a passing build (not in
    Reproduction, where only a test run checks the goal); None elsewhere."""
    keys: List[Optional[tuple]] = [None] * (hi - lo)
    if phase == REPAIR:
        for at in tries:
            for x in range(max(at["start"], lo), min(at["end"] + 1, hi)):
                keys[x - lo] = ("attempt", at["id"])
    for x in range(lo, hi):
        if keys[x - lo] is None:
            result = run_result(acts, acts[x])
            if result in DECISIVE:
                keys[x - lo] = ("run", x)
            elif result == "build_pass" and phase != REPRODUCTION:
                keys[x - lo] = ("weak", x)
    return keys


def _localization(acts: List[dict], lo: int, hi: int, ctx: dict) -> List[dict]:
    """One subphase: succeeded when the span touches a target file, failed when targets
    are known and it touches none, unchecked when no target is known."""
    if not ctx["targets"]:
        outcome, evidence = "unchecked", "none"
    else:
        hit = any(_match(f, ctx["targets"]) for x in range(lo, hi) for f in acts[x]["files"])
        outcome, evidence = ("succeeded" if hit else "failed"), "target_file"
    return [{"outcome": outcome, "evidence": evidence, "lo": lo, "hi": hi,
             "n_events": 1, "n_attempts": 0, "repeats": 0, "workarounds": 0}]


def subphases(acts: List[dict], lo: int, hi: int, phase: str, tries: List[dict],
              ctx: dict) -> List[dict]:
    """The span's subphases: dicts with outcome, evidence, [lo, hi), n_events, n_attempts
    and repeats (events that repeat the previous failing run unchanged, K4)."""
    if phase == LOCALIZATION:
        return _localization(acts, lo, hi, ctx)
    keys = _event_keys(acts, lo, hi, phase, tries)
    # a passing build decides only when no other event follows it in the span
    last_real = max((i for i, k in enumerate(keys) if k is not None and k[0] != "weak"),
                    default=-1)
    keys = [None if k is not None and k[0] == "weak" and i < last_real else k
            for i, k in enumerate(keys)]
    if not any(keys):
        return [{"outcome": "unchecked", "evidence": "none", "lo": lo, "hi": hi,
                 "n_events": 0, "n_attempts": 0, "repeats": 0, "workarounds": 0}]
    nxt = None                                   # an action belongs to the event it leads to
    for i in range(len(keys) - 1, -1, -1):
        if keys[i] is None:
            keys[i] = nxt
        else:
            nxt = keys[i]
    prv = None                                   # trailing actions join the last event
    for i in range(len(keys)):
        if keys[i] is None:
            keys[i] = prv
        else:
            prv = keys[i]
    events: List[dict] = []
    for i, key in enumerate(keys):
        if events and events[-1]["key"] == key:
            events[-1]["hi"] = lo + i + 1
        else:
            events.append({"key": key, "lo": lo + i, "hi": lo + i + 1})
    by_id = {at["id"]: at for at in tries}
    for ev in events:
        kind, value = ev["key"]
        ev["repeat"] = ev["workaround"] = False
        if kind == "attempt":
            ev["outcome"], ev["evidence"] = by_id[value]["outcome"], by_id[value]["evidence"]
        else:
            ev["outcome"] = _RUN_OUTCOME[phase][run_result(acts, acts[value])]
            ev["evidence"] = run_evidence(acts, acts[value])
            before = ctx["previous_run"].get(value)
            ev["repeat"] = before is not None and _repeats(acts, before, value)
            ev["workaround"] = before is not None and _changed_rerun(acts, before, value)
    out: List[dict] = []
    for ev in events:                            # run-length encoding by outcome
        attempt = ev["key"][0] == "attempt"
        if out and out[-1]["outcome"] == ev["outcome"]:
            last = out[-1]
            last["hi"] = ev["hi"]
            last["n_events"] += 1
            last["n_attempts"] += attempt
            last["repeats"] += ev["repeat"]
            last["workarounds"] += ev["workaround"]
            last["evidence"] = _strongest((last["evidence"], ev["evidence"]))
        else:
            out.append({"outcome": ev["outcome"], "evidence": ev["evidence"], "lo": ev["lo"],
                        "hi": ev["hi"], "n_events": 1, "n_attempts": int(attempt),
                        "repeats": int(ev["repeat"]), "workarounds": int(ev["workaround"])})
    return out


def _repeats(acts: List[dict], before: int, now: int) -> bool:
    """K4: the run at ``now`` repeats the decisive run at ``before`` (the one before it,
    in any phase): both failed, with the same full command and the same error signature,
    and nothing was edited or set up in between."""
    a, b = acts[before], acts[now]
    if run_result(acts, a) not in _FAILURES or run_result(acts, b) not in _FAILURES:
        return False
    return _started(acts, before)["run_key"] == _started(acts, now)["run_key"] \
        and a["error_sig"] == b["error_sig"] \
        and not segment._changes_between(acts, before, now)


def _changed_rerun(acts: List[dict], before: int, now: int) -> bool:
    """The run at ``now`` retries the failed decisive run at ``before`` (the one before
    it, in any phase) with something changed: the same command once environment prefixes
    and output filters are set aside (``segment.norm_cmd``), but a different full command
    (another ``JAVA_HOME``, another Gradle flag), or an environment command in between."""
    if run_result(acts, acts[before]) not in _FAILURES:
        return False
    a, b = _started(acts, before), _started(acts, now)
    if a["key"] != b["key"]:
        return False
    return a["run_key"] != b["run_key"] or any(
        acts[x]["category"] == "env_setup" for x in range(before + 1, now))


#: what a failed search prints when it really failed; ``grep``/``rg`` exit 1 on no match
_SEARCH_ERROR = re.compile(r"No such file|not found|[Ee]rror|Permission denied|[Ii]nvalid"
                           r"|unrecognized|illegal|regex parse")


def _tool_error(a: dict) -> bool:
    """A lookup, edit or other non-execution call that failed.  A search that exits non-zero
    without an error message found nothing; that is a result, not an error."""
    if a.get("failed") is not True or taxonomy.CATEGORY_FAMILY.get(a["category"]) not in (
            "inspect", "modify", "other"):
        return False
    return a["category"] != "search_code" or bool(_SEARCH_ERROR.search(a.get("result") or ""))


def flags(acts: List[dict], lo: int, hi: int, repeats: int, workarounds: int,
          min_reads: int = REPEATED_READS) -> List[str]:
    """The subphase's flags (FLAGS, spec §7)."""
    rows = acts[lo:hi]
    found: List[str] = []
    edited = [os.path.basename(f) for a in rows if a["category"] in _EDITS
              for f in a.get("edit_files") or []]
    if any(a.get("edit_role") == "test" for a in rows) or \
            set(edited) & taxonomy.HARNESS_SCRIPTS:
        found.append("test_modified")
    build_config = any(a.get("edit_role") == "toolchain" and not set(
        os.path.basename(f) for f in a.get("edit_files") or []) <= taxonomy.HARNESS_SCRIPTS
        for a in rows)
    failing = any(run_result(acts, a) in _FAILURES for a in rows)
    if build_config or workarounds or (failing and any(a["category"] == "env_setup"
                                                       for a in rows)):
        found.append("environment_workaround")
    if repeats:
        found.append("repeated_failure")
    reads = collections.Counter(f for a in rows if a["category"] == "read_file"
                                for f in a["files"])
    if reads and max(reads.values()) >= min_reads:
        found.append("repeated_reads")
    if any(a["category"] == "device_ops" for a in rows):
        found.append("manual_ui_check")            # drives the app: no automatic verdict
    return found


# ----------------------------------------------------------------------------- assembly
def override_problem(acts: List[dict], x: int, phase: str, ctx: dict) -> Optional[str]:
    """Why a user rule cannot put action ``x`` in ``phase`` (NEUTRAL: let it follow the
    work around it), or None when it can.  The rules never break the invariants: a source
    edit is Repair, and the first fix bounds the pre-only and post-only phases (G1)."""
    if source_edit(acts[x]):
        return "an edit of app source is always repair"
    if phase in PRE_ONLY and x >= ctx["anchor"]:
        return f"{phase} happens only before the first fix"
    if phase in POST_ONLY and x < ctx["anchor"]:
        return f"{phase} happens only from the first fix on"
    return None


def assign(acts: List[dict], targets: Optional[Iterable[str]] = None, *,
           absorb_max: int = ABSORB_MAX, keep_rules: bool = True,
           smoothing: bool = True, overrides: Optional[Dict[int, str]] = None,
           repeated_reads: int = REPEATED_READS) -> Dict[str, Any]:
    """Phases and subphases of prepared actions (``segment.prepare``).  ``keep_rules`` and
    ``smoothing`` switch P2 and P4 off for baselines and ablations (B2 = both off).

    ``overrides`` ({position: phase or NEUTRAL}) are user rules (``atif.rules``): each
    replaces the P1 phase of its action, again after K1, and its action is never absorbed
    by P4; one that would break an invariant (``override_problem``) is skipped.  The
    result's ``overrides`` says, per position, None (applied) or why it was skipped."""
    if not acts:
        return {"phases": [], "own_phase": [], "phase": [], "attempts": [],
                "anchor": None, "context": {}, "metrics": {}, "overrides": {}}
    ctx = context(acts, targets)
    ph = table(acts, ctx)
    status = {x: override_problem(acts, x, p, ctx) for x, p in (overrides or {}).items()}
    forced = {x: p for x, p in (overrides or {}).items() if status[x] is None}
    for x, p in forced.items():
        ph[x] = p
    ph = resolve_markers(acts, ph, ctx)
    tries = attempts(acts)
    if keep_rules:
        ph = keep_attempts(ph, tries)
        for x, p in forced.items():
            if p != NEUTRAL:
                ph[x] = p
    own = resolve_neutral(ph)
    locked = {x for x, p in forced.items() if p != NEUTRAL}
    final = smooth(acts, own, absorb_max, locked) if smoothing else list(own)
    spans: List[dict] = []
    for k, (phase, lo, hi) in enumerate(_spans(final), 1):
        subs = []
        for j, sp in enumerate(subphases(acts, lo, hi, phase, tries, ctx), 1):
            subs.append({
                "id": f"p{k}.{j}", "outcome": sp["outcome"], "evidence": sp["evidence"],
                "start": acts[sp["lo"]]["action_index"],
                "end": acts[sp["hi"] - 1]["action_index"],
                "n_actions": sp["hi"] - sp["lo"], "n_events": sp["n_events"],
                "n_attempts": sp["n_attempts"],
                "flags": flags(acts, sp["lo"], sp["hi"], sp["repeats"], sp["workarounds"],
                               repeated_reads),
                "own_phases": dict(collections.Counter(own[sp["lo"]:sp["hi"]])),
                "_lo": sp["lo"], "_hi": sp["hi"],
            })
        spans.append({"id": f"p{k}", "phase": phase, "start": acts[lo]["action_index"],
                      "end": acts[hi - 1]["action_index"], "n_actions": hi - lo,
                      "subphases": subs, "_lo": lo, "_hi": hi})
    result = {"phases": spans, "own_phase": own, "phase": final, "attempts": tries,
              "anchor": acts[ctx["anchor"]]["action_index"] if ctx["anchor"] < len(acts)
              else None, "context": ctx, "overrides": status}
    result["metrics"] = metrics(acts, result)
    return result


def phases(trajectory: dict, bug_id: str, targets: Optional[Iterable[str]] = None,
           **options: Any) -> Dict[str, Any]:
    """Phase one trajectory; ``check_hierarchy`` runs on the result.  Returns ``actions``
    (annotated rows), ``phases`` (spans with their subphases), ``own_phase`` and ``phase``
    per action, ``attempts``, ``anchor`` (an action_index, or None) and ``metrics``."""
    acts = segment.prepare(trajectory, bug_id)
    result = assign(acts, targets, **options)
    result["actions"] = acts
    check_hierarchy(acts, result, name=f"bug-{bug_id}")
    return result


def action_labels(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One dict per action of a ``phases`` result: the labels the annotation sheets and the
    ground-truth scoring carry.  fix_stage is pre-fix before the anchor; attempt is the id
    of the repair attempt whose range (first edit to judging run) holds the action, or ""."""
    acts = result["actions"]
    sub_of: Dict[int, dict] = {}
    for s in result["phases"]:
        for sp in s["subphases"]:
            for x in range(sp["_lo"], sp["_hi"]):
                sub_of[x] = sp
    attempt_of = {x: at["id"] for at in result["attempts"]
                  for x in range(at["start"], at["end"] + 1)}
    anchor = result["context"].get("anchor", len(acts)) if acts else 0
    return [{"category": a["category"], "file_role": taxonomy.action_roles(a),
             "fix_stage": "pre-fix" if x < anchor else "post-fix",
             "phase": result["phase"][x], "own_phase": result["own_phase"][x],
             "subphase": sub_of[x]["id"], "subphase_outcome": sub_of[x]["outcome"],
             "subphase_evidence": sub_of[x]["evidence"], "attempt": attempt_of.get(x, "")}
            for x, a in enumerate(acts)]


# ----------------------------------------------------------------------------- metrics
def metrics(acts: List[dict], result: Dict[str, Any]) -> Dict[str, Any]:
    """Per-trajectory measures (spec §8).  Polls are left out of every count, so the five
    phase counts add up to ``tool_actions``."""
    final, spans, tries = result["phase"], result["phases"], result["attempts"]
    ctx = result["context"]
    work = [x for x, a in enumerate(acts) if a["category"] != "wait_process"]
    out: Dict[str, Any] = {"tool_actions": len(work)}
    for phase in PHASES:
        out[f"{phase}_actions"] = sum(1 for x in work if final[x] == phase)
    out["env_actions"] = sum(1 for x in work if acts[x]["category"] == "env_setup"
                             or _probe(acts[x]) or acts[x]["fail_kind"] == "env"
                             or (acts[x]["category"] in _EDITS
                                 and acts[x].get("edit_role") == "toolchain"))
    out["n_attempts"] = len(tries)
    out["n_failed_attempts"] = sum(1 for at in tries if at["outcome"] == "failed")
    out["n_blocked_attempts"] = sum(1 for at in tries if at["outcome"] == "blocked")
    out["attempts_to_first_pass"] = next((at["id"] for at in tries if at["outcome"] ==
                                          "succeeded" and at["evidence"] == "test"), None)
    counts = collections.Counter(s["phase"] for s in spans)
    out["repair_cycles"] = counts[REPAIR]
    out["reentries"] = {phase: max(0, counts[phase] - 1) for phase in PHASES}
    subs = [(s["phase"], sp) for s in spans for sp in s["subphases"]]
    out["reproduced_before_fix"] = any(p == REPRODUCTION and sp["outcome"] == "succeeded"
                                       for p, sp in subs)
    hit = next((x for x in work if any(_match(f, ctx["targets"]) for f in acts[x]["files"])),
               None)
    out["actions_to_first_found"] = sum(1 for x in work if x < hit) if hit is not None else None
    out["target_source"] = ctx["target_source"]
    out["blocked_subphases"] = sum(1 for _, sp in subs if sp["outcome"] == "blocked")
    for flag in FLAGS:
        out[f"{flag}_subphases"] = sum(1 for _, sp in subs if flag in sp["flags"])
    # behaviours too common to flag a stretch with, kept as per-run counts (V2 metrics)
    out["tool_errors"] = sum(1 for x in work if _tool_error(acts[x]))
    out["reverts"] = sum(1 for x in work if acts[x].get("reverts"))
    out["self_reviews"] = sum(1 for x in work if acts[x]["category"] == "diff"
                              or acts[x].get("_own_read"))
    for phase in (REPAIR, VALIDATION):
        last = next((sp for p, sp in reversed(subs) if p == phase), None)
        out[f"final_{phase}_outcome"] = last["outcome"] if last else None
        out[f"final_{phase}_evidence"] = last["evidence"] if last else None
    return out


# ----------------------------------------------------------------------------- invariants
def check_hierarchy(acts: List[dict], result: Dict[str, Any], name: str = "") -> None:
    """Raise ValueError on any violation of the spec's invariants (§6, §7)."""
    problems: List[str] = []
    spans, final = result["phases"], result["phase"]
    anchor = result["context"].get("anchor", len(acts)) if acts else 0
    pos = 0
    for s in spans:
        if s["_lo"] != pos:
            problems.append(f"{s['id']} starts at {s['_lo']}, expected {pos}")
        if s["phase"] not in PHASES:
            problems.append(f"{s['id']} has phase {s['phase']}")
        inner = s["_lo"]
        for k, sp in enumerate(s["subphases"]):
            if sp["_lo"] != inner:
                problems.append(f"{sp['id']} starts at {sp['_lo']}, expected {inner}")
            inner = sp["_hi"]
            if sp["outcome"] not in PHASE_OUTCOMES.get(s["phase"], ()):
                problems.append(f"{sp['id']} outcome {sp['outcome']} not allowed in {s['phase']}")
            if sp["evidence"] not in EVIDENCE:
                problems.append(f"{sp['id']} has evidence {sp['evidence']}")
            if k and s["subphases"][k - 1]["outcome"] == sp["outcome"]:
                problems.append(f"{sp['id']} repeats the outcome of the subphase before it")
            if set(sp["flags"]) - set(FLAGS):
                problems.append(f"{sp['id']} has unknown flags {set(sp['flags']) - set(FLAGS)}")
        if inner != s["_hi"]:
            problems.append(f"{s['id']}'s subphases end at {inner}, the span at {s['_hi']}")
        pos = s["_hi"]
    if pos != len(acts):
        problems.append(f"phases cover {pos} of {len(acts)} actions")
    for x, a in enumerate(acts):
        if source_edit(a) and final[x] != REPAIR:
            problems.append(f"source edit at action {a['action_index']} is in {final[x]}")
        if final[x] in PRE_ONLY and x >= anchor:
            problems.append(f"action {a['action_index']} is {final[x]} after the anchor")
        if final[x] in POST_ONLY and x < anchor:
            problems.append(f"action {a['action_index']} is {final[x]} before the anchor")
    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems[:10]))
