from google.adk.agents import Agent

from cinetrace.agents.action_agent.agent import action_agent
from cinetrace.agents.diagnostic_sentinel.agent import diagnostic_sentinel
from cinetrace.env import load_env

load_env()

root_agent = Agent(
    name="studio_orchestrator",
    model="gemini-2.5-flash",
    description="Decides what to do next after farm-waste findings.",
    instruction=(
        "You are the Studio Orchestrator for CineTrace AI. "
        "Do not invent extra agents. Do not invent ClickHouse rows. "
        "1) Delegate investigation to diagnostic_sentinel (MCP queries only). "
        "2) Apply this priority and pick 1–3 job_id values: "
        "license/OOM failures and retry loops first, then zombies, "
        "then idle queue, then overruns. "
        "3) Delegate those jobs to action_agent for dry-run propose_remediation. "
        "4) Summarize findings and the persisted dry-run proposals. "
        "executed is always false in this foundation."
    ),
    sub_agents=[diagnostic_sentinel, action_agent],
)
