#!/bin/bash
# CIN-only worktree ensure. Never source paperclip-env.sh (defaults to SYN).
set -euo pipefail

TOKEN_FILE="${CINETRACE_GITHUB_ENV:-/home/ubuntu/.cinetrace/github.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f /opt/cinetrace-ai/scripts/oracle/ensure_cin_worktrees.py ]; then
  PY=/opt/cinetrace-ai/scripts/oracle/ensure_cin_worktrees.py
else
  PY="${SCRIPT_DIR}/ensure_cin_worktrees.py"
fi

if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: missing $TOKEN_FILE" >&2
  exit 1
fi
if [ ! -f "$PY" ]; then
  echo "ERROR: missing $PY" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$TOKEN_FILE"
set +a

if [ -z "${GH_TOKEN:-}" ]; then
  echo "ERROR: GH_TOKEN not set after sourcing $TOKEN_FILE" >&2
  exit 1
fi

export CINETRACE_GITHUB_ENV="$TOKEN_FILE"
export CINETRACE_CLONE="${CINETRACE_CLONE:-/opt/cinetrace-ai}"
export PAPERCLIP_API_BASE="${PAPERCLIP_API_BASE:-http://127.0.0.1:3100}"

exec python3 "$PY"
