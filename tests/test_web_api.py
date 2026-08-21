"""Supervisor GET APIs. Skip if ClickHouse creds are missing. No Vertex required."""

import pytest
from fastapi.testclient import TestClient

from cinetrace.clickhouse.client import credentials_ready


@pytest.fixture
def client() -> TestClient:
    from cinetrace.web.app import app

    return TestClient(app)


def test_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Run supervisor" in response.text
    assert "Estimated waste" in response.text
    assert "After recorded dry-runs" in response.text
    assert "Waste by category" in response.text
    assert "Sentinel queries" in response.text
    assert "The three agents" in response.text
    assert "kill render-farm waste" in response.text
    assert "mcp-clickhouse" in response.text
    assert "farm-spark" in response.text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "Show full" in js.text
    assert "timeline-full" in js.text
    assert "TIMELINE_AGENTS" in js.text


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "run_public" in payload
    assert "clickhouse" in payload


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_jobs(client: TestClient) -> None:
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) >= 50
    assert {job["job_id"] for job in jobs} >= {
        "job-fail-lic",
        "job-zombie",
        "job-fail-oom",
        "job-retry-loop",
        "job-idle-queue",
        "job-overrun",
    }


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_proposals(client: TestClient) -> None:
    response = client.get("/api/proposals")
    assert response.status_code == 200
    assert "proposals" in response.json()


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_impact(client: TestClient) -> None:
    response = client.get("/api/impact")
    assert response.status_code == 200
    payload = response.json()
    assert payload["before_usd"] > 0
    assert payload["after_usd"] <= payload["before_usd"]
    assert payload["waste_job_count"] >= 5
    job_ids = {row["job_id"] for row in payload["jobs"]}
    assert {"job-fail-lic", "job-zombie", "job-overrun", "job-idle-queue"} <= job_ids
    assert payload["assumptions"]["gpu_hour_usd"] == 3.5


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_waste(client: TestClient) -> None:
    response = client.get("/api/waste")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "clickhouse"
    assert "run_query" in payload["mcp_tools"]
    assert list(payload["summary"]) == [
        "failed",
        "retry_loops",
        "idle_queue",
        "zombies",
        "overruns",
    ]
    assert payload["summary"]["failed"] == 3
    assert payload["summary"]["retry_loops"] == 3
    assert payload["summary"]["idle_queue"] == 1
    assert payload["summary"]["zombies"] == 1
    assert payload["summary"]["overruns"] == 1
    assert len(payload["queries"]) == 5
    failed = payload["queries"][0]
    assert failed["id"] == "failed"
    assert "status = 'failed'" in failed["sql"]
    assert {row["job_id"] for row in failed["rows"]} == {
        "job-fail-oom",
        "job-fail-lic",
        "job-retry-loop",
    }


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_rollup(client: TestClient) -> None:
    response = client.get("/api/rollup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "clickhouse"
    assert "toDate" in payload["sql"]
    assert payload["days"]
    assert {"day", "jobs", "cpu_hours", "gpu_hours"} <= set(payload["days"][0])


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_query_log(client: TestClient) -> None:
    response = client.get("/api/query-log")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "system.query_log"
    assert "query_log" in payload["sql"]
    assert "rows" in payload
