#!/bin/bash
# Installs Perses locally — dashboards as code, provisioned from
# perses/provisioning/ in this repo (versioned, not built by hand in a UI).
# Opt-in, separate from install.sh/install-exporter.sh/install-victoriametrics.sh:
# pure consumption of VictoriaMetrics' PromQL API, nothing depends on it.
#
# Heavier than the other pieces here (~85MB binary, ~90MB RSS in steady
# state; systemd's cgroup memory accounting reports higher due to page
# cache from unpacking the plugin bundle, not actual RSS) — see
# docs/madrs/MADR-003 for the measurement and why it was still chosen over
# vmui alone: dashboard-as-code in Git outweighs the extra footprint for
# this use case. If that trade-off doesn't fit, vmui (already running via
# VictoriaMetrics) covers ad-hoc PromQL with zero extra cost.
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$BASE/.." && pwd)"
PERSES_DIR="$REPO_ROOT/perses"
UNIT_DIR="$HOME/.config/systemd/user"
OPT_DIR="$HOME/.local/opt/perses"

PERSES_VERSION="v0.54.0"
PERSES_ARCHIVE="perses_0.54.0_linux_amd64.tar.gz"
PERSES_URL="https://github.com/perses/perses/releases/download/${PERSES_VERSION}/${PERSES_ARCHIVE}"
PERSES_SHA256="450a387501162fec8e36f0f2628be02ad994fefa989ad1e72a8889ce5eb12a4c"

echo "=== Perses local installer (${PERSES_VERSION}, opt-in, ~90MB) ==="
echo ""

mkdir -p "$OPT_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${PERSES_ARCHIVE}..."
curl -sL -o "$TMP/$PERSES_ARCHIVE" "$PERSES_URL"

echo "Verifying checksum..."
echo "${PERSES_SHA256}  $TMP/$PERSES_ARCHIVE" | sha256sum -c - || {
  echo "❌ checksum mismatch — refusing to install a corrupted/unexpected binary." >&2
  exit 1
}

tar xzf "$TMP/$PERSES_ARCHIVE" -C "$OPT_DIR"

# Perses looks for plugins-archive/ (panel/datasource plugin bundle) in its
# own working directory, not next to the binary — the systemd unit's
# WorkingDirectory is perses/ in this repo, so the bundle needs to be
# reachable from there too. Symlinked, not copied: ~100MB, no reason to
# duplicate it, and a version bump only needs to update this one link.
ln -sf "$OPT_DIR/plugins-archive" "$PERSES_DIR/plugins-archive"
mkdir -p "$PERSES_DIR/data"

mkdir -p "$UNIT_DIR"
ln -sf "$BASE/ai-tokens-perses.service" "$UNIT_DIR/ai-tokens-perses.service"

systemctl --user daemon-reload
systemctl --user enable --now ai-tokens-perses.service

echo "✅ Installed and started:"
echo "   ai-tokens-perses.service  (http://127.0.0.1:8080)"
echo ""
echo "Dashboard (versioned in perses/provisioning/dashboard.yaml):"
echo "   http://127.0.0.1:8080/projects/ai-tokens-tracker/dashboards/ai-tokens"
echo ""
echo "Requires ai-tokens-victoriametrics.service running (datasource points"
echo "at http://127.0.0.1:8428) — see install-victoriametrics.sh."
echo ""
echo "Check status:  systemctl --user status ai-tokens-perses.service"
echo "Uninstall:     bash $BASE/uninstall-perses.sh"
