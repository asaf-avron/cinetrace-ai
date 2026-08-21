"""Remediation proposals and the human decisions on them.

MCP `run_query` is select-only, so writes go over HTTPS with clickhouse-connect.
Same cluster, same credentials, different client -- the read path an agent gets
is deliberately narrower than the write path the application holds.

Nothing in this module changes a render host. A proposal is a record; approving
one is also just a record. Execution against a real farm would be the next
integration, and it would read this table.
"""

from __future__ import annotations

from typing import Any

from cinetrace.clickhouse.client import get_client
from cinetrace.clickhouse.impact import CPU_HOUR_USD, GPU_HOUR_USD
from cinetrace.clickhouse.queries import run_with_stats

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

DECISIONS = frozenset({"approved", "rejected"})

PROPOSAL_COLUMNS = [
    "job_id",
    "action",
    "reason",
    "shot_at_risk",
    "agent",
    "mode",
    "status",
    "outcome",
    "executed",
]


def propose_remediation(
    job_id: str,
    action: str,
    reason: str,
    shot_at_risk: str = "",
) -> dict:
    """Record a dry-run remediation for a wasteful render job, pending human approval.

    Writes one row to ClickHouse. It does not kill, hold, or release anything on
    the farm, and it never will from here -- a supervisor has to approve it
    first.

    Args:
        job_id: The render job to act on, exactly as it appears in render_jobs.
        action: One of hold_license_job, hold_oom_job, stop_retry_loop,
            kill_zombie, release_idle_queue, flag_overrun.
        reason: One sentence of evidence, including the measured number that
            justifies acting.
        shot_at_risk: The show/shot this protects, or an empty string if the
            job is not blocking a delivery.
    """
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}")
    client = get_client()
    try:
        client.insert(
            "remediation_proposals",
            [[job_id, action, reason, shot_at_risk, "action_agent", "dry_run", "proposed", "", 0]],
            column_names=PROPOSAL_COLUMNS,
        )
    finally:
        client.close()
    return {
        "job_id": job_id,
        "action": action,
        "reason": reason,
        "shot_at_risk": shot_at_risk,
        "executed": False,
        "mode": "dry_run",
        "status": "proposed",
        "decision": "pending",
        "persisted": True,
    }


def decide_proposal(
    job_id: str,
    action: str,
    decision: str,
    decided_by: str = "supervisor",
    note: str = "",
) -> dict:
    """Approve or reject a proposal. Append-only: the original proposal is untouched."""
    if decision not in DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}. Allowed: {sorted(DECISIONS)}")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}")
    client = get_client()
    try:
        client.insert(
            "proposal_decisions",
            [[job_id, action, decision, decided_by, note]],
            column_names=["job_id", "action", "decision", "decided_by", "note"],
        )
    finally:
        client.close()
    return {
        "job_id": job_id,
        "action": action,
        "decision": decision,
        "decided_by": decided_by,
        "note": note,
        "executed": False,
        "persisted": True,
    }


# The live farm view: everything still actionable, then the freshest work.
# Never the whole table -- render_jobs is 200k rows and the page shows 60.
LIVE_JOBS = f"""
SELECT
    job_id, show, shot, renderer, host, status,
    started_at, ended_at,
    round(cpu_hours, 1) AS cpu_hours,
    round(gpu_hours, 1) AS gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done,
    waste_class,
    retry_loop,
    is_open,
    round(waste_cpu_hours * {CPU_HOUR_USD} + waste_gpu_hours * {GPU_HOUR_USD}, 2) AS waste_usd
FROM job_waste
WHERE is_open
   OR (status IN ('running', 'queued'))
   OR coalesce(ended_at, started_at) >= now('UTC') - INTERVAL 2 HOUR
ORDER BY
    is_open DESC,
    waste_usd DESC,
    coalesce(ended_at, started_at) DESC
LIMIT {{limit:UInt32}}
"""

PROPOSALS = """
SELECT
    job_id, action, reason, shot_at_risk, agent,
    mode, executed, created_at, decision, decided_by, decided_at, note
FROM proposal_state
ORDER BY created_at DESC
LIMIT {limit:UInt32}
"""


def list_jobs(limit: int = 60) -> list[dict]:
    """Jobs worth showing: open waste first, then the freshest farm activity."""
    client = get_client()
    try:
        rows, _cols, _stats = run_with_stats(client, LIVE_JOBS, {"limit": limit})
        return rows
    finally:
        client.close()


def list_proposals(limit: int = 50) -> list[dict]:
    client = get_client()
    try:
        rows, _cols, _stats = run_with_stats(client, PROPOSALS, {"limit": limit})
        return rows
    finally:
        client.close()
