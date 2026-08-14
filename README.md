# CineTrace AI

Autonomous multi-agent VFX studio supervisor for Media & Entertainment. CineTrace AI eliminates render-farm compute waste by analyzing farm telemetry.

Built for [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/) on the **ClickHouse** partner track.

## Mission

Our mission is to develop and orchestrate CineTrace AI, an autonomous multi-agent system designed for the Media & Entertainment industry. CineTrace AI will act as a VFX studio supervisor to eliminate compute waste by analyzing render farm telemetry. As the orchestrator, your role is to assist in building, testing, and managing our three core sub-agents—the Diagnostic Sentinel, the Studio Orchestrator, and the Action Agent—and ensuring they properly connect to ClickHouse via the Model Context Protocol (MCP).

## Agents

| Agent | Role |
| --- | --- |
| **Diagnostic Sentinel** | Detect waste and anomalies in render-farm telemetry |
| **Studio Orchestrator** | Decide what to do next |
| **Action Agent** | Execute the remediation |

All three connect to **ClickHouse via MCP**. ClickHouse is the telemetry store; queries must be real, not mocked.

## Stack

- **Gemini** + **Google Cloud Agent Builder / Agent Engine (ADK)** as the submission core
- **ClickHouse** via **MCP** for telemetry
- Google Cloud and ClickHouse must be imported and called in code, not only named here

Hackathon resources: [agentic-cinema.devpost.com/resources](https://agentic-cinema.devpost.com/resources)

## Local setup

Prerequisites: Python 3.10+, [uv](https://github.com/astral-sh/uv) (`python -m uv` if `uv` is not on PATH), `gcloud` with application-default credentials on project `cinetrace-ai`.

1. Copy env and fill ClickHouse HTTPS secrets (Connect → HTTPS, not MCP):

   ```bash
   cp .env.example .env
   ```

   Set `CLICKHOUSE_HOST` and `CLICKHOUSE_PASSWORD`. Other keys are already filled.

2. Install deps:

   ```bash
   uv sync --extra dev
   ```

3. Apply schema + seed, then health-check (real ClickHouse `SELECT` and MCP):

   ```bash
   uv run python -m cinetrace.clickhouse.apply
   uv run python -m cinetrace.clickhouse.health
   uv run python -m cinetrace.clickhouse.mcp_smoke
   ```

4. Supervisor UI (public product surface) or ADK CLI (local debug only):

   ```bash
   uv run uvicorn cinetrace.web.app:app --reload --port 8080
   uv run adk web src/cinetrace
   ```

   Open `http://127.0.0.1:8080`. **Run supervisor** calls the Studio Orchestrator in-process. `adk web` stays local for debugging.

5. Import tests (no secrets required):

   ```bash
   uv run pytest
   ```

Remote MCP `https://mcp.clickhouse.cloud/mcp` is enabled on the Cloud service for hosted/OAuth clients. Local agents use stdio `mcp-clickhouse` with the same HTTPS credentials.

## Hosted

- **Supervisor (Cloud Run, judge URL):** https://cinetrace-781071502822.us-central1.run.app
- **Agents (Vertex Agent Engine):** `projects/cinetrace-ai/locations/us-central1/reasoningEngines/7649057753100451840` (same `root_agent`). Query: `https://us-central1-aiplatform.googleapis.com/v1/projects/cinetrace-ai/locations/us-central1/reasoningEngines/7649057753100451840:query`

The page and job/proposal tables are public. **Run supervisor** spends Vertex credits: it requires a demo token (ask the team; do not commit it), is limited to 5 runs per hour, and always uses the fixed supervisor prompt. Set `SUPERVISOR_RUN_ENABLED=false` overnight.

ClickHouse and `SUPERVISOR_RUN_TOKEN` live in Secret Manager. Wake the ClickHouse Cloud service before a demo so the first query does not time out.

Set a [budget alert](https://console.cloud.google.com/billing) on the `cinetrace-ai` billing account (50% / 90% of the $100 credits). Do not raise Vertex quotas. The Agent Engine `:query` URL is IAM-only — do not grant `allUsers` and do not use it as the public demo.

Redeploy Cloud Run after code changes:

```bash
uv run python scripts/sync_secrets.py
gcloud run deploy cinetrace --source . --project=cinetrace-ai --region=us-central1 --max-instances=1 --quiet
```

## Submission (Devpost)

Deadline: **Sep 9, 2026 @ 2:00pm PDT**. Judging: implementation, design, impact, idea quality. ClickHouse track prizes: $7,500 / $4,500 / $3,000.

Before submit:

- [ ] Flip this repo from private to **public**
- [ ] Add a complete open-source license (visible in GitHub About)
- [ ] Prove Google Cloud and ClickHouse are used at runtime in code
- [ ] Hosted project URL
- [ ] 3-minute **working demo** video (YouTube/Vimeo, English or English subtitles)
- [ ] Complete the Devpost form and select the ClickHouse track
