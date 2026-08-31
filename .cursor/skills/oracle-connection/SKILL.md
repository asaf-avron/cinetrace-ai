---
name: oracle-connection
description: Provides connection details and service discovery for Oracle infrastructure (SSH, Paperclip CIN only). Use when investigating Oracle host, Paperclip CineTrace company, or host service logs.
---

# Oracle Infrastructure Connection (CineTrace / CIN)

This skill is for the **cinetrace-ai** workspace. Paperclip work is **CIN / CineTrace AI only**.

**Never** list, patch, archive, or delete company **SYN / Maqom**. **Never** list, patch, archive, or delete company **PKN / PocketNode Core** (UUID `2dfca2d5-4c80-4a9d-b5bb-19b9323c5a20`). Never treat `companies[0]` as CIN. Never `source /opt/milepo-oracle/scripts/paperclip-env.sh` without `PAPERCLIP_COMPANY_ISSUE_PREFIX=CIN` — that script defaults to SYN and falls back to the first company if the prefix is missing.

Do not change `/opt/milepo-oracle` deploy defaults to CIN. Do not commit board tokens or `.env` into this repo.

## SSH Connection

- **Host**: `151.145.87.224` (Oracle ARM instance)
- **User**: `ubuntu`
- **SSH Alias**: `oracle` (if configured in `~/.ssh/config`)

```bash
ssh ubuntu@151.145.87.224
# or
ssh oracle
```

## Service Discovery Index

Host services live under `/opt/milepo-oracle`. They are shared infrastructure. Use them for SSH/logs only — do not operate the Milepo product or SYN Paperclip board from this workspace.

| Service | Docker Container Name | Port | Purpose |
|---------|----------------------|------|---------|
| **Paperclip** | `milepo-oracle-paperclip-bridge-1` (bridge to host) | 3100 | AI orchestration; use company CIN only |
| **milepo-gateway** | `milepo-oracle-milepo-gateway-1` | 3200 | FastAPI webhooks (Milepo) |
| **Backend Prod** | `milepo-oracle-backend-prod-1` | 8002 (host), 8000 (container) | Milepo production API |
| **Backend Staging** | `milepo-oracle-backend-staging-1` | 8001 (host), 8000 (container) | Milepo staging API |
| **Frontend Prod** | `milepo-oracle-frontend-prod-1` | 3000 | Milepo production frontend |
| **Frontend Staging** | `milepo-oracle-frontend-staging-1` | 3000 | Milepo staging frontend |
| **nginx-proxy** | `insiteu-oracle-nginx-proxy-1` | 80/443 | Reverse proxy |

## Common Commands

### Docker Compose (run from `/opt/milepo-oracle`)

```bash
cd /opt/milepo-oracle
sudo docker compose ps
sudo docker compose logs <service>
sudo docker compose restart <service>
```

Use `sudo` for docker and systemctl.

### Environment Variables

- **Location**: `/opt/milepo-oracle/.env` (board token `PAPERCLIP_API_KEY` — read on the host only)
- **Paperclip API**: `http://127.0.0.1:3100` (on Oracle)
- **Paperclip URL (Docker)**: `http://paperclip-bridge:3100`

## Key URLs

- **Paperclip**: `https://paperclip.maqom.buzz/`
- **Paperclip (nip.io fallback)**: `https://paperclip.151.145.87.224.nip.io/`
- **CineTrace company UI**: `https://paperclip.maqom.buzz/CIN/`

## Paperclip API (CIN only)

- **Base URL**: `http://127.0.0.1:3100` (inside Oracle)
- **Auth**: Board token from `/opt/milepo-oracle/.env` (`PAPERCLIP_API_KEY`)
- **Company**: resolve by `issuePrefix == "CIN"` at runtime. Do not hardcode the company UUID. If CIN is missing, **stop** — do not fall back to SYN.

```bash
ssh oracle 'KEY=$(grep "^PAPERCLIP_API_KEY=" /opt/milepo-oracle/.env | cut -d= -f2- | tr -d "\r")
curl -sf -H "Authorization: Bearer $KEY" http://127.0.0.1:3100/api/companies \
  | jq -r ".[] | select(.issuePrefix==\"CIN\") | \"\(.id)\t\(.name)\""'
```

Resolve `COMPANY_ID` (fail if absent):

```bash
ssh oracle 'KEY=$(grep "^PAPERCLIP_API_KEY=" /opt/milepo-oracle/.env | cut -d= -f2- | tr -d "\r")
curl -sf -H "Authorization: Bearer $KEY" http://127.0.0.1:3100/api/companies \
  | python3 -c "
import json,sys
rows=json.load(sys.stdin)
cin=next((c for c in rows if c.get(\"issuePrefix\")==\"CIN\"), None)
assert cin, \"CIN company not found\"
print(cin[\"id\"])
"'
```

If you must source the Milepo helper:

```bash
PAPERCLIP_COMPANY_ISSUE_PREFIX=CIN source /opt/milepo-oracle/scripts/paperclip-env.sh
# then confirm COMPANY_ID is CIN, not 94bea508-f6a9-44db-b44c-ff6a6974b3e5
```

Useful endpoints (always include the resolved CIN `COMPANY_ID`):

- `GET /api/companies` — filter to CIN
- `GET /api/companies/{companyId}/issues`
- `GET /api/companies/{companyId}/agents`

## CIN checkout (not Milepo)

- Clone: `/opt/cinetrace-ai` with worktrees at `/opt/cinetrace-ai/worktrees/<slug>`
- GitHub PAT: `/home/ubuntu/.cinetrace/github.env` (`GH_TOKEN=...`, chmod 600). Never `gh auth login` with it — host `gh` is `insiteu-bot` for SYN.
- Worktree timer: `cinetrace-worktree-automation.timer` (CIN only). Do not use `paperclip-worktree-automation`.

## Notes

- Supabase and Milepo app DBs are not CineTrace. Do not use them as the CineTrace telemetry store (ClickHouse is).
- Paperclip itself is a host systemd service (`paperclip`), not only Docker.
