"""Unified parsing of coding-agent trajectories into ATIF v1.7.

    from atif import detect, schema, taxonomy, tar
    trajectory = detect.parse(path)          # any supported agent log
    errors = schema.validate(trajectory)
    rows = tar.iterations(trajectory, bug_id="18", agent="codex")
"""
from __future__ import annotations

from . import (claude, codex, corpus, detect, outcomes, qwen, schema, segment,  # noqa: F401
               tar, taxonomy, verdict, view)

__version__ = schema.PARSER_VERSION
__all__ = ["claude", "codex", "corpus", "detect", "outcomes", "qwen", "schema", "segment",
           "tar", "taxonomy", "verdict", "view"]
