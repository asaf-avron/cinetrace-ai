"""ADK McpToolset → official mcp-clickhouse (stdio) using HTTPS .env creds."""

from __future__ import annotations

import os
import shutil
import sys

from google.adk.tools.mcp_tool import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters

from cinetrace.env import load_env


def _stdio_server_params() -> StdioServerParameters:
    load_env()
    env = os.environ.copy()
    for key in (
        "CLICKHOUSE_HOST",
        "CLICKHOUSE_PORT",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
        "CLICKHOUSE_SECURE",
        "CLICKHOUSE_VERIFY",
        "CLICKHOUSE_DATABASE",
    ):
        value = os.getenv(key)
        if value is not None:
            env[key] = value

    mcp_bin = shutil.which("mcp-clickhouse")
    if mcp_bin:
        return StdioServerParameters(command=mcp_bin, args=[], env=env)

    # mcp-clickhouse has no __main__.py; invoke the published entrypoint.
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", "from mcp_clickhouse.main import main; main()"],
        env=env,
    )


_toolset: McpToolset | None = None


def clickhouse_mcp_toolset() -> McpToolset:
    """Agents query ClickHouse through MCP, not a mocked wrapper."""
    global _toolset
    if _toolset is None:
        _toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=_stdio_server_params(),
                timeout=60,
            )
        )
    return _toolset
