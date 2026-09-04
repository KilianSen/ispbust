"""Pull measurement data from the collection containers.

The report container never touches a probe's live database. It asks each probe
for a snapshot over HTTP, which keeps probes free to sit on isolated VLANs with
no shared storage and no SSH between them.

A probe configured with a local `db:` path instead of a `url:` is simply
copied -- useful when everything runs on one host, or when you are working from
an archive after the fact.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import ProbeRef, SiteConfig
from .storage import open_db, sha256_of

LOG = logging.getLogger("ispbust.retrieve")

TIMEOUT = 300  # a year of data over a slow link takes a while


class RetrievalError(RuntimeError):
    pass


def _request(url: str, token: str | None, timeout: int = 30):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(req, timeout=timeout)


def probe_info(ref: ProbeRef) -> dict:
    """Ask a probe what it is and how much data it holds."""
    if not ref.url:
        info = {"wan": {"id": ref.id, "label": ref.label, "kind": ref.kind},
                "source": "local file", "path": str(ref.db)}
        # A local file gets the same shape as a live probe's /info so callers
        # do not have to care which kind of source they are looking at.
        path = Path(ref.db)
        if path.exists():
            con = open_db(path, read_only=True)
            try:
                row = con.execute(
                    "SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last FROM icmp"
                ).fetchone()
                info["store"] = {"tables": {"icmp": {
                    "rows": row["n"], "first": row["first"], "last": row["last"]}}}
            except sqlite3.Error as exc:
                info["store"] = {"error": str(exc)}
            finally:
                con.close()
        else:
            info["store"] = {"error": "file not found"}
        return info
    url = ref.url.rstrip("/") + "/info"
    try:
        with _request(url, ref.token) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RetrievalError("could not reach probe %s at %s: %s" % (ref.id, url, exc)) from exc


def fetch_probe(ref: ProbeRef, out_dir: Path,
                date_from: str | None = None, date_to: str | None = None) -> Path:
    """Return a local path to this probe's database."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / ("%s.sqlite" % ref.id)

    if not ref.url:
        source = Path(ref.db)
        if not source.exists():
            raise RetrievalError("probe %s: database not found at %s" % (ref.id, source))
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        LOG.info("probe %s: copied %s", ref.id, source)
        return dest

    params = {}
    if date_from:
        params["from"] = date_from
    if date_to:
        params["to"] = date_to
    url = ref.url.rstrip("/") + "/export/sqlite"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    LOG.info("probe %s: downloading %s", ref.id, url)
    tmp = dest.with_suffix(".sqlite.part")
    try:
        with _request(url, ref.token, TIMEOUT) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        hint = " (check the export token)" if exc.code == 401 else ""
        raise RetrievalError("probe %s: HTTP %s from %s%s"
                             % (ref.id, exc.code, url, hint)) from exc
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise RetrievalError("probe %s: %s" % (ref.id, exc)) from exc

    tmp.replace(dest)
    digest, size = sha256_of(dest)
    LOG.info("probe %s: %.1f MB, sha256 %s", ref.id, size / 1048576, digest[:16])
    return dest


def fetch_all(site: SiteConfig, out_dir: Path,
              date_from: str | None = None, date_to: str | None = None,
              required: bool = True) -> dict:
    """Fetch every probe in the site config.

    The link under test is mandatory: without it there is no report. A control
    that cannot be reached is a warning -- the report still builds, it just
    loses the side-by-side comparison and says so.
    """
    results: dict = {}
    for ref in site.probes:
        try:
            results[ref.id] = fetch_probe(ref, out_dir, date_from, date_to)
        except RetrievalError as exc:
            if ref.kind == "under_test" and required:
                raise
            LOG.warning("skipping control probe %s: %s", ref.id, exc)
    if site.under_test.id not in results:
        raise RetrievalError("no data for the link under test (%s)" % site.under_test.id)
    return results
