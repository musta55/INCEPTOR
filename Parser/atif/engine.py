"""The analysis engine of the hosted viewer: this package, zipped for Pyodide.

The Analyze page needs ``atif.upload`` and the parsers and phases behind it, several thousand
lines of Python.  Hosted as static files (Vercel), it has no server to send a log to, so it
runs this same Python in the browser: ``viewer/engine/worker.js`` loads Pyodide (CPython compiled to WebAssembly) from a CDN,
unpacks ``viewer/engine/atif.zip`` and calls ``upload.rules_info()`` and ``upload.request()``.
One engine, so the hosted page, the local server and the CLI give identical results; the log
never leaves the browser.

    python3 -m atif.cli engine          # rewrite viewer/engine/atif.zip (``view`` does it too)

The zip is deterministic (sorted names, fixed timestamps), so an unchanged package rewrites it
byte for byte; ``tests/test_view.py`` fails when it is older than the package.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Dict

PACKAGE = Path(__file__).resolve().parent
#: modules the browser cannot or need not run: the CLI, the HTTP server, the harbor check
LEFT_OUT = {"cli.py", "serve.py", "harbor_check.py"}
_STAMP = (2026, 1, 1, 0, 0, 0)


def sources() -> Dict[str, bytes]:
    """{"atif/<module>.py": source} of every module the engine ships."""
    return {f"atif/{p.name}": p.read_bytes()
            for p in sorted(PACKAGE.glob("*.py")) if p.name not in LEFT_OUT}


def build() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in sources().items():
            info = zipfile.ZipInfo(name, _STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return buf.getvalue()


def path(viewer_dir: Path) -> Path:
    return Path(viewer_dir) / "engine" / "atif.zip"


def write(viewer_dir: Path) -> Path:
    """Write the engine zip into the viewer; returns its path."""
    out = path(viewer_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build())
    return out


def current(viewer_dir: Path) -> bool:
    """Whether the viewer's engine zip holds exactly this package's sources."""
    try:
        with zipfile.ZipFile(path(viewer_dir)) as zf:
            shipped = {n: zf.read(n) for n in zf.namelist()}
    except (OSError, zipfile.BadZipFile):
        return False
    return shipped == sources()
