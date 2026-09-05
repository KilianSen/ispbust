# Deployment

Two images, one job each:

| Image | Runs | Needs |
|---|---|---|
| `ispbust-probe` | one container per uplink, continuously | `CAP_NET_RAW`, a pinned route, a volume |
| `ispbust-report` | anywhere on the network | HTTP access to the probes |

---

## The one rule

> **Each probe must leave the host over exactly one uplink, with failover
> disabled.**

A probe that fails over records a healthy line at precisely the moment the line
breaks. Everything below exists to guarantee that, and there is a verification
step at the end that you should not skip.

---

## Topology A — one host per uplink (recommended)

Simplest and hardest to get wrong. Each probe runs on a machine whose default
route *is* the uplink being measured: a small VM, an LXC container, a Raspberry
Pi. The probe uses `network_mode: host` and needs no special networking.

```
                  ┌─ VM/LXC/Pi ──────────┐
   uplink A ──────┤ ispbust-probe (wan-a)│──┐
                  └──────────────────────┘  │
                  ┌─ VM/LXC/Pi ──────────┐  ├── ispbust-report ──► :8080
   uplink B ──────┤ ispbust-probe (wan-b)│──┘      (anywhere)
                  └──────────────────────┘
```

On the router, policy-route each probe host to its uplink and **disable
failover on that route**. On UniFi this lives under *Settings → Routing →
Traffic Routes*; the toggle is variously called "Failover", "Fallback to
default interface" or "Use default route if interface is down". Also exclude
these hosts from any load-balancing policy.

### Proxmox example

```bash
pct create 161 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname probe-a --cores 1 --memory 512 --swap 512 --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,tag=61,ip=10.0.61.10/24,gw=10.0.61.1 \
  --features nesting=1 --onboot 1 --start 1
```

`--onboot 1` matters. A probe that does not come back after a host reboot
leaves a hole in the record, and a hole is the first thing a support desk will
point at.

Running the probes on **different physical hosts** is worth the effort — it
removes the "your one server was broken" objection entirely.

## Topology B — one host, macvlan per VLAN

If you would rather run everything on one machine, give each probe its own
macvlan interface on a VLAN that the router pins to one uplink. The commented
`networks:` block at the bottom of `docker/docker-compose.yml` has the shape.

Note that macvlan interfaces cannot talk to their own host — fine here, since
the report container reaches the probes over the LAN.

---

## Bring it up

```bash
git clone <this repo> ispbust && cd ispbust

# 1. shared export token, so probes do not hand their data to anyone who asks
export ISPBUST_EXPORT_TOKEN="$(openssl rand -hex 24)"

# 2. copy and edit the configs, then point compose at them
mkdir -p config
cp examples/probe.under-test.yaml examples/probe.control.yaml examples/site.yaml config/
#    - probe configs: label, and your ISP's resolvers (tools/unifi-discover.sh finds them)
#    - site.yaml: probe URLs, the same token, timezone, language, customer reference
cp docker/.env.example docker/.env
#    - set UNDER_TEST_CONFIG=../config/probe.under-test.yaml (and the other two)

# 3. validate before starting anything
docker run --rm -v "$PWD/config/probe.under-test.yaml:/c.yaml:ro" \
  ispbust-probe:1.0.0 check --probe /c.yaml

# 4. start
cd docker
docker compose up -d probe-under-test          # on the host pinned to uplink A
docker compose up -d probe-control             # on the host pinned to uplink B
docker compose up -d report                    # anywhere

# 5. optional live dashboards
docker compose --profile metrics up -d
```

Report service on `http://<host>:8080`, Grafana on `:3000`, Prometheus on
`:9090`.

### Without compose

```bash
docker run -d --name ispbust-probe --restart unless-stopped \
  --network host --cap-add NET_RAW \
  -v ispbust-data:/var/lib/ispbust \
  -v "$PWD/config/probe.under-test.yaml:/etc/ispbust/probe.yaml:ro" \
  -e ISPBUST_EXPORT_TOKEN="$ISPBUST_EXPORT_TOKEN" \
  ispbust-probe:1.0.0

docker run -d --name ispbust-report --restart unless-stopped \
  -p 8080:8080 \
  -v ispbust-reports:/reports -v ispbust-fetched:/data \
  -v "$PWD/config/site.yaml:/etc/ispbust/site.yaml:ro" \
  ispbust-report:1.0.0 serve
```

