"""The farm keeps moving whether or not anyone clicked Run.

A dashboard that only changes when you press a button reads as a demo. This
module keeps two clocks going:

- **tick** (every ``LIVE_TICK_SECONDS``) writes one telemetry sample per
  in-flight job and advances delivery. Hundreds of rows, and it is what keeps
  the farm_minute materialized view producing current minutes.
- **refresh** (every ``LIVE_REFRESH_SECONDS``) rebuilds the last 48 hours of
  render_jobs against a fresh now(), so running jobs do not silently age into
  zombies over a multi-week judging window.

Subscribers get a compact snapshot over SSE after each tick. Everything is
best-effort: if ClickHouse is asleep or credentials are missing, the loop logs,
backs off, and the page still works on its normal fetches.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any

from cinetrace.clickhouse.client import credentials_ready, get_client
from cinetrace.env import load_env

log = logging.getLogger("cinetrace.live")

DEFAULT_TICK_SECONDS = 30
DEFAULT_REFRESH_SECONDS = 900
ERROR_BACKOFF_SECONDS = 60
MAX_SUBSCRIBERS = 40

SNAPSHOT = """
SELECT
    (SELECT count() FROM frame_samples) AS samples,
    (SELECT count() FROM render_jobs) AS jobs,
    (SELECT countIf(status = 'running') FROM render_jobs) AS running,
    (SELECT countIf(status = 'queued') FROM render_jobs) AS queued,
    (SELECT count() FROM job_waste WHERE is_open) AS open_waste_jobs,
    (SELECT round(sum(waste_cpu_hours * 0.12 + waste_gpu_hours * 3.50), 2)
       FROM job_waste WHERE is_open) AS open_waste_usd,
    (SELECT uniqMerge(active_hosts) FROM farm_minute
      WHERE minute >= now('UTC') - INTERVAL 5 MINUTE) AS hosts_active,
    (SELECT round(arrayElement(
        quantilesTDigestMerge(0.5)(gpu_util_q), 1), 1)
       FROM farm_minute WHERE minute >= now('UTC') - INTERVAL 5 MINUTE) AS gpu_p50
"""


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def ticker_enabled() -> bool:
    load_env()
    flag = os.getenv("LIVE_TICKER_ENABLED", "true").strip().lower()
    return flag in {"1", "true", "yes", "on"} and credentials_ready()


class LiveFarm:
    """Owns the background loop and the set of SSE subscribers."""

    def __init__(self) -> None:
        self.tick_seconds = _int_env("LIVE_TICK_SECONDS", DEFAULT_TICK_SECONDS)
        self.refresh_seconds = _int_env(
            "LIVE_REFRESH_SECONDS", DEFAULT_REFRESH_SECONDS
        )
        self.reset_hour = _int_env("DEMO_RESET_HOUR_UTC", -1)
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._last_refresh = 0.0
        self._last_reset_day: str = ""
        self.last_snapshot: dict[str, Any] = {}
        self.ticks = 0
        self.errors = 0

    # -- subscriptions ----------------------------------------------------

    def subscribe(self) -> asyncio.Queue | None:
        if len(self._subscribers) >= MAX_SUBSCRIBERS:
            return None
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _publish(self, payload: dict) -> None:
        message = json.dumps(payload, default=str)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A slow browser must not hold up the farm.
                pass

    # -- the loop ---------------------------------------------------------

    def _maybe_reset(self, client: Any) -> bool:
        """Clear proposals once a day so the page greets a judge with an unsolved farm.

        Daily rather than hourly on purpose: someone who approves a proposal
        should see the dollar figure stay moved for the rest of their session.
        """
        if self.reset_hour < 0:
            return False
        now = time.gmtime()
        today = time.strftime("%Y-%m-%d", now)
        if now.tm_hour != self.reset_hour or self._last_reset_day == today:
            return False
        client.command("TRUNCATE TABLE IF EXISTS remediation_proposals")
        client.command("TRUNCATE TABLE IF EXISTS proposal_decisions")
        self._last_reset_day = today
        log.info("daily demo reset: cleared proposals and decisions")
        return True

    def _tick_sync(self) -> dict:
        from cinetrace.clickhouse.generate import refresh_live_cohort, tick

        client = get_client()
        try:
            now = time.time()
            refreshed = False
            if now - self._last_refresh >= self.refresh_seconds:
                refresh_live_cohort(client)
                self._last_refresh = now
                refreshed = True
            was_reset = self._maybe_reset(client)
            tick(client)
            result = client.query(SNAPSHOT)
            snapshot = dict(zip(result.column_names, result.result_rows[0]))
            snapshot["cohort_refreshed"] = refreshed
            snapshot["demo_reset"] = was_reset
            return snapshot
        finally:
            client.close()

    async def _loop(self) -> None:
        while True:
            try:
                snapshot = await asyncio.to_thread(self._tick_sync)
                self.ticks += 1
                snapshot["tick"] = self.ticks
                snapshot["at"] = time.time()
                self.last_snapshot = snapshot
                self._publish(snapshot)
                delay = self.tick_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a sleeping cluster is normal
                self.errors += 1
                log.warning("live tick failed (%s): %s", type(exc).__name__, exc)
                delay = ERROR_BACKOFF_SECONDS
            await asyncio.sleep(delay)

    async def start(self) -> None:
        if self._task is not None or not ticker_enabled():
            return
        # Refresh on the first tick so a container that has been down for days
        # does not serve a stale live cohort.
        self._last_refresh = 0.0
        self._task = asyncio.create_task(self._loop(), name="cinetrace-live-farm")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def status(self) -> dict:
        return {
            "enabled": self._task is not None,
            "tick_seconds": self.tick_seconds,
            "refresh_seconds": self.refresh_seconds,
            "reset_hour_utc": self.reset_hour,
            "ticks": self.ticks,
            "errors": self.errors,
            "subscribers": len(self._subscribers),
            "last_snapshot": self.last_snapshot,
        }


live_farm = LiveFarm()
