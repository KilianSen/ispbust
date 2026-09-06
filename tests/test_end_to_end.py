"""End-to-end tests: the seams that would silently break the evidence chain.

Run with `pytest`, or `python -m pytest tests/ -v`.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ispbust.analysis import LinkData, analyse, paired_comparison
from ispbust.collectors import IcmpCollector
from ispbust.config import ConfigError, Thresholds, load_probe_config, load_site_config
from ispbust.demo import build_demo, generate
from ispbust.experiment import arm_for, plan
from ispbust.report.builder import build_report
from ispbust.report.strings import Strings
from ispbust.server import make_server, serve_in_background
from ispbust.storage import Store

# ------------------------------------------------------------- fping parsing


def test_fping_parse_marks_losses():
    out = IcmpCollector.parse(
        "1.1.1.1 : 12.3 11.9 - 12.1 -\n"
        "8.8.8.8 : 14.0 13.8 13.9 14.2 14.1\n"
        "62.156.128.1 : - - - - -\n")
    assert out["1.1.1.1"] == [12.3, 11.9, None, 12.1, None]
    assert out["8.8.8.8"].count(None) == 0
    assert out["62.156.128.1"] == [None] * 5


@pytest.mark.parametrize("junk", ["", "garbage\n", "1.1.1.1 :\n", "no colon\n", ": 1 2\n"])
def test_fping_parse_survives_junk(junk):
    IcmpCollector.parse(junk)


def test_rtt_stats():
    s = IcmpCollector.rtt_stats([10.0, 12.0, 11.0, 50.0])
    assert s["min"] == 10.0 and s["max"] == 50.0
    assert s["avg"] == pytest.approx(20.75)
    assert IcmpCollector.rtt_stats([])["avg"] is None


# ------------------------------------------------------------------ analysis


def _rows(minutes):
    """minutes: [(iso_minute, loss_ratio)] -> icmp-shaped dicts."""
    rows = []
    for m, loss in minutes:
        sent = 60
        lost = int(round(sent * loss))
        rows.append({"ts": m + ":00.000Z", "target": "1.1.1.1", "role": "anchor",
                     "sent": sent, "lost": lost, "loss_ratio": loss,
                     "rtt_avg": 10.0, "rtt_max": 20.0, "rtt_p95": 15.0})
    return rows


def _link(minutes, wan="wan-a", kind="under_test"):
    return LinkData(wan, wan, kind, _rows(minutes), Thresholds())


def test_outage_runs_exclude_isolated_minutes():
    data = [("2026-09-01T10:%02d" % i, 0.5) for i in range(4)]
    data += [("2026-09-01T10:%02d" % i, 0.0) for i in range(4, 8)]
    data += [("2026-09-01T10:%02d" % i, 0.9) for i in range(8, 10)]
    data += [("2026-09-01T10:%02d" % i, 0.0) for i in range(10, 20)]
    data += [("2026-09-01T10:20", 0.6)]  # isolated -- must not count
    data += [("2026-09-01T10:%02d" % i, 0.0) for i in range(21, 25)]

    outages = _link(data).outages(min_minutes=2)
    assert len(outages) == 2
    assert outages[0]["minutes"] == 4
    assert outages[1]["minutes"] == 2
    assert outages[1]["avg_loss"] == pytest.approx(0.9)


def test_paired_comparison_isolates_the_link_under_test():
    primary = _link([("2026-09-01T11:%02d" % i, 1.0) for i in range(3)])
    control = _link([("2026-09-01T11:%02d" % i, 0.0) for i in range(3)], wan="wan-b", kind="control")
    c = paired_comparison(primary, control)
    assert c["common_minutes"] == 3
    assert c["primary_only_bad"] == 3
    assert c["primary_blackout_control_fine"] == 3
    assert c["control_only_bad"] == 0


def test_empty_link_does_not_explode():
    link = _link([])
    assert link.outages() == []
    assert link.totals() == (0, 0)
    assert link.loss_ratio() == 0.0


# -------------------------------------------------------------------- config


def test_site_config_requires_a_link_under_test(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text(
        "site:\n  name: x\nprobes:\n  - id: a\n    kind: control\n    db: /tmp/a.sqlite\n",
        encoding="utf-8")
    with pytest.raises(ConfigError):
        load_site_config(path)


def test_experiment_requires_a_committed_seed(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text(
        "site:\n  name: x\n"
        "probes:\n  - id: a\n    kind: under_test\n    db: /tmp/a.sqlite\n"
        "experiment:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="seed"):
        load_site_config(path)


def test_probe_config_rejects_a_useless_window(tmp_path):
    path = tmp_path / "probe.yaml"
    path.write_text(
        "wan:\n  id: a\n  label: A\n"
        "icmp:\n  window_seconds: 2\n  targets:\n    - host: 1.1.1.1\n      role: anchor\n",
        encoding="utf-8")
    with pytest.raises(ConfigError, match="window_seconds"):
        load_probe_config(path)


def test_example_configs_are_valid():
    root = Path(__file__).resolve().parent.parent
    for name in ("probe.under-test.yaml", "probe.control.yaml"):
        load_probe_config(root / "examples" / name)
    load_site_config(root / "examples" / "site.yaml")


# ------------------------------------------------------------------ HTTP API


@pytest.fixture
def probe_server(tmp_path):
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")
    store.insert("icmp", {
        "ts": "2026-09-01T10:00:00.000Z", "wan": "wan-a", "target": "1.1.1.1",
        "role": "anchor", "sent": 60, "lost": 3, "loss_ratio": 0.05,
        "rtt_min": 1.0, "rtt_avg": 2.0, "rtt_max": 3.0, "rtt_p95": 2.5,
        "rtt_stddev": 0.4, "window_s": 60,
    })
    # Bind the loopback address the tests actually connect to. Listening on
    # 0.0.0.0 made connection setup intermittently time out under load.
    httpd = make_server(store, "wan-a", "Link A", "under_test", 0,
                        token="secret", bind="127.0.0.1")
    serve_in_background(httpd)
    port = httpd.server_address[1]
    yield "http://127.0.0.1:%d" % port
    httpd.shutdown()
    store.close()


def _get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read()


def test_health_and_info_need_no_token(probe_server):
    status, body = _get(probe_server + "/health")
    assert status == 200 and b"ok" in body

    status, body = _get(probe_server + "/info")
    info = json.loads(body)
    assert info["wan"]["id"] == "wan-a"
    assert info["store"]["tables"]["icmp"]["rows"] == 1


def test_metrics_endpoint_serves_prometheus(probe_server):
    status, body = _get(probe_server + "/metrics")
    assert status == 200
    assert b"ispbust" in body


def test_export_rejects_a_missing_token(probe_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(probe_server + "/export/sqlite")
    assert exc.value.code == 401


def test_export_returns_a_usable_database(probe_server, tmp_path):
    status, body = _get(probe_server + "/export/sqlite", token="secret")
    assert status == 200
    out = tmp_path / "pulled.sqlite"
    out.write_bytes(body)

    import sqlite3
    con = sqlite3.connect(str(out))
    assert con.execute("SELECT COUNT(*) FROM icmp").fetchone()[0] == 1
    con.close()


def test_export_date_filter_excludes_everything_outside_the_range(probe_server, tmp_path):
    _, body = _get(probe_server + "/export/sqlite?from=2020-01-01&to=2020-01-02", token="secret")
    out = tmp_path / "filtered.sqlite"
    out.write_bytes(body)

    import sqlite3
    con = sqlite3.connect(str(out))
    assert con.execute("SELECT COUNT(*) FROM icmp").fetchone()[0] == 0
    con.close()


# ------------------------------------------------------------- retrieval


def test_fetch_over_http_feeds_the_report(tmp_path, probe_server):
    from ispbust.config import ProbeRef
    from ispbust.retrieve import fetch_probe, probe_info

    ref = ProbeRef(id="wan-a", label="Link A", kind="under_test",
                   url=probe_server, token="secret")
    info = probe_info(ref)
    assert info["wan"]["id"] == "wan-a"

    path = fetch_probe(ref, tmp_path / "data")
    assert path.exists() and path.stat().st_size > 0


def test_fetch_with_a_bad_token_fails_clearly(tmp_path, probe_server):
    from ispbust.config import ProbeRef
    from ispbust.retrieve import RetrievalError, fetch_probe

    ref = ProbeRef(id="wan-a", label="A", kind="under_test", url=probe_server, token="wrong")
    with pytest.raises(RetrievalError, match="token"):
        fetch_probe(ref, tmp_path / "data")


# ---------------------------------------------------------------- reporting


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    return build_demo(out, days=3)


def test_analysis_finds_the_planted_fault(demo):
    site = load_site_config(demo["site"])
    a = analyse(site, demo["databases"], demo["date_from"], demo["date_to"])
    h = a.headline()
    assert h["measured_minutes"] == 3 * 24 * 60
    assert h["loss"] > 0.01
    assert h["control_loss"] < h["loss"] / 10
    assert h["primary_only_bad"] > 0
    assert a.has_first_hop
    assert a.first_hop_ips


@pytest.mark.parametrize("lang", Strings().available())
def test_report_renders_in_every_language(demo, lang):
    site = load_site_config(demo["site"])
    a = analyse(site, demo["databases"], demo["date_from"], demo["date_to"])
    html = build_report(a, lang)
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "<svg" in html
    assert 'lang="%s"' % lang in html
    # An unresolved placeholder means a string is missing a parameter.
    assert "{" not in html.split("<style>")[0]


def test_report_without_a_control_still_builds(tmp_path):
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) \
        - timedelta(days=2)
    db = generate(tmp_path / "solo.sqlite", "solo", start, 2, faulty=True, seed=7)
    site_path = tmp_path / "site.yaml"
    site_path.write_text(
        "site:\n  name: solo\n  timezone: UTC\n  language: en\n"
        "probes:\n  - id: solo\n    label: Solo\n    kind: under_test\n    db: %s\n"
        % db.as_posix(), encoding="utf-8")

    site = load_site_config(site_path)
    a = analyse(site, {"solo": db}, start.strftime("%Y-%m-%d"),
                (start + timedelta(days=1)).strftime("%Y-%m-%d"))
    assert not a.has_control
    html = build_report(a)
    assert "<svg" in html


# --------------------------------------------------------------- experiment


def test_experiment_schedule_is_deterministic_and_balanced():
    from datetime import date

    entries = plan(seed=20260904, days=28, start=date(2026, 9, 5))
    again = plan(seed=20260904, days=28, start=date(2026, 9, 5))
    assert entries == again

    reboot = sum(1 for e in entries if e["arm"] == "reboot")
    assert reboot == 14, "pairs should balance the arms exactly"


def test_experiment_arms_differ_between_seeds():
    from datetime import date

    days = [date(2026, 9, 5) + timedelta(days=i) for i in range(40)]
    a = [arm_for(d, 1) for d in days]
    b = [arm_for(d, 2) for d in days]
    assert a != b


# ------------------------------------------------------- discovery guards


def _discovery(tmp_path, targets, via="1.1.1.1", hop=2):

    from ispbust.collectors import DiscoveryCollector, ProbeContext
    from ispbust.config import DiscoveryConfig, IcmpConfig, ProbeConfig, Target
    from ispbust.metrics import Labels

    cfg = ProbeConfig(
        wan_id="wan-a", label="A", data_dir=tmp_path,
        icmp=IcmpConfig(targets=[Target(host=h, role=r) for h, r in targets]),
        discovery=DiscoveryConfig(via=via, hop=hop),
    )
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("wan-a", "under_test"),
                       stop=threading.Event())
    return DiscoveryCollector(ctx), ctx, store


def test_discovery_rejects_the_destination_as_first_hop(tmp_path):
    """A path shorter than `hop` returns the anchor itself, not an ISP edge."""
    collector, ctx, store = _discovery(tmp_path, [("1.1.1.1", "anchor")])
    assert collector.acceptable("1.1.1.1") is False
    assert ctx.targets() == list(ctx.cfg.icmp.targets), "target set must be untouched"
    store.close()


def test_discovery_rejects_a_host_already_configured(tmp_path):
    """Adopting it would silently reassign that target's role."""
    collector, ctx, store = _discovery(tmp_path, [("8.8.8.8", "anchor")], via="1.1.1.1")
    assert collector.acceptable("8.8.8.8") is False
    store.close()


