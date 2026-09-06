"""The measurement loops.

Each collector is a small class with a `run_once`; the base class owns the
timing, the error handling and the liveness accounting. A collector that
raises is logged, counted and retried -- it never takes the process down,
because a dead probe is a hole in the evidence and a hole in the evidence is
the first thing a support desk will point at.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import socket
import ssl
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass

from .config import (
    DiscoveryConfig,
    DnsConfig,
    EgressConfig,
    IcmpConfig,
    ProbeConfig,
    ReachConfig,
    Target,
    TcpConfig,
    TraceConfig,
)
from .metrics import Labels
from .storage import Store, iso

try:
    import dns.exception
    import dns.resolver
except ImportError:  # pragma: no cover - probing DNS is optional
    dns = None

LOG = logging.getLogger("ispbust.collect")


def run_cmd(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """Run a subprocess and never raise. Returns (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "not found: %s" % cmd[0]
    except OSError as exc:
        return 1, "", repr(exc)


# --------------------------------------------------------------------- base


class Collector:
    name = "collector"

    def __init__(self, probe: ProbeContext):
        self.probe = probe
        self.cfg = probe.cfg
        self.store = probe.store
        self.labels = probe.labels
        self.stop = probe.stop

    @property
    def interval(self) -> float:
        raise NotImplementedError

    def run_once(self) -> None:
        raise NotImplementedError

    def loop(self) -> None:
        while not self.stop.is_set():
            started = time.time()
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                LOG.exception("%s collector error: %s", self.name, exc)
                self.labels.collector_error(self.name).inc()
            self.stop.wait(max(1.0, self.interval - (time.time() - started)))


@dataclass
class ProbeContext:
    """Everything the collectors share."""

    cfg: ProbeConfig
    store: Store
    labels: Labels
    stop: threading.Event
    dynamic_targets: list = None
    lock: threading.Lock = None
    last_event_trace: float = 0.0

    def __post_init__(self) -> None:
        if self.dynamic_targets is None:
            self.dynamic_targets = []
        if self.lock is None:
            self.lock = threading.Lock()

    def targets(self) -> list[Target]:
        with self.lock:
            return list(self.cfg.icmp.targets) + list(self.dynamic_targets)

    def set_dynamic(self, targets: list[Target]) -> None:
        with self.lock:
            self.dynamic_targets = targets

    def record_event(self, kind: str, role: str | None, target: str | None, detail: str) -> None:
        self.store.insert("events", {
            "ts": iso(), "wan": self.cfg.wan_id, "kind": kind,
            "target": target, "role": role, "detail": detail,
        })
        self.labels.events(kind).inc()
        LOG.warning("[%s] %s %s %s -- %s", self.cfg.wan_id, kind, role or "", target or "", detail)


# --------------------------------------------------------------------- ICMP


class IcmpCollector(Collector):
    """Continuous ping, aggregated into fixed windows.

    One packet per second per target by default. Sparser sampling produces
    numbers an operator can wave away as noise; this produces 1440 samples per
    target per day and a per-minute loss figure that is hard to argue with.
    """

    name = "icmp"

    @property
    def conf(self) -> IcmpConfig:
        return self.cfg.icmp

    @property
    def interval(self) -> float:
        return self.conf.window_seconds

    @property
    def count(self) -> int:
        return max(1, self.conf.window_seconds * 1000 // self.conf.packet_interval_ms)

    def command(self, hosts: list[str], family: str = "ipv4") -> list[str]:
        cmd = ["fping", "-6" if family == "ipv6" else "-4",
               "-C", str(self.count), "-p", str(self.conf.packet_interval_ms),
               "-t", str(self.conf.timeout_ms), "-q", "-B1", "-r0"]
        if self.cfg.source_ip and family == "ipv4":
            cmd += ["-S", self.cfg.source_ip]
        return cmd + hosts

    @staticmethod
    def parse(stderr: str) -> dict:
        """fping -C writes `1.2.3.4 : 1.23 2.34 - 4.56` to stderr; `-` is a loss.

        Split on the *last* colon, not the first: an IPv6 target is full of
        colons and splitting on the first one would truncate the address to
        its first group and drop every sample for it.
        """
        out: dict = {}
        for line in stderr.splitlines():
            if ":" not in line:
                continue
            host, _, rest = line.rpartition(":")
            host = host.strip()
            if not host:
                continue
            vals: list = []
            for tok in rest.split():
                if tok == "-":
                    vals.append(None)
                else:
                    with contextlib.suppress(ValueError):
                        vals.append(float(tok))
            if vals:
                out[host] = vals
        return out

    @staticmethod
    def rtt_stats(vals: list) -> dict:
        if not vals:
            return {"min": None, "avg": None, "max": None, "p95": None, "stddev": None}
        s = sorted(vals)
        n = len(s)
        avg = sum(s) / n
        var = sum((v - avg) ** 2 for v in s) / n
        idx = min(n - 1, int(round(0.95 * (n - 1))))
        return {"min": round(s[0], 3), "avg": round(avg, 3), "max": round(s[-1], 3),
                "p95": round(s[idx], 3), "stddev": round(var ** 0.5, 3)}

    @staticmethod
    def family_of(host: str) -> str:
        """A literal with a colon is IPv6; anything else goes over IPv4."""
        return "ipv6" if ":" in host else "ipv4"

    def run_once(self) -> None:
        targets = self.probe.targets()
        if not targets:
            self.stop.wait(10)
            return
        groups: dict = {}
        for t in targets:
            groups.setdefault(self.family_of(t.host), {})[t.host] = t
        ts = iso()

        if len(groups) == 1:
            family, by_host = next(iter(groups.items()))
            self.measure(family, by_host, ts)
            return

        # fping cannot mix address families in one run, and each run blocks for
        # a whole window. Running them one after another would sample every
        # target half as often and break the one-row-per-target-per-minute
        # cadence the report is built on, so the families run side by side and
        # share a timestamp.
        threads = [
            threading.Thread(target=self.measure, args=(family, by_host, ts),
                             name="icmp-%s" % family, daemon=True)
            for family, by_host in groups.items()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.conf.window_seconds + 45)

    def measure(self, family: str, by_host: dict, ts: str) -> None:
        rc, _, err = run_cmd(self.command(list(by_host), family),
                             timeout=self.conf.window_seconds + 30)
        if rc == 127:
            LOG.error("fping is not installed -- the ICMP collector cannot run")
            self.stop.wait(30)
            return
        for host, vals in self.parse(err).items():
            target = by_host.get(host)
            if target is None:
                continue
            good = [v for v in vals if v is not None]
            sent, lost = len(vals), len(vals) - len(good)
            ratio = lost / sent if sent else 0.0
            stats = self.rtt_stats(good)
            self.store.insert("icmp", {
                "ts": ts, "wan": self.cfg.wan_id, "target": host, "role": target.role,
                "sent": sent, "lost": lost, "loss_ratio": round(ratio, 6),
                "rtt_min": stats["min"], "rtt_avg": stats["avg"], "rtt_max": stats["max"],
                "rtt_p95": stats["p95"], "rtt_stddev": stats["stddev"],
                "window_s": self.conf.window_seconds, "family": family,
            })
            self.labels.icmp_loss(host, target.role).set(ratio)
            self.labels.icmp_sent(host, target.role).inc(sent)
            self.labels.icmp_lost(host, target.role).inc(lost)
            for stat, value in stats.items():
                if value is not None:
                    self.labels.icmp_rtt(host, target.role, stat).set(value)
            self.check_event(host, target, ratio, stats)

    def check_event(self, host: str, target: Target, ratio: float, stats: dict) -> None:
        kinds = []
        if ratio >= self.conf.event_loss_ratio:
            kinds.append("packet_loss")
        if stats["avg"] is not None and stats["avg"] >= self.conf.event_rtt_ms:
            kinds.append("latency")
        if ratio >= 0.999:
            kinds.append("blackout")
        for kind in kinds:
            self.probe.record_event(
                kind, target.role, host,
                "loss=%.1f%% avg=%s max=%s p95=%s"
                % (ratio * 100, stats["avg"], stats["max"], stats["p95"]))
        # `enabled: false` means no traceroutes at all -- scheduled or triggered.
        # CI caught the opposite reading: a probe with traceroute disabled was
        # still firing event traces.
        if kinds and self.cfg.trace.enabled and self.cfg.trace.on_event:
            now = time.time()
            if now - self.probe.last_event_trace >= self.cfg.trace.on_event_cooldown_seconds:
                self.probe.last_event_trace = now
                threading.Thread(
                    target=TraceCollector(self.probe).capture, args=("event",),
                    name="trace-event", daemon=True).start()


# ---------------------------------------------------------------------- DNS


class DnsCollector(Collector):
    """Query the operator's resolvers and public ones side by side.

    This is what separates "the line is broken" from "their resolvers are
    broken" -- two complaints with completely different fixes.
    """

    name = "dns"

    def __init__(self, probe: ProbeContext):
        super().__init__(probe)
        self.index = 0

    @property
    def conf(self) -> DnsConfig:
        return self.cfg.dns

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def run_once(self) -> None:
        if dns is None:
            LOG.error("dnspython is not installed -- the DNS collector cannot run")
            self.stop.wait(60)
            return
        names = self.conf.names or ["example.com"]
        for resolver in self.conf.resolvers:
            if self.stop.is_set():
                return
            self.query(resolver, names[self.index % len(names)])
        self.index += 1

    def query(self, resolver: dict, qname: str) -> None:
        ip = resolver["ip"]
        role = resolver.get("role", "")
        qtype = resolver.get("qtype", "A")
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = [ip]
        r.timeout = self.conf.timeout_seconds
        r.lifetime = self.conf.timeout_seconds
        if self.cfg.source_ip:
            r.source = self.cfg.source_ip

        started = time.monotonic()
        outcome, rcode, answer = "ok", "NOERROR", ""
        try:
            ans = r.resolve(qname, qtype)
            answer = ",".join(sorted(str(a) for a in ans))[:500]
        except dns.resolver.NXDOMAIN:
            outcome, rcode = "nxdomain", "NXDOMAIN"
        except dns.resolver.NoAnswer:
            outcome, rcode = "noanswer", "NOERROR"
        except dns.resolver.LifetimeTimeout:
            outcome, rcode = "timeout", ""
        except dns.exception.DNSException as exc:
            outcome, rcode = "error", type(exc).__name__
        duration = time.monotonic() - started

        self.store.insert("dns", {
            "ts": iso(), "wan": self.cfg.wan_id, "resolver": ip, "resolver_role": role,
            "qname": qname, "qtype": qtype, "outcome": outcome, "rcode": rcode,
            "duration_s": round(duration, 4), "answer": answer,
        })
        self.labels.dns_seconds(ip, role, qname).set(duration)
        self.labels.dns_queries(ip, role, outcome).inc()
        if outcome in ("timeout", "error"):
            self.probe.record_event("dns_failure", role, ip,
                                    "%s/%s -> %s %s" % (qname, qtype, outcome, rcode))


# ----------------------------------------------------------------- TCP / TLS


class TcpCollector(Collector):
    """Connect and handshake timings -- what an application actually feels."""

    name = "tcp"

    @property
    def conf(self) -> TcpConfig:
        return self.cfg.tcp

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def run_once(self) -> None:
        for target in self.conf.targets:
            if self.stop.is_set():
                return
            self.check(target)

    def check(self, target: dict) -> None:
        host = target["host"]
        port = int(target.get("port", 443))
        use_tls = bool(target.get("tls", port == 443))
        connect_s = tls_s = None
        ok, error = 1, None
        sock = None
        try:
            started = time.monotonic()
            sock = socket.create_connection(
                (host, port), timeout=10,
                source_address=(self.cfg.source_ip, 0) if self.cfg.source_ip else None)
            connect_s = round(time.monotonic() - started, 4)
            if use_tls:
                ctx = ssl.create_default_context()
                started = time.monotonic()
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    tls.do_handshake()
                    tls_s = round(time.monotonic() - started, 4)
                sock = None  # wrap_socket's context manager closed it
        except Exception as exc:  # noqa: BLE001 - any failure is a data point
            ok, error = 0, ("%s: %s" % (type(exc).__name__, exc))[:300]
        finally:
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()

        self.store.insert("tcp", {
            "ts": iso(), "wan": self.cfg.wan_id, "target": host, "port": port,
            "connect_s": connect_s, "tls_s": tls_s, "ok": ok, "error": error,
        })
        if connect_s is not None:
            self.labels.tcp_seconds(host, "connect").set(connect_s)
        if tls_s is not None:
            self.labels.tcp_seconds(host, "tls").set(tls_s)
        if not ok:
            self.labels.tcp_failures(host).inc()
            self.probe.record_event("tcp_failure", "anchor", host, error or "")


# ------------------------------------------------------------ reachability


FAMILIES = {"ipv4": socket.AF_INET, "ipv6": socket.AF_INET6}


class ReachCollector(Collector):
    """Open a real connection to real sites, once per address family.

    ICMP to an anchor proves the link carries packets; it does not prove a
    browser can load a page. A host with AAAA records on a network whose IPv6
    routing is broken fails in the browser while every ping stays green,
    because the browser tries IPv6 first and the pings never did.

    Recording each family separately makes that visible, and the combination
    "IPv4 fine, IPv6 resolves but will not connect" is reported as its own
    event -- it is a specific, fixable fault, and one an operator will
    otherwise insist is imaginary.
    """

    name = "reach"

    @property
    def conf(self) -> ReachConfig:
        return self.cfg.reach

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def run_once(self) -> None:
        for target in self.conf.targets:
            if self.stop.is_set():
                return
            self.check_target(target)

    def check_target(self, target: dict) -> None:
        host = target["host"]
        port = int(target.get("port", 443))
        use_tls = bool(target.get("tls", port == 443))
        outcomes: dict = {}

        for family_name in self.conf.families:
            if self.stop.is_set():
                return
            outcomes[family_name] = self.check_family(host, port, use_tls, family_name)

        self.compare_families(host, outcomes)

    def check_family(self, host: str, port: int, use_tls: bool, family_name: str) -> dict:
        family = FAMILIES[family_name]
        row = {
            "ts": iso(), "wan": self.cfg.wan_id, "host": host, "port": port,
            "family": family_name, "address": None, "resolved": 0,
            "connect_s": None, "tls_s": None, "http_status": None,
            "ok": None, "error": None,
        }

        address, why = self.resolve(host, family_name)
        if address is None:
            # "This site has no AAAA record" and "this host cannot resolve AAAA
            # because its IPv6 is broken" are different findings, and the OS
            # resolver blurs them -- see resolve(). Nothing was attempted here,
            # so ok stays NULL either way.
            row["error"] = why
            self.store.insert("reach", row)
            self.labels.reach_attempt(host, family_name, "unresolved").inc()
            return row

        row["address"] = address
        row["resolved"] = 1
        sockaddr = (address, port, 0, 0) if family is socket.AF_INET6 else (address, port)
        sock = None
        try:
            started = time.monotonic()
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(self.conf.timeout_seconds)
            if self.cfg.source_ip and family is socket.AF_INET:
                sock.bind((self.cfg.source_ip, 0))
            sock.connect(sockaddr)
            row["connect_s"] = round(time.monotonic() - started, 4)

            stream = sock
            if use_tls:
                ctx = ssl.create_default_context()
                started = time.monotonic()
                stream = ctx.wrap_socket(sock, server_hostname=host)
                stream.do_handshake()
                row["tls_s"] = round(time.monotonic() - started, 4)
                sock = None

            request = "\r\n".join([
                "HEAD / HTTP/1.1",
                "Host: %s" % host,
                "User-Agent: ispbust",
                "Connection: close",
                "", "",
            ])
            stream.sendall(request.encode())
            first_line = stream.recv(200).decode("utf-8", "replace").split("\r\n")[0]
            parts = first_line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                row["http_status"] = int(parts[1])
            # Any status at all means the whole path worked. Which status the
            # site chose to return is its business, not the link's.
            row["ok"] = 1 if row["http_status"] else 0
            if not row["http_status"]:
                row["error"] = "no HTTP status in reply: %r" % first_line[:80]
            with contextlib.suppress(OSError):
                stream.close()
        except Exception as exc:  # noqa: BLE001 - any failure is the data point
            row["ok"] = 0
            row["error"] = ("%s: %s" % (type(exc).__name__, exc))[:300]
        finally:
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()

        self.store.insert("reach", row)
        outcome = "ok" if row["ok"] else "failed"
        self.labels.reach_attempt(host, family_name, outcome).inc()
        self.labels.reach_up(host, family_name).set(1 if row["ok"] else 0)
        for phase in ("connect_s", "tls_s"):
            if row[phase] is not None:
                self.labels.reach_seconds(host, family_name, phase[:-2]).set(row[phase])
        return row

    def resolve(self, host: str, family_name: str) -> tuple:
        """Find an address for this family, without asking the OS to choose.

        socket.getaddrinfo() is the obvious tool and the wrong one here. A
        Windows host with no usable IPv6 route returns WSANO_DATA for an AAAA
        lookup rather than the record, so the family that is actually broken
        looks like a family the site does not publish -- the check would go
        quiet on precisely the machine with the fault. Asking DNS directly
        keeps "no record" and "cannot reach" apart.

        Falls back to the OS resolver only when dnspython is unavailable.
        """
        rdtype = "AAAA" if family_name == "ipv6" else "A"
        if dns is not None:
            try:
                answer = dns.resolver.resolve(host, rdtype)
                addresses = [r.address for r in answer]
                if addresses:
                    return addresses[0], None
                return None, "no %s record" % rdtype
            except dns.resolver.NoAnswer:
                return None, "no %s record" % rdtype
            except dns.resolver.NXDOMAIN:
                return None, "NXDOMAIN"
            except dns.exception.DNSException as exc:
                return None, "%s lookup failed: %s" % (rdtype, type(exc).__name__)

        family = FAMILIES[family_name]
        try:
            infos = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
        except OSError as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)
        return (infos[0][4][0], None) if infos else (None, "no %s record" % rdtype)

    def compare_families(self, host: str, outcomes: dict) -> None:
        """Flag the asymmetric case, which is the one users actually feel."""
        for family_name, row in outcomes.items():
            others = [r for name, r in outcomes.items() if name != family_name]
            if row.get("resolved") and row.get("ok") == 0 and any(o.get("ok") == 1 for o in others):
                working = ", ".join(sorted(n for n, r in outcomes.items() if r.get("ok") == 1))
                self.probe.record_event(
                    "address_family_broken", family_name, host,
                    "%s resolves to %s but will not connect (%s), while %s works. "
                    "A browser tries the broken family first, so the site fails to "
                    "load even though ICMP stays clean."
                    % (family_name, row.get("address"), row.get("error"), working))

        attempted = [r for r in outcomes.values() if r.get("resolved")]
        if attempted and all(r.get("ok") == 0 for r in attempted):
            self.probe.record_event("site_unreachable", "reach", host,
                                    "no address family could complete a request")


# ----------------------------------------------------------------- egress


class EgressCollector(Collector):
    """Confirm the probe is still leaving by the uplink it is pinned to.

    Everything else this tool records assumes the probe's traffic went out the
    uplink named in its config. When a router quietly fails a "pinned" probe
    over to the other uplink, that assumption breaks silently and in the worst
    possible way: the probe keeps reporting a perfectly healthy line for the
    whole duration of the outage it was deployed to document, and the numbers
    look entirely normal.

    So the probe asks the internet which address it arrived from, and compares
    that against what it should be. A mismatch does not degrade the data, it
    invalidates it for that period, and the report has to say so.
    """

    name = "egress"

    def __init__(self, probe: ProbeContext):
        super().__init__(probe)
        self.reported: dict = {}

    @property
    def conf(self) -> EgressConfig:
        return self.cfg.egress

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def run_once(self) -> None:
        for family in self.conf.families:
            if self.stop.is_set():
                return
            self.check(family)

    def observe(self, family: str) -> tuple:
        """Ask several independent services; the first clean answer wins."""
        for url in self.conf.endpoints.get(family, []):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "ispbust"})
                with urllib.request.urlopen(request, timeout=self.conf.timeout_seconds) as resp:
                    text = resp.read(200).decode("utf-8", "replace").strip()
                address = ipaddress.ip_address(text)
            except Exception as exc:  # noqa: BLE001 - just try the next endpoint
                LOG.debug("egress endpoint %s failed: %s", url, exc)
                continue
            if address.version != (6 if family == "ipv6" else 4):
                continue
            return str(address), url, None
        return None, None, "no egress endpoint answered"

    def expected_networks(self, family: str) -> list:
        """Configured prefixes win; otherwise use the learned baseline."""
        version = 6 if family == "ipv6" else 4
        configured = []
        for cidr in self.conf.expected_prefixes:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if net.version == version:
                configured.append(net)
        if configured:
            return configured

        baseline = self.store.get_meta("egress_baseline_" + family)
        if baseline:
            try:
                return [ipaddress.ip_network(baseline, strict=False)]
            except ValueError:
                return []
        return []

    def learn(self, family: str, address: str) -> None:
        width = (self.conf.match_prefix_ipv6 if family == "ipv6"
                 else self.conf.match_prefix_ipv4)
        network = ipaddress.ip_network("%s/%d" % (address, width), strict=False)
        self.store.set_meta("egress_baseline_" + family, str(network))
        self.store.marker("egress_baseline", "%s %s" % (family, network))
        LOG.info("egress baseline for %s learned as %s (observed %s). State it "
                 "explicitly with egress.expected_prefixes -- a learned baseline "
                 "assumes the pin was correct at that moment.",
                 family, network, address)

    def check(self, family: str) -> None:
        address, endpoint, error = self.observe(family)
        networks = self.expected_networks(family)

        row = {
            "ts": iso(), "wan": self.cfg.wan_id, "family": family,
            "address": address,
            "expected": ", ".join(str(n) for n in networks) if networks else None,
            "ok": None, "endpoint": endpoint, "error": error,
        }

        if address is None:
            # Could not ask. Not a leak: most likely the link is simply down,
            # which every other collector is already recording.
            self.store.insert("egress", row)
            self.labels.egress_ok(family).set(0)
            return

        if not networks:
            self.learn(family, address)
            networks = self.expected_networks(family)
            row["expected"] = ", ".join(str(n) for n in networks)

        inside = any(ipaddress.ip_address(address) in net for net in networks)
        row["ok"] = 1 if inside else 0
        self.store.insert("egress", row)
        self.labels.egress_ok(family).set(1 if inside else 0)
        self.labels.egress_info(family, address).set(1)

        previous = self.reported.get(family)
        if not inside and previous != address:
            self.reported[family] = address
            self.probe.record_event(
                "egress_unexpected", family, address,
                "this probe left by %s, outside the expected range (%s). It is not "
                "measuring the uplink it is pinned to, so anything recorded for this "
                "period describes a different link. Check the router policy route and "
                "turn its failover off." % (address, row["expected"]))
        elif inside and previous is not None:
            self.reported.pop(family, None)
            self.probe.record_event(
                "egress_restored", family, address,
                "egress is back inside the expected range (%s)" % row["expected"])


