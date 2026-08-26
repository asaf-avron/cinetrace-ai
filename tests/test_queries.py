"""The SQL contract: real ClickHouse features, and no magic thresholds left."""

import pytest

from cinetrace.clickhouse.client import credentials_ready
from cinetrace.clickhouse.queries import (
    ALL_WASTE,
    FARM_TIMELINE,
    QUERY_LOG,
    ROOT_CAUSE_ASOF,
    SCHEMA_BRIEF,
    SHOTS_AT_RISK,
    RETRY_STORMS,
)

needs_clickhouse = pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)


def test_detection_layer_keeps_its_five_categories() -> None:
    assert list(ALL_WASTE) == [
        "failed",
        "retry_loops",
        "idle_queue",
        "zombies",
        "overruns",
    ]


def test_thresholds_come_from_cohort_baselines_not_constants() -> None:
    """`cpu_hours >= 100` is meaningless across renderers with 10x different costs."""
    all_sql = "\n".join(ALL_WASTE.values())
    assert "cpu_hours >= 100" not in all_sql
    assert "gpu_hours >= 50" not in all_sql
    assert "cohort_fence" in ALL_WASTE["overruns"]
    assert "FROM job_waste" in ALL_WASTE["failed"]
    assert "count() OVER ()" in all_sql
    assert "toFloat64(cohort_p50)" in ALL_WASTE["overruns"]
    assert "toFloat64(cohort_fence)" in ALL_WASTE["overruns"]


def test_root_cause_uses_asof_and_bounds_both_sides() -> None:
    """ASOF materialises its right side; unbounded against 235M rows exhausts the cluster."""
    assert "ASOF LEFT JOIN" in ROOT_CAUSE_ASOF
    assert "s.ts <= j.ended_at" in ROOT_CAUSE_ASOF
    assert "INTERVAL 50 HOUR" in ROOT_CAUSE_ASOF
    assert "host IN (SELECT host FROM oom_failures)" in ROOT_CAUSE_ASOF


def test_retry_storms_use_a_window_function() -> None:
    assert "lagInFrame" in RETRY_STORMS
    assert "PARTITION BY host" in RETRY_STORMS


def test_shots_projection_is_earliest_deadline_first() -> None:
    assert "OVER (" in SHOTS_AT_RISK and "ORDER BY s.review_at" in SHOTS_AT_RISK
    assert "slots_recovered" in SHOTS_AT_RISK
    # shots is a ReplacingMergeTree; without FINAL a tick can read two versions.
    assert "FROM shots AS s FINAL" in SHOTS_AT_RISK


def test_timeline_reads_the_materialized_view_not_the_fact_table() -> None:
    assert "FROM farm_minute" in FARM_TIMELINE
    assert "frame_samples" not in FARM_TIMELINE
    assert "quantilesTDigestMerge" in FARM_TIMELINE
    assert "uniqMerge" in FARM_TIMELINE


def test_schema_brief_warns_the_agent_about_the_fact_table() -> None:
    assert "250M" in SCHEMA_BRIEF or "250 million" in SCHEMA_BRIEF
    assert "ALWAYS bound this table" in SCHEMA_BRIEF
    assert "job_waste" in SCHEMA_BRIEF and "cohort_baselines" in SCHEMA_BRIEF


def test_query_log_covers_the_farm_tables() -> None:
    assert "system.query_log" in QUERY_LOG
    assert "frame_samples" in QUERY_LOG


@needs_clickhouse
def test_live_panels_report_what_they_scanned() -> None:
    from cinetrace.clickhouse.queries import fetch_waste_showcase

    showcase = fetch_waste_showcase()
    assert len(showcase["queries"]) == 5
    for panel in showcase["queries"]:
        assert panel["stats"]["rows_read"] > 0
        assert panel["stats"]["elapsed_ms"] >= 0
        assert "total_matches" not in panel["columns"]
        assert panel["total_matches"] >= panel["count"]
        for row in panel["rows"]:
            assert "total_matches" not in row


@needs_clickhouse
def test_overrun_cohort_values_are_three_decimals() -> None:
    """quantileTDigest is Float32; round() without a widening cast leaks junk."""
    from cinetrace.clickhouse.queries import fetch_waste_showcase

    overruns = next(q for q in fetch_waste_showcase()["queries"] if q["id"] == "overruns")
    if not overruns["rows"]:
        pytest.skip("no overruns in the current 7-day window")
    for row in overruns["rows"]:
        for key in ("cohort_p50", "cohort_fence", "hours_per_frame"):
            value = row[key]
            if value is None:
                continue
            text = f"{float(value):.10f}".rstrip("0")
            decimals = len(text.split(".")[1]) if "." in text else 0
            assert decimals <= 3, f"{key}={value!r} still carries Float32 noise"


@needs_clickhouse
def test_asof_finds_saturated_vram_before_an_oom_death() -> None:
    from cinetrace.clickhouse.queries import fetch_root_cause

    rows = fetch_root_cause()["asof"]["rows"]
    if not rows:
        pytest.skip("no OOM failures in the current 48h window")
    assert max(r["vram_pct"] for r in rows) > 90
    assert all(r["seconds_before_death"] >= 0 for r in rows)


@needs_clickhouse
def test_farm_is_at_studio_scale() -> None:
    from cinetrace.clickhouse.queries import fetch_farm_scale

    scale = fetch_farm_scale()
    assert scale["samples"] > 100_000_000, "ClickHouse should be doing real work"
    assert scale["jobs"] > 100_000
    assert scale["rollup_rows"] > 0, "the materialized view should be populated"


@needs_clickhouse
def test_review_deadlines_stay_inside_their_published_session() -> None:
    """The board must not ratchet into the future.

    A rolled shot gets its next deadline measured from now(); measuring it from
    the deadline it replaced pushes the whole schedule forward a day at a time,
    and after a few days of ticking nothing on the board can ever be late.
    """
    from cinetrace.clickhouse.generate import SESSION_HOURS
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    rows = fetch_shots_at_risk()["rows"]
    assert rows, "the delivery board should be populated"
    for row in rows:
        # +14h is the quarter of the board that slips to the following session.
        limit = SESSION_HOURS[row["show"]] + 14
        assert row["hours_to_review"] <= limit + 1, (
            f"{row['show']} {row['shot']} sits {row['hours_to_review']}h out, "
            f"past its {limit}h session -- the deadlines have drifted"
        )


@needs_clickhouse
def test_delivery_board_has_something_at_stake() -> None:
    """Zero shots at risk makes the product's headline read zero."""
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    shots = fetch_shots_at_risk()
    assert shots["tracked_count"] > 0
    assert shots["slots_stuck"] > 0, "zombie and idle-queue jobs should hold slots"
