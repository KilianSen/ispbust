"""Render an :class:`~ispbust.analysis.Analysis` into a single HTML file.

Self-contained on purpose: no external CSS, JS, fonts or images. The document
has to survive being mailed as an attachment, printed to PDF, and opened on a
machine with no internet -- which is, after all, the situation being reported.
"""

from __future__ import annotations

import html
from datetime import datetime

from ..analysis import Analysis, parse_minute, tzinfo_for
from . import charts
from .strings import Strings
from .style import CSS


def esc(value) -> str:
    return html.escape(str(value))


def pct(value, digits: int = 2) -> str:
    if value is None:
        return "&ndash;"
    return ("%." + str(digits) + "f") % (value * 100) + " %"


def ms(value, digits: int = 1) -> str:
    if value is None:
        return "&ndash;"
    return ("%." + str(digits) + "f ms") % value


def seconds_as_ms(value) -> str:
    if value is None:
        return "&ndash;"
    return "%.0f ms" % (value * 1000)


def human_bytes(size) -> str:
    if size is None:
        return "&ndash;"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.1f %s" % (size, unit)
        size /= 1024.0
    return str(size)


def group_thousands(n: int) -> str:
    return "{:,}".format(n)


class ReportBuilder:
    def __init__(self, analysis: Analysis, language: str | None = None):
        self.a = analysis
        self.site = analysis.site
        self.t = Strings(language or analysis.site.language)
        self.tz = tzinfo_for(analysis.site.timezone)
        self.out: list = []
        self.section_no = 0

    # -- small emitters ------------------------------------------------

    def w(self, chunk: str) -> None:
        self.out.append(chunk)

    def heading(self, key: str, **kwargs) -> None:
        self.section_no += 1
        self.w("<h2>%d. %s</h2>" % (self.section_no, self.t(key, **kwargs)))

    def table(self, headers: list, rows: list) -> None:
        """rows are lists of already-escaped cell strings or (value, css) pairs."""
        self.w('<div class="wrap"><table><thead><tr>')
        for h in headers:
            self.w("<th>%s</th>" % h)
        self.w("</tr></thead><tbody>")
        for row in rows:
            self.w("<tr>")
            for cell in row:
                if isinstance(cell, tuple):
                    value, cls = cell
                    self.w('<td class="%s">%s</td>' % (cls, value))
                else:
                    self.w("<td>%s</td>" % cell)
            self.w("</tr>")
        self.w("</tbody></table></div>")

    def local(self, dt: datetime) -> str:
        return dt.astimezone(self.tz).strftime("%d.%m.%Y %H:%M")

    def loss_cell(self, value, threshold: float = 0.01) -> tuple:
        if value is None:
            return ("&ndash;", "")
        return (pct(value), "bad" if value >= threshold else "")

    # -- document ------------------------------------------------------

    def build(self) -> str:
        a = self.a
        self.w('<!doctype html><html lang="%s"><head><meta charset="utf-8">' % esc(self.t.lang))
        self.w('<meta name="viewport" content="width=device-width,initial-scale=1">')
        self.w("<title>%s</title>" % esc(self.t("doc_title")))
        self.w("<style>%s</style></head><body>" % CSS)

        self.w("<h1>%s</h1>" % esc(self.t("doc_title")))
        self.w('<p class="sub">%s</p>' % self.t(
            "subtitle",
            frm=esc(self.fmt_date(a.date_from)), to=esc(self.fmt_date(a.date_to)),
            tz=esc(self.site.timezone),
            ref=esc(self.site.customer_ref or self.t("no_ref")),
            now=esc(datetime.now(self.tz).strftime("%d.%m.%Y %H:%M"))))

        self.kpis()
        self.section_summary()
        if a.egress and a.egress.get("checks"):
            self.section_integrity()
        self.section_daily()
        self.section_outages()
        if a.cycle:
            self.section_cycle()
        self.section_hour_profile()
        if a.dns:
            self.section_dns()
        if a.reach:
            self.section_reach()
        self.section_targets()
        if a.traces:
            self.section_traces()
        self.section_method()

        self.w('<footer>%s</footer>' % self.t(
            "footer", frm=esc(self.fmt_date(a.date_from)), to=esc(self.fmt_date(a.date_to))))
        self.w("</body></html>")
        return "".join(self.out)

    @staticmethod
    def fmt_date(value: str) -> str:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")

    # -- blocks --------------------------------------------------------

    def kpi(self, value: str, label: str, alarm: bool = False) -> None:
        self.w('<div class="kpi%s"><div class="v">%s</div><div class="l">%s</div></div>'
               % (" alarm" if alarm else "", value, label))

    def kpis(self) -> None:
        a = self.a
        primary_loss = a.primary.loss_ratio()
        self.w('<div class="kpis">')
        self.kpi(pct(primary_loss),
                 self.t("kpi_primary_loss", label=esc(a.primary.label)),
                 alarm=primary_loss >= 0.01)
        if a.has_control:
            control = a.controls[0]
            self.kpi(pct(control.loss_ratio()),
                     self.t("kpi_control_loss", label=esc(control.label)))
        if a.has_first_hop:
            fh = a.primary.loss_ratio("first_hop")
            self.kpi(pct(fh), self.t("kpi_first_hop_loss"), alarm=fh >= 0.01)
        self.kpi(str(a.primary.blackout_minutes), self.t("kpi_blackout"),
                 alarm=a.primary.blackout_minutes > 0)
        self.kpi(str(len(a.outages)), self.t("kpi_events"), alarm=len(a.outages) > 5)
        self.w("</div>")

    def section_summary(self) -> None:
        a = self.a
        self.heading("s1_heading")
        self.w("<p>%s</p>" % self.t("s1_method"))
        self.w("<p>%s</p>" % self.t(
            "s1_result",
            loss=pct(a.primary.loss_ratio()),
            minutes=group_thousands(a.primary.measured_minutes()),
            blackout=a.primary.blackout_minutes,
            degraded=a.primary.degraded_minutes,
            threshold=pct(self.site.thresholds.degraded_loss, 0)))

        if a.has_control and a.comparison.get("common_minutes"):
            c = a.comparison
            self.w('<div class="note"><strong>%s</strong> %s</div>' % (
                self.t("s1_control_title"),
                self.t("s1_control_body",
                       control=esc(c["control_label"]),
                       only_bad=c["primary_only_bad"],
                       common=group_thousands(c["common_minutes"]),
                       blackout_fine=c["primary_blackout_control_fine"])))
        elif not a.has_control:
            self.w("<p>%s</p>" % self.t("s1_no_control"))

        if a.has_first_hop:
            self.w("<p>%s</p>" % self.t(
                "s1_first_hop",
                loss=pct(a.primary.loss_ratio("first_hop")),
                hops=esc(", ".join(a.first_hop_ips) or "?")))

    def section_integrity(self) -> None:
        """Placed immediately after the summary on purpose.

        A reader is entitled to know the measurements describe the connection
        named on the front page before being asked to accept any of them.
        """
        a = self.a
        e = a.egress
        self.heading("si_heading")
        self.w("<p>%s</p>" % self.t("si_intro"))

        graded = e["confirmed"] + e["leaked"]
        if graded:
            self.w("<p>%s</p>" % self.t(
                "si_confirmed", confirmed=e["confirmed"], graded=graded,
                ratio=pct(e["confirmed_ratio"] or 0.0),
                expected=esc(e["expected"] or "&ndash;")))

        if e["leaked"]:
            self.w('<div class="note"><strong>%s</strong> %s</div>' % (
                self.t("si_leak_title"), self.t("si_leak_body")))
            rows = []
            for window in e["windows"]:
                rows.append([
                    self.local(parse_minute(window["start"][:16])),
                    self.local(parse_minute(window["end"][:16])),
                    "<code>%s</code>" % esc(window["address"] or "?"),
                    window["checks"],
                ])
            self.table([self.t("th_start"), self.t("th_end"),
                        self.t("th_observed_address"), self.t("th_checks")], rows)
        elif graded:
            self.w("<p>%s</p>" % self.t("si_clean"))

        if e["unknown"]:
            self.w('<p class="method">%s</p>' % self.t("si_unknown", count=e["unknown"]))

    def section_daily(self) -> None:
        a = self.a
        self.heading("s2_heading")
        days = sorted(set(a.daily_primary) | set(a.daily_control))
        series = [{
            "name": self.t("legend_primary"), "cls": "bar-primary",
            "values": [a.daily_primary.get(d, {}).get("loss", 0.0) for d in days],
        }]
        if a.has_control:
            series.append({
                "name": self.t("legend_control"), "cls": "bar-control",
                "values": [a.daily_control.get(d, {}).get("loss", 0.0) for d in days],
            })
        self.w(charts.grouped_bars([d[5:] for d in days], series, self.t("chart_daily")))
        self.w('<div class="legend">')
        self.w('<span><i style="background:var(--primary)"></i>%s</span>' % self.t("legend_primary"))
        if a.has_control:
            self.w('<span><i style="background:var(--control)"></i>%s</span>' % self.t("legend_control"))
        self.w("</div>")

        headers = [self.t("th_day"), self.t("th_minutes"), self.t("th_loss"),
                   self.t("th_degraded"), self.t("th_blackout"), self.t("th_rtt_median")]
        if a.has_control:
            headers.append(self.t("th_control_loss"))
        rows = []
        for day in days:
            d = a.daily_primary.get(day)
            if not d:
                continue
            row = [esc(day), d["minutes"], self.loss_cell(d["loss"]),
                   d["degraded"], d["blackout"], ms(d["rtt_median"])]
            if a.has_control:
                cd = a.daily_control.get(day)
                row.append(pct(cd["loss"]) if cd else "&ndash;")
            rows.append(row)
        self.table(headers, rows)

    def section_outages(self) -> None:
        a = self.a
        self.heading("s3_heading")
        self.w("<p>%s</p>" % self.t("s3_intro",
                                    threshold=pct(self.site.thresholds.degraded_loss, 0),
                                    tz=esc(self.site.timezone)))
        if not a.outages:
            self.w(charts.empty(self.t("empty")))
            return
        headers = [self.t("th_start"), self.t("th_end"), self.t("th_duration"),
                   self.t("th_avg_loss"), self.t("th_max_loss")]
        if a.has_control:
            headers.append(self.t("th_control_same_time"))
        rows = []
        for run in a.outages[:40]:
            row = [self.local(run["start"]), self.local(run["end"]), run["minutes"],
                   (pct(run["avg_loss"]), "bad"), (pct(run["max_loss"]), "bad")]
            if a.has_control:
                key = run["start"].strftime("%Y-%m-%dT%H:%M")
                value = a.control_minute_loss.get(key)
                cls = "ok" if (value is not None and value < self.site.thresholds.degraded_loss) else ""
                row.append((pct(value) if value is not None else "&ndash;", cls))
            rows.append(row)
        self.table(headers, rows)
        if len(a.outages) > 40:
            self.w('<p class="method">%s</p>' % self.t("s3_more", count=len(a.outages) - 40))

    def section_cycle(self) -> None:
        a = self.a
        device = esc(self.site.experiment.device_label)
        hour = "%02d:00" % self.site.experiment.hour
        self.heading("s4_heading", device=device)
        self.w("<p>%s</p>" % self.t("s4_intro", device=device, hour=hour))
        points = [{
            "label": "+%d" % p["hours_since"],
            "value": p["loss"],
            "tooltip": "+%dh (%02d:00): %.2f%%, %d min" % (
                p["hours_since"], p["local_hour"], p["loss"] * 100, p["minutes"]),
        } for p in a.cycle]
        self.w(charts.single_bars(points, self.t("s4_heading", device=device),
                                  self.t("chart_cycle_axis", hour=hour)))
        self.table(
            [self.t("th_hours_since"), self.t("th_local_time"), self.t("th_loss"),
             self.t("th_minutes"), self.t("th_degraded")],
            [["+%d h" % p["hours_since"], "%02d:00" % p["local_hour"],
              self.loss_cell(p["loss"]), p["minutes"], p["degraded_minutes"]]
             for p in a.cycle])

    def section_hour_profile(self) -> None:
        a = self.a
        self.heading("s5_heading")
        self.w("<p>%s</p>" % self.t("s5_intro"))
        points = [{
            "label": "%02d" % p["hour"],
            "value": p["loss"],
            "tooltip": "%02d:00: %.2f%%, %d min" % (p["hour"], p["loss"] * 100, p["minutes"]),
        } for p in a.hour_profile]
        self.w(charts.single_bars(points, self.t("s5_heading"), self.t("chart_hour_axis")))

    def section_dns(self) -> None:
        a = self.a
        self.heading("s6_heading")
        self.w("<p>%s</p>" % self.t("s6_intro"))
        rows = []
        for ip, b in sorted(a.dns.items(), key=lambda kv: -kv[1]["fail_ratio"]):
            rows.append([
                "<code>%s</code>" % esc(ip), esc(b["role"]), b["total"], b["failed"],
                self.loss_cell(b["fail_ratio"]),
                seconds_as_ms(b["p50"]), seconds_as_ms(b["p95"]),
            ])
        self.table([self.t("th_resolver"), self.t("th_role"), self.t("th_queries"),
                    self.t("th_failures"), self.t("th_fail_rate"),
                    self.t("th_p50"), self.t("th_p95")], rows)

    def section_reach(self) -> None:
        a = self.a
        self.heading("sr_heading")
        self.w("<p>%s</p>" % self.t("sr_intro"))

        for finding in a.reach_broken:
            self.w('<div class="note"><strong>%s</strong> %s</div>' % (
                self.t("sr_finding_title"),
                self.t("sr_finding_body",
                       host=esc(finding["host"]),
                       address=esc(finding["address"] or "?"),
                       family=esc(finding["family"].upper()),
                       failed=int(round(finding["fail_ratio"] * finding["attempts"])),
                       attempts=finding["attempts"],
                       working=esc(", ".join(f.upper() for f in finding["working"])))))

        headers = [self.t("th_site"), self.t("th_family"), self.t("th_address"),
                   self.t("th_attempts"), self.t("th_failed"), self.t("th_fail_rate"),
                   self.t("th_connect_avg")]
        if a.reach_control:
            headers.append(self.t("th_control_family"))
        rows = []
        for (host, family), b in sorted(a.reach.items()):
            if not b["attempts"]:
                continue
            row = [
                esc(host), esc(family.upper()),
                "<code>%s</code>" % esc(b["last_address"] or "&ndash;"),
                b["attempts"], b["failed"], self.loss_cell(b["fail_ratio"]),
                ("%.0f ms" % (b["connect_avg"] * 1000)) if b["connect_avg"] is not None else "&ndash;",
            ]
            if a.reach_control:
                c = a.reach_control.get((host, family))
                row.append(pct(c["fail_ratio"]) if c and c["attempts"] else "&ndash;")
            rows.append(row)
        self.table(headers, rows)

    def section_targets(self) -> None:
        a = self.a
        self.heading("s7_heading")
        rows = [[
            "<code>%s</code>" % esc(r["target"]), esc(r["role"]), r["sent"], r["lost"],
            self.loss_cell(r["loss"]), ms(r["rtt_avg"]),
        ] for r in a.primary.target_rows()]
        self.table([self.t("th_target"), self.t("th_role"), self.t("th_packets"),
                    self.t("th_lost"), self.t("th_loss"), self.t("th_rtt_avg")], rows)

    def section_traces(self) -> None:
        a = self.a
        self.heading("s8_heading")
        self.w("<p>%s</p>" % self.t("s8_intro"))
        for trace in a.traces:
            when = self.local(parse_minute(trace["ts"][:16]))
            self.w("<h3>%s &rarr; <code>%s</code></h3>" % (esc(when), esc(trace["target"])))
            rows = []
            for hop in trace["hops"]:
                try:
                    loss = float(hop.get("Loss%", 0) or 0)
                except (TypeError, ValueError):
                    loss = 0.0
                rows.append([
                    esc(hop.get("count", "")),
                    "<code>%s</code>" % esc(hop.get("host", "???")),
                    ("%s %%" % esc(hop.get("Loss%", "")), "bad" if loss >= 1 else ""),
                    esc(hop.get("Avg", "")), esc(hop.get("Wrst", "")),
                ])
            self.table([self.t("th_hop"), self.t("th_address"), self.t("th_loss"),
                        self.t("th_avg_ms"), self.t("th_worst_ms")], rows)

    def section_method(self) -> None:
        a = self.a
        self.heading("s9_heading")
        self.w('<p class="method">%s</p>' % self.t(
            "s9_method", window=a.window_seconds, tz=esc(self.site.timezone)))
        self.w('<p class="method">%s</p>' % self.t("s9_raw"))
        self.table(
            [self.t("th_file"), self.t("th_size"), self.t("th_sha256")],
            [["<code>%s</code>" % esc(f["name"]), human_bytes(f["bytes"]),
              "<code>%s</code>" % esc(f["sha256"])] for f in a.files])


def build_report(analysis: Analysis, language: str | None = None) -> str:
    return ReportBuilder(analysis, language).build()