def test_discovery_accepts_a_genuine_operator_hop(tmp_path):
    collector, ctx, store = _discovery(tmp_path, [("1.1.1.1", "anchor")])
    assert collector.acceptable("62.156.128.1") is True
    store.close()


def test_disabled_traceroute_also_disables_event_captures(tmp_path):
    """`enabled: false` must mean no traceroutes at all.

    CI caught the opposite: a probe with traceroute disabled still fired
    event-triggered captures, because only the scheduled loop consulted the
    flag.
    """
    import threading

    from ispbust.collectors import IcmpCollector, ProbeContext
    from ispbust.config import IcmpConfig, ProbeConfig, Target, TraceConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(
        wan_id="wan-a", label="A", data_dir=tmp_path,
        icmp=IcmpConfig(targets=[Target(host="1.1.1.1", role="anchor")], event_loss_ratio=0.01),
        trace=TraceConfig(enabled=False, on_event=True),
    )
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("wan-a", "under_test"),
                       stop=threading.Event())
    collector = IcmpCollector(ctx)

    fired = []
    original = threading.Thread
    try:
        threading.Thread = lambda *a, **k: fired.append(k.get("name")) or original(*a, **k)
        collector.check_event("1.1.1.1", cfg.icmp.targets[0], 0.5,
                              {"avg": 10.0, "max": 20.0, "p95": 15.0})
    finally:
        threading.Thread = original

    assert fired == [], "no traceroute thread should start when traceroute is disabled"
    events = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert events > 0, "the loss event itself must still be recorded"
    store.close()


