"""The single entry point for both containers.

The collection image runs `ispbust probe`. The report image runs `ispbust
report`, `fetch`, `summary`, `serve` or `experiment`. One binary, one config
format, so there is nothing to keep in sync between the two halves.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__

LOG = logging.getLogger("ispbust.cli")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else os.environ.get("ISPBUST_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )


def _default_range(days: int = 30) -> tuple:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), (today - timedelta(days=1)).isoformat()


def _valid_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD, got %r" % value) from None
    return value


# ------------------------------------------------------------------ probe


def cmd_probe(args) -> int:
    from .config import load_probe_config
    from .daemon import run_daemon

    cfg = load_probe_config(args.config)
    return run_daemon(cfg)


def cmd_check(args) -> int:
    """Validate a config file and print what it will do -- no side effects."""
    from .config import load_probe_config, load_site_config

    if args.probe:
        cfg = load_probe_config(args.probe)
        print("probe config OK: %s" % args.probe)
        print("  wan          : %s (%s, %s)" % (cfg.label, cfg.wan_id, cfg.kind))
        print("  data dir     : %s" % cfg.data_dir)
        print("  http port    : %d%s" % (cfg.port, "" if cfg.export_token else "  (no export token set)"))
        print("  icmp targets : %d static, window %ds, %d ms spacing"
              % (len(cfg.icmp.targets), cfg.icmp.window_seconds, cfg.icmp.packet_interval_ms))
        for t in cfg.icmp.targets:
            print("                 %-18s %s" % (t.host, t.role))
        print("  discovery    : %s" % ("hop %d via %s" % (cfg.discovery.hop, cfg.discovery.via)
                                       if cfg.discovery.enabled else "disabled"))
        print("  dns          : %d resolvers, %d names, every %ds"
              % (len(cfg.dns.resolvers), len(cfg.dns.names), cfg.dns.interval_seconds)
              if cfg.dns.enabled else "  dns          : disabled")
        if cfg.reach.enabled and cfg.reach.targets:
            print("  reachability : %d sites over %s every %ds"
                  % (len(cfg.reach.targets), "+".join(cfg.reach.families),
                     cfg.reach.interval_seconds))
            for r in cfg.reach.targets:
                print("                 %s:%s" % (r["host"], r.get("port", 443)))
        else:
            print("  reachability : disabled")
        print("  tcp          : %d targets every %ds"
              % (len(cfg.tcp.targets), cfg.tcp.interval_seconds)
              if cfg.tcp.enabled else "  tcp          : disabled")
    if args.site:
        site = load_site_config(args.site)
        print("site config OK: %s" % args.site)
        print("  site         : %s (%s, language %s)" % (site.name, site.timezone, site.language))
        print("  under test   : %s (%s)" % (site.under_test.label, site.under_test.id))
        for c in site.controls:
            print("  control      : %s (%s)" % (c.label, c.id))
        print("  thresholds   : degraded %.1f%%, blackout %.1f%%"
              % (site.thresholds.degraded_loss * 100, site.thresholds.blackout_loss * 100))
        print("  experiment   : %s" % ("seed %d at %02d:00" % (site.experiment.seed, site.experiment.hour)
                                       if site.experiment.enabled else "disabled"))
    if not (args.probe or args.site):
        print("pass --probe and/or --site", file=sys.stderr)
        return 2
    return 0


# ------------------------------------------------------------------ fetch


def cmd_fetch(args) -> int:
    from .config import load_site_config
    from .retrieve import fetch_all, probe_info

    site = load_site_config(args.site)
    if args.info:
        for ref in site.probes:
            try:
                info = probe_info(ref)
                store = info.get("store", {})
                tables = store.get("tables", {})
                icmp = tables.get("icmp", {})
                print("%-12s %-28s %s" % (ref.id, ref.label, ref.url or ref.db))
                print("             rows=%s first=%s last=%s"
                      % (icmp.get("rows", "?"), icmp.get("first", "?"), icmp.get("last", "?")))
            except Exception as exc:  # noqa: BLE001
                print("%-12s UNREACHABLE: %s" % (ref.id, exc))
        return 0

    paths = fetch_all(site, args.out, args.date_from, args.date_to)
    for wan_id, path in sorted(paths.items()):
        print("%-12s -> %s (%.1f MB)" % (wan_id, path, path.stat().st_size / 1048576))
    return 0


# ----------------------------------------------------------------- report


def _resolve_databases(site, args) -> dict:
    """Either pull fresh snapshots from the probes or use what is on disk."""
    from .retrieve import fetch_all

    if args.no_fetch:
        databases = {}
        for ref in site.probes:
            local = ref.db or (args.data_dir / ("%s.sqlite" % ref.id))
            if Path(local).exists():
                databases[ref.id] = Path(local)
            else:
                LOG.warning("no local database for %s at %s", ref.id, local)
        return databases
    return fetch_all(site, args.data_dir, args.date_from, args.date_to)


def cmd_report(args) -> int:
    from .analysis import analyse
    from .config import load_site_config
    from .report.builder import build_report

    site = load_site_config(args.site)
    databases = _resolve_databases(site, args)
    analysis = analyse(site, databases, args.date_from, args.date_to)
    html = build_report(analysis, args.language)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    h = analysis.headline()
    print("wrote %s (%.0f KB)" % (args.out, args.out.stat().st_size / 1024))
    print_headline(h)
    return 0


def print_headline(h: dict) -> None:
    print("  link under test  : %s" % h["link"])
    print("  measured minutes : %s" % "{:,}".format(h["measured_minutes"]))
    print("  packet loss      : %.2f %%" % (h["loss"] * 100))
    if h["first_hop_loss"] is not None:
        print("  loss to ISP hop  : %.2f %%" % (h["first_hop_loss"] * 100))
    print("  degraded minutes : %s" % "{:,}".format(h["degraded_minutes"]))
    print("  blackout minutes : %s" % "{:,}".format(h["blackout_minutes"]))
    print("  outage events    : %s" % "{:,}".format(h["outage_events"]))
    if h["control_loss"] is not None:
        print("  control loss     : %.2f %%" % (h["control_loss"] * 100))
        print("  bad on test only : %s of %s common minutes"
              % ("{:,}".format(h["primary_only_bad"]), "{:,}".format(h["common_minutes"])))


def cmd_summary(args) -> int:
    from .analysis import analyse
    from .config import load_site_config

    site = load_site_config(args.site)
    databases = _resolve_databases(site, args)
    analysis = analyse(site, databases, args.date_from, args.date_to)
    h = analysis.headline()
    if args.json:
        print(json.dumps(h, indent=2))
    else:
        print("ispbust summary %s .. %s" % (args.date_from, args.date_to))
        print_headline(h)
    return 0


# ------------------------------------------------------------------ serve


def cmd_serve(args) -> int:
    from .serve import serve

    return serve(args.site, args.reports_dir, args.port, args.interval,
                 args.days, args.language, args.data_dir)


# ------------------------------------------------------------- experiment


def cmd_experiment(args) -> int:
    from .config import load_site_config
    from .experiment import analyse, format_analysis, format_plan, plan, run_tonight

    site = load_site_config(args.site)
    cfg = site.experiment
    if not cfg.seed:
        print("set experiment.seed in the site config first", file=sys.stderr)
        return 2

    if args.action == "plan":
        start = date.fromisoformat(args.start) if args.start else None
        print(format_plan(plan(cfg.seed, args.days, start, cfg.hour), cfg.seed, cfg.hour))
        return 0

    db = args.db or (args.data_dir / ("%s.sqlite" % site.under_test.id))
    if args.action == "run":
        result = run_tonight(cfg, Path(db), site.under_test.id, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0 if "error" not in result else 1

    result = analyse(site, Path(db), site.under_test.id, args.since)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_analysis(result))
    return 0


# -------------------------------------------------------------- demo/test


def cmd_demo(args) -> int:
    from .analysis import analyse
    from .config import load_site_config
    from .demo import build_demo
    from .report.builder import build_report

    info = build_demo(args.out_dir, args.days, args.language)
    print("wrote synthetic databases and %s" % info["site"])

    if not args.no_report:
        site = load_site_config(info["site"])
        analysis = analyse(site, info["databases"], info["date_from"], info["date_to"])
        out = args.out_dir / "report.html"
        out.write_text(build_report(analysis, args.language), encoding="utf-8")
        print("wrote %s" % out)
        print_headline(analysis.headline())
    print()
    print("rebuild in another language with:")
    print("  ispbust report --site %s --from %s --to %s --no-fetch --language de --out report-de.html"
          % (info["site"], info["date_from"], info["date_to"]))
    return 0


def cmd_selftest(args) -> int:
    """End-to-end check: generate, analyse, render, in every language."""
    import tempfile

    from .analysis import analyse
    from .config import load_site_config
    from .demo import build_demo
    from .report.builder import build_report
    from .report.strings import Strings

    failures = []
    with tempfile.TemporaryDirectory(prefix="ispbust-selftest-") as tmp:
        tmp_path = Path(tmp)
        info = build_demo(tmp_path, days=3)
        site = load_site_config(info["site"])
        analysis = analyse(site, info["databases"], info["date_from"], info["date_to"])
        h = analysis.headline()
        print("generated 3 days: %s measured minutes, %.2f%% loss"
              % (h["measured_minutes"], h["loss"] * 100))
        if h["measured_minutes"] < 4000:
            failures.append("expected ~4320 measured minutes, got %d" % h["measured_minutes"])
        if h["loss"] <= 0:
            failures.append("synthetic faulty link reported no loss")
        if h["control_loss"] is None or h["control_loss"] >= h["loss"]:
            failures.append("control link is not cleaner than the link under test")

        for lang in Strings().available():
            html = build_report(analysis, lang)
            if "<svg" not in html or "</html>" not in html:
                failures.append("%s: report is not complete HTML" % lang)
            if "{" in html and "}" in html.split("<style>")[0]:
                failures.append("%s: unformatted placeholder in the header" % lang)
            print("rendered %s: %d KB" % (lang, len(html) // 1024))

    if failures:
        for f in failures:
            print("FAIL: %s" % f, file=sys.stderr)
        return 1
    print("selftest OK")
    return 0


# -------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ispbust",
        description="Measure an internet connection continuously and produce evidence "
                    "an operator's support desk cannot deflect.")
    p.add_argument("--version", action="version", version="ispbust " + __version__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    default_from, default_to = _default_range()

    # collection image
    s = sub.add_parser("probe", help="run the collection daemon (collection image)")
    s.add_argument("--config", type=Path,
                   default=Path(os.environ.get("ISPBUST_CONFIG", "/etc/ispbust/probe.yaml")))
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser("check", help="validate config files and print what they will do")
    s.add_argument("--probe", type=Path)
    s.add_argument("--site", type=Path)
    s.set_defaults(func=cmd_check)

    # report image
    def add_site_args(sp, with_range: bool = True):
        sp.add_argument("--site", type=Path,
                        default=Path(os.environ.get("ISPBUST_SITE", "/etc/ispbust/site.yaml")))
        sp.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("ISPBUST_DATA_DIR", "/data")))
        if with_range:
            sp.add_argument("--from", dest="date_from", type=_valid_date, default=default_from)
            sp.add_argument("--to", dest="date_to", type=_valid_date, default=default_to)

    s = sub.add_parser("fetch", help="pull database snapshots from the probes")
    add_site_args(s, with_range=False)
    s.add_argument("--from", dest="date_from", type=_valid_date, default=None)
    s.add_argument("--to", dest="date_to", type=_valid_date, default=None)
    s.add_argument("--out", type=Path, default=None,
                   help="where to write snapshots (default: --data-dir)")
    s.add_argument("--info", action="store_true", help="only show what each probe holds")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("report", help="build the fault report")
    add_site_args(s)
    s.add_argument("--out", type=Path, default=Path("report.html"))
    s.add_argument("--language", default=None, help="override the site config language")
    s.add_argument("--no-fetch", action="store_true",
                   help="use databases already on disk instead of pulling fresh ones")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("summary", help="print the headline numbers without building a report")
    add_site_args(s)
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-fetch", action="store_true")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("serve", help="rebuild the report on a schedule and serve it")
    add_site_args(s, with_range=False)
    s.add_argument("--reports-dir", type=Path,
                   default=Path(os.environ.get("ISPBUST_REPORTS_DIR", "/reports")))
    s.add_argument("--port", type=int, default=int(os.environ.get("ISPBUST_SERVE_PORT", 8080)))
    s.add_argument("--interval", type=int, default=int(os.environ.get("ISPBUST_INTERVAL", 21600)),
                   help="seconds between rebuilds (default 6h)")
    s.add_argument("--days", type=int, default=int(os.environ.get("ISPBUST_REPORT_DAYS", 30)),
                   help="how many days back each rebuild covers")
    s.add_argument("--language", default=None)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("experiment", help="A/B test a nightly power cycle")
    s.add_argument("action", choices=["plan", "run", "analyse"])
    add_site_args(s, with_range=False)
    s.add_argument("--days", type=int, default=28, help="plan: how many nights")
    s.add_argument("--start", default=None, help="plan: first night, YYYY-MM-DD")
    s.add_argument("--db", type=Path, default=None, help="run/analyse: probe database")
    s.add_argument("--dry-run", action="store_true", help="run: decide but change nothing")
    s.add_argument("--since", type=_valid_date, default=default_from, help="analyse: start date")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_experiment)

    s = sub.add_parser("demo", help="generate synthetic data and a sample report")
    s.add_argument("--out-dir", type=Path, default=Path("./demo"))
    s.add_argument("--days", type=int, default=10)
    s.add_argument("--language", default="en")
    s.add_argument("--no-report", action="store_true")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("selftest", help="end-to-end check of analysis and rendering")
    s.set_defaults(func=cmd_selftest)

    return p


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    if getattr(args, "out", None) is None and args.command == "fetch":
        args.out = args.data_dir

    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI should not spew tracebacks
        if args.verbose:
            raise
        LOG.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
