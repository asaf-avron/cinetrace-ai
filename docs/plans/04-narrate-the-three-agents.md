---
name: Narrate the three agents
overview: Turn the Gemini text blob into a visible detect → decide → dry-run timeline so judges see Diagnostic Sentinel, Studio Orchestrator, and Action Agent as a loop, not one dump.
todos:
  - id: structure-events
    content: Parse runner events into a typed timeline (sentinel / orchestrator / action) on POST /api/run
    status: completed
  - id: timeline-ui
    content: Replace or sit above Last run with a three-step narrative and highlight new proposal rows
    status: completed
  - id: status-copy
    content: Update in-run status text to the three names; do not add agents
    status: completed
isProject: false
---

# Narrate the three agents

Do this after the query panel (01) and $ headlines (02). [`runner.py`](src/cinetrace/web/runner.py) already collects `[event.author]: text` from ADK. The UI dumps that into `#summary`. Authors are already the three roles: `diagnostic_sentinel`, `studio_orchestrator`, `action_agent`. No new agents.

```mermaid
sequenceDiagram
  participant UI
  participant Run as POST api/run
  participant Orch as Studio Orchestrator
  participant Sen as Diagnostic Sentinel
  participant Act as Action Agent
  participant CH as ClickHouse
  UI ->> Run: token plus rate limit
  Run ->> Orch: DEFAULT_PROMPT
  Orch ->> Sen: investigate
  Sen ->> CH: MCP run_query
  Orch ->> Act: pick 1 to 3 job_ids
  Act ->> CH: propose_remediation
  Run ->> UI: timeline plus new proposals
```

## 1. Structured run payload

- In `run_supervisor`, keep the text summary, and also return `timeline: [{ agent, text }]` using `event.author`.
- Map authors to display names: Diagnostic Sentinel, Studio Orchestrator, Action Agent. Drop empty/tool-only events that have no text.
- Include `recorded` (already returned) and the `job_id`s those rows touched.
- Do not stream SSE in the first cut unless the wait (~1–2 min) feels broken; a single JSON response is enough. If you add progress later, keep it on `/api/run` and do not open a second Gemini call.

## 2. Timeline UI

- Section **Supervisor loop** on [`index.html`](src/cinetrace/web/templates/index.html): three columns or a vertical list — Detect / Decide / Dry-run — filled from `timeline`.
- Keep the raw summary collapsed or under **Last run** for debugging.
- After a successful run, mark new proposal rows (e.g. a class on the `<tr>`) so Action Agent → table is obvious.
- If plan 01 is done, reuse the same `job_id` highlight on the waste panel.

## 3. Copy only

- Toolbar status today: `Running detect → decide → dry-run…`. Keep that language; optionally expand to the three agent names while in flight.
- README one-liner: the hosted page shows the three-agent loop after Run.

**Out of scope:** A fourth agent, a planner, or a “narrator.” Changing Orchestrator policy. Agent Engine as the public demo. WebSockets.
