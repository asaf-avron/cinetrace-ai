"""What the waste costs, priced in ClickHouse rather than in Python.

The previous version pulled every job over the wire and summed in a loop. That
worked at 62 rows and falls over at 200,000. Everything here is an aggregate
that runs on the cluster; only totals and a top-N list come back.

Two numbers, because they answer different questions:

- **open** — waste burning right now: zombies holding GPUs, idle queue entries
  holding reserved slots, failures and overruns from the last 48 hours. This is
  what an agent can still do something about, and it is the number that moves
  when a human approves a remediation.
- **historical** — the same pricing over however much history the farm holds,
  measured rather than assumed. Nobody can recover it; it exists to size the
  problem honestly.

Rate assumptions (studio-lot ballpark for the judge narrative, not a quote):

- ``GPU_HOUR_USD = 3.50`` — dedicated GPU render slot, GCP A100-class order of
  magnitude.
- ``CPU_HOUR_USD = 0.12`` — CPU render path, n2-standard vCPU order of magnitude.

Waste attribution is one primary class per job, defined in ``job_waste``
(``006_cohort_baselines.sql``), so the headline is never double-counted.
``retry_loop`` is a tag that overlaps ``failed``; it is counted in the category
card and never added to the total again.

Recovery is credited on **human approval**, not on the agent's proposal. An
agent finding waste does not reduce the bill; a supervisor approving the fix
does.
"""

from __future__ import annotations

from typing import Any

from cinetrace.clickhouse.client import get_client
from cinetrace.clickhouse.queries import run_with_stats

GPU_HOUR_USD = 3.50
CPU_HOUR_USD = 0.12
# Only used if the farm is empty and dateDiff has nothing to measure.
HISTORY_DAYS_FALLBACK = 90

CATEGORY_ORDER = ("failed", "retry_loops", "idle_queue", "zombies", "overruns")

CATEGORY_CLASS = {
    "failed": "failed",
    "idle_queue": "idle_queue",
    "zombies": "zombie",
    "overruns": "overrun",
}

ASSUMPTIONS = {
    "gpu_hour_usd": GPU_HOUR_USD,
    "cpu_hour_usd": CPU_HOUR_USD,
    "idle_queue_priced_as": "reserved_gpu_slot_hours",
    "overrun_baseline": "per-cohort tDigest fence, p50 + 3 * (p95 - p50)",
    "zombie_age": "running and started_at older than 6 hours",
    "open_window": "running, queued, or ended in the last 48 hours",
    "recovery": "credited when a human approves the proposal, not when the agent files it",
}

_USD = "(waste_cpu_hours * {cpu:Float64} + waste_gpu_hours * {gpu:Float64})"

TOTALS = f"""
WITH
    approved AS (
        SELECT DISTINCT job_id FROM proposal_state WHERE decision = 'approved'
    ),
    pending AS (
        SELECT DISTINCT job_id FROM proposal_state WHERE decision = 'pending'
    )
SELECT
    count() AS total_jobs,
    countIf(waste_class != 'healthy') AS waste_jobs,
    countIf(is_open) AS open_jobs,

    round(sumIf({_USD}, is_open), 2) AS open_usd,
    round(sumIf(waste_cpu_hours, is_open), 1) AS open_cpu_hours,
    round(sumIf(waste_gpu_hours, is_open), 1) AS open_gpu_hours,

    round(sumIf({_USD}, is_open AND job_id IN approved), 2) AS approved_usd,
    countIf(is_open AND job_id IN approved) AS approved_jobs,
    round(sumIf({_USD}, is_open AND job_id IN pending), 2) AS pending_usd,
    countIf(is_open AND job_id IN pending) AS pending_jobs,

    round(sumIf({_USD}, waste_class != 'healthy'), 2) AS historical_usd,
    round(sumIf(waste_cpu_hours, waste_class != 'healthy'), 1) AS historical_cpu_hours,
    round(sumIf(waste_gpu_hours, waste_class != 'healthy'), 1) AS historical_gpu_hours,

    -- The historical sum has no date bound, so it covers however much history
    -- the farm currently holds. The live ticker grows that every day up to the
    -- 100-day TTL, so annualising against a hardcoded 90 would inflate the
    -- figure by a few percent today and 11% once the window fills. Measure it.
    greatest(dateDiff('day', min(started_at), now('UTC')), 1) AS history_days
FROM job_waste
"""

# Output aliases must not shadow the columns they aggregate: `AS waste_cpu_hours`
# over `sum(waste_cpu_hours)` makes the *_USD expression resolve to the alias,
# which ClickHouse rejects as an aggregate inside an aggregate.
CATEGORIES = f"""
SELECT
    waste_class AS category,
    count() AS job_count,
    countIf(is_open) AS open_count,
    round(sum({_USD}), 2) AS waste_usd,
    round(sumIf({_USD}, is_open), 2) AS open_usd,
    round(sum(waste_cpu_hours), 1) AS cpu_hours_total,
    round(sum(waste_gpu_hours), 1) AS gpu_hours_total
FROM job_waste
WHERE waste_class != 'healthy'
GROUP BY category
"""

