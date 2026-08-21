# Demo shot list (2:00–2:30)

Replace the file on the existing public Vimeo video **https://vimeo.com/1220287055** so Devpost stays put. English audio. Optional SRT: `docs/demo/cinetrace-ai-demo.srt`.

Wake ClickHouse Cloud first. Confirm `https://cinetrace-781071502822.us-central1.run.app/api/health` shows `"clickhouse": true`.

1. Open the hosted supervisor. Read the hero: three agents, live ClickHouse.
2. Point at **Estimated waste** vs **After recorded dry-runs**. If after is $0, say those jobs already have dry-run proposals (recovered, not healthy).
3. Show waste category cards, then one Sentinel SQL panel (`mcp-clickhouse` `run_query`).
4. Click **Run supervisor**. Wait for Diagnostic Sentinel → Studio Orchestrator → Action Agent.
5. Show **This run · mcp-clickhouse** tool calls (or `system.query_log` if it loaded).
6. Farm-hours sparkline + a highlighted job row and a `recorded` proposal (`executed=no`, `mode=dry_run`).
7. Close: Gemini + ADK on Cloud Run, ClickHouse via official MCP, three agents only.

Do not film slides. Do not film Agent Engine.
