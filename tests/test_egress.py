"""Tests for the egress check.

This is the check the rest of the tool leans on. A probe pinned to one uplink
whose router quietly fails it over keeps reporting a healthy line for the whole
outage it was deployed to record, and every figure derived from it is then
describing a different link. Observed on real hardware, which is why this
exists.
"""

from __future__ import annotations

import threading

import pytest

from ispbust.collectors import EgressCollector, ProbeContext
from ispbust.config import EgressConfig, ProbeConfig
from ispbust.metrics import Labels
from ispbust.storage import Store

DG = "94.31.74.53"
DG_PREFIX = "94.31.72.0/22"
STARLINK = "9.246.125.16"


def make(tmp_path, **egress_kwargs):
    cfg = ProbeConfig(wan_id="dg", label="DG", data_dir=tmp_path,
                      egress=EgressConfig(**egress_kwargs))
    store = Store(tmp_path / "p.sqlite", tmp_path / "raw", "dg")
    ctx = ProbeContext(cfg=cfg, store=store, labels=Labels("dg", "under_test"),
                       stop=threading.Event())
    return EgressCollector(ctx), ctx, store


def events(store, kind=None):
    sql = "SELECT kind, role, target, detail FROM events"
    params = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    return list(store.db.execute(sql, params))


def rows(store):
    return list(store.db.execute(
        "SELECT family, address, expected, ok, error FROM egress ORDER BY rowid"))


# ------------------------------------------------------------- observation


def test_observe_uses_the_first_endpoint_that_answers(tmp_path, monkeypatch):
    collector, _, store = make(tmp_path, endpoints={"ipv4": ["https://a", "https://b"]})
    calls = []

    class Resp:
        def __init__(self, body):
            self.body = body
        def read(self, n=None):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if request.full_url == "https://a":
            raise OSError("unreachable")
        return Resp(b" 94.31.74.53\n")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    address, endpoint, error = collector.observe("ipv4")
    assert address == DG
    assert endpoint == "https://b"
    assert error is None
    assert calls == ["https://a", "https://b"]
    store.close()


def test_observe_rejects_an_answer_of_the_wrong_family(tmp_path, monkeypatch):
    """An endpoint reached over IPv4 must not be recorded as an IPv6 egress."""
    collector, _, store = make(tmp_path, families=["ipv6"],
                               endpoints={"ipv6": ["https://only-v4-answered"]})

    class Resp:
        def read(self, n=None):
            return b"94.31.74.53"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Resp())
    address, _, error = collector.observe("ipv6")
    assert address is None
    assert error
    store.close()


# ---------------------------------------------------------------- matching


def test_configured_prefix_beats_a_learned_baseline(tmp_path):
    collector, _, store = make(tmp_path, expected_prefixes=[DG_PREFIX])
    store.set_meta("egress_baseline_ipv4", "9.246.125.0/24")
    nets = collector.expected_networks("ipv4")
    assert [str(n) for n in nets] == [DG_PREFIX]
    store.close()


def test_baseline_is_learned_once_and_persists(tmp_path, monkeypatch):
    collector, ctx, store = make(tmp_path)
    monkeypatch.setattr(collector, "observe", lambda family: (DG, "https://x", None))

    collector.check("ipv4")
    assert store.get_meta("egress_baseline_ipv4") == "94.31.74.0/24"
    assert rows(store)[0]["ok"] == 1
    assert events(store, "egress_unexpected") == []

    # A second observation inside the learned range must stay quiet.
    collector.check("ipv4")
    assert events(store, "egress_unexpected") == []
    store.close()


# -------------------------------------------------------------- the leak


def test_leak_to_the_other_uplink_raises_an_event(tmp_path, monkeypatch):
    """The real failure: WAN1 down, probe silently rides WAN2, data looks fine."""
    collector, _, store = make(tmp_path, expected_prefixes=[DG_PREFIX])
    monkeypatch.setattr(collector, "observe", lambda family: (STARLINK, "https://x", None))

    collector.check("ipv4")

    row = rows(store)[0]
    assert row["ok"] == 0
    assert row["address"] == STARLINK
    assert row["expected"] == DG_PREFIX

    found = events(store, "egress_unexpected")
    assert len(found) == 1
    assert STARLINK in found[0]["detail"]
    assert "failover" in found[0]["detail"]
    store.close()


def test_a_continuing_leak_is_not_re_reported_every_cycle(tmp_path, monkeypatch):
    collector, _, store = make(tmp_path, expected_prefixes=[DG_PREFIX])
    monkeypatch.setattr(collector, "observe", lambda family: (STARLINK, "https://x", None))

    for _ in range(4):
        collector.check("ipv4")

    assert len(events(store, "egress_unexpected")) == 1, "one event, not one per cycle"
    assert len(rows(store)) == 4, "but every observation is still recorded"
    assert all(r["ok"] == 0 for r in rows(store))
    store.close()


def test_recovery_is_reported(tmp_path, monkeypatch):
    collector, _, store = make(tmp_path, expected_prefixes=[DG_PREFIX])
    observed = [STARLINK, STARLINK, DG]
    monkeypatch.setattr(collector, "observe",
                        lambda family: (observed.pop(0), "https://x", None))

    for _ in range(3):
        collector.check("ipv4")

    assert len(events(store, "egress_unexpected")) == 1
    restored = events(store, "egress_restored")
    assert len(restored) == 1
    assert restored[0]["target"] == DG
    store.close()


