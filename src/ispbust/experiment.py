"""A/B testing a daily intervention, usually a modem power cycle.

Rebooting a modem every night is a common folk remedy, and it is genuinely
ambiguous: the same symptom pattern fits "the reboot is fixing a device that
degrades" and "the reboot is triggering a re-registration that costs hours".
Those call for opposite actions, so the honest move is to measure.

The arm for each night is derived from a fixed seed, which means the schedule
is decided in advance and cannot drift to fit the result. That property is what
makes the outcome evidence rather than an anecdote.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .analysis import parse_minute, tzinfo_for
from .config import ExperimentConfig, SiteConfig
from .storage import iso, open_db

LOG = logging.getLogger("ispbust.experiment")

REBOOT = "reboot"
CONTROL = "no_reboot"


def arm_for(day: date, seed: int) -> str:
    """Deterministic arm for one night.

    Balanced in pairs of consecutive nights, so a run of one arm cannot line up
    with a weekend, a weather front or an operator maintenance window.
    """
    pair_index = day.toordinal() // 2
    coin = hashlib.sha256(("%d:%d" % (seed, pair_index)).encode()).digest()[0] & 1
    first_of_pair = day.toordinal() % 2 == 0
    reboot = (coin == 1) if first_of_pair else (coin == 0)
    return REBOOT if reboot else CONTROL


def plan(seed: int, days: int, start: date | None = None, hour: int = 3) -> list:
    start = start or date.today()
    return [{"date": start + timedelta(days=i),
             "arm": arm_for(start + timedelta(days=i), seed)} for i in range(days)]


def format_plan(entries: list, seed: int, hour: int) -> str:
    counts = defaultdict(int)
    lines = ["A/B schedule for the nightly intervention",
             "seed=%d  start=%s  days=%d  hour=%02d:00 local"
             % (seed, entries[0]["date"], len(entries), hour),
             "",
             "%-12s %-10s %s" % ("date", "weekday", "arm")]
    for e in entries:
        counts[e["arm"]] += 1
        lines.append("%-12s %-10s %s" % (
            e["date"].isoformat(), e["date"].strftime("%a"),
            "POWER CYCLE" if e["arm"] == REBOOT else "leave running"))
    lines += ["",
              "balance: %d intervention nights, %d control nights"
              % (counts[REBOOT], counts[CONTROL]),
              "",
              "Keep this file. Committing to the schedule in advance is what makes",
              "the result evidence rather than an anecdote."]
    return "\n".join(lines)


def write_marker(db: Path, wan: str, kind: str, detail: str) -> bool:
    if not db.exists():
        LOG.warning("database %s does not exist -- marker not recorded", db)
        return False
    con = open_db(db)
    try:
        con.execute("INSERT INTO markers (ts, wan, kind, detail) VALUES (?,?,?,?)",
                    (iso(), wan, kind, detail))
        con.commit()
        return True
    finally:
        con.close()


def _hit(url: str, timeout: int = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return "HTTP %d" % resp.status


def run_tonight(cfg: ExperimentConfig, db: Path, wan: str,
                dry_run: bool = False, today: date | None = None) -> dict:
    """Execute tonight's arm. Intended to be called from cron at `cfg.hour`."""
    today = today or date.today()
    arm = arm_for(today, cfg.seed)
    detail = {"arm": arm, "seed": cfg.seed, "date": today.isoformat()}

    if arm == CONTROL:
        detail["action"] = "none"
        if not dry_run:
            write_marker(db, wan, "ab_control_night", json.dumps(detail))
        return detail

    detail["off_seconds"] = cfg.off_seconds
    if dry_run:
        detail["action"] = "would power cycle"
        detail["off_url"] = cfg.plug_off_url or "<not configured>"
        detail["on_url"] = cfg.plug_on_url or "<not configured>"
        return detail

    if not (cfg.plug_off_url and cfg.plug_on_url):
        detail["action"] = "marker only -- no plug URLs configured"
        write_marker(db, wan, "ab_reboot_night", json.dumps(detail))
        return detail

    write_marker(db, wan, "ab_reboot_begin", json.dumps(detail))
    ok = True
    try:
        detail["off_result"] = _hit(cfg.plug_off_url)
        time.sleep(cfg.off_seconds)
        detail["on_result"] = _hit(cfg.plug_on_url)
    except Exception as exc:  # noqa: BLE001
        ok = False
        detail["error"] = "%s: %s" % (type(exc).__name__, exc)
        # A plug that failed to switch back on is the worst possible outcome,
        # so try once more regardless of what went wrong.
        try:
            detail["recovery"] = _hit(cfg.plug_on_url)
        except Exception as exc2:  # noqa: BLE001
            detail["recovery_error"] = str(exc2)
    write_marker(db, wan, "ab_reboot_night" if ok else "ab_reboot_failed", json.dumps(detail))
    return detail


