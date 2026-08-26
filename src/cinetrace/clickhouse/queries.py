"""The SQL CineTrace runs against ClickHouse. Real queries, no mocked rows.

Two layers, and the difference matters when reading the UI:

- **Detection** (``ALL_WASTE``) is deterministic. Fixed SQL over the
  ``job_waste`` view, so the same farm always yields the same findings. These
  are the panels on the supervisor page.
- **Investigation** is agentic. The Diagnostic Sentinel writes its own
  drill-down SQL through MCP ``run_query``; those statements are captured at
  runtime and shown in the MCP evidence panel, not hardcoded here.

The detection SQL no longer carries magic numbers. ``cpu_hours >= 100`` became
``hours_per_frame > overrun_fence`` where the fence is a per-cohort tDigest
upper bound from ``006_cohort_baselines.sql``.
"""

from __future__ import annotations

from typing import Any

# What the Sentinel is told about the data model. It writes its own SQL from
# this, so the brief has to be accurate and has to warn about the row counts --
# an unbounded scan of frame_samples is the one way an agent can hurt here.
SCHEMA_BRIEF = """
ClickHouse database `default`. Four objects matter:

render_jobs  (~200k rows, one per render job, 90 days)
    job_id String, show, shot, renderer, host, status
    status is one of: completed, failed, running, queued
    started_at DateTime64, ended_at Nullable(DateTime64)
    cpu_hours Float64, gpu_hours Float64, queue_wait_seconds UInt32
    retry_count UInt8, error_class (oom|license|crash|timeout|disk|''),
    frames_total UInt32, frames_done UInt32

frame_samples  (~250M rows, telemetry every 12s of wall time per job)
    ts DateTime64, job_id String, show, host, frame UInt32,
    gpu_util UInt8, vram_used_mb UInt32, vram_total_mb UInt32,
    cpu_util UInt8, rss_mb UInt32, state (load|render|save)
    ORDER BY (job_id, ts), with a projection ordered by (host, ts).
    ALWAYS bound this table by job_id or host AND a time range.

job_waste  (view over render_jobs)
    every render_jobs column plus:
    waste_class (zombie|failed|idle_queue|overrun|healthy),
    waste_cpu_hours, waste_gpu_hours, hours_per_frame,
    cohort_p50, cohort_fence, retry_loop UInt8, is_open UInt8
    is_open = an action can still change the outcome: the job is holding a
    GPU or a queue slot right now (zombie, idle_queue), or it failed in the
    last 48h and will be resubmitted. Overruns are completed and can never
    be open -- their hours are already spent.

cohort_baselines  (view)
    show, renderer, p50, p95, p995, overrun_fence, cpu_p50, gpu_p50
    tDigest percentiles of hours-per-frame per (show, renderer) cohort.

farm_minute  (AggregatingMergeTree, ~800k rows)
    minute, show, and aggregate STATES: samples, active_jobs, active_hosts,
    gpu_util_q, cpu_util_q, vram_peak.
    Read with -Merge combinators, e.g. uniqMerge(active_jobs).

shots  (delivery schedule)
    show, shot, sequence, review_at DateTime, frames_required,
    frames_delivered, priority
"""

# --------------------------------------------------------------------------
# Deterministic detection layer
# --------------------------------------------------------------------------

FAILED = """
SELECT job_id, show, shot, renderer, host, error_class, retry_count,
       round(cpu_hours, 1) AS cpu_hours, round(gpu_hours, 1) AS gpu_hours,
       count() OVER () AS total_matches
FROM job_waste
WHERE waste_class = 'failed' AND is_open
ORDER BY (cpu_hours + gpu_hours) DESC, job_id
LIMIT 25
"""

RETRY_LOOPS = """
SELECT job_id, show, shot, renderer, host, error_class, retry_count,
       round(cpu_hours + gpu_hours, 1) AS burned_hours,
       count() OVER () AS total_matches
FROM job_waste
WHERE retry_loop AND is_open
ORDER BY retry_count DESC, burned_hours DESC
LIMIT 25
"""

IDLE_QUEUE = """
SELECT job_id, show, shot, renderer, queue_wait_seconds,
       round(queue_wait_seconds / 3600, 1) AS slot_hours_held,
       count() OVER () AS total_matches
FROM job_waste
WHERE waste_class = 'idle_queue'
ORDER BY queue_wait_seconds DESC, job_id
LIMIT 25
"""

