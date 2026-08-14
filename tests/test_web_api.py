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


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_jobs(client: TestClient) -> None:
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 8
    assert {job["job_id"] for job in jobs} >= {"job-fail-lic", "job-zombie"}


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_api_proposals(client: TestClient) -> None:
    response = client.get("/api/proposals")
    assert response.status_code == 200
    assert "proposals" in response.json()
