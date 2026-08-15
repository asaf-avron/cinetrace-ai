"""FastAPI supervisor: ClickHouse tables + gated Run supervisor."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cinetrace.clickhouse.client import credentials_ready
from cinetrace.clickhouse.impact import fetch_impact
from cinetrace.clickhouse.proposals import list_jobs, list_proposals
from cinetrace.env import load_env
from cinetrace.web.guard import HourlyLimiter, extract_token, run_enabled, token_ok
from cinetrace.web.runner import DEFAULT_PROMPT, run_supervisor

load_env()

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = WEB_DIR / "templates"
STATIC = WEB_DIR / "static"

app = FastAPI(title="CineTrace AI", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.state.limiter = HourlyLimiter()


class RunRequest(BaseModel):
    message: str | None = Field(default=None)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(TEMPLATES / "index.html")


@app.get("/api/health")
def api_health() -> dict:
    return {"ok": True, "clickhouse": credentials_ready()}


@app.get("/api/jobs")
def api_jobs() -> dict:
    if not credentials_ready():
        raise HTTPException(503, "ClickHouse credentials are not set")
    return {"jobs": _jsonable(list_jobs())}


@app.get("/api/proposals")
def api_proposals() -> dict:
    if not credentials_ready():
        raise HTTPException(503, "ClickHouse credentials are not set")
    return {"proposals": _jsonable(list_proposals())}


@app.get("/api/impact")
def api_impact() -> dict:
    if not credentials_ready():
        raise HTTPException(503, "ClickHouse credentials are not set")
    return _jsonable_value(fetch_impact())


@app.post("/api/run")
async def api_run(
    body: RunRequest | None = None,
    authorization: Annotated[str | None, Header()] = None,
    x_run_token: Annotated[str | None, Header()] = None,
) -> dict:
    if not run_enabled():
        raise HTTPException(403, "Supervisor run is disabled")
    if not token_ok(extract_token(authorization, x_run_token)):
        raise HTTPException(401, "Demo token required")
    if not app.state.limiter.allow():
        raise HTTPException(429, "Run limit reached (5 per hour)")
    if not credentials_ready():
        raise HTTPException(503, "ClickHouse credentials are not set")
    _ = body
    result = await run_supervisor(DEFAULT_PROMPT)
    return {
        "summary": result["summary"],
        "recorded": result["recorded"],
        "jobs": _jsonable(list_jobs()),
        "proposals": _jsonable(list_proposals()),
        "impact": _jsonable_value(fetch_impact()),
    }


def _jsonable_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable_value(item) for item in value]
    return value


def _jsonable(rows: list[dict]) -> list[dict]:
    return [_jsonable_value(row) for row in rows]
