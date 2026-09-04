"""The probe's HTTP surface.

Serves three things:

* ``/metrics``      -- Prometheus scrape endpoint
* ``/export/*``     -- lets the report container pull the raw data over HTTP,
                       so probes on isolated VLANs need no SSH and no shared
                       storage
* ``/info``, ``/health`` -- what this probe is and whether it is alive

Export endpoints can be protected with a shared token. The data is measurement
telemetry rather than secrets, but an open endpoint that hands out a database
is still a bad habit.
"""

from __future__ import annotations

import errno
import hmac
import json
import logging
import shutil
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .storage import Store

LOG = logging.getLogger("ispbust.server")

DATE_FMT = "%Y-%m-%d"


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, DATE_FMT)
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ispbust/" + __version__
    protocol_version = "HTTP/1.1"

    # injected by make_server
    store: Store
    wan_id: str
    wan_label: str
    wan_kind: str
    token: str | None

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        LOG.debug("%s %s", self.address_string(), fmt % args)

    # -- helpers ------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, indent=2).encode(), "application/json")

    def _text(self, code: int, text: str) -> None:
        self._send(code, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _authorised(self, query: dict) -> bool:
        if not self.token:
            return True
        supplied = ""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            supplied = auth[7:]
        elif query.get("token"):
            supplied = query["token"][0]
        return hmac.compare_digest(supplied, self.token)

    def _stream_file(self, path: Path, filename: str, content_type: str) -> None:
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as fh:
            shutil.copyfileobj(fh, self.wfile, length=1 << 20)

    # -- routing ------------------------------------------------------

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if route == "/health":
            return self._text(200, "ok\n")

        if route == "/metrics":
            return self._send(200, generate_latest(), CONTENT_TYPE_LATEST)

        if route == "/info":
            return self._json(200, {
                "version": __version__,
                "wan": {"id": self.wan_id, "label": self.wan_label, "kind": self.wan_kind},
                "store": self.store.summary(),
            })

        if route == "/":
            return self._text(200, (
                "ispbust probe %s\n"
                "wan: %s (%s, %s)\n\n"
                "  /health            liveness\n"
                "  /metrics           Prometheus metrics\n"
                "  /info              probe identity and row counts\n"
                "  /export/sqlite     database snapshot (?from=&to= to filter by date)\n"
                "  /export/ndjson     raw archive for one day (?date=YYYY-MM-DD)\n"
                "  /export/list       days available in the raw archive\n"
            ) % (__version__, self.wan_label, self.wan_id, self.wan_kind))

        if route.startswith("/export"):
            if not self._authorised(query):
                return self._json(401, {"error": "invalid or missing export token"})
            return self._export(route, query)

        return self._json(404, {"error": "no such endpoint", "path": route})

    def _export(self, route: str, query: dict) -> None:
        if route == "/export/list":
            return self._json(200, {
                "wan": self.wan_id,
                "days": sorted(p.stem for p in self.store.raw_dir.glob("*.ndjson")),
            })

        if route == "/export/ndjson":
            date = (query.get("date") or [""])[0]
            if not _valid_date(date):
                return self._json(400, {"error": "date=YYYY-MM-DD is required"})
            path = self.store.raw_dir / ("%s.ndjson" % date)
            if not path.exists():
                return self._json(404, {"error": "no archive for that day", "date": date})
            return self._stream_file(path, "%s-%s.ndjson" % (self.wan_id, date),
                                     "application/x-ndjson")

        if route == "/export/sqlite":
            date_from = (query.get("from") or [""])[0] or None
            date_to = (query.get("to") or [""])[0] or None
            for value in (date_from, date_to):
                if value and not _valid_date(value):
                    return self._json(400, {"error": "from/to must be YYYY-MM-DD"})
            tmp_dir = Path(tempfile.mkdtemp(prefix="ispbust-export-"))
            tmp = tmp_dir / ("%s.sqlite" % self.wan_id)
            try:
                self.store.snapshot(tmp, date_from, date_to)
                name = "%s.sqlite" % self.wan_id
                self._stream_file(tmp, name, "application/vnd.sqlite3")
            except Exception as exc:  # noqa: BLE001
                LOG.exception("export failed")
                self._json(500, {"error": "export failed", "detail": str(exc)})
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        return self._json(404, {"error": "no such export", "path": route})


def make_server(store: Store, wan_id: str, wan_label: str, wan_kind: str,
                port: int, token: str | None = None,
                bind: str = "0.0.0.0", bind_retry_seconds: int = 30) -> ThreadingHTTPServer:
    """Build the probe's HTTP server, waiting for the port if it is still held.

    On a restart the previous process can still own the socket for a moment
    while it finishes flushing. Failing outright there costs a respawn cycle,
    and a respawn cycle is a hole in the record -- so wait for the port instead.
    """
    handler = type("BoundHandler", (Handler,), {
        "store": store, "wan_id": wan_id, "wan_label": wan_label,
        "wan_kind": wan_kind, "token": token,
    })
    deadline = time.monotonic() + max(0, bind_retry_seconds)
    while True:
        try:
            httpd = ThreadingHTTPServer((bind, port), handler)
            break
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE,) or time.monotonic() >= deadline:
                raise
            LOG.warning("port %d still in use, waiting for it to free up", port)
            time.sleep(2)
    httpd.daemon_threads = True
    return httpd


def serve_in_background(httpd: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return thread
