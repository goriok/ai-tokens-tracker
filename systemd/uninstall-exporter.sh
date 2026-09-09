#!/bin/bash
UNIT_DIR="$HOME/.config/systemd/user"

systemctl --user disable --now ai-tokens-exporter.service 2>/dev/null
rm -f "$UNIT_DIR/ai-tokens-exporter.service"

systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null

echo "✅ ai-tokens-exporter.service removed"
echo "   (the timeseries data at ~/.local/share/ai-tokens-tracker/tsdb/ and the installed"
echo "   binary at ~/.local/bin/aitokens-exporter are left in place — remove by hand if wanted)"