def test_discovery_skips_a_hop_that_does_not_answer_echo(tmp_path, monkeypatch):
    """Answering traceroute is not the same as answering ping.

    Found on a real line: the operator's CGNAT gateway replies to TTL-exceeded
    (so mtr shows it at 0.0% loss) but drops echo requests addressed to itself.
    Probing it would record a permanent 100% loss and put a false claim in the
    report.
    """
    from ispbust import collectors

    collector, ctx, store = _discovery(tmp_path, [("1.1.1.1", "anchor")])

    # mtr finds a hop; fping gets nothing back from it.
    monkeypatch.setattr(collectors.TraceCollector, "mtr",
                        lambda self, target, cycles: [{"count": 2, "host": "100.124.1.27"}])

    # The probe must ask fping for per-packet output (-C). With the lowercase
    # -c it gets only a summary line, which the parser reads as "no replies",
    # so every hop would look silent and the check would reject all of them --
    # a bug that survived the first version of this test because the mock
    # returned the format the code was supposed to use rather than the one it
    # actually asked for.
    seen = {}

    def fake_run(cmd, timeout):
        seen["cmd"] = cmd
        return (1, "", "100.124.1.27 : - - - - -\n")

    monkeypatch.setattr(collectors, "run_cmd", fake_run)

    collector.run_once()

    assert "-C" in seen["cmd"], "must request per-packet output, not a summary"
    assert ctx.dynamic_targets == [], "a silent hop must not become a probe target"
    kinds = [r[0] for r in store.db.execute("SELECT kind FROM markers")]
    assert "upstream_hop_no_echo" in kinds, "the reason must be recorded"

    # Repeating must not spam the marker table.
    collector.run_once()
    again = [r[0] for r in store.db.execute(
        "SELECT kind FROM markers WHERE kind='upstream_hop_no_echo'")]
    assert len(again) == 1
    store.close()


