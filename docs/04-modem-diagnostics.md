# Reading the operator's modem

If you can get **signal levels** out of the box on your wall, you have the
strongest single number in the whole project. Everything else here measures the
*symptom*; the signal level measures the *cause*, and a level that drifts over
weeks is a physical fault that is very hard to argue with.

On fibre that means optical receive power at the ONT. On DSL it is SNR margin
and attenuation; on cable, downstream/upstream power and SNR. The principle is
the same in each case: one reading proves nothing, a trend proves a lot.

## Identify the box first

Photograph the label, including the model number, the serial, and any
technology-specific identifier (a GPON serial, a CM MAC). You will need those
identifiers whether you end up diagnosing the line, escalating, or asking to
substitute your own equipment.

Two things worth establishing early:

- **Is it bridging or routing?** If you have never entered access credentials
  and your own router picks up an address by DHCP, the box is bridging. That is
  simpler to reason about, and it means there is no session to migrate if you
  later replace it.
- **Does it expose anything at all?** Many operator-supplied units are locked
  down. Find out before you build a plan around its readings.

## Getting data out of it

```bash
./tools/modem-probe.sh                  # scan the usual management addresses
./tools/modem-probe.sh 192.168.100.1    # or a known one
```

Run it from a host on the segment between the modem and your router, or from
the router itself. It records everything it finds, timestamped, into
`ont-evidence/` — including the raw status pages, so you are not
re-transcribing numbers by hand.

If nothing responds, the management address probably sits on a subnet your
interface has no address in. Add one temporarily:

```bash
ip addr add 192.168.100.2/24 dev <wan-interface>
./tools/modem-probe.sh 192.168.100.1
ip addr del 192.168.100.2/24 dev <wan-interface>
```

On UniFi gateways, `tools/unifi-discover.sh` tells you which interface is which
WAN. Elsewhere, `ip route get 1.1.1.1` names it.

## What to record, and how often

Once a day at a fixed time is enough. Keep every reading; the trend is the
evidence.

### Fibre (GPON/XGS-PON)

| Value | Healthy | Meaning |
|---|---|---|
| Rx optical power | roughly −15 to −25 dBm | below about −27 dBm the link is marginal |
| Tx optical power | per the module's spec | rarely the problem, but record it |
| FEC corrected / uncorrected blocks | flat | rising means a dirty or damaged link |
| BIP errors | flat | same |
| PON state | O5 | anything else is a re-ranging event |
| LOS / LOF counters | 0 | each increment is a physical dropout |
| Modem uptime | matches your expectations | unexplained resets are a finding |

### DSL

| Value | Meaning |
|---|---|
| SNR margin (dB) | falling margin over weeks is the classic degrading-line signature |
| Line attenuation (dB) | should be stable; a change means something physical moved |
| CRC / FEC / ES / SES counters | rising counts are errors reaching your traffic |
| Retrains / resyncs | each one is a dropped connection |

### Cable (DOCSIS)

| Value | Healthy | Meaning |
|---|---|---|
| Downstream power | roughly −7 to +7 dBmV | outside that, the segment is mis-levelled |
| Downstream SNR/MER | above ~33 dB for QAM256 | falling SNR precedes uncorrectables |
| Upstream power | roughly 35–50 dBmV | high values mean the modem is straining |
| Correctable / uncorrectable codewords | uncorrectables should be ~0 | these are your lost packets |
| T3 / T4 timeouts | 0 | each is a lost upstream conversation |

## If it tells you nothing

Common, and not a dead end — it is an argument.

- **It becomes part of your case.** A sealed modem that exposes no diagnostics
  means neither side can see the physical layer. Say exactly that if you ask to
  use your own equipment: you are asking for the ability to diagnose your own
  line.
- **Ask the operator to read their side instead.** They have all of it: signal
  levels for your line, error counters, and the deactivation/reactivation log.
  Request it in writing whether or not you expect an answer — the request and
  the response both become part of the record.

What to ask for, and how to phrase it, is in
[03-escalation.md](03-escalation.md).

## Substituting your own modem

Where regulation permits it and the operator supports it, customer-supplied
modems are usually far more transparent. A GPON SFP stick, for instance,
typically exposes its own optical readings over SSH or a serial console, so you
can monitor receive power continuously and alert on drift instead of
discovering degradation weeks later through its symptoms.

Two cautions:

- **Check whether it would actually help.** If the fault is in the line rather
  than the box, replacing the box changes nothing — see the cause table in
  [03-escalation.md](03-escalation.md).
- **Document the fault first.** Swapping hardware before the fault is on record
  hands the operator a permanent deflection: *"you are not using our
  equipment."* Keep the original box, too, so you can put it back within
  minutes.
