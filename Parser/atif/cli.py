"""Command line entry point: trajparse.

Every command works on a selection of agents x configs x runs x bugs:

    bug ids (8 18) or --all      the bugs (list and validate default to every bug); ids may
                                 come anywhere, except straight after --config or --runs
    --config NAME... | all       prompt configurations (default original, for list every
                                 config; all = the 17 with outcomes, without
                                 file_method_screen)
    --runs K... | all            runs (default 1 2 3)
    --agent claude|codex|qwen    repeatable (default all three)

    python3 -m atif.cli list                      # agent x config x run matrix, outcome counts
    python3 -m atif.cli convert --all             # original, runs 1-3, 3 agents -> data/
    python3 -m atif.cli convert 18 --config all --runs 1
    python3 -m atif.cli validate                  # re-validate the converted files of the selection
    python3 -m atif.cli validate --from-raw --config all   # all 7,650 converted in memory;
                                                           # writes only the report
    python3 -m atif.cli validate --harbor         # plus Harbor's official validator (uv)
    python3 -m atif.cli phases 18 --runs 1        # phases -> subphases outline
    python3 -m atif.cli segment 18 --runs 1       # purposes -> segments outline (baseline B3)
    python3 -m atif.cli actions 18                # categories, phases and the phase sequence
    python3 -m atif.cli audit 18 --agent qwen     # what fraction of each raw log survives
    python3 -m atif.cli output 18 codex <call_id> --run 2
    python3 -m atif.cli serve                     # viewer + Analyze page on http://127.0.0.1:8765/
    python3 -m atif.cli engine                    # the Analyze page's in-browser engine (Pyodide)
    python3 -m atif.cli analyze LOG [--rules rules.json] [--json out.json]
                                                  # one log of any agent, outside the corpus
    python3 -m atif.cli view --all --rules rules.json      # the corpus under your own rules
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence,
                    Tuple)

if __package__ in (None, ""):                      # allow running the file directly
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atif import audit as audit_mod
from atif import (corpus, detect, engine, outcomes, phase, rules, schema, segment, tar, taxonomy,
                  view)
from atif.corpus import Key

HERE = Path(__file__).resolve().parent.parent          # Parser/
DEFAULT_DATASET = HERE.parent / "Dataset"
DEFAULT_OUT = HERE / "data"
DEFAULT_VIEW = HERE / "viewer"
DEFAULT_JOBS = min(8, os.cpu_count() or 1)
HARBOR_CMD = ["uv", "run", "--python", "3.12", "--no-project", "--with", "harbor",
              "python", "-m", "atif.harbor_check"]


# --------------------------------------------------------------------------- #
# selection


class Selection(NamedTuple):
    agents: Tuple[str, ...]
    configs: Tuple[str, ...]
    runs: Tuple[int, ...]
    bugs: Optional[Tuple[str, ...]]          # None = every bug


def add_selection(parser: argparse.ArgumentParser, *, bugs: bool = True,
                  every_config: bool = False) -> None:
    """The selection flags every command shares; ``every_config`` makes the default every
    config on disk instead of ``original`` (for ``list``)."""
    if bugs:
        parser.add_argument("bug_id", nargs="*", help="bug ids, e.g. 8 18 (or bug-8)")
        parser.add_argument("--all", action="store_true", help="every bug")
    extra = ", ".join(corpus.EXTRA_CONFIGS)
    parser.add_argument("--config", nargs="+", metavar="NAME",
                        default=["all", *corpus.EXTRA_CONFIGS] if every_config
                        else [corpus.DEFAULT_CONFIG],
                        help=f"prompt configurations (default "
                             f"{'all and ' + extra if every_config else corpus.DEFAULT_CONFIG}; "
                             f"'all' = the {len(corpus.CONFIGS)} with outcomes, not {extra})")
    parser.add_argument("--runs", nargs="+", default=[str(r) for r in corpus.RUNS], metavar="K",
                        help="runs (default 1 2 3; 'all')")
    parser.add_argument("--agent", action="append", choices=corpus.AGENTS,
                        help="repeatable (default: all three)")


def add_conversion(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-output", type=int, default=schema.OUTPUT_LIMIT,
                        help=f"truncate tool output above N chars (default "
                             f"{schema.OUTPUT_LIMIT:,}; the full text stays recoverable from "
                             f"the raw log)")
    parser.add_argument("--full", action="store_true", help="never truncate tool output")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"worker processes (default {DEFAULT_JOBS})")


def _split(values: Iterable[str]) -> List[str]:
    return [v.strip() for value in values for v in str(value).split(",") if v.strip()]


def selection(args: argparse.Namespace, *, default_all_bugs: bool = False) -> Selection:
    """Resolve the selection flags; exits with a message on an unknown name."""
    configs: List[str] = []
    for name in _split(args.config):
        names = corpus.CONFIGS if name == "all" else (name,)
        for config in names:
            if config not in corpus.CONFIGS + corpus.EXTRA_CONFIGS:
                hint = " (bug ids cannot directly follow --config)" if config.isdigit() else ""
                raise SystemExit(f"unknown config {config!r}{hint}; known: "
                                 + ", ".join(corpus.CONFIGS + corpus.EXTRA_CONFIGS))
            if config not in configs:
                configs.append(config)
    runs: List[int] = []
    for value in _split(args.runs):
        if value == "all":
            runs.extend(r for r in corpus.RUNS if r not in runs)
        elif value.isdigit() and int(value) in corpus.RUNS:
            if int(value) not in runs:
                runs.append(int(value))
        else:
            raise SystemExit(f"--runs takes {', '.join(map(str, corpus.RUNS))} or 'all', not "
                             f"{value!r} (bug ids cannot directly follow --runs)")
    agents = tuple(a for a in corpus.AGENTS if a in (args.agent or corpus.AGENTS))
    bugs: Optional[Tuple[str, ...]] = None
    ids = [b[4:] if b.startswith("bug-") else b for b in _split(getattr(args, "bug_id", []) or [])]
    for bug in ids:
        if not bug.isdigit():
            raise SystemExit(f"not a bug id: {bug!r}")
    every = getattr(args, "all", False)
    if ids and every:
        raise SystemExit(f"{args.command}: pass bug ids or --all, not both")
    if ids:
        bugs = tuple(sorted(set(ids), key=int))
    elif not every and not default_all_bugs:
        raise SystemExit(f"{args.command}: pass bug ids or --all")
    return Selection(agents, tuple(configs), tuple(sorted(runs)), bugs)


def selection_flags(sel: Selection) -> List[str]:
    """The command-line flags that reproduce a selection (for the Harbor subprocess)."""
    flags = list(sel.bugs) if sel.bugs is not None else ["--all"]
    for agent in sel.agents:
        flags += ["--agent", agent]
    return flags + ["--config", *sel.configs, "--runs", *map(str, sel.runs)]


def keys(dataset: Path, sel: Selection) -> List[Tuple[Key, Path]]:
    return list(corpus.iter_logs(dataset, sel.agents, sel.configs, sel.runs, sel.bugs))


def _runs_label(runs: Iterable[int]) -> str:
    runs = sorted(set(runs))
    if len(runs) > 2 and runs == list(range(runs[0], runs[-1] + 1)):
        return f"{runs[0]}-{runs[-1]}"
    return ",".join(map(str, runs)) or "-"


def _paths(args: argparse.Namespace) -> Tuple[Path, Path]:
    return Path(args.dataset).resolve(), Path(args.out).resolve()


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(HERE))
    except ValueError:
        return str(path)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]], left: int = 1,
           indent: str = "  ") -> None:
    """A plain text table: the first ``left`` columns left-aligned, the rest right-aligned."""
    cells = [[f"{c:,}" if isinstance(c, int) and not isinstance(c, bool) else str(c) for c in row]
             for row in rows]
    widths = [max([len(h)] + [len(r[k]) for r in cells]) for k, h in enumerate(headers)]

    def line(values: Sequence[str]) -> str:
        return indent + "  ".join(v.ljust(w) if k < left else v.rjust(w)
                                  for k, (v, w) in enumerate(zip(values, widths))).rstrip()
    print(line(headers))
    for row in cells:
        print(line(row))


class Progress:
    """Progress on stderr: one overwriting line on a terminal; in a log file, a line every
    ``every`` seconds (so a fast run prints none)."""

    def __init__(self, total: int, label: str, quiet: bool = False, every: float = 10.0):
        self.total, self.label, self.quiet, self.every = total, label, quiet, every
        self.done = self.failed = 0
        self.tty = sys.stderr.isatty()
        self.started = self.printed = time.time()

    def step(self, n: int = 1, failed: int = 0) -> None:
        self.done += n
        self.failed += failed
        if self.quiet:
            return
        text = (f"  {self.label} {self.done:,}/{self.total:,}"
                + (f" ({self.failed} failed)" if self.failed else ""))
        if self.tty:
            print("\r" + text, end="", file=sys.stderr, flush=True)
        elif time.time() - self.printed >= self.every and self.done < self.total:
            print(text, file=sys.stderr, flush=True)
            self.printed = time.time()

    def close(self) -> float:
        if self.tty and not self.quiet and self.done:
            print(file=sys.stderr)
        return time.time() - self.started


def _pool_map(func, tasks: List[Any], jobs: int):
    """Yield func(task) for every task, in completion order; in-process when jobs <= 1."""
    if jobs <= 1 or len(tasks) <= 1:
        for task in tasks:
            yield func(task)
        return
    import multiprocessing
    with multiprocessing.Pool(min(jobs, len(tasks))) as pool:
        chunk = max(1, len(tasks) // (jobs * 16))
        for result in pool.imap_unordered(func, tasks, chunksize=chunk):
            yield result


# --------------------------------------------------------------------------- #
# conversion


def set_output_limit(limit: int) -> None:
    """The truncation cap of tool output; ``schema.truncate`` reads it at call time.  Set in
    every worker, since a spawned process starts from the module's default."""
    schema.OUTPUT_LIMIT = limit


