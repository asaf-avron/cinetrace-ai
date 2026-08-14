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
