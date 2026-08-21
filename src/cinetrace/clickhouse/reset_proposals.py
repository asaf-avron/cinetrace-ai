"""Clear proposals and decisions so the supervisor page shows an unsolved farm.

Run before a demo or on the nightly judging-window schedule. Without it, a page
that has already been through a full detect-decide-approve cycle shows recovered
waste and no story.
"""

from __future__ import annotations

from cinetrace.clickhouse.client import get_client


def reset_proposals() -> None:
    client = get_client()
    try:
        client.command("TRUNCATE TABLE IF EXISTS remediation_proposals")
        client.command("TRUNCATE TABLE IF EXISTS proposal_decisions")
    finally:
        client.close()


def main() -> None:
    reset_proposals()
    print("Cleared proposals and decisions. Open waste is fully unrecovered again.")


if __name__ == "__main__":
    main()
