#!/usr/bin/env bash
# Identify the operator-supplied modem and pull whatever it will tell us about
# the physical link. Signal levels and error counters are the strongest single
# piece of evidence available: a drifting optical receive power, a falling SNR
# margin or a rising error count is a physical-layer fault that no amount of
# "have you rebooted it" can explain away.
#
# Run from a host on the segment between the modem and your router, or from the
# router itself. Read-only: it never writes to the device.
#
#   ./modem-probe.sh                 # scan the usual management addresses
#   ./modem-probe.sh 192.168.100.1   # probe a known address
#
# If nothing answers, the modem's management address may live on a subnet your
# interface has no address in. Add a secondary address first:
#   ip addr add 192.168.100.2/24 dev <wan-interface>   # remove it afterwards
set -uo pipefail

OUT_DIR="${ONT_OUT_DIR:-./ont-evidence}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUT_DIR/ont-$STAMP.txt"

CANDIDATES=("$@")
if [ ${#CANDIDATES[@]} -eq 0 ]; then
  CANDIDATES=(192.168.100.1 192.168.1.1 192.168.0.1 192.168.10.1 10.0.0.1 169.254.1.1)
fi

say() { echo "$@" | tee -a "$LOG"; }

say "ispbust ONT probe -- $STAMP"
say "output: $LOG"
say

for ip in "${CANDIDATES[@]}"; do
  say "=== $ip ==="
  if ! ping -c 2 -W 2 "$ip" >/dev/null 2>&1; then
    say "  no ICMP response"
    say
    continue
  fi
  say "  responds to ping"

  # ARP entry identifies the vendor via the OUI -- worth recording even if
  # every management port is closed.
  mac="$(ip neigh show "$ip" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="lladdr") print $(i+1)}')"
  [ -n "$mac" ] && say "  MAC: $mac  (OUI $(echo "$mac" | cut -c1-8) -- look up the vendor)"

  for port in 80 443 22 23 161 8080; do
    if command -v nc >/dev/null 2>&1 && nc -z -w2 "$ip" "$port" 2>/dev/null; then
      say "  tcp/$port open"
    fi
  done

  for scheme in http https; do
    body="$OUT_DIR/${ip}-${scheme}-$STAMP.html"
    code="$(curl -sk -m 8 -o "$body" -w '%{http_code}' "$scheme://$ip/" 2>/dev/null)"
    if [ "$code" != "000" ] && [ -n "$code" ]; then
      say "  $scheme:// -> HTTP $code, $(wc -c <"$body") bytes -> $(basename "$body")"
      title="$(grep -oiE '<title>[^<]*' "$body" 2>/dev/null | head -1 | cut -c8-)"
      [ -n "$title" ] && say "    page title: $title"
      grep -oiE '(bktel|genexis|nokia|huawei|zte|xon[0-9]+|fibertwist|pulse)[a-z0-9._-]*' "$body" 2>/dev/null |
        sort -u | head -5 | while read -r hit; do say "    identifier: $hit"; done
    else
      rm -f "$body"
    fi
  done

  if command -v snmpwalk >/dev/null 2>&1; then
    for community in public private; do
      # 1.3.6.1.2.1.1 = system MIB; many ONTs expose optics under a private OID
      # tree whose root the sysDescr will point at.
      if snmpwalk -v2c -c "$community" -t 2 -r 1 "$ip" 1.3.6.1.2.1.1 \
           >"$OUT_DIR/${ip}-snmp-$community-$STAMP.txt" 2>/dev/null; then
        say "  SNMP responds (community: $community) -> ${ip}-snmp-$community-$STAMP.txt"
        head -3 "$OUT_DIR/${ip}-snmp-$community-$STAMP.txt" | sed 's/^/    /' | tee -a "$LOG"
        break
      else
        rm -f "$OUT_DIR/${ip}-snmp-$community-$STAMP.txt"
      fi
    done
  else
    say "  (snmpwalk not installed -- apt install snmp to try SNMP)"
  fi
  say
done

cat >>"$LOG" <<'NOTES'

=== what to look for ===
Optical receive power (Rx), reported in dBm. Healthy GPON at the ONT is roughly
-15 to -25 dBm. Below about -27 dBm the link is marginal and errors follow.
Record it daily: a level that drifts downward over weeks is a physical fault
(bend, dirty or loose connector, failing splice, degrading OLT port), and that
is the single most useful number you can put in front of the operator.

Also worth capturing if the device exposes them:
  * FEC corrected/uncorrected blocks, BIP errors -- rising counts mean a dirty link
  * GPON state (O1..O5); anything that leaves O5 is a re-ranging event
  * LOS / LOF / dying-gasp counters
  * ONT uptime -- proves whether it reset on its own

=== if the modem tells you nothing ===
That is itself a finding, and it is the core of the argument for replacing it:
a sealed modem that exposes no diagnostics leaves both sides guessing. Ask your
operator in writing to read out their own line-side values instead:
  * signal level at their end for your line, historical if they keep it
  * per-line error counters and the deactivation/reactivation log
  * ranging, retrain and dying-gasp events
They have all of this. Requesting it in writing also creates a paper trail
showing you asked and what they answered.
NOTES

say "done -- collected in $OUT_DIR"
say "keep every run: a series of Rx readings over weeks is what proves drift."
