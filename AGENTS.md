# CineTrace AI

VFX studio supervisor that kills render-farm compute waste by analyzing telemetry.

## Agents

Only these three exist. Do not invent extra roles.

- **Diagnostic Sentinel** — detect waste and anomalies in farm telemetry
- **Studio Orchestrator** — decide what to do next (ADK `root_agent`)
- **Action Agent** — execute the remediation (dry-run; persists `proposed` then `recorded` rows)

## Data

ClickHouse is the telemetry store. Agents query it through **MCP** (`run_query` is select-only). Python applies schema, seed, health, and dry-run `remediation_proposals` with **clickhouse-connect** over HTTPS. Same service, two clients. Queries must be real, not mocked.

## Stack

Gemini + Google Cloud ADK / Agent Engine is the submission core. Do not substitute another orchestrator.

## Secrets

No secrets in git. Use the local `.env` (gitignored). Copy from `.env.example`. Fill `CLICKHOUSE_HOST` and `CLICKHOUSE_PASSWORD` from ClickHouse Cloud **Connect → HTTPS**, not the MCP tab.

## Paperclip / Oracle

Oracle and Paperclip are allowed **only** for company **CIN / CineTrace AI**. Do not operate on SYN/Maqom. Do not change `/opt/milepo-oracle` deploy defaults to CIN.

Use `.cursor/skills/oracle-connection` for SSH/host facts and `.cursor/skills/paperclip-cin` for CIN issues/agents/heartbeats. Resolve the company at runtime with `issuePrefix == "CIN"`. Never use `companies[0]` and never source `paperclip-env.sh` without `PAPERCLIP_COMPANY_ISSUE_PREFIX=CIN`. Board tokens stay on the Oracle host (`.env`); do not commit them here.

CIN host checkout is `/opt/cinetrace-ai` with per-agent worktrees under `worktrees/<slug>`. Do not use `/opt/milepo/worktrees`. GitHub access is the personal PAT in `/home/ubuntu/.cinetrace/github.env` (`GH_TOKEN=...`); never `gh auth login` with it (host `gh` stays `insiteu-bot`). See `paperclip-cin`.

## Screenshots

Never write to `docs/screenshots` while iterating. Use the gitignored `.scratch/` directory for any intermediate capture.

Verify with text, not images. Row counts, float formatting, pill contents, and copy changes are all checkable with `curl` against the JSON APIs or by grepping the served HTML, CSS, and JS.

Read an image only when the question is genuinely geometric (overlap, overflow, sticky positioning).

Run `scripts/capture_screenshots.sh` exactly once, after all UI work is merged and deployed.
