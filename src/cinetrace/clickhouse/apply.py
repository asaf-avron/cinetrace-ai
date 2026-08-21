"""Apply schema DDL to ClickHouse Cloud over HTTPS.

Numbered files run in filename order, which is load-bearing: ``005_rollups.sql``
creates a materialized view over ``frame_samples``, and a materialized view only
sees rows inserted *after* it exists. Schema first, then
``python -m cinetrace.clickhouse.generate`` to fill the farm.
"""

from __future__ import annotations

from pathlib import Path

from cinetrace.clickhouse.client import get_client

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"


def schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def _statements(sql: str) -> list[str]:
    cleaned = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    parts: list[str] = []
    for chunk in cleaned.split(";"):
        statement = chunk.strip()
        if statement:
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
    for path in schema_files():
        apply_file(path.name)
        print(f"applied {path.name}")
    print(
        "Schema applied. Run `python -m cinetrace.clickhouse.generate` to build the farm."
    )


if __name__ == "__main__":
    main()
