"""Proposals and the human decision on them. Skips until creds are in .env.

Two hard-won constraints shape this file.

First, one integration test rather than several: cleanup uses a lightweight
DELETE, which is an asynchronous mutation on SharedMergeTree, and a later INSERT
into a table whose mutation is still settling does not reliably become visible.

Second, every write uses a freshly generated job id. Re-using an id that has
been deleted before -- even in an earlier pytest run -- means the new row can be
swallowed by the lingering mutation, which reads as "the insert silently did
nothing". That also keeps pytest rows out of the demo the judges see.

The dollar figure moving on approval is asserted through the SQL contract in
test_impact.py rather than here, because the impact aggregates dedupe by job and
a supervisor run may already have filed a proposal for the same archetype.
"""

import uuid

import pytest

from cinetrace.clickhouse.client import credentials_ready, get_client

needs_clickhouse = pytest.mark.skipif(
    not credentials_ready(),
    reason="CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD are not set in .env",
)


def _cleanup(job_id: str) -> None:
    client = get_client()
    try:
        for table in ("remediation_proposals", "proposal_decisions"):
            client.command(
                f"DELETE FROM {table} WHERE job_id = {{jid:String}} "
                "SETTINGS mutations_sync = 1",
                parameters={"jid": job_id},
            )
    finally:
        client.close()


def test_unknown_action_is_refused() -> None:
    from cinetrace.clickhouse.proposals import propose_remediation

    with pytest.raises(ValueError):
        propose_remediation("job-zombie", "rm -rf the farm", "nope")


def test_unknown_decision_is_refused() -> None:
    from cinetrace.clickhouse.proposals import decide_proposal

    with pytest.raises(ValueError):
        decide_proposal("job-zombie", "kill_zombie", "probably")


@needs_clickhouse
def test_proposal_is_pending_until_a_human_decides() -> None:
    """The full governance path: file, read as pending, approve, read as approved."""
    from cinetrace.clickhouse.proposals import decide_proposal, propose_remediation

    job_id = f"job-pytest-{uuid.uuid4().hex[:8]}"
    try:
        proposed = propose_remediation(
            job_id,
            "kill_zombie",
            "pytest evidence: 71.5 GPU-hours with frames stuck at 23",
            shot_at_risk="ORBIT sh0435",
        )
        assert proposed["executed"] is False
        assert proposed["mode"] == "dry_run"
        assert proposed["decision"] == "pending"

        client = get_client()
        try:
            filed = client.query(
                "SELECT decision, shot_at_risk, agent, executed FROM proposal_state "
                "WHERE job_id = {jid:String}",
                parameters={"jid": job_id},
            ).result_rows
            assert filed == [("pending", "ORBIT sh0435", "action_agent", 0)]

            # Filing is not approval: the impact query must not see it yet.
            credited = client.query(
                "SELECT count() FROM proposal_state "
                "WHERE job_id = {jid:String} AND decision = 'approved'",
                parameters={"jid": job_id},
            ).result_rows[0][0]
            assert credited == 0
        finally:
            client.close()

        decided = decide_proposal(
            job_id, "kill_zombie", "approved", decided_by="pytest", note="looks right"
        )
        assert decided["executed"] is False, "approving still changes no render host"

        client = get_client()
        try:
            after = client.query(
                "SELECT decision, decided_by, note FROM proposal_state "
                "WHERE job_id = {jid:String}",
                parameters={"jid": job_id},
            ).result_rows
            assert after == [("approved", "pytest", "looks right")]

            # This is the exact predicate the impact totals credit against.
            in_approved = client.query(
                "SELECT count() FROM ("
                "  SELECT DISTINCT job_id FROM proposal_state WHERE decision = 'approved'"
                ") WHERE job_id = {jid:String}",
                parameters={"jid": job_id},
            ).result_rows[0][0]
            assert in_approved == 1
        finally:
            client.close()
    finally:
        _cleanup(job_id)


@needs_clickhouse
def test_rejecting_does_not_credit_a_saving() -> None:
    from cinetrace.clickhouse.proposals import decide_proposal, propose_remediation

    job_id = f"job-pytest-{uuid.uuid4().hex[:8]}"
    try:
        propose_remediation(job_id, "flag_overrun", "pytest reject path")
        decide_proposal(job_id, "flag_overrun", "rejected", decided_by="pytest")

        client = get_client()
        try:
            rows = client.query(
                "SELECT decision FROM proposal_state WHERE job_id = {jid:String}",
                parameters={"jid": job_id},
            ).result_rows
            assert rows == [("rejected",)]
        finally:
            client.close()
    finally:
        _cleanup(job_id)
