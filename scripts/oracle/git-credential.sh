#!/bin/bash
# Repo-local GitHub credential helper for CIN only.
# Reads GH_TOKEN from ~/.cinetrace/github.env. Do not use as the global helper.
set -euo pipefail
TOKEN_FILE="${CINETRACE_GITHUB_ENV:-/home/ubuntu/.cinetrace/github.env}"

case "${1:-}" in
  get)
    if [ ! -f "$TOKEN_FILE" ]; then
      exit 0
    fi
    # shellcheck disable=SC1090
    set -a
    source "$TOKEN_FILE"
    set +a
    if [ -z "${GH_TOKEN:-}" ]; then
      exit 0
    fi
    printf 'username=x-access-token\npassword=%s\n' "$GH_TOKEN"
    ;;
  store|erase)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
