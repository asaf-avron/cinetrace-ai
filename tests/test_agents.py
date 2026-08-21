"""The pipeline shape. Three product agents, run in a fixed order, no more."""

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent


def test_pipeline_is_deterministic_detect_decide_act() -> None:
    """A SequentialAgent cannot skip a stage; LLM-driven transfer could."""
    from cinetrace.agent import root_agent

    assert isinstance(root_agent, SequentialAgent)
    assert [a.name for a in root_agent.sub_agents] == [
        "sentinel_investigation",
        "studio_orchestrator",
        "action_agent",
    ]


def test_only_the_three_named_agents_reason() -> None:
    """Containers are plumbing. Every LlmAgent must be one of the documented three."""
    from cinetrace.agent import root_agent

    def llm_agents(agent):
        if isinstance(agent, LlmAgent):
            yield agent.name
        for child in getattr(agent, "sub_agents", None) or []:
            yield from llm_agents(child)

    assert sorted(llm_agents(root_agent)) == [
        "action_agent",
        "diagnostic_sentinel",
        "studio_orchestrator",
    ]


def test_sentinel_loops_so_it_can_react_to_what_it_finds() -> None:
    from cinetrace.agents.diagnostic_sentinel.agent import (
        MAX_PASSES,
        sentinel_investigation,
    )

    assert isinstance(sentinel_investigation, LoopAgent)
    assert sentinel_investigation.max_iterations == MAX_PASSES


def test_sentinel_gets_schema_and_tools_not_a_query_list() -> None:
    from cinetrace.agents.diagnostic_sentinel.agent import INSTRUCTION, diagnostic_sentinel

    tools = {getattr(t, "__name__", type(t).__name__) for t in diagnostic_sentinel.tools}
    assert "McpToolset" in tools
    assert "find_similar_failures" in tools
    assert "exit_loop" in tools

    assert "frame_samples" in INSTRUCTION and "ASOF" in INSTRUCTION
    # The old build pasted five finished queries into the prompt.
    assert "SELECT job_id, show, shot, status" not in INSTRUCTION


def test_stages_hand_off_through_session_state() -> None:
    from cinetrace.agents.action_agent.agent import INSTRUCTION as ACTION
    from cinetrace.agents.action_agent.agent import action_agent
    from cinetrace.agents.diagnostic_sentinel.agent import diagnostic_sentinel
    from cinetrace.agents.studio_orchestrator.agent import (
        INSTRUCTION as DECIDE,
    )
    from cinetrace.agents.studio_orchestrator.agent import studio_orchestrator

    assert diagnostic_sentinel.output_key == "sentinel_findings"
    assert studio_orchestrator.output_key == "orchestrator_plan"
    assert action_agent.output_key == "action_log"
    assert "{sentinel_findings?}" in DECIDE
    assert "{orchestrator_plan?}" in ACTION


def test_action_agent_cannot_claim_it_touched_the_farm() -> None:
    from cinetrace.agents.action_agent.agent import INSTRUCTION

    assert "dry_run" in INSTRUCTION
    assert "executed=false" in INSTRUCTION
    assert "Never say" in INSTRUCTION
