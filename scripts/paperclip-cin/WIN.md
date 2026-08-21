# CineTrace AI — ClickHouse-track win constraints

Company is **CIN / CineTrace AI** only. Resolve it with `issuePrefix == "CIN"`. Never SYN/Maqom. Never `companies[0]`. Never source `paperclip-env.sh` without `PAPERCLIP_COMPANY_ISSUE_PREFIX=CIN`. Never operate on company id `94bea508-f6a9-44db-b44c-ff6a6974b3e5`.

Host checkout is `/opt/cinetrace-ai` with worktrees under `/opt/cinetrace-ai/worktrees/<slug>`. Do not use `/opt/milepo` or `/opt/milepo-app`.

## Product (do not invent)

Only three ADK agents exist:

- Diagnostic Sentinel — detect waste via MCP `run_query`
- Studio Orchestrator — decide
- Action Agent — dry-run remediation

Do not add a fourth product agent. Do not rewrite the UI in React/Next/Vue. Keep FastAPI + `src/cinetrace/web/`. ClickHouse must be queried through official `mcp-clickhouse` at runtime.

## Git

Feature branches and PRs only. Never push `main`. GitHub Actions deploys Cloud Run from `main` after the board merges. No secrets in git. Never `gh auth login` with the CIN PAT (host `gh` stays `insiteu-bot`).

## Scope freeze

Do not hire CMO, UXDesigner, or extra engineers. The only reports are CEO → CTO. If blocked on Devpost, Vimeo, GCP org, or secrets, assign the **board** (Asaf), do not hire.

Work only the frozen CIN backlog the board created (MCP evidence, impact copy/reset, farm sparkline, shot list, tests) unless the board comments a new ticket.