ZOMBIES = """
SELECT job_id, show, shot, renderer, host, started_at,
       round(dateDiff('second', started_at, now('UTC')) / 3600, 1) AS age_hours,
       round(cpu_hours, 1) AS cpu_hours, round(gpu_hours, 1) AS gpu_hours,
       frames_done, frames_total,
       count() OVER () AS total_matches
FROM job_waste
WHERE waste_class = 'zombie'
ORDER BY started_at ASC, job_id
LIMIT 25
"""

# The one query that shows why the cohort baselines exist: the same job is
# "normal" or "3.4x its cohort" depending on which renderer it ran on.
# Overruns are completed jobs, so they are never "open" -- nothing can be
# reclaimed. They are shown because the pattern is what needs fixing upstream.
OVERRUNS = """
SELECT job_id, show, shot, renderer,
       round(hours_per_frame, 3) AS hours_per_frame,
       round(toFloat64(cohort_p50), 3) AS cohort_p50,
       round(toFloat64(cohort_fence), 3) AS cohort_fence,
       round(hours_per_frame / nullIf(cohort_p50, 0), 1) AS x_over_cohort,
       round(cpu_hours + gpu_hours, 1) AS total_hours,
       count() OVER () AS total_matches
FROM job_waste
WHERE waste_class = 'overrun'
  AND coalesce(ended_at, started_at) >= now('UTC') - INTERVAL 7 DAY
ORDER BY x_over_cohort DESC, total_hours DESC
LIMIT 25
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

CATEGORY_NOTES = {
    "failed": "Burned hours with no deliverable frames.",
    "retry_loops": "Same job resubmitted 4+ times; the fix is upstream.",
    "idle_queue": "Reserved slot sitting unused for an hour or more.",
    "zombies": "Still 'running' 6+ hours in, frames barely moving.",
    "overruns": "Hours per frame above the (show, renderer) tDigest fence.",
}

MCP_TOOLS = ("list_databases", "list_tables", "run_query")

# --------------------------------------------------------------------------
# ClickHouse-native investigation queries
# --------------------------------------------------------------------------

# ASOF JOIN: for every OOM failure, the last host telemetry sample recorded
# before the job died. A plain JOIN cannot express "nearest preceding row";
# doing this in Python would mean pulling millions of samples over the wire.
#
# Both sides are narrowed before the join. ASOF builds its right side in
# memory, so joining against the raw 235M-row table is a fast way to exhaust
# the cluster -- bound it by the failure window and by the handful of hosts
# actually involved. The by_host projection then serves the (host, ts) seek.
ROOT_CAUSE_ASOF = """
WITH oom_failures AS
(
    SELECT job_id, show, shot, host, error_class, ended_at
    FROM render_jobs
    WHERE status = 'failed'
      AND error_class = 'oom'
      AND ended_at IS NOT NULL
      AND ended_at >= now('UTC') - INTERVAL 48 HOUR
    ORDER BY ended_at DESC
    LIMIT 40
)
SELECT
    j.job_id AS job_id,
    j.show AS show,
    j.shot AS shot,
    j.host AS host,
    j.error_class AS error_class,
    j.ended_at AS died_at,
    s.ts AS last_sample_at,
    dateDiff('second', s.ts, j.ended_at) AS seconds_before_death,
    s.vram_used_mb AS vram_used_mb,
    s.vram_total_mb AS vram_total_mb,
    round(100 * s.vram_used_mb / s.vram_total_mb, 1) AS vram_pct,
    s.gpu_util AS gpu_util,
    s.frame AS last_frame
FROM oom_failures AS j
ASOF LEFT JOIN
(
    SELECT host, ts, frame, gpu_util, vram_used_mb, vram_total_mb
    FROM frame_samples
    WHERE ts >= now('UTC') - INTERVAL 50 HOUR
      AND host IN (SELECT host FROM oom_failures)
) AS s
    ON j.host = s.host AND s.ts <= j.ended_at
ORDER BY vram_pct DESC, job_id
LIMIT 12
"""

# Window function over failures per host. A host that fails repeatedly in a
# short span is a bad node, not six unlucky jobs — lagInFrame gives the gap to
# the previous failure on the same host without a self-join.
RETRY_STORMS = """
SELECT
    host,
    show,
    job_id,
    error_class,
    ended_at,
    prev_failure_at,
    dateDiff('minute', prev_failure_at, ended_at) AS minutes_since_prev
