"""MCP this-run extraction from fixture ADK events. No live Vertex."""

from google.adk.events.event import Event
from google.genai import types

from cinetrace.web.runner import MCP_PREVIEW_CHARS, extract_mcp_calls


def _event(author: str, parts: list[types.Part], role: str = "model") -> Event:
    return Event(author=author, content=types.Content(role=role, parts=parts))


def test_extracts_run_query_args_from_adk_function_call() -> None:
    sql = "SELECT job_id FROM render_jobs WHERE status = 'failed'"
    part = types.Part.from_function_call(name="run_query", args={"query": sql})
    part.function_call.id = "fc-run-1"
    calls = extract_mcp_calls([_event("diagnostic_sentinel", [part])])
    assert len(calls) == 1
    assert calls[0]["tool"] == "run_query"
    assert calls[0]["args"]["query"] == sql
    assert "status = 'failed'" in calls[0]["query"]
    assert calls[0]["mcp_server"] == "mcp-clickhouse"
    assert calls[0]["agent"] == "sentinel"
    assert calls[0]["truncated"] is False


def test_pairs_function_response_and_truncates_large_result() -> None:
    call = types.Part.from_function_call(
        name="run_query",
        args={"query": "SELECT count() FROM render_jobs"},
    )
    call.function_call.id = "fc-big"
    payload = {"result": "row," * 4000}
    response = types.Part.from_function_response(name="run_query", response=payload)
    response.function_response.id = "fc-big"
    calls = extract_mcp_calls(
        [
            _event("diagnostic_sentinel", [call]),
            _event("diagnostic_sentinel", [response], role="user"),
        ]
    )
    assert len(calls) == 1
    assert calls[0]["tool"] == "run_query"
    assert calls[0]["args"]["query"] == "SELECT count() FROM render_jobs"
    assert calls[0]["truncated"] is True
    preview = calls[0]["result"]["result"]
    assert isinstance(preview, str)
    assert preview.endswith("chars]")
    assert len(preview) < len(payload["result"])
    assert len(preview) <= MCP_PREVIEW_CHARS + 40


def test_ignores_non_mcp_function_calls() -> None:
    part = types.Part.from_function_call(
        name="transfer_to_agent",
        args={"agent_name": "action_agent"},
    )
    assert extract_mcp_calls([_event("studio_orchestrator", [part])]) == []


def test_accepts_prefixed_mcp_tool_name() -> None:
    part = types.Part.from_function_call(
        name="mcp_clickhouse_run_query",
        args={"query": "SELECT 1"},
    )
    calls = extract_mcp_calls([_event("action_agent", [part])])
    assert calls[0]["tool"] == "run_query"
    assert calls[0]["agent"] == "action"
    assert calls[0]["args"]["query"] == "SELECT 1"
