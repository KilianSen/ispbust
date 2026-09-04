"""Prometheus metrics.

The live view only. Nothing here is the evidence -- the evidence is in SQLite
and the NDJSON archive, which survive a Prometheus wipe or a retention change.

Every series carries `wan` (the probe's id) and `wan_kind` (under_test or
control) so a dashboard can compare links without hardcoding anyone's ISP.
"""

from __future__ import annotations

import contextlib

from prometheus_client import Counter, Gauge, Info

ICMP_LOSS = Gauge(
    "ispbust_icmp_loss_ratio", "Packet loss in the most recent window",
    ["wan", "wan_kind", "target", "role"])
ICMP_RTT = Gauge(
    "ispbust_icmp_rtt_ms", "Round-trip time statistic over the most recent window",
    ["wan", "wan_kind", "target", "role", "stat"])
ICMP_SENT = Counter(
    "ispbust_icmp_sent", "ICMP echo requests sent",
    ["wan", "wan_kind", "target", "role"])
ICMP_LOST = Counter(
    "ispbust_icmp_lost", "ICMP echo requests with no reply",
    ["wan", "wan_kind", "target", "role"])

DNS_SECONDS = Gauge(
    "ispbust_dns_query_seconds", "Duration of the most recent DNS query",
    ["wan", "wan_kind", "resolver", "resolver_role", "name"])
DNS_QUERIES = Counter(
    "ispbust_dns_queries", "DNS queries by outcome",
    ["wan", "wan_kind", "resolver", "resolver_role", "outcome"])

TCP_SECONDS = Gauge(
    "ispbust_tcp_connect_seconds", "TCP connect or TLS handshake duration",
    ["wan", "wan_kind", "target", "phase"])
TCP_FAILURES = Counter(
    "ispbust_tcp_failures", "TCP or TLS handshake failures",
    ["wan", "wan_kind", "target"])

EVENTS = Counter(
    "ispbust_events", "Impairment events detected by the probe",
    ["wan", "wan_kind", "kind"])

UPSTREAM_HOP = Gauge(
    "ispbust_upstream_hop_info", "Discovered ISP-side first hop (always 1)",
    ["wan", "wan_kind", "hop_ip"])

PROBE_UP = Gauge("ispbust_probe_up", "Probe liveness", ["wan", "wan_kind"])
COLLECTOR_ERRORS = Counter(
    "ispbust_collector_errors", "Unhandled errors inside a collector loop",
    ["wan", "collector"])
BUILD = Info("ispbust_build", "Build information")


class Labels:
    """Binds the two constant labels once so call sites stay readable."""

    def __init__(self, wan: str, kind: str):
        self.wan = wan
        self.kind = kind

    def icmp_loss(self, target: str, role: str):
        return ICMP_LOSS.labels(self.wan, self.kind, target, role)

    def icmp_rtt(self, target: str, role: str, stat: str):
        return ICMP_RTT.labels(self.wan, self.kind, target, role, stat)

    def icmp_sent(self, target: str, role: str):
        return ICMP_SENT.labels(self.wan, self.kind, target, role)

    def icmp_lost(self, target: str, role: str):
        return ICMP_LOST.labels(self.wan, self.kind, target, role)

    def dns_seconds(self, resolver: str, role: str, name: str):
        return DNS_SECONDS.labels(self.wan, self.kind, resolver, role, name)

    def dns_queries(self, resolver: str, role: str, outcome: str):
        return DNS_QUERIES.labels(self.wan, self.kind, resolver, role, outcome)

    def tcp_seconds(self, target: str, phase: str):
        return TCP_SECONDS.labels(self.wan, self.kind, target, phase)

    def tcp_failures(self, target: str):
        return TCP_FAILURES.labels(self.wan, self.kind, target)

    def events(self, kind: str):
        return EVENTS.labels(self.wan, self.kind, kind)

    def upstream_hop(self, hop_ip: str):
        return UPSTREAM_HOP.labels(self.wan, self.kind, hop_ip)

    def drop_upstream_hop(self, hop_ip: str) -> None:
        with contextlib.suppress(KeyError):
            UPSTREAM_HOP.remove(self.wan, self.kind, hop_ip)

    def probe_up(self):
        return PROBE_UP.labels(self.wan, self.kind)

    def collector_error(self, collector: str):
        return COLLECTOR_ERRORS.labels(self.wan, collector)
