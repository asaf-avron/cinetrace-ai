"""Named waste queries. Sentinel must run these via MCP run_query — no invented rows."""

FAILED = """
SELECT job_id, show, shot, status, error_class, retry_count, cpu_hours, gpu_hours
FROM render_jobs
WHERE status = 'failed'
ORDER BY retry_count DESC, job_id
"""

RETRY_LOOPS = """
SELECT job_id, show, shot, status, error_class, retry_count
FROM render_jobs
WHERE retry_count >= 4
ORDER BY retry_count DESC, job_id
"""

IDLE_QUEUE = """
SELECT job_id, show, shot, status, queue_wait_seconds
FROM render_jobs
WHERE status = 'queued' AND queue_wait_seconds >= 3600
ORDER BY queue_wait_seconds DESC, job_id
"""

ZOMBIES = """
SELECT job_id, show, shot, status, started_at, cpu_hours, gpu_hours, frames_done, frames_total
FROM render_jobs
WHERE status = 'running' AND started_at < now('UTC') - INTERVAL 6 HOUR
ORDER BY started_at ASC, job_id
"""

OVERRUNS = """
SELECT job_id, show, shot, status, cpu_hours, gpu_hours
FROM render_jobs
WHERE cpu_hours >= 100 OR gpu_hours >= 50
ORDER BY cpu_hours DESC, job_id
"""

ALL_WASTE = {
    "failed": FAILED,
    "retry_loops": RETRY_LOOPS,
    "idle_queue": IDLE_QUEUE,
    "zombies": ZOMBIES,
    "overruns": OVERRUNS,
}

CATEGORY_LABELS = {
    "failed": "Failed",
    "retry_loops": "Retry loops",
    "idle_queue": "Idle queue",
    "zombies": "Zombies",
    "overruns": "Overruns",
}

MCP_TOOLS = ("list_databases", "list_tables", "run_query")

FARM_ROLLUP = """
SELECT
    toDate(coalesce(ended_at, started_at), 'UTC') AS day,
    count() AS jobs,
    round(sum(cpu_hours), 1) AS cpu_hours,
    round(sum(gpu_hours), 1) AS gpu_hours
FROM render_jobs
GROUP BY day
ORDER BY day
"""


def fetch_waste_showcase() -> dict:
    """Run the five Sentinel queries against live ClickHouse.

    Agents execute this same SQL via MCP ``run_query``. The supervisor UI uses
    clickhouse-connect over HTTPS to the same service so the page can show
    counts and sample rows without spawning stdio MCP on every refresh.
    """
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        queries: list[dict] = []
        summary: dict[str, int] = {}
        for name, sql in ALL_WASTE.items():
            result = client.query(sql.strip())
            rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
            count = len(rows)
            summary[name] = count
            queries.append(
                {
                    "id": name,
                    "label": CATEGORY_LABELS[name],
                    "sql": sql.strip(),
                    "mcp_tool": "run_query",
                    "columns": list(result.column_names),
                    "rows": rows,
                    "count": count,
                }
            )
        return {
            "source": "clickhouse",
            "mcp_tools": list(MCP_TOOLS),
            "note": (
                "Exact Diagnostic Sentinel queries. Agents run these via MCP "
                "run_query; this panel executes the same SQL on the same "
                "ClickHouse service."
            ),
            "summary": summary,
            "queries": queries,
        }
    finally:
        client.close()


def fetch_farm_rollup() -> dict:
    """Hours-by-day from live render_jobs (seed is now()-relative)."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        result = client.query(FARM_ROLLUP.strip())
        rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
        return {
            "source": "clickhouse",
            "sql": FARM_ROLLUP.strip(),
            "days": rows,
        }
    finally:
        client.close()


QUERY_LOG = """
SELECT
    event_time,
    user,
    substring(query, 1, 360) AS query
FROM system.query_log
WHERE type = 'QueryFinish'
  AND positionCaseInsensitive(query, 'render_jobs') > 0
ORDER BY event_time DESC
LIMIT 12
"""


def fetch_query_log() -> dict:
    """Recent ClickHouse query_log rows that touched render_jobs.

    Best-effort proof the cluster ran the Sentinel SQL. Cloud permissions may
    deny system.query_log; the UI then shows the HTTPS showcase only.
    """
    from cinetrace.clickhouse.client import get_client

    client = None
    try:
        client = get_client()
        result = client.query(QUERY_LOG.strip())
        rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
        return {
            "ok": True,
            "source": "system.query_log",
            "sql": QUERY_LOG.strip(),
            "rows": rows,
            "note": "Live query_log on this ClickHouse service (same cluster MCP uses).",
        }
    except Exception as exc:  # noqa: BLE001 — Cloud may deny system tables
        return {
            "ok": False,
            "source": "system.query_log",
            "sql": QUERY_LOG.strip(),
            "rows": [],
            "note": (
                f"query_log unavailable ({type(exc).__name__}). "
                "Sentinel SQL is still on this page via HTTPS."
            ),
        }
    finally:
        if client is not None:
            client.close()


def sentinel_instruction() -> str:
    blocks = "\n\n".join(
        f"{name}:\n{sql.strip()}" for name, sql in ALL_WASTE.items()
    )
    return (
        "You are the Diagnostic Sentinel for CineTrace AI. "
        "Query ClickHouse through your MCP tools only (list_databases, list_tables, run_query). "
        "Do not invent rows. Run these exact queries against render_jobs, then return "
        "concrete job_id values and why each looks wasteful.\n\n"
        f"{blocks}"
    )