FROM
(
    SELECT
        host, show, job_id, error_class, ended_at,
        lagInFrame(ended_at) OVER (
            PARTITION BY host ORDER BY ended_at
            ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
        ) AS prev_failure_at
    FROM render_jobs
    WHERE status = 'failed'
      AND ended_at IS NOT NULL
      AND ended_at >= now('UTC') - INTERVAL 48 HOUR
)
WHERE prev_failure_at > '1970-01-02 00:00:00'
  AND dateDiff('minute', prev_failure_at, ended_at) <= 90
ORDER BY ended_at DESC
LIMIT 20
"""

# Earliest-deadline-first projection: walk each show's shot queue in review
# order and accumulate the frames ahead of each shot. A shot misses dailies if
# the farm cannot clear everything ahead of it before review_at.
#
# slots_recovered adds back the hosts currently pinned by zombies and idle
# queue entries -- that difference is the whole product pitch.
SHOTS_AT_RISK = """
WITH
    live_slots AS (
        SELECT show, count() AS slots
        FROM render_jobs
        WHERE status = 'running'
          AND started_at >= now('UTC') - INTERVAL 6 HOUR
        GROUP BY show
    ),
    stuck_slots AS (
        SELECT show, count() AS slots
        FROM job_waste
        WHERE waste_class IN ('zombie', 'idle_queue')
        GROUP BY show
    ),
    show_rate AS (
        SELECT show, avg(p50) AS hours_per_frame
        FROM cohort_baselines
        GROUP BY show
    )
SELECT
    show, shot, sequence, priority, review_at,
    frames_required, frames_delivered, frames_remaining,
    slots_now, slots_recovered,
    round(hours_to_review, 1) AS hours_to_review,
    round(eta_now, 1) AS eta_hours_now,
    round(eta_recovered, 1) AS eta_hours_recovered,
    at_risk,
    at_risk AND (eta_recovered <= hours_to_review) AS recoverable
