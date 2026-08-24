"""Streaming /api/run. Mocks the supervisor so tests never call Gemini."""

import json

import pytest
from fastapi.testclient import TestClient

from cinetrace.web.guard import HourlyLimiter

COMPLETE_KEYS = {
    "run_id",
    "engine",
    "engine_fallback_reason",
    "summary",
    "timeline",
    "highlighted_job_ids",
    "mcp_calls",
    "mcp_server",
    "sentinel_passes",
    "cost",
    "jobs",
    "proposals",
    "impact",
    "waste",
    "shots",
    "root_cause",
    "rollup",
    "query_log",
}

RESULT = {
    "run_id": "abc123def456",
    "engine": "in_process_adk",
    "engine_fallback_reason": "",
    "summary": "ok",
    "timeline": [
        {
            "agent": "sentinel",
            "label": "Diagnostic Sentinel",
            "role": "detect",
            "author": "diagnostic_sentinel",
            "text": "Found job-fail-lic",
            "job_ids": ["job-fail-lic"],
            "pass": 1,
        }
    ],
    "highlighted_job_ids": ["job-fail-lic"],
    "mcp_calls": [
        {
            "agent": "sentinel",
            "label": "Diagnostic Sentinel",
            "author": "diagnostic_sentinel",
            "tool": "run_query",
            "mcp_server": "mcp-clickhouse",
            "query": "SELECT 1",
        }
    ],
    "mcp_server": "mcp-clickhouse",
    "sentinel_passes": 1,
    "cost": {
        "input_tokens": 10,
        "output_tokens": 2,
        "model_calls": 1,
        "usd": 0.00001,
        "elapsed_s": 0.1,
        "model": "gemini-2.5-flash",
        "note": "test",
    },
    "proposals": [],
}


async def _fake_stream(_message=None):
    yield {"type": "engine", "engine": "in_process_adk", "reason": ""}
    yield {
        "type": "stage",
        "agent": "sentinel",
        "label": "Diagnostic Sentinel",
        "role": "detect",
        "pass": 1,
    }
    yield {
        "type": "query",
        "agent": "sentinel",
        "label": "Diagnostic Sentinel",
        "author": "diagnostic_sentinel",
        "tool": "run_query",
        "mcp_server": "mcp-clickhouse",
        "query": "SELECT 1",
    }
    yield {
        "type": "step",
        "agent": "sentinel",
        "label": "Diagnostic Sentinel",
        "role": "detect",
        "author": "diagnostic_sentinel",
        "text": "Found job-fail-lic",
        "job_ids": ["job-fail-lic"],
        "pass": 1,
    }
    yield {
        "type": "cost",
        "input_tokens": 10,
        "output_tokens": 2,
        "model_calls": 1,
        "usd": 0.00001,
        "elapsed_s": 0.1,
    }
    yield {"type": "result", **RESULT}


def _stub_fetches(webapp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webapp, "stream_supervisor", _fake_stream)
    monkeypatch.setattr(webapp, "list_jobs", lambda: [])
    monkeypatch.setattr(webapp, "list_proposals", lambda: [])
    monkeypatch.setattr(webapp, "fetch_impact", lambda: {"before_usd": 1})
    monkeypatch.setattr(webapp, "fetch_waste_showcase", lambda: {"summary": {}})
    monkeypatch.setattr(webapp, "fetch_farm_rollup", lambda: {"days": []})
    monkeypatch.setattr(webapp, "fetch_query_log", lambda: {"ok": False, "rows": []})
    monkeypatch.setattr(webapp, "fetch_shots_at_risk", lambda: {"shots": []})
    monkeypatch.setattr(webapp, "fetch_root_cause", lambda: {"rows": []})
    monkeypatch.setattr(webapp, "credentials_ready", lambda: True)


def _parse_sse(text: str) -> list[dict]:
    frames = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                frames.append(json.loads(line[6:]))
    return frames


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "test-token-value")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "true")
    monkeypatch.setenv("SUPERVISOR_RUN_LIMIT", "5")
    monkeypatch.setenv("SUPERVISOR_RUN_PUBLIC", "false")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=5)
    webapp.app.state.last_run = None
    _stub_fetches(webapp, monkeypatch)
    return TestClient(webapp.app)


def test_stream_emits_frames_then_complete(client: TestClient) -> None:
    response = client.post(
        "/api/run",
        json={},
        headers={"X-Run-Token": "test-token-value", "Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    frames = _parse_sse(response.text)
    assert [f["type"] for f in frames] == [
        "engine",
        "stage",
        "query",
        "step",
        "cost",
        "complete",
    ]
    complete = frames[-1]
    assert COMPLETE_KEYS <= set(complete)
    assert complete["summary"] == "ok"
    assert complete["mcp_server"] == "mcp-clickhouse"
    assert complete["run_id"] == "abc123def456"

    cached = client.get("/api/last-run").json()
    assert cached["available"] is True
    assert cached["run_id"] == "abc123def456"
    assert cached["timeline"][0]["agent"] == "sentinel"


def test_stream_without_token_is_401(client: TestClient) -> None:
    response = client.post(
        "/api/run", json={}, headers={"Accept": "text/event-stream"}
    )
    assert response.status_code == 401


def test_stream_disabled_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "test-token-value")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "false")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=5)
    client = TestClient(webapp.app)
    response = client.post(
        "/api/run",
        json={},
        headers={"X-Run-Token": "test-token-value", "Accept": "text/event-stream"},
    )
    assert response.status_code == 403


def test_stream_without_clickhouse_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_RUN_TOKEN", "test-token-value")
    monkeypatch.setenv("SUPERVISOR_RUN_ENABLED", "true")
    monkeypatch.setenv("SUPERVISOR_RUN_PUBLIC", "false")
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=5)
    monkeypatch.setattr(webapp, "credentials_ready", lambda: False)
    client = TestClient(webapp.app)
    response = client.post(
        "/api/run",
        json={},
        headers={"X-Run-Token": "test-token-value", "Accept": "text/event-stream"},
    )
    assert response.status_code == 503


def test_stream_rate_limited(client: TestClient) -> None:
    from cinetrace.web import app as webapp

    webapp.app.state.limiter = HourlyLimiter(max_runs=2)
    headers = {"X-Run-Token": "test-token-value", "Accept": "text/event-stream"}
    assert client.post("/api/run", json={}, headers=headers).status_code == 200
    assert client.post("/api/run", json={}, headers=headers).status_code == 200
    assert client.post("/api/run", json={}, headers=headers).status_code == 429
