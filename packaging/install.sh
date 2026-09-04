#!/bin/sh
# Install an ispbust probe natively, without Docker.
#
#   ./install.sh /path/to/probe.yaml
#   curl -fsSL https://raw.githubusercontent.com/KilianSen/ispbust/master/packaging/install.sh | sh -s -- probe.yaml
#
# Handles Debian/Ubuntu (apt + systemd) and Alpine (apk + OpenRC). Idempotent:
# re-run it to upgrade, and your config is left alone.
#
# Useful on a small VM or a Raspberry Pi that only exists to be a probe, where
# a container runtime is more machinery than the job needs.
set -eu

REF="${ISPBUST_REF:-master}"
TARBALL="https://github.com/KilianSen/ispbust/archive/refs/heads/${REF}.tar.gz"
CONFIG_SRC="${1:-}"

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

say() { printf '==> %s\n' "$*"; }

# ---------------------------------------------------------------- packages

if command -v apk >/dev/null 2>&1; then
    OS=alpine
    say "Alpine detected"
    # mtr lives in the community repository, which is not always enabled.
    if ! grep -q '^http.*community' /etc/apk/repositories 2>/dev/null; then
        say "enabling the community repository (backup at /etc/apk/repositories.bak)"
        cp -n /etc/apk/repositories /etc/apk/repositories.bak 2>/dev/null || true
        sed -i 's|^#\(http.*community\)|\1|' /etc/apk/repositories
    fi
    apk update -q
    apk add -q --no-cache python3 py3-pip fping mtr libcap ca-certificates tzdata chrony logrotate
    rc-update add chronyd default >/dev/null 2>&1 || true
    rc-service chronyd start >/dev/null 2>&1 || true
elif command -v apt-get >/dev/null 2>&1; then
    OS=debian
    say "Debian/Ubuntu detected"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends \
        python3 python3-venv python3-pip fping mtr-tiny libcap2-bin \
        ca-certificates tzdata chrony logrotate
    systemctl enable --now chrony >/dev/null 2>&1 || \
        systemctl enable --now chronyd >/dev/null 2>&1 || true
else
    echo "unsupported distribution: need apk or apt-get" >&2
    exit 1
fi

# Timestamps are the evidence, and the paired comparison buckets by minute, so
# a probe with an unsynchronised clock quietly corrupts the comparison.
say "clock: $(date -u '+%Y-%m-%dT%H:%M:%SZ') UTC"

# ------------------------------------------------------------ capabilities

# fping and mtr need raw sockets. Grant the binaries the capability rather than
# running the probe as root.
for bin in fping mtr; do
    path="$(command -v "$bin" 2>/dev/null || true)"
    [ -n "$path" ] || continue
    setcap cap_net_raw+ep "$path" 2>/dev/null || true
    say "$bin: $(getcap "$path" 2>/dev/null || echo 'no capability set -- ICMP may fail')"
done

# ------------------------------------------------------------------ layout

if ! id ispbust >/dev/null 2>&1; then
    if [ "$OS" = alpine ]; then
        adduser -S -D -H -h /var/lib/ispbust -s /sbin/nologin ispbust
    else
        useradd --system --home-dir /var/lib/ispbust --shell /usr/sbin/nologin ispbust
    fi
fi
GROUP=ispbust
id -gn ispbust >/dev/null 2>&1 && GROUP="$(id -gn ispbust)"

install -d -o ispbust -g "$GROUP" -m 0755 /var/lib/ispbust /var/lib/ispbust/raw
install -d -m 0755 /etc/ispbust /opt/ispbust

# -------------------------------------------------------------------- code

say "installing ispbust ($REF)"
[ -x /opt/ispbust/venv/bin/python ] || python3 -m venv /opt/ispbust/venv
/opt/ispbust/venv/bin/pip install --quiet --no-cache-dir --upgrade pip
/opt/ispbust/venv/bin/pip install --quiet --no-cache-dir --upgrade "$TARBALL"
say "installed $(/opt/ispbust/venv/bin/ispbust --version)"