FROM
(
    SELECT
        s.show AS show,
        s.shot AS shot,
        s.sequence AS sequence,
        s.priority AS priority,
        s.review_at AS review_at,
        s.frames_required AS frames_required,
        s.frames_delivered AS frames_delivered,
        s.frames_required - s.frames_delivered AS frames_remaining,
        greatest(coalesce(l.slots, 0), 1) AS slots_now,
        greatest(coalesce(l.slots, 0) + coalesce(k.slots, 0), 1) AS slots_recovered,
        coalesce(r.hours_per_frame, 0.3) AS hpf,
        dateDiff('second', now('UTC'), s.review_at) / 3600 AS hours_to_review,
        sum(s.frames_required - s.frames_delivered) OVER (
            PARTITION BY s.show ORDER BY s.review_at
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS frames_ahead,
        frames_ahead * hpf / slots_now AS eta_now,
        frames_ahead * hpf / slots_recovered AS eta_recovered,
        eta_now > hours_to_review AS at_risk
    FROM shots AS s FINAL
    LEFT JOIN live_slots AS l ON l.show = s.show
    LEFT JOIN stuck_slots AS k ON k.show = s.show
    LEFT JOIN show_rate AS r ON r.show = s.show
    WHERE s.frames_delivered < s.frames_required
      AND s.review_at > now('UTC')
)
ORDER BY at_risk DESC, hours_to_review ASC
LIMIT 200
"""

# Reads the AggregatingMergeTree rollup, not the 250M-row fact table. The
# -Merge combinators finish the aggregate states the MV wrote on insert.
FARM_TIMELINE = """
SELECT
    toStartOfHour(minute) AS hour,
    show,
    countMerge(samples) AS samples,
    uniqMerge(active_jobs) AS jobs,
    uniqMerge(active_hosts) AS hosts,
    round(arrayElement(quantilesTDigestMerge(0.5, 0.95, 0.995)(gpu_util_q), 1), 1) AS gpu_p50,
    round(arrayElement(quantilesTDigestMerge(0.5, 0.95, 0.995)(gpu_util_q), 3), 1) AS gpu_p995,
    maxMerge(vram_peak) AS vram_peak_mb
FROM farm_minute
WHERE minute >= now('UTC') - INTERVAL 48 HOUR
GROUP BY hour, show
ORDER BY hour ASC, show ASC
"""

FARM_ROLLUP = """
SELECT
    toDate(coalesce(ended_at, started_at), 'UTC') AS day,
    count() AS jobs,
    round(sum(cpu_hours), 1) AS cpu_hours,
    round(sum(gpu_hours), 1) AS gpu_hours
FROM render_jobs
WHERE coalesce(ended_at, started_at) >= now('UTC') - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
"""

FARM_SCALE = """
SELECT
    (SELECT count() FROM render_jobs) AS jobs,
    (SELECT count() FROM frame_samples) AS samples,
    (SELECT count() FROM shots) AS shots,
    (SELECT uniq(host) FROM render_jobs) AS hosts,
    (SELECT uniq(show) FROM render_jobs) AS shows,
    (SELECT count() FROM farm_minute) AS rollup_rows,
    (SELECT round(dateDiff('day', min(started_at), now('UTC'))) FROM render_jobs) AS days_of_history,
    (SELECT sum(rows) FROM system.parts
      WHERE active AND table = 'frame_samples') AS parts_rows,
    (SELECT round(sum(bytes_on_disk) / 1048576, 1) FROM system.parts
      WHERE active AND table = 'frame_samples') AS samples_mb
"""

QUERY_LOG = """
SELECT
    event_time,
    user,
    read_rows,
    round(query_duration_ms) AS duration_ms,
    substring(query, 1, 320) AS query
FROM system.query_log
WHERE type = 'QueryFinish'
  AND (positionCaseInsensitive(query, 'render_jobs') > 0
       OR positionCaseInsensitive(query, 'frame_samples') > 0
       OR positionCaseInsensitive(query, 'job_waste') > 0)
ORDER BY event_time DESC
LIMIT 12
"""


# --------------------------------------------------------------------------
# Execution helpers
# --------------------------------------------------------------------------


def _stats(result: Any) -> dict[str, Any]:
    """Per-query performance from the X-ClickHouse-Summary response header.

    Read straight off the response rather than from system.query_log, which is
    flushed asynchronously and would lag the UI by several seconds.
    """
    summary = getattr(result, "summary", None) or {}

    def _int(key: str) -> int:
        try:
            return int(summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    rows_read = _int("read_rows")
    bytes_read = _int("read_bytes")
    elapsed_ms = _int("elapsed_ns") / 1_000_000
    rows_per_sec = int(rows_read / (elapsed_ms / 1000)) if elapsed_ms > 0 else 0
    return {
        "rows_read": rows_read,
        "bytes_read": bytes_read,
        "mb_read": round(bytes_read / 1_048_576, 1),
        "elapsed_ms": round(elapsed_ms, 1),
        "rows_per_sec": rows_per_sec,
    }


def run_with_stats(
    client: Any, sql: str, parameters: dict | None = None
) -> tuple[list[dict], list[str], dict[str, Any]]:
    """Run SQL and return ``(rows, columns, performance stats)``."""
    result = client.query(sql.strip(), parameters=parameters or {})
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    return rows, list(result.column_names), _stats(result)


def _panel(client: Any, name: str, sql: str) -> dict[str, Any]:
    rows, columns, stats = run_with_stats(client, sql)
    total = 0
    if "total_matches" in columns:
        columns = [c for c in columns if c != "total_matches"]
        if rows:
            total = int(rows[0].get("total_matches") or 0)
        for row in rows:
            row.pop("total_matches", None)
    return {
        "id": name,
        "label": CATEGORY_LABELS.get(name, name),
        "note": CATEGORY_NOTES.get(name, ""),
        "sql": sql.strip(),
        "mcp_tool": "run_query",
        "columns": columns,
        "rows": rows,
        "count": len(rows),
        "total_matches": total or len(rows),
        "stats": stats,
    }


def fetch_waste_showcase() -> dict:
    """The five deterministic detection queries, with live rows and timings."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        queries = [_panel(client, name, sql) for name, sql in ALL_WASTE.items()]
        summary = {panel["id"]: panel["count"] for panel in queries}
        return {
            "source": "clickhouse",
            "mcp_tools": list(MCP_TOOLS),
            "note": (
                "Deterministic detection layer. The Sentinel runs this same SQL "
                "through MCP run_query, then writes its own drill-downs from there. "
                "Thresholds come from per-cohort tDigest baselines, not constants."
            ),
            "summary": summary,
            "queries": queries,
        }
    finally:
        client.close()


def fetch_root_cause() -> dict:
    """ASOF JOIN evidence: the last host sample before each OOM death."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        rows, columns, stats = run_with_stats(client, ROOT_CAUSE_ASOF)
        storms, storm_cols, storm_stats = run_with_stats(client, RETRY_STORMS)
        return {
            "source": "clickhouse",
            "asof": {
                "sql": ROOT_CAUSE_ASOF.strip(),
                "columns": columns,
                "rows": rows,
                "count": len(rows),
                "stats": stats,
                "note": (
                    "ASOF LEFT JOIN pairs each OOM failure with the nearest "
                    "preceding telemetry sample on the same host."
                ),
            },
            "storms": {
                "sql": RETRY_STORMS.strip(),
                "columns": storm_cols,
                "rows": storms,
                "count": len(storms),
                "stats": storm_stats,
                "note": (
                    "lagInFrame over failures per host: repeat failures inside "
                    "90 minutes point at the node, not the job."
                ),
            },
        }
    finally:
        client.close()


def fetch_shots_at_risk() -> dict:
    """Delivery risk: which shots miss their review, and which are recoverable."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        rows, columns, stats = run_with_stats(client, SHOTS_AT_RISK)
        at_risk = [r for r in rows if r.get("at_risk")]
        recoverable = [r for r in at_risk if r.get("recoverable")]
        next_review = min((r["review_at"] for r in at_risk), default=None)
        return {
            "source": "clickhouse",
            "sql": SHOTS_AT_RISK.strip(),
            "columns": columns,
            "rows": rows,
            "stats": stats,
            "at_risk_count": len(at_risk),
            "recoverable_count": len(recoverable),
            "tracked_count": len(rows),
            "next_review_at": next_review,
            "shows_at_risk": sorted({r["show"] for r in at_risk}),
            # Slots held by zombie and idle-queue jobs, counted once per show.
            "slots_stuck": sum(
                max(int(r["slots_recovered"]) - int(r["slots_now"]), 0)
                for r in {row["show"]: row for row in rows}.values()
            ),
            "note": (
                "Earliest-deadline-first projection over the shot queue. "
                "recoverable = would make review if the zombie and idle-queue "
                "slots were released now."
            ),
        }
    finally:
        client.close()


def fetch_farm_rollup() -> dict:
    """Hours by day plus the per-minute rollup served from the materialized view."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        days, _cols, day_stats = run_with_stats(client, FARM_ROLLUP)
        timeline, _tcols, timeline_stats = run_with_stats(client, FARM_TIMELINE)
        return {
            "source": "clickhouse",
            "sql": FARM_ROLLUP.strip(),
            "days": days,
            "stats": day_stats,
            "timeline": {
                "sql": FARM_TIMELINE.strip(),
                "rows": timeline,
                "stats": timeline_stats,
                "note": (
                    "Served from farm_minute, an AggregatingMergeTree kept current "
                    "by a materialized view. The 250M-row fact table is not touched."
                ),
            },
        }
    finally:
        client.close()


def fetch_farm_scale() -> dict:
    """Headline scale counters, for the 'this is why ClickHouse' strip."""
    from cinetrace.clickhouse.client import get_client

    client = get_client()
    try:
        rows, _cols, stats = run_with_stats(client, FARM_SCALE)
        payload = rows[0] if rows else {}
        payload["stats"] = stats
        payload["source"] = "clickhouse"
        return payload
    finally:
        client.close()


def fetch_query_log() -> dict:
    """Recent cluster-side proof that this SQL really ran here.

    Best-effort: ClickHouse Cloud may deny system.query_log to the app user, in
    which case the response-header stats on each panel still stand on their own.
    """
    from cinetrace.clickhouse.client import get_client

    client = None
    try:
        client = get_client()
        rows, _cols, _stats = run_with_stats(client, QUERY_LOG)
        return {
            "ok": True,
            "source": "system.query_log",
            "sql": QUERY_LOG.strip(),
            "rows": rows,
            "note": "Live query_log on the same ClickHouse service the agents use.",
        }
    except Exception as exc:  # noqa: BLE001 — Cloud may deny system tables
        return {
            "ok": False,
            "source": "system.query_log",
            "sql": QUERY_LOG.strip(),
            "rows": [],
            "note": (
                f"query_log unavailable ({type(exc).__name__}). "
                "Per-query timings on each panel come from the response summary."
            ),
        }
    finally:
        if client is not None:
            client.close()
