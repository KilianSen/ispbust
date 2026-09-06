"""Tests for the automatic assessment.

These rules state conclusions in a document that goes to an operator, so the
thresholds they turn on are worth pinning down. The cases below are the ones
that matter: the fault is isolated to the link, the fault is inside the
operator's network, the pattern says congestion rather than hardware, and the
several ways the tool must decline to conclude anything.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ispbust.assessment import CRITICAL, GOOD, WARNING, assess


class FakeLink:
    def __init__(self, loss=0.0, first_hop=0.0, minutes=4320,
                 degraded=0, blackout=0, label="Line under test"):
        self._loss = loss
        self._first_hop = first_hop
        self._minutes = minutes
        self.degraded_minutes = degraded
        self.blackout_minutes = blackout
        self.label = label

    def loss_ratio(self, which="anchor"):
        return self._first_hop if which == "first_hop" else self._loss

    def measured_minutes(self, which="anchor"):
        return self._minutes


def analysis(**kwargs):
    primary = kwargs.pop("primary", FakeLink())
    base = {
        "primary": primary,
        "controls": [],
        "comparison": {},
        "has_control": False,
        "has_first_hop": False,
        "first_hop_ips": [],
        "outages": [],
        "hour_profile": [],
        "cycle": [],
        "dns": {},
        "reach_broken": [],
        "egress": {},
        "site": SimpleNamespace(experiment=SimpleNamespace(device_label="modem")),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def keys(findings):
    return [f.key for f in findings]


def one(findings, key):
    found = [f for f in findings if f.key == key]
    assert found, "expected %s, got %s" % (key, keys(findings))
    return found[0]


# --------------------------------------------------------------- integrity


def test_a_leak_is_reported_and_ranks_first():
    a = analysis(egress={
        "checks": 10, "confirmed": 4, "leaked": 6, "unknown": 0,
        "windows": [{"address": "9.246.125.16", "checks": 6}],
        "expected": "94.31.72.0/22", "confirmed_ratio": 0.4,
    })
    findings = assess(a)
    assert findings[0].key == "integrity_leaked", "nothing outranks invalid data"
    assert findings[0].severity == CRITICAL
    assert findings[0].params["address"] == "9.246.125.16"


def test_a_confirmed_pin_is_reported_as_good():
    a = analysis(egress={"checks": 12, "confirmed": 12, "leaked": 0, "unknown": 0,
                         "windows": [], "expected": "94.31.72.0/22", "confirmed_ratio": 1.0})
    assert one(assess(a), "integrity_confirmed").severity == GOOD


def test_no_egress_checks_is_flagged_rather_than_assumed_fine():
    assert one(assess(analysis()), "integrity_unverified").severity == WARNING


# ------------------------------------------------------------- loss levels


@pytest.mark.parametrize("loss,expected", [
    (0.12, "loss_severe"),
    (0.02, "loss_degraded"),
    (0.004, "loss_minor"),
    (0.0001, "loss_clean"),
])
def test_loss_is_graded(loss, expected):
    assert one(assess(analysis(primary=FakeLink(loss=loss))), expected)


def test_a_clean_period_does_not_claim_the_fault_is_gone():
    body = one(assess(analysis(primary=FakeLink(loss=0.0))), "loss_clean")
    assert body.severity == GOOD


# --------------------------------------------------------------- isolation


def test_fault_isolated_to_the_link_under_test():
    a = analysis(
        primary=FakeLink(loss=0.08),
        has_control=True,
        controls=[FakeLink(label="Backup link")],
        comparison={"common_minutes": 1440, "primary_only_bad": 300,
                    "control_only_bad": 2, "both_bad": 5,
                    "primary_blackout_control_fine": 40,
                    "primary_loss": 0.08, "control_loss": 0.001},
    )
    f = one(assess(a), "isolated_to_link")
    assert f.severity == CRITICAL
    assert f.params["control"] == "Backup link"


def test_both_links_bad_blocks_the_isolation_claim():
    a = analysis(
        primary=FakeLink(loss=0.08), has_control=True,
        controls=[FakeLink(label="Backup link")],
        comparison={"common_minutes": 1440, "primary_only_bad": 5,
                    "control_only_bad": 4, "both_bad": 200,
                    "primary_blackout_control_fine": 0,
                    "primary_loss": 0.08, "control_loss": 0.07},
    )
    findings = assess(a)
    assert "both_links_bad" in keys(findings)
    assert "isolated_to_link" not in keys(findings)


def test_a_worse_control_is_stated_plainly():
    a = analysis(
        primary=FakeLink(loss=0.001), has_control=True,
        controls=[FakeLink(label="Backup link")],
        comparison={"common_minutes": 1440, "primary_only_bad": 1,
                    "control_only_bad": 250, "both_bad": 0,
                    "primary_blackout_control_fine": 0,
                    "primary_loss": 0.001, "control_loss": 0.09},
    )
    assert "control_worse" in keys(assess(a))
    assert "isolated_to_link" not in keys(assess(a))


def test_missing_control_is_called_out():
    assert one(assess(analysis()), "no_control").severity == WARNING


# ------------------------------------------------------ where the loss is


def test_loss_at_the_operators_own_node():
    a = analysis(primary=FakeLink(loss=0.06, first_hop=0.05),
                 has_first_hop=True, first_hop_ips=["100.124.1.27"])
    f = one(assess(a), "operator_network_loss")
    assert f.severity == CRITICAL
    assert "100.124.1.27" in f.params["hops"]


def test_clean_first_hop_places_the_fault_beyond_it():
    a = analysis(primary=FakeLink(loss=0.05, first_hop=0.0),
                 has_first_hop=True, first_hop_ips=["100.124.1.27"])
    assert "beyond_first_hop" in keys(assess(a))


# ------------------------------------------------------- shape over the day


def _hours(peak_loss, base_loss):
    return [{"hour": h, "loss": peak_loss if 18 <= h < 24 else base_loss, "minutes": 60}
            for h in range(24)]


def test_evening_concentration_reads_as_congestion():
    a = analysis(primary=FakeLink(loss=0.03), hour_profile=_hours(0.08, 0.002))
    assert one(assess(a), "congestion_pattern").severity == WARNING


def test_flat_loss_reads_as_a_fault():
    a = analysis(primary=FakeLink(loss=0.03), hour_profile=_hours(0.03, 0.03))
    assert one(assess(a), "constant_pattern").severity == CRITICAL


def test_no_pattern_claim_on_a_clean_line():
    a = analysis(primary=FakeLink(loss=0.0001), hour_profile=_hours(0.0001, 0.0001))
    assert "congestion_pattern" not in keys(assess(a))
    assert "constant_pattern" not in keys(assess(a))


# ------------------------------------------------------------ other faults


def test_broken_address_family_is_reported():
    a = analysis(reach_broken=[
        {"host": "claude.ai", "family": "ipv6", "address": "2607:6bc0::10",
         "working": ["ipv4"], "fail_ratio": 1.0, "attempts": 12, "errors": {}},
    ])
    f = one(assess(a), "family_broken")
    assert f.severity == CRITICAL
    assert f.params["family"] == "IPv6"
    assert f.params["example"] == "claude.ai"
    assert f.params["count"] == 1


def test_operator_resolvers_failing_alone_is_not_a_line_fault():
    a = analysis(dns={
        "80.69.96.12": {"role": "isp_resolver", "total": 500, "fail_ratio": 0.20},
        "1.1.1.1": {"role": "public_control", "total": 500, "fail_ratio": 0.001},
    })
    assert one(assess(a), "resolver_fault").severity == CRITICAL


def test_dns_failing_everywhere_points_at_the_line():
    a = analysis(dns={
        "80.69.96.12": {"role": "isp_resolver", "total": 500, "fail_ratio": 0.15},
        "1.1.1.1": {"role": "public_control", "total": 500, "fail_ratio": 0.14},
    })
    assert "dns_both_bad" in keys(assess(a))
    assert "resolver_fault" not in keys(assess(a))


def _cycle(after, later):
    return [{"hours_since": h, "loss": after if h < 12 else later,
             "minutes": 60, "local_hour": h, "degraded_minutes": 0} for h in range(24)]


def test_instability_after_the_restart_is_reported_as_harmful():
    a = analysis(primary=FakeLink(loss=0.05), cycle=_cycle(0.09, 0.004))
    assert one(assess(a), "restart_harmful").severity == CRITICAL


def test_degradation_with_uptime_supports_replacing_the_device():
    a = analysis(primary=FakeLink(loss=0.05), cycle=_cycle(0.004, 0.09))
    assert one(assess(a), "restart_helpful").severity == WARNING


# ------------------------------------------------------------------ order


def test_findings_are_ordered_worst_first():
    a = analysis(
        primary=FakeLink(loss=0.08, first_hop=0.05),
        has_first_hop=True, first_hop_ips=["100.124.1.27"],
        egress={"checks": 5, "confirmed": 5, "leaked": 0, "unknown": 0,
                "windows": [], "expected": "94.31.72.0/22", "confirmed_ratio": 1.0},
    )
    severities = [f.severity for f in assess(a)]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1,
                                                           "neutral": 2, "good": 3}[s])


def test_every_finding_has_text_in_every_language():
    """A finding with no string renders as its key, which would look broken."""
    from ispbust.report.strings import STRINGS

    a = analysis(
        primary=FakeLink(loss=0.08, first_hop=0.05, minutes=120),
        has_control=True, controls=[FakeLink(label="Backup")],
        comparison={"common_minutes": 100, "primary_only_bad": 50, "control_only_bad": 0,
                    "both_bad": 0, "primary_blackout_control_fine": 5,
                    "primary_loss": 0.08, "control_loss": 0.0},
        has_first_hop=True, first_hop_ips=["100.124.1.27"],
        hour_profile=_hours(0.03, 0.03), cycle=_cycle(0.09, 0.004),
        dns={"a": {"role": "isp_resolver", "total": 10, "fail_ratio": 0.5},
             "b": {"role": "public_control", "total": 10, "fail_ratio": 0.0}},
        reach_broken=[{"host": "x", "family": "ipv6", "address": "::1",
                       "working": ["ipv4"], "fail_ratio": 1.0, "attempts": 2, "errors": {}}],
        egress={"checks": 4, "confirmed": 4, "leaked": 0, "unknown": 0,
                "windows": [], "expected": "94.31.72.0/22", "confirmed_ratio": 1.0},
    )
    findings = assess(a)
    assert len(findings) >= 8, keys(findings)
    for finding in findings:
        for key in (finding.title_key, finding.body_key):
            assert key in STRINGS, "no text for %s" % key
            for lang in ("en", "de"):
                text = STRINGS[key].get(lang)
                assert text, "%s missing %s" % (key, lang)
                text.format(**finding.params)  # every placeholder must resolve


# ----------------------------------------------- refusing to over-conclude


def _leaked(confirmed_ratio):
    return {"checks": 10, "confirmed": int(10 * confirmed_ratio),
            "leaked": 10 - int(10 * confirmed_ratio), "unknown": 0,
            "windows": [{"address": "9.246.125.16", "checks": 1}],
            "expected": "94.31.72.0/22", "confirmed_ratio": confirmed_ratio}


def test_no_causal_conclusions_are_drawn_from_leaked_data():
    """The tool must not say where the fault is using data it just invalidated."""
    a = analysis(
        primary=FakeLink(loss=0.08, first_hop=0.05),
        has_first_hop=True, first_hop_ips=["100.64.0.1"],
        has_control=True, controls=[FakeLink(label="Backup")],
        comparison={"common_minutes": 1440, "primary_only_bad": 300, "control_only_bad": 0,
                    "both_bad": 0, "primary_blackout_control_fine": 10,
                    "primary_loss": 0.08, "control_loss": 0.0},
        egress=_leaked(0.1),
    )
    found = keys(assess(a))
    assert "integrity_leaked" in found
    assert "conclusions_withheld" in found
    for suppressed in ("operator_network_loss", "isolated_to_link",
                       "loss_severe", "constant_pattern"):
        assert suppressed not in found, "%s must not be claimed from leaked data" % suppressed


def test_a_mostly_clean_period_still_gets_conclusions():
    a = analysis(primary=FakeLink(loss=0.08), egress=_leaked(0.9))
    found = keys(assess(a))
    assert "integrity_leaked" in found
    assert "conclusions_withheld" not in found
    assert "loss_severe" in found, "a brief blip must not silence the whole report"


def test_broken_family_is_reported_once_not_once_per_site():
    a = analysis(reach_broken=[
        {"host": h, "family": "ipv6", "address": "2607:6bc0::10", "working": ["ipv4"],
         "fail_ratio": 1.0, "attempts": 6, "errors": {}}
        for h in ("claude.ai", "www.google.com", "www.heise.de")
    ])
    found = [f for f in assess(a) if f.key == "family_broken"]
    assert len(found) == 1
    assert found[0].params["count"] == 3
    assert "claude.ai" in found[0].params["hosts"]
    assert found[0].params["family"] == "IPv6", "must read as IPv6, not IPV6"
    assert found[0].params["working"] == "IPv4"


def test_withheld_and_leaked_findings_also_have_text():
    from ispbust.report.strings import STRINGS

    a = analysis(primary=FakeLink(loss=0.08), egress=_leaked(0.1))
    findings = assess(a)
    assert {"integrity_leaked", "conclusions_withheld"} <= set(keys(findings))
    for finding in findings:
        for key in (finding.title_key, finding.body_key):
            for lang in ("en", "de"):
                STRINGS[key][lang].format(**finding.params)
