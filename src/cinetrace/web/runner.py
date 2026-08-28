"""Run the three-agent pipeline and turn ADK events into something a judge can read.

Two execution paths. When `AGENT_ENGINE_ID` is set the supervisor calls the
deployed Vertex Agent Engine, so the hosted demo exercises the managed Google
Cloud agent runtime rather than a second copy of the agents inside the web
container. If that call is unavailable -- not configured, no credentials, an API
error -- it falls back to the in-process ADK Runner over the same `root_agent`.
Same agents and same MCP either way; the fallback exists so a live demo never
dies on an IAM hiccup.

Events from the two paths differ in shape (typed ADK objects vs JSON dicts), so
both are normalised before anything reads them.

Proposals are left `pending` on purpose. The agent files a record; the dollar
figure only moves when a human approves it on the page.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from google.adk.apps.app import App
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from cinetrace.agent import root_agent
from cinetrace.clickhouse.proposals import list_proposals
from cinetrace.env import load_env

DEFAULT_PROMPT = (
    "Audit the render farm. Find the waste that is burning capacity right now, "
    "prove the root cause from telemetry, and record dry-run remediations for "
    "the jobs whose slots would most protect an upcoming dailies review."
)


def build_prompt() -> str:
    """Name the reviews at risk instead of trusting the Sentinel to go looking.

    Told only to weigh delivery risk, it ranks by hours and reaches for the
    biggest zombie, which is usually one of the fixed archetypes on a show with
    nothing due. The Orchestrator then correctly reports that the plan protects
    no review, and the product's headline claim never demonstrates itself even
    though the farm is full of waste sitting on the show that is actually late.
    Making the board an input rather than an errand is the difference between
    that happening most runs and not at all.
    """
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    try:
        rows = fetch_shots_at_risk()["rows"]
    except Exception:  # a broken board must not take the whole run with it
        return DEFAULT_PROMPT

    at_risk = [row for row in rows if row.get("at_risk")]
    if not at_risk:
        return f"{DEFAULT_PROMPT} No shot is currently projected to miss its review."

    shows = ", ".join(sorted({str(row["show"]) for row in at_risk}))
    shots = ", ".join(f"{row['show']} {row['shot']}" for row in at_risk[:8])
    return (
        f"{DEFAULT_PROMPT} Reviews at risk right now: {len(at_risk)} shots on "
        f"{shows} ({shots}). Open waste on those shows outranks larger waste "
        "anywhere else, so report at least one open job from them by job_id."
    )

AGENT_STEPS = {
    "diagnostic_sentinel": {
        "id": "sentinel",
        "label": "Diagnostic Sentinel",
        "role": "detect",
    },
    "studio_orchestrator": {
        "id": "orchestrator",
        "label": "Studio Orchestrator",
        "role": "decide",
    },
    "action_agent": {
        "id": "action",
        "label": "Action Agent",
        "role": "remediate",
    },
}

# Gemini 2.5 Flash list pricing, USD per million tokens. Used only to put the
# supervisor's own cost next to the waste it found -- a tool that kills compute
# waste should be able to say what it spends.
INPUT_USD_PER_MTOK = 0.30
OUTPUT_USD_PER_MTOK = 2.50
MODEL_NAME = "gemini-2.5-flash"

_JOB_ID = re.compile(r"\bjob-[a-z0-9-]+\b", re.IGNORECASE)
_MCP_TOOLS = {"run_query", "list_tables", "list_databases"}


def _step_for(author: str) -> dict | None:
    return AGENT_STEPS.get((author or "").strip().lower())


def _job_ids_in(text: str) -> list[str]:
    seen: list[str] = []
    for match in _JOB_ID.findall(text or ""):
        job_id = match.lower()
        if job_id not in seen:
            seen.append(job_id)
    return seen


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a typed ADK object or an Agent Engine dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def normalize_event(event: Any) -> dict:
    """Flatten one ADK or Agent Engine event into author / text / calls / usage."""
    author = _get(event, "author", "") or ""
    content = _get(event, "content") or {}
    parts = _get(content, "parts") or []

    text_chunks: list[str] = []
    calls: list[dict] = []
    for part in parts:
        chunk = _get(part, "text")
        if chunk:
            text_chunks.append(str(chunk))
        fc = _get(part, "function_call")
        if fc:
            args = _get(fc, "args") or {}
            if not isinstance(args, dict):
                args = dict(args)
            calls.append({"name": (_get(fc, "name") or "").strip(), "args": args})

    meta = _get(event, "usage_metadata") or {}
    return {
        "author": author,
        "text": "".join(text_chunks).strip(),
        "function_calls": calls,
        "input_tokens": int(_get(meta, "prompt_token_count", 0) or 0),
        "output_tokens": int(_get(meta, "candidates_token_count", 0) or 0),
        "has_usage": bool(meta),
    }


def _mcp_calls(normalized: dict) -> list[dict]:
    """Tool calls that went through mcp-clickhouse (select-only run_query)."""
    author = normalized["author"]
    step = _step_for(author)
    found: list[dict] = []
    for call in normalized["function_calls"]:
        name = call["name"]
        short = name.rsplit(".", 1)[-1].lower() if name else ""
        if short not in _MCP_TOOLS and "run_query" not in name.lower():
            continue
        query = call["args"].get("query") or call["args"].get("sql") or ""
        found.append(
            {
                "agent": (step or {}).get("id") or "orchestrator",
                "label": (step or {}).get("label") or author,
                "author": author,
                "tool": short or "run_query",
                "mcp_server": "mcp-clickhouse",
                "query": query.strip() if isinstance(query, str) else str(query),
            }
        )
    return found


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK,
        6,
    )


class RunCollector:
    """Folds the event stream into the timeline, MCP evidence, and usage totals."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.timeline: list[dict] = []
        self.highlighted: list[str] = []
        self.mcp_calls: list[dict] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.model_calls = 0
        self.sentinel_passes = 0
        self._started = time.time()
        self._last_stage: tuple[str, int | None] | None = None

    def _cost_frame(self) -> dict:
        return {
            "type": "cost",
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_calls": self.model_calls,
            "usd": cost_usd(self.input_tokens, self.output_tokens),
            "elapsed_s": round(time.time() - self._started, 1),
            "model": MODEL_NAME,
        }

    def add(self, event: Any) -> list[dict]:
        """Fold one event and return the frames it produced for the live UI."""
        frames: list[dict] = []
        normalized = normalize_event(event)
        for call in _mcp_calls(normalized):
            # Models like to end SQL with a semicolon; mcp-clickhouse rejects
            # multi-statement input, so the agent retries the identical query
            # without it. Show the successful form once rather than both.
            call["query"] = call["query"].rstrip().rstrip(";").rstrip()
            if any(
                prior["query"] == call["query"] and prior["author"] == call["author"]
                for prior in self.mcp_calls
            ):
                continue
            self.mcp_calls.append(call)
            frames.append({"type": "query", **call})
        self.input_tokens += normalized["input_tokens"]
        self.output_tokens += normalized["output_tokens"]
        if normalized["has_usage"]:
            self.model_calls += 1

        text = normalized["text"]
        if not text:
            if frames:
                frames.append(self._cost_frame())
            return frames
        author = normalized["author"]
        self.lines.append(f"[{author}]: {text}")

        step = _step_for(author)
        if not step:
            if frames:
                frames.append(self._cost_frame())
            return frames
        jobs = _job_ids_in(text)
        for job_id in jobs:
            if job_id not in self.highlighted:
                self.highlighted.append(job_id)

        entry = {
            "agent": step["id"],
            "label": step["label"],
            "role": step["role"],
            "author": author,
            "text": text,
            "job_ids": jobs,
        }
        pass_n: int | None = None
        if step["id"] == "sentinel":
            self.sentinel_passes += 1
            pass_n = self.sentinel_passes
            entry["pass"] = pass_n
        stage_key = (step["id"], pass_n)
        if stage_key != self._last_stage:
            self._last_stage = stage_key
            stage = {
                "type": "stage",
                "agent": step["id"],
                "label": step["label"],
                "role": step["role"],
            }
            if pass_n is not None:
                stage["pass"] = pass_n
            frames.append(stage)
        self.timeline.append(entry)
        frames.append({"type": "step", **entry})
        frames.append(self._cost_frame())
        return frames

    def payload(self, run_id: str, elapsed_s: float, engine: str) -> dict:
        return {
            "run_id": run_id,
            "engine": engine,
            "summary": "\n\n".join(self.lines),
            "timeline": self.timeline,
            "highlighted_job_ids": self.highlighted,
            "mcp_calls": self.mcp_calls,
            "mcp_server": "mcp-clickhouse",
            "sentinel_passes": self.sentinel_passes,
            "cost": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "model_calls": self.model_calls,
                "usd": cost_usd(self.input_tokens, self.output_tokens),
                "elapsed_s": round(elapsed_s, 1),
                "model": MODEL_NAME,
                "note": "Gemini 2.5 Flash list pricing applied to this run's tokens.",
            },
        }