def test_discovery_adopts_a_hop_that_does_answer(tmp_path, monkeypatch):
    from ispbust import collectors

    collector, ctx, store = _discovery(tmp_path, [("1.1.1.1", "anchor")])
    monkeypatch.setattr(collectors.TraceCollector, "mtr",
                        lambda self, target, cycles: [{"count": 2, "host": "62.156.128.1"}])
    monkeypatch.setattr(collectors, "run_cmd",
                        lambda cmd, timeout: (0, "", "62.156.128.1 : 1.2 1.3 1.1 1.4 1.2\n"))

    collector.run_once()

    assert [t.host for t in ctx.dynamic_targets] == ["62.156.128.1"]
    assert ctx.dynamic_targets[0].role == "isp_first_hop"
    store.close()


def test_make_server_waits_for_a_port_still_in_use(tmp_path, monkeypatch):
    """A restart must not cost a respawn cycle -- that is a gap in the record.

    Driven through the constructor rather than a real socket race: Windows lets
    SO_REUSEADDR rebind a live port, so contention cannot be reproduced
    portably, and a real race makes the rest of the suite flaky.
    """
    import errno

    from ispbust import server as server_mod

    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")
    attempts = []
    real = server_mod.ThreadingHTTPServer

    def flaky(address, handler):
        attempts.append(address)
        if len(attempts) < 3:
            raise OSError(errno.EADDRINUSE, "Address already in use")
        return real(("127.0.0.1", 0), handler)

    monkeypatch.setattr(server_mod, "ThreadingHTTPServer", flaky)
    monkeypatch.setattr(server_mod.time, "sleep", lambda _s: None)

    httpd = server_mod.make_server(store, "wan-a", "A", "under_test", 9109,
                                   token=None, bind_retry_seconds=30)
    assert len(attempts) == 3, "should have retried until the port freed up"
    httpd.server_close()
    store.close()