# --------------------------------------------------------------- traceroute


class TraceCollector(Collector):
    """Periodic path snapshots, plus one the instant loss is detected.

    A traceroute taken during the fault shows which hop starts dropping. A
    traceroute taken afterwards shows nothing, which is why the ICMP collector
    triggers this one directly.
    """

    name = "trace"

    @property
    def conf(self) -> TraceConfig:
        return self.cfg.trace

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def mtr(self, target: str, cycles: int) -> list:
        cmd = ["mtr", "--json", "-n", "-c", str(cycles)]
        if self.cfg.source_ip:
            cmd += ["-a", self.cfg.source_ip]
        rc, out, err = run_cmd(cmd + [target], timeout=cycles * 3 + 60)
        if rc != 0 or not out.strip():
            LOG.debug("mtr failed rc=%s err=%s", rc, err[:200])
            return []
        try:
            return json.loads(out)["report"]["hubs"]
        except (ValueError, KeyError) as exc:
            LOG.debug("could not parse mtr output: %s", exc)
            return []

    def capture(self, trigger: str = "scheduled") -> None:
        hops = self.mtr(self.conf.target, self.conf.cycles)
        if not hops:
            return
        self.store.insert("trace", {
            "ts": iso(), "wan": self.cfg.wan_id, "target": self.conf.target,
            "trigger": trigger, "hops_json": json.dumps(hops, separators=(",", ":")),
        })

    def run_once(self) -> None:
        self.capture("scheduled")


