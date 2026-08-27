"""Impact pricing. The arithmetic now lives in ClickHouse, so this checks the
rate model and the SQL contract rather than re-implementing the sums in Python.
"""

import pytest

from cinetrace.clickhouse.client import credentials_ready
from cinetrace.clickhouse.impact import (
    ASSUMPTIONS,
    CATEGORIES,
    CPU_HOUR_USD,
    GPU_HOUR_USD,
    TOP_OPEN,
    TOTALS,
    hours_to_usd,
)

needs_clickhouse = pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)


def test_rates_are_the_documented_ones() -> None:
    assert GPU_HOUR_USD == 3.50
    assert CPU_HOUR_USD == 0.12
    assert ASSUMPTIONS["gpu_hour_usd"] == 3.50
    assert "tDigest" in ASSUMPTIONS["overrun_baseline"]
    assert "approves" in ASSUMPTIONS["recovery"]


def test_hours_price_at_the_stated_rates() -> None:
    assert hours_to_usd(0, 10) == pytest.approx(35.0)
    assert hours_to_usd(100, 0) == pytest.approx(12.0)
    assert hours_to_usd(96, 48) == pytest.approx(96 * 0.12 + 48 * 3.50)


def test_totals_sql_aggregates_on_the_cluster() -> None:
    """No SELECT of individual jobs: 198k rows must never cross the wire."""
    assert "FROM job_waste" in TOTALS
    assert "sumIf" in TOTALS
    assert "is_open" in TOTALS
    # Recovery is credited on approval, not on the agent filing a proposal.
    assert "decision = 'approved'" in TOTALS
    assert "decision = 'pending'" in TOTALS


def test_category_aliases_do_not_shadow_aggregated_columns() -> None:
    """ClickHouse rejects sum(x) AS x when another aggregate also reads x."""
    assert "AS cpu_hours_total" in CATEGORIES
    assert "AS gpu_hours_total" in CATEGORIES
    assert "AS waste_cpu_hours" not in CATEGORIES


def test_top_open_is_bounded() -> None:
    assert "LIMIT {limit:UInt32}" in TOP_OPEN
    assert "WHERE w.is_open" in TOP_OPEN


def test_history_span_is_measured_not_assumed() -> None:
    """The historical sum has no date bound, so it covers whatever the farm
    holds. Annualising that against a hardcoded 90 overstates the yearly figure
    by more every day the ticker runs.
    """
    assert "dateDiff('day', min(started_at), now('UTC'))" in TOTALS


@needs_clickhouse
def test_live_impact_shape() -> None:
    from cinetrace.clickhouse.impact import fetch_impact

    impact = fetch_impact(top_n=5)
    open_now = impact["open"]
    history = impact["historical"]

    assert history["total_jobs"] > 100_000, "the farm should be at studio scale"
    assert history["usd"] > open_now["usd"], "all history must exceed what is open now"
    assert open_now["remaining_usd"] == pytest.approx(
        open_now["usd"] - open_now["approved_usd"], abs=0.02
    )
    assert len(impact["top_jobs"]) <= 5
    assert {c["category"] for c in impact["categories"]} == {
        "failed", "retry_loops", "idle_queue", "zombies", "overruns",
    }


@needs_clickhouse
def test_annualised_figure_divides_by_the_span_it_summed() -> None:
    from cinetrace.clickhouse.impact import fetch_impact

    history = fetch_impact(top_n=1)["historical"]
    days = history["days"]
    assert days >= 90, "the seed lays down about three months of jobs"
    assert history["annualized_usd"] == pytest.approx(
        history["usd"] * 365 / days, rel=0.01
    )


@needs_clickhouse
def test_overruns_are_never_counted_as_open() -> None:
    """A completed job's hours are spent; no action reclaims them."""
    from cinetrace.clickhouse.impact import fetch_impact

    overruns = next(
        c for c in fetch_impact()["categories"] if c["category"] == "overruns"
    )
    assert overruns["open_count"] == 0
    assert overruns["open_usd"] == 0.0
    assert overruns["waste_usd"] > 0, "they should still show in the 90-day total"
