"""Live MCP select. Skips until HTTPS creds are in .env."""

import pytest

from cinetrace.clickhouse.client import credentials_ready


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_mcp_run_query_counts_render_jobs() -> None:
    from cinetrace.clickhouse.mcp_smoke import count_render_jobs

    assert count_render_jobs() >= 50
