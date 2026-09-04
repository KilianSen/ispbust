"""Inline SVG charts.

Hand-rolled rather than matplotlib: the report has to be a single file with no
external assets, print cleanly, and be readable in an email client. That rules
out a plotting library and a PNG, and it turns out a bar chart is about forty
lines of arithmetic.

Every bar carries a <title>, so hovering in a browser gives the exact figure
while the printed version stays clean.
"""

from __future__ import annotations

import html

PALETTE = {
    "primary": "var(--primary)",
    "control": "var(--control)",
}


def _escape(value) -> str:
    return html.escape(str(value))


def _nice_top(values: list, minimum: float = 0.02) -> float:
    """Pick an axis maximum with a little headroom above the tallest bar."""
    peak = max(values) if values else 0.0
    return max(minimum, peak * 1.15)


def _axis_labels(top: float, fractions=(0, 0.25, 0.5, 0.75, 1.0)) -> list:
    return [(f, top * f) for f in fractions]


def empty(message: str) -> str:
    return '<p class="empty">%s</p>' % _escape(message)


def grouped_bars(categories: list, series: list, title: str,
                 width: int = 900, height: int = 280, max_labels: int = 20) -> str:
    """Bar chart with one group per category and one bar per series.

    `series` is a list of {"name", "cls", "values"} where values align with
    categories and are fractions (0..1).
    """
    if not categories or not series:
        return empty(title)

    pad_l, pad_r, pad_t, pad_b = 58, 12, 16, 54
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    all_values = [v for s in series for v in s["values"] if v is not None]
    top = _nice_top(all_values)
    slot = plot_w / len(categories)
    bar_w = min(18.0, slot / (len(series) + 1.4))

    out = ['<svg viewBox="0 0 %d %d" width="100%%" height="%d" class="chart" role="img" '
           'aria-label="%s" xmlns="http://www.w3.org/2000/svg">' % (width, height, height, _escape(title))]

    for frac, value in _axis_labels(top):
        y = pad_t + plot_h * (1 - frac)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>'
                   % (pad_l, y, width - pad_r, y))
        out.append('<text x="%.1f" y="%.1f" class="ax" text-anchor="end">%.1f%%</text>'
                   % (pad_l - 6, y + 4, value * 100))

    label_every = max(1, len(categories) // max_labels)
    for i, category in enumerate(categories):
        centre = pad_l + slot * (i + 0.5)
        offset = -bar_w * len(series) / 2
        for s in series:
            value = s["values"][i] if i < len(s["values"]) else None
            if value is not None:
                bar_h = plot_h * (value / top) if top else 0
                out.append(
                    '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="%s">'
                    '<title>%s — %s: %.2f%%</title></rect>'
                    % (centre + offset, pad_t + plot_h - bar_h, bar_w, max(bar_h, 0.6),
                       s["cls"], _escape(category), _escape(s["name"]), value * 100))
            offset += bar_w * 1.1
        if i % label_every == 0:
            out.append('<text x="%.1f" y="%.1f" class="ax" text-anchor="end" '
                       'transform="rotate(-55 %.1f %.1f)">%s</text>'
                       % (centre, height - pad_b + 16, centre, height - pad_b + 16,
                          _escape(category)))

    out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="axis"/>'
               % (pad_l, pad_t + plot_h, width - pad_r, pad_t + plot_h))
    out.append("</svg>")
    return "".join(out)


def single_bars(points: list, title: str, axis_title: str = "",
                width: int = 900, height: int = 260) -> str:
    """Bar chart for a fixed sequence.

    `points` is a list of {"label", "value", "tooltip"} where value is a
    fraction (0..1).
    """
    if not points or not any(p["value"] for p in points):
        return empty(title)

    pad_l, pad_r, pad_t = 58, 12, 16
    pad_b = 46 if axis_title else 30
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    top = _nice_top([p["value"] for p in points])
    slot = plot_w / len(points)

    out = ['<svg viewBox="0 0 %d %d" width="100%%" height="%d" class="chart" role="img" '
           'aria-label="%s" xmlns="http://www.w3.org/2000/svg">' % (width, height, height, _escape(title))]

    for frac, value in _axis_labels(top, (0, 0.5, 1.0)):
        y = pad_t + plot_h * (1 - frac)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>'
                   % (pad_l, y, width - pad_r, y))
        out.append('<text x="%.1f" y="%.1f" class="ax" text-anchor="end">%.1f%%</text>'
                   % (pad_l - 6, y + 4, value * 100))

    for i, point in enumerate(points):
        x = pad_l + slot * i
        bar_h = plot_h * (point["value"] / top) if top else 0
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="bar-primary">'
                   '<title>%s</title></rect>'
                   % (x + slot * 0.15, pad_t + plot_h - bar_h, slot * 0.7, max(bar_h, 0.6),
                      _escape(point.get("tooltip", point["label"]))))
        out.append('<text x="%.1f" y="%.1f" class="ax" text-anchor="middle">%s</text>'
                   % (x + slot * 0.5, height - pad_b + 16, _escape(point["label"])))

    if axis_title:
        out.append('<text x="%.1f" y="%.1f" class="ax-title" text-anchor="middle">%s</text>'
                   % (pad_l + plot_w / 2, height - 6, _escape(axis_title)))
    out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="axis"/>'
               % (pad_l, pad_t + plot_h, width - pad_r, pad_t + plot_h))
    out.append("</svg>")
    return "".join(out)
