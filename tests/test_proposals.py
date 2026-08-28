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
def test_a_shot_that_still_makes_its_review_cannot_be_claimed_as_protected() -> None:
    """"Protects a review" is the strongest claim the product makes.

    A model that names a shot with a soon deadline which is nonetheless still
    on track has not found a protected delivery, and recording it would put a
    false linkage in the table the whole page rests on. The proposal still
    files -- the waste is real either way -- but the claim does not survive.
    """
    from cinetrace.clickhouse.proposals import propose_remediation
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    rows = fetch_shots_at_risk()["rows"]
    safe = next((r for r in rows if not r.get("at_risk")), None)
    if safe is None:
        pytest.skip("every tracked shot is at risk right now")

    job_id = f"job-test-{uuid.uuid4().hex[:8]}"
    try:
        result = propose_remediation(
            job_id, "kill_zombie", "because", f"{safe['show']} {safe['shot']}"
        )
        assert result["persisted"], "the waste is real even when the shot claim is not"
        assert result["shot_at_risk"] == ""
        assert "protecting no delivery" in result["shot_at_risk_note"]

        client = get_client()
        try:
            filed = client.query(
                "SELECT shot_at_risk FROM proposal_state WHERE job_id = {jid:String}",
                parameters={"jid": job_id},
            ).result_rows
            assert filed == [("",)], "an unverified shot must not reach the table"
        finally:
            client.close()
    finally:
        _cleanup(job_id)


def test_a_multi_shot_claim_keeps_the_one_the_board_agrees_with() -> None:
    """The Orchestrator writes prose, not a field.

    A job blocking three shots comes through as "NEBULA sh0202, NEBULA sh0466,
    NEBULA sh0471". Parsing that as a single SHOW/shot pair threw away a
    correct claim and recorded the proposal as protecting nothing.
    """
    from cinetrace.clickhouse.proposals import _verify_shot

    at_risk = frozenset({("NEBULA", "sh0466"), ("DRIFT", "sh0221")})

    assert (
        _verify_shot("NEBULA sh0202, NEBULA sh0466, NEBULA sh0471", at_risk)
        == "NEBULA sh0466"
    )
    assert _verify_shot("DRIFT sh0221", at_risk) == "DRIFT sh0221"
    assert _verify_shot("nebula/sh0466", at_risk) == "NEBULA sh0466"
    assert _verify_shot("ORBIT sh0194", at_risk) == ""
    assert _verify_shot("NEBULA sh0202, ORBIT sh0194", at_risk) == ""
    assert _verify_shot("the NEBULA one", at_risk) == ""
    assert _verify_shot("none", at_risk) == ""


@needs_clickhouse
def test_a_shot_the_board_does_not_know_is_dropped() -> None:
    from cinetrace.clickhouse.proposals import propose_remediation

    job_id = f"job-test-{uuid.uuid4().hex[:8]}"
    try:
        result = propose_remediation(job_id, "kill_zombie", "because", "the NEBULA one")
        assert result["shot_at_risk"] == ""
        assert result["shot_at_risk_note"]
    finally:
        _cleanup(job_id)


@needs_clickhouse
def test_a_genuinely_at_risk_shot_is_accepted() -> None:
    from cinetrace.clickhouse.proposals import propose_remediation
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    rows = fetch_shots_at_risk()["rows"]
    risky = next((r for r in rows if r.get("at_risk")), None)
    if risky is None:
        pytest.skip("nothing is at risk right now")

    job_id = f"job-test-{uuid.uuid4().hex[:8]}"
    try:
        result = propose_remediation(
            job_id, "kill_zombie", "because", f"{risky['show']} {risky['shot']}"
        )
        assert result["persisted"]
        assert result["shot_at_risk"] == f"{risky['show']} {risky['shot']}"
    finally:
        _cleanup(job_id)


@needs_clickhouse
def test_proposal_is_pending_until_a_human_decides() -> None:
    """The full governance path: file, read as pending, approve, read as approved."""
    from cinetrace.clickhouse.proposals import decide_proposal, propose_remediation

    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    # Cannot be a fixed literal: shot_at_risk is validated against the live
    # delivery board, and a hardcoded shot stops being at risk as it ticks.
    risky = next((r for r in fetch_shots_at_risk()["rows"] if r.get("at_risk")), None)
    if risky is None:
        pytest.skip("nothing is at risk right now")
    shot = f"{risky['show']} {risky['shot']}"

    job_id = f"job-pytest-{uuid.uuid4().hex[:8]}"
    try:
        proposed = propose_remediation(
            job_id,
            "kill_zombie",
            "pytest evidence: 71.5 GPU-hours with frames stuck at 23",
            shot_at_risk=shot,
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
            assert filed == [("pending", shot, "action_agent", 0)]

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
