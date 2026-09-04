"""Rebuild the report on a schedule and serve it over HTTP.

This is what makes the report container a service rather than a command you
have to remember to run. It pulls fresh snapshots from every probe, rebuilds
the rolling report, keeps the dated copies, and serves the lot on a plain
directory listing.

Kept deliberately small: the report itself is a single self-contained file, so
"serving" it needs no framework and no database.
"""

from __future__ import annotations

import html
import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .analysis import analyse
from .config import load_site_config
from .report.builder import build_report
from .retrieve import fetch_all

LOG = logging.getLogger("ispbust.serve")

INDEX_CSS = """
body{font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
     margin:0 auto;padding:32px;max-width:760px;color:#12161c}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#5a6673;margin:0 0 24px}
ul{list-style:none;padding:0;margin:0}
li{border:1px solid #d7dde5;border-radius:8px;padding:10px 14px;margin-bottom:8px;
   display:flex;justify-content:space-between;align-items:center;gap:12px}
li.latest{border-color:#2b6cb0;background:#f5f9ff}
a{color:#2b6cb0;text-decoration:none;font-weight:600}
a:hover{text-decoration:underline}
.meta{color:#5a6673;font-size:12px;font-variant-numeric:tabular-nums}
.empty{color:#5a6673;font-style:italic}
"""


def write_index(reports_dir: Path, site_name: str, last_build: dict | None) -> None:
    reports = sorted((p for p in reports_dir.glob("report-*.html")), reverse=True)
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           "<title>ispbust reports — %s</title>" % html.escape(site_name),
           "<style>%s</style></head><body>" % INDEX_CSS,
           "<h1>Connection fault reports</h1>"]

    if last_build:
        out.append('<p class="sub">%s · last rebuilt %s · %s measured minutes · '
                   "%.2f %% packet loss</p>"
                   % (html.escape(site_name),
                      html.escape(last_build["built_at"]),
                      "{:,}".format(last_build["measured_minutes"]),
                      last_build["loss"] * 100))
    else:
        out.append('<p class="sub">%s · no report built yet</p>' % html.escape(site_name))

    if (reports_dir / "latest.html").exists():
        out.append('<ul><li class="latest"><a href="latest.html">Current report</a>'
                   '<span class="meta">always the newest build</span></li>')
    else:
        out.append("<ul>")

    for path in reports[:60]:
        stat = path.stat()
        out.append('<li><a href="%s">%s</a><span class="meta">%s · %.0f KB</span></li>'
                   % (html.escape(path.name), html.escape(path.stem.replace("report-", "")),
                      datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                      stat.st_size / 1024))
    if not reports:
        out.append('<li class="empty">Nothing generated yet.</li>')
    out.append("</ul></body></html>")
    (reports_dir / "index.html").write_text("".join(out), encoding="utf-8")


def build_once(site_path: Path, reports_dir: Path, data_dir: Path,
               days: int, language: str | None) -> dict:
    site = load_site_config(site_path)
    date_to = (date.today() - timedelta(days=1)).isoformat()
    date_from = (date.today() - timedelta(days=days)).isoformat()

    databases = fetch_all(site, data_dir, date_from, date_to)
    analysis = analyse(site, databases, date_from, date_to)
    document = build_report(analysis, language)

    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    dated = reports_dir / ("report-%s_%s-to-%s.html" % (stamp, date_from, date_to))
    dated.write_text(document, encoding="utf-8")
    (reports_dir / "latest.html").write_text(document, encoding="utf-8")

    headline = analysis.headline()
    headline["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    headline["file"] = dated.name
    write_index(reports_dir, site.name, headline)
    LOG.info("built %s -- %.2f%% loss over %s minutes",
             dated.name, headline["loss"] * 100, headline["measured_minutes"])
    return headline


def rebuild_loop(site_path: Path, reports_dir: Path, data_dir: Path, days: int,
                 language: str | None, interval: int, stop: threading.Event) -> None:
    while not stop.is_set():
        started = time.time()
        try:
            build_once(site_path, reports_dir, data_dir, days, language)
        except Exception as exc:  # noqa: BLE001 - a failed build must not kill the server
            LOG.error("rebuild failed: %s", exc)
            try:
                site = load_site_config(site_path)
                write_index(reports_dir, site.name, None)
            except Exception:  # noqa: BLE001
                pass
        stop.wait(max(60.0, interval - (time.time() - started)))


def serve(site_path: Path, reports_dir: Path, port: int, interval: int,
          days: int, language: str | None, data_dir: Path) -> int:
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    stop = threading.Event()
    worker = threading.Thread(
        target=rebuild_loop,
        args=(site_path, reports_dir, data_dir, days, language, interval, stop),
        name="rebuild", daemon=True)
    worker.start()

    handler = partial(SimpleHTTPRequestHandler, directory=str(reports_dir))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.daemon_threads = True
    LOG.info("serving %s on :%d, rebuilding every %ds over the last %d days",
             reports_dir, port, interval, days)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        stop.set()
        httpd.server_close()
    return 0