def parse(dataset: Path, key: Key, path: Path) -> dict:
    """Raw log -> ATIF, with the corpus coordinates in the root ``extra``."""
    extra: Dict[str, Any] = {
        "bug_id": key.bug, "agent": key.agent, "config": key.config, "run": key.run,
        "raw_log": str(Path(path).relative_to(dataset)), "dataset": dataset.name,
    }
    if key.agent == "codex":
        # the harness's run-meta.json (model, reasoning effort, sandbox); the Qwen parser
        # attaches its own bug-<id>.meta.json, and Claude runs have no sidecar
        meta = corpus.sidecar_meta(dataset, key)
        if meta:
            extra["harness_meta"] = meta
    return detect.parse(path, extra=extra)


def load_or_parse(dataset: Path, out: Path, key: Key, path: Path) -> dict:
    """The converted ATIF file when present, else the raw log parsed in memory."""
    converted = corpus.atif_path(out, key)
    if converted.is_file():
        return json.loads(converted.read_text(encoding="utf-8"))
    return parse(dataset, key, path)


def _merge_rows(existing: Path, rows: List[dict], agents: Iterable[str]) -> List[dict]:
    """Rows of the agents not converted this time are kept from the sheet already on disk,
    so converting one agent never drops the others from a bug's sheet."""
    agents = set(agents)
    kept: List[dict] = []
    if existing.is_file():
        with existing.open(encoding="utf-8") as handle:
            kept = [row for row in (json.loads(line) for line in handle if line.strip())
                    if row.get("agent") not in agents]
    order = {agent: k for k, agent in enumerate(corpus.AGENTS)}
    return sorted(kept + rows, key=lambda r: order.get(r.get("agent"), len(order)))


def _describe(exc: Exception, dataset: Path) -> str:
    """An exception as one line, with paths shown relative to the dataset."""
    return f"{type(exc).__name__}: {exc}".replace(f"{dataset}{os.sep}", "")


