#!/bin/bash
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

echo "=== ai-tokens-tracker Go exporter installer (opt-in, separate from install.sh) ==="
echo ""

if ! command -v go >/dev/null 2>&1; then
  echo "❌ go not found in PATH — install Go before running this." >&2
  exit 1
fi

echo "Building and installing the exporter binary to ~/.local/bin..."
(cd "$BASE/../exporter" && /usr/bin/env make install)

mkdir -p "$UNIT_DIR"
ln -sf "$BASE/ai-tokens-exporter.service" "$UNIT_DIR/ai-tokens-exporter.service"

systemctl --user daemon-reload
systemctl --user enable --now ai-tokens-exporter.service

echo "✅ Installed and started:"
echo "   ai-tokens-exporter.service  (backfills once, then serves http://127.0.0.1:9464/metrics)"
echo ""
echo "Check status:  systemctl --user status ai-tokens-exporter.service"
echo "Watch logs:    journalctl --user -u ai-tokens-exporter.service -f"
echo "Metrics:       curl http://127.0.0.1:9464/metrics"
echo "Uninstall:     bash $BASE/uninstall-exporter.sh"
echo ""
echo "Optional: install VictoriaMetrics locally for PromQL/vmui — see systemd/README.md."
