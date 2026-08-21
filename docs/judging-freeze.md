# Judging freeze (4–9 Sep 2026)

Deadline: **9 Sep 2026 2:00pm PDT**. Feature freeze **4 Sep**. After that: health checks only.

## Daily (4–9 Sep)

1. Wake the ClickHouse Cloud service.
2. `GET https://cinetrace-781071502822.us-central1.run.app/api/health` — `ok` and `clickhouse: true`.
3. One **Run supervisor** (5/hour). Confirm timeline + MCP evidence.
4. Do not merge UI features. Ops-only if the page 503s.

## Before the 9th morning walkthrough

- [ ] Vimeo https://vimeo.com/1220287055 matches the live UI (re-record on this id)
- [ ] Devpost https://devpost.com/software/cinetrace-ai still Clickhouse track
- [ ] Vertex budget alert 50%/90% of credits
- [ ] ClickHouse trial/billing covers late-September judging if needed
- [ ] `SUPERVISOR_RUN_PUBLIC=true` on Cloud Run; limiter 5/hour; `max-instances=1`

## Fresh $ demo (optional)

If “after recorded dry-runs” is $0 and you want a first-run delta on camera:

```bash
uv run python -m cinetrace.clickhouse.reset_proposals
```

That truncates `remediation_proposals` only. Do not truncate `render_jobs`.
