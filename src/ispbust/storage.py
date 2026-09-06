"""Durable storage for measurements.

Three sinks, deliberately:

* **SQLite** -- queryable, and what the report is built from
* **NDJSON** -- append-only daily files, the archive you hand over when someone
  asks for raw data; nothing rewrites them
* Prometheus lives in :mod:`ispbust.metrics` and is the live view only

Every write is best-effort: a probe that dies because a disk hiccuped is a
probe that produces a gap in the evidence exactly when it matters.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOG = logging.getLogger("ispbust.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS icmp (
  ts TEXT NOT NULL, wan TEXT NOT NULL, target TEXT NOT NULL, role TEXT NOT NULL,
  sent INTEGER, lost INTEGER, loss_ratio REAL,
  rtt_min REAL, rtt_avg REAL, rtt_max REAL, rtt_p95 REAL, rtt_stddev REAL,
  window_s INTEGER
);
CREATE INDEX IF NOT EXISTS icmp_ts ON icmp(ts);
CREATE INDEX IF NOT EXISTS icmp_role_ts ON icmp(role, ts);

CREATE TABLE IF NOT EXISTS dns (
  ts TEXT NOT NULL, wan TEXT NOT NULL, resolver TEXT NOT NULL, resolver_role TEXT,
  qname TEXT NOT NULL, qtype TEXT, outcome TEXT NOT NULL, rcode TEXT,
  duration_s REAL, answer TEXT
);
CREATE INDEX IF NOT EXISTS dns_ts ON dns(ts);
CREATE INDEX IF NOT EXISTS dns_outcome ON dns(outcome, ts);

CREATE TABLE IF NOT EXISTS tcp (
  ts TEXT NOT NULL, wan TEXT NOT NULL, target TEXT NOT NULL, port INTEGER,
  connect_s REAL, tls_s REAL, ok INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS tcp_ts ON tcp(ts);

CREATE TABLE IF NOT EXISTS trace (
  ts TEXT NOT NULL, wan TEXT NOT NULL, target TEXT NOT NULL,
  trigger TEXT, hops_json TEXT
);
CREATE INDEX IF NOT EXISTS trace_ts ON trace(ts);

CREATE TABLE IF NOT EXISTS events (
  ts TEXT NOT NULL, wan TEXT NOT NULL, kind TEXT NOT NULL,
  target TEXT, role TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS markers (
  ts TEXT NOT NULL, wan TEXT, kind TEXT NOT NULL, detail TEXT
);
CREATE INDEX IF NOT EXISTS markers_ts ON markers(ts);

-- One row per (host, address family) attempt: did the name resolve, did the
-- connection open, did TLS complete, what did the server say. This is what a
-- browser actually experiences, and it is the only check that catches a
-- dual-stack host whose AAAA path is broken while its A path is fine.
CREATE TABLE IF NOT EXISTS reach (
  ts TEXT NOT NULL, wan TEXT NOT NULL, host TEXT NOT NULL, port INTEGER,
  family TEXT NOT NULL, address TEXT, resolved INTEGER,
  connect_s REAL, tls_s REAL, http_status INTEGER, ok INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS reach_ts ON reach(ts);
CREATE INDEX IF NOT EXISTS reach_host ON reach(host, family, ts);

-- Which public address this probe actually left by. A probe pinned to one
-- uplink that quietly fails over to another keeps reporting a healthy line
-- during the outage it exists to record, so every other number here depends
-- on this one.
CREATE TABLE IF NOT EXISTS egress (
  ts TEXT NOT NULL, wan TEXT NOT NULL, family TEXT NOT NULL,
  address TEXT, expected TEXT, ok INTEGER, endpoint TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS egress_ts ON egress(ts);
CREATE INDEX IF NOT EXISTS egress_ok ON egress(ok, ts);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT
);
"""

TABLES = ("icmp", "dns", "tcp", "trace", "events", "markers", "reach", "egress")

# Columns added after the first release. Applied on open so a probe that has
# been collecting for weeks keeps its history across an upgrade -- re-measuring
# last month is not an option.
MIGRATIONS: dict = {
    "icmp": {"family": "TEXT"},
    "dns": {"family": "TEXT"},
    "tcp": {"family": "TEXT"},
}


