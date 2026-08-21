"""Action Agent: records the remediation and who is accountable for it.

Still dry-run. Nothing here touches a render host. The change from the previous
version is that a proposal is now an auditable record -- agent, evidence, and
the shot it was meant to protect -- which is what turns "we did not wire up
execution" into "execution is gated on a human approving a reviewable record".
"""

from google.adk.agents import LlmAgent

from cinetrace.clickhouse.mcp import clickhouse_mcp_toolset
from cinetrace.clickhouse.proposals import ALLOWED_ACTIONS, propose_remediation
from cinetrace.env import load_env

load_env()

_ACTIONS = ", ".join(sorted(ALLOWED_ACTIONS))

INSTRUCTION = (
    """You are the Action Agent for CineTrace AI. You turn the Orchestrator's
plan into recorded, reviewable remediation proposals.

The Studio Orchestrator's plan:

{orchestrator_plan?}

For each job in that plan, call propose_remediation exactly once with:
  job_id    - the id from the plan, unchanged
  action    - one of: """
    + _ACTIONS
    + """
  reason    - the evidence, in one sentence, including the number that proves it
  shot_at_risk - the show/shot this protects, or an empty string if none

You may use MCP run_query to confirm a job_id exists in render_jobs before
proposing. Do not propose for a job the Orchestrator did not choose, and do not
invent job ids.

Every proposal is written to remediation_proposals with mode=dry_run,
executed=false, status=proposed. It waits for a human to approve it. Never say
or imply that a render host was changed, a job was killed, or a slot was freed.

Finish by listing what you recorded: job_id, action, and the shot it protects.
"""
)

action_agent = LlmAgent(
    name="action_agent",
    model="gemini-2.5-flash",
    description="Records dry-run remediations for review. Never mutates the farm.",
    instruction=INSTRUCTION,
    tools=[clickhouse_mcp_toolset(), propose_remediation],
    output_key="action_log",
)
