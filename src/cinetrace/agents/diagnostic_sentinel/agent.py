from google.adk.agents import Agent

from cinetrace.clickhouse.mcp import clickhouse_mcp_toolset
from cinetrace.clickhouse.queries import sentinel_instruction
from cinetrace.env import load_env

load_env()

diagnostic_sentinel = Agent(
    name="diagnostic_sentinel",
    model="gemini-2.5-flash",
    description=(
        "Detects waste and anomalies in render-farm telemetry stored in ClickHouse."
    ),
    instruction=sentinel_instruction(),
    tools=[clickhouse_mcp_toolset()],
)
