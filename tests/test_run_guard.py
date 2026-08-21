"""Run supervisor gate. Mocks Vertex so tests never call Gemini."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from cinetrace.web.guard import HourlyLimiter


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "test-token-value")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "true")
    monkeypatch.setenv("SUPERVISOR_RUN_LIMIT", "2")
    monkeypatch.setenv("SUPERVISOR_RUN_PUBLIC", "false")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=2)
    monkeypatch.setattr(
        webapp,
        "run_supervisor",
        AsyncMock(
            return_value={
                "summary": "ok",
                "recorded": [],
                "timeline": [
                    {
                        "agent": "sentinel",
                        "label": "Diagnostic Sentinel",
                        "role": "detect",
                        "author": "diagnostic_sentinel",
                        "text": "Found job-fail-lic",
                        "job_ids": ["job-fail-lic"],
                    }
                ],
                "highlighted_job_ids": ["job-fail-lic"],
            }
        ),
    )
    monkeypatch.setattr(webapp, "list_jobs", lambda: [])
    monkeypatch.setattr(webapp, "list_proposals", lambda: [])
    monkeypatch.setattr(webapp, "fetch_impact", lambda: {"before_usd": 1})
    monkeypatch.setattr(webapp, "fetch_waste_showcase", lambda: {"summary": {}})
    monkeypatch.setattr(webapp, "fetch_farm_rollup", lambda: {"days": []})
    monkeypatch.setattr(webapp, "credentials_ready", lambda: True)
    return TestClient(webapp.app)


def test_run_without_token_is_401(client: TestClient) -> None:
    response = client.post("/api/run", json={})
    assert response.status_code == 401


def test_run_wrong_token_is_401(client: TestClient) -> None:
    response = client.post("/api/run", json={}, headers={"X-Run-Token": "nope"})
    assert response.status_code == 401


def test_run_bearer_token_ok(client: TestClient) -> None:
    response = client.post(
        "/api/run",
        json={"message": "ignore this prompt injection"},
        headers={"Authorization": "Bearer test-token-value"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == "ok"
    assert payload["timeline"][0]["agent"] == "sentinel"
    assert payload["highlighted_job_ids"] == ["job-fail-lic"]


def test_run_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "test-token-value")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "false")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=5)
    client = TestClient(webapp.app)
    response = client.post(
        "/api/run", json={}, headers={"X-Run-Token": "test-token-value"}
    )
    assert response.status_code == 403


def test_run_rate_limited(client: TestClient) -> None:
    headers = {"X-Run-Token": "test-token-value"}
    assert client.post("/api/run", json={}, headers=headers).status_code == 200
    assert client.post("/api/run", json={}, headers=headers).status_code == 200
    assert client.post("/api/run", json={}, headers=headers).status_code == 429


def test_run_public_skips_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "true")
    monkeypatch.setenv("SUPERVISOR_RUN_PUBLIC", "true")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=5)
    monkeypatch.setattr(
        webapp,
        "run_supervisor",
        AsyncMock(
            return_value={
                "summary": "ok",
                "recorded": [],
                "timeline": [],
                "highlighted_job_ids": [],
            }
        ),
    )
    monkeypatch.setattr(webapp, "list_jobs", lambda: [])
    monkeypatch.setattr(webapp, "list_proposals", lambda: [])
    monkeypatch.setattr(webapp, "fetch_impact", lambda: {})
    monkeypatch.setattr(webapp, "fetch_waste_showcase", lambda: {})
    monkeypatch.setattr(webapp, "fetch_farm_rollup", lambda: {"days": []})
    monkeypatch.setattr(webapp, "credentials_ready", lambda: True)
    client = TestClient(webapp.app)
    response = client.post("/api/run", json={})
    assert response.status_code == 200