RETRY_LOOP_CATEGORY = f"""
SELECT
    count() AS job_count,
    countIf(is_open) AS open_count,
    round(sum({_USD}), 2) AS waste_usd,
    round(sumIf({_USD}, is_open), 2) AS open_usd,
    round(sum(waste_cpu_hours), 1) AS cpu_hours_total,
    round(sum(waste_gpu_hours), 1) AS gpu_hours_total
FROM job_waste
WHERE retry_loop AND waste_class != 'healthy'
"""

TOP_OPEN = f"""
WITH decided AS (
    SELECT job_id, argMax(decision, created_at) AS decision
    FROM proposal_state GROUP BY job_id
)
SELECT
    w.job_id AS job_id,
    w.show AS show,
    w.shot AS shot,
    w.renderer AS renderer,
    w.host AS host,
    w.status AS status,
    w.waste_class AS waste_class,
    w.retry_loop AS retry_loop,
    w.error_class AS error_class,
    w.retry_count AS retry_count,
    round(w.waste_cpu_hours, 1) AS cpu_hours_wasted,
    round(w.waste_gpu_hours, 1) AS gpu_hours_wasted,
    round(w.waste_cpu_hours * {{cpu:Float64}} + w.waste_gpu_hours * {{gpu:Float64}}, 2) AS waste_usd,
    round(w.hours_per_frame, 3) AS hours_per_frame,
    round(toFloat64(w.cohort_p50), 3) AS cohort_p50,
    w.frames_done AS frames_done,
    w.frames_total AS frames_total,
    coalesce(d.decision, 'none') AS decision
FROM job_waste AS w
LEFT JOIN decided AS d ON d.job_id = w.job_id
WHERE w.is_open
ORDER BY waste_usd DESC
LIMIT {{limit:UInt32}}
"""


def hours_to_usd(cpu_hours: float, gpu_hours: float) -> float:
    """Price a pair of hour counts. Kept as a function so tests can assert the math."""
    return cpu_hours * CPU_HOUR_USD + gpu_hours * GPU_HOUR_USD


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _hours(value: Any) -> float:
    return round(float(value or 0), 1)


def fetch_impact(top_n: int = 25) -> dict[str, Any]:
    """Aggregate the whole farm on the cluster and return totals plus a top-N."""
    rates = {"cpu": CPU_HOUR_USD, "gpu": GPU_HOUR_USD}
    client = get_client()
    try:
        totals_rows, _cols, stats = run_with_stats(client, TOTALS, rates)
        totals = totals_rows[0] if totals_rows else {}

        cat_rows, _cc, _cs = run_with_stats(client, CATEGORIES, rates)
        by_class = {row["category"]: row for row in cat_rows}

        retry_rows, _rc, _rs = run_with_stats(client, RETRY_LOOP_CATEGORY, rates)
        by_class["retry_loops"] = retry_rows[0] if retry_rows else {}

        top_rows, _tc, _ts = run_with_stats(
            client, TOP_OPEN, {**rates, "limit": top_n}
        )
    finally:
        client.close()

    def _category(name: str) -> dict[str, Any]:
        row = by_class.get(CATEGORY_CLASS.get(name, name), {}) or {}
        return {
            "category": name,
            "job_count": int(row.get("job_count") or 0),
            "open_count": int(row.get("open_count") or 0),
            "waste_usd": _money(row.get("waste_usd")),
            "open_usd": _money(row.get("open_usd")),
            "waste_cpu_hours": _hours(row.get("cpu_hours_total")),
            "waste_gpu_hours": _hours(row.get("gpu_hours_total")),
        }

    open_usd = _money(totals.get("open_usd"))
    approved_usd = _money(totals.get("approved_usd"))
    pending_usd = _money(totals.get("pending_usd"))
    historical_usd = _money(totals.get("historical_usd"))
    history_days = int(totals.get("history_days") or HISTORY_DAYS_FALLBACK)

    return {
        "source": "clickhouse",
        "open": {
            "usd": open_usd,
            "remaining_usd": _money(open_usd - approved_usd),
            "approved_usd": approved_usd,
            "pending_usd": pending_usd,
            "job_count": int(totals.get("open_jobs") or 0),
            "approved_jobs": int(totals.get("approved_jobs") or 0),
            "pending_jobs": int(totals.get("pending_jobs") or 0),
            "cpu_hours": _hours(totals.get("open_cpu_hours")),
            "gpu_hours": _hours(totals.get("open_gpu_hours")),
        },
        "historical": {
            "usd": historical_usd,
            "days": history_days,
            "annualized_usd": _money(historical_usd * 365 / history_days),
            "job_count": int(totals.get("waste_jobs") or 0),
            "total_jobs": int(totals.get("total_jobs") or 0),
            "cpu_hours": _hours(totals.get("historical_cpu_hours")),
            "gpu_hours": _hours(totals.get("historical_gpu_hours")),
        },
        "recovery_state": (
            "none"
            if approved_usd <= 0
            else ("full" if approved_usd >= open_usd else "partial")
        ),
        "categories": [_category(name) for name in CATEGORY_ORDER],
        "top_jobs": top_rows,
        "assumptions": ASSUMPTIONS,
        "stats": stats,
    }