def _convert_group(task: tuple) -> List[dict]:
    """Convert one (config, run, bug) for the selected agents; write ATIF, reading views
    and the bug's annotation sheet.  Returns one result per trajectory."""
    dataset, out, config, run, bug, logs, limit = task
    set_output_limit(limit)
    results, rows = [], []
    for agent, path in logs:
        key = Key(agent, config, run, bug)
        result: Dict[str, Any] = {"key": key, "status": "ok", "errors": []}
        results.append(result)
        try:
            trajectory = parse(dataset, key, Path(path))
            errors = schema.validate(trajectory, corpus.traj_id(key))
            if errors:
                result.update(status="invalid", errors=errors[:20], n_errors=len(errors))
            else:
                schema.write(trajectory, corpus.atif_path(out, key))
                phased = phase.phases(trajectory, bug)       # once, for both outputs
                agent_rows = tar.iterations(trajectory, bug_id=bug, agent=agent,
                                            config=config, run=run, result=phased)
                tar.write_reading_view(trajectory, corpus.reading_path(out, key),
                                       bug_id=f"bug-{bug}", result=phased)
        except Exception as exc:                       # reported, never fatal for the batch
            result.update(status="error", errors=[_describe(exc, dataset)])
        if result["status"] != "ok":
            # no output from an earlier conversion may outlive a failed one
            for stale in (corpus.atif_path(out, key), corpus.reading_path(out, key)):
                if stale.is_file():
                    stale.unlink()
            continue
        rows.extend(agent_rows)
        extra = trajectory.get("extra") or {}
        result.update(
            steps=len(trajectory["steps"]), actions=len(agent_rows),
            failed=sum(1 for r in agent_rows if r["failed"] == "true"),
            reasoning=sum(1 for r in agent_rows if r["thought_source"] == "reasoning"),
            gaps=list(extra.get("known_gaps") or []),
            phases=taxonomy.segments([r["phase"] for r in agent_rows]))
    sheet = corpus.annotation_path(out, config, run, bug, "jsonl")
    if rows or sheet.is_file():
        merged = _merge_rows(sheet, rows, [agent for agent, _ in logs])
        tar.write_jsonl(merged, sheet)
        tar.write_csv(merged, corpus.annotation_path(out, config, run, bug, "csv"))
    return results


def _print_failures(results: List[dict], limit: int = 20) -> None:
    failures = [r for r in results if r["status"] not in ("ok", "missing")]
    for r in failures[:limit]:
        first = r["errors"][0] if r["errors"] else ""
        name = corpus.traj_id(r["key"]) if r["key"] else r.get("path", "?")
        print(f"  {r['status'].upper():7} {name}: {first[:200]}")
    if len(failures) > limit:
        print(f"  ... and {len(failures) - limit} more")


def cmd_convert(args: argparse.Namespace) -> int:
    dataset, out = _paths(args)
    sel = selection(args)
    found = keys(dataset, sel)
    if not found:
        print(f"no logs match the selection under {dataset}", file=sys.stderr)
        return 2
    groups: Dict[Tuple[str, int, str], List[Tuple[str, str]]] = defaultdict(list)
    for key, path in found:
        groups[(key.config, key.run, key.bug)].append((key.agent, str(path)))
    limit = 10 ** 12 if args.full else args.max_output
    tasks = [(dataset, out, config, run, bug, logs, limit)
             for (config, run, bug), logs in groups.items()]
    print(f"converting {len(found):,} trajectories ({len(tasks):,} annotation sheets), "
          f"{min(args.jobs, len(tasks))} job(s)")
    progress = Progress(len(found), "converted", args.quiet)
    results: List[dict] = []
    for group in _pool_map(_convert_group, tasks, args.jobs):
        results.extend(group)
        progress.step(len(group), sum(1 for r in group if r["status"] != "ok"))
    elapsed = progress.close()
    results.sort(key=lambda r: (corpus.AGENTS.index(r["key"].agent),
                                corpus.config_order(r["key"].config), r["key"].run,
                                int(r["key"].bug)))
    if args.verbose:
        for r in results:
            if r["status"] != "ok":
                continue
            print(f"  {corpus.traj_id(r['key']):48} steps={r['steps']:3} actions={r['actions']:3}"
                  f" failed={r['failed']:2} thought={r['reasoning']:3}/{r['actions']:<3}"
                  f" gaps={','.join(r['gaps']) or '-'}")
            print("      " + " -> ".join(f"{p}({n})" for p, n in r["phases"]))

    status = Counter(r["status"] for r in results)
    print(f"converted {status['ok']:,}/{len(results):,} in {elapsed:.1f}s"
          f" ({status['invalid']} invalid, {status['error']} errors)")
    configs = sorted({r["key"].config for r in results}, key=corpus.config_order)
    by_cell: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in results:          # one row per agent and config, or per agent for many configs
        config = r["key"].config if len(configs) <= 3 else f"{len(configs)} configs"
        by_cell[(r["key"].agent, config)].append(r)
    rows = []
    for (agent, config), cell in by_cell.items():
        ok = [r for r in cell if r["status"] == "ok"]
        rows.append((agent, config, _runs_label(r["key"].run for r in cell), len(ok),
                     len(cell) - len(ok), sum(r["steps"] for r in ok),
                     sum(r["actions"] for r in ok), sum(r["failed"] for r in ok)))
    _table(("agent", "config", "runs", "converted", "errors", "steps", "actions",
            "failed actions"), rows, left=3)
    _print_failures(results)
    empty = [r for r in results if r["status"] == "ok" and not r["steps"]]
    if empty:
        print(f"  warning: {len(empty)} trajectories have no steps: "
              + ", ".join(corpus.traj_id(r["key"]) for r in empty[:5])
              + (" ..." if len(empty) > 5 else ""))
    print(f"wrote {_rel(out)}/{{atif,annotation,reading}}/"
          + (_brace(configs) if len(configs) <= 3 else "<config>") + "/"
          + _brace([f"run{k}" for k in sorted({r["key"].run for r in results})]))
    return 1 if status["invalid"] or status["error"] else 0


def _brace(names: List[str]) -> str:
    return names[0] if len(names) == 1 else "{" + ",".join(names) + "}"


# --------------------------------------------------------------------------- #
# validation (atif.schema here; Harbor's validator through atif.harbor_check)


def validate_one(task: tuple) -> dict:
    """Validate one trajectory.  ``task`` = (validator, source, dataset, out, key, path, limit)
    with validator ``atif`` or ``harbor`` and source ``converted`` (the file under ``out``),
    ``raw`` (parse the raw log in memory) or ``file`` (``path`` is an ATIF file)."""
    validator, source, dataset, out, key, path, limit = task
    result: Dict[str, Any] = {"key": key, "status": "ok", "errors": [], "n_errors": 0,
                              "path": str(path)}
    if source == "converted":
        path = corpus.atif_path(out, key)
        result["path"] = str(path)
        if not path.is_file():
            result["status"] = "missing"
            return result
    try:
        if source == "raw":
            set_output_limit(limit)
            trajectory: Any = parse(dataset, key, Path(path))
            if validator == "harbor":           # what would be written: JSON round trip
                trajectory = json.loads(json.dumps(trajectory, default=str))
        elif validator == "harbor":
            trajectory = Path(path)             # Harbor loads files itself
        else:
            trajectory = json.loads(Path(path).read_text(encoding="utf-8"))
        if validator == "harbor":
            from atif import harbor_check
            errors = harbor_check.harbor_errors(trajectory)
        else:
            errors = schema.validate(trajectory, corpus.traj_id(key) if key else str(path))
    except Exception as exc:
        result.update(status="error", errors=[_describe(exc, dataset)], n_errors=1)
        return result
    if errors:
        result.update(status="invalid", errors=errors[:20], n_errors=len(errors))
    return result


