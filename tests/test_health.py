"""Live ClickHouse health check. Skips until HTTPS creds are in .env."""

import pytest

from cinetrace.clickhouse.client import credentials_ready, ping


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_live_select_one() -> None:
    assert ping() == 1