def test_make_server_gives_up_when_the_port_never_frees(tmp_path, monkeypatch):
    import errno

    from ispbust import server as server_mod

    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")

    def always_busy(address, handler):
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(server_mod, "ThreadingHTTPServer", always_busy)
    monkeypatch.setattr(server_mod.time, "sleep", lambda _s: None)

    with pytest.raises(OSError):
        server_mod.make_server(store, "wan-a", "A", "under_test", 9109,
                               token=None, bind_retry_seconds=1)
    store.close()


def test_make_server_does_not_swallow_other_errors(tmp_path, monkeypatch):
    """Only EADDRINUSE is worth waiting on; anything else must surface at once."""
    import errno

    from ispbust import server as server_mod

    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "wan-a")

    def denied(address, handler):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(server_mod, "ThreadingHTTPServer", denied)
    with pytest.raises(OSError) as exc:
        server_mod.make_server(store, "wan-a", "A", "under_test", 80,
                               token=None, bind_retry_seconds=30)
    assert exc.value.errno == errno.EACCES
    store.close()


# ------------------------------------------------------- dual-stack support


def test_fping_parse_handles_ipv6_addresses():
    """Splitting on the first colon would truncate every IPv6 target."""
    out = IcmpCollector.parse(
        "1.1.1.1                  : 12.3 11.9 - 12.1\n"
        "2606:4700:4700::1111     : 14.0 13.8 13.9 14.2\n"
        "2001:4860:4860::8888     : - - - -\n")
    assert out["2606:4700:4700::1111"] == [14.0, 13.8, 13.9, 14.2]
    assert out["2001:4860:4860::8888"] == [None] * 4
    assert out["1.1.1.1"][2] is None


def test_icmp_family_detection_and_flags(tmp_path):
    import threading

    from ispbust.collectors import IcmpCollector, ProbeContext
    from ispbust.config import IcmpConfig, ProbeConfig, Target
    from ispbust.metrics import Labels

    assert IcmpCollector.family_of("1.1.1.1") == "ipv4"
    assert IcmpCollector.family_of("2606:4700:4700::1111") == "ipv6"

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      icmp=IcmpConfig(targets=[Target(host="1.1.1.1", role="anchor")]),
                      source_ip="10.0.0.9")
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    c = IcmpCollector(ctx)

    v4 = c.command(["1.1.1.1"], "ipv4")
    v6 = c.command(["2606:4700:4700::1111"], "ipv6")
    assert "-4" in v4 and "-6" not in v4
    assert "-6" in v6 and "-4" not in v6
    # An IPv4 source address cannot be bound on an IPv6 socket.
    assert "-S" in v4 and "-S" not in v6
    store.close()