def run_validation(validator: str, source: str, items: List[Tuple[Optional[Key], Path]], *,
                   dataset: Path, out: Path, jobs: int, limit: int = schema.OUTPUT_LIMIT,
                   quiet: bool = False) -> Tuple[List[dict], float]:
    tasks = [(validator, source, dataset, out, key, path, limit) for key, path in items]
    progress = Progress(len(tasks), "validated", quiet)
    results = []
    for result in _pool_map(validate_one, tasks, jobs):
        results.append(result)
        progress.step(1, result["status"] in ("invalid", "error"))
    return results, progress.close()


def covered(keys: Iterable[Key]) -> Selection:
    """The smallest selection holding every key: the agents, configs, runs and bugs seen
    (for ATIF files given to a validator by path)."""
    keys = list(keys)
    return Selection(tuple(a for a in corpus.AGENTS if any(k.agent == a for k in keys)),
                     tuple(sorted({k.config for k in keys}, key=corpus.config_order)),
                     tuple(sorted({k.run for k in keys})),
                     tuple(sorted({k.bug for k in keys}, key=int)))


def report_name(validator: str, source: str, sel: Optional[Selection],
                dataset: Optional[Path] = None) -> str:
    """The report's file name, without suffix: ``<validator>-<source>`` for the whole corpus
    (the 17 outcome configs x every run, agent and bug), else that name plus the selection,
    so a narrower run never overwrites the report of a wider or different one:
    ``atif-converted-original-r123``, ``harbor-raw-all-r2-qwen-bug8+18``.  Lists longer than
    a file name should carry become a count and a digest (``12bugs-3fa9c1``).  ``sel`` None
    (files outside the converted layout) gives ``<validator>-files``."""
    if sel is None:
        return f"{validator}-files"
    bugs = sel.bugs
    if bugs is not None and dataset is not None and \
            set(bugs) == set(corpus.all_bug_ids(dataset)):
        bugs = None
    if (set(sel.configs) == set(corpus.CONFIGS) and set(sel.runs) == set(corpus.RUNS)
            and set(sel.agents) == set(corpus.AGENTS) and bugs is None):
        return f"{validator}-{source}"

    def listed(values: Sequence[Any], keep: int, noun: str) -> str:
        values = [str(v) for v in values]
        if len(values) <= keep:
            return "+".join(values)
        digest = hashlib.sha1(",".join(values).encode("utf-8")).hexdigest()[:6]
        return f"{len(values)}{noun}-{digest}"
    configs = sorted(sel.configs, key=corpus.config_order)
    if set(corpus.CONFIGS) <= set(configs):
        parts = ["+".join(["all"] + [c for c in configs if c not in corpus.CONFIGS])]
    else:
        parts = [listed(configs, 2, "configs")]
    parts.append("r" + "".join(map(str, sorted(sel.runs))))
    if set(sel.agents) != set(corpus.AGENTS):
        parts.append("+".join(a for a in corpus.AGENTS if a in sel.agents))
    if bugs is not None:
        parts.append(("bug" if len(bugs) <= 3 else "") + listed(bugs, 3, "bugs"))
    return f"{validator}-{source}-" + "-".join(parts)


def report_validation(results: List[dict], *, validator: str, version: str, source: str,
                      out: Path, name: str, elapsed: float, jobs: int,
                      sel: Optional[Selection] = None, dataset: Optional[Path] = None) -> int:
    """Write ``<out>/validation/<name>.json`` (summary; ``name`` from ``report_name``) and
    ``<name>-failures.csv``, print a summary per agent and config, return the exit code (1 if
    anything failed)."""
    def blank() -> Dict[str, int]:
        return {"total": 0, "valid": 0, "invalid": 0, "error": 0, "missing": 0}

    by_cell: Dict[str, Dict[str, int]] = defaultdict(blank)
    by_agent: Dict[str, Dict[str, int]] = defaultdict(blank)
    runs: Dict[str, set] = defaultdict(set)
    totals = blank()
    names = {"ok": "valid", "invalid": "invalid", "error": "error", "missing": "missing"}
    for r in results:
        key = r["key"]
        agent, config = (key.agent, key.config) if key else ("?", "?")
        for bucket in (by_cell[f"{agent}/{config}"], by_agent[agent], totals):
            bucket["total"] += 1
            bucket[names[r["status"]]] += 1
        if key:
            runs[f"{agent}/{config}"].add(key.run)
    failures = [r for r in results if r["status"] in ("invalid", "error")]
    summary = {
        "validator": validator, "validator_version": version, "source": source,
        "created": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(dataset) if dataset else None,
        "selection": None if sel is None else {
            "agents": list(sel.agents), "configs": list(sel.configs), "runs": list(sel.runs),
            "bugs": "all" if sel.bugs is None else list(sel.bugs)},
        "seconds": round(elapsed, 1), "jobs": jobs, "totals": totals,
        "by_agent": dict(by_agent), "by_agent_config": dict(by_cell),
        "failures": len(failures),
    }
    folder = Path(out) / "validation"
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / f"{name}.json"
    report.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    failures_csv = folder / f"{name}-failures.csv"
    with failures_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("traj_id", "agent", "config", "run", "bug", "status", "n_errors",
                         "errors", "path"))
        for r in failures:
            key = r["key"]
            writer.writerow((corpus.traj_id(key) if key else "", *(key or ("", "", "", "")),
                             r["status"], r["n_errors"], " | ".join(r["errors"][:5]), r["path"]))

    label = {"converted": "converted ATIF files", "raw": "raw logs converted in memory"}[source]
    checked = totals["total"] - totals["missing"]
    all_runs = sorted(set().union(*runs.values())) if runs else []
    print(f"{validator} validator ({version}) on {label}: {checked:,} trajectories, "
          f"runs {_runs_label(all_runs)}, {elapsed:.1f}s, {jobs} job(s)")
    # one row per config, one column per agent: valid/total, '!' where something failed
    agents = sorted(by_agent, key=lambda a: corpus.AGENTS.index(a) if a in corpus.AGENTS else 9)
    configs = sorted({cell.split("/", 1)[1] for cell in by_cell}, key=corpus.config_order)

    def cell(c: Optional[Dict[str, int]]) -> str:
        if not c:
            return "-"
        return f"{c['valid']:,}/{c['total'] - c['missing']:,}" + \
            (" !" if c["invalid"] or c["error"] else "")
    rows = [[config] + [cell(by_cell.get(f"{a}/{config}")) for a in agents] for config in configs]
    if len(configs) > 1:
        rows.append(["all"] + [cell(by_agent[a]) for a in agents])
    rows.append(["invalid / error"] + [f"{by_agent[a]['invalid']} / {by_agent[a]['error']}"
                                       for a in agents])
    _table(["config"] + agents, rows)
    _print_failures(failures)
    print(f"{totals['valid']:,}/{checked:,} valid"
          + (f", {len(failures):,} FAILED" if failures else "")
          + f"   report: {_rel(report)} (+ {failures_csv.name})")
    return 1 if failures else 0


