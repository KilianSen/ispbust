#!/usr/bin/env python3
"""
Export UDM Pro WAN state to Prometheus, and archive the raw JSON.

The router's own view of the link is independent corroboration: it records
carrier loss, DHCP lease changes and WAN failover events that a ping probe
cannot see. When DG claims "the line was up", the router's own uptime counter
resetting is awkward for them.

  export UDMP_HOST=10.0.60.1 UDMP_USER=ispbust-ro UDMP_PASS=...
  python udmp_exporter.py --port 9110 --archive /var/lib/ispbust/udmp

Create a dedicated LOCAL admin account on the UDM Pro for this (Settings ->
Admins -> Add Admin -> Restrict to Local Access, read-only role). Do not use
your Ubiquiti SSO account: SSO logins are rate-limited and MFA-gated.

Self-signed certificate verification is off by default because the UDM Pro
ships one; the connection stays on the LAN.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path

from prometheus_client import Counter, Gauge, start_http_server

LOG = logging.getLogger("udmp")

G_UP = Gauge("udmp_wan_up", "WAN reported up by the router", ["wan", "name"])
G_LATENCY = Gauge("udmp_wan_latency_ms", "WAN latency as measured by the router", ["wan", "name"])
G_UPTIME = Gauge("udmp_wan_uptime_seconds", "WAN uptime reported by the router", ["wan", "name"])
G_RX = Gauge("udmp_wan_rx_bytes", "WAN bytes received", ["wan", "name"])
G_TX = Gauge("udmp_wan_tx_bytes", "WAN bytes sent", ["wan", "name"])
G_SPEED = Gauge("udmp_wan_link_speed_mbps", "Negotiated link speed", ["wan", "name"])
G_IPINFO = Gauge("udmp_wan_ip_info", "Current WAN IP and gateway (value=1)",
                 ["wan", "name", "ip", "gateway"])
C_SCRAPE_FAIL = Counter("udmp_scrape_failures", "Failed polls of the UDM Pro")
G_SCRAPE_OK = Gauge("udmp_scrape_ok", "Last poll succeeded")


class Udmp:
    def __init__(self, host: str, user: str, password: str, verify: bool):
        self.base = "https://" + host
        self.user = user
        self.password = password
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.csrf: str | None = None

    def _request(self, path: str, data: dict | None = None) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method="POST" if body else "GET")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        with self.opener.open(req, timeout=20) as resp:
            token = resp.headers.get("X-CSRF-Token") or resp.headers.get("x-csrf-token")
            if token:
                self.csrf = token
            raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}

    def login(self) -> None:
        self._request("/api/auth/login", {"username": self.user, "password": self.password})
        LOG.info("logged in to %s", self.base)

    def devices(self) -> list:
        d = self._request("/proxy/network/api/s/default/stat/device")
        return d.get("data", [])

    def health(self) -> list:
        d = self._request("/proxy/network/api/s/default/stat/health")
        return d.get("data", [])


def as_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def publish(devices: list, health: list) -> int:
    """Walk the gateway object for wan1/wan2 sub-objects and export what exists.

    UniFi shifts these field names between releases, so every read is optional
    and a missing field is skipped rather than fatal.
    """
    found = 0
    for dev in devices:
        if dev.get("type") not in ("udm", "ugw", "uxg"):
            continue
        for key in ("wan1", "wan2", "wan3", "wan4"):
            wan = dev.get(key)
            if not isinstance(wan, dict):
                continue
            found += 1
            name = wan.get("ifname") or key
            labels = (key, name)
            up = wan.get("up")
            if up is not None:
                G_UP.labels(*labels).set(1 if up else 0)
            for field, gauge in (("latency", G_LATENCY), ("uptime", G_UPTIME),
                                 ("rx_bytes", G_RX), ("tx_bytes", G_TX),
                                 ("speed", G_SPEED)):
                v = as_float(wan.get(field))
                if v is not None:
                    gauge.labels(*labels).set(v)
            ip = wan.get("ip") or ""
            gw = wan.get("gateway") or ""
            if ip or gw:
                G_IPINFO.labels(key, name, ip, gw).set(1)

    for sub in health:
        if sub.get("subsystem") != "wan":
            continue
        v = as_float(sub.get("latency"))
        if v is not None:
            G_LATENCY.labels("health", sub.get("wan_ip") or "wan").set(v)
    return found


def archive(path: Path, devices: list, health: list) -> None:
    path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC)
    f = path / (stamp.strftime("%Y-%m-%d") + ".ndjson")
    payload = {
        "ts": stamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "devices": [
            {k: v for k, v in d.items()
             if k in ("name", "model", "version", "uptime", "type",
                      "wan1", "wan2", "wan3", "wan4", "uplink", "sys_stats")}
            for d in devices
        ],
        "health": health,
    }
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Export UDM Pro WAN state to Prometheus.")
    ap.add_argument("--host", default=os.environ.get("UDMP_HOST", ""))
    ap.add_argument("--user", default=os.environ.get("UDMP_USER", ""))
    ap.add_argument("--password", default=os.environ.get("UDMP_PASS", ""))
    ap.add_argument("--port", type=int, default=9110)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--archive", type=Path, default=None,
                    help="directory for raw JSON snapshots (recommended)")
    ap.add_argument("--verify-tls", action="store_true",
                    help="verify the router certificate (off by default: self-signed)")
    ap.add_argument("--once", action="store_true", help="poll once and print, for testing")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (args.host and args.user and args.password):
        sys.exit("set --host/--user/--password or UDMP_HOST/UDMP_USER/UDMP_PASS")

    client = Udmp(args.host, args.user, args.password, args.verify_tls)

    if args.once:
        client.login()
        devs, hp = client.devices(), client.health()
        n = publish(devs, hp)
        print("found %d WAN objects on %d devices" % (n, len(devs)))
        for d in devs:
            if d.get("type") in ("udm", "ugw", "uxg"):
                print(json.dumps({k: d.get(k) for k in ("name", "model", "wan1", "wan2")},
                                 indent=2)[:4000])
        return 0

    start_http_server(args.port)
    LOG.info("metrics on :%d, polling %s every %ds", args.port, args.host, args.interval)
    logged_in = False
    while True:
        try:
            if not logged_in:
                client.login()
                logged_in = True
            devs, hp = client.devices(), client.health()
            publish(devs, hp)
            if args.archive:
                archive(args.archive, devs, hp)
            G_SCRAPE_OK.set(1)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as exc:
            LOG.warning("poll failed: %s", exc)
            C_SCRAPE_FAIL.inc()
            G_SCRAPE_OK.set(0)
            logged_in = False  # session probably expired
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
