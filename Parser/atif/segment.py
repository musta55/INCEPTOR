"""Segmenter: action -> segment (a higher-level action) -> purpose.

Port of the validated prototype (``experiments/segments``, rules R1-R11; archived in
``Inspection/experiments-2026-09-30-prototypes.tar.gz``), deterministic
and rule-based.  Every action lands in exactly one segment, segments are contiguous,
every segment lands in exactly one purpose, purposes are contiguous; ``check_hierarchy``
enforces this and the rest of the ``trajview/1`` invariants.
"""
from __future__ import annotations

import collections
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import lookup, project, taxonomy, verdict as verdict_mod

# ----------------------------------------------------------------------------- classes
EXEC = {"build", "run_test", "device_ops", "run_shell"}
VERIFY = {"build", "run_test"}                      # actions that can decide an attempt
ORIENT = {"orient", "plan", "other"}

PATH_RE = re.compile(r"(?:~|/)?(?:[\w.\-+]+/)*[\w.\-+]+\.(?:java|kt|xml|gradle|kts|sh|properties"
                     r"|json|pro|txt|md|png|log|yml|yaml|py|csv|trt|cfg|toml)\b")
HARNESS_FILES = {"run_pipeline.sh", "local.properties", "gradle.properties",
                 "gradle-wrapper.properties"}
ENV_HINT = re.compile(r"JavaVirtualMachines|java_home|\.gradle(?:-local|-home)?/|jdk|/tmp/"
                      r"|\.android(?:-home|-local)?|ANDROID_(?:SDK|HOME)|sdkmanager|/Library/"
                      r"|/opt/|brew")
GENERIC_DIRS = {"java", "main", "src", "app", "res", "", ".", "kotlin"}
TEST_PATH = re.compile(r"reproducing_script_project|androidTest|/test/|^test/")
EXEC_KINDS = ("exec", "fix_attempt", "toolchain_fix", "test_edit")


def repo_rel(path: str, bug: str) -> Optional[str]:
    """Path relative to the bug checkout (a SWE-bench project: to the repository root), or
    None if it lies outside it."""
    proj = project.current()
    if proj.swebench:
        rest = proj.below_root(path)
        if rest is not None:
            return rest or "."
        if path.startswith(("/", "~")):
            return None
        return path[2:] if path.startswith("./") else path
    match = re.search(r"/bug-%s(?:/(.*)|/?$)" % re.escape(bug), path)
    if match:
        return match.group(1) or "."
    if path.startswith(("/", "~")):
        return None                                   # absolute path outside the repo
    return path[2:] if path.startswith("./") else path


def action_paths(a: dict) -> Tuple[List[str], List[str]]:
    """(inside-repo paths, outside-repo paths) touched by the action."""
    bug = a["bug_id"]
    raw: List[str] = []
    call = taxonomy.resolve_call({"function_name": a["tool"], "arguments": a.get("args") or {}})
    tool, args = call.get("function_name", ""), call.get("arguments") or {}
    if a["mid_level"] == "edit_file" and (tool == taxonomy.PATCH_TOOL
                                          or tool in taxonomy.SHELL_TOOLS):
        raw += taxonomy.edited_files(call)
    else:
        for key in taxonomy.PATH_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value:
                raw.append(value)
        text = a.get("cmd") or ""
        if text:
            raw += PATH_RE.findall(text)
            for token in re.findall(r"(?<![\w$])(/[\w.\-/+ ]+?)(?=[\s'\"]|$)", text):
                if token.count("/") >= 2:
                    raw.append(token.strip())
        if a["mid_level"] == "search_code" and isinstance(args.get("pattern"), str) \
                and "/" in args["pattern"]:
            raw.append(args["pattern"])
    inside: List[str] = []
    outside: List[str] = []
    for path in raw:
        rel = repo_rel(path, bug)
        if rel is not None:
            inside.append(rel)
        else:
            outside.append(path)
    return inside, outside


def norm_cmd(a: dict) -> str:
    """Core of a shell command, for 'identical repeated command' detection (R6)."""
    if a["mid_level"] == "wait_process":
        return "wait"
    c = a.get("cmd") or ""
    if not c or a["tool"] == taxonomy.PATCH_TOOL:
        return a["tool"] + ":" + (a.get("target") or "")[:120]
    parts = []
    for seg in re.split(r"&&|;|\n", c):
        seg = seg.strip()
        seg = re.split(r"\|\s*(?:tail|head|grep|sed|tee|awk|cut|sort|uniq|wc)\b", seg)[0]
        seg = seg.replace("2>&1", "").strip()
        toks = seg.split()
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])
                        or toks[0] in ("export", "env", "time", "nohup")):
            toks.pop(0)
        if not toks or toks[0] in ("cd", "export", "set", "mkdir", "echo", "true", "source",
                                   "pushd", "popd", "sleep"):
            continue
        parts.append(" ".join(toks))
    return " && ".join(parts)[:300] or c[:120]


#: pipeline stages that only filter or copy output; a re-run that differs only in these
#: is the same run looked at differently
OUTPUT_FILTERS = {"tail", "head", "grep", "egrep", "fgrep", "rg", "tee", "sed", "awk", "cut",
                  "sort", "uniq", "wc", "less", "more", "cat", "nl"}


def run_cmd(a: dict) -> str:
    """The command as run, for the strict stuck test (fix 1): whitespace-normalised, env
    assignments, ``export``s and ``mkdir``s kept, so that a re-run with a different
    ``GRADLE_USER_HOME`` or ``JAVA_HOME`` is a *different* command.  Only trailing
    output filters (``| tail -30``, ``| grep -A5 Assertion``, ``| tee log``) and the
    ``2>&1`` feeding them are dropped.  Splitting is quote-, ``$(...)``- and
    heredoc-aware (``taxonomy.split_commands``)."""
    c = a.get("cmd") or ""
    if not c or a["tool"] == taxonomy.PATCH_TOOL:
        return a["tool"] + ":" + json.dumps(a.get("args", {}), sort_keys=True, default=str)[:300]
    parts = taxonomy.split_commands(c)
    pipelines: List[List[str]] = [[]]
    seps: List[str] = []
    for segment_text, sep in parts:
        pipelines[-1].append(segment_text)
        if sep != "|":
            pipelines.append([])
            seps.append(sep)
    out: List[str] = []
    for stages, sep in zip(pipelines, seps):
        while len(stages) > 1:
            tokens = taxonomy._tokenize(stages[-1])
            if tokens and tokens[0].rsplit("/", 1)[-1] in OUTPUT_FILTERS:
                stages = stages[:-1]
            else:
                break
        if not stages:
            continue
        stages[-1] = re.sub(r"\s*2>&1\s*$", "", stages[-1])
        out.append(" | ".join(" ".join(x.split()) for x in stages))
        if sep and sep != "\n":
            out.append(sep)
        elif sep == "\n":
            out.append(";")
    text = " ".join(out).strip()
    return re.sub(r"\s*[;&|]+$", "", text) or " ".join(c.split())


