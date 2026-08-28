"""Event folding: the runner has to read ADK objects and Agent Engine dicts alike."""

import pytest

from cinetrace.clickhouse.apply import _statements
from cinetrace.clickhouse.client import credentials_ready
from cinetrace.web.runner import (
    DEFAULT_PROMPT,
    RunCollector,
    _job_ids_in,
    _step_for,
    build_prompt,
    cost_usd,
    normalize_event,
)

needs_clickhouse = pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)


@needs_clickhouse
def test_prompt_names_the_reviews_at_risk() -> None:
    """The Sentinel ranks by hours unless the deadline is put in front of it.

    Left to find the board itself it reached for the biggest zombie, which sits
    on a show with nothing due, and the run protected nothing.
    """
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    prompt = build_prompt()
    assert prompt.startswith(DEFAULT_PROMPT)

    at_risk = [r for r in fetch_shots_at_risk()["rows"] if r.get("at_risk")]
    if not at_risk:
        assert "No shot is currently projected to miss" in prompt
        return

    for show in {str(r["show"]) for r in at_risk}:
        assert show in prompt
    assert f"{at_risk[0]['show']} {at_risk[0]['shot']}" in prompt
    assert "outranks larger waste" in prompt


def test_job_ids_extracted_from_agent_text() -> None:
    assert _job_ids_in("Found Job-fail-lic and job-zombie.") == [
        "job-fail-lic",
        "job-zombie",
    ]


def test_step_maps_only_the_three_agents() -> None:
    assert _step_for("diagnostic_sentinel")["id"] == "sentinel"
    assert _step_for("studio_orchestrator")["id"] == "orchestrator"
    assert _step_for("action_agent")["id"] == "action"
    assert _step_for("cinetrace_supervisor") is None
    assert _step_for("user") is None


def test_apply_strips_sql_comments() -> None:
    sql = "-- comment\nTRUNCATE TABLE IF EXISTS render_jobs;\n-- more\nINSERT INTO t VALUES (1);"
    assert _statements(sql) == [
        "TRUNCATE TABLE IF EXISTS render_jobs",
        "INSERT INTO t VALUES (1)",
    ]


class _FakeEvent:
    """Shape of a typed ADK event, enough for the collector."""

    def __init__(self, author, text=None, tool=None, query=None, tokens=None):
        self.author = author
        self.usage_metadata = None
        if tokens:
            self.usage_metadata = type(
                "U",
                (),
                {"prompt_token_count": tokens[0], "candidates_token_count": tokens[1]},
            )()
        part = type("P", (), {"text": text, "function_call": None})()
        if tool:
            part.function_call = type("F", (), {"name": tool, "args": {"query": query}})()
        self.content = type("C", (), {"parts": [part]})()


def test_normalize_reads_adk_objects_and_agent_engine_dicts_the_same() -> None:
    typed = normalize_event(
        _FakeEvent("diagnostic_sentinel", tool="run_query", query="SELECT 1", tokens=(10, 5))
    )
    as_dict = normalize_event(
        {
            "author": "diagnostic_sentinel",
            "content": {"parts": [{"function_call": {"name": "run_query", "args": {"query": "SELECT 1"}}}]},
            "usage_metadata": {"prompt_token_count": 10, "candidates_token_count": 5},
        }
    )
    assert typed == as_dict
    assert typed["function_calls"][0]["name"] == "run_query"
    assert typed["input_tokens"] == 10


def test_collector_captures_mcp_queries_and_attributes_them() -> None:
    collector = RunCollector()
    collector.add(
        _FakeEvent(
            "diagnostic_sentinel",
            tool="run_query",
            query="SELECT job_id FROM render_jobs WHERE status = 'failed'",
        )
    )
    call = collector.mcp_calls[0]
    assert call["tool"] == "run_query"
    assert call["mcp_server"] == "mcp-clickhouse"
    assert call["agent"] == "sentinel"
    assert "status = 'failed'" in call["query"]


def test_collector_collapses_the_semicolon_retry() -> None:
    """The model appends ';', mcp-clickhouse rejects it, the model retries. One entry."""
    collector = RunCollector()
    for query in ("SELECT 1;", "SELECT 1"):
        collector.add(_FakeEvent("diagnostic_sentinel", tool="run_query", query=query))
    assert len(collector.mcp_calls) == 1
    assert collector.mcp_calls[0]["query"] == "SELECT 1"


def test_timeline_numbers_the_sentinel_passes() -> None:
    collector = RunCollector()
    collector.add(_FakeEvent("diagnostic_sentinel", text="looking at job-zombie"))
    collector.add(_FakeEvent("diagnostic_sentinel", text="confirmed"))
    collector.add(_FakeEvent("action_agent", text="recorded"))
    assert [s["pass"] for s in collector.timeline if s["agent"] == "sentinel"] == [1, 2]
    assert collector.sentinel_passes == 2
    assert collector.highlighted == ["job-zombie"]


def test_collector_returns_query_stage_and_step_frames() -> None:
    collector = RunCollector()
    query_frames = collector.add(
        _FakeEvent("diagnostic_sentinel", tool="run_query", query="SELECT 1")
    )
    assert [f["type"] for f in query_frames] == ["query", "cost"]
    assert query_frames[0]["query"] == "SELECT 1"

    step_frames = collector.add(
        _FakeEvent("diagnostic_sentinel", text="looking at job-zombie")
    )
    assert [f["type"] for f in step_frames] == ["stage", "step", "cost"]
    assert step_frames[0]["agent"] == "sentinel"
    assert step_frames[0]["pass"] == 1
    assert step_frames[1]["job_ids"] == ["job-zombie"]


def test_cost_uses_flash_list_pricing() -> None:
    assert cost_usd(1_000_000, 0) == 0.30
    assert cost_usd(0, 1_000_000) == 2.50
    assert cost_usd(0, 0) == 0.0
