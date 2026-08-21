from cinetrace.clickhouse.apply import _statements
from cinetrace.web.runner import _job_ids_in, _step_for


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


def test_apply_strips_sql_comments() -> None:
    sql = "-- comment\nTRUNCATE TABLE IF EXISTS render_jobs;\n-- more\nINSERT INTO t VALUES (1);"
    assert _statements(sql) == [
        "TRUNCATE TABLE IF EXISTS render_jobs",
        "INSERT INTO t VALUES (1)",
    ]