def area(path: Optional[str]) -> Optional[str]:
    """Coarse code area used as the localization focus key (R4)."""
    if path is None:
        return None
    base = os.path.basename(path)
    if TEST_PATH.search(path):
        return "test-scripts"
    if base in HARNESS_FILES:
        return "harness"
    if base.endswith((".gradle", ".kts", ".pro")):
        return "build-config"
    if base == "AndroidManifest.xml":
        return "manifest"
    if "/res/" in "/" + path:
        match = re.search(r"res/([\w\-]+)", path)
        return "res/" + (match.group(1).split("-")[0] if match else "")
    d = os.path.dirname(path)
    last = os.path.basename(d)
    if last in GENERIC_DIRS:
        last = os.path.basename(os.path.dirname(d)) if last else ""
        if last in GENERIC_DIRS:
            return None
    return "src/" + last if last else None


# ----------------------------------------------------------------------------- enrichment
def enrich(acts: List[dict]) -> Tuple[int, int]:
    """Per-action fields the rules read.  Returns (first source edit, last edit) as
    positions into ``acts`` (``len(acts)`` / -1 when absent)."""
    by_index = {a["action_index"]: k for k, a in enumerate(acts)}
    for i, a in enumerate(acts):
        a["_i"] = i
        inside, outside = action_paths(a)
        a["files"] = sorted(set(p for p in inside if "*" not in p and (
            PATH_RE.fullmatch(p) or "." in os.path.basename(p))))
        a["outside"] = outside
        a["key"] = norm_cmd(a) if (a.get("cmd") and a["tool"] != taxonomy.PATCH_TOOL) else \
            a["tool"] + ":" + json.dumps(a.get("args", {}), sort_keys=True, default=str)[:300]
        a["run_key"] = run_cmd(a)
        a["error_sig"] = verdict_mod.error_signature(a.get("result") or "", a["fail_kind"]) \
            if a["verdict"] == "fail" else None
        mid = a["mid_level"]
        a["waits_pos"] = by_index.get(a.get("waits_on")) if a.get("waits_on") else None
        # R1: macro-class used for segmentation
        if mid in EXEC or mid == "env_setup" or mid == "wait_process":
            cls = "EXEC"
        elif mid == "edit_file":
            cls = "EDIT"
        elif mid == "vcs":
            cls = "VCS"
        else:
            cls = "EXPL"
            # R2: exploration of the harness / toolchain is part of execution work
            harness = any(os.path.basename(p) in HARNESS_FILES or p.startswith("build/")
                          or "/build/outputs" in p or p.endswith((".log", ".png"))
                          for p in inside)
            env_only = bool(outside) and not inside and (
                any(ENV_HINT.search(o) for o in outside)
                or not any(o.endswith((".java", ".kt", ".xml")) for o in outside))
            if harness or env_only or (mid in ("orient", "search_code")
                                       and ENV_HINT.search(a.get("cmd") or "")):
                cls = "EXEC"
                a["env_probe"] = True
        a["cls"] = cls
        areas = [x for x in (area(p) for p in inside if "*" not in p) if x]
        a["area"] = collections.Counter(areas).most_common(1)[0][0] if areas else None
    # R2c: phase anchor = first edit of application source
    first_src = taxonomy.first_source_edit(acts)
    first_src = len(acts) if first_src is None else first_src
    last_edit = max((i for i, a in enumerate(acts) if a["mid_level"] == "edit_file"),
                    default=-1)
    return first_src, last_edit


def _runs(seq: List[int], keyf) -> List[list]:
    out: List[list] = []
    for i, x in enumerate(seq):
        k = keyf(x)
        if out and out[-1][0] == k:
            out[-1][1].append(i)
        else:
            out.append([k, [i]])
    return out


# ----------------------------------------------------------------------------- segmentation
def delegated_scopes(acts: List[dict], i: int) -> int:
    """End (exclusive) of the actions ``taxonomy.actions`` spliced in after the delegate
    call ``acts[i]``: those of its sub-agent and of any sub-agent that one delegates to.
    A sub-agent whose steps the log does not hold (a background agent) adds none."""
    own = {acts[i].get("delegates_to") or "sub-" + str(acts[i]["call_id"])}
    j = i + 1
    while j < len(acts) and acts[j]["scope"] in own:
        if acts[j]["mid_level"] == "delegate":
            own.add(acts[j].get("delegates_to") or "sub-" + str(acts[j]["call_id"]))
        j += 1
    return j


def micro_units(acts: List[dict]) -> List[list]:
    """R1-R3: runs of the same macro-class, with delegation blocks and blip absorption."""
    blocks: List[list] = []
    i = 0
    while i < len(acts):
        a = acts[i]
        if a["mid_level"] == "delegate":         # R3a: delegate call + spliced sub-agent actions
            j = delegated_scopes(acts, i)
            blocks.append(["DELEG", list(range(i, j))])
            i = j
            continue
        if blocks and blocks[-1][0] == a["cls"]:
            blocks[-1][1].append(i)
        else:
            blocks.append([a["cls"], [i]])
        i += 1
    changed = True                               # R3b: blip absorption to a fixed point
    while changed:
        changed = False
        for k in range(1, len(blocks) - 1):
            c, idx = blocks[k]
            left, right = blocks[k - 1][0], blocks[k + 1][0]
            n = len(idx)
            mids = {acts[x]["mid_level"] for x in idx}
            # R3c / K1: a short git diff/status, or a single lookup, between an edit and its
            # verification run belongs to the fix attempt -> fold it into the EDIT block
            if left == "EDIT" and right == "EXEC" and (c == "VCS" and n <= 2
                                                       or c == "EXPL" and n == 1):
                blocks[k - 1][1] += idx
                del blocks[k]
                changed = True
                break
            if left != right or c == left or c == "DELEG" or left == "DELEG":
                continue
            absorb = False
            if c == "EXPL" and left == "EXEC" and n <= 1:
                absorb = True                    # glance at code/output between runs
            elif c == "EXPL" and left == "EDIT" and n <= 2:
                absorb = True                    # look-up while patching
            elif c == "VCS" and left in ("EDIT", "EXEC") and n <= 1:
                absorb = True                    # git diff/checkout between edits or runs
            elif mids <= {"orient", "wait_process", "plan"} and n <= 1:
                absorb = True                    # ls / wait / todo blip anywhere
            if absorb:
                blocks[k - 1][1] += idx + blocks[k + 1][1]
                del blocks[k:k + 2]
                changed = True
                break
    return blocks


def eff_mid(acts: List[dict], a: dict) -> str:
    w = a.get("waits_pos")
    return acts[w]["mid_level"] if w is not None else a["mid_level"]


def split_exec(acts: List[dict], idx: List[int]) -> List[List[int]]:
    """R5: cut an execution unit after a passing run_test, or after a passing build that
    ended a streak of failed builds, when more execution follows."""
    parts: List[List[int]] = []
    cur: List[int] = []
    failed_builds = 0
    for x in idx:
        a = acts[x]
        cur.append(x)
        v = a["verdict"]
        m = eff_mid(acts, a)
        if m == "build" and v == "fail":
            failed_builds += 1
        if v == "pass" and (m == "run_test" or (m == "build" and failed_builds > 0)):
            parts.append(cur)
            cur, failed_builds = [], 0
    if cur:
        if parts and len(cur) == 1 and acts[cur[0]]["mid_level"] in ("wait_process", "orient"):
            parts[-1] += cur
        else:
            parts.append(cur)
    return parts


