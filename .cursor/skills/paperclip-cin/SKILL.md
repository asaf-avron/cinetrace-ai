---
name: paperclip-cin
description: Interact with Paperclip company CIN (CineTrace AI) — issues, agents, comments, heartbeats. Never SYN/Maqom. Use when creating or updating CIN tickets, invoking CEO/CTO, or checking CIN board state.
---

# Paperclip CIN

Use this skill for **board/API work** on CineTrace AI. Use `oracle-connection` for SSH/host facts. Both are CIN-only.

**Never** operate on SYN/Maqom. **Never** operate on PKN/PocketNode Core (UUID `2dfca2d5-4c80-4a9d-b5bb-19b9323c5a20`). Never `companies[0]`. Never source `paperclip-env.sh` without `PAPERCLIP_COMPANY_ISSUE_PREFIX=CIN`, and still assert the resolved id is not `94bea508-f6a9-44db-b44c-ff6a6974b3e5`.

Do not commit board tokens. Read `PAPERCLIP_API_KEY` on Oracle from `/opt/milepo-oracle/.env`.

## Resolve company (every session)

```bash
ssh oracle 'KEY=$(grep "^PAPERCLIP_API_KEY=" /opt/milepo-oracle/.env | cut -d= -f2- | tr -d "\r")
curl -sf -H "Authorization: Bearer $KEY" http://127.0.0.1:3100/api/companies \
  | python3 -c "
import json,sys
rows=json.load(sys.stdin)
cin=next((c for c in rows if c.get(\"issuePrefix\")==\"CIN\"), None)
assert cin, \"CIN company not found\"
assert cin[\"id\"]!=\"94bea508-f6a9-44db-b44c-ff6a6974b3e5\"
print(cin[\"id\"])
"'
```

UI: `https://paperclip.maqom.buzz/CIN/`  
API on host: `http://127.0.0.1:3100` with `Authorization: Bearer $PAPERCLIP_API_KEY`.

Known roles (resolve ids at runtime; do not hardcode forever):

- CEO — `adapterType: cursor`, heartbeats off until enabled in UI
- CTO — `adapterType: cursor`, reports to CEO

## Common actions (CIN only)

Prefix every CLI call with `--api-base http://127.0.0.1:3100 --api-key "$PAPERCLIP_API_KEY"` and `-C "$CIN_ID"` where required. Run on Oracle via `ssh oracle`.

```bash
# list
paperclipai issue list -C "$CIN_ID" --api-base http://127.0.0.1:3100 --api-key "$KEY" --json
paperclipai agent list -C "$CIN_ID" --api-base http://127.0.0.1:3100 --api-key "$KEY" --json

# create issue (optional assignee)
paperclipai issue create -C "$CIN_ID" --title "..." --description "..." \
  --assignee-agent-id "$CEO_ID" --api-base http://127.0.0.1:3100 --api-key "$KEY" --json

# one-shot heartbeat (does not enable the timer)
paperclipai heartbeat run --agent-id "$CEO_ID" --source on_demand --trigger manual \
  --timeout-ms 180000 --api-base http://127.0.0.1:3100 --api-key "$KEY"
```

Do not run Milepo `deploy.sh` or `paperclip-agent-roster.sh` (they can target SYN).

## Worktrees — SYN-style layout, CIN-only paths

SYN coding agents use `adapterConfig.cwd` under `/opt/milepo-app/worktrees/<role>`. CIN mirrors that under **`/opt/cinetrace-ai`**. Do not use `/opt/milepo*`. Do not run `paperclipai worktree:make` (that creates an isolated Paperclip instance, not a coding checkout). Do not reuse the host timer `paperclip-worktree-automation` (SYN).

```text
/home/ubuntu/.cinetrace/github.env     # GH_TOKEN=...  chmod 600; never commit
/opt/cinetrace-ai                      # main checkout of asaf-avron/cinetrace-ai
/opt/cinetrace-ai/worktrees/<slug>     # one worktree per CIN agent (ceo, cto, …)
```

Oracle global `gh` is **`insiteu-bot`**. Never `gh auth login` with the CIN PAT (that would replace the bot). This repo uses a **repo-local** credential helper (`~/.cinetrace/git-credential.sh`). CIN agents also get `GH_TOKEN` merged into `adapterConfig.env` so `gh pr` does not fall back to the bot. Canonical token store is the host file — not a Paperclip secret.

`scripts/oracle/ensure-cin-worktrees.sh` (timer `cinetrace-worktree-automation.timer`, every 5 min) resolves `issuePrefix == "CIN"`, creates a missing worktree + branch `<slug>-work`, and merge-PATCHes `adapterConfig.cwd` + `GH_TOKEN`. It must not replace `adapterConfig.env` (would drop `CURSOR_API_KEY`).

Feature branches + PRs only. Never push `main` from an agent.

## Isolation checklist

- Company filter: `issuePrefix == "CIN"`
- No SYN issue ids (`SYN-*`)
- No PKN issue ids (`PKN-*`)
- No `/opt/milepo` or `milepo-oracle` worktrees
- No `/opt/pocketnode-core` worktrees
- No importing Milepo or PocketNode company skills onto CIN unless explicitly asked
