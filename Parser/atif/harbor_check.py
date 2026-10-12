"""Harbor's official ATIF validator over many trajectories, in one process.

Harbor (``harbor.utils.trajectory_validator``, the reference implementation of the ATIF
schema) needs Python >= 3.12 and pydantic, so it runs under ``uv`` rather than the system
Python.  From ``Parser/``:

    uv run --python 3.12 --no-project --with harbor python -m atif.harbor_check data/atif/original
    uv run ... python -m atif.harbor_check --files-from list.txt
    uv run ... python -m atif.harbor_check --from-raw --config all --all --jobs 8

Positional arguments are ATIF files or directories (searched for ``*.atif.json``), or, when
none of them is an existing path, bug ids of a selection (the ``trajparse`` flags:
``--all``, ``--config``, ``--runs``, ``--agent``).  A selection is validated from the
converted files under ``--out`` or, with ``--from-raw``, from the raw logs converted in
memory with this package (no ATIF file is written).  ``trajparse validate --harbor``
launches this module once for its whole selection.

Writes ``<out>/validation/<name>.json`` (summary) and ``<name>-failures.csv``, the same
report format as the dependency-free validator.  ``<name>`` is ``harbor-raw`` or
``harbor-converted`` for the whole corpus and carries the selection otherwise (see
``cli.report_name``); files given by path are named after the configs, runs, agents and
bugs they cover, or ``harbor-files`` when one lies outside the converted layout.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from . import cli, corpus
from .corpus import Key

#: the trajectory's corpus coordinates, from the converted layout
#: atif/<config>/run<k>/bug-<id>_<agent>.atif.json
_LAYOUT = (r"(?:^|/)atif/(?P<config>[^/]+)/run(?P<run>\d+)/"
           r"bug-(?P<bug>\d+)_(?P<agent>%s)\.atif\.json$" % "|".join(corpus.AGENTS))


def harbor_errors(trajectory: Any) -> List[str]:
    """Harbor's error list for a trajectory dict or an ATIF file path (empty = valid)."""
    from harbor.utils.trajectory_validator import TrajectoryValidator
    validator = TrajectoryValidator()
    validator.validate(trajectory)
    return list(validator.errors)


def harbor_version() -> str:
    try:
        from importlib.metadata import version
        return f"harbor {version('harbor')}"
    except Exception:                                   # not installed: reported by main()
        return "harbor (unknown version)"


def key_of(path: Path) -> Optional[Key]:
    match = re.search(_LAYOUT, Path(path).as_posix())
    if not match:
        return None
    return Key(match["agent"], match["config"], int(match["run"]), match["bug"])


def _files(targets: List[str]) -> List[Path]:
    """Files as given; directories searched for ``*.atif.json``.  Inside a directory that
    holds the converted layout only that layout is taken, so ``data/atif`` skips the flat
    files left there by the earlier corpus."""
    found: List[Path] = []
    for target in targets:
        path = Path(target)
        if not path.is_dir():
            found.append(path)
            continue
        candidates = sorted(path.rglob("*.atif.json"))
        in_layout = [p for p in candidates if key_of(p.resolve())]
        found.extend(in_layout or candidates)
    return found


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="atif.harbor_check", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(cli.DEFAULT_DATASET))
    parser.add_argument("--out", default=str(cli.DEFAULT_OUT),
                        help="converted files and validation/ reports (default data/)")
    cli.add_selection(parser)
    cli.add_conversion(parser)
    parser.add_argument("--from-raw", action="store_true",
                        help="convert the selection's raw logs in memory and validate those")
    parser.add_argument("--files-from", metavar="LIST",
                        help="a text file naming one ATIF file per line")
    parser.add_argument("--report", help="report name (default: from the source and the "
                                          "selection)")
    parser.add_argument("--quiet", action="store_true", help="no progress line")
    args = parser.parse_intermixed_args(argv)
    args.command = "harbor_check"

    try:
        import harbor.utils.trajectory_validator  # noqa: F401
    except ImportError:
        print("harbor is not importable here; run this module through\n  "
              + " ".join(cli.HARBOR_CMD[:-3]) + " python -m atif.harbor_check ...",
              file=sys.stderr)
        return 2

    dataset, out = cli._paths(args)
    targets = list(args.bug_id or [])
    if args.files_from:
        targets += [line.strip() for line in Path(args.files_from).read_text().splitlines()
                    if line.strip()]
    sel = None
    if targets and any(Path(t).exists() for t in targets):
        missing = [t for t in targets if not Path(t).exists()]
        if missing:
            print(f"not found: {', '.join(missing[:5])}", file=sys.stderr)
            return 2
        source = "file"
        items: List[Tuple[Optional[Key], Path]] = [(key_of(p.resolve()), p)
                                                    for p in _files(targets)]
        if items and all(key for key, _ in items):
            sel = cli.covered(key for key, _ in items)
    else:
        sel = cli.selection(args, default_all_bugs=True)
        found = cli.keys(dataset, sel)
        source = "raw" if args.from_raw else "converted"
        items = found if args.from_raw else \
            [(key, corpus.atif_path(out, key)) for key, _ in found
             if corpus.atif_path(out, key).is_file()]
    if not items:
        print("nothing to validate (no ATIF files, or none converted for the selection)",
              file=sys.stderr)
        return 2
    limit = 10 ** 12 if args.full else args.max_output
    results, elapsed = cli.run_validation("harbor", source, items, dataset=dataset, out=out,
                                          jobs=args.jobs, limit=limit, quiet=args.quiet)
    source = "raw" if source == "raw" else "converted"
    return cli.report_validation(
        results, validator="harbor", version=harbor_version(), source=source, out=out,
        name=args.report or cli.report_name("harbor", source, sel, dataset),
        elapsed=elapsed, jobs=min(args.jobs, len(items)), sel=sel, dataset=dataset)


if __name__ == "__main__":
    raise SystemExit(main())
