"""HTTPS health check against live ClickHouse."""

from __future__ import annotations

from cinetrace.clickhouse.client import get_client, ping


def main() -> None:
    one = ping()
    client = get_client()
    try:
        jobs = client.query("SELECT count() FROM render_jobs").result_rows[0][0]
        proposals = client.query(
            "SELECT count() FROM remediation_proposals"
        ).result_rows[0][0]
    except Exception as exc:  # noqa: BLE001 — table may not exist yet
        print(f"SELECT 1 = {one}; tables not ready: {exc}")
        return
    finally:
        client.close()
    print(
        f"SELECT 1 = {one}; render_jobs rows = {jobs}; "
        f"remediation_proposals rows = {proposals}"
    )


if __name__ == "__main__":
    main()
