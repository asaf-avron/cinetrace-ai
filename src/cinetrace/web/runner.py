"""In-process ADK run of the Studio Orchestrator."""

from __future__ import annotations

import json
import re
from typing import Any

from google.adk.apps.app import App
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from cinetrace.agent import root_agent
from cinetrace.clickhouse.proposals import list_proposals, record_outcome
from cinetrace.env import load_env

DEFAULT_PROMPT = (
    "Find wasteful render jobs in ClickHouse via MCP. Do not invent rows. "
    "Propose dry-run remediations for the top 3 by policy "
    "(license/OOM and retry loops first, then zombies, idle queue, overruns)."
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

_JOB_ID = re.compile(r"\bjob-[a-z0-9-]+\b", re.IGNORECASE)
_MCP_TOOLS = {"run_query", "list_tables", "list_databases"}
MCP_PREVIEW_CHARS = 2000


def _step_for(author: str) -> dict | None:
    key = (author or "").strip().lower()
    return AGENT_STEPS.get(key)


def _job_ids_in(text: str) -> list[str]:
    seen: list[str] = []
    for match in _JOB_ID.findall(text or ""):
        job_id = match.lower()
        if job_id not in seen:
            seen.append(job_id)
    return seen


def _canonical_mcp_tool(name: str | None) -> str | None:
    raw = (name or "").strip().lower().replace("-", "_")
    if not raw:
        return None
    for tool in _MCP_TOOLS:
        if raw == tool or raw.endswith("." + tool) or raw.endswith("_" + tool):
            return tool
    return None


def _truncate_text(value: str, limit: int = MCP_PREVIEW_CHARS) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + f"…[+{len(value) - limit} chars]", True


def _preview_payload(value: Any, limit: int = MCP_PREVIEW_CHARS) -> tuple[Any, bool]:
    if value is None:
        return None, False
    if isinstance(value, str):
        return _truncate_text(value, limit)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        truncated = False
        for key, item in value.items():
            preview, item_trunc = _preview_payload(item, limit)
            out[str(key)] = preview
            truncated = truncated or item_trunc
        return out, truncated
    if isinstance(value, (list, tuple)):
        try:
            raw = json.dumps(value, default=str)
        except TypeError:
            raw = str(value)
        if len(raw) <= limit:
            return list(value), False
        text, _ = _truncate_text(raw, limit)
        return text, True
    return value, False


def _as_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw:
        try:
            return dict(raw)
        except (TypeError, ValueError):
            return {"value": raw}
    return {}


def _query_from_args(args: dict[str, Any]) -> str:
    query = args.get("query") or args.get("sql") or ""
    if isinstance(query, str):
        return query.strip()
    return str(query)


def _mcp_record(author: str, tool: str, args: dict[str, Any], call_id: str | None) -> dict[str, Any]:
    step = _step_for(author)
    preview_args, truncated = _preview_payload(args)
    if not isinstance(preview_args, dict):
        preview_args = {"query": preview_args}
    return {
        "tool": tool,
        "args": preview_args,
        "query": _query_from_args(preview_args if isinstance(preview_args, dict) else args),
        "author": author,
        "agent": (step or {}).get("id") or "",
        "label": (step or {}).get("label") or author,
        "mcp_server": "mcp-clickhouse",
        "id": call_id,
        "truncated": truncated,
    }


def extract_mcp_calls(events: list[Any]) -> list[dict[str, Any]]:
    """Pull mcp-clickhouse invocations out of ADK runner events.

    Captures ``function_call`` args (``query`` for ``run_query``) and pairs
    matching ``function_response`` payloads, truncating large results.
    """
    ordered: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        author = getattr(event, "author", "") or ""
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc:
                tool = _canonical_mcp_tool(getattr(fc, "name", None))
                if tool:
                    call_id = getattr(fc, "id", None)
                    record = _mcp_record(author, tool, _as_args(getattr(fc, "args", None)), call_id)
                    ordered.append(record)
                    if call_id:
                        by_id[str(call_id)] = record
            fr = getattr(part, "function_response", None)
            if fr:
                tool = _canonical_mcp_tool(getattr(fr, "name", None))
                if not tool:
                    continue
                call_id = getattr(fr, "id", None)
                result, trunc = _preview_payload(getattr(fr, "response", None))
                record = by_id.get(str(call_id)) if call_id else None
                if record is None:
                    record = _mcp_record(author, tool, {}, call_id)
                    ordered.append(record)
                    if call_id:
                        by_id[str(call_id)] = record
                record["result"] = result
                record["truncated"] = bool(record.get("truncated")) or trunc
    return ordered


def _mcp_calls_from_event(event) -> list[dict]:
    """Tool calls that went through mcp-clickhouse (select-only run_query)."""
    return extract_mcp_calls([event])


async def run_supervisor(message: str | None = None) -> dict:
    load_env()
    before = {(p["job_id"], p["action"], str(p["created_at"])) for p in list_proposals()}
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
    query = DEFAULT_PROMPT
    content = types.Content(role="user", parts=[types.Part(text=query)])
    lines: list[str] = []
    timeline: list[dict] = []
    highlighted: list[str] = []
    adk_events: list = []
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=content,
    ):
        adk_events.append(event)
        if not event.content or not event.content.parts:
            continue
        text = "".join(part.text or "" for part in event.content.parts).strip()
        if not text:
            continue
        author = event.author or ""
        lines.append(f"[{author}]: {text}")
        step = _step_for(author)
        if step:
            jobs = _job_ids_in(text)
            for job_id in jobs:
                if job_id not in highlighted:
                    highlighted.append(job_id)
            timeline.append(
                {
                    "agent": step["id"],
                    "label": step["label"],
                    "role": step["role"],
                    "author": author,
                    "text": text,
                    "job_ids": jobs,
                }
            )

    mcp_calls = extract_mcp_calls(adk_events)
    summary = "\n\n".join(lines)
    recorded: list[dict] = []
    for proposal in list_proposals():
        key = (proposal["job_id"], proposal["action"], str(proposal["created_at"]))
        if key in before:
            continue
        if proposal.get("status") != "proposed":
            continue
        recorded.append(
            record_outcome(
                proposal["job_id"],
                proposal["action"],
                f"Supervisor recorded dry-run: {proposal['action']} on {proposal['job_id']}",
            )
        )
        job_id = str(proposal["job_id"]).lower()
        if job_id not in highlighted:
            highlighted.append(job_id)
    if recorded and not any(step["agent"] == "action" for step in timeline):
        jobs = [str(row["job_id"]) for row in recorded]
        timeline.append(
            {
                "agent": "action",
                "label": AGENT_STEPS["action_agent"]["label"],
                "role": AGENT_STEPS["action_agent"]["role"],
                "author": "action_agent",
                "text": "Recorded dry-run remediations for "
                + ", ".join(jobs)
                + ".",
                "job_ids": jobs,
            }
        )
    return {
        "summary": summary,
        "recorded": recorded,
        "timeline": timeline,
        "highlighted_job_ids": highlighted,
        "mcp_calls": mcp_calls,
        "mcp_server": "mcp-clickhouse",
    }
