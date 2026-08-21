from cinetrace.clickhouse.apply import _statements
from cinetrace.web.runner import (
    AGENT_STEPS,
    TIMELINE_AGENTS,
    TIMELINE_SUMMARY_MAX_CHARS,
    _job_ids_in,
    _mcp_calls_from_event,
    _step_for,
    _timeline_entry,
    truncate_timeline_text,
)


def test_job_ids_extracted_from_agent_text() -> None:
    assert _job_ids_in("Found Job-fail-lic and job-zombie.") == [
        "job-fail-lic",
        "job-zombie",
    ]


def test_step_maps_only_the_three_agents() -> None:
    assert _step_for("diagnostic_sentinel")["id"] == "sentinel"
    assert _step_for("studio_orchestrator")["id"] == "orchestrator"
    assert _step_for("action_agent")["id"] == "action"
    assert _step_for("user") is None
    assert {step["id"] for step in AGENT_STEPS.values()} == TIMELINE_AGENTS


def test_apply_strips_sql_comments() -> None:
    sql = "-- comment\nTRUNCATE TABLE IF EXISTS render_jobs;\n-- more\nINSERT INTO t VALUES (1);"
    assert _statements(sql) == [
        "TRUNCATE TABLE IF EXISTS render_jobs",
        "INSERT INTO t VALUES (1)",
    ]


def test_mcp_calls_from_run_query_part() -> None:
    class FC:
        name = "run_query"
        args = {"query": "SELECT job_id FROM render_jobs WHERE status = 'failed'"}

    class Part:
        function_call = FC()
        text = None

    class Content:
        parts = [Part()]

    class Event:
        author = "diagnostic_sentinel"
        content = Content()

    calls = _mcp_calls_from_event(Event())
    assert calls[0]["tool"] == "run_query"
    assert calls[0]["mcp_server"] == "mcp-clickhouse"
    assert "status = 'failed'" in calls[0]["query"]
    assert calls[0]["agent"] == "sentinel"


def test_truncate_keeps_short_copy() -> None:
    text = "Found job-fail-oom and job-fail-lic."
    summary, truncated = truncate_timeline_text(text)
    assert truncated is False
    assert summary == text
    assert truncate_timeline_text("") == ("", False)
    assert truncate_timeline_text(None) == ("", False)


def test_truncate_caps_line_count() -> None:
    lines = [
        "Diagnostic Sentinel found failed license jobs.",
        "job-fail-lic is waiting on a seat.",
        "job-fail-oom ran out of GPU memory.",
        "job-retry-loop is spinning.",
        "job-idle-queue sat too long.",
        "job-zombie never exited.",
        "job-overrun blew the frame budget.",
    ]
    text = "\n".join(lines)
    summary, truncated = truncate_timeline_text(text)
    assert truncated is True
    assert summary.endswith("…")
    assert summary.count("\n") <= 2
    assert "job-overrun" not in summary
    assert len(summary) <= TIMELINE_SUMMARY_MAX_CHARS


def test_truncate_caps_character_count() -> None:
    text = "Waste detected. " + ("retry loop " * 80) + "on job-retry-loop."
    summary, truncated = truncate_timeline_text(text)
    assert truncated is True
    assert len(summary) <= TIMELINE_SUMMARY_MAX_CHARS
    assert summary.endswith("…")
    assert "Waste detected" in summary


def test_timeline_entry_keeps_full_text_and_job_ids() -> None:
    text = "\n".join(
        f"Line {i}: job-fail-oom job-fail-lic job-retry-loop job-idle-queue job-zombie job-overrun."
        for i in range(8)
    )
    jobs = _job_ids_in(text)
    entry = _timeline_entry(AGENT_STEPS["diagnostic_sentinel"], "diagnostic_sentinel", text, jobs)
    assert entry["agent"] == "sentinel"
    assert entry["label"] == "Diagnostic Sentinel"
    assert entry["truncated"] is True
    assert entry["text"] == text
    assert entry["summary"] != text
    assert len(entry["summary"]) <= TIMELINE_SUMMARY_MAX_CHARS
    assert entry["job_ids"] == [
        "job-fail-oom",
        "job-fail-lic",
        "job-retry-loop",
        "job-idle-queue",
        "job-zombie",
        "job-overrun",
    ]
