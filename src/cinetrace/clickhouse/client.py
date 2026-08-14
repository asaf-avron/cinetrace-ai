"""Real clickhouse-connect client for schema, seed, and health checks."""

from __future__ import annotations

import os

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from cinetrace.env import load_env


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def credentials_ready() -> bool:
    load_env()
    host = os.getenv("CLICKHOUSE_HOST", "").strip()
    password = os.getenv("CLICKHOUSE_PASSWORD", "").strip()
    return bool(host and password)


def get_client() -> Client:
    load_env()
    host = os.getenv("CLICKHOUSE_HOST", "").strip()
    if not host:
        raise RuntimeError(
            "CLICKHOUSE_HOST is empty. Paste the HTTPS host from "
            "ClickHouse Cloud Connect into .env"
        )
    password = os.getenv("CLICKHOUSE_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "CLICKHOUSE_PASSWORD is empty. Paste the HTTPS password from "
            "ClickHouse Cloud Connect into .env"
        )
    return clickhouse_connect.get_client(
        host=host,
        port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=password,
        database=os.getenv("CLICKHOUSE_DATABASE", "default"),
        secure=_truthy(os.getenv("CLICKHOUSE_SECURE"), True),
        verify=_truthy(os.getenv("CLICKHOUSE_VERIFY"), True),
    )


def ping() -> int:
    """Run a real SELECT 1. Returns 1 on success."""
    client = get_client()
    try:
        result = client.query("SELECT 1")
        return int(result.result_rows[0][0])
    finally:
        client.close()
