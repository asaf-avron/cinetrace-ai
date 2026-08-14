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
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=2)
    monkeypatch.setattr(
        webapp,
        "run_supervisor",
        AsyncMock(return_value={"summary": "ok", "recorded": []}),
    )
    monkeypatch.setattr(webapp, "list_jobs", lambda: [])
    monkeypatch.setattr(webapp, "list_proposals", lambda: [])
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
    assert response.json()["summary"] == "ok"


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
