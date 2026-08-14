def test_root_agent_has_exactly_two_sub_agents() -> None:
    from cinetrace.agent import root_agent

    names = [agent.name for agent in root_agent.sub_agents]
    assert root_agent.name == "studio_orchestrator"
    assert names == ["diagnostic_sentinel", "action_agent"]
