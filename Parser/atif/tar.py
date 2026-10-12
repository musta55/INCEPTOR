"""Thought-Action-Result views and the annotation sheets manual analysis runs on.

An ATIF step is one LLM inference and may issue several tool calls, so it is the
storage unit. A TAR iteration is one *action* with its thought and result, so it is
the analysis unit. This module derives the latter from the former without losing the
inference boundary (``step_id`` and ``parallel_calls_in_step`` are carried through).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import phase as phase_mod

#: Written empty by the exporter; filled in by a human. Kept at the end of the row.  The
#: annotation of the phase taxonomy runs on the Ground Truth workbooks
#: (``make_ground_truth.py``); these columns mirror theirs.
MANUAL_COLUMNS = ("manual_phase", "manual_category", "manual_notes")

#: ``category`` .. ``attempt`` are the phase taxonomy (``atif.phase.action_labels``).
#: ``mid_level`` and ``edit_role`` are not exported: category and file_role replace them
#: (codebook v3, appendix); only the rules and baseline B3 still read them
AUTO_COLUMNS = ("bug_id", "agent", "config", "run", "action_index", "scope", "step_id",
                "call_index_in_step", "parallel_calls_in_step", "timestamp", "tool",
                "category", "file_role", "fix_stage", "phase", "own_phase", "subphase",
                "subphase_outcome", "subphase_evidence", "attempt",
                "target", "failed", "verdict", "fail_kind", "thought_source",
                "thought_preview", "result_preview", "call_id")


def iterations(trajectory: dict, *, bug_id: str, agent: str, config: Optional[str] = None,
               run: Optional[int] = None,
               result: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One row per action. ``config`` and ``run`` default to the ones the convert step
    recorded in the trajectory's root ``extra``; ``result`` is the trajectory's
    ``phase.phases``, when the caller has it already."""
    extra = trajectory.get("extra") or {}
    config = extra.get("config", "") if config is None else config
    run = extra.get("run", "") if run is None else run
    result = result or phase_mod.phases(trajectory, str(bug_id))
    rows = result["actions"]                 # annotated, with verdicts (segment.prepare)
    labels = phase_mod.action_labels(result)
    out: List[Dict[str, Any]] = []
    for row, label in zip(rows, labels):
        out.append({
            "bug_id": bug_id,
            "agent": agent,
            "config": config,
            "run": run,
            "action_index": row["action_index"],
            "scope": row["scope"],
            "step_id": row["step_id"],
            "call_index_in_step": row["call_index_in_step"],
            "parallel_calls_in_step": row["parallel_calls_in_step"],
            "timestamp": row["timestamp"],
            "tool": row["tool"],
            **label,                                   # phase taxonomy v3 (atif.phase)
            "target": row["target"],
            "failed": "" if row["failed"] is None else str(bool(row["failed"])).lower(),
            "verdict": row["verdict"],                 # read from the result text
            "fail_kind": row["fail_kind"] or "",
            "thought_source": row["thought_source"],
            "thought_preview": " ".join(row["thought"].split())[:300],
            "result_preview": " ".join((row["result_preview"] or "").split())[:300],
            "call_id": row["call_id"],
            **{column: "" for column in MANUAL_COLUMNS},
        })
    return out


def write_csv(rows: Iterable[Dict[str, Any]], path: Path) -> Path:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AUTO_COLUMNS) + list(MANUAL_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_jsonl(rows: Iterable[Dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str) + "\n")
    return path


def _fence(text: str, limit: int = 1500) -> str:
    text = (text or "").strip()
    if not text:
        return "_(none)_"
    if len(text) > limit:
        text = text[:limit] + f"\n... [{len(text) - limit} more chars]"
    return "```\n" + text + "\n```"


def write_reading_view(trajectory: dict, path: Path, *, bug_id: str,
                       result: Optional[Dict[str, Any]] = None) -> Path:
    """A human-readable TAR transcript: one section per iteration, for manual reading;
    ``result`` as in ``iterations``."""
    agent = trajectory["agent"]["name"]
    result = result or phase_mod.phases(trajectory, str(bug_id).replace("bug-", ""))
    rows = result["actions"]
    labels = phase_mod.action_labels(result)
    extra = trajectory.get("extra") or {}
    lines: List[str] = [
        f"# {bug_id} - {agent} - TAR reading view", "",
        f"- configuration: `{extra.get('config') or 'unknown'}` | run: {extra.get('run') or '?'}"
        f" | raw log: `{extra.get('raw_log') or extra.get('source_file') or 'unknown'}`",
        f"- model: `{trajectory['agent'].get('model_name') or 'unknown'}`"
        f" | agent version: `{trajectory['agent'].get('version')}`",
        f"- session: `{trajectory.get('session_id')}`",
        f"- session end: `{extra.get('outcome')}` | source: `{extra.get('source_format')}`",
        f"- steps (LLM inferences): {len(trajectory.get('steps', []))}"
        f" | actions: {len(rows)}"
        f" | failed actions: {sum(1 for r in rows if r['failed'])}",
        f"- known gaps: {', '.join(extra.get('known_gaps') or []) or 'none recorded'}",
        "",
        "Phases: "
        + " -> ".join(f"{s['phase']}({s['n_actions']}: "
                      + ", ".join(sp["outcome"] for sp in s["subphases"]) + ")"
                      for s in result["phases"]),
        "",
    ]
    last_step = None
    for row, label in zip(rows, labels):
        header = (f"## {row['action_index']}. {label['category']} / {label['phase']}"
                  + (f" (own phase {label['own_phase']})" if label["own_phase"] != label["phase"] else "")
                  + f"  ({row['tool']})")
        if row["scope"] != "main":
            header += f"  [subagent {row['scope']}]"
        lines.append(header)
        meta = [f"step {row['step_id']}"]
        if row["parallel_calls_in_step"] > 1:
            meta.append(f"call {row['call_index_in_step'] + 1}"
                        f"/{row['parallel_calls_in_step']} of this inference")
        if row["timestamp"]:
            meta.append(row["timestamp"])
        if row["failed"]:
            meta.append("**FAILED**")
        lines.append("_" + " | ".join(meta) + "_")
        lines.append("")
        show_thought = row["step_id"] != last_step or row["scope"] != "main"
        lines.append(f"**Thought** ({row['thought_source']}):")
        lines.append(_fence(row["thought"]) if show_thought
                     else "_(same inference as the previous action)_")
        lines.append("")
        lines.append("**Action**:")
        lines.append(_fence(row["command"] or row["target"], 800))
        lines.append("")
        lines.append("**Result**:")
        if row.get("delegates_to"):
            delegated = sum(1 for other in rows if other["scope"] == row["delegates_to"])
            lines.append(f"_delegated to subagent `{row['delegates_to']}`"
                         f" -- its {delegated} actions follow below_")
        else:
            lines.append(_fence(row["result_preview"], 800))
        lines.append("")
        last_step = row["step_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
