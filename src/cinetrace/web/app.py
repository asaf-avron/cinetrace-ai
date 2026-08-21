"""FastAPI supervisor: the public product surface over ClickHouse and the agents.

Every GET here runs real SQL against the same ClickHouse service the agents
query through MCP, and reports what that query cost -- rows scanned, bytes,
milliseconds. The page is the evidence, not a description of it.

Two writes exist. `POST /api/run` spends Vertex credits and is gated and rate
limited. `POST /api/proposals/decide` records a human approving or rejecting an
agent proposal; it is append-only and cheap, but still limited so the audit
trail cannot be spammed.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cinetrace.clickhouse.client import credentials_ready
from cinetrace.clickhouse.impact import fetch_impact
from cinetrace.clickhouse.proposals import (
    ALLOWED_ACTIONS,
    DECISIONS,
    decide_proposal,
    list_jobs,
    list_proposals,
)
from cinetrace.clickhouse.queries import (
    fetch_farm_rollup,
    fetch_farm_scale,
    fetch_query_log,
    fetch_root_cause,
    fetch_shots_at_risk,
    fetch_waste_showcase,
)
from cinetrace.env import load_env
from cinetrace.web.guard import (
    HourlyLimiter,
    extract_token,
    run_enabled,
    run_public,
    token_ok,
)
from cinetrace.web.live import live_farm
from cinetrace.web.runner import DEFAULT_PROMPT, run_supervisor

load_env()

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = WEB_DIR / "templates"
STATIC = WEB_DIR / "static"

SSE_KEEPALIVE_SECONDS = 20


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await live_farm.start()
    try:
        yield
    finally:
        await live_farm.stop()


app = FastAPI(title="CineTrace AI", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.state.limiter = HourlyLimiter()
app.state.decision_limiter = HourlyLimiter(max_runs=60)
# The evidence from the most recent run, so a judge who does not want to spend
# one of the five hourly runs still sees the three-agent timeline and the SQL
# the Sentinel wrote. In memory only; a redeploy starts empty.
app.state.last_run = None


class RunRequest(BaseModel):
    message: str | None = Field(default=None)


class DecisionRequest(BaseModel):
    job_id: str
    action: str
    decision: str
    decided_by: str = Field(default="supervisor")
    note: str = Field(default="")


def _require_clickhouse() -> None:
    if not credentials_ready():
        raise HTTPException(503, "ClickHouse credentials are not set")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(TEMPLATES / "index.html")


@app.get("/api/health")
def api_health() -> dict:
    return {
        "ok": True,
        "clickhouse": credentials_ready(),
        "run_public": run_public(),
        "run_enabled": run_enabled(),
        "live": live_farm.status(),
    }


@app.get("/api/jobs")
def api_jobs() -> dict:
    _require_clickhouse()
    return {"jobs": _jsonable(list_jobs())}


@app.get("/api/proposals")
def api_proposals() -> dict:
    _require_clickhouse()
    return {"proposals": _jsonable(list_proposals())}


@app.get("/api/impact")
def api_impact() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_impact())


@app.get("/api/waste")
def api_waste() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_waste_showcase())


@app.get("/api/shots")
def api_shots() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_shots_at_risk())


@app.get("/api/root-cause")
def api_root_cause() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_root_cause())


@app.get("/api/scale")
def api_scale() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_farm_scale())


@app.get("/api/rollup")
def api_rollup() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_farm_rollup())


@app.get("/api/query-log")
def api_query_log() -> dict:
    _require_clickhouse()
    return _jsonable_value(fetch_query_log())


@app.get("/api/last-run")
def api_last_run() -> dict:
    """Evidence from the most recent supervisor run, if this instance has one."""
    if not app.state.last_run:
        return {"available": False}
    return {"available": True, **app.state.last_run}


@app.get("/api/similar")
def api_similar(q: Annotated[str, Query(min_length=4, max_length=400)]) -> dict:
    """Semantic search over past incidents. The Sentinel calls the same code path."""
    _require_clickhouse()
    from cinetrace.clickhouse.embeddings import find_similar

    return _jsonable_value(find_similar(q, limit=4))


@app.get("/api/stream")
async def api_stream() -> StreamingResponse:
    """Server-sent events: one farm snapshot per live tick."""
    queue = live_farm.subscribe()
    if queue is None:
        raise HTTPException(503, "Too many live subscribers")

    async def events():
        try:
            if live_farm.last_snapshot:
                yield f"data: {json.dumps(live_farm.last_snapshot, default=str)}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=SSE_KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {message}\n\n"
        finally:
            live_farm.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/proposals/decide")
def api_decide(body: DecisionRequest) -> dict:
    """Approve or reject an agent proposal. This is what moves the dollar figure."""
    if body.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {sorted(DECISIONS)}")
    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"action must be one of {sorted(ALLOWED_ACTIONS)}")
    _require_clickhouse()
    if not app.state.decision_limiter.allow():
        raise HTTPException(429, "Decision limit reached")
    result = decide_proposal(
        body.job_id,
        body.action,
        body.decision,
        decided_by=(body.decided_by or "supervisor")[:64],
        note=(body.note or "")[:280],
    )
    return {
        "decision": _jsonable_value(result),
        "impact": _jsonable_value(fetch_impact()),
        "proposals": _jsonable(list_proposals()),
    }


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
    _require_clickhouse()
    _ = body  # The public run always uses the fixed prompt.
    result = await run_supervisor(DEFAULT_PROMPT)
    app.state.last_run = {
        "run_id": result.get("run_id"),
        "engine": result.get("engine"),
        "engine_fallback_reason": result.get("engine_fallback_reason", ""),
        "timeline": result.get("timeline") or [],
        "highlighted_job_ids": result.get("highlighted_job_ids") or [],
        "mcp_calls": result.get("mcp_calls") or [],
        "sentinel_passes": result.get("sentinel_passes", 0),
        "cost": result.get("cost") or {},
    }
    return {
        "run_id": result.get("run_id"),
        "engine": result.get("engine"),
        "engine_fallback_reason": result.get("engine_fallback_reason", ""),
        "summary": result["summary"],
        "timeline": result.get("timeline") or [],
        "highlighted_job_ids": result.get("highlighted_job_ids") or [],
        "mcp_calls": result.get("mcp_calls") or [],
        "mcp_server": result.get("mcp_server") or "mcp-clickhouse",
        "sentinel_passes": result.get("sentinel_passes", 0),
        "cost": result.get("cost") or {},
        "jobs": _jsonable(list_jobs()),
        "proposals": _jsonable(list_proposals()),
        "impact": _jsonable_value(fetch_impact()),
        "waste": _jsonable_value(fetch_waste_showcase()),
        "shots": _jsonable_value(fetch_shots_at_risk()),
        "root_cause": _jsonable_value(fetch_root_cause()),
        "rollup": _jsonable_value(fetch_farm_rollup()),
        "query_log": _jsonable_value(fetch_query_log()),
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


DEFAULT_RUN_PROMPT = DEFAULT_PROMPT
