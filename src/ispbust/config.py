"""Configuration for both halves of the tool.

Two documents exist:

* a **probe config**, one per collection container -- what to measure and how
* a **site config**, read by the report container -- which probes exist, which
  one is under test, and how the report should read

Everything is deliberately vendor-neutral. The tool has no idea who sells you
either connection; it knows a link under test and one or more controls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

UNDER_TEST = "under_test"
CONTROL = "control"


class ConfigError(ValueError):
    """Raised with a message meant to be read by a human fixing a YAML file."""


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError("config file not found: %s" % path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError("%s is not valid YAML: %s" % (path, exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError("%s must contain a YAML mapping at the top level" % path)
    return data


def _seq(raw: dict, key: str) -> list:
    """A YAML key with nothing but comments under it parses as None, not [].

    That is an easy thing to write by hand -- the shipped examples did it --
    so treat a null sequence as an empty one instead of failing on it.
    """
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError("%s must be a list, got %s" % (key, type(value).__name__))
    return list(value)


def _env(name: str, default: Any = None) -> Any:
    """Environment overrides let a container be configured without a file edit."""
    return os.environ.get("ISPBUST_" + name, default)


# --------------------------------------------------------------------- probe


@dataclass
class Target:
    host: str
    role: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.host:
            raise ConfigError("icmp target needs a host")
        if not self.role:
            raise ConfigError("icmp target %s needs a role" % self.host)


@dataclass
class IcmpConfig:
    window_seconds: int = 60
    packet_interval_ms: int = 1000
    timeout_ms: int = 1500
    event_loss_ratio: float = 0.02
    event_rtt_ms: float = 250.0
    targets: list[Target] = field(default_factory=list)


@dataclass
class DnsConfig:
    enabled: bool = True
    interval_seconds: int = 15
    timeout_seconds: float = 3.0
    names: list[str] = field(default_factory=list)
    resolvers: list[dict] = field(default_factory=list)


@dataclass
class TcpConfig:
    enabled: bool = True
    interval_seconds: int = 60
    targets: list[dict] = field(default_factory=list)


@dataclass
class ReachConfig:
    """End-to-end reachability of real sites, over every address family.

    ICMP to an anchor proves the link carries packets. It does not prove a
    browser can open a page: a host with AAAA records and broken IPv6 routing
    fails in the browser while every ping stays green. Only an actual
    connection, per family, catches that.
    """

    enabled: bool = True
    interval_seconds: int = 120
    timeout_seconds: float = 10.0
    families: list = field(default_factory=lambda: ["ipv4", "ipv6"])
    targets: list = field(default_factory=list)


@dataclass
class EgressConfig:
    """Confirm the probe is still leaving by the uplink it is supposed to.

    This is the check the rest of the tool rests on. A probe pinned to one
    uplink whose router quietly fails it over to the other keeps reporting a
    healthy line throughout the outage it was deployed to record -- and the
    numbers look completely normal, which is what makes it dangerous.
    """

    enabled: bool = True
    interval_seconds: int = 300
    timeout_seconds: float = 10.0
    families: list = field(default_factory=lambda: ["ipv4"])
    # Authoritative when set. Without it the first successful observation is
    # taken as the baseline, which is convenient but assumes the pin was
    # correct at that moment -- so prefer stating it.
    expected_prefixes: list = field(default_factory=list)
    endpoints: dict = field(default_factory=lambda: {
        "ipv4": ["https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"],
        "ipv6": ["https://api6.ipify.org", "https://icanhazip.com"],
    })
    # Width used to compare a learned baseline, so a normal address change
    # inside the operator's range is not mistaken for a failover.
    match_prefix_ipv4: int = 24
    match_prefix_ipv6: int = 48


@dataclass
class TraceConfig:
    enabled: bool = True
    target: str = "1.1.1.1"
    cycles: int = 10
    interval_seconds: int = 900
    on_event: bool = True
    on_event_cooldown_seconds: int = 300


@dataclass
class DiscoveryConfig:
    """Finds the ISP's own first hop so it can be probed continuously.

    Loss measured against the operator's next hop sits inside their network,
    which removes every "the internet was busy" answer.
    """

    enabled: bool = True
    via: str = "1.1.1.1"
    hop: int = 2
    role: str = "isp_first_hop"
    interval_seconds: int = 3600


@dataclass
class ProbeConfig:
    wan_id: str
    label: str
    kind: str = UNDER_TEST
    source_ip: str | None = None
    port: int = 9109
    export_token: str | None = None
    data_dir: Path = Path("/var/lib/ispbust")
    retain_days: int = 0
    icmp: IcmpConfig = field(default_factory=IcmpConfig)
    dns: DnsConfig = field(default_factory=DnsConfig)
    tcp: TcpConfig = field(default_factory=TcpConfig)
    reach: ReachConfig = field(default_factory=ReachConfig)
    egress: EgressConfig = field(default_factory=EgressConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ispbust.sqlite"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


def load_probe_config(path: Path) -> ProbeConfig:
    raw = _load_yaml(path)
    wan = raw.get("wan") or {}
    server = raw.get("server") or {}
    storage = raw.get("storage") or {}

    wan_id = _env("WAN_ID", wan.get("id"))
    if not wan_id:
        raise ConfigError("wan.id is required (or set ISPBUST_WAN_ID)")
    kind = _env("WAN_KIND", wan.get("kind", UNDER_TEST))
    if kind not in (UNDER_TEST, CONTROL):
        raise ConfigError("wan.kind must be '%s' or '%s', got %r" % (UNDER_TEST, CONTROL, kind))

    icmp_raw = raw.get("icmp") or {}
    targets = [Target(**t) for t in _seq(icmp_raw, "targets")]

    dns_raw = raw.get("dns") or {}
    for r in _seq(dns_raw, "resolvers"):
        if "ip" not in r:
            raise ConfigError("every dns.resolvers entry needs an 'ip'")

    tcp_raw = raw.get("tcp") or {}
    for t in _seq(tcp_raw, "targets"):
        if "host" not in t:
            raise ConfigError("every tcp.targets entry needs a 'host'")

    reach_raw = raw.get("reachability") or {}
    for r in _seq(reach_raw, "targets"):
        if "host" not in r:
            raise ConfigError("every reachability.targets entry needs a 'host'")
    families = [f.lower() for f in (reach_raw.get("families") or ["ipv4", "ipv6"])]
    for fam in families:
        if fam not in ("ipv4", "ipv6"):
            raise ConfigError("reachability.families may only contain 'ipv4' and 'ipv6'")

    egress_raw = raw.get("egress") or {}
    egress_families = [f.lower() for f in (egress_raw.get("families") or ["ipv4"])]
    for fam in egress_families:
        if fam not in ("ipv4", "ipv6"):
            raise ConfigError("egress.families may only contain 'ipv4' and 'ipv6'")
    import ipaddress as _ipaddress
    for cidr in _seq(egress_raw, "expected_prefixes"):
        try:
            _ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ConfigError("egress.expected_prefixes: %r is not a network: %s" % (cidr, exc)) from exc

    trace_raw = raw.get("traceroute") or {}
    disc_raw = raw.get("upstream_discovery") or {}

    cfg = ProbeConfig(
        wan_id=str(wan_id),
        label=str(_env("WAN_LABEL", wan.get("label", wan_id))),
        kind=kind,
        source_ip=(_env("SOURCE_IP", wan.get("source_ip")) or None),
        port=int(_env("PORT", server.get("port", 9109))),
        export_token=(_env("EXPORT_TOKEN", server.get("export_token")) or None),
        data_dir=Path(str(_env("DATA_DIR", storage.get("data_dir", "/var/lib/ispbust")))),
        retain_days=int(_env("RETAIN_DAYS", storage.get("retain_days", 0))),
        icmp=IcmpConfig(
            window_seconds=int(icmp_raw.get("window_seconds", 60)),
            packet_interval_ms=int(icmp_raw.get("packet_interval_ms", 1000)),
            timeout_ms=int(icmp_raw.get("timeout_ms", 1500)),
            event_loss_ratio=float(icmp_raw.get("event_loss_ratio", 0.02)),
            event_rtt_ms=float(icmp_raw.get("event_rtt_ms", 250)),
            targets=targets,
        ),
        dns=DnsConfig(
            enabled=bool(dns_raw.get("enabled", True)),
            interval_seconds=int(dns_raw.get("interval_seconds", 15)),
            timeout_seconds=float(dns_raw.get("timeout_seconds", 3.0)),
            names=_seq(dns_raw, "names"),
            resolvers=_seq(dns_raw, "resolvers"),
        ),
        tcp=TcpConfig(
            enabled=bool(tcp_raw.get("enabled", True)),
            interval_seconds=int(tcp_raw.get("interval_seconds", 60)),
            targets=_seq(tcp_raw, "targets"),
        ),
        reach=ReachConfig(
            enabled=bool(reach_raw.get("enabled", True)),
            interval_seconds=int(reach_raw.get("interval_seconds", 120)),
            timeout_seconds=float(reach_raw.get("timeout_seconds", 10.0)),
            families=families,
            targets=_seq(reach_raw, "targets"),
        ),
        egress=EgressConfig(
            enabled=bool(egress_raw.get("enabled", True)),
            interval_seconds=int(egress_raw.get("interval_seconds", 300)),
            timeout_seconds=float(egress_raw.get("timeout_seconds", 10.0)),
            families=egress_families,
            expected_prefixes=_seq(egress_raw, "expected_prefixes"),
            endpoints=dict(egress_raw.get("endpoints") or EgressConfig().endpoints),
            match_prefix_ipv4=int(egress_raw.get("match_prefix_ipv4", 24)),
            match_prefix_ipv6=int(egress_raw.get("match_prefix_ipv6", 48)),
        ),
        trace=TraceConfig(
            enabled=bool(trace_raw.get("enabled", True)),
            target=str(trace_raw.get("target", "1.1.1.1")),
            cycles=int(trace_raw.get("cycles", 10)),
            interval_seconds=int(trace_raw.get("interval_seconds", 900)),
            on_event=bool(trace_raw.get("on_event", True)),
            on_event_cooldown_seconds=int(trace_raw.get("on_event_cooldown_seconds", 300)),
        ),
        discovery=DiscoveryConfig(
            enabled=bool(disc_raw.get("enabled", True)),
            via=str(disc_raw.get("via", "1.1.1.1")),
            hop=int(disc_raw.get("hop", 2)),
            role=str(disc_raw.get("role", "isp_first_hop")),
            interval_seconds=int(disc_raw.get("interval_seconds", 3600)),
        ),
    )

    if cfg.icmp.window_seconds < 10:
        raise ConfigError("icmp.window_seconds below 10 produces noisy, unconvincing data")
    if not targets and not cfg.discovery.enabled:
        raise ConfigError("no icmp targets and upstream discovery disabled -- nothing to measure")
    return cfg


# ---------------------------------------------------------------------- site


@dataclass
class ProbeRef:
    """How the report container reaches one collection container."""

    id: str
    label: str
    kind: str = UNDER_TEST
    url: str | None = None
    token: str | None = None
    db: Path | None = None  # local file instead of a URL

    def __post_init__(self) -> None:
        if not self.url and not self.db:
            raise ConfigError("probe %s needs either a url or a db path" % self.id)
        if self.kind not in (UNDER_TEST, CONTROL):
            raise ConfigError("probe %s: kind must be '%s' or '%s'" % (self.id, UNDER_TEST, CONTROL))


@dataclass
class Thresholds:
    degraded_loss: float = 0.05
    blackout_loss: float = 0.999

    def __post_init__(self) -> None:
        if not 0 < self.degraded_loss < self.blackout_loss <= 1.0:
            raise ConfigError("thresholds must satisfy 0 < degraded_loss < blackout_loss <= 1")


@dataclass
class ExperimentConfig:
    """Optional A/B test of a nightly device power cycle."""

    enabled: bool = False
    hour: int = 3
    seed: int = 0
    device_label: str = "modem"
    plug_off_url: str | None = None
    plug_on_url: str | None = None
    off_seconds: int = 45


@dataclass
class SiteConfig:
    name: str = "site"
    timezone: str = "UTC"
    language: str = "en"
    isp_name: str = "the operator"
    customer_ref: str = ""
    contract_downstream_mbps: float | None = None
    contract_upstream_mbps: float | None = None
    probes: list[ProbeRef] = field(default_factory=list)
    thresholds: Thresholds = field(default_factory=Thresholds)
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)

    @property
    def under_test(self) -> ProbeRef:
        for p in self.probes:
            if p.kind == UNDER_TEST:
                return p
        raise ConfigError("no probe with kind '%s' in the site config" % UNDER_TEST)

    @property
    def controls(self) -> list[ProbeRef]:
        return [p for p in self.probes if p.kind == CONTROL]


def load_site_config(path: Path) -> SiteConfig:
    raw = _load_yaml(path)
    site = raw.get("site") or {}
    probes = [ProbeRef(
        id=str(p["id"]),
        label=str(p.get("label", p["id"])),
        kind=str(p.get("kind", UNDER_TEST)),
        url=(p.get("url") or None),
        token=(p.get("token") or None),
        db=(Path(p["db"]) if p.get("db") else None),
    ) for p in _seq(raw, "probes")]
    if not probes:
        raise ConfigError("site config lists no probes")

    th = raw.get("thresholds") or {}
    ex = raw.get("experiment") or {}
    cfg = SiteConfig(
        name=str(_env("SITE_NAME", site.get("name", "site"))),
        timezone=str(_env("TZ_NAME", site.get("timezone", "UTC"))),
        language=str(_env("LANGUAGE", site.get("language", "en"))).lower(),
        isp_name=str(site.get("isp_name", "the operator")),
        customer_ref=str(site.get("customer_ref", "")),
        contract_downstream_mbps=site.get("contract_downstream_mbps"),
        contract_upstream_mbps=site.get("contract_upstream_mbps"),
        probes=probes,
        thresholds=Thresholds(
            degraded_loss=float(th.get("degraded_loss", 0.05)),
            blackout_loss=float(th.get("blackout_loss", 0.999)),
        ),
        experiment=ExperimentConfig(
            enabled=bool(ex.get("enabled", False)),
            hour=int(ex.get("hour", 3)),
            seed=int(ex.get("seed", 0)),
            device_label=str(ex.get("device_label", "modem")),
            plug_off_url=(ex.get("plug_off_url") or None),
            plug_on_url=(ex.get("plug_on_url") or None),
            off_seconds=int(ex.get("off_seconds", 45)),
        ),
    )
    # Fail here rather than at report time if no link is marked under test.
    _ = cfg.under_test
    if cfg.experiment.enabled and not cfg.experiment.seed:
        raise ConfigError("experiment.enabled requires a fixed experiment.seed -- "
                          "the schedule must be decided in advance to be credible")
    return cfg
