"""Live ticker startup must not block Cloud Run's listen probe."""

import asyncio
import time

from cinetrace.web.live import (
    STARTUP_REFRESH_DELAY_SECONDS,
    LiveFarm,
    ticker_enabled,
)


def test_ticker_enabled_reads_flag(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TICKER_ENABLED", "false")
    monkeypatch.setenv("CLICKHOUSE_HOST", "example.clickhouse.cloud")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "x")
    assert ticker_enabled() is False
    monkeypatch.setenv("LIVE_TICKER_ENABLED", "true")
    assert ticker_enabled() is True


def test_start_defers_cohort_refresh_past_startup_probe(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TICKER_ENABLED", "true")
    monkeypatch.setenv("CLICKHOUSE_HOST", "example.clickhouse.cloud")
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "x")
    monkeypatch.setenv("LIVE_REFRESH_SECONDS", "900")

    farm = LiveFarm()
    monkeypatch.setattr(farm, "_tick_sync", lambda: {"samples": 0})

    async def _run() -> None:
        await farm.start()
        try:
            until_refresh = farm.refresh_seconds - (
                time.time() - farm._last_refresh
            )
            assert farm._task is not None
            assert 30 <= until_refresh <= STARTUP_REFRESH_DELAY_SECONDS + 5
        finally:
            await farm.stop()

    asyncio.run(_run())
    assert farm._task is None


def test_start_is_noop_when_ticker_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_TICKER_ENABLED", "false")
    farm = LiveFarm()

    async def _run() -> None:
        await farm.start()
        assert farm._task is None
        await farm.stop()

    asyncio.run(_run())
