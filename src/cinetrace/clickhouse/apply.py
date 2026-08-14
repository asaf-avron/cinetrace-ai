"""Apply schema and seed SQL to ClickHouse Cloud over HTTPS."""

from __future__ import annotations

from pathlib import Path

from cinetrace.clickhouse.client import get_client

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"


def _statements(sql: str) -> list[str]:
    parts: list[str] = []
    for chunk in sql.split(";"):
        statement = chunk.strip()
        if statement and not statement.startswith("--"):
            parts.append(statement)
    return parts


def apply_file(name: str) -> None:
    path = SCHEMA_DIR / name
    sql = path.read_text(encoding="utf-8")
    client = get_client()
    try:
        for statement in _statements(sql):
            client.command(statement)
    finally:
        client.close()


def main() -> None:
    apply_file("001_render_jobs.sql")
    apply_file("002_remediation_proposals.sql")
    apply_file("003_proposal_outcomes.sql")
    apply_file("seed.sql")
    print("Applied schema and seed to ClickHouse.")


if __name__ == "__main__":
    main()
