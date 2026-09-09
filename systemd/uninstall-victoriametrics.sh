#!/bin/bash
UNIT_DIR="$HOME/.config/systemd/user"

systemctl --user disable --now ai-tokens-victoriametrics.service 2>/dev/null
rm -f "$UNIT_DIR/ai-tokens-victoriametrics.service"

systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null

echo "✅ ai-tokens-victoriametrics.service removed"
echo "   (the binary at ~/.local/opt/victoria-metrics/ and its data at"
echo "   ~/.local/share/ai-tokens-tracker/vm-data/ are left in place — remove by hand if wanted)"
