"""Call official mcp-clickhouse over stdio and run a real SELECT."""

from __future__ import annotations

import asyncio
import json

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from cinetrace.clickhouse.mcp import _stdio_server_params


async def mcp_run_query(sql: str) -> str:
    params = _stdio_server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("run_query", {"query": sql})
            texts = [
                block.text
                for block in result.content
                if getattr(block, "text", None)
            ]
            return "\n".join(texts)


def count_render_jobs() -> int:
    raw = asyncio.run(mcp_run_query("SELECT count() AS n FROM render_jobs"))
    payload = json.loads(raw)
    return int(payload["rows"][0][0])


def main() -> None:
    n = count_render_jobs()
    print(f"MCP run_query: render_jobs rows = {n}")


if __name__ == "__main__":
    main()
