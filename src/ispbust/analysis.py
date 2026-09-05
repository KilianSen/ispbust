"""Turning rows into findings.

Nothing here formats anything. The report renderer and the `summary` command
both consume the same objects, so the numbers in a printed summary and the
numbers in the document handed to an operator cannot drift apart.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import SiteConfig, Thresholds
from .storage import open_db, sha256_of

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

# Roles whose loss represents "the internet, from here".
ANCHOR_ROLES = ("anchor", "anchor_de", "anchor_intl")
FIRST_HOP_ROLE = "isp_first_hop"


def minute_key(ts: str) -> str:
    """'2026-08-04T12:38:07.123Z' -> '2026-08-04T12:38' (UTC)."""
    return ts[:16]


def parse_minute(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)


def tzinfo_for(name: str):
    if ZoneInfo is None:
        return UTC
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown zone should not kill a report
        return UTC


# --------------------------------------------------------------- one link


@dataclass
class Bucket:
    sent: int = 0
    lost: int = 0
    rtt: list = field(default_factory=list)

    @property
    def loss(self) -> float:
        return (self.lost / self.sent) if self.sent else 0.0


class LinkData:
    """Per-minute rollups for a single WAN."""

    def __init__(self, wan_id: str, label: str, kind: str, rows: list, thresholds: Thresholds):
        self.id = wan_id
        self.label = label
        self.kind = kind
        self.th = thresholds
        self.anchor: dict = defaultdict(Bucket)
        self.first_hop: dict = defaultdict(Bucket)
        self.by_target: dict = defaultdict(lambda: {"sent": 0, "lost": 0, "role": "", "rtt": []})

        for r in rows:
            m = minute_key(r["ts"])
            bucket = None
            if r["role"] in ANCHOR_ROLES:
                bucket = self.anchor[m]
            elif r["role"] == FIRST_HOP_ROLE:
                bucket = self.first_hop[m]
            if bucket is not None:
                bucket.sent += r["sent"] or 0
                bucket.lost += r["lost"] or 0
                if r["rtt_avg"] is not None:
                    bucket.rtt.append(r["rtt_avg"])
            t = self.by_target[r["target"]]
            t["role"] = r["role"]
            t["sent"] += r["sent"] or 0
            t["lost"] += r["lost"] or 0
            if r["rtt_avg"] is not None:
                t["rtt"].append(r["rtt_avg"])

    def _source(self, which: str) -> dict:
        return self.anchor if which == "anchor" else self.first_hop

    def minute_loss(self, which: str = "anchor") -> dict:
        return {m: b.loss for m, b in self._source(which).items()}

    def totals(self, which: str = "anchor") -> tuple[int, int]:
        src = self._source(which)
        return sum(b.sent for b in src.values()), sum(b.lost for b in src.values())

    def loss_ratio(self, which: str = "anchor") -> float:
        sent, lost = self.totals(which)
        return (lost / sent) if sent else 0.0

    def measured_minutes(self, which: str = "anchor") -> int:
        return len(self._source(which))

    def count_at_or_above(self, threshold: float, which: str = "anchor") -> int:
        return sum(1 for b in self._source(which).values() if b.loss >= threshold)

    @property
    def degraded_minutes(self) -> int:
        return self.count_at_or_above(self.th.degraded_loss)

    @property
    def blackout_minutes(self) -> int:
        return self.count_at_or_above(self.th.blackout_loss)

    def daily(self, which: str = "anchor") -> dict:
        out: dict = defaultdict(lambda: {"sent": 0, "lost": 0, "minutes": 0,
                                         "degraded": 0, "blackout": 0, "rtt": []})
        for m, b in self._source(which).items():
            d = out[m[:10]]
            d["sent"] += b.sent
            d["lost"] += b.lost
            d["minutes"] += 1
            if b.loss >= self.th.degraded_loss:
                d["degraded"] += 1
            if b.loss >= self.th.blackout_loss:
                d["blackout"] += 1
            d["rtt"].extend(b.rtt)
        for d in out.values():
            d["loss"] = (d["lost"] / d["sent"]) if d["sent"] else 0.0
            d["rtt_median"] = statistics.median(d["rtt"]) if d["rtt"] else None
            d.pop("rtt")
        return dict(sorted(out.items()))

    def outages(self, min_minutes: int = 2, which: str = "anchor") -> list:
        """Runs of consecutive minutes at or above the degraded threshold."""
        loss = self.minute_loss(which)
        runs: list = []
        current: dict | None = None
        previous: datetime | None = None

        def close(run: dict | None) -> None:
            if run and len(run["losses"]) >= min_minutes:
                runs.append(run)

        for m in sorted(loss):
            dt = parse_minute(m)
            bad = loss[m] >= self.th.degraded_loss
            contiguous = previous is not None and (dt - previous) <= timedelta(minutes=2)
            if bad and current and contiguous:
                current["end"] = dt
                current["losses"].append(loss[m])
            elif bad:
                close(current)
                current = {"start": dt, "end": dt, "losses": [loss[m]]}
            else:
                close(current)
                current = None
            previous = dt
        close(current)

        for run in runs:
            run["minutes"] = len(run["losses"])
            run["avg_loss"] = sum(run["losses"]) / len(run["losses"])
            run["max_loss"] = max(run["losses"])
        runs.sort(key=lambda r: (r["minutes"], r["avg_loss"]), reverse=True)
        return runs

    def target_rows(self) -> list:
        rows = []
        for target, b in self.by_target.items():
            loss = (b["lost"] / b["sent"]) if b["sent"] else 0.0
            rows.append({
                "target": target, "role": b["role"], "sent": b["sent"], "lost": b["lost"],
                "loss": loss,
                "rtt_avg": statistics.fmean(b["rtt"]) if b["rtt"] else None,
            })
        rows.sort(key=lambda r: -r["loss"])
        return rows


# ------------------------------------------------------------- comparisons


def paired_comparison(primary: LinkData, control: LinkData) -> dict:
    """Minutes measured on both links at once.

    This is the part an operator cannot argue with: identical probes, identical
    targets, identical minute, one network broken and the other not.
    """
    p, c = primary.minute_loss(), control.minute_loss()
    common = sorted(set(p) & set(c))
    result = {
        "control_id": control.id, "control_label": control.label,
        "common_minutes": len(common), "both_bad": 0, "primary_only_bad": 0,
        "control_only_bad": 0, "neither_bad": 0, "primary_blackout_control_fine": 0,
        "first": common[0] if common else None, "last": common[-1] if common else None,
        "primary_loss": 0.0, "control_loss": 0.0,
    }
    if not common:
        return result

    th = primary.th.degraded_loss
    p_sent = p_lost = c_sent = c_lost = 0
    for m in common:
        pb, cb = p[m] >= th, c[m] >= th
        if pb and cb:
            result["both_bad"] += 1
        elif pb:
            result["primary_only_bad"] += 1
            if p[m] >= primary.th.blackout_loss and not cb:
                result["primary_blackout_control_fine"] += 1
        elif cb:
            result["control_only_bad"] += 1
        else:
            result["neither_bad"] += 1
        pb_bucket, cb_bucket = primary.anchor[m], control.anchor[m]
        p_sent += pb_bucket.sent
        p_lost += pb_bucket.lost
        c_sent += cb_bucket.sent
        c_lost += cb_bucket.lost

    result["primary_loss"] = (p_lost / p_sent) if p_sent else 0.0
    result["control_loss"] = (c_lost / c_sent) if c_sent else 0.0
    return result


def cycle_profile(link: LinkData, tz_name: str, hour: int) -> list:
    """Loss bucketed by hours elapsed since a daily event (e.g. a power cycle).

    If a nightly reboot is curing a fault, loss is lowest right after it and
    climbs. If the reboot is *causing* the outage, the spike sits in the hours
    immediately following. Same data, opposite conclusions -- so plot it.
    """
    tz = tzinfo_for(tz_name)
    buckets = {h: {"sent": 0, "lost": 0, "minutes": 0, "degraded": 0} for h in range(24)}
    for m, b in link.anchor.items():
        local = parse_minute(m).astimezone(tz)
        since = (local.hour - hour) % 24
        bucket = buckets[since]
        bucket["sent"] += b.sent
        bucket["lost"] += b.lost
        bucket["minutes"] += 1
        if b.loss >= link.th.degraded_loss:
            bucket["degraded"] += 1
    return [{
        "hours_since": h,
        "local_hour": (hour + h) % 24,
        "loss": (buckets[h]["lost"] / buckets[h]["sent"]) if buckets[h]["sent"] else 0.0,
        "minutes": buckets[h]["minutes"],
        "degraded_minutes": buckets[h]["degraded"],
    } for h in range(24)]


def hour_of_day_profile(link: LinkData, tz_name: str) -> list:
    """Loss by local hour of day -- separates congestion from hardware faults."""
    tz = tzinfo_for(tz_name)
    buckets = {h: {"sent": 0, "lost": 0, "minutes": 0} for h in range(24)}
    for m, b in link.anchor.items():
        h = parse_minute(m).astimezone(tz).hour
        buckets[h]["sent"] += b.sent
        buckets[h]["lost"] += b.lost
        buckets[h]["minutes"] += 1
    return [{
        "hour": h,
        "loss": (buckets[h]["lost"] / buckets[h]["sent"]) if buckets[h]["sent"] else 0.0,
        "minutes": buckets[h]["minutes"],
    } for h in range(24)]


def reach_summary(rows: list) -> dict:
    """Per (host, family): how often a real connection actually completed.

    `resolved == 0` means the family had no record for that host, which is not
    a fault and is counted separately -- an IPv4-only site must never look like
    a broken IPv6 path.
    """
    by_key: dict = defaultdict(
        lambda: {"attempts": 0, "ok": 0, "failed": 0, "unresolved": 0,
                 "errors": {}, "last_address": None, "connect": []})
    for r in rows:
        b = by_key[(r["host"], r["family"])]
        if not r["resolved"]:
            b["unresolved"] += 1
            continue
        b["attempts"] += 1
        b["last_address"] = r["address"] or b["last_address"]
        if r["ok"]:
            b["ok"] += 1
            if r["connect_s"] is not None:
                b["connect"].append(r["connect_s"])
        else:
            b["failed"] += 1
            if r["error"]:
                key = r["error"].split(":")[0]
                b["errors"][key] = b["errors"].get(key, 0) + 1
    out = {}
    for (host, family), b in by_key.items():
        b["fail_ratio"] = (b["failed"] / b["attempts"]) if b["attempts"] else 0.0
        b["connect_avg"] = statistics.fmean(b["connect"]) if b["connect"] else None
        b.pop("connect")
        out[(host, family)] = b
    return out


def broken_families(summary: dict) -> list:
    """Hosts where one family works and another resolves but never connects."""
    hosts: dict = defaultdict(dict)
    for (host, family), b in summary.items():
        hosts[host][family] = b
    findings = []
    for host, families in sorted(hosts.items()):
        working = [f for f, b in families.items() if b["attempts"] and b["fail_ratio"] < 0.5]
        broken = [f for f, b in families.items() if b["attempts"] and b["fail_ratio"] >= 0.5]
        for family in broken:
            if working:
                findings.append({
                    "host": host, "family": family,
                    "address": families[family]["last_address"],
                    "fail_ratio": families[family]["fail_ratio"],
                    "attempts": families[family]["attempts"],
                    "working": sorted(working),
                    "errors": families[family]["errors"],
                })
    return findings


def dns_summary(rows: list) -> dict:
    by_resolver: dict = defaultdict(
        lambda: {"total": 0, "failed": 0, "nxdomain": 0, "role": "", "durations": []})
    for r in rows:
        b = by_resolver[r["resolver"]]
        b["role"] = r["resolver_role"] or ""
        b["total"] += 1
        if r["outcome"] in ("timeout", "error"):
            b["failed"] += 1
        elif r["outcome"] == "nxdomain":
            b["nxdomain"] += 1
        if r["duration_s"] is not None:
            b["durations"].append(r["duration_s"])
    for b in by_resolver.values():
        d = sorted(b["durations"])
        b["p50"] = d[len(d) // 2] if d else None
        b["p95"] = d[min(len(d) - 1, int(0.95 * (len(d) - 1)))] if d else None
        b["fail_ratio"] = (b["failed"] / b["total"]) if b["total"] else 0.0
        b.pop("durations")
    return dict(by_resolver)


# ------------------------------------------------------------ orchestration


@dataclass
class Analysis:
    site: SiteConfig
    date_from: str
    date_to: str
    primary: LinkData
    controls: list
    comparison: dict
    daily_primary: dict
    daily_control: dict
    outages: list
    control_minute_loss: dict
    cycle: list
    hour_profile: list
    dns: dict
    traces: list
    first_hop_ips: list
    files: list
    reach: dict = field(default_factory=dict)
    reach_control: dict = field(default_factory=dict)
    reach_broken: list = field(default_factory=list)
    window_seconds: int = 60

    @property
    def has_control(self) -> bool:
        return bool(self.controls)

    @property
    def has_first_hop(self) -> bool:
        return self.primary.totals(FIRST_HOP_ROLE)[0] > 0

    def headline(self) -> dict:
        return {
            "link": self.primary.label,
            "measured_minutes": self.primary.measured_minutes(),
            "loss": self.primary.loss_ratio(),
            "first_hop_loss": self.primary.loss_ratio(FIRST_HOP_ROLE) if self.has_first_hop else None,
            "degraded_minutes": self.primary.degraded_minutes,
            "blackout_minutes": self.primary.blackout_minutes,
            "outage_events": len(self.outages),
            "control_loss": self.comparison.get("control_loss") if self.has_control else None,
            "primary_only_bad": self.comparison.get("primary_only_bad") if self.has_control else None,
            "common_minutes": self.comparison.get("common_minutes") if self.has_control else None,
        }


def _load_icmp(con: sqlite3.Connection, wan: str, t0: str, t1: str) -> list:
    return con.execute(
        "SELECT ts, target, role, sent, lost, loss_ratio, rtt_avg, rtt_max, rtt_p95 "
        "FROM icmp WHERE wan = ? AND ts >= ? AND ts < ? ORDER BY ts", (wan, t0, t1)).fetchall()


def analyse(site: SiteConfig, databases: dict, date_from: str, date_to: str) -> Analysis:
    """Build the full analysis from a mapping of wan id -> sqlite path."""
    t0 = date_from + "T00:00"
    t1 = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00"

    links: dict = {}
    connections: dict = {}
    for ref in site.probes:
        path = databases.get(ref.id)
        if not path or not Path(path).exists():
            continue
        con = open_db(Path(path), read_only=True)
        connections[ref.id] = con
        links[ref.id] = LinkData(ref.id, ref.label, ref.kind,
                                 _load_icmp(con, ref.id, t0, t1), site.thresholds)

    primary_ref = site.under_test
    if primary_ref.id not in links:
        raise ValueError("no data found for the link under test (%s)" % primary_ref.id)
    primary = links[primary_ref.id]
    controls = [links[r.id] for r in site.controls if r.id in links]

    comparison = paired_comparison(primary, controls[0]) if controls else {}
    control_minute_loss = controls[0].minute_loss() if controls else {}
    daily_control = controls[0].daily() if controls else {}

    con = connections[primary_ref.id]
    dns_rows = con.execute(
        "SELECT ts, resolver, resolver_role, qname, outcome, rcode, duration_s "
        "FROM dns WHERE wan = ? AND ts >= ? AND ts < ? ORDER BY ts",
        (primary_ref.id, t0, t1)).fetchall()
    traces = con.execute(
        "SELECT ts, target, trigger, hops_json FROM trace "
        "WHERE wan = ? AND ts >= ? AND ts < ? AND trigger = 'event' ORDER BY ts DESC LIMIT 5",
        (primary_ref.id, t0, t1)).fetchall()
    hop_rows = con.execute(
        "SELECT DISTINCT detail FROM markers WHERE wan = ? AND kind = 'upstream_hop' "
        "AND ts >= ? AND ts < ?", (primary_ref.id, t0, t1)).fetchall()
    def _reach(wan_id: str, connection) -> list:
        try:
            return connection.execute(
                "SELECT ts, host, port, family, address, resolved, connect_s, tls_s, "
                "http_status, ok, error FROM reach WHERE wan = ? AND ts >= ? AND ts < ?",
                (wan_id, t0, t1)).fetchall()
        except sqlite3.Error:
            # A probe running an older build has no reach table yet.
            return []

    reach = reach_summary(_reach(primary_ref.id, con))
    reach_control = {}
    if controls and site.controls[0].id in connections:
        reach_control = reach_summary(
            _reach(site.controls[0].id, connections[site.controls[0].id]))

    window_row = con.execute(
        "SELECT window_s, COUNT(*) AS n FROM icmp WHERE wan = ? AND ts >= ? AND ts < ? "
        "GROUP BY window_s ORDER BY n DESC LIMIT 1", (primary_ref.id, t0, t1)).fetchone()

    parsed_traces = []
    for t in traces:
        try:
            hops = json.loads(t["hops_json"])
        except (ValueError, TypeError):
            hops = []
        parsed_traces.append({"ts": t["ts"], "target": t["target"], "hops": hops})

    files = []
    for wan_id, path in sorted(databases.items()):
        p = Path(path)
        if not p.exists():
            continue
        digest, size = sha256_of(p)
        files.append({"name": "%s (%s)" % (p.name, wan_id), "bytes": size, "sha256": digest})

    analysis = Analysis(
        site=site,
        date_from=date_from,
        date_to=date_to,
        primary=primary,
        controls=controls,
        comparison=comparison,
        daily_primary=primary.daily(),
        daily_control=daily_control,
        outages=primary.outages(),
        control_minute_loss=control_minute_loss,
        cycle=cycle_profile(primary, site.timezone, site.experiment.hour)
        if site.experiment.enabled else [],
        hour_profile=hour_of_day_profile(primary, site.timezone),
        dns=dns_summary(dns_rows),
        traces=parsed_traces,
        first_hop_ips=sorted({r["detail"] for r in hop_rows if r["detail"]}),
        files=files,
        reach=reach,
        reach_control=reach_control,
        reach_broken=broken_families(reach),
        window_seconds=int(window_row["window_s"] or 60) if window_row else 60,
    )
    for con in connections.values():
        con.close()
    return analysis