def cmd_validate(args: argparse.Namespace) -> int:
    dataset, out = _paths(args)
    sel = selection(args, default_all_bugs=True)
    found = keys(dataset, sel)
    if not found:
        print(f"no logs match the selection under {dataset}", file=sys.stderr)
        return 2
    limit = 10 ** 12 if args.full else args.max_output
    source = "raw" if args.from_raw else "converted"
    items = found if args.from_raw else \
        [(key, corpus.atif_path(out, key)) for key, _ in found
         if corpus.atif_path(out, key).is_file()]
    if not items:
        print("no converted trajectories in the selection; run convert first "
              "(or validate --from-raw)", file=sys.stderr)
        return 2
    if not args.from_raw and len(items) < len(found):
        print(f"{len(found) - len(items):,} of the {len(found):,} selected trajectories are not "
              f"converted; validating the {len(items):,} that are")
    results, elapsed = run_validation("atif", source, items, dataset=dataset, out=out,
                                      jobs=args.jobs, limit=limit, quiet=args.quiet)
    code = report_validation(results, validator="atif",
                             version=f"atif.schema {schema.SCHEMA_VERSION}", source=source,
                             out=out, name=report_name("atif", source, sel, dataset),
                             elapsed=elapsed,
                             jobs=min(args.jobs, len(items)), sel=sel, dataset=dataset)
    if args.harbor:
        print()
        code = max(code, run_harbor(args, sel, dataset, out, None if args.from_raw else
                                    [path for _, path in items]))
    return code


def run_harbor(args: argparse.Namespace, sel: Selection, dataset: Path, out: Path,
               files: Optional[List[Path]]) -> int:
    """Harbor's official validator, in one ``uv`` process for the whole selection."""
    cmd = HARBOR_CMD + ["--dataset", str(dataset), "--out", str(out), "--jobs", str(args.jobs)]
    listing = None
    if files is None:
        cmd += ["--from-raw", "--max-output", str(10 ** 12 if args.full else args.max_output)]
        cmd += selection_flags(sel)
    else:
        listing = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        listing.write("\n".join(map(str, files)) + "\n")
        listing.close()
        # named after the selection asked for, like the atif report, not after the files
        cmd += ["--files-from", listing.name,
                "--report", report_name("harbor", "converted", sel, dataset)]
    if args.quiet:
        cmd.append("--quiet")
    sys.stdout.flush()                                  # keep our report above Harbor's
    try:
        return subprocess.run(cmd, cwd=str(HERE)).returncode
    except FileNotFoundError:
        print("Harbor's validator runs through uv, which is not on PATH "
              "(https://docs.astral.sh/uv/)", file=sys.stderr)
        return 2
    finally:
        if listing is not None:
            os.unlink(listing.name)


# --------------------------------------------------------------------------- #
# reading commands


def _by_sheet(found: List[Tuple[Key, Path]]) -> Dict[Tuple[str, str, int], List[Tuple[Key, Path]]]:
    """Group a selection by (bug, config, run), bugs numerically."""
    groups: Dict[Tuple[str, str, int], List[Tuple[Key, Path]]] = defaultdict(list)
    for key, path in found:
        groups[(key.bug, key.config, key.run)].append((key, path))
    return dict(sorted(groups.items(), key=lambda kv: (int(kv[0][0]),
                                                       corpus.config_order(kv[0][1]), kv[0][2])))


def cmd_actions(args: argparse.Namespace) -> int:
    dataset, out = _paths(args)
    found = keys(dataset, selection(args))
    if not found:
        print("no logs match the selection", file=sys.stderr)
        return 2
    for key, path in found:
        trajectory = load_or_parse(dataset, out, key, path)
        result = phase.phases(trajectory, key.bug)
        rows = result["actions"]
        cats = Counter(r["category"] for r in rows)
        phs = Counter(result["phase"])
        print(f"\n=== {corpus.traj_id(key)} "
              f"({len(rows)} actions, {sum(1 for r in rows if r['failed'])} failed)")
        print("  category:", ", ".join(f"{k}={v}" for k, v in cats.most_common()))
        print("  phase   :", ", ".join(f"{k}={v}" for k, v in phs.most_common()))
        print("  sequence:", " -> ".join(
            f"{p}({n})" for p, n in taxonomy.segments(result["phase"])))
    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    """Print each trajectory's purposes -> segments outline, with outcome and loops."""
    dataset, out = _paths(args)
    found = keys(dataset, selection(args))
    if not found:
        print("no logs match the selection", file=sys.stderr)
        return 2
    table = outcomes.load(dataset)
    totals: Counter = Counter()
    for (bug, config, run), group in _by_sheet(found).items():
        print(f"bug-{bug}  {config}/run{run}")
        for key, path in group:
            result = segment.segment(load_or_parse(dataset, out, key, path), bug)
            passed = outcomes.outcome_for(table, key.agent, bug, config, run)["pass"]
            tree = result["hierarchy"]
            totals["trajectories"] += 1
            totals["segments"] += len(result["segments"])
            totals["purposes"] += len(tree["purposes"])
            totals["loops"] += len(tree["loops"])
            print(f"  {key.agent}: {len(result['actions'])} actions, first source edit "
                  f"{result['first_source_edit']}, outcome "
                  f"{'pass' if passed else 'fail' if passed is False else 'n/a'}")
            for p in tree["purposes"]:
                print(f"    {p['label']} [{p['start']}-{p['end']}]")
                for s in p["segments"]:
                    nested = f" (in {p['label']}, own {s['purpose']})" if s["nested"] else ""
                    flags = f"  {{{', '.join(s['flags'])}}}" if s["flags"] else ""
                    print(f"      {s['id']:>4} [{s['start']}-{s['end']}] {s['type']} / "
                          f"{s['outcome']}{nested}: {s['label']}{flags}")
            for loop in tree["loops"]:
                print(f"    loop {loop['type']} [{loop['start']}-{loop['end']}] "
                      f"x{loop['iterations']} ({loop['failed_iterations']} failed), "
                      f"{loop['ended']}: {' '.join(loop['segment_ids'])}")
    print(f"\n{totals['trajectories']} trajectories, {totals['purposes']} purposes, "
          f"{totals['segments']} segments, {totals['loops']} loops")
    return 0


