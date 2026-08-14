"""Load repo-root .env for ADK, clickhouse-connect, and mcp-clickhouse."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> Path:
    env_path = REPO_ROOT / ".env"
    load_dotenv(env_path, override=False)
    return env_path
