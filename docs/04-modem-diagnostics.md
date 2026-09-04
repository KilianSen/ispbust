# Reading the fibre modem

If you can get **optical receive power** out of the ONT, you have the strongest
single number in the whole project. Everything else measures the *symptom*;
Rx power measures the *cause*, and a level that drifts down over weeks is a
physical fault that cannot be argued with.

## What you have

You identified the box as looking like a **BKtel XON1500** (BKtel is now part of
HUBER+SUHNER; the XON1500 is an FTTH customer termination unit, and the series
included variants with CATV/SAT overlay). Confirm the exact model from the
label when you are next on site — photograph the label including the serial and
any GPON ID, since you will need those identifiers later either way.

Your WAN is plain DHCP with no credentials ever entered, which means the box is
already acting as a **bridge**. That is good news for the SFP plan: there is no
PPPoE session to migrate.

## Getting data out of it

```bash
./tools/modem-probe.sh                  # scan the usual management addresses
./tools/modem-probe.sh 192.168.100.1    # or a known one
```

Run it from a host on the segment between the ONT and the UDM Pro, or from the
UDM Pro itself. If nothing responds, the management address probably sits on a
subnet your interface has no address in. On the UDMP:

```bash
ip addr add 192.168.100.2/24 dev eth8    # use the actual DG WAN interface
./tools/modem-probe.sh 192.168.100.1
ip addr del 192.168.100.2/24 dev eth8    # tidy up
```

`tools/unifi-discover.sh` tells you which interface is the DG WAN.

## What to record, and how often

Once a day is enough, at a fixed time. Log it and keep every reading — a single
value proves nothing, a downward trend over six weeks proves a lot.

| Value | Healthy | Meaning |
|---|---|---|
| Rx optical power | roughly −15 to −25 dBm | below about −27 dBm the link is marginal |
| Tx optical power | per spec of the module | rarely the problem, but record it |
| FEC corrected / uncorrected blocks | flat | rising = dirty or damaged link |
| BIP errors | flat | same |
| GPON state | O5 | anything else is a re-ranging event |
| LOS / LOF counters | 0 | each increment is a physical dropout |
| ONT uptime | matches your reboot schedule | unexplained resets are a finding |

If the ONT exposes a web UI, save the status page HTML each day rather than
transcribing numbers — `modem-probe.sh` already does this, timestamped, into
`ont-evidence/`.

## If it tells you nothing

Quite likely: DG-supplied units are often locked down. That is not a dead end,
it is an argument.

- **It becomes evidence for your case.** A sealed modem exposing no diagnostics
  means neither side can see the physical layer. Say exactly that when you ask
  for your own ONT: you are asking for the ability to diagnose your own line.
- **Ask DG to read the OLT side instead.** They have all of it — Rx power for
  your ONT, error counters, the deactivation/reactivation log. Requesting it in
  writing is worth doing regardless of whether they answer, because the
  request and the answer both become part of the record.

The list of what to request, and how to phrase it, is in
[03-escalation.md](03-escalation.md).

## A GPON SFP would solve this permanently

Sticks like the FS.com GPON-ONU-34-20BI expose their own optical readings over
SSH or a serial console, which means you could monitor Rx power continuously
and alert on drift — instead of discovering the degradation weeks later through
its symptoms. Worth mentioning to DG: a customer who can see their own optical
budget generates fewer support calls, not more.
