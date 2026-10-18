"""Which kind of project a trajectory works on: the corpus's Android apps, or a SWE-bench
style Python repository.

The rules were built for the Android corpus: the project is the ``bug-<id>`` checkout, tests
live under ``test/`` or ``androidTest/``, a shell write edits the project when it writes code,
resources or build scripts, and test runs are Gradle's.  A SWE-bench trajectory (SWE-agent,
OpenHands, mini-swe-agent) works elsewhere: the repository sits at ``/testbed``,
``/workspace/<repo>`` or ``/<repo>``, its tests are ``tests/`` and ``test_*.py``, and the agent
reproduces the issue with a script it writes at the repository root (``reproduce_issue.py``)
and runs with ``python``.

A ``Project`` holds that difference.  The adapters (``atif.swebench``) record it in the ATIF
file, ``extra.project = {"kind": "swebench", "roots": [...], "instance_id": ...}``; a file
without it is an Android one, so the corpus is never read any other way.  While a trajectory
is analysed, ``use`` makes its project the current one, and the few rules that depend on it
(``taxonomy``: what is inside the checkout, a project file, a test file, a test run;
``segment.repo_rel``; ``verdict``: pytest and unittest results, Python tracebacks) ask
``current()``.  Under the Android project they run exactly as before.

    with project.use(trajectory):
        result = rules.phases(trajectory, bug, ruleset)
"""
from __future__ import annotations

import contextlib
import contextvars
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple, Union

ANDROID = "android"
SWEBENCH = "swebench"
KINDS = (ANDROID, SWEBENCH)


@dataclass(frozen=True)
class Project:
    """``kind`` (ANDROID or SWEBENCH); ``roots``: absolute repository locations of a SWE-bench
    run, longest first (empty when none was found: absolute paths are then outside); the
    task's ``instance_id`` (``astropy__astropy-12907``) when the log names it; ``checkout``:
    the folder an Android run was started in (the log's ``extra.cwd``, the bug checkout), which
    the lookup tables (``atif.lookup``) take as the repository, or "" when the log names none."""
    kind: str = ANDROID
    roots: Tuple[str, ...] = ()
    instance_id: str = ""
    checkout: str = ""

    @property
    def swebench(self) -> bool:
        return self.kind == SWEBENCH

    def below_root(self, path: str) -> Optional[str]:
        """The part of ``path`` below a repository root ("" for the root itself), or None
        when the path is not under one."""
        for root in self.roots:
            if path == root or path == root + "/":
                return ""
            if path.startswith(root + "/"):
                return path[len(root) + 1:]
        return None

    def as_extra(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind}
        if self.roots:
            out["roots"] = list(self.roots)
        if self.instance_id:
            out["instance_id"] = self.instance_id
        return out


DEFAULT = Project()
_CURRENT: contextvars.ContextVar = contextvars.ContextVar("atif_project", default=DEFAULT)


def make(kind: str = SWEBENCH, roots: Any = (), instance_id: str = "") -> Project:
    """A project with its roots normalised: absolute, no trailing slash, longest first."""
    if kind not in KINDS:
        raise ValueError(f"unknown project kind {kind!r}")
    clean = {str(r).rstrip("/") for r in roots or () if str(r).startswith("/")} - {""}
    return Project(kind, tuple(sorted(clean, key=lambda r: (-len(r), r))), str(instance_id or ""))


def of(trajectory: Optional[dict]) -> Project:
    """The project an ATIF trajectory records in ``extra.project``; Android without one, with
    the folder the run was started in (``extra.cwd``) as its checkout."""
    extra = (trajectory or {}).get("extra") or {}
    spec = extra.get("project")
    if not isinstance(spec, dict) or spec.get("kind") not in KINDS:
        cwd = extra.get("cwd")
        if isinstance(cwd, str) and cwd.startswith("/") and cwd.rstrip("/").count("/") >= 2:
            return Project(checkout=cwd.rstrip("/"))
        return DEFAULT
    return make(spec["kind"], spec.get("roots") or (), spec.get("instance_id") or "")


def stamp(trajectory: dict, proj: Project) -> dict:
    """Record ``proj`` in the trajectory's ``extra.project``; returns the trajectory."""
    trajectory.setdefault("extra", {})["project"] = proj.as_extra()
    return trajectory


def current() -> Project:
    return _CURRENT.get()


@contextlib.contextmanager
def use(what: Union[Project, dict, None]) -> Iterator[Project]:
    """Make a project (or the one a trajectory records) the current one for the block."""
    proj = what if isinstance(what, Project) else of(what)
    token = _CURRENT.set(proj)
    try:
        yield proj
    finally:
        _CURRENT.reset(token)


# --------------------------------------------------------------------------- #
# SWE-bench conventions (Python repositories)

#: files whose change from the shell edits the project: code and its configuration.  Logs,
#: notes, patches and scratch output (``> out.txt``) are not
PROJECT_FILE = re.compile(r"\.(?:py|pyx|pxd|pyi|c|h|cc|cpp|hpp|js|ts|go|rs|rb|java"
                          r"|cfg|toml|ini|json|ya?ml)$")
#: build and packaging configuration: editing it gets the project to install or the tests to
#: run, it does not repair the code
TOOLCHAIN_FILES = {"setup.py", "setup.cfg", "pyproject.toml", "tox.ini", "pytest.ini",
                   "MANIFEST.in", "Makefile", "Pipfile", "environment.yml", ".coveragerc",
                   "noxfile.py"}
TOOLCHAIN_NAME = re.compile(r"^requirements[\w.\-]*\.txt$")
#: test code: a tests folder, pytest's and unittest's file names, pytest's conftest
TEST_PATH = re.compile(r"(?:^|/)(?:tests?|testing)/|(?:^|/)(?:test_[^/]*|[^/]*_tests?)\.py$"
                       r"|(?:^|/)conftest\.py$")
#: a script the agent wrote to edit files (live-SWE-agent writes its own tools:
#: ``python /testbed/edit_file.py <file> 245 245 <<EOF``): running it edits the files it names
EDIT_TOOL = re.compile(r"edit|replace|patch|modify|insert|rewrite|write", re.IGNORECASE)
#: a script at the repository root is the agent's own (``reproduce_issue.py``,
#: ``debug_separable.py``), not the repository's: SWE-bench packages live in folders
SCRIPT = re.compile(r"\.(?:py|sh)$")


def scratch(rel: str, proj: Project) -> bool:
    """Whether a path is one of the agent's own scripts rather than the repository's: a script
    at the repository root (pytest's ``conftest.py`` and ``setup.py`` aside) or outside every
    root.  It counts as test code, but changing it is not changing the repository's tests."""
    base = rel.rsplit("/", 1)[-1]
    if not SCRIPT.search(base) or base in ("conftest.py",) or base in TOOLCHAIN_FILES:
        return False
    return (rel.startswith("/") and bool(proj.roots)) or "/" not in rel


def swebench_role(rel: str, proj: Project) -> str:
    """toolchain, test or source of a path under the SWE-bench conventions.  ``rel`` is
    repository-relative, or absolute when it lies outside every root: an edit there is
    a scratch file (``/tmp/repro.py``), which counts as test code like a root script."""
    base = rel.rsplit("/", 1)[-1]
    if base in TOOLCHAIN_FILES or TOOLCHAIN_NAME.match(base):
        return "toolchain"
    if TEST_PATH.search(rel):
        return "test"
    if rel.startswith("/") and proj.roots:
        return "test" if SCRIPT.search(base) else "toolchain"
    if "/" not in rel and SCRIPT.search(base):
        return "test"
    return "source"