def first_decisive(acts: List[dict], idx: List[int]) -> Optional[int]:
    """R5b: position (in idx) of the first run that decides a fix attempt: a failing
    build/run_test, or a passing run_test.  A passing build alone does not decide it."""
    for k, x in enumerate(idx):
        a = acts[x]
        m = eff_mid(acts, a)
        if m in VERIFY and a["verdict"] == "fail":
            return k
        if m == "run_test" and a["verdict"] == "pass":
            return k
    return None


def split_explore(acts: List[dict], idx: List[int]) -> List[Tuple[List[int], Optional[str]]]:
    """R4: split a localization unit where the code area in focus changes."""
    ar = [acts[x]["area"] for x in idx]
    nxt = None                                   # unknown targets bind forward, then backward
    for k in range(len(ar) - 1, -1, -1):
        if ar[k] is None:
            ar[k] = nxt
        else:
            nxt = ar[k]
    prv = None
    for k in range(len(ar)):
        if ar[k] is None:
            ar[k] = prv
        else:
            prv = ar[k]
    rr = _runs(list(range(len(idx))), lambda k: ar[k])
    merged: List[list] = []                      # singleton areas join the previous run
    for key, ks in rr:
        if merged and (len(ks) == 1 or key == merged[-1][0]):
            merged[-1][1] += ks
        else:
            merged.append([key, ks])
    if len(merged) > 1 and len(merged[0][1]) == 1:
        merged[1][1] = merged[0][1] + merged[1][1]
        merged.pop(0)
    return [([idx[k] for k in ks], key) for key, ks in merged]


def block_role(acts: List[dict], idx: List[int]) -> str:
    roles = {acts[x]["edit_role"] for x in idx if acts[x]["mid_level"] == "edit_file"}
    if "source" in roles or not roles:
        return "source"
    return "test" if "test" in roles else "toolchain"


def segment_actions(acts: List[dict]) -> Tuple[List[dict], List[dict], List[dict], int]:
    """Segments, purposes and loops (internal form) for enriched actions."""
    first_src, last_edit = enrich(acts)
    blocks = micro_units(acts)
    segs: List[dict] = []
    k = 0
    while k < len(blocks):
        c, idx = blocks[k]
        if c == "EDIT":
            role = block_role(acts, idx)
            kind = {"source": "fix_attempt", "test": "test_edit", "toolchain": "toolchain_fix"}[role]
            if k + 1 < len(blocks) and blocks[k + 1][0] == "EXEC":   # R5b: edits + their run
                ex = blocks[k + 1][1]
                cut = first_decisive(acts, ex)
                head, rest = (ex, []) if cut is None else (ex[:cut + 1], ex[cut + 1:])
                segs.append({"kind": kind, "idx": idx + head, "edit_role": role})
                for part in (split_exec(acts, rest) if rest else []):
                    segs.append({"kind": "exec", "idx": part})
                k += 2
                continue
            segs.append({"kind": kind, "idx": idx, "edit_role": role, "unverified": True})
        elif c == "EXEC":
            for part in split_exec(acts, idx):
                segs.append({"kind": "exec", "idx": part})
        elif c == "EXPL":
            for part, focus in split_explore(acts, idx):
                segs.append({"kind": "explore", "idx": part, "area": focus})
        elif c == "DELEG":
            segs.append({"kind": "delegate", "idx": idx})
        elif c == "VCS":
            segs.append({"kind": "vcs", "idx": idx})
        k += 1
    ctx = {"first_src": first_src, "last_edit": last_edit,
           "edited": set(f for a in acts if a["mid_level"] == "edit_file" for f in a["files"])}
    for s in segs:
        describe(acts, s, ctx)
    segs = merge_stuck(acts, segs, ctx)
    assign_outcomes(acts, segs, ctx)
    purposes = build_purposes(acts, segs, ctx)
    loops = detect_loops(purposes, segs)
    return segs, purposes, loops, first_src


# ----------------------------------------------------------------------------- description
EXPLORE_ASK = re.compile(r"^\s*(find|read|search|explore|quickly explore|i need to understand"
                         r"|i'm investigating|in .{0,120}?find and read)", re.I)
EDIT_ASK = re.compile(r"\b(replace|fix|make|modify|change|update|implement|add|remove|rewrite"
                      r"|refactor|apply)\b", re.I)


def delegated_edit(a: dict) -> bool:
    """R3a: a delegation is an edit delegation when its instruction asks for a change.
    A sub-agent type without edit tools (``taxonomy.READ_ONLY_SUBAGENTS``, the
    ``Explore`` agent of Claude Code and Qwen Code) never edits, whatever the instruction
    says: its prompts restate the bug ("... should update ...") and start "I need to find"."""
    args = a.get("args") or {}
    kind = str(args.get(taxonomy.SUBAGENT_TYPE_KEY) or "")
    if kind.startswith(taxonomy.READ_ONLY_SUBAGENTS):
        return False
    text = next((v for k in taxonomy.DELEGATE_PROMPT_KEYS
                 for v in [args.get(k)] if isinstance(v, str) and v), a.get("target") or "")
    return not EXPLORE_ASK.search(text) and bool(EDIT_ASK.search(text[:600]))


def edit_roles(acts: List[dict], idx: List[int]) -> List[str]:
    """Roles of the files the segment edits: source, test, toolchain, or harness (the
    benchmark's check script, which ``taxonomy.file_role`` counts as toolchain)."""
    roles = set()
    for x in idx:
        a = acts[x]
        if a["mid_level"] != "edit_file":
            continue
        if not a["files"]:
            roles.add(a.get("edit_role") or "source")
        for f in a["files"]:
            roles.add("harness" if os.path.basename(f) == "run_pipeline.sh"
                      else taxonomy.file_role(f))
    return sorted(roles)


def executed_test(s: dict) -> bool:
    """Q4: the segment's decisive run is a test run (or a poll of one) that executed: it
    passed, or it failed with kind ``test``."""
    return s["decisive_mid"] == "run_test" and (
        s["verdict"] == "pass" or (s["verdict"] == "fail" and s["fail_kind"] == "test"))


def run_type(s: dict) -> str:
    """Q4-Q7 of the codebook's type procedure (§3.3), for a segment that runs something or
    edits only non-source files.  Q6 reads the purpose of an ``exec`` segment, so
    ``seg_purpose`` calls this only for edit segments."""
    pre = s["pre_fix"]
    if executed_test(s):                                                         # Q4
        if pre:
            return "reproduction_succeeded" if s["verdict"] == "fail" \
                else "reproduction_not_reproduced"
        return "validation_passed" if s["verdict"] == "pass" else "validation_failed"
    roles = set(s["edit_roles"])
    if roles and roles <= {"test", "harness"} and not s["has_decisive"]:          # Q5
        return "test_or_harness_modification"
    if "toolchain" in roles or (s["kind"] == "exec" and s["purpose"] == "environment"):
        return "toolchain_wrestling"                                             # Q6
    if s["verdict"] == "fail":
        return "reproduction_blocked" if pre else "validation_blocked_by_env"
    return "reproduction_other" if pre else "validation_other"                  # Q7


