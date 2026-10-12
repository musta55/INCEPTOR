"""Locate the raw logs in Dataset/: one per (agent, prompt configuration, run, bug).

Layout of this corpus (one results folder per agent, one sub-folder per config and run):

    Dataset/a_apr_test_results/<agent>_run<k>.csv                   outcomes (atif.outcomes)
    Dataset/o_codex_results/codex_<config>_run<k>/codex/log-bug-<id>/logs/
        codex-session-rollout-*.jsonl                                the trajectory
        run-meta.json, run-<ts>.log                                  harness sidecar, console
    Dataset/p_claude_results/claude_<config>_run<k>/claude_logs/bug-<id>_output.txt
    Dataset/q_qwen_results/qwen_<config>_run<k>/qwen/bug-<id>.log    (+ bug-<id>.meta.json)

Three agents (Claude Code, Codex CLI, Qwen Code) x 17 prompt configurations x 3 runs x 50
bugs = 7,650 trajectories, all with an APR outcome.  ``file_method_screen`` is an 18th config
on disk (Claude and Codex runs 1-2, Qwen run 1; 250 logs) that the outcome CSVs do not
cover: it is converted only on request and kept out of every default and every statistic.

Run folders are named ``<agent>_<config>_run<k>``; config names are prefixes of one another
(``causing_screen_description`` / ``causing_screen_description_screenshot``), so the name is
parsed with one anchored pattern (``RUN_DIR``), never by splitting on ``_``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

AGENTS = ("claude", "codex", "qwen")
#: the outcome columns of a_apr_test_results/*.csv, in CSV order
CONFIGS = (
    "original", "perfect", "reference", "title_ob", "ob_omitted", "eb_omitted",
    "s2r_omitted", "file_method_no_screen",
    "causing_screen_description", "causing_screen_description_screenshot",
    "causing_screen_description_screenshot_xml",
    "manifesting_screen_description", "manifesting_screen_description_screenshot",
    "manifesting_screen_description_screenshot_xml",
    "caus_man_screen_description", "caus_man_screen_description_screenshot",
    "caus_man_screen_description_screenshot_xml",
)
#: on disk but without outcomes: convertible on request, never in a default selection
EXTRA_CONFIGS = ("file_method_screen",)
RUNS = (1, 2, 3)
DEFAULT_CONFIG = "original"

#: agent -> (results folder under Dataset/, agent folder inside each run folder)
AGENT_LAYOUT = {"claude": ("p_claude_results", "claude_logs"),
                "codex": ("o_codex_results", "codex"),
                "qwen": ("q_qwen_results", "qwen")}
RUN_DIR = re.compile(r"^(claude|codex|qwen)_(.+)_run(\d+)$")
#: bug id in a log's file or folder name: bug-<id>_output.txt, log-bug-<id>, bug-<id>.log
_BUG_NAME = {"claude": re.compile(r"^bug-(\d+)_output\.txt$"),
             "codex": re.compile(r"^log-bug-(\d+)$"),
             "qwen": re.compile(r"^bug-(\d+)\.log$")}


class Key(NamedTuple):
    """One trajectory of the corpus."""
    agent: str
    config: str
    run: int
    bug: str


def parse_run_dir(name: str) -> Optional[Tuple[str, str, int]]:
    """``codex_causing_screen_description_screenshot_run2`` -> (agent, config, run)."""
    match = RUN_DIR.match(name)
    if not match:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def config_order(config: str) -> Tuple[int, str]:
    """Sort key: the 17 outcome configs in CSV order, then the extra ones, then the rest."""
    known = CONFIGS + EXTRA_CONFIGS
    return (known.index(config), "") if config in known else (len(known), config)


def run_dir(dataset: Path, agent: str, config: str, run: int) -> Path:
    results, folder = AGENT_LAYOUT[agent]
    return Path(dataset) / results / f"{agent}_{config}_run{int(run)}" / folder


def log_path(dataset: Path, agent: str, config: str, run: int, bug: str) -> Optional[Path]:
    """The raw trajectory log, or None when that run has no log for the bug."""
    base = run_dir(dataset, agent, config, run)
    bug = str(bug)
    if agent == "claude":
        candidate = base / f"bug-{bug}_output.txt"
    elif agent == "qwen":
        candidate = base / f"bug-{bug}.log"
    else:
        # one rollout per session; a resumed or retried session would leave several,
        # and the largest is the one that did the work
        rollouts = list((base / f"log-bug-{bug}" / "logs").glob("*rollout-*.jsonl"))
        if not rollouts:
            return None
        candidate = max(rollouts, key=lambda p: (p.stat().st_size, p.name))
    return candidate if candidate.is_file() else None


def logs_for(dataset: Path, bug: str, config: str = DEFAULT_CONFIG,
             run: int = 1) -> Dict[str, Path]:
    """{agent: raw log path} for one bug in one (config, run), skipping agents that lack it."""
    found: Dict[str, Path] = {}
    for agent in AGENTS:
        path = log_path(dataset, agent, config, run, bug)
        if path is not None:
            found[agent] = path
    return found


def available_runs(dataset: Path) -> List[Tuple[str, str, int]]:
    """Every (agent, config, run) whose run folder exists, agents and configs in canonical
    order."""
    found = []
    for agent in AGENTS:
        results = Path(dataset) / AGENT_LAYOUT[agent][0]
        if not results.is_dir():
            continue
        for child in results.iterdir():
            parsed = parse_run_dir(child.name)
            if parsed and parsed[0] == agent and \
                    (child / AGENT_LAYOUT[agent][1]).is_dir():
                found.append(parsed)
    return sorted(found, key=lambda t: (AGENTS.index(t[0]), config_order(t[1]), t[2]))


def bugs_in(dataset: Path, agent: str, config: str, run: int) -> List[str]:
    """Bug ids present in one run folder (by name; ``log_path`` checks the file itself)."""
    base = run_dir(dataset, agent, config, run)
    if not base.is_dir():
        return []
    pattern = _BUG_NAME[agent]
    ids = (pattern.match(child.name) for child in base.iterdir())
    return sorted((m.group(1) for m in ids if m), key=int)


def all_bug_ids(dataset: Path) -> List[str]:
    """Every bug id with a log in any run folder, sorted numerically."""
    ids = set()
    for agent, config, run in available_runs(dataset):
        ids.update(bugs_in(dataset, agent, config, run))
    return sorted(ids, key=int)


def iter_logs(dataset: Path, agents: Optional[Iterable[str]] = None,
              configs: Optional[Iterable[str]] = None, runs: Optional[Iterable[int]] = None,
              bugs: Optional[Iterable[str]] = None) -> Iterator[Tuple[Key, Path]]:
    """(Key, raw log) for every trajectory on disk that matches the filters.

    ``None`` means no filter, so ``iter_logs(dataset)`` walks all 7,900 logs, the extra
    config included; pass ``configs=CONFIGS`` for the 7,650 with outcomes.  Order: agent,
    config, run, bug (numeric)."""
    agents = set(agents) if agents is not None else None
    configs = set(configs) if configs is not None else None
    runs = {int(r) for r in runs} if runs is not None else None
    bugs = sorted({str(b) for b in bugs}, key=int) if bugs is not None else None
    for agent, config, run in available_runs(dataset):
        if (agents is not None and agent not in agents) or \
                (configs is not None and config not in configs) or \
                (runs is not None and run not in runs):
            continue
        for bug in (bugs if bugs is not None else bugs_in(dataset, agent, config, run)):
            path = log_path(dataset, agent, config, run, bug)
            if path is not None:
                yield Key(agent, config, run, bug), path


def sidecar_meta(dataset: Path, key: Key) -> Optional[dict]:
    """The harness's own record of the run, when it wrote one: Qwen's ``bug-<id>.meta.json``
    (model, exit code, duration, start/finish), Codex's ``run-meta.json`` (model, reasoning
    effort, sandbox).  Claude runs have none."""
    base = run_dir(dataset, key.agent, key.config, key.run)
    if key.agent == "qwen":
        path = base / f"bug-{key.bug}.meta.json"
    elif key.agent == "codex":
        path = base / f"log-bug-{key.bug}" / "logs" / "run-meta.json"
    else:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def traj_id(key: Key) -> str:
    return f"bug-{key.bug}/{key.agent}/{key.config}/run{key.run}"


def atif_path(out: Path, key: Key) -> Path:
    return Path(out) / "atif" / key.config / f"run{key.run}" / \
        f"bug-{key.bug}_{key.agent}.atif.json"


def reading_path(out: Path, key: Key) -> Path:
    return Path(out) / "reading" / key.config / f"run{key.run}" / f"bug-{key.bug}_{key.agent}.md"


def annotation_path(out: Path, config: str, run: int, bug: str, suffix: str = "csv") -> Path:
    """The per-(bug, config, run) annotation sheet; it holds every agent's actions."""
    return Path(out) / "annotation" / config / f"run{int(run)}" / f"bug-{bug}_actions.{suffix}"
