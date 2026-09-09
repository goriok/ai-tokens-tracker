#!/bin/bash
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"

echo "=== ai-tokens-tracker installer (standalone) ==="
echo "For continuous collection + dashboards, see systemd/README.md instead —"
echo "this only links the manual tracked-call commands."
echo ""

mkdir -p ~/.local/bin
chmod +x "$BASE/bin/"*
ln -sf "$BASE/bin/agydelegate" ~/.local/bin/agydelegate
ln -sf "$BASE/bin/agytrack" ~/.local/bin/agytrack
ln -sf "$BASE/bin/copilottrack" ~/.local/bin/copilottrack
echo "✅ Commands linked in ~/.local/bin: agydelegate, agytrack, copilottrack"
echo "   (each falls back to 'go run' if exporter/bin/aitokens-exporter isn't installed yet —"
echo "   run 'make install' in exporter/ once to avoid that overhead on every call)"

echo ""
echo "=== Next steps ==="
echo "For continuous background collection + /metrics + dashboards:"
echo "  bash systemd/install-exporter.sh"
echo "  bash systemd/install-victoriametrics.sh   # optional: PromQL + vmui"
echo "  bash systemd/install-perses.sh            # optional: versioned dashboards"
