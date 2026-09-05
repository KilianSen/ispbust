# Configuration reference

Two documents. The probe config says *what to measure*; the site config says
*how to read it*. Collection containers never see the site config, and the
report container never sees a probe config.

---

## Probe config

Full annotated examples: [`examples/probe.under-test.yaml`](../examples/probe.under-test.yaml)
and [`examples/probe.control.yaml`](../examples/probe.control.yaml).

### `wan`

| Key | Default | Meaning |
|---|---|---|
| `id` | — | Stable identifier, stamped into every row. Changing it later orphans old data. |
| `label` | `id` | Human name, printed verbatim in the report. |
| `kind` | `under_test` | `under_test` or `control`. |
| `source_ip` | unset | Bind measurements to one address. Only needed on multi-homed hosts. |

### `server`

| Key | Default | Meaning |
|---|---|---|
| `port` | `9109` | Serves `/metrics`, `/info`, `/health`, `/export/*`. |
| `export_token` | unset | Shared secret for `/export/*`. Unset means anyone who can reach the port can download the database. |

### `storage`

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | `/var/lib/ispbust` | SQLite lives here, NDJSON in `raw/`. |
| `retain_days` | `0` | Prune SQLite rows older than this. `0` keeps everything. **The NDJSON archive is never pruned.** |

### `icmp`

| Key | Default | Meaning |
|---|---|---|
| `window_seconds` | `60` | Aggregation window. One row per target per window. Values below 10 are rejected as too noisy to be persuasive. |
| `packet_interval_ms` | `1000` | 1 pps gives 1440 samples per target per day. |
| `timeout_ms` | `1500` | Per-packet timeout. |
| `event_loss_ratio` | `0.02` | Loss at or above this in one window is logged as an event. |
| `event_rtt_ms` | `250` | Mean RTT at or above this is logged as an event. |
| `targets[]` | — | `host`, `role`, optional `note`. |

**Target roles carry meaning** — the analysis groups by them:

| Role | Used for |
|---|---|
| `anchor`, `anchor_de`, `anchor_intl` | Headline loss figure and the paired comparison. **Keep these identical between the two probes.** |
| `isp_first_hop` | Loss inside the operator's own network. Added automatically by discovery. |
| `isp_resolver` | Their DNS servers, measured by ICMP as well as by query. |
| `ont_mgmt` | The modem's management address, if it answers. |
| anything else | Recorded and shown per-target, but excluded from the headline. |

### `upstream_discovery`

Traces to `via`, takes hop `hop`, and adds it as a continuously probed target.
Hop 1 is your own router; hop 2 is the operator's edge. Loss measured there is
loss inside their network, before any handover — the single most useful number
in the report. If your router adds an extra hop (double NAT, a modem in router
mode), set `hop: 3` and confirm with `mtr -n 1.1.1.1`.

**The candidate has to answer pings before it is adopted.** Many operator
routers — carrier-grade NAT gateways especially — reply to TTL-exceeded, so
they appear in a traceroute, while silently dropping ICMP echo addressed to
themselves. Probing one of those would record a permanent 100 % loss that is an
artefact of its ICMP policy rather than a fault, and putting that number in
front of an operator would be worse than useless. If the discovered hop does
not answer, the probe logs a warning, records an `upstream_hop_no_echo` marker,
and leaves it alone; the report then omits the first-hop section entirely.

You are not left with nothing in that case: the scheduled `mtr` runs still
record per-hop loss for that address using TTL-exceeded, and those appear in
the report's path-measurement section. It is also worth asking your operator
whether they will enable ICMP echo on your gateway for diagnostics — some
will.

### `dns`

Queries each resolver in turn, rotating through `names` so a cached answer
cannot hide a broken resolver. List the operator's resolvers *and* public ones:
the comparison is what separates "the line is broken" from "their resolvers are
broken".

### `reachability`

Opens a real connection to real sites, separately over each address family,
and records what happened: did the name resolve, did the socket connect, did
TLS complete, what status came back.

This exists because packet loss and reachability are different questions. A
site with AAAA records, on a network whose IPv6 routing is broken, fails in
the browser while every ICMP measurement stays at 0 % loss — the browser tries
IPv6 first, and the pings never did. Nothing else in this tool can see that.

| Key | Default | Meaning |
|---|---|---|
| `interval_seconds` | `120` | How often each site is checked. |
| `timeout_seconds` | `10` | Per-attempt budget, connect and TLS together. |
| `families` | `[ipv4, ipv6]` | Which address families to try. |
| `targets[]` | — | `host`, optional `port` (443) and `tls`. |

Two events come out of it:

- **`address_family_broken`** — one family resolves but will not connect while
  another works. This is the one users feel as "the site doesn't load", and it
  names the family, the address and the error.
