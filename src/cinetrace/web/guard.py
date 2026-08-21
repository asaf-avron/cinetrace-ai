"""Gate and rate-limit the Vertex-costing supervisor run."""

from __future__ import annotations

import os
import time
from hmac import compare_digest


def _flag(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def run_enabled() -> bool:
    return os.getenv("SUPERVISOR_RUN_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def run_public() -> bool:
    """Judging-week: skip the demo token, keep rate limit and enable flag."""
    return _flag("SUPERVISOR_RUN_PUBLIC")


def expected_token() -> str:
    return os.getenv("SUPERVISOR_RUN_TOKEN", "").strip()


def extract_token(authorization: str | None, x_run_token: str | None) -> str:
    if x_run_token and x_run_token.strip():
        return x_run_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def token_ok(provided: str) -> bool:
    if run_public():
        return True
    expected = expected_token()
    if not expected or not provided or len(provided) != len(expected):
        return False
    return compare_digest(provided, expected)


class HourlyLimiter:
    def __init__(self, max_runs: int | None = None, window_s: float = 3600) -> None:
        self.max_runs = max_runs if max_runs is not None else int(
            os.getenv("SUPERVISOR_RUN_LIMIT", "5")
        )
        self.window_s = window_s
        self._times: list[float] = []

    def reset(self) -> None:
        self._times.clear()

    def allow(self) -> bool:
        now = time.monotonic()
        self._times = [stamp for stamp in self._times if now - stamp < self.window_s]
        if len(self._times) >= self.max_runs:
            return False
        self._times.append(now)
        return True
