def test_sentinel_instruction_includes_waste_sql() -> None:
    from cinetrace.clickhouse.queries import sentinel_instruction

    text = sentinel_instruction()
    assert "status = 'failed'" in text
    assert "retry_count >= 4" in text
    assert "queue_wait_seconds >= 3600" in text
    assert "status = 'running'" in text
    assert "cpu_hours >= 100" in text
    assert "run_query" in text