# ------------------------------------------------------------------ config

if [ -n "$CONFIG_SRC" ] && [ -f "$CONFIG_SRC" ]; then
    if [ -f /etc/ispbust/probe.yaml ]; then
        say "keeping the existing /etc/ispbust/probe.yaml (new one at .dist)"
        install -m 0640 -g "$GROUP" "$CONFIG_SRC" /etc/ispbust/probe.yaml.dist
    else
        install -m 0640 -g "$GROUP" "$CONFIG_SRC" /etc/ispbust/probe.yaml
    fi
elif [ ! -f /etc/ispbust/probe.yaml ]; then
    echo "no config supplied and none installed." >&2
    echo "  Copy examples/probe.under-test.yaml to /etc/ispbust/probe.yaml, then re-run." >&2
    exit 1
fi

# Generate an export token if the config still has an empty one.
if grep -q 'export_token: *""' /etc/ispbust/probe.yaml 2>/dev/null; then
    if [ ! -f /etc/ispbust/export-token ]; then
        /opt/ispbust/venv/bin/python -c 'import secrets;print(secrets.token_hex(24))' \
            > /etc/ispbust/export-token
        chmod 600 /etc/ispbust/export-token
    fi
    TOKEN="$(cat /etc/ispbust/export-token)"
    sed -i "s|export_token: *\"\"|export_token: \"$TOKEN\"|" /etc/ispbust/probe.yaml
    say "generated an export token (also at /etc/ispbust/export-token)"
fi

/opt/ispbust/venv/bin/ispbust check --probe /etc/ispbust/probe.yaml

# --------------------------------------------------------------- log rotate

cat > /etc/logrotate.d/ispbust <<EOF
/var/log/ispbust.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su ispbust $GROUP
}
EOF

# ------------------------------------------------------------------ service

BASE="$(dirname "$0")"
if [ "$OS" = alpine ]; then
    if [ -f "$BASE/openrc/ispbust" ]; then
        install -m 0755 "$BASE/openrc/ispbust" /etc/init.d/ispbust
    else
        /opt/ispbust/venv/bin/python - <<'PY'
import urllib.request
url = "https://raw.githubusercontent.com/KilianSen/ispbust/master/packaging/openrc/ispbust"
open("/etc/init.d/ispbust", "wb").write(urllib.request.urlopen(url, timeout=30).read())
PY
        chmod 0755 /etc/init.d/ispbust
    fi
    rc-update add ispbust default >/dev/null 2>&1 || true
    rc-service ispbust restart
    sleep 3
    rc-service ispbust status | tail -1
    say "logs: tail -f /var/log/ispbust.log"
else
    if [ -f "$BASE/systemd/ispbust-probe.service" ]; then
        install -m 0644 "$BASE/systemd/ispbust-probe.service" \
            /etc/systemd/system/ispbust-probe.service
    else
        /opt/ispbust/venv/bin/python - <<'PY'
import urllib.request
url = ("https://raw.githubusercontent.com/KilianSen/ispbust/master/"
       "packaging/systemd/ispbust-probe.service")
open("/etc/systemd/system/ispbust-probe.service", "wb").write(
    urllib.request.urlopen(url, timeout=30).read())
PY
    fi
    systemctl daemon-reload
    systemctl enable --now ispbust-probe
    sleep 3
    systemctl is-active ispbust-probe
    say "logs: journalctl -u ispbust-probe -f"
fi

PORT="$(sed -n 's/^ *port: *\([0-9]*\).*/\1/p' /etc/ispbust/probe.yaml | head -1)"
PORT="${PORT:-9109}"
say "done"
echo
echo "  check it:   curl -s localhost:$PORT/info"
echo "  token:      $(cat /etc/ispbust/export-token 2>/dev/null || echo '(set in probe.yaml)')"
echo
echo "  NOW VERIFY THE PINNING. Disable the WAN this probe measures and confirm"
echo "  it goes completely dark. If it keeps answering, it is failing over and"
echo "  every measurement it takes is worthless."
