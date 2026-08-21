"""Truncate dry-run proposals so the Impact card can show open waste again."""

from __future__ import annotations

from cinetrace.clickhouse.client import get_client


def reset_proposals() -> None:
    client = get_client()
    try:
        client.command("TRUNCATE TABLE IF EXISTS remediation_proposals")
    finally:
        client.close()


def main() -> None:
    reset_proposals()
    print("Truncated remediation_proposals. Impact after_usd will match open waste until the next Run.")


if __name__ == "__main__":
    main()