async def _iter_in_process(prompt: str):
    app = App(name="cinetrace", root_agent=root_agent)
    session_service = InMemorySessionService()
    runner = Runner(
        app=app,
        session_service=session_service,
        artifact_service=InMemoryArtifactService(),
    )
    session = await session_service.create_session(
        app_name="cinetrace", user_id="supervisor"
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=content,
    ):
        yield event


async def stream_supervisor(message: str | None = None):
    """Yield engine/stage/query/step/cost frames, then a result payload.

    The public run always uses the fixed prompt. `message` is accepted so the
    endpoint signature stays the same and is ignored on purpose.
    """
    load_env()
    _ = message
    run_id = uuid.uuid4().hex[:12]
    started = time.time()

    from cinetrace.web.agent_engine import stream_agent_engine

    collector = RunCollector()
    prompt = build_prompt()
    events, error = await stream_agent_engine(prompt)
    if events:
        engine = "agent_engine"
        yield {"type": "engine", "engine": engine, "reason": ""}
        for event in events:
            for frame in collector.add(event):
                yield frame
    else:
        engine = "in_process_adk"
        yield {
            "type": "engine",
            "engine": engine,
            "reason": error or "",
        }
        async for event in _iter_in_process(prompt):
            for frame in collector.add(event):
                yield frame

    payload = collector.payload(run_id, time.time() - started, engine)
    payload["engine_fallback_reason"] = error or ""
    payload["proposals"] = list_proposals()
    yield {"type": "result", **payload}


async def run_supervisor(message: str | None = None) -> dict:
    """Buffer the streamed run into the payload the JSON endpoint already returns."""
    result: dict | None = None
    async for frame in stream_supervisor(message):
        if frame.get("type") == "result":
            result = {key: value for key, value in frame.items() if key != "type"}
    if result is None:
        raise RuntimeError("supervisor produced no result")
    return result
