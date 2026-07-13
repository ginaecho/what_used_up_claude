#!/usr/bin/env bash
# Install the /budget slash command globally so it works in every project.
#
#   ./install.sh                 # install script + command into ~/.claude
#   ./install.sh --limit-5h 2M --limit-weekly '$150'   # also write limits config
#
# After installing, type /budget inside any Claude Code session.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CMD_DIR="$CLAUDE_DIR/commands"

mkdir -p "$CMD_DIR"
cp "$SRC_DIR/claude_usage_stats.py" "$CLAUDE_DIR/claude_usage_stats.py"
cp "$SRC_DIR/.claude/commands/budget.md" "$CMD_DIR/budget.md"
echo "Installed:"
echo "  $CLAUDE_DIR/claude_usage_stats.py"
echo "  $CMD_DIR/budget.md   (type /budget in any session)"

LIMIT_5H=""
LIMIT_WEEKLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --limit-5h)     LIMIT_5H="$2"; shift 2;;
    --limit-weekly) LIMIT_WEEKLY="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

if [ -n "$LIMIT_5H" ] || [ -n "$LIMIT_WEEKLY" ]; then
  python3 - "$CLAUDE_DIR/usage_limits.json" "$LIMIT_5H" "$LIMIT_WEEKLY" <<'PY'
import json, sys
path, l5, lw = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if l5: data["limit_5h"] = l5
if lw: data["limit_weekly"] = lw
open(path, "w").write(json.dumps(data, indent=2) + "\n")
print(f"  {path}   ({data})")
PY
else
  echo
  echo "Tip: set your plan caps for headroom recommendations, e.g."
  echo "  ./install.sh --limit-5h 2M --limit-weekly '\$150'"
  echo "  (run /usage in Claude Code once to find your real numbers)"
fi