def test_an_unreachable_endpoint_is_not_treated_as_a_leak(tmp_path, monkeypatch):
    """A dead link cannot answer. That is an outage, not a pin failure, and the
    other collectors already record it -- claiming a leak here would be wrong."""
    collector, _, store = make(tmp_path, expected_prefixes=[DG_PREFIX])
    monkeypatch.setattr(collector, "observe",
                        lambda family: (None, None, "no egress endpoint answered"))

    collector.check("ipv4")

    row = rows(store)[0]
    assert row["ok"] is None, "unknown, not failed"
    assert row["error"]
    assert events(store) == []
    store.close()


def test_expected_prefixes_of_the_wrong_family_are_ignored(tmp_path):
    collector, _, store = make(tmp_path, families=["ipv6"],
                               expected_prefixes=[DG_PREFIX, "2a00:6020::/32"])
    nets = collector.expected_networks("ipv6")
    assert [str(n) for n in nets] == ["2a00:6020::/32"]
    store.close()


def test_config_rejects_a_malformed_prefix(tmp_path):
    from ispbust.config import ConfigError, load_probe_config

    path = tmp_path / "probe.yaml"
    path.write_text(
        "wan:\n  id: a\n  label: A\n"
        "icmp:\n  targets:\n    - host: 1.1.1.1\n      role: anchor\n"
        "egress:\n  expected_prefixes: ['not-a-network']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a network"):
        load_probe_config(path)


# ------------------------------------------------- summarising for the report


def _row(ts, address, ok, expected="94.31.72.0/22"):
    return {"ts": ts, "family": "ipv4", "address": address,
            "expected": expected, "ok": ok}


def test_summary_counts_and_groups_leak_windows():
    from ispbust.analysis import egress_summary

    rows = [
        _row("2026-09-06T10:00:00.000Z", DG, 1),
        _row("2026-09-06T10:05:00.000Z", STARLINK, 0),
        _row("2026-09-06T10:10:00.000Z", STARLINK, 0),
        _row("2026-09-06T10:15:00.000Z", DG, 1),
        _row("2026-09-06T10:20:00.000Z", None, None),
        _row("2026-09-06T10:25:00.000Z", STARLINK, 0),
    ]
    s = egress_summary(rows)
    assert s["checks"] == 6
    assert s["confirmed"] == 2
    assert s["leaked"] == 3
    assert s["unknown"] == 1
    assert s["confirmed_ratio"] == pytest.approx(2 / 5), "unknown excluded from the ratio"
    assert len(s["windows"]) == 2, "the gap of confirmed checks splits the windows"
    assert s["windows"][0]["checks"] == 2
    assert s["windows"][0]["address"] == STARLINK
    assert s["expected"] == "94.31.72.0/22"


def test_summary_of_a_clean_period_has_no_windows():
    from ispbust.analysis import egress_summary

    s = egress_summary([_row("2026-09-06T10:0%d:00.000Z" % i, DG, 1) for i in range(5)])
    assert s["leaked"] == 0
    assert s["windows"] == []
    assert s["confirmed_ratio"] == 1.0


def test_summary_of_nothing_does_not_divide_by_zero():
    from ispbust.analysis import egress_summary

    s = egress_summary([])
    assert s["checks"] == 0
    assert s["confirmed_ratio"] is None


def test_report_states_the_leak_prominently(tmp_path):
    """A reader must be told the data is about a different link before believing it."""
    from ispbust.analysis import analyse, egress_summary
    from ispbust.config import load_site_config
    from ispbust.demo import build_demo
    from ispbust.report.builder import build_report

    info = build_demo(tmp_path, days=2)
    site = load_site_config(info["site"])
    a = analyse(site, info["databases"], info["date_from"], info["date_to"])

    a.egress = egress_summary([
        _row("2026-09-06T10:00:00.000Z", DG, 1),
        _row("2026-09-06T10:05:00.000Z", STARLINK, 0),
        _row("2026-09-06T10:10:00.000Z", STARLINK, 0),
    ])

    for lang in ("en", "de"):
        html = build_report(a, lang)
        assert "9.246.125.16" in html, "the offending address must appear"
        assert "94.31.72.0/22" in html, "so must what was expected"
        heading = "Integrity of the measurement" if lang == "en" else "Integrität der Messung"
        assert heading in html
        # It has to come before the daily figures, not be buried at the end.
        daily = "Daily breakdown" if lang == "en" else "Tägliche Auswertung"
        assert html.index(heading) < html.index(daily)


def test_report_omits_the_section_when_nothing_was_checked(tmp_path):
    from ispbust.analysis import analyse
    from ispbust.config import load_site_config
    from ispbust.demo import build_demo
    from ispbust.report.builder import build_report

    info = build_demo(tmp_path, days=2)
    site = load_site_config(info["site"])
    a = analyse(site, info["databases"], info["date_from"], info["date_to"])
    a.egress = {}
    assert "Integrity of the measurement" not in build_report(a, "en")
