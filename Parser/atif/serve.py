"""A local server for the viewer, so that its Analyze page can run the Python analysis on a
log the user drops in, under the rules the user sets.

    python3 -m atif.cli serve            # http://127.0.0.1:8765/  (analyze.html: one log)

The static pages still open from ``file://``.  The Analyze page uses this server when it is
opened from it, and otherwise (the hosted viewer) runs the same package in the browser
(``atif.engine``); both call ``upload.rules_info`` and ``upload.request``.
Standard library only.  It listens on the loopback interface by default and keeps nothing:
an uploaded log lives in memory (and a temporary file while it is parsed) for one request.

    GET  /api/rules      the built-in rules in plain words, the default rule set, and the
                         vocabularies a custom rule can name
    POST /api/analyze    {"name", "text", "rules", "outcome": true|false|null, "bug"}
                         -> ``atif.upload.request`` (``trajview-single/1``), or
                         {"error": message} with status 400
    POST /api/corpus     {"rules", "summary", "paths": ["data/atif/run1/bug-18.json.gz", ...]}
                         -> ``atif.upload.corpus_request`` on those packs of the viewer
                         directory (``view.write_packs``): the corpus under the user's rules
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from . import upload

#: a JSON request body may be a little larger than the log it carries
MAX_BODY = upload.MAX_BYTES + 4 * 1024 * 1024
#: the only files /api/corpus reads: corpus packs inside the viewer directory
PACK_PATH = re.compile(r"^data/atif/run\d+/bug-[A-Za-z0-9_.-]+\.json\.gz$")


class Handler(SimpleHTTPRequestHandler):
    server_version = "TrajecTiers"

    def log_message(self, fmt: str, *args: Any) -> None:            # quiet static files
        if self.path.startswith("/api/") or (args and str(args[1]).startswith(("4", "5"))):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/api/rules":
            self._json(HTTPStatus.OK, upload.rules_info())
            return
        if self.path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "no such endpoint"})
            return
        super().do_GET()

    def _packs(self, body: Any) -> Any:
        """The corpus request with its pack paths read: ``paths`` -> ``packs``."""
        if not isinstance(body, dict) or not isinstance(body.get("paths"), list):
            raise ValueError("expected {\"rules\", \"summary\", \"paths\": [...]}")
        packs = []
        for rel in body["paths"]:
            if not isinstance(rel, str) or not PACK_PATH.match(rel) or ".." in rel:
                raise ValueError(f"not a corpus pack path: {rel!r}")
            path = Path(self.directory) / rel
            if not path.is_file():
                raise ValueError(f"{rel} is missing: run python3 -m atif.cli view --all")
            packs.append(json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")))
        return {**{k: v for k, v in body.items() if k != "paths"}, "packs": packs}

    def do_POST(self) -> None:
        route = self.path.split("?")[0]
        if route not in ("/api/analyze", "/api/corpus"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "no such endpoint"})
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if size <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "the request is empty"})
            return
        if size > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                       {"error": f"the file is larger than {upload.MAX_BYTES // 2 ** 20} MB"})
            return
        try:
            body = json.loads(self.rfile.read(size).decode("utf-8", "replace"))
            result = upload.request(body) if route == "/api/analyze" \
                else upload.corpus_request(self._packs(body))
        except ValueError as exc:                     # not JSON, or not a pack path
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:                                  # report, keep serving
            self.log_error("analyze failed: %r", exc)
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                       {"error": f"the analysis failed: {type(exc).__name__}: {exc}"})
            return
        if "error" in result:
            self._json(HTTPStatus.BAD_REQUEST, result)
            return
        self._json(HTTPStatus.OK, result)


def serve(viewer_dir: Path, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = False) -> None:
    handler = partial(Handler, directory=str(viewer_dir))
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{'127.0.0.1' if host in ('', '0.0.0.0') else host}:{httpd.server_port}/"
    print(f"TrajecTiers on {url}  (analyze a log: {url}analyze.html)  Ctrl-C stops it")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  warning: listening beyond this machine; anyone who can reach it can upload logs")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url + "analyze.html",)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