def cmd_phases(args: argparse.Namespace) -> int:
    """Print each trajectory's phases -> subphases outline (``atif.phase``), with outcomes,
    flags and the share of actions the tool registry left as ``other``."""
    dataset, out = _paths(args)
    found = keys(dataset, selection(args))
    if not found:
        print("no logs match the selection", file=sys.stderr)
        return 2
    table = outcomes.load(dataset)
    totals: Counter = Counter()
    categories: Dict[str, Counter] = defaultdict(Counter)
    for (bug, config, run), group in _by_sheet(found).items():
        print(f"bug-{bug}  {config}/run{run}")
        for key, path in group:
            result = phase.phases(load_or_parse(dataset, out, key, path), bug)
            passed = outcomes.outcome_for(table, key.agent, bug, config, run)["pass"]
            categories[key.agent].update(a["category"] for a in result["actions"])
            totals["trajectories"] += 1
            totals["phases"] += len(result["phases"])
            totals["subphases"] += sum(len(s["subphases"]) for s in result["phases"])
            m = result["metrics"]
            print(f"  {key.agent}: {len(result['actions'])} actions, anchor "
                  f"{result['anchor']}, {m['n_attempts']} attempts, harness "
                  f"{'pass' if passed else 'fail' if passed is False else 'n/a'}")
            for s in result["phases"]:
                print(f"    {s['phase']} [{s['start']}-{s['end']}]")
                for sp in s["subphases"]:
                    count = f" x{sp['n_events']}" if sp["n_events"] > 1 else ""
                    tries = f", {sp['n_attempts']} attempts" if sp["n_attempts"] > 1 else ""
                    flags = f"  {{{', '.join(sp['flags'])}}}" if sp["flags"] else ""
                    evidence = f" ({sp['evidence']})" if sp["evidence"] != "none" else ""
                    print(f"      {sp['id']:>6} [{sp['start']}-{sp['end']}] "
                          f"{sp['outcome']}{evidence}{count}{tries}{flags}")
    print(f"\n{totals['trajectories']} trajectories, {totals['phases']} phase spans, "
          f"{totals['subphases']} subphases")
    for agent, counts in sorted(categories.items()):
        n = sum(counts.values())
        print(f"  {agent}: {n} actions, other {counts['other'] / n:.1%} "
              f"(registry coverage gate: <= 1%)")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    """Write the viewer data: ``data/overview.js`` (one run, every bug) and one
    ``data/bugs/bug-<id>.js`` per selected bug (every selected run). Reads converted files."""
    dataset, out = _paths(args)
    sel = selection(args, default_all_bugs=True)
    if len(sel.configs) != 1:
        raise SystemExit("view: pass exactly one --config (the viewer shows one configuration)")
    if args.overview_run not in sel.runs:
        raise SystemExit(f"view: --overview-run {args.overview_run} is not among --runs")
    ruleset = load_rules(args.rules) if args.rules else None
    try:
        summary = view.export(out, dataset, Path(args.path), config=sel.configs[0],
                              runs=sel.runs, overview_run=args.overview_run,
                              bug_ids=sel.bugs, agents=sel.agents, ruleset=ruleset)
    except ValueError as exc:
        raise SystemExit(f"view: {exc}")
    if ruleset:
        added = ", ".join(o["id"] + (f"={o['value']}" if "value" in o else "")
                          for o in ruleset["optional"]) or "none"
        print(f"rules: {args.rules} (mandatory G1-G6; optional {added}; "
              f"{len(ruleset['custom'])} custom rule(s))")
    print(f"wrote {_rel(Path(summary['overview']))} ({summary['overview_bytes']:,} bytes, "
          f"{summary['bugs']} bugs, {summary['overview_trajectories']} trajectories of run "
          f"{summary['overview_run']})")
    print(f"wrote {summary['bug_files']} bug page file(s), {summary['bug_bytes']:,} bytes, "
          f"{summary['trajectories']} trajectories; largest "
          f"{_rel(Path(summary['largest_bug_file'])) if summary['largest_bug_file'] else '-'} "
          f"({summary['largest_bug_bytes']:,} bytes)")
    packs = view.write_packs(out, Path(args.path), config=sel.configs[0], runs=sel.runs,
                             bug_ids=sel.bugs or corpus.all_bug_ids(dataset), agents=sel.agents)
    print(f"wrote {packs['files']} corpus pack(s), {packs['bytes']:,} bytes "
          f"(data/atif/: the ATIF the viewer re-runs under a user's rules)")
    _write_engine(Path(args.path))
    if summary["missing"]:
        print(f"  {len(summary['missing'])} trajectories not converted yet (run convert first): "
              + ", ".join(summary["missing"][:8]) + (" ..." if len(summary["missing"]) > 8 else ""))
    return 0


def _write_engine(viewer_dir: Path) -> None:
    out = engine.write(viewer_dir)
    print(f"wrote {_rel(out)} ({out.stat().st_size:,} bytes, {len(engine.sources())} modules: "
          f"the Analyze page's engine)")


def cmd_engine(args: argparse.Namespace) -> int:
    """Write ``viewer/engine/atif.zip``, this package for the Analyze page to run in the
    browser (``atif.engine``)."""
    _write_engine(Path(args.path))
    return 0


