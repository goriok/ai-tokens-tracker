#!/bin/bash
# Installs VictoriaMetrics single-node locally — a single static binary, no
# Docker — as the optional PromQL/vmui layer for the exporter's /metrics.
# Opt-in, separate from install.sh and install-exporter.sh: this is pure
# consumption of the exporter, nothing depends on it being present.
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
OPT_DIR="$HOME/.local/opt/victoria-metrics"
BIN_DIR="$HOME/.local/bin"

VM_VERSION="v1.151.0"
VM_ARCHIVE="victoria-metrics-linux-amd64-${VM_VERSION}.tar.gz"
VM_URL="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VM_VERSION}/${VM_ARCHIVE}"
VM_SHA256="629bd538bdccaae6cb6c33fd6d387387abf5b6c00f2a99667407ad6085db1c91"

echo "=== VictoriaMetrics local installer (${VM_VERSION}, opt-in) ==="
echo ""

mkdir -p "$OPT_DIR" "$BIN_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${VM_ARCHIVE}..."
curl -sL -o "$TMP/$VM_ARCHIVE" "$VM_URL"

echo "Verifying checksum..."
echo "${VM_SHA256}  $TMP/$VM_ARCHIVE" | sha256sum -c - || {
  echo "❌ checksum mismatch — refusing to install a corrupted/unexpected binary." >&2
  exit 1
}

tar xzf "$TMP/$VM_ARCHIVE" -C "$OPT_DIR"
ln -sf "$OPT_DIR/victoria-metrics-prod" "$BIN_DIR/victoria-metrics"

mkdir -p "$UNIT_DIR"
ln -sf "$BASE/ai-tokens-victoriametrics.service" "$UNIT_DIR/ai-tokens-victoriametrics.service"

systemctl --user daemon-reload
systemctl --user enable --now ai-tokens-victoriametrics.service

echo "✅ Installed and started:"
echo "   ai-tokens-victoriametrics.service  (http://127.0.0.1:8428, vmui at /vmui/)"
echo ""
echo "This scrapes the exporter's /metrics (http://127.0.0.1:9464) — make sure"
echo "ai-tokens-exporter.service is installed and running first (see install-exporter.sh)."
echo ""
echo "Check status:  systemctl --user status ai-tokens-victoriametrics.service"
echo "Query UI:      xdg-open http://127.0.0.1:8428/vmui/"
echo "Uninstall:     bash $BASE/uninstall-victoriametrics.sh"
