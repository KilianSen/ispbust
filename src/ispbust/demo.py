"""Synthetic data, so the report can be judged before any real collection.

Two uses: seeing what the deliverable looks like before committing a fortnight
to measuring, and giving the test suite something deterministic to chew on.

The fault it models is the awkward one -- a link that degrades with uptime
*and* misbehaves for hours after a restart -- because that is the case where
the report has to do real work to separate the two.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .storage import open_db

ANCHORS = [("1.1.1.1", "anchor"), ("8.8.8.8", "anchor"),
           ("9.9.9.9", "anchor"), ("194.25.0.60", "anchor_de")]
FIRST_HOP = "62.156.128.1"
ISP_RESOLVERS = [("80.69.96.12", "isp_resolver"), ("80.69.100.12", "isp_resolver")]
PUBLIC_RESOLVERS = [("1.1.1.1", "public_control"), ("9.9.9.9", "public_control")]
NAMES = ["example.com", "heise.de", "google.com", "cloudflare.com", "wikipedia.org"]

# Built with str.format rather than %-formatting: the payload is full of
# literal "Loss%" keys, which %-formatting would try to interpret.
TRACE_HOPS = (
    '[{{"count":1,"host":"10.0.61.1","Loss%":0.0,"Avg":0.4,"Wrst":1.1}},'
    '{{"count":2,"host":"{hop}","Loss%":31.0,"Avg":4.2,"Wrst":180.3}},'
    '{{"count":3,"host":"62.156.130.5","Loss%":33.0,"Avg":6.9,"Wrst":210.7}},'
    '{{"count":4,"host":"1.1.1.1","Loss%":34.0,"Avg":9.1,"Wrst":240.2}}]'
).format(hop=FIRST_HOP)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fault_profile(local_hour: int, rng: random.Random) -> float:
    """Loss for one minute on the faulty link.

    Heavy instability for the nine hours after the 03:00 restart, a clean
    middle of the day, then a slow climb as uptime accumulates.
    """
    since_restart = (local_hour - 3) % 24
    if since_restart < 9:
        if rng.random() < 0.06:
            return 1.0
        base = 0.28 if rng.random() < 0.45 else 0.04
    elif since_restart < 16:
        base = 0.005
    else:
        base = 0.02 + 0.004 * (since_restart - 16)
    return min(1.0, max(0.0, base + rng.gauss(0, 0.015)))


def _rtt(loss: float, base: float, rng: random.Random) -> tuple:
    if loss >= 0.999:
        return (None, None, None, None, None)
    jitter = 1 + loss * 12
    avg = base * jitter + abs(rng.gauss(0, 1.5))
    return (round(max(0.4, avg - 1.2), 3), round(avg, 3), round(avg + 8 * jitter, 3),
            round(avg + 3 * jitter, 3), round(2 * jitter, 3))


def generate(path: Path, wan_id: str, start: datetime, days: int,
             faulty: bool, seed: int, utc_offset_hours: int = 2) -> Path:
    """Write one synthetic probe database."""
    if path.exists():
        path.unlink()
    con = open_db(path)
    rng = random.Random(seed)

    targets = list(ANCHORS)
    resolvers = list(PUBLIC_RESOLVERS)
    if faulty:
        targets.append((FIRST_HOP, "isp_first_hop"))
        resolvers = ISP_RESOLVERS + PUBLIC_RESOLVERS

    icmp_rows, dns_rows = [], []
    for i in range(days * 24 * 60):
        moment = start + timedelta(minutes=i)
        ts = _iso(moment)
        local_hour = (moment.hour + utc_offset_hours) % 24
        loss = fault_profile(local_hour, rng) if faulty else max(0.0, rng.gauss(0.002, 0.004))

        for host, role in targets:
            # The operator's own first hop sees slightly less loss than the
            # far anchors -- the fault is upstream of it, not at it.
            target_loss = loss * (0.85 if role == "isp_first_hop" else 1.0)
            sent = 60
            lost = min(sent, int(round(sent * target_loss)))
            base = 1.8 if role == "isp_first_hop" else (6.5 if faulty else 38.0)
            mn, avg, mx, p95, sd = _rtt(target_loss, base, rng)
            icmp_rows.append((ts, wan_id, host, role, sent, lost,
                              round(lost / sent, 6), mn, avg, mx, p95, sd, 60))

        if i % 15 == 0:
            for ip, role in resolvers:
                name = NAMES[(i // 15) % len(NAMES)]
                is_isp = role == "isp_resolver"
                fail_chance = (0.10 + loss * 0.5) if is_isp else (loss * 0.3)
                if rng.random() < fail_chance:
                    outcome, rcode, duration, answer = "timeout", "", 3.0, ""
                else:
                    outcome, rcode = "ok", "NOERROR"
                    duration = round(abs(rng.gauss(0.09 if is_isp else 0.03, 0.05)) + 0.005, 4)
                    answer = "93.184.216.34"
                dns_rows.append((ts, wan_id, ip, role, name, "A", outcome, rcode,
                                 duration, answer))

    con.executemany(
        "INSERT INTO icmp (ts,wan,target,role,sent,lost,loss_ratio,rtt_min,rtt_avg,"
        "rtt_max,rtt_p95,rtt_stddev,window_s) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", icmp_rows)
    con.executemany(
        "INSERT INTO dns (ts,wan,resolver,resolver_role,qname,qtype,outcome,rcode,"
        "duration_s,answer) VALUES (?,?,?,?,?,?,?,?,?,?)", dns_rows)
    if faulty:
        con.execute("INSERT INTO markers (ts,wan,kind,detail) VALUES (?,?,?,?)",
                    (_iso(start), wan_id, "upstream_hop", FIRST_HOP))
        con.execute("INSERT INTO trace (ts,wan,target,trigger,hops_json) VALUES (?,?,?,?,?)",
                    (_iso(start + timedelta(hours=5)), wan_id, "1.1.1.1", "event", TRACE_HOPS))
    con.commit()
    con.close()
    return path


SITE_TEMPLATE = """# Generated by `ispbust demo`. Edit freely.
site:
  name: demo
  timezone: Europe/Berlin
  language: {language}
  isp_name: "Example Fibre"
  customer_ref: "DEMO-12345"

probes:
  - id: {primary}
    label: "Fibre line (under test)"
    kind: under_test
    db: {primary_db}
  - id: {control}
    label: "Backup link (control)"
    kind: control
    db: {control_db}

thresholds:
  degraded_loss: 0.05
  blackout_loss: 0.999

experiment:
  enabled: true
  hour: 3
  seed: 20260904
  device_label: "fibre modem"
"""


def build_demo(out_dir: Path, days: int = 10, language: str = "en",
               primary: str = "wan-a", control: str = "wan-b") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    primary_db = out_dir / ("%s.sqlite" % primary)
    control_db = out_dir / ("%s.sqlite" % control)
    generate(primary_db, primary, start, days, faulty=True, seed=1)
    generate(control_db, control, start, days, faulty=False, seed=2)

    site_path = out_dir / "site.yaml"
    site_path.write_text(SITE_TEMPLATE.format(
        language=language, primary=primary, control=control,
        primary_db=primary_db.as_posix(), control_db=control_db.as_posix()),
        encoding="utf-8")

    return {
        "site": site_path,
        "databases": {primary: primary_db, control: control_db},
        "date_from": start.strftime("%Y-%m-%d"),
        "date_to": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
