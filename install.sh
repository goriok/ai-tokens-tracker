#!/bin/bash
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"

echo "=== agy-tracker installer (standalone) ==="
echo "For Claude Code or Antigravity plugin install, see README.md instead."
echo ""

mkdir -p ~/.local/bin
chmod +x "$BASE/bin/"*
ln -sf "$BASE/bin/agystatus" ~/.local/bin/agystatus
ln -sf "$BASE/bin/agysnapshot" ~/.local/bin/agysnapshot
ln -sf "$BASE/bin/agywidget" ~/.local/bin/agywidget
ln -sf "$BASE/bin/agydelegate" ~/.local/bin/agydelegate
echo "✅ Commands linked in ~/.local/bin: agystatus, agysnapshot, agywidget, agydelegate"

echo ""
echo "=== Next steps ==="
echo "1. Run 'agysnapshot' once to record your first quota snapshot"
echo "2. Run 'agystatus' to generate and open the report"
echo "3. To collect automatically, schedule 'agysnapshot' via cron/systemd timer"
echo "   (e.g. hourly — the quota is weekly, high frequency doesn't add much)"
