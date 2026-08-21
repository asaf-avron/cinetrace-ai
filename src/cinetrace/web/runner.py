"""In-process ADK run of the Studio Orchestrator."""

from __future__ import annotations

import re

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


def _part_function_call(part) -> tuple[str, dict]:
    fc = getattr(part, "function_call", None)
    if not fc:
        return "", {}
    name = (getattr(fc, "name", None) or "").strip()
    args = getattr(fc, "args", None) or {}
    if not isinstance(args, dict):
        args = dict(args) if args else {}
    return name, args


def _mcp_calls_from_event(event) -> list[dict]:
    """Tool calls that went through mcp-clickhouse (select-only run_query)."""
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    author = event.author or ""
    step = _step_for(author)
    found: list[dict] = []
    for part in parts:
        name, args = _part_function_call(part)
        short = name.rsplit(".", 1)[-1].lower() if name else ""
        query = args.get("query") or args.get("sql") or ""
        is_mcp = short in _MCP_TOOLS or "run_query" in name.lower()
        if not is_mcp and not (isinstance(query, str) and query.strip()):
            continue
        if not is_mcp:
            continue
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
    mcp_calls: list[dict] = []
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=content,
    ):
        mcp_calls.extend(_mcp_calls_from_event(event))
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
