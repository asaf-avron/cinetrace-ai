"""Remediation proposals and the human decisions on them.

MCP `run_query` is select-only, so writes go over HTTPS with clickhouse-connect.
Same cluster, same credentials, different client -- the read path an agent gets
is deliberately narrower than the write path the application holds.

Nothing in this module changes a render host. A proposal is a record; approving
one is also just a record. Execution against a real farm would be the next
integration, and it would read this table.
"""

from __future__ import annotations

import re
import time
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

# One run files several proposals in a row and each would otherwise re-run the
# delivery projection. The board only moves on a ticker beat, so a few seconds
# of reuse costs nothing and saves a round trip per proposal.
_AT_RISK_TTL_S = 30.0
_at_risk_cache: tuple[float, frozenset[tuple[str, str]]] | None = None


def _shots_currently_at_risk() -> frozenset[tuple[str, str]]:
    global _at_risk_cache
    now = time.monotonic()
    if _at_risk_cache and now - _at_risk_cache[0] < _AT_RISK_TTL_S:
        return _at_risk_cache[1]
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    shots = frozenset(
        (str(row["show"]), str(row["shot"]))
        for row in fetch_shots_at_risk()["rows"]
        if row.get("at_risk")
    )
    _at_risk_cache = (now, shots)
    return shots


# The Orchestrator writes prose, not a field. It says "NEBULA sh0202, NEBULA
# sh0466, NEBULA sh0471" when one job blocks three shots, and "ORBIT sh0194"
# when it has talked itself into a shot that is fine. Pull every SHOW/shot pair
# out and keep the first that the board agrees is actually at risk.
_SHOT_RE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)[\s/]+(sh\d+)")


def _verify_shot(value: str, at_risk: frozenset[tuple[str, str]]) -> str:
    for show, shot in _SHOT_RE.findall(value):
        key = (show.upper(), shot.lower())
        if key in at_risk:
            return f"{key[0]} {key[1]}"
    return ""


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
        shot_at_risk: The show/shot this protects, as "SHOW shotid", or an
            empty string if the job is not blocking a delivery. Recorded only if
            that shot is currently projected to miss its review; a shot that
            still makes its deadline is not protected by anything, and the
            response will tell you when the claim was dropped.
    """
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}")
    # "Protects a review" is the strongest claim this product makes, so it is
    # the one claim a model does not get to assert unchecked. A shot with a
    # review in an hour that is still projected to make it is not protected by
    # anything, and recording it as such would put a false linkage in the audit
    # table the whole page rests on.
    #
    # Dropped rather than raised: ADK propagates a tool exception instead of
    # returning it to the model, so refusing here would abort the run over a
    # detail the proposal does not depend on. The note goes back in the tool
    # response, which the model does see, so its narration can follow.
    verified_shot = ""
    note = ""
    if shot_at_risk.strip():
        verified_shot = _verify_shot(shot_at_risk, _shots_currently_at_risk())
        if not verified_shot:
            note = (
                f"No shot in {shot_at_risk!r} is currently projected to miss its "
                "review, so this proposal is recorded as protecting no delivery. "
                "Say so rather than claiming it saves a shot."
            )
    client = get_client()
    try:
        client.insert(
            "remediation_proposals",
            [[job_id, action, reason, verified_shot, "action_agent", "dry_run", "proposed", "", 0]],
            column_names=PROPOSAL_COLUMNS,
        )
    finally:
        client.close()
    return {
        "job_id": job_id,
        "action": action,
        "reason": reason,
        "shot_at_risk": verified_shot,
        "shot_at_risk_note": note,
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
