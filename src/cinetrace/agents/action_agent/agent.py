from google.adk.agents import Agent

from cinetrace.clickhouse.mcp import clickhouse_mcp_toolset
from cinetrace.clickhouse.proposals import ALLOWED_ACTIONS, propose_remediation
from cinetrace.env import load_env

load_env()

_actions = ", ".join(sorted(ALLOWED_ACTIONS))

action_agent = Agent(
    name="action_agent",
    model="gemini-2.5-flash",
    description="Executes (currently dry-run) remediations for wasteful render jobs.",
    instruction=(
        "You are the Action Agent for CineTrace AI. "
        "You may query ClickHouse through MCP (run_query) to confirm a job_id in render_jobs. "
        "Call propose_remediation for each intended fix. Allowed actions: "
        f"{_actions}. "
        "propose_remediation writes a row to remediation_proposals over HTTPS and always "
        "returns executed=false / mode=dry_run. Never claim a farm change was applied."
    ),
    tools=[clickhouse_mcp_toolset(), propose_remediation],
)
