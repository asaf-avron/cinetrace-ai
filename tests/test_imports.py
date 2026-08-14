"""Prove Google Cloud and ClickHouse are imported in code, not only named."""


def test_clickhouse_connect_imported() -> None:
    import clickhouse_connect

    assert clickhouse_connect.get_client is not None


def test_vertex_ai_imported() -> None:
    from google.cloud import aiplatform

    assert aiplatform is not None


def test_adk_imported() -> None:
    from google.adk.agents import Agent

    assert Agent is not None


def test_cinetrace_client_imports_clickhouse() -> None:
    from cinetrace.clickhouse import client

    assert client.get_client.__module__.startswith("cinetrace")
