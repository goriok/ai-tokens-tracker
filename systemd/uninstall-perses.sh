#!/bin/bash
UNIT_DIR="$HOME/.config/systemd/user"
BASE="$(cd "$(dirname "$0")" && pwd)"

systemctl --user disable --now ai-tokens-perses.service 2>/dev/null
rm -f "$UNIT_DIR/ai-tokens-perses.service"
rm -f "$BASE/../perses/plugins-archive"

systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null

echo "✅ ai-tokens-perses.service removed"
echo "   (the binary at ~/.local/opt/perses/ and provisioned data at"
echo "   perses/data/ are left in place — perses/provisioning/ is versioned"
echo "   source, never touched; remove the rest by hand if wanted)"
