#!/bin/bash
UNIT_DIR="$HOME/.config/systemd/user"

for unit in ai-tokens-claude-code.timer ai-tokens-agy.timer ai-tokens-dashboard.service; do
  systemctl --user disable --now "$unit" 2>/dev/null
done

for unit in ai-tokens-claude-code.service ai-tokens-claude-code.timer \
            ai-tokens-agy.service ai-tokens-agy.timer \
            ai-tokens-dashboard.service; do
  rm -f "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user reset-failed 2>/dev/null

echo "✅ ai-tokens-tracker systemd units removed"