def seg_purpose(acts: List[dict], s: dict, ctx: dict) -> str:
    idx, first_src = s["idx"], ctx["first_src"]
    mids = [acts[x]["mid_level"] for x in idx]
    pre = idx[0] < first_src
    if s["kind"] == "fix_attempt":
        return "repair"
    if s["kind"] in ("toolchain_fix", "test_edit"):   # §4.1: the own purpose of its type
        t = run_type(s)
        if t == "test_or_harness_modification":
            return "reproduction" if pre else "repair"
        return "environment" if t == "toolchain_wrestling" else t.split("_", 1)[0]
    if s["kind"] == "vcs":
        return "review"
    if s["kind"] == "delegate":
        return "repair" if ("edit_file" in mids or delegated_edit(acts[idx[0]])) \
            else "localization"
    if s["kind"] == "explore":
        if all(m in ORIENT for m in mids):
            return "orientation"                 # planning is not a purpose
        # R10: after the last edit, reading back only files one has edited = patch review
        if idx[0] > ctx["last_edit"] >= 0 and s["files"] and set(s["files"]) <= ctx["edited"]:
            s["reads_own_patch"] = True
            return "review"
        return "localization"
    # exec
    if all(acts[x]["mid_level"] == "wait_process" for x in idx) \
            and acts[idx[0]].get("waits_pos") is not None:
        return "reproduction" if acts[idx[0]]["waits_pos"] < first_src else "validation"
    if s.get("decisive_mid") == "run_test":     # a test decided it: not just env work
        return "reproduction" if pre else "validation"
    env = sum(1 for x in idx if acts[x]["mid_level"] == "env_setup" or acts[x].get("env_probe"))
    verif = [x for x in idx if acts[x]["mid_level"] in VERIFY]
    if env * 2 >= len(idx) and not any(acts[x]["verdict"] == "pass"
                                       and acts[x]["mid_level"] == "run_test" for x in idx):
        return "environment"
    if not verif and all(acts[x]["mid_level"] in ("orient", "wait_process")
                         or acts[x].get("env_probe") for x in idx):
        return "environment"
    return "reproduction" if pre else "validation"


