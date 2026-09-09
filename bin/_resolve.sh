# Sourced by the other bin/ wrappers — resolves the aitokens-exporter
# binary once: prefer the installed one (`make install` in exporter/),
# fall back to `go run` for local development so these wrappers work right
# after a clone. Sets $AITOKENS_EXPORTER_BIN as a string ready to be used
# unquoted as the start of a command (it's either one path or `go run
# <dir>`, never something needing its own quoting).
PROJECT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

if command -v aitokens-exporter >/dev/null 2>&1; then
  AITOKENS_EXPORTER_BIN="aitokens-exporter"
elif [ -x "$HOME/.local/bin/aitokens-exporter" ]; then
  AITOKENS_EXPORTER_BIN="$HOME/.local/bin/aitokens-exporter"
else
  AITOKENS_EXPORTER_BIN="go run $PROJECT_DIR/exporter/cmd/aitokens-exporter"
fi
