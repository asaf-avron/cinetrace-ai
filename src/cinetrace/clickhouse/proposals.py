"""Persist dry-run remediations over HTTPS. MCP is select-only by default."""

from __future__ import annotations

from cinetrace.clickhouse.client import get_client

ALLOWED_ACTIONS = frozenset(
    {
        "hold_license_job",
        "hold_oom_job",
        "stop_retry_loop",
        "kill_zombie",
        "release_idle_queue",
        "flag_overrun",
    }
)


def propose_remediation(job_id: str, action: str, reason: str) -> dict:
    """Record a dry-run farm remediation. Does not change any render host."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}"
        )
    client = get_client()
    try:
        client.insert(
            "remediation_proposals",
            [[job_id, action, reason, "dry_run", "proposed", "", 0]],
            column_names=[
                "job_id",
                "action",
                "reason",
                "mode",
                "status",
                "outcome",
                "executed",
            ],
        )
    finally:
        client.close()
    return {
        "job_id": job_id,
        "action": action,
        "reason": reason,
        "executed": False,
        "mode": "dry_run",
        "status": "proposed",
        "persisted": True,
    }


def record_outcome(job_id: str, action: str, outcome: str) -> dict:
    """Mark a dry-run as recorded. Still does not touch any render host."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}"
        )
    client = get_client()
    try:
        client.insert(
            "remediation_proposals",
            [[job_id, action, outcome, "dry_run", "recorded", outcome, 0]],
            column_names=[
                "job_id",
                "action",
                "reason",
                "mode",
                "status",
                "outcome",
                "executed",
            ],
        )
    finally:
        client.close()
    return {
        "job_id": job_id,
        "action": action,
        "outcome": outcome,
        "executed": False,
        "mode": "dry_run",
        "status": "recorded",
        "persisted": True,
    }


def list_jobs() -> list[dict]:
    client = get_client()
    try:
        result = client.query(
            """
            SELECT
                job_id, show, shot, renderer, host, status,
                started_at, ended_at, cpu_hours, gpu_hours,
                queue_wait_seconds, retry_count, error_class,
                frames_total, frames_done
            FROM render_jobs
            ORDER BY
                if(status = 'failed', 0, if(status = 'running', 1, if(status = 'queued', 2, 3))),
                retry_count DESC,
                cpu_hours DESC
            """
        )
        return [dict(zip(result.column_names, row)) for row in result.result_rows]
    finally:
        client.close()


def list_proposals(limit: int = 50) -> list[dict]:
    client = get_client()
    try:
        result = client.query(
            """
            SELECT job_id, action, reason, mode, status, outcome, executed, created_at
            FROM remediation_proposals
            ORDER BY created_at DESC
            LIMIT {lim:UInt32}
            """,
            parameters={"lim": limit},
        )
        return [dict(zip(result.column_names, row)) for row in result.result_rows]
    finally:
        client.close()