def load_rules(path: str) -> Dict[str, Any]:
    """A rule set file (``atif.rules``, e.g. exported from the Analyze page), checked."""
    try:
        return rules.normalize(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, rules.RuleError) as exc:
        raise SystemExit(f"rules: {path}: {exc}")


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyse one log of any of the three agents, a SWE-bench run of SWE-agent, OpenHands or
    mini-swe-agent, or an ATIF file, that need not be in the corpus, under the default rules or
    ``--rules``, and print its phases outline."""
    from atif import upload
    ruleset = load_rules(args.rules) if args.rules else None
    outcome = {"pass": True, "fail": False}.get(args.outcome)
    try:
        res = upload.analyze_path(Path(args.log), ruleset=ruleset, outcome=outcome, bug=args.bug)
    except (OSError, upload.UploadError, rules.RuleError) as exc:
        print(f"analyze: {exc}", file=sys.stderr)
        return 2
    t, src = res["trajectory"], res["source"]
    print(f"{args.log}: {src['agent']} ({src['format']}), bug {src['bug'] or '?'}"
          f"{' (inferred)' if src['bug_inferred'] else ''}, {t['n_actions']} actions, "
          f"first fix {t['anchor'] or '-'}, {t['stats']['n_attempts']} attempts")
    for w in res["warnings"]:
        print(f"  note: {w}")
    for s in t["phases"]:
        print(f"  {s['phase']} [{s['start']}-{s['end']}]")
        for sp in s["subphases"]:
            flags = f"  {{{', '.join(sp['flags'])}}}" if sp["flags"] else ""
            evidence = f" ({sp['evidence']})" if sp["evidence"] != "none" else ""
            print(f"    {sp['id']:>6} [{sp['start']}-{sp['end']}] {sp['outcome']}{evidence}{flags}")
    report = res["rules"]
    print(f"  mandatory: {', '.join(r['id'] for r in report['mandatory'])}; optional: "
          f"{', '.join(r['id'] for r in report['optional'] if r['on']) or 'none'}")
    for r in [o for o in report["optional"] if o["on"] and "matched" in o] + report["custom"]:
        skipped = f", {len(r['skipped'])} skipped" if r.get("skipped") else ""
        state = "" if r.get("enabled", True) else " (off)"
        print(f"  rule {r['id']}{state}: {r['sentence']}  -> {len(r['matched'])} action(s){skipped}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                   encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the viewer and its Analyze page (one uploaded log, your own rules)."""
    from atif import serve
    try:
        serve.serve(Path(args.path), host=args.host, port=args.port, open_browser=args.open)
    except OSError as exc:
        raise SystemExit(f"serve: {exc} (is port {args.port} in use? try --port)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Measure what fraction of each raw log survives into its ATIF conversion."""
    dataset, _ = _paths(args)
    found = keys(dataset, selection(args))
    if not found:
        print("no logs match the selection", file=sys.stderr)
        return 2
    worst, failed = 1.0, 0
    for key, path in found:
        try:
            report = audit_mod.audit(path, parse(dataset, key, path))
        except Exception as exc:
            failed += 1
            print(f"=== {corpus.traj_id(key)}  FAILED: {_describe(exc, dataset)}")
            continue
        print(audit_mod.render(report, corpus.traj_id(key)))
        totals = report["totals"]
        if totals["blocks"]:
            worst = min(worst, totals["found"] / totals["blocks"])
    print(f"\nlowest block-preservation rate seen: {100 * worst:.1f}% "
          f"over {len(found) - failed} trajectories"
          + (f"; {failed} could not be audited" if failed else ""))
    return 1 if failed else 0


def cmd_output(args: argparse.Namespace) -> int:
    """Print one tool result in full, straight from the raw log."""
    dataset, _ = _paths(args)
    bug = args.bug_id[4:] if args.bug_id.startswith("bug-") else args.bug_id
    path = corpus.log_path(dataset, args.agent, args.config, args.run, bug)
    if path is None:
        print(f"no {args.agent} log for bug-{bug} in {args.config}/run{args.run}", file=sys.stderr)
        return 2
    for block in audit_mod.INVENTORIES[detect.detect(path)](path):
        if block["call_id"] == args.call_id and block["field"] in ("output", "content"):
            print(block["text"])
            return 0
    print(f"call_id {args.call_id} not found in {path.name}", file=sys.stderr)
    return 1


def _grid(agents: Sequence[str], configs: Sequence[str], runs: Sequence[int],
          value: Callable[[str, str, int], str]) -> None:
    """One row per config, one column group per agent, one column per run; configs outside
    the outcome CSVs are starred."""
    names = {c: c + ("" if c in corpus.CONFIGS else " *") for c in configs}
    cells = {(a, c, r): value(a, c, r) for a in agents for c in configs for r in runs}
    width = max(len(n) for n in names.values()) + 2
    cell = max([2] + [len(v) for v in cells.values()])
    group = len(runs) * (cell + 1) + 2

    def line(name: str, column: Callable[[str, int], str]) -> None:
        print("  " + name.ljust(width) + "".join(
            "".join(column(a, r).rjust(cell + 1) for r in runs)[1:].ljust(group)
            for a in agents).rstrip())
    print("  " + " " * width + "".join(a.ljust(group) for a in agents).rstrip())
    line("", lambda a, r: f"r{r}")
    for config in configs:
        line(names[config], lambda a, r: cells[(a, config, r)])


def cmd_list(args: argparse.Namespace) -> int:
    """Logs per agent x config x run, and their APR outcomes, for the selection (by default
    every config on disk, every run, agent and bug)."""
    dataset, _ = _paths(args)
    sel = selection(args, default_all_bugs=True)
    ids = corpus.all_bug_ids(dataset)
    bugs = list(sel.bugs) if sel.bugs is not None else ids
    configs = sorted(sel.configs, key=corpus.config_order)
    print(f"{dataset}: {len(ids)} bug ids")
    counts: Counter = Counter()
    present: Dict[Tuple[str, str, int], set] = defaultdict(set)
    for key, _ in corpus.iter_logs(dataset, sel.agents, configs, sel.runs, sel.bugs):
        counts[(key.agent, key.config, key.run)] += 1
        present[(key.agent, key.config, key.run)].add(key.bug)
    print(f"\nlogs per agent x config x run ({len(bugs)} = complete, - = none)")
    _grid(sel.agents, configs, sel.runs, lambda a, c, r: str(counts.get((a, c, r)) or "-"))
    if any(c not in corpus.CONFIGS for c in configs):
        print(f"  * not in the outcome CSVs ({', '.join(corpus.EXTRA_CONFIGS)}): "
              "convertible on request, outside every statistic")
    per_agent = Counter()
    for (agent, config, _), n in counts.items():
        per_agent[agent] += n
    in_outcome = sum(n for (_, config, _), n in counts.items() if config in corpus.CONFIGS)
    print(f"  total {sum(counts.values()):,} logs ({in_outcome:,} in the {len(corpus.CONFIGS)} "
          f"outcome configs): " + ", ".join(f"{a} {per_agent[a]:,}" for a in sel.agents))
    if args.verbose:
        for (agent, config, run), found in sorted(present.items()):
            missing = sorted(set(bugs) - found, key=int)
            if missing:
                print(f"  {agent}_{config}_run{run}: missing bug-" + ", bug-".join(missing))

    scored = [c for c in configs if c in corpus.CONFIGS]
    if not scored:
        return 0
    table = outcomes.load(dataset)

    def passes(agent: str, config: str, run: int) -> str:
        known = [v for v in (table.get((agent, config, run, b)) for b in bugs) if v is not None]
        if not known:
            return "n/a"
        return str(sum(known)) if len(known) == len(bugs) else f"{sum(known)}/{len(known)}"
    print(f"\nAPR outcomes ({outcomes.OUTCOME_SOURCE}): passes of the {len(bugs)} bugs "
          f"(p/k where only k have an outcome)")
    _grid(sel.agents, scored, sel.runs, passes)
    return 0


# --------------------------------------------------------------------------- #


class IntermixedParser(argparse.ArgumentParser):
    """A sub-command parser that takes positionals among the flags (``segment --agent qwen
    18``), via ``parse_known_intermixed_args``; argparse cannot intermix at the top level,
    which holds the sub-commands, so each sub-command parser does it for its own part."""

    def parse_known_args(self, args=None, namespace=None):
        if getattr(self, "_intermixing", False):     # the intermixed parse calls back here
            return super().parse_known_args(args, namespace)
        self._intermixing = True
        try:
            return self.parse_known_intermixed_args(args, namespace)
        finally:
            self._intermixing = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trajparse", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET),
                        help="the corpus (default ../Dataset)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output root (default data/)")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=IntermixedParser)

    convert = sub.add_parser("convert", help="raw logs -> ATIF + annotation sheets + reading views")
    add_selection(convert)
    add_conversion(convert)
    convert.add_argument("--quiet", action="store_true", help="no progress line")
    convert.add_argument("--verbose", action="store_true",
                         help="one line per trajectory (steps, actions, phases)")
    convert.set_defaults(func=cmd_convert)

    validate = sub.add_parser("validate", help="validate converted (or raw) trajectories")
    add_selection(validate)
    add_conversion(validate)
    validate.add_argument("--from-raw", action="store_true",
                          help="convert the raw logs in memory and validate those (writes "
                               "only the report)")
    validate.add_argument("--harbor", action="store_true",
                          help="also run Harbor's official validator (one uv process)")
    validate.add_argument("--quiet", action="store_true", help="no progress line")
    validate.set_defaults(func=cmd_validate)

    actions = sub.add_parser("actions", help="categories, phases and the phase sequence per trajectory")
    add_selection(actions)
    actions.set_defaults(func=cmd_actions)

    auditor = sub.add_parser("audit", help="what fraction of each raw log survives")
    add_selection(auditor)
    auditor.set_defaults(func=cmd_audit)

    output = sub.add_parser("output", help="print one tool result in full from the raw log")
    output.add_argument("bug_id")
    output.add_argument("agent", choices=corpus.AGENTS)
    output.add_argument("call_id")
    output.add_argument("--config", default=corpus.DEFAULT_CONFIG,
                        choices=corpus.CONFIGS + corpus.EXTRA_CONFIGS, metavar="NAME")
    output.add_argument("--run", type=int, default=1)
    output.set_defaults(func=cmd_output)

    segmenter = sub.add_parser("segment", help="purposes -> segments outline per trajectory")
    add_selection(segmenter)
    segmenter.set_defaults(func=cmd_segment)

    phaser = sub.add_parser("phases", help="phases -> subphases outline per trajectory")
    add_selection(phaser)
    phaser.set_defaults(func=cmd_phases)

    viewer = sub.add_parser("view", help="write the viewer data (overview + one file per bug)")
    add_selection(viewer)
    viewer.add_argument("--overview-run", type=int, default=1, metavar="K",
                        help="the run the overview page shows (default 1)")
    viewer.add_argument("--path", default=str(DEFAULT_VIEW),
                        help="viewer directory (default Parser/viewer; writes data/ inside it)")
    viewer.add_argument("--rules", metavar="FILE",
                        help="a rule set (JSON, e.g. exported from the Analyze page) instead "
                             "of the default rules")
    viewer.set_defaults(func=cmd_view)

    analyzer = sub.add_parser("analyze", help="phases of one log of any agent (or an ATIF "
                                              "file), outside the corpus")
    analyzer.add_argument("log", help="a Claude Code, Codex CLI or Qwen Code log, a SWE-agent, OpenHands or "
                                               "mini-swe-agent run, or an ATIF file")
    analyzer.add_argument("--rules", metavar="FILE", help="a rule set (JSON)")
    analyzer.add_argument("--bug", help="the bug id, when the log does not name its bug-<id> checkout")
    analyzer.add_argument("--outcome", choices=("pass", "fail"), help="the harness outcome, if known")
    analyzer.add_argument("--json", metavar="FILE", help="also write the full result")
    analyzer.set_defaults(func=cmd_analyze)

    server = sub.add_parser("serve", help="serve the viewer with its Analyze page "
                                          "(upload one log, set your own rules)")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--host", default="127.0.0.1",
                        help="interface to listen on (default: this machine only)")
    server.add_argument("--open", action="store_true", help="open the Analyze page in a browser")
    server.add_argument("--path", default=str(DEFAULT_VIEW), help="viewer directory")
    server.set_defaults(func=cmd_serve)

    packer = sub.add_parser("engine", help="pack this package for the Analyze page to run "
                                           "in the browser (viewer/engine/atif.zip)")
    packer.add_argument("--path", default=str(DEFAULT_VIEW), help="viewer directory")
    packer.set_defaults(func=cmd_engine)

    listing = sub.add_parser("list", help="what the dataset contains, and outcome counts")
    add_selection(listing, every_config=True)
    listing.add_argument("--verbose", action="store_true", help="name missing bugs")
    listing.set_defaults(func=cmd_list)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
