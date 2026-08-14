"""In-process ADK run of the Studio Orchestrator."""

from __future__ import annotations

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
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue
        text = "".join(part.text or "" for part in event.content.parts).strip()
        if text:
            lines.append(f"[{event.author}]: {text}")

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
    return {"summary": summary, "recorded": recorded}
