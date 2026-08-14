"""Persist a dry-run proposal over HTTPS. Skips until creds are in .env."""

import pytest

from cinetrace.clickhouse.client import credentials_ready, get_client


@pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)
def test_propose_remediation_persists() -> None:
    from cinetrace.clickhouse.proposals import propose_remediation, record_outcome

    result = propose_remediation(
        "job-fail-lic",
        "hold_license_job",
        "pytest dry-run persist",
    )
    assert result["executed"] is False
    assert result["persisted"] is True
    assert result["status"] == "proposed"

    recorded = record_outcome(
        "job-fail-lic",
        "hold_license_job",
        "pytest recorded dry-run outcome",
    )
    assert recorded["status"] == "recorded"
    assert recorded["executed"] is False

    client = get_client()
    try:
        rows = client.query(
            "SELECT count() FROM remediation_proposals "
            "WHERE job_id = {jid:String} AND status = {st:String}",
            parameters={"jid": "job-fail-lic", "st": "recorded"},
        ).result_rows[0][0]
    finally:
        client.close()
    assert int(rows) >= 1