- **`site_unreachable`** — no family could complete a request.

A family with no record for a host is not a fault and is never reported as
one: an IPv4-only site is simply IPv4-only.

Resolution deliberately goes to DNS directly rather than through
`getaddrinfo`. A host whose IPv6 is broken can return "no such record" for an
AAAA lookup instead of the record, which would make the check go quiet on
exactly the machine that has the problem.

### `tcp` and `traceroute`

TCP connect and TLS handshake timings are what an application actually feels.
`traceroute.on_event: true` captures the path the moment loss is detected — a
traceroute taken afterwards shows nothing, which is why this is triggered
rather than only scheduled. `traceroute.enabled: false` turns off both the
scheduled and the triggered captures.

---

## Site config

Full annotated example: [`examples/site.yaml`](../examples/site.yaml).

### `site`

`name`, `timezone` (IANA, e.g. `Europe/Berlin`), `language` (`de` or `en`),
`isp_name`, `customer_ref` (printed on the report — put your account number
here), and optional `contract_downstream_mbps` / `contract_upstream_mbps` for
context.

### `probes[]`

Each entry needs `id`, `label`, `kind`, and either:

- `url` — the probe's HTTP endpoint, plus `token` matching its `export_token`; or
- `db` — a path to a database file, for working from an archive or a
  single-host setup.

Exactly one probe must be `kind: under_test`. Controls are optional but the
report is dramatically weaker without one: the paired comparison is the part an
operator cannot argue with.

### `thresholds`

| Key | Default | Meaning |
|---|---|---|
| `degraded_loss` | `0.05` | A minute at or above this counts as degraded and feeds the outage runs. |
| `blackout_loss` | `0.999` | A minute at or above this counts as a total outage. |

Raising `degraded_loss` makes the report more conservative and harder to
dismiss. Lowering it below about 1 % invites the reply that you are counting
normal internet behaviour.

### `experiment`

A/B test of a daily intervention — see [03-escalation.md](03-escalation.md).
`enabled: true` requires a non-zero `seed`, deliberately: the schedule has to
be fixed in advance for the result to mean anything.

---

## Environment overrides

Useful for running the same config file in several containers. All are prefixed
`ISPBUST_`:

| Variable | Overrides |
|---|---|
| `ISPBUST_WAN_ID`, `ISPBUST_WAN_LABEL`, `ISPBUST_WAN_KIND` | `wan.*` |
| `ISPBUST_SOURCE_IP` | `wan.source_ip` |
| `ISPBUST_PORT`, `ISPBUST_EXPORT_TOKEN` | `server.*` |
| `ISPBUST_DATA_DIR`, `ISPBUST_RETAIN_DAYS` | `storage.*` |
| `ISPBUST_SITE_NAME`, `ISPBUST_TZ_NAME`, `ISPBUST_LANGUAGE` | `site.*` |
| `ISPBUST_CONFIG`, `ISPBUST_SITE`, `ISPBUST_REPORTS_DIR` | default file paths |
| `ISPBUST_INTERVAL`, `ISPBUST_REPORT_DAYS`, `ISPBUST_SERVE_PORT` | `serve` behaviour |
| `ISPBUST_LOG` | log level (`DEBUG`, `INFO`, …) |

---

## Probe HTTP API

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | no | `ok` |
| `GET /info` | no | probe identity, row counts, first and last timestamps |
| `GET /metrics` | no | Prometheus exposition |
| `GET /export/sqlite` | token | database snapshot; `?from=&to=` filters by date |
| `GET /export/ndjson?date=YYYY-MM-DD` | token | the raw archive for one day |
| `GET /export/list` | token | which days the archive holds |

Snapshots use SQLite's `VACUUM INTO`, so they are internally consistent even
while the probe keeps writing.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://10.0.61.10:9109/export/sqlite?from=2026-08-01&to=2026-08-31" \
  -o august.sqlite
```

---

## Commands

```
ispbust probe        run the collection daemon                 (collection image)
ispbust check        validate configs and print what they do
ispbust fetch        pull snapshots from the probes            (report image)
ispbust report       build the fault report
ispbust summary      headline numbers, optionally as JSON
ispbust serve        rebuild on a schedule and serve over HTTP
ispbust experiment   plan | run | analyse the A/B test
ispbust demo         synthetic data plus a sample report
ispbust selftest     end-to-end check of analysis and rendering
```

Every command takes `--help`. `report`, `summary` and `experiment` default to
the last 30 days ending yesterday.

---

## Adding a language

Add your language key to each entry in
[`src/ispbust/report/strings.py`](../src/ispbust/report/strings.py). Nothing
else in the renderer is language-aware, and any string you miss falls back to
English rather than crashing. `ispbust selftest` renders every language it
finds, so a missing placeholder shows up immediately.