def migrate(con: sqlite3.Connection) -> list:
    """Add any columns this version expects but an older database lacks."""
    added = []
    for table, columns in MIGRATIONS.items():
        try:
            present = {row[1] for row in con.execute("PRAGMA table_info(%s)" % table)}
        except sqlite3.Error:
            continue
        if not present:
            continue
        for column, decl in columns.items():
            if column not in present:
                try:
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
                    added.append("%s.%s" % (table, column))
                except sqlite3.Error as exc:
                    LOG.error("could not add %s.%s: %s", table, column, exc)
    if added:
        con.commit()
        LOG.info("schema migration added: %s", ", ".join(added))
    return added


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime | None = None) -> str:
    return (ts or utcnow()).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def open_db(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
        con.commit()
        migrate(con)
    con.row_factory = sqlite3.Row
    return con


class Store:
    """SQLite plus an append-only NDJSON archive."""

    def __init__(self, db_path: Path, raw_dir: Path, wan: str, retain_days: int = 0):
        self.db_path = db_path
        self.raw_dir = raw_dir
        self.wan = wan
        self.retain_days = retain_days
        raw_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = open_db(db_path)
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                        ("wan", wan))
        self.db.commit()

    # -- writing ------------------------------------------------------

    def _archive(self, table: str, row: dict) -> None:
        path = self.raw_dir / (utcnow().strftime("%Y-%m-%d") + ".ndjson")
        payload = {"table": table}
        payload.update(row)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except OSError as exc:
            LOG.warning("raw archive write failed: %s", exc)

    def insert(self, table: str, row: dict) -> None:
        if table not in TABLES:
            raise ValueError("unknown table: %s" % table)
        cols = ",".join(row)
        marks = ",".join("?" * len(row))
        with self.lock:
            try:
                self.db.execute(
                    "INSERT INTO %s (%s) VALUES (%s)" % (table, cols, marks),
                    tuple(row.values()))
                self.db.commit()
            except sqlite3.Error as exc:
                LOG.error("sqlite insert into %s failed: %s", table, exc)
        self._archive(table, row)

    def marker(self, kind: str, detail: str) -> None:
        self.insert("markers", {"ts": iso(), "wan": self.wan, "kind": kind, "detail": detail})

    # -- small persistent key/value -----------------------------------

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        """Survives restarts, which is the point: a baseline relearned on every
        start would silently adopt whatever the link was doing at that moment."""
        with self.lock:
            try:
                row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            except sqlite3.Error as exc:
                LOG.error("meta read failed: %s", exc)
                return default
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.lock:
            try:
                self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                                (key, value))
                self.db.commit()
            except sqlite3.Error as exc:
                LOG.error("meta write failed: %s", exc)

    # -- housekeeping -------------------------------------------------

    def prune(self) -> int:
        """Drop rows older than retain_days. 0 means keep everything.

        The NDJSON archive is never pruned -- it is the evidence of record.
        """
        if self.retain_days <= 0:
            return 0
        cutoff = iso(utcnow() - timedelta(days=self.retain_days))
        removed = 0
        with self.lock:
            try:
                for table in TABLES:
                    cur = self.db.execute("DELETE FROM %s WHERE ts < ?" % table, (cutoff,))
                    removed += cur.rowcount or 0
                self.db.commit()
            except sqlite3.Error as exc:
                LOG.error("prune failed: %s", exc)
        if removed:
            LOG.info("pruned %d rows older than %s", removed, cutoff)
        return removed

    # -- reading ------------------------------------------------------

    def summary(self) -> dict:
        out: dict = {"wan": self.wan, "tables": {}}
        with self.lock:
            for table in TABLES:
                try:
                    row = self.db.execute(
                        "SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last FROM %s" % table
                    ).fetchone()
                    out["tables"][table] = {"rows": row["n"], "first": row["first"], "last": row["last"]}
                except sqlite3.Error as exc:
                    out["tables"][table] = {"error": str(exc)}
        try:
            out["db_bytes"] = self.db_path.stat().st_size
        except OSError:
            out["db_bytes"] = None
        out["raw_files"] = sorted(p.name for p in self.raw_dir.glob("*.ndjson"))
        return out

    def snapshot(self, dest: Path, date_from: str | None = None, date_to: str | None = None) -> Path:
        """Write a consistent copy of the database, optionally time-filtered.

        Uses SQLite's own VACUUM INTO for the full copy so the snapshot is
        internally consistent even while the probe keeps writing.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        with self.lock:
            self.db.execute("VACUUM INTO ?", (str(dest),))
        if not (date_from or date_to):
            return dest

        lo = (date_from or "0000-01-01") + "T00:00"
        hi = (date_to or "9999-12-31") + "T23:59:59.999Z"
        con = sqlite3.connect(str(dest), timeout=30)
        try:
            for table in TABLES:
                con.execute("DELETE FROM %s WHERE ts < ? OR ts > ?" % table, (lo, hi))
            con.commit()
            con.execute("VACUUM")
            con.commit()
        finally:
            con.close()
        return dest

    def close(self) -> None:
        with self.lock, contextlib.suppress(sqlite3.Error):
            self.db.close()


def sha256_of(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def merge_databases(sources: dict, dest: Path) -> Path:
    """Combine several probe databases into one, tagging rows by WAN id.

    Rows already carry a `wan` column, so a merge is a straight copy. Used when
    the report is built from files rather than live probe endpoints.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    out = open_db(dest)
    try:
        for wan_id, src in sources.items():
            if not Path(src).exists():
                LOG.warning("skipping missing database for %s: %s", wan_id, src)
                continue
            tmp = Path(tempfile.gettempdir()) / ("ispbust-merge-%s.sqlite" % wan_id)
            shutil.copy2(src, tmp)
            out.execute("ATTACH DATABASE ? AS src", (str(tmp),))
            try:
                for table in TABLES:
                    out.execute("INSERT INTO %s SELECT * FROM src.%s" % (table, table))
                out.commit()
            finally:
                out.execute("DETACH DATABASE src")
                tmp.unlink(missing_ok=True)
    finally:
        out.close()
    return dest
