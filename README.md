# ispbust

[![CI](https://github.com/KilianSen/ispbust/actions/workflows/ci.yml/badge.svg)](https://github.com/KilianSen/ispbust/actions/workflows/ci.yml)
[![Docker images](https://github.com/KilianSen/ispbust/actions/workflows/docker.yml/badge.svg)](https://github.com/KilianSen/ispbust/actions/workflows/docker.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Prove your internet connection is faulty, with evidence a support desk cannot
deflect.

ispbust measures two uplinks continuously and side by side, then produces a
single self-contained document showing that one of them is broken and the other
is not — same network, same targets, same minute, different uplink. That
comparison closes off "the problem is on your side" before anyone raises it.

It is vendor-neutral: it knows about a *link under test* and a *control*, and
nothing about who sells you either.

```
  uplink under test ──► ispbust-probe ─┐
                                       ├──► ispbust-report ──► report.html
  control uplink ─────► ispbust-probe ─┘         :8080         (+ Grafana)
```

---

## Two images

| Image | Job |
|---|---|
| **`ispbust-probe`** | One container per uplink. Measures continuously, stores locally, serves `/metrics` and `/export/*`. |
| **`ispbust-report`** | Pulls snapshots from the probes, analyses them, renders the report, serves it on a schedule. |

One binary (`ispbust`), one config format, nothing to keep in sync between
them. Probes can sit on isolated VLANs — the report container reaches them over
HTTP, so there is no shared storage and no SSH between hosts.

## See the output before you build anything

```bash
pip install .
ispbust demo --out-dir ./demo          # synthetic data + a sample report
# open demo/report.html
ispbust demo --out-dir ./demo --language de
```

The demo models a genuinely awkward fault — a link that degrades with uptime
*and* misbehaves for hours after a restart — because that is the case where the
report has to do real work.

## Run it for real

```bash
export ISPBUST_EXPORT_TOKEN="$(openssl rand -hex 24)"
cp examples/*.yaml .          # edit labels, probe URLs, timezone, language
cd docker && docker compose up -d
```

Images are built from `master` by CI for `linux/amd64` and `linux/arm64` (so a
Raspberry Pi works as a probe host):

```
ghcr.io/kiliansen/ispbust-probe:latest
ghcr.io/kiliansen/ispbust-report:latest
```

Report at `http://<host>:8080`. Add `--profile metrics` for Prometheus and
Grafana. Full instructions, including the Proxmox and macvlan layouts, in
[docs/01-deployment.md](docs/01-deployment.md).

---

## What it measures

Per uplink, continuously, from identical containers:

- **ICMP** at 1 packet/second/target, aggregated per minute — to neutral
  anchors and, crucially, to **the operator's own first hop**, discovered
  automatically. Loss measured there is loss inside their network, before any
  handover to anyone else.
- **DNS** against the operator's resolvers *and* public ones, so "their
  resolvers are broken" is distinguishable from "the line is broken".
- **TCP connect and TLS handshake** timings — what an application actually
  feels.
- **Verification that the probe is still on the uplink it claims**, by asking
  external services which address its traffic arrived from. A probe silently
  failed over to the backup reports a healthy line throughout the outage it was
  meant to record; this is what catches that.
- **Real connections to real sites, per address family** — because loss and
  reachability are different questions. A dual-stack site on a network with
  broken IPv6 routing fails in the browser while every ping stays at 0 % loss.
- **mtr** on a schedule, plus a path snapshot triggered the instant loss
  appears. A traceroute taken afterwards shows nothing.

Everything lands in SQLite (queryable), append-only NDJSON (the archive you
hand over), and Prometheus (the live view only — the evidence survives a
Prometheus wipe).

## What it concludes

The report does not stop at tables. It states what the measurements support —
whether the fault is isolated to the link under test, whether the loss sits
inside the operator's own network, whether the shape over the day reads as
congestion or as a fault, whether an address family is broken, whether the
operator's resolvers are at fault rather than the line, and whether a nightly
restart is curing the problem or causing it.

Every finding names the figures it rests on, because a conclusion a reader
cannot check is worth less than none. The findings that decline to conclude
anything matter as much as the rest: no control link, too short a period, both
links bad at once. And if the egress check found the probe on the wrong uplink,
the assessment withholds its conclusions entirely rather than describing the
wrong connection with confidence.

## What comes out

A single HTML file, no external assets, prints straight to PDF:

1. Headline figures — loss, total-outage minutes, fault events
2. The paired comparison against the control link
3. Loss to the operator's own first hop
4. Per-day breakdown, ranked outage events with the control's figure alongside
5. Loss by time of day — separates congestion from a hardware fault
6. DNS statistics per resolver
7. Path measurements captured during faults
8. Method, and SHA-256 hashes of the exact raw files it was built from

German and English included; adding a language means adding one key per string
and nothing else ([docs/02-configuration.md](docs/02-configuration.md)).

---

## The one rule

> **Each probe must leave the host over exactly one uplink, with failover
> disabled.**

A probe that fails over records a healthy line at precisely the moment the line
breaks. [docs/01-deployment.md](docs/01-deployment.md) has a physical
verification step — unplug the link under test, confirm its probe goes
completely dark. Re-run it after every router firmware update.

## Testing a nightly modem restart

If you power-cycle a modem on a timer, you probably do not know whether it is
helping. The symptom pattern fits both "the restart fixes a device that
degrades" and "the restart triggers a re-registration that costs hours" — and
those call for opposite actions.

```bash
ispbust experiment plan --days 28 > schedule.txt   # commit in advance
ispbust experiment analyse --since 2026-09-01      # after two weeks
```

Arms are derived from a fixed seed, so the schedule cannot drift to fit the
result. That property is what makes the outcome evidence rather than an
anecdote.

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

## Layout

```
src/ispbust/          the tool: collectors, storage, HTTP, analysis, report
  report/             renderer, charts, per-language strings, stylesheet
docker/               both Dockerfiles, compose stack, Prometheus + Grafana
packaging/            native install: systemd and OpenRC units, install.sh
examples/             annotated probe and site configs
tools/                optional vendor helpers (UniFi discovery, modem probing)
docs/                 deployment, configuration, escalation, modem diagnostics
tests/                end-to-end tests including the probe/report HTTP seam
```

## Documentation

- [Deployment](docs/01-deployment.md) — topologies, Docker, and verifying the pinning
- [Configuration](docs/02-configuration.md) — both config files, the HTTP API, adding a language
- [Using the evidence](docs/03-escalation.md) — diagnosing the cause, what to demand, escalation
- [Modem diagnostics](docs/04-modem-diagnostics.md) — getting signal levels out of the operator's box

## Requirements

Probes need `fping`, `mtr` and `CAP_NET_RAW` (both are in the image). The
report side is Python 3.11+ with PyYAML, prometheus-client and dnspython.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ispbust selftest
```

## Licence

MIT.
