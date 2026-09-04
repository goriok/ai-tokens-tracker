#!/bin/bash
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

echo "=== ai-tokens-tracker systemd (user) installer ==="
echo ""

mkdir -p "$UNIT_DIR"
for unit in ai-tokens-claude-code.service ai-tokens-claude-code.timer \
            ai-tokens-agy.service ai-tokens-agy.timer \
            ai-tokens-dashboard.service; do
  ln -sf "$BASE/$unit" "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now ai-tokens-claude-code.timer
systemctl --user enable --now ai-tokens-agy.timer
systemctl --user enable --now ai-tokens-dashboard.service

echo "✅ Installed and started:"
echo "   ai-tokens-claude-code.timer  (collects every 5min, zero token cost)"
echo "   ai-tokens-agy.timer          (collects hourly — quota is weekly)"
echo "   ai-tokens-dashboard.service  (http://127.0.0.1:8765, always on)"
echo ""
echo "Check status:  systemctl --user status ai-tokens-dashboard.service"
echo "Watch logs:    journalctl --user -u ai-tokens-dashboard.service -f"
echo "Uninstall:     bash $BASE/uninstall.sh"