def test_reach_flags_a_family_that_resolves_but_cannot_connect(tmp_path, monkeypatch):
    """The exact fault that started this: AAAA present, IPv6 unroutable.

    ICMP to IPv4 anchors stays perfectly clean, so nothing else in the tool
    notices, while a browser trying IPv6 first fails to load the site at all.
    """
    import threading

    from ispbust.collectors import ProbeContext, ReachCollector
    from ispbust.config import ProbeConfig, ReachConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(
        wan_id="w", label="w", data_dir=tmp_path,
        reach=ReachConfig(targets=[{"host": "claude.ai", "port": 443}]),
    )
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = ReachCollector(ctx)

    def fake_check(host, port, tls, family_name):
        if family_name == "ipv4":
            return {"host": host, "family": "ipv4", "address": "160.79.104.10",
                    "resolved": 1, "ok": 1, "error": None}
        return {"host": host, "family": "ipv6", "address": "2607:6bc0::10",
                "resolved": 1, "ok": 0, "error": "OSError: [Errno 101] Network unreachable"}

    monkeypatch.setattr(collector, "check_family", fake_check)
    collector.run_once()

    events = list(store.db.execute("SELECT kind, role, target, detail FROM events"))
    assert len(events) == 1, events
    kind, role, target, detail = events[0]
    assert kind == "address_family_broken"
    assert role == "ipv6"
    assert target == "claude.ai"
    assert "ipv4" in detail
    store.close()


def test_reach_stays_quiet_when_both_families_work(tmp_path, monkeypatch):
    import threading

    from ispbust.collectors import ProbeContext, ReachCollector
    from ispbust.config import ProbeConfig, ReachConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      reach=ReachConfig(targets=[{"host": "example.com"}]))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = ReachCollector(ctx)
    monkeypatch.setattr(collector, "check_family",
                        lambda h, p, t, f: {"host": h, "family": f, "resolved": 1, "ok": 1})
    collector.run_once()
    assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    store.close()


def test_reach_ignores_a_family_with_no_records(tmp_path, monkeypatch):
    """An IPv4-only site is not a fault, and must not be reported as one."""
    import threading

    from ispbust.collectors import ProbeContext, ReachCollector
    from ispbust.config import ProbeConfig, ReachConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      reach=ReachConfig(targets=[{"host": "v4only.example"}]))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = ReachCollector(ctx)

    def fake_check(host, port, tls, family_name):
        if family_name == "ipv4":
            return {"host": host, "family": "ipv4", "resolved": 1, "ok": 1}
        return {"host": host, "family": "ipv6", "resolved": 0, "ok": None,
                "error": "no AAAA record"}

    monkeypatch.setattr(collector, "check_family", fake_check)
    collector.run_once()
    assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    store.close()


def test_migration_adds_columns_to_an_older_database(tmp_path):
    """A probe that has been collecting for weeks must keep its history."""
    import sqlite3

    from ispbust.storage import migrate

    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE icmp (ts TEXT NOT NULL, wan TEXT, target TEXT, role TEXT, "
                "sent INTEGER, lost INTEGER, loss_ratio REAL, rtt_min REAL, rtt_avg REAL, "
                "rtt_max REAL, rtt_p95 REAL, rtt_stddev REAL, window_s INTEGER)")
    con.execute("INSERT INTO icmp (ts, wan, target, role, sent, lost) "
                "VALUES ('2026-09-01T10:00:00.000Z','w','1.1.1.1','anchor',60,0)")
    con.commit()

    added = migrate(con)
    assert "icmp.family" in added
    cols = {r[1] for r in con.execute("PRAGMA table_info(icmp)")}
    assert "family" in cols
    assert con.execute("SELECT COUNT(*) FROM icmp").fetchone()[0] == 1, "history must survive"
    assert migrate(con) == [], "migration must be idempotent"
    con.close()


