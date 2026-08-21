"""Truncate dry-run proposals so the Impact card can show open waste again."""

from __future__ import annotations

from cinetrace.clickhouse.client import get_client

TRUNCATE_SQL = "TRUNCATE TABLE IF EXISTS remediation_proposals"
COUNT_SQL = "SELECT count() FROM remediation_proposals"


def _proposal_count(client) -> int:
    return int(client.query(COUNT_SQL).result_rows[0][0])


def reset_proposals() -> dict[str, int]:
    """TRUNCATE ``remediation_proposals`` only. Never touches ``render_jobs``."""
    client = get_client()
    try:
        before = _proposal_count(client)
        client.command(TRUNCATE_SQL)
        after = _proposal_count(client)
    finally:
        client.close()
    return {"before": before, "after": after}


def main() -> None:
    counts = reset_proposals()
    print(
        f"remediation_proposals rows before = {counts['before']}; "
        f"after = {counts['after']}"
    )


if __name__ == "__main__":
    main()
