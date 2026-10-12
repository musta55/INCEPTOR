"""Baselines for the phase taxonomy (``Parser/Phase taxonomy.md`` §9).

B1  the V2 analysis plan's phase assignment ("APR Trajectory Analysis V2", Action
    Classification and Phase Assignment): one split at the first edit of any file.
B2  per-action tags only: ``phase.assign(..., keep_rules=False, smoothing=False)``.
B3  the old purpose layer (``atif.segment``), its labels mapped to the five phases.

Each returns one label per action, or None where the method gives the action no phase.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import phase

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
    "orientation": phase.UNDERSTANDING, "localization": phase.LOCALIZATION,
    "reproduction": phase.REPRODUCTION, "repair": phase.REPAIR,
    "validation": phase.VALIDATION, "review": phase.VALIDATION, "environment": None,
}


def first_edit_split(acts: List[dict]) -> List[Optional[str]]:
    """B1.  Before the first edit (``edit`` or ``shell_edit``, any file): setup, build and
    test understand; a read understands when no file it reads is code, else it locates;
    search and diff locate.  Edits repair wherever they are.  After the first edit: build,
    test, search, read and diff validate, and setup is cleanup, which we fold into
    validation.  Plan, sub-agent and other actions get no phase, and polls are dropped."""
    cats = [V2_CATEGORY.get(a["category"], "other") for a in acts]
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
            out.append(phase.UNDERSTANDING)
        elif c == "read":
            files = a.get("files") or []
            code = not files or any(f.endswith(V2_CODE) for f in files)
            out.append(phase.LOCALIZATION if code else phase.UNDERSTANDING)
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