def test_reach_resolution_does_not_trust_the_os_family_filter(tmp_path, monkeypatch):
    """A host with broken IPv6 must not look like a site without AAAA.

    Windows returns WSANO_DATA for an AAAA lookup when it has no usable IPv6
    route, so getaddrinfo(AF_INET6) reports "no such record" on exactly the
    machine that is broken. Resolution therefore goes to DNS directly.
    """
    import socket
    import threading

    from ispbust.collectors import ProbeContext, ReachCollector
    from ispbust.config import ProbeConfig, ReachConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      reach=ReachConfig(targets=[{"host": "claude.ai"}]))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = ReachCollector(ctx)

    def exploding_getaddrinfo(*a, **k):
        raise OSError(11004, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", exploding_getaddrinfo)

    class FakeRecord:
        def __init__(self, address):
            self.address = address

    def fake_resolve(name, rdtype):
        return [FakeRecord("2607:6bc0::10" if rdtype == "AAAA" else "160.79.104.10")]

    from ispbust import collectors
    monkeypatch.setattr(collectors.dns.resolver, "resolve", fake_resolve)

    address, why = collector.resolve("claude.ai", "ipv6")
    assert address == "2607:6bc0::10", "must ask DNS, not the OS resolver"
    assert why is None
    store.close()


def test_reach_reports_a_genuinely_absent_record_as_absent(tmp_path, monkeypatch):
    import threading

    from ispbust import collectors
    from ispbust.collectors import ProbeContext, ReachCollector
    from ispbust.config import ProbeConfig, ReachConfig
    from ispbust.metrics import Labels

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      reach=ReachConfig(targets=[{"host": "v4only.example"}]))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = ReachCollector(ctx)

    def no_answer(name, rdtype):
        raise collectors.dns.resolver.NoAnswer()

    monkeypatch.setattr(collectors.dns.resolver, "resolve", no_answer)
    address, why = collector.resolve("v4only.example", "ipv6")
    assert address is None
    assert why == "no AAAA record"
    store.close()


def test_icmp_families_are_measured_concurrently(tmp_path):
    """Sequential family runs would halve the sampling rate.

    Each fping run blocks for a full window, so running IPv4 then IPv6 would
    produce one row per target every two minutes instead of every minute --
    quietly breaking the cadence every figure in the report rests on.
    """
    import threading
    import time

    from ispbust.collectors import IcmpCollector, ProbeContext
    from ispbust.config import IcmpConfig, ProbeConfig, Target
    from ispbust.metrics import Labels

    cfg = ProbeConfig(
        wan_id="w", label="w", data_dir=tmp_path,
        icmp=IcmpConfig(window_seconds=10, targets=[
            Target(host="1.1.1.1", role="anchor"),
            Target(host="2606:4700:4700::1111", role="anchor_v6"),
        ]),
    )
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = IcmpCollector(ctx)

    spans = {}

    def fake_measure(family, by_host, ts):
        start = time.monotonic()
        time.sleep(0.4)
        spans[family] = (start, time.monotonic())

    collector.measure = fake_measure
    started = time.monotonic()
    collector.run_once()
    elapsed = time.monotonic() - started

    assert set(spans) == {"ipv4", "ipv6"}, spans
    assert elapsed < 0.75, "families ran one after another (%.2fs)" % elapsed
    # They must actually overlap, not merely finish quickly.
    (a_start, a_end), (b_start, b_end) = spans["ipv4"], spans["ipv6"]
    assert a_start < b_end and b_start < a_end, "family runs did not overlap"
    store.close()


def test_icmp_single_family_takes_the_direct_path(tmp_path):
    """No thread churn when there is nothing to parallelise."""
    import threading

    from ispbust.collectors import IcmpCollector, ProbeContext
    from ispbust.config import IcmpConfig, ProbeConfig, Target
    from ispbust.metrics import Labels

    cfg = ProbeConfig(wan_id="w", label="w", data_dir=tmp_path,
                      icmp=IcmpConfig(targets=[Target(host="1.1.1.1", role="anchor")]))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "w")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("w", "under_test"),
                       stop=threading.Event())
    collector = IcmpCollector(ctx)

    seen = []
    collector.measure = lambda family, by_host, ts: seen.append((family, threading.current_thread().name))
    collector.run_once()

    assert len(seen) == 1 and seen[0][0] == "ipv4"
    assert seen[0][1] == threading.current_thread().name, "should run inline"
    store.close()
