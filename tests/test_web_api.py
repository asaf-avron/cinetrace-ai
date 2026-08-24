"""Supervisor GET APIs. Skip if ClickHouse creds are missing. No Vertex required."""

import pytest
from fastapi.testclient import TestClient

from cinetrace.clickhouse.client import credentials_ready

needs_clickhouse = pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)


@pytest.fixture
def client() -> TestClient:
    from cinetrace.web.app import app

    return TestClient(app)


def test_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    page = response.text
    for marker in (
        "Run supervisor",
        "Dailies at risk",
        "protect the dailies",
        "Waste by category",
        "The three agents",
        "Root cause",
        "Have we seen this before?",
        "mcp-clickhouse",
        "farm-spark",
        "shot-cards",
        "page-nav",
        "Back to top",
        "run-toolbar",
        "live-jobs",
    ):
        assert marker in page, f"missing {marker!r}"


def test_health(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert {"run_public", "clickhouse", "run_enabled", "live"} <= set(payload)


@needs_clickhouse
def test_api_jobs_is_bounded_and_leads_with_waste(client: TestClient) -> None:
    jobs = client.get("/api/jobs").json()["jobs"]
    assert 0 < len(jobs) <= 60, "198k rows must never be serialised to the page"
    assert jobs[0]["is_open"], "open waste sorts first"
    assert "waste_usd" in jobs[0]


@needs_clickhouse
def test_api_impact_separates_open_from_history(client: TestClient) -> None:
    payload = client.get("/api/impact").json()
    assert payload["open"]["usd"] >= 0
    assert payload["historical"]["usd"] > payload["open"]["usd"]
    assert payload["historical"]["total_jobs"] > 100_000
    assert payload["assumptions"]["gpu_hour_usd"] == 3.5


@needs_clickhouse
def test_api_waste_reports_query_cost(client: TestClient) -> None:
    payload = client.get("/api/waste").json()
    assert payload["source"] == "clickhouse"
    assert "run_query" in payload["mcp_tools"]
    assert list(payload["summary"]) == [
        "failed",
        "retry_loops",
        "idle_queue",
        "zombies",
        "overruns",
    ]
    assert all(q["stats"]["rows_read"] > 0 for q in payload["queries"])


@needs_clickhouse
def test_api_shots_projects_delivery_risk(client: TestClient) -> None:
    payload = client.get("/api/shots").json()
    assert payload["tracked_count"] > 0
    assert payload["at_risk_count"] <= payload["tracked_count"]
    assert payload["recoverable_count"] <= payload["at_risk_count"]
    assert "review_at" in payload["columns"]


@needs_clickhouse
def test_api_root_cause_exposes_the_asof_sql(client: TestClient) -> None:
    payload = client.get("/api/root-cause").json()
    assert "ASOF LEFT JOIN" in payload["asof"]["sql"]
    assert "lagInFrame" in payload["storms"]["sql"]


@needs_clickhouse
def test_api_scale_shows_the_farm_is_large(client: TestClient) -> None:
    payload = client.get("/api/scale").json()
    assert payload["samples"] > 100_000_000
    assert payload["hosts"] > 0


@needs_clickhouse
def test_api_similar_matches_on_meaning(client: TestClient) -> None:
    response = client.get(
        "/api/similar", params={"q": "the card ran out of memory mid frame"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"], "the incident archive should return neighbours"
    assert payload["matches"][0]["error_class"] == "oom"
    assert payload["matches"][0]["similarity"] > 0.5


@needs_clickhouse
def test_api_rollup(client: TestClient) -> None:
    payload = client.get("/api/rollup").json()
    assert payload["source"] == "clickhouse"
    assert payload["days"]
    assert {"day", "jobs", "cpu_hours", "gpu_hours"} <= set(payload["days"][0])
    assert "farm_minute" in payload["timeline"]["sql"]


@needs_clickhouse
def test_api_query_log(client: TestClient) -> None:
    payload = client.get("/api/query-log").json()
    assert payload["source"] == "system.query_log"
    assert "rows" in payload


def test_decide_rejects_unknown_action(client: TestClient) -> None:
    response = client.post(
        "/api/proposals/decide",
        json={"job_id": "job-zombie", "action": "delete_everything", "decision": "approved"},
    )
    assert response.status_code == 400


def test_decide_rejects_unknown_decision(client: TestClient) -> None:
    response = client.post(
        "/api/proposals/decide",
        json={"job_id": "job-zombie", "action": "kill_zombie", "decision": "maybe"},
    )
    assert response.status_code == 400
