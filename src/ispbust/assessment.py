"""Turn measurements into findings.

The report already puts the numbers in front of a reader. This decides what
they mean: which of the plausible causes the data actually supports, which it
rules out, and what to ask for next. That judgement was previously left to
whoever read the tables, which meant it was usually not made at all.

Every finding names the figures it rests on. A conclusion a reader cannot
check is worth less than no conclusion, because an operator will check it.

Findings carry a string key and parameters rather than prose, so they render in
whichever language the report is built in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CRITICAL = "critical"
WARNING = "warning"
NEUTRAL = "neutral"
GOOD = "good"

_ORDER = {CRITICAL: 0, WARNING: 1, NEUTRAL: 2, GOOD: 3}

# Hours treated as the evening peak when separating congestion from a fault.
PEAK_HOURS = range(18, 24)


@dataclass
class Finding:
    key: str
    severity: str
    params: dict = field(default_factory=dict)

    @property
    def title_key(self) -> str:
        return "f_%s_title" % self.key

    @property
    def body_key(self) -> str:
        return "f_%s_body" % self.key


def _pct(value: float, digits: int = 2) -> str:
    return ("%." + str(digits) + "f") % (value * 100) + " %"


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def assess(analysis) -> list:
    """Return findings, most serious first."""
    findings: list = []
    for rule in (
        _integrity,
        _sufficiency,
        _headline_loss,
        _isolation,
        _operator_network,
        _time_of_day,
        _address_family,
        _resolvers,
        _restart_cycle,
    ):
        findings.extend(rule(analysis) or [])
    findings.sort(key=lambda f: _ORDER.get(f.severity, 9))
    return findings


# ------------------------------------------------------------------ rules


def _integrity(a) -> list:
    """Nothing else means anything if the probe was on the wrong uplink."""
    e = a.egress or {}
    if not e.get("checks"):
        return [Finding("integrity_unverified", WARNING)]
    if e.get("leaked"):
        return [Finding("integrity_leaked", CRITICAL, {
            "leaked": e["leaked"],
            "graded": e["confirmed"] + e["leaked"],
            "windows": len(e["windows"]),
            "address": (e["windows"][0]["address"] if e["windows"] else "?"),
            "expected": e.get("expected") or "?",
        })]
    return [Finding("integrity_confirmed", GOOD, {
        "confirmed": e["confirmed"], "expected": e.get("expected") or "?",
    })]


def _sufficiency(a) -> list:
    minutes = a.primary.measured_minutes()
    if minutes < 60:
        return [Finding("too_little_data", WARNING, {"minutes": minutes})]
    if minutes < 1440:
        return [Finding("short_period", WARNING, {
            "minutes": minutes, "hours": round(minutes / 60, 1),
        })]
    return []


def _headline_loss(a) -> list:
    loss = a.primary.loss_ratio()
    params = {
        "loss": _pct(loss),
        "minutes": "{:,}".format(a.primary.measured_minutes()),
        "degraded": "{:,}".format(a.primary.degraded_minutes),
        "blackout": "{:,}".format(a.primary.blackout_minutes),
        "events": len(a.outages),
    }
    if loss >= 0.05:
        return [Finding("loss_severe", CRITICAL, params)]
    if loss >= 0.01:
        return [Finding("loss_degraded", CRITICAL, params)]
    if loss >= 0.001:
        return [Finding("loss_minor", WARNING, params)]
    return [Finding("loss_clean", GOOD, params)]


def _isolation(a) -> list:
    """Does the fault follow this link, or is it everywhere?"""
    if not a.has_control or not a.comparison.get("common_minutes"):
        return [Finding("no_control", WARNING)]
    c = a.comparison
    params = {
        "only_bad": "{:,}".format(c["primary_only_bad"]),
        "common": "{:,}".format(c["common_minutes"]),
        "control_only": "{:,}".format(c["control_only_bad"]),
        "both": "{:,}".format(c["both_bad"]),
        "control": a.controls[0].label,
        "primary_loss": _pct(c["primary_loss"]),
        "control_loss": _pct(c["control_loss"]),
        "blackout_fine": "{:,}".format(c["primary_blackout_control_fine"]),
    }
    if c["primary_only_bad"] >= 10 and c["primary_only_bad"] > max(3 * c["control_only_bad"], 3):
        return [Finding("isolated_to_link", CRITICAL, params)]
    if c["control_only_bad"] > max(3 * c["primary_only_bad"], 3):
        return [Finding("control_worse", NEUTRAL, params)]
    if c["both_bad"] >= 10 and c["both_bad"] > 3 * c["primary_only_bad"]:
        return [Finding("both_links_bad", WARNING, params)]
    return [Finding("no_isolation_signal", NEUTRAL, params)]


def _operator_network(a) -> list:
    if not a.has_first_hop:
        return []
    loss = a.primary.loss_ratio("first_hop")
    params = {"loss": _pct(loss), "hops": ", ".join(a.first_hop_ips) or "?"}
    if loss >= 0.01:
        return [Finding("operator_network_loss", CRITICAL, params)]
    if a.primary.loss_ratio() >= 0.01:
        return [Finding("beyond_first_hop", NEUTRAL, params)]
    return []


def _time_of_day(a) -> list:
    """Congestion clusters in the evening peak; a fault does not care."""
    profile = [p for p in (a.hour_profile or []) if p["minutes"]]
    if len(profile) < 12 or a.primary.loss_ratio() < 0.005:
        return []
    peak = _mean([p["loss"] for p in profile if p["hour"] in PEAK_HOURS])
    rest = _mean([p["loss"] for p in profile if p["hour"] not in PEAK_HOURS])
    params = {"peak": _pct(peak), "rest": _pct(rest)}
    if peak >= 0.01 and peak >= 2 * max(rest, 1e-9):
        return [Finding("congestion_pattern", WARNING, params)]
    if rest > 0 and peak <= 1.5 * rest:
        return [Finding("constant_pattern", CRITICAL, params)]
    return []


def _address_family(a) -> list:
    findings = []
    for broken in a.reach_broken or []:
        findings.append(Finding("family_broken", CRITICAL, {
            "family": broken["family"].upper(),
            "host": broken["host"],
            "address": broken["address"] or "?",
            "working": ", ".join(f.upper() for f in broken["working"]),
            "fail": _pct(broken["fail_ratio"], 0),
        }))
    return findings


def _resolvers(a) -> list:
    """Separate "their DNS is broken" from "the line is broken"."""
    if not a.dns:
        return []
    isp = [b for b in a.dns.values() if b["role"] == "isp_resolver" and b["total"]]
    public = [b for b in a.dns.values() if b["role"] == "public_control" and b["total"]]
    if not isp or not public:
        return []
    isp_fail = _mean([b["fail_ratio"] for b in isp])
    public_fail = _mean([b["fail_ratio"] for b in public])
    params = {"isp": _pct(isp_fail), "public": _pct(public_fail)}
    if isp_fail >= 0.02 and isp_fail >= 3 * max(public_fail, 1e-9):
        return [Finding("resolver_fault", CRITICAL, params)]
    if isp_fail >= 0.02 and public_fail >= 0.02:
        return [Finding("dns_both_bad", WARNING, params)]
    return []


def _restart_cycle(a) -> list:
    """Is the nightly restart curing the fault, or causing it?"""
    profile = [p for p in (a.cycle or []) if p["minutes"]]
    if len(profile) < 12:
        return []
    after = _mean([p["loss"] for p in profile if p["hours_since"] < 12])
    later = _mean([p["loss"] for p in profile if p["hours_since"] >= 12])
    params = {"after": _pct(after), "later": _pct(later),
              "device": a.site.experiment.device_label}
    if after >= 0.01 and after >= 1.5 * max(later, 1e-9):
        return [Finding("restart_harmful", CRITICAL, params)]
    if later >= 0.01 and later >= 1.5 * max(after, 1e-9):
        return [Finding("restart_helpful", WARNING, params)]
    return []
