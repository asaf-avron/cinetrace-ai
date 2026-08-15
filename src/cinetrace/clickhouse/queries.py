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
