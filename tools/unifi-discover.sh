#!/bin/sh
# Run this ON a UniFi gateway (UDM/UDM Pro/UXG) (ssh root@<udmp-ip>) to collect the facts the probe
# config needs: which interface is which WAN, the DG gateway, and DG's
# resolvers. Prints a ready-to-paste YAML fragment at the end.
#
# Read-only. Uses /bin/sh so it works in UniFi OS's minimal shell.

echo "=== UniFi OS ==="
(ubnt-device-info firmware 2>/dev/null || cat /etc/unifi-os/unifi-os.conf 2>/dev/null) | head -5
echo

echo "=== interfaces with addresses ==="
ip -4 -o addr show | awk '{print $2, $4}'
echo

echo "=== routing table ==="
ip route show
echo

echo "=== default routes per table (dual-WAN policy routing) ==="
ip rule show 2>/dev/null
for t in 201 202 203 204; do
  r=$(ip route show table "$t" 2>/dev/null | head -3)
  [ -n "$r" ] && echo "table $t:" && echo "$r"
done
echo

echo "=== DHCP leases on WAN interfaces ==="
for f in /var/run/dhclient*.leases /run/dhclient*.leases /var/lib/dhcp/*.leases; do
  [ -f "$f" ] || continue
  echo "--- $f"
  # last lease block only -- that is the one currently in force
  awk '/^lease/{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$f" |
    grep -E 'option (routers|domain-name-servers|dhcp-server-identifier)|fixed-address|renew|expire'
done
echo

echo "=== resolv.conf ==="
cat /etc/resolv.conf 2>/dev/null
echo

echo "=== first hops on each WAN ==="
for i in $(ip -4 -o addr show | awk '$2 ~ /^eth|^ppp/ {print $2}' | sort -u); do
  gw=$(ip route show dev "$i" 2>/dev/null | awk '/default/{print $3; exit}')
  [ -n "$gw" ] && echo "$i -> gateway $gw"
done
echo

echo "=== WAN link state and error counters ==="
for i in $(ip -4 -o addr show | awk '$2 ~ /^eth/ {print $2}' | sort -u); do
  echo "--- $i"
  ip -s link show "$i" | sed -n '2,6p'
  ethtool "$i" 2>/dev/null | grep -E 'Speed|Duplex|Link detected'
  ethtool -S "$i" 2>/dev/null | grep -iE 'err|drop|crc|fail' | head -12
done
echo

cat <<'HINT'
=== what to do with this ===
1. Identify the DG WAN interface (the one whose gateway is a public address in
   DG's range, not 192.168.x.x).
2. Take "option domain-name-servers" from that interface's lease -- those are
   DG's resolvers. Paste them into probe/config.dg.yaml under BOTH
   icmp.targets (role: isp_resolver) and dns.resolvers (role: isp_resolver).
3. Note the gateway address. The probe discovers it automatically as hop 2,
   but pinning it explicitly makes the evidence unambiguous.
4. Re-run this after any DG-side change; if the gateway or resolvers move,
   that is itself worth recording.
HINT
