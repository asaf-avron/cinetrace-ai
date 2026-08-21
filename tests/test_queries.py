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
    from cinetrace.clickhouse.queries import FARM_ROLLUP, QUERY_LOG

    assert "toDate" in FARM_ROLLUP
    assert "cpu_hours" in FARM_ROLLUP
    assert "gpu_hours" in FARM_ROLLUP
    assert "system.query_log" in QUERY_LOG


def test_query_log_sql_includes_cost_columns() -> None:
    from cinetrace.clickhouse.queries import QUERY_LOG, query_log_sql

    for column in ("event_time", "user", "query_duration_ms", "read_rows", "result_rows"):
        assert column in QUERY_LOG
    assert "substring(query, 1, 360) AS query" in QUERY_LOG
    core = query_log_sql(())
    assert "event_time" in core
    assert "query_duration_ms" not in core
    assert "read_rows" not in core
    assert "result_rows" not in core


class _QueryResult:
    def __init__(self, names: list[str], rows: list[list]) -> None:
        self.column_names = names
        self.result_rows = rows


class _FailCostThenCoreClient:
    def __init__(self) -> None:
        self.sqls: list[str] = []

    def query(self, sql: str):
        self.sqls.append(sql)
        if "system.columns" in sql:
            raise RuntimeError("system.columns denied")
        if "query_duration_ms" in sql or "read_rows" in sql or "result_rows" in sql:
            raise RuntimeError("UNKNOWN_IDENTIFIER")
        return _QueryResult(
            ["event_time", "user", "query"],
            [["2026-01-01 00:00:00", "default", "SELECT * FROM render_jobs"]],
        )

    def close(self) -> None:
        return None


class _PartialCostClient:
    def query(self, sql: str):
        if "system.columns" in sql:
            return _QueryResult(["name"], [["read_rows"]])
        if "query_duration_ms" in sql or "result_rows" in sql:
            raise RuntimeError("UNKNOWN_IDENTIFIER")
        names = ["event_time", "user", "query"]
        row: list = ["2026-01-01 00:00:00", "default", "SELECT * FROM render_jobs"]
        if "read_rows" in sql:
            names = ["event_time", "user", "read_rows", "query"]
            row = ["2026-01-01 00:00:00", "default", 42, "SELECT * FROM render_jobs"]
        return _QueryResult(names, [row])

    def close(self) -> None:
        return None


def test_fetch_query_log_omits_missing_cost_columns(monkeypatch) -> None:
    from cinetrace.clickhouse import queries

    client = _FailCostThenCoreClient()
    monkeypatch.setattr("cinetrace.clickhouse.client.get_client", lambda: client)
    payload = queries.fetch_query_log()
    assert payload["ok"] is True
    assert "query_duration_ms" in payload["sql"]
    assert payload["rows"][0]["query"] == "SELECT * FROM render_jobs"
    assert "query_duration_ms" not in payload["rows"][0]
    assert "read_rows" not in payload["rows"][0]
    assert "result_rows" not in payload["rows"][0]


def test_fetch_query_log_keeps_present_cost_columns(monkeypatch) -> None:
    from cinetrace.clickhouse import queries

    monkeypatch.setattr(
        "cinetrace.clickhouse.client.get_client", lambda: _PartialCostClient()
    )
    payload = queries.fetch_query_log()
    assert payload["ok"] is True
    assert payload["rows"][0]["read_rows"] == 42
    assert "query_duration_ms" not in payload["rows"][0]
    assert "result_rows" not in payload["rows"][0]


def test_impact_sql_matches_sentinel_predicates() -> None:
    from cinetrace.clickhouse.impact import CLASSIFY_JOBS, HEALTHY_BASELINE

    assert "status = 'failed'" in CLASSIFY_JOBS
    assert "queue_wait_seconds >= 3600" in CLASSIFY_JOBS
    assert "INTERVAL 6 HOUR" in CLASSIFY_JOBS
    assert "cpu_hours >= 100" in CLASSIFY_JOBS
    assert "gpu_hours >= 50" in CLASSIFY_JOBS
    assert "frames_done > 0" in HEALTHY_BASELINE