# ------------------------------------------------------------ hop discovery


class DiscoveryCollector(Collector):
    """Find the ISP's own next hop and add it to the ICMP target list.

    Hop 1 is the customer's router. Hop 2 is the operator's edge. Loss measured
    there is loss inside their network, before any handover to anyone else --
    the one measurement that cannot be blamed on the public internet, on a
    second WAN, or on the customer's LAN.
    """

    name = "discovery"

    def __init__(self, probe: ProbeContext):
        super().__init__(probe)
        self.current: str | None = None
        # Hops that answer traceroute but not echo, so the warning is logged
        # once per address rather than every hour.
        self.silent: set = set()

    @property
    def conf(self) -> DiscoveryConfig:
        return self.cfg.discovery

    @property
    def interval(self) -> float:
        return self.conf.interval_seconds

    def run_once(self) -> None:
        hops = TraceCollector(self.probe).mtr(self.conf.via, 3)
        ip = None
        for hop in hops:
            try:
                if int(hop.get("count", 0)) == self.conf.hop:
                    ip = hop.get("host")
                    break
            except (TypeError, ValueError):
                continue
        if not ip or ip in ("???", "0.0.0.0") or ip == self.current:
            return
        if not self.acceptable(ip):
            return
        if not self.responds_to_echo(ip):
            if ip not in self.silent:
                self.silent.add(ip)
                LOG.warning(
                    "discovered hop %s answers traceroute but not ICMP echo -- NOT probing "
                    "it. Measuring it would record a permanent 100%% loss that is an "
                    "artefact of the router's ICMP policy, not a fault. The report will "
                    "omit the first-hop section; the scheduled traceroutes still capture "
                    "per-hop loss for this address.", ip)
                self.store.marker("upstream_hop_no_echo", ip)
            return
        self.silent.discard(ip)

        LOG.info("upstream first hop: %s -> %s", self.current, ip)
        if self.current:
            self.labels.drop_upstream_hop(self.current)
            self.probe.record_event("upstream_hop_change", self.conf.role, ip,
                                    "first hop changed %s -> %s" % (self.current, ip))
        self.current = ip
        self.labels.upstream_hop(ip).set(1)
        self.probe.set_dynamic([Target(host=ip, role=self.conf.role,
                                       note="auto-discovered ISP next hop")])
        self.store.marker("upstream_hop", ip)

    def responds_to_echo(self, ip: str) -> bool:
        """Does this hop actually answer pings?

        Plenty of operator routers reply to TTL-exceeded (so they appear in a
        traceroute) while dropping ICMP echo addressed to themselves. Probing
        such a hop records 100 % loss forever -- an artefact of its ICMP policy,
        not a fault. Putting that number in front of an operator would be worse
        than useless, so the candidate has to prove it answers first.
        """
        # -C (not -c): the uppercase form prints one RTT per packet, which is
        # what IcmpCollector.parse understands. The lowercase form prints only a
        # summary line, which the parser finds no numbers in -- so every host
        # would look silent.
        cmd = ["fping", "-C", "5", "-p", "300", "-t", "1000", "-q", "-r0"]
        if self.cfg.source_ip:
            cmd += ["-S", self.cfg.source_ip]
        rc, _, err = run_cmd(cmd + [ip], timeout=30)
        if rc == 127:
            return False
        replies = IcmpCollector.parse(err).get(ip, [])
        return any(v is not None for v in replies)

    def acceptable(self, ip: str) -> bool:
        """Reject a discovered hop that would corrupt the target set.

        Two degenerate cases, both seen in the wild behind NAT and on very
        short paths: the hop is the discovery destination itself (so the path
        is shorter than `hop` and what came back is an anchor, not an operator
        edge), or it duplicates a target already configured under another role.
        Adopting either would silently reassign that target's role and lose an
        anchor from the headline figure.
        """
        if ip == self.conf.via:
            LOG.warning("discovered hop %d is the discovery target itself (%s) -- "
                        "the path is shorter than expected; set upstream_discovery.hop "
                        "correctly (check `mtr -n %s`) or disable discovery",
                        self.conf.hop, ip, self.conf.via)
            self.store.marker("upstream_hop_rejected", "equals discovery target: " + ip)
            return False
        clash = next((t for t in self.cfg.icmp.targets if t.host == ip), None)
        if clash is not None:
            LOG.warning("discovered hop %s is already a configured target with role %r -- "
                        "keeping the configured role and not adding it again",
                        ip, clash.role)
            self.store.marker("upstream_hop_rejected",
                              "already configured as %s: %s" % (clash.role, ip))
            return False
        return True
