# Judging freeze and the judging window

Two dates that matter, and they are three weeks apart:

- **Submission deadline: 9 Sep 2026, 2:00pm PDT.** Feature freeze **4 Sep**.
- **Judging period: 23 Sep – 7 Oct 2026.** This is when a judge actually opens
  the URL. The service has to be correct and warm for that whole window, which
  is long after anyone is still looking at the repo.

The second date is the one previous plans missed. Everything below exists to
survive it without a human doing daily chores.

## What keeps itself alive

| Risk | Mitigation | Where |
| --- | --- | --- |
| Cold start costs a judge ~9s | `--min-instances=1`, `--no-cpu-throttling` | [deploy-cloud-run.yml](../.github/workflows/deploy-cloud-run.yml) |
| ClickHouse Cloud idles to sleep | Live ticker queries every 30s | [live.py](../src/cinetrace/web/live.py) |
| Running jobs age past the 6h zombie threshold | Live cohort rebuilt against a fresh `now()` every 15 min | `refresh_live_cohort` in [generate.py](../src/cinetrace/clickhouse/generate.py) |
| Page shows an already-solved farm | Proposals and decisions cleared daily at `DEMO_RESET_HOUR_UTC` | [live.py](../src/cinetrace/web/live.py) |
| `frame_samples` grows without bound | 100-day TTL | [010_frame_samples_ttl.sql](../src/cinetrace/schema/010_frame_samples_ttl.sql) |
| Agent Engine IAM hiccup kills a demo | Falls back to in-process ADK, same `root_agent` | [agent_engine.py](../src/cinetrace/web/agent_engine.py) |

## Weekly check during judging (23 Sep – 7 Oct)

1. `GET /api/health` — `ok: true`, `clickhouse: true`, and `live.ticks`
   increasing between checks. If `live.errors` is climbing, ClickHouse is
   refusing connections.
2. Load the page. The live pill should say "jobs rendering" with a moving
   sample count, not "reconnecting".
3. "Dailies at risk" should show a small number, not zero and not forty. Zero
   means the cohort refresh stopped; forty means it is refreshing but the
   shots table was not rebuilt.
4. One **Run supervisor** (5/hour limit). Confirm the timeline fills all three
   stages and the MCP panel shows agent-written SQL.
5. Check the ClickHouse Cloud and GCP billing consoles against the alerts.

## Cost

The live ticker deliberately keeps ClickHouse Cloud awake, which is the
trade: a service that sleeps is a service that times out on a judge's first
query. Two knobs if spend runs hot:

- Raise `LIVE_TICK_SECONDS` (30 → 120). The page updates less often; the
  cluster still never sleeps.
- Set `LIVE_TICKER_ENABLED=false` and accept cold queries. Do not do this
  during the judging window.

Budget alerts to have in place before 9 Sep:

- [ ] GCP billing alert at 50% and 90% of the $100 hackathon credits
- [ ] ClickHouse Cloud spend alert; confirm the trial or billing covers
      through 7 Oct, not just through the submission deadline
- [ ] Vertex quotas left at defaults (do not raise)

## Before the 9th

- [ ] Vimeo https://vimeo.com/1220287055 matches the live UI (re-record on this id)
- [ ] Devpost https://devpost.com/software/cinetrace-ai on the ClickHouse track
- [ ] Devpost gallery has screenshots, not just the video
- [ ] Devpost description includes findings and learnings (a rules requirement)
- [ ] `SUPERVISOR_RUN_PUBLIC=true` on Cloud Run so judges need no token
- [ ] Repo public, Apache-2.0 visible in the GitHub About panel

## Manual reset

To put the page back to an unsolved farm on demand:

```bash
uv run python -m cinetrace.clickhouse.reset_proposals
```

That clears `remediation_proposals` and `proposal_decisions` only. It never
touches `render_jobs` or `frame_samples` — regenerating those takes 20 minutes
and is not something to do near a demo.