def decisive(acts: List[dict], idx: List[int]) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Verdict that decides the segment: the last pass/fail of a build/run_test (or of a
    wait on one); only if there is none, the last pass/fail of device_ops/run_shell.
    Returns (verdict, fail_kind, action position)."""
    for tier in (VERIFY, {"device_ops", "run_shell"}):
        for x in reversed(idx):
            a = acts[x]
            if eff_mid(acts, a) in tier and a["verdict"] in ("pass", "fail"):
                return a["verdict"], a["fail_kind"], x
    return None, None, None


def _failed(a: dict) -> bool:
    return a["verdict"] == "fail" or a.get("failed") is True


def failing_runs(acts: List[dict], idx: List[int]) -> List[dict]:
    """Failing executions in ``idx``, one per run: a poll of a background session is
    attributed to the command that started it, so polling one failed run three times
    is one failure, not three."""
    runs: Dict[int, dict] = {}
    for x in idx:
        a = acts[x]
        if a["verdict"] != "fail" or a["mid_level"] not in verdict_mod.EXEC_MIDS:
            continue
        start = a["waits_pos"] if a["mid_level"] == "wait_process" else x
        if start is None:
            continue                             # a wait on nothing we know
        started = acts[start]
        runs[start] = {"pos": start, "end": x, "run_key": started["run_key"],
                       "key": started["key"], "sig": a["error_sig"]}
    return [runs[k] for k in sorted(runs)]


def _changes_between(acts: List[dict], lo: int, hi: int) -> bool:
    """Whether an edit or an environment change happened strictly between two runs."""
    return any(acts[x]["mid_level"] in ("edit_file", "env_setup") for x in range(lo + 1, hi))


def strict_repeats(acts: List[dict], runs: List[dict]) -> Tuple[Dict[str, int], int]:
    """Fix 1.  ({run_key: runs in the repeating chain}, number of progressing repeats).

    A repeat is *strict* (stuck) when the same full command fails again with the same
    error signature and no ``edit_file`` / ``env_setup`` action lies between the two
    runs.  A repeat that only matches after the loose ``norm_cmd`` normalisation (env
    prefix changed, error changed, or something was changed in between) is a
    progressing workaround and is counted separately, for ``env_wrestling``."""
    strict: Dict[str, int] = {}
    progressing = 0
    previous: Dict[str, dict] = {}
    for run in runs:
        last = previous.get(run["key"])
        if last is not None:
            if last["run_key"] == run["run_key"] and last["sig"] == run["sig"] \
                    and not _changes_between(acts, last["end"], run["pos"]):
                strict[run["run_key"]] = strict.get(run["run_key"], 1) + 1
            else:
                progressing += 1
        previous[run["key"]] = run
    return strict, progressing


def describe(acts: List[dict], s: dict, ctx: dict) -> None:
    idx = s["idx"]
    s["start"] = acts[idx[0]]["action_index"]
    s["end"] = acts[idx[-1]]["action_index"]
    s["steps"] = [acts[x]["action_index"] for x in idx]
    s["mid_seq"] = [acts[x]["mid_level"] for x in idx]
    s["n"] = len(idx)
    files: List[str] = []
    for x in idx:
        for f in acts[x]["files"]:
            if f not in files:
                files.append(f)
    s["files"] = files
    s["verdict"], s["fail_kind"], s["verdict_at"] = decisive(acts, idx)
    s["decisive_mid"] = eff_mid(acts, acts[s["verdict_at"]]) if s["verdict_at"] is not None \
        else None
    s["pre_fix"] = idx[0] < ctx["first_src"]
    s["has_decisive"] = first_decisive(acts, idx) is not None
    s["edit_roles"] = edit_roles(acts, idx)
    s["purpose"] = seg_purpose(acts, s, ctx)
    s["raw_failed"] = [acts[x]["action_index"] for x in idx if acts[x].get("failed") is True]
    s["verdict_failed"] = [acts[x]["action_index"] for x in idx if acts[x]["verdict"] == "fail"]
    s["failed_steps"] = sorted(set(s["raw_failed"]) | set(s["verdict_failed"]))
    keys = [acts[x]["key"] for x in idx]
    s["distinct_targets"] = len(set(keys))
    s["repetition_ratio"] = 1 - len(set(keys)) / len(keys)
    s["failing_runs"] = failing_runs(acts, idx)
    s["repeated_failing"], s["progressing_repeats"] = strict_repeats(acts, s["failing_runs"])
    s["env_actions"] = sum(1 for x in idx if acts[x]["mid_level"] == "env_setup"
                           or acts[x].get("env_probe"))
    s["fail_kinds"] = dict(collections.Counter(acts[x]["fail_kind"] for x in idx
                                               if acts[x]["fail_kind"]))


def merge_stuck(acts: List[dict], segs: List[dict], ctx: dict) -> List[dict]:
    """R6: two execution segments of the same purpose that both end in the same failing
    run -- the same full command (``run_cmd``) with the same error signature -- separated
    by at most one explore/exec segment of <= 3 actions and with no edit or env_setup
    between the two runs, are one 'stuck' segment."""
    def last_fail_key(s):
        if s["kind"] != "exec" or s["verdict"] != "fail" or not s["failing_runs"]:
            return None
        run = s["failing_runs"][-1]
        return run["run_key"], run["sig"]

    def unchanged(a, b):
        return not _changes_between(acts, a["failing_runs"][-1]["end"], b["failing_runs"][-1]["pos"])
    changed = True
    while changed:
        changed = False
        for j in range(len(segs) - 1):
            a = segs[j]
            ka = last_fail_key(a)
            if ka is None:
                continue
            for gap in (0, 1):
                c = j + 1 + gap
                if c >= len(segs):
                    break
                if gap and not (segs[j + 1]["kind"] in ("explore", "exec") and segs[j + 1]["n"] <= 3):
                    break
                b = segs[c]
                if b["purpose"] == a["purpose"] and last_fail_key(b) == ka and unchanged(a, b):
                    idx = [x for t in segs[j:c + 1] for x in t["idx"]]
                    new = {"kind": "exec", "idx": idx, "merged_stuck": True}
                    describe(acts, new, ctx)
                    new["purpose"] = a["purpose"]
                    segs[j:c + 1] = [new]
                    changed = True
                    break
            if changed:
                break
    return segs


# ----------------------------------------------------------------------------- outcome
#: which later purposes count as a retry of a failed segment
FAMILY = {"repair": {"repair", "validation", "environment"},
          "validation": {"validation", "repair"},
          "reproduction": {"reproduction", "environment"},
          "environment": {"environment", "reproduction", "validation"},
          "localization": {"localization"}, "review": {"review"},
          "orientation": {"orientation", "localization"}}


def exec_outcome(s: dict, pre: bool) -> Tuple[str, str]:
    """R7: outcome + detail of an execution-bearing segment."""
    v, fk = s["verdict"], s["fail_kind"]
    stuck = bool(s["repeated_failing"]) or s.get("merged_stuck")
    if s.get("unverified"):
        return "unverified", "edit_not_followed_by_run"
    if v is None:
        return "no_verdict", "no_decisive_run"
    if pre:                                      # fix 2: every segment before the anchor
        if v == "fail" and fk == "test":
            return "succeeded", "reproduced"     # the test runs and fails before the fix
        if v == "fail":
            return ("looped" if stuck else "failed"), "blocked_" + (fk or "exit")
        ran_test = s.get("decisive_mid") == "run_test"
        return ("failed", "not_reproduced") if ran_test else ("succeeded", "builds")
    if s["kind"] == "toolchain_fix" and not executed_test(s):   # an executed test: Q4 below
        if v == "pass" or fk == "test":
            return "succeeded", "toolchain_fixed"
        return ("looped" if stuck else "failed"), "blocked_" + (fk or "exit")
    if v == "pass":
        return "succeeded", ("tests_pass" if s["decisive_mid"] == "run_test" else
                             "builds" if s["decisive_mid"] == "build" else "ran_ok")
    detail = {"test": "tests_fail", "build": "patch_breaks_build",
              "env": "blocked_env"}.get(fk, "blocked_exit")
    return ("looped" if stuck else "failed"), detail


def assign_outcomes(acts: List[dict], segs: List[dict], ctx: dict) -> None:
    """R7/R8: outcome and flags per segment."""
    for j, s in enumerate(segs):
        flags: List[str] = []
        idx = s["idx"]
        last = acts[idx[-1]]
        nxt = segs[j + 1] if j + 1 < len(segs) else None
        pre = idx[0] < ctx["first_src"]
        if s["kind"] in EXEC_KINDS:
            outcome, detail = exec_outcome(s, pre)
            if outcome == "succeeded" and s["repeated_failing"]:
                flags.append("recovered_after_repeats")
        else:
            detail = None
            nf = len(s["raw_failed"])
            same = collections.Counter(acts[x]["key"] for x in idx)
            if nf and (last.get("failed") is True or nf * 2 >= len(idx)):
                outcome, detail = "failed", "tool_errors"
            elif any(v >= 2 for v in same.values()) and s["kind"] == "explore" \
                    and s["repetition_ratio"] >= 0.34:
                outcome, detail = "looped", "repeats_same_lookup"
            else:
                outcome = "completed"
        if outcome in ("failed", "looped"):
            fam = FAMILY.get(s["purpose"], {s["purpose"]})
            if s["kind"] in EXEC_KINDS:
                later = [t for t in segs[j + 1:] if t["purpose"] in fam
                         and t["kind"] in EXEC_KINDS + ("delegate",)]
            else:
                later = [t for t in segs[j + 1:] if t["purpose"] in fam]
            if nxt is None:
                flags.append("ends_trajectory_unresolved")
            elif later and later[0] is nxt:
                flags.append("retried_immediately")
            elif later:
                flags.append("retried_after_detour")
            else:
                flags.append("abandoned")
        if s["repeated_failing"] or s.get("merged_stuck"):
            flags.append("stuck_repeating_command")
        if s["kind"] in EXEC_KINDS and (s["fail_kinds"].get("env")
                                        or s["progressing_repeats"]):
            flags.append("env_wrestling")      # includes re-runs that changed something
        edited = [f for x in idx if acts[x]["mid_level"] == "edit_file" for f in acts[x]["files"]]
        if s["kind"] == "toolchain_fix":
            flags.append("edits_toolchain")
            if any("run_pipeline.sh" in f for f in edited):
                flags.append("edits_harness")
        if s["kind"] == "test_edit" or (s["kind"] == "delegate" and s["purpose"] == "repair"
                                        and "reproducing_script_project" in
                                        (acts[idx[0]].get("target") or "")):
            flags.append("edits_test_script")
        if s["kind"] == "fix_attempt" and any(taxonomy.file_role(f) == "test" for f in edited):
            flags.append("edits_test_script")
        if any(acts[x]["mid_level"] == "vcs" and re.search(r"git (checkout|restore|stash|reset)",
                                                           acts[x].get("cmd") or "") for x in idx):
            flags.append("reverts_changes")
        if s["kind"] == "explore" and s["n"] >= 3 and s["purpose"] == "localization":
            app_files = [f for f in s["files"] if area(f) and area(f).startswith(("src/", "res/"))]
            if app_files and not (set(app_files) & ctx["edited"]) \
                    and len(app_files) == len(s["files"]):
                flags.append("off_patch_exploration")
            reads = collections.Counter(f for x in idx if acts[x]["mid_level"] == "read_file"
                                        for f in acts[x]["files"])
            if any(v >= 3 for v in reads.values()):
                flags.append("rereads_same_file")
        if s["raw_failed"]:
            flags.append("tool_errors")
        s["outcome"], s["outcome_detail"], s["flags"] = outcome, detail, flags
        s["label"] = make_label(acts, s)


def _short(p: str) -> str:
    return os.path.basename(p) if p else p


def _fs(names: List[str]) -> str:
    unique: List[str] = []
    for x in names:
        if _short(x) not in unique:
            unique.append(_short(x))
    return ", ".join(unique[:3]) + (" +%d" % (len(unique) - 3) if len(unique) > 3 else "")


DETAIL_TXT = {"reproduced": "bug reproduced (test fails)", "blocked_env": "blocked by toolchain/env",
              "blocked_build": "blocked: project does not compile",
              "blocked_exit": "blocked (non-zero exit)", "blocked_test": "test fails",
              "not_reproduced": "test passes before fix", "builds": "builds",
              "tests_pass": "tests pass", "tests_fail": "tests still fail",
              "patch_breaks_build": "patch breaks build", "toolchain_fixed": "toolchain now works",
              "ran_ok": "command succeeded", "no_decisive_run": "no verdict",
              "edit_not_followed_by_run": "not verified"}


def make_label(acts: List[dict], s: dict) -> str:
    k, p = s["kind"], s["purpose"]
    d = DETAIL_TXT.get(s["outcome_detail"], s["outcome_detail"] or "")
    stuck = " [stuck]" if s["outcome"] == "looped" else ""
    edited = [f for x in s["idx"] if acts[x]["mid_level"] == "edit_file" for f in acts[x]["files"]]
    nv = sum(1 for m in s["mid_seq"] if m in VERIFY)
    ne = s["mid_seq"].count("edit_file")
    if k == "explore":
        if p == "orientation":
            return "Plan / update todo list" if all(m == "plan" for m in s["mid_seq"]) \
                else "Orient in workspace"
        if p == "review":
            return f"Re-read own patch: {_fs(s['files'])}"
        ar = s.get("area") or "code"
        n_read, n_search = s["mid_seq"].count("read_file"), s["mid_seq"].count("search_code")
        verb = "Sweep" if n_read >= 3 and len(s["files"]) >= 3 else (
            "Search" if n_search > n_read else "Inspect")
        fs = _fs(s["files"])
        if not fs:                               # pattern-only searches: show the patterns
            pats: List[str] = []
            for x in s["idx"]:
                t = re.sub(r"\s+", " ", str((acts[x].get("args") or {}).get("pattern")
                                            or acts[x].get("target") or ""))[:40]
                if t and t not in pats:
                    pats.append(t)
            if not pats:
                return f"{verb} {ar}"
            return (f"{verb} for " + "; ".join("'%s'" % t for t in pats[:2])
                    + (" +%d" % (len(pats) - 2) if len(pats) > 2 else ""))
        return f"{verb} {ar}: {fs}"
    if k == "delegate":
        return f"Delegated {'edit' if p == 'repair' else 'exploration'} ({s['n'] - 1} sub-agent actions)"
    if k == "vcs":
        return "Review diff / git state"
    if k == "fix_attempt":
        if s.get("unverified"):
            return f"Edit {_fs(edited) or 'code'} (not verified)"
        return f"Fix attempt: {ne} edit(s) to {_fs(edited) or 'code'} -> {nv} run(s): {d}{stuck}"
    if k == "toolchain_fix":
        if s.get("unverified"):
            return f"Toolchain edit {_fs(edited)} (not verified)"
        return f"Toolchain fix: edit {_fs(edited)} -> {nv} run(s): {d}{stuck}"
    if k == "test_edit":
        if s.get("unverified"):
            return f"Edit test script {_fs(edited)} (not verified)"
        return f"Modify test script {_fs(edited)} -> {nv} run(s): {d}{stuck}"
    if all(m == "wait_process" for m in s["mid_seq"]):
        w = acts[s["idx"][0]].get("waits_pos")
        if w is None:
            return "Wait for process"
        return (f"Wait for background run from action {acts[w]['action_index']}"
                + (f": {d}" if s["verdict"] else ""))
    if p == "environment":
        return f"Toolchain/environment setup ({s['env_actions']} env actions): {d}{stuck}"
    what = "Reproduce" if p == "reproduction" else "Validate"
    extra = " with env fixes" if s["env_actions"] else ""
    return f"{what}: {nv} run(s){extra}: {d}{stuck}"


# ----------------------------------------------------------------------------- purposes, loops
ABSORB_MAX = 3
REPRO_REACH = 2                   # R9c: how many segments away a reproduction segment may be
REPAIR_GAP_MAX = 10               # R9b cap in actions
REPAIR_GAP_OK = {"localization", "validation", "environment", "orientation", "review"}
ABSORBABLE_ANYWHERE = {"orientation"}
#: (segment purpose, host purpose) pairs that may nest when sandwiched (R9a)
ABSORBABLE_INTO = {("localization", "repair"), ("validation", "repair"),
                   ("environment", "reproduction"), ("environment", "validation"),
                   ("environment", "repair"), ("localization", "validation"),
                   ("environment", "localization"), ("localization", "reproduction"),
                   ("review", "repair"), ("localization", "environment")}


def build_purposes(acts: List[dict], segs: List[dict], ctx: dict) -> List[dict]:
    """R9: purposes are maximal runs of segments with the same host purpose, where
      (a) a segment of <= ABSORB_MAX actions sandwiched between two segments of the same
          purpose nests in it, for the (segment, host) pairs in ABSORBABLE_*;
      (b) fix-verify loop: a run of localization / validation / environment / orientation /
          review segments between two repair segments, with <= REPAIR_GAP_MAX actions in
          total, nests in one 'repair' purpose;
      (c) reproduction effort: before the first source edit, environment segments within
          REPRO_REACH segments of a reproduction segment nest in 'reproduction'.
    A nested segment keeps its own purpose label at segment level (field ``purpose``)."""
    host = [s["purpose"] for s in segs]
    changed = True                               # (c)
    while changed:
        changed = False
        for j, s in enumerate(segs):
            if host[j] == "environment" and s["idx"][0] < ctx["first_src"]:
                near = [host[t] for t in range(j - REPRO_REACH, j + REPRO_REACH + 1)
                        if 0 <= t < len(segs) and t != j]
                if "reproduction" in near:
                    host[j] = "reproduction"
                    changed = True
    for j in range(1, len(segs) - 1):            # (a)
        h, me = host[j - 1], host[j]
        if h != host[j + 1] or me == h or segs[j]["n"] > ABSORB_MAX:
            continue
        if me in ABSORBABLE_ANYWHERE or (me, h) in ABSORBABLE_INTO:
            host[j] = h
    rep = [j for j, label in enumerate(host) if label == "repair"]   # (b)
    for a, b in zip(rep, rep[1:]):
        gap = range(a + 1, b)
        if gap and all(host[g] in REPAIR_GAP_OK for g in gap) \
                and sum(segs[g]["n"] for g in gap) <= REPAIR_GAP_MAX:
            for g in gap:
                host[g] = "repair"
    purposes: List[dict] = []
    for j, s in enumerate(segs):
        s["purpose_host"] = host[j]
        if purposes and purposes[-1]["label"] == host[j]:
            purposes[-1]["seg_idx"].append(j)
        else:
            purposes.append({"label": host[j], "seg_idx": [j]})
    for p in purposes:
        ss = [segs[j] for j in p["seg_idx"]]
        p["start"], p["end"] = ss[0]["start"], ss[-1]["end"]
        p["n_actions"] = sum(s["n"] for s in ss)
    return purposes


def detect_loops(purposes: List[dict], segs: List[dict]) -> List[dict]:
    """R11 loop overlay.
    fix_verify_loop  : a repair purpose holding >= 2 fix attempts / edits where at least
                       one attempt or nested re-verification failed.
    reproduction_loop: >= 2 failed (blocked / not reproduced) reproduction or environment
                       execution segments before the first source edit (waits excluded).
    stuck_segment    : any segment that repeats an identical failing command."""
    loops: List[dict] = []
    for pi, p in enumerate(purposes):
        if p["label"] != "repair":
            continue
        ss = [segs[x] for x in p["seg_idx"]]
        att = [s for s in ss if s["kind"] in ("fix_attempt", "test_edit", "toolchain_fix")
               or (s["kind"] == "delegate" and s["purpose"] == "repair")]
        bad = [s for s in ss if s["outcome"] in ("failed", "looped") and s["kind"] in EXEC_KINDS]
        if len(att) >= 2 and bad:
            last_ok = ss[-1]["outcome"] == "succeeded" or (
                pi + 1 < len(purposes) and purposes[pi + 1]["label"] == "validation"
                and segs[purposes[pi + 1]["seg_idx"][0]]["outcome"] == "succeeded")
            loops.append({"type": "fix_verify_loop", "purpose": pi, "start": p["start"],
                          "end": p["end"], "iterations": len(att),
                          "failed_iterations": sum(1 for s in att
                                                   if s["outcome"] in ("failed", "looped")),
                          "failed_segments": len(bad),
                          "ended": "succeeded" if last_ok else "unresolved"})
    first_src_start = next((t["start"] for t in segs if t["kind"] == "fix_attempt"), 10 ** 9)
    pre = [s for s in segs if s["purpose"] in ("reproduction", "environment")
           and s["kind"] in EXEC_KINDS and not all(m == "wait_process" for m in s["mid_seq"])
           and s["start"] < first_src_start]
    bad = [s for s in pre if s["outcome"] in ("failed", "looped")]
    if len(bad) >= 2:
        loops.append({"type": "reproduction_loop", "start": bad[0]["start"], "end": bad[-1]["end"],
                      "iterations": len(pre), "failed_iterations": len(bad),
                      "ended": "reproduced" if any(s["outcome_detail"] == "reproduced" for s in pre)
                      else ("succeeded" if any(s["outcome"] == "succeeded" for s in pre)
                            else "unresolved")})
    for j, s in enumerate(segs):
        if "stuck_repeating_command" in s["flags"]:
            loops.append({"type": "stuck_segment", "segment": j, "start": s["start"],
                          "end": s["end"], "repeated": s["repeated_failing"],
                          "ended": s["outcome"]})
    return loops


# ----------------------------------------------------------------------------- codebook v0
#: segment types, in the precedence order of ``segment_type``
SEGMENT_TYPES = ("stuck_repeating_failure", "test_or_harness_modification",
                 "reproduction_succeeded", "reproduction_blocked", "reproduction_not_reproduced",
                 "reproduction_other", "toolchain_wrestling", "unverified_edit",
                 "fix_attempt_passed", "fix_attempt_failed", "fix_attempt_breaks_build",
                 "fix_attempt_blocked_by_env", "fix_attempt_other", "validation_passed",
                 "validation_failed", "validation_blocked_by_env", "validation_other",
                 "delegated_edit", "delegated_exploration", "review_patch",
                 "orientation_planning", "lookup_tool_errors",
                 "file_by_file_localization_sweep", "targeted_lookup", "other")
KINDS = ("exec", "fix_attempt", "toolchain_fix", "test_edit", "explore", "delegate", "vcs")
OUTCOMES = ("succeeded", "failed", "looped", "unverified", "completed", "no_verdict")
FLAGS = ("retried_immediately", "retried_after_detour", "abandoned",
         "ends_trajectory_unresolved", "stuck_repeating_command", "env_wrestling",
         "edits_toolchain", "edits_harness", "edits_test_script", "reverts_changes",
         "off_patch_exploration", "rereads_same_file", "tool_errors", "recovered_after_repeats")
LOOP_TYPES = ("fix_verify_loop", "reproduction_loop", "stuck_segment")
LOOP_ENDINGS = ("passed", "failed", "abandoned")


def segment_type(s: dict) -> str:
    """Codebook §3.3: the questions Q1-Q11, asked in their order; the first yes gives the
    type.  ``orientation_planning`` keeps its v0 name although ``planning`` is no longer a
    purpose."""
    k, p, d = s["kind"], s["purpose"], s["outcome_detail"]
    if k in EXEC_KINDS and s["outcome"] == "looped":                            # Q1
        return "stuck_repeating_failure"
    if k == "delegate":                                                         # Q2
        return "delegated_" + ("edit" if p == "repair" else "exploration")
    if k == "fix_attempt":                                                      # Q3
        if s.get("unverified"):
            return "unverified_edit"
        return {"tests_pass": "fix_attempt_passed", "tests_fail": "fix_attempt_failed",
                "patch_breaks_build": "fix_attempt_breaks_build",
                "blocked_env": "fix_attempt_blocked_by_env"}.get(d, "fix_attempt_other")
    if k in EXEC_KINDS:                                                         # Q4-Q7
        return run_type(s)
    if k == "vcs" or p == "review":                                             # Q8
        return "review_patch"
    if p == "orientation":                                                      # Q9
        return "orientation_planning"
    if k == "explore":                                                          # Q10
        if s["outcome"] == "failed":
            return "lookup_tool_errors"
        if s["mid_seq"].count("read_file") >= 3 and len(s["files"]) >= 3:
            return "file_by_file_localization_sweep"
        return "targeted_lookup"
    return "other"                                                              # Q11


# ----------------------------------------------------------------------------- contract form
def _loop_ending(success: bool, end: int, segs: List[dict]) -> str:
    """passed when the loop's last attempt succeeded; failed when nothing was executed
    after it (the run ended in the loop); abandoned when the agent moved on."""
    if success:
        return "passed"
    later = [t for t in segs if t["start"] > end and t["kind"] in EXEC_KINDS]
    return "abandoned" if later else "failed"


def _contract_loops(acts: List[dict], segs: List[dict], loops: List[dict],
                    seg_ids: Dict[int, str]) -> List[dict]:
    out: List[dict] = []
    for loop in loops:
        if loop["type"] == "stuck_segment":
            s = segs[loop["segment"]]
            keys = set(s["repeated_failing"])
            last = s["failing_runs"][-1] if s["failing_runs"] else None
            if last is not None and not keys:     # merged across segments (R6)
                keys = {last["run_key"]}
            passed_later = any(a["run_key"] in keys and a["verdict"] == "pass"
                               for a in acts if a["action_index"] > s["end"])
            repeats = max(list(s["repeated_failing"].values()) + [2])
            item = {"type": "stuck_segment", "start": s["start"], "end": s["end"],
                    "iterations": repeats, "failed_iterations": repeats,
                    "ended": _loop_ending(passed_later, s["end"], segs)}
        else:
            success = loop["ended"] in ("succeeded", "reproduced")
            item = {"type": loop["type"], "start": loop["start"], "end": loop["end"],
                    "iterations": loop["iterations"],
                    "failed_iterations": loop["failed_iterations"],
                    "ended": _loop_ending(success, loop["end"], segs)}
        item["segment_ids"] = [seg_ids[j] for j, t in enumerate(segs)
                               if t["start"] >= item["start"] and t["end"] <= item["end"]]
        out.append(item)
    return out


def hierarchy(acts: List[dict], segs: List[dict], purposes: List[dict],
              loops: List[dict]) -> Dict[str, Any]:
    """Purposes, segments and loops in the ``trajview/1`` shape."""
    seg_ids = {j: f"s{j + 1}" for j in range(len(segs))}
    out_purposes: List[dict] = []
    for pi, p in enumerate(purposes):
        items: List[dict] = []
        for j in p["seg_idx"]:
            s = segs[j]
            items.append({
                "id": seg_ids[j], "type": segment_type(s), "kind": s["kind"],
                "label": s["label"], "purpose": s["purpose"],
                "nested": s["purpose"] != s["purpose_host"],
                "outcome": s["outcome"], "outcome_detail": s["outcome_detail"],
                "start": s["start"], "end": s["end"], "steps": s["steps"],
                "flags": s["flags"],
                # additive
                "n_actions": s["n"], "mid_seq": s["mid_seq"], "files": s["files"][:8],
                "failed_steps": s["failed_steps"], "fail_kinds": s["fail_kinds"],
            })
        out_purposes.append({"id": f"p{pi + 1}", "label": p["label"], "start": p["start"],
                             "end": p["end"], "n_actions": p["n_actions"], "segments": items})
    return {"purposes": out_purposes, "loops": _contract_loops(acts, segs, loops, seg_ids)}


VOCAB = {"mid": list(taxonomy.MID_LEVEL), "purposes": list(taxonomy.PHASES),
         "segment_types": list(SEGMENT_TYPES), "flags": list(FLAGS)}


def check_hierarchy(obj: Dict[str, Any], n_actions: int, actions: Optional[List[dict]] = None,
                    name: str = "") -> None:
    """Raise ValueError listing every violation of the ``trajview/1`` invariants:

    1. ``actions[k].i == k + 1`` (when ``actions`` is given);
    2. purposes are contiguous and cover 1..n_actions exactly once;
    3. segments inside a purpose are contiguous and cover that purpose exactly once;
    4. ``steps == range(start, end + 1)``;
    5. loop ``segment_ids`` refer to segment ids of the same trajectory;
    6. every segment type, purpose label, segment purpose, flag, kind, outcome, loop type and
       ending, and every action ``mid`` and ``phase``, is in the vocabulary."""
    errors: List[str] = []
    purposes = obj.get("purposes") or []
    expected = 1
    seg_ids = set()
    for p in purposes:
        if p.get("label") not in VOCAB["purposes"]:
            errors.append(f"purpose {p.get('id')}: label {p.get('label')!r} not in vocab")
        if p["start"] != expected:
            errors.append(f"purpose {p.get('id')} starts at {p['start']}, expected {expected}")
        if p["end"] < p["start"]:
            errors.append(f"purpose {p.get('id')} ends before it starts")
        inner = p["start"]
        if not p.get("segments"):
            errors.append(f"purpose {p.get('id')} has no segments")
        for s in p.get("segments") or []:
            seg_ids.add(s["id"])
            if s["start"] != inner:
                errors.append(f"segment {s['id']} starts at {s['start']}, expected {inner}")
            if s["steps"] != list(range(s["start"], s["end"] + 1)):
                errors.append(f"segment {s['id']}: steps != range(start, end + 1)")
            inner = s["end"] + 1
            for field, vocab in (("type", VOCAB["segment_types"]), ("purpose", VOCAB["purposes"]),
                                 ("kind", KINDS), ("outcome", OUTCOMES)):
                if s.get(field) not in vocab:
                    errors.append(f"segment {s['id']}: {field} {s.get(field)!r} not in vocab")
            for flag in s.get("flags") or []:
                if flag not in VOCAB["flags"]:
                    errors.append(f"segment {s['id']}: flag {flag!r} not in vocab")
        if inner != p["end"] + 1:
            errors.append(f"purpose {p.get('id')}: segments end at {inner - 1}, purpose at {p['end']}")
        expected = p["end"] + 1
    if expected != n_actions + 1:
        errors.append(f"purposes cover 1..{expected - 1}, trajectory has {n_actions} actions")
    for loop in obj.get("loops") or []:
        if loop.get("type") not in LOOP_TYPES or loop.get("ended") not in LOOP_ENDINGS:
            errors.append(f"loop {loop.get('type')}/{loop.get('ended')} not in vocab")
        for sid in loop.get("segment_ids") or []:
            if sid not in seg_ids:
                errors.append(f"loop {loop['type']} refers to unknown segment {sid}")
    if actions is not None:
        if len(actions) != n_actions:
            errors.append(f"{len(actions)} actions, n_actions = {n_actions}")
        for k, action in enumerate(actions):
            if action.get("i") != k + 1:
                errors.append(f"actions[{k}].i == {action.get('i')}, expected {k + 1}")
            if action.get("mid") not in VOCAB["mid"]:
                errors.append(f"action {k + 1}: mid {action.get('mid')!r} not in vocab")
            if "phase" in action and action["phase"] not in VOCAB["purposes"]:
                errors.append(f"action {k + 1}: phase {action.get('phase')!r} not in vocab")
    if errors:
        raise ValueError(f"{name or 'trajectory'}: {len(errors)} invariant violation(s): "
                         + "; ".join(errors[:20]))


# ----------------------------------------------------------------------------- entry point
def prepare(trajectory: dict, bug_id: str) -> List[dict]:
    """Annotated actions with verdicts and their lookup category (``atif.lookup``), in the
    shape the rules read."""
    rows = verdict_mod.attach(taxonomy.annotate(trajectory))
    lookup.annotate(rows)
    for row in rows:
        row["bug_id"] = str(bug_id)
        row["args"] = row.get("arguments") or {}
        row["cmd"] = taxonomy.shell_command({"function_name": row["tool"],
                                             "arguments": row["args"]})
    return rows


def segment(trajectory: dict, bug_id: str) -> Dict[str, Any]:
    """Segment one trajectory.

    Returns ``actions`` (annotated rows), ``segments``/``purposes``/``loops`` in internal
    form, ``hierarchy`` (purposes and loops in the ``trajview/1`` shape, invariant-checked)
    and ``first_source_edit`` (an action_index, or None)."""
    with project.use(trajectory):
        acts = prepare(trajectory, bug_id)
        if not acts:
            return {"actions": [], "segments": [], "purposes": [], "loops": [],
                    "hierarchy": {"purposes": [], "loops": []}, "first_source_edit": None}
        segs, purposes, loops, first_src = segment_actions(acts)
    for s in segs:
        s["type"] = segment_type(s)
    tree = hierarchy(acts, segs, purposes, loops)
    check_hierarchy(tree, len(acts), name=f"bug-{bug_id}")
    return {"actions": acts, "segments": segs, "purposes": purposes, "loops": loops,
            "hierarchy": tree,
            "first_source_edit": acts[first_src]["action_index"] if first_src < len(acts)
            else None}