### Without Docker

Useful on a small VM or a Raspberry Pi that exists only to be a probe, where a
container runtime is more machinery than the job needs. Handles Debian/Ubuntu
(apt + systemd) and Alpine (apk + OpenRC), and is idempotent — re-run it to
upgrade and your config is left alone.

```bash
git clone https://github.com/KilianSen/ispbust && cd ispbust
sudo packaging/install.sh config/probe.under-test.yaml
```

It installs `fping`, `mtr` and `chrony`, grants the probing binaries
`cap_net_raw` so the probe itself runs unprivileged, creates a venv under
`/opt/ispbust`, generates an export token if the config has an empty one,
installs the service and log rotation, and starts it.

`chrony` is not optional politeness: timestamps are the evidence, and the
paired comparison buckets by minute, so a probe with an unsynchronised clock
quietly corrupts the comparison against the other link.

Service units live in [`packaging/`](../packaging) if you would rather install
by hand.

---

## Verify the pinning — do not skip this

On each probe host:

```bash
curl -s https://api.ipify.org; echo    # must differ between the two probes
mtr -n -c 3 --report 1.1.1.1           # hop 2 must be the expected operator
```

Then the test that actually matters:

1. Unplug the uplink under test (or disable that WAN on the router).
2. On the probe under test, `ping 1.1.1.1` must **fail completely**.
   If it still succeeds, the probe is failing over and every measurement you
   take is worthless. Fix the routing before going further.
3. On the control probe, ping must keep working.
4. Plug it back in.

Re-run this after every router firmware update. Firmware updates have been
known to quietly reset policy-route settings.

### IPv6 is probably not pinned, and that changes what the numbers mean

Policy routing on consumer gateways — UniFi included — is usually IPv4-only.
If your LAN has IPv6, check where it actually goes:

```bash
# on each probe: which source address does the far end see?
python3 -c "import urllib.request;print(urllib.request.urlopen('https://api6.ipify.org',timeout=10).read().decode())"
```

If both probes report an address from the **same** prefix, their IPv6 traffic
is leaving by the same uplink regardless of the IPv4 pin, and the control link
is not a control for IPv6. Treat the IPv6 rows as measurements of whichever
uplink owns that prefix, and lean on the IPv4 comparison for anything you put
in front of an operator.

There is a sharper consequence if your LAN prefix is delegated from one ISP.
IPv6 then has **no failover**: an address delegated by operator A cannot be
routed out of operator B, whose network will drop it at the edge. So when A
fails, IPv4 fails over and the connection looks alive, while IPv6 stays
pointed at the dead uplink. Every dual-stack site breaks in the browser —
users report "the site does not load at all" while every ping still succeeds.
The `reachability` collector is what makes that visible; see
[02-configuration.md](02-configuration.md).

---

## Check that data is arriving

```bash
# what each probe holds, from the report container's point of view
docker compose exec report ispbust fetch --info

# headline numbers without building a document
docker compose exec report ispbust summary --from 2026-09-01 --to 2026-09-07

# straight from a probe
curl -s http://10.0.61.10:9109/info | python -m json.tool
curl -s http://10.0.61.10:9109/metrics | grep ispbust_icmp_loss_ratio
```

---

## Backups

The measurement archive is the deliverable. Losing it means starting over.

```bash
# the NDJSON archive is append-only and compresses extremely well
docker run --rm -v ispbust-data:/data -v "$PWD/backup:/backup" \
  debian:12-slim tar czf /backup/ispbust-$(date +%F).tar.gz -C /data .
```

Keep the raw files untouched — the SHA-256 hashes printed in the report refer
to them, and that chain is what makes the document hard to wave away.

---

## Upgrading

Probe databases carry their schema with them and new columns are additive, so
a rolling upgrade is safe:

```bash
docker compose pull && docker compose up -d
```

Take a backup first anyway. You cannot re-measure last month.
