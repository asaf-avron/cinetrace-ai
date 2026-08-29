"""Studio Orchestrator: decides what to act on, and the pipeline that runs it.

The three product agents are unchanged: Diagnostic Sentinel detects, Studio
Orchestrator decides, Action Agent acts. What changed is the control flow. The
old wiring made this an LlmAgent with sub_agents and hoped the model would
transfer to each in turn; a bad sample could skip the Action Agent entirely and
still look like a successful run.

`cinetrace_supervisor` is a SequentialAgent -- ADK plumbing, not a fourth role.
It guarantees detect -> decide -> act every time, and each stage keeps its own
model reasoning. Stages hand off through session state (`output_key`).
"""

from google.adk.agents import LlmAgent, SequentialAgent

from cinetrace.agents.action_agent.agent import action_agent
from cinetrace.agents.diagnostic_sentinel.agent import sentinel_investigation
from cinetrace.agents.tools import shots_at_risk_brief
from cinetrace.clickhouse.proposals import ALLOWED_ACTIONS
from cinetrace.env import load_env

load_env()

_ACTIONS = ", ".join(sorted(ALLOWED_ACTIONS))

# Not an f-string: {sentinel_findings?} is ADK state templating, resolved at
# invocation from what the Sentinel wrote, and must survive Python untouched.
INSTRUCTION = (
    """You are the Studio Orchestrator for CineTrace AI. You decide which
wasteful render jobs are worth acting on right now. You do not detect, and you
do not execute.

The Diagnostic Sentinel just reported:

{sentinel_findings?}

Call shots_at_risk_brief before you decide anything. It is not optional: it
tells you which shots are about to miss a client review and whether freeing
stuck GPU slots would save them. Waste that threatens a review is worth more
than waste that only costs money, and you cannot know which is which without
looking.

Choose 1 to 3 job_id values, in this order of preference:
1. Zombies on a show that has a shot at risk. They hold a GPU right now and
   releasing it directly moves a deadline.
2. Idle-queue jobs on a show that has a shot at risk. Same argument, cheaper.
3. OOM, license and retry-loop failures. These recur until someone fixes the
   cause, so acting stops future waste rather than recovering past waste.
4. Overruns. Already finished, so flag only -- nothing to reclaim.

Allowed actions: """
    + _ACTIONS
    + """

Reply with a short plan. One line per job: the job_id, the action, and one
sentence of justification that quotes the Sentinel's evidence or the delivery
impact. Write the job_id exactly as the Sentinel reported it and nothing else --
"job-zombie", never "ORBIT job-zombie". The show belongs to the shot it
protects, not to the job. Name that show/shot in the form "SHOW shotid", so the
Action Agent can record it; write "none" only when the job genuinely blocks no
delivery. Then state which reviews this plan is intended to save.

Use only job_id values the Sentinel actually reported. If it found nothing
actionable, say so and pick nothing -- an empty plan is a valid answer.
"""
)

studio_orchestrator = LlmAgent(
    name="studio_orchestrator",
    model="gemini-2.5-flash",
    description="Decides which farm waste to act on, weighted by delivery risk.",
    instruction=INSTRUCTION,
    tools=[shots_at_risk_brief],
    output_key="orchestrator_plan",
)

root_agent = SequentialAgent(
    name="cinetrace_supervisor",
    description=(
        "Deterministic detect -> decide -> dry-run pipeline over the three "
        "CineTrace agents."
    ),
    sub_agents=[sentinel_investigation, studio_orchestrator, action_agent],
)
