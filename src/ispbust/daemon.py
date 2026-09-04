"""The collection daemon: wires config, storage, collectors and HTTP together."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time

from . import __version__
from .collectors import (
    Collector,
    DiscoveryCollector,
    DnsCollector,
    IcmpCollector,
    ProbeContext,
    TcpCollector,
    TraceCollector,
)
from .config import ProbeConfig
from .metrics import BUILD, Labels
from .server import make_server, serve_in_background
from .storage import Store

LOG = logging.getLogger("ispbust.daemon")

PRUNE_INTERVAL_SECONDS = 6 * 3600


class Daemon:
    def __init__(self, cfg: ProbeConfig):
        self.cfg = cfg
        self.stop = threading.Event()
        self.store = Store(cfg.db_path, cfg.raw_dir, cfg.wan_id, cfg.retain_days)
        self.labels = Labels(cfg.wan_id, cfg.kind)
        self.ctx = ProbeContext(cfg=cfg, store=self.store, labels=self.labels, stop=self.stop)
        self.httpd = None
        BUILD.info({"version": __version__, "wan": cfg.wan_id, "kind": cfg.kind})

    def collectors(self) -> list[Collector]:
        active: list[Collector] = [IcmpCollector(self.ctx)]
        if self.cfg.discovery.enabled:
            active.append(DiscoveryCollector(self.ctx))
        if self.cfg.dns.enabled and self.cfg.dns.resolvers:
            active.append(DnsCollector(self.ctx))
        if self.cfg.tcp.enabled and self.cfg.tcp.targets:
            active.append(TcpCollector(self.ctx))
        if self.cfg.trace.enabled:
            active.append(TraceCollector(self.ctx))
        return active

    def prune_loop(self) -> None:
        while not self.stop.is_set():
            self.stop.wait(PRUNE_INTERVAL_SECONDS)
            if not self.stop.is_set():
                self.store.prune()

    def run(self) -> int:
        self.labels.probe_up().set(1)
        self.httpd = make_server(
            self.store, self.cfg.wan_id, self.cfg.label, self.cfg.kind,
            self.cfg.port, self.cfg.export_token)
        serve_in_background(self.httpd)
        LOG.info("ispbust %s -- wan=%s (%s, %s) http=:%d source_ip=%s",
                 __version__, self.cfg.label, self.cfg.wan_id, self.cfg.kind,
                 self.cfg.port, self.cfg.source_ip or "default")
        if self.cfg.export_token:
            LOG.info("export endpoints require a token")
        else:
            LOG.warning("export endpoints are unauthenticated -- set server.export_token "
                        "if this probe is reachable beyond your trusted network")

        self.store.marker("probe_start", "version=%s pid=%d host=%s"
                          % (__version__, os.getpid(), socket.gethostname()))

        threads = []
        for collector in self.collectors():
            t = threading.Thread(target=collector.loop, name=collector.name, daemon=True)
            t.start()
            threads.append(t)
            LOG.info("started collector: %s", collector.name)
        threading.Thread(target=self.prune_loop, name="prune", daemon=True).start()

        try:
            while not self.stop.is_set():
                self.stop.wait(1.0)
        except KeyboardInterrupt:
            self.stop.set()

        LOG.info("shutting down")
        self.labels.probe_up().set(0)
        self.store.marker("probe_stop", "clean shutdown")
        if self.httpd is not None:
            self.httpd.shutdown()
        deadline = time.time() + 10
        for t in threads:
            t.join(timeout=max(0.1, deadline - time.time()))
        self.store.close()
        return 0


def run_daemon(cfg: ProbeConfig) -> int:
    daemon = Daemon(cfg)

    def handle(signum, _frame):
        LOG.info("received signal %s", signum)
        daemon.stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handle)
    return daemon.run()
