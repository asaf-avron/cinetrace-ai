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
