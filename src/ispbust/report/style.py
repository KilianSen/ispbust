"""The report's stylesheet.

Print is the primary medium: this document gets attached to a support ticket
and, if it goes further, printed. So the page is sized for A4, tables avoid
breaking across pages, and nothing depends on a web font or a colour that
disappears in greyscale.
"""

CSS = """
:root{
  --ink:#12161c; --muted:#5a6673; --line:#d7dde5; --bg:#fff;
  --primary:#c0392b; --control:#2b6cb0; --good:#1f7a4d; --warn-bg:#fff4e5; --warn-line:#d99a2b;
}
*{box-sizing:border-box}
body{
  margin:0 auto;padding:32px;max-width:1000px;background:var(--bg);color:var(--ink);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:18px;margin:34px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
h3{font-size:15px;margin:20px 0 6px}
p{margin:8px 0}
.sub{color:var(--muted);margin:0 0 20px}

table{border-collapse:collapse;width:100%;margin:12px 0;font-variant-numeric:tabular-nums}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{background:#f2f5f8;font-weight:600}
tbody tr:nth-child(even){background:#fafbfc}
.wrap{overflow-x:auto}

.bad{color:var(--primary);font-weight:600}
.ok{color:var(--good)}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:#fafbfc}
.kpi .v{font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.1}
.kpi .l{color:var(--muted);font-size:12px;margin-top:4px}
.kpi.alarm{border-color:var(--primary);background:#fdf2f0}
.kpi.alarm .v{color:var(--primary)}

.chart{display:block;margin:10px 0;border:1px solid var(--line);border-radius:6px;background:#fff}
.grid{stroke:#e8edf2;stroke-width:1}
.axis{stroke:#98a4b0;stroke-width:1}
.ax{font-size:10px;fill:var(--muted)}
.ax-title{font-size:11px;fill:var(--muted)}
.bar-primary{fill:var(--primary)}
.bar-control{fill:var(--control)}

.legend{display:flex;gap:18px;font-size:12px;color:var(--muted);margin:6px 0 0}
.legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}

.note{background:var(--warn-bg);border-left:3px solid var(--warn-line);padding:10px 14px;
      margin:14px 0;border-radius:0 6px 6px 0}
.method{color:var(--muted);font-size:13px}
.empty{color:var(--muted);font-style:italic}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;
     background:#f2f5f8;padding:1px 5px;border-radius:3px}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);
       color:var(--muted);font-size:12px}

@media print{
  body{padding:0;font-size:11.5px;max-width:none}
  h2{page-break-after:avoid}
  table,.chart,.kpi,.note{page-break-inside:avoid}
  .wrap{overflow:visible}
}
"""
