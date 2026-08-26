#!/usr/bin/env bash
# Regenerate docs/screenshots from a running supervisor.
#
# Recapture policy (also in AGENTS.md): never write here while iterating.
# Use .scratch/ for mid-work captures. Verify with curl / grep, not images.
# Run this script exactly once after UI work is merged and deployed.
#
# Uses ?solo=<section-id> so each image is exactly one section: headless Chrome
# ignores scroll position, so the alternative is cropping a tall screenshot at
# hardcoded pixel offsets, which break the moment an agent writes a longer
# answer.
#
# Usage:
#   uv run uvicorn cinetrace.web.app:app --port 8080     # in another shell
#   curl -X POST localhost:8080/api/run                  # so the timeline fills
#   bash scripts/capture_screenshots.sh
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8080}"
OUT="${OUT:-$(pwd)/docs/screenshots}"
CHROME="${CHROME:-/c/Program Files/Google/Chrome/Application/chrome.exe}"

mkdir -p "$OUT"

shot () { # name, WxH, query
  # Unique profile *and* disk cache per shot. Sharing either means Chrome serves
  # a stale app.js, and the page renders with whatever behaviour the previous
  # capture had -- which looks exactly like the new flag not working.
  local profile="/tmp/cinetrace-shot-$1"
  rm -rf "$profile"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-sandbox \
    --user-data-dir="$profile" --disk-cache-dir="$profile/cache" \
    --virtual-time-budget=25000 \
    --window-size="$2" --screenshot="$OUT/$1.png" "$BASE/?nolive&$3" \
    >/dev/null 2>&1 || true
  rm -rf "$profile"
  printf '  %-26s %s bytes\n' "$1" "$(stat -c %s "$OUT/$1.png" 2>/dev/null || echo MISSING)"
}

echo "Capturing to $OUT"
shot 01-dailies-at-risk    1600,1080 ""
shot 02-impact-and-waste   1600,520  "solo=impact-row"
shot 03-three-agents       1600,900  "solo=agents"
shot 04-mcp-evidence       1600,1000 "solo=agents"
shot 05-root-cause-asof    1600,1000 "solo=root-cause"
shot 06-semantic-recall    1600,700  "solo=recall"
shot 07-detection-sql      1600,1100 "solo=sentinel-queries"
shot 08-proposals-approval 1600,700  "solo=proposals-section"
shot 09-full-page          1600,6600 ""
echo "Done. Captions live in docs/devpost.md."
