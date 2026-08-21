def test_sentinel_instruction_includes_waste_sql() -> None:
    from cinetrace.clickhouse.queries import ALL_WASTE, sentinel_instruction

    text = sentinel_instruction()
    assert "status = 'failed'" in text
    assert "retry_count >= 4" in text
    assert "queue_wait_seconds >= 3600" in text
    assert "status = 'running'" in text
    assert "cpu_hours >= 100" in text
    assert "run_query" in text
    assert list(ALL_WASTE) == [
        "failed",
        "retry_loops",
        "idle_queue",
        "zombies",
        "overruns",
    ]


def test_farm_rollup_sql() -> None:
    from cinetrace.clickhouse.queries import FARM_ROLLUP

    assert "toDate" in FARM_ROLLUP
    assert "cpu_hours" in FARM_ROLLUP
    assert "gpu_hours" in FARM_ROLLUP


def test_impact_sql_matches_sentinel_predicates() -> None:
    from cinetrace.clickhouse.impact import CLASSIFY_JOBS, HEALTHY_BASELINE

    assert "status = 'failed'" in CLASSIFY_JOBS
    assert "queue_wait_seconds >= 3600" in CLASSIFY_JOBS
    assert "INTERVAL 6 HOUR" in CLASSIFY_JOBS
    assert "cpu_hours >= 100" in CLASSIFY_JOBS
    assert "gpu_hours >= 50" in CLASSIFY_JOBS
    assert "frames_done > 0" in HEALTHY_BASELINE
