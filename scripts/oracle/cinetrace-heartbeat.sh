#!/bin/bash
# CIN-only: one CEO heartbeat then one CTO heartbeat. Never SYN.
set -euo pipefail
KEY=$(grep "^PAPERCLIP_API_KEY=" /opt/milepo-oracle/.env | cut -d= -f2- | tr -d "\r")
CIN=$(curl -sf -H "Authorization: Bearer $KEY" http://127.0.0.1:3100/api/companies | python3 -c "
import json,sys
rows=json.load(sys.stdin)
cin=next((c for c in rows if c.get('issuePrefix')=='CIN'), None)
assert cin, 'CIN company not found'
assert cin['id']!='94bea508-f6a9-44db-b44c-ff6a6974b3e5'
print(cin['id'])
")
CEO=$(curl -sf -H "Authorization: Bearer $KEY" "http://127.0.0.1:3100/api/companies/$CIN/agents" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
ceo=next((a for a in rows if (a.get('role') or '').lower()=='ceo'), None)
assert ceo
print(ceo['id'])
")
CTO=$(curl -sf -H "Authorization: Bearer $KEY" "http://127.0.0.1:3100/api/companies/$CIN/agents" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
cto=next((a for a in rows if (a.get('role') or '').lower()=='cto'), None)
assert cto
print(cto['id'])
")
API=(--api-base http://127.0.0.1:3100 --api-key "$KEY")
# 3 minutes each; do not overlap (maxConcurrentRuns=1)
paperclipai heartbeat run --agent-id "$CEO" --source timer --trigger system --timeout-ms 180000 "${API[@]}"
paperclipai heartbeat run --agent-id "$CTO" --source timer --trigger system --timeout-ms 180000 "${API[@]}"