def analyse(site: SiteConfig, db: Path, wan: str, since: str) -> dict:
    """Compare loss between intervention nights and control nights."""
    cfg = site.experiment
    tz = tzinfo_for(site.timezone)
    con = open_db(db, read_only=True)
    try:
        rows = con.execute(
            "SELECT ts, sent, lost FROM icmp WHERE wan = ? AND role IN "
            "('anchor','anchor_de','anchor_intl') AND ts >= ? ORDER BY ts",
            (wan, since + "T00:00")).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError("no ICMP rows for %s since %s" % (wan, since))

    per_minute: dict = defaultdict(lambda: {"sent": 0, "lost": 0})
    for r in rows:
        b = per_minute[r["ts"][:16]]
        b["sent"] += r["sent"] or 0
        b["lost"] += r["lost"] or 0

    arms: dict = {REBOOT: [], CONTROL: []}
    early: dict = {REBOOT: [], CONTROL: []}
    for m, b in per_minute.items():
        if not b["sent"]:
            continue
        local = parse_minute(m).astimezone(tz)
        # A "night" runs from the intervention hour to the next one, so the
        # hours after a power cycle belong to that cycle rather than being
        # split across two calendar days.
        cycle_day = (local - timedelta(hours=cfg.hour)).date()
        arm = arm_for(cycle_day, cfg.seed)
        loss = b["lost"] / b["sent"]
        arms[arm].append(loss)
        if (local.hour - cfg.hour) % 24 < 12:
            early[arm].append(loss)

    def stats(values: list) -> dict:
        if not values:
            return {"minutes": 0}
        ordered = sorted(values)
        return {
            "minutes": len(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "p95": ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))],
            "degraded_share": sum(1 for v in values if v >= site.thresholds.degraded_loss) / len(values),
        }

    result = {
        "seed": cfg.seed, "since": since, "hour": cfg.hour, "timezone": site.timezone,
        "full_cycle": {REBOOT: stats(arms[REBOOT]), CONTROL: stats(arms[CONTROL])},
        "first_12h": {REBOOT: stats(early[REBOOT]), CONTROL: stats(early[CONTROL])},
    }
    result["reading"] = _reading(arms, site.thresholds.degraded_loss)
    return result


def _reading(arms: dict, degraded: float) -> dict:
    r, c = arms[REBOOT], arms[CONTROL]
    if not r or not c:
        return {"verdict": "insufficient_data",
                "text": "Not enough data in one or both arms yet."}
    n = min(len(r), len(c))
    r_mean, c_mean = statistics.fmean(r), statistics.fmean(c)
    if n < 2000:
        return {"verdict": "insufficient_data",
                "text": "Only %d comparable minutes per arm. A week per arm is the "
                        "minimum worth quoting -- keep collecting." % n}
    if r_mean > c_mean * 1.25:
        return {"verdict": "reboot_harmful",
                "text": "Loss is materially HIGHER on nights the device is power cycled. "
                        "The reboot is not curing the fault, it is contributing to it. "
                        "Stop the timer, let the line run, and take the measurement to "
                        "the operator as it stands."}
    if c_mean > r_mean * 1.25:
        return {"verdict": "reboot_helpful",
                "text": "Loss is materially LOWER on nights the device is power cycled. "
                        "The device degrades while running -- consistent with a firmware "
                        "or memory fault. That is a direct argument for replacing it."}
    return {"verdict": "no_difference",
            "text": "No meaningful difference between the arms. The reboot is neither "
                    "helping nor hurting, which points at the line or the operator's "
                    "equipment rather than the modem. Ask for the line-side optical "
                    "readings."}


def format_analysis(result: dict) -> str:
    def line(label: str, s: dict) -> str:
        if not s.get("minutes"):
            return "  %-18s: no data" % label
        return ("  %-18s: %6d min | mean %6.2f%% | median %5.2f%% | p95 %6.2f%% | "
                "degraded %5.1f%% of minutes"
                % (label, s["minutes"], s["mean"] * 100, s["median"] * 100,
                   s["p95"] * 100, s["degraded_share"] * 100))

    out = ["A/B analysis of the nightly intervention",
           "seed=%d  since=%s  hour=%02d:00 %s"
           % (result["seed"], result["since"], result["hour"], result["timezone"]),
           "", "full 24h cycle",
           line("intervention", result["full_cycle"][REBOOT]),
           line("control", result["full_cycle"][CONTROL]),
           "", "first 12h after the intervention hour",
           line("intervention", result["first_12h"][REBOOT]),
           line("control", result["first_12h"][CONTROL]),
           "", "READING: " + result["reading"]["text"]]
    return "\n".join(out)
