-- Governance layer. A proposal is a reviewable record, not a side effect.
--
-- Both tables are append-only, which is the point: the audit trail is the
-- artifact. Decisions live separately from proposals so approving something
-- never rewrites what the agent originally claimed.
ALTER TABLE remediation_proposals
    ADD COLUMN IF NOT EXISTS shot_at_risk String DEFAULT '';

ALTER TABLE remediation_proposals
    ADD COLUMN IF NOT EXISTS agent LowCardinality(String) DEFAULT 'action_agent';

CREATE TABLE IF NOT EXISTS proposal_decisions
(
    job_id     String,
    action     LowCardinality(String),
    decision   LowCardinality(String),
    decided_by String,
    note       String DEFAULT '',
    decided_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (job_id, action, decided_at);

-- Current state of each proposal: the latest decision wins, and anything
-- undecided is pending. The impact card only credits savings once a human has
-- approved, so the dollar figure moves on approval, not on the agent's say-so.
CREATE OR REPLACE VIEW proposal_state AS
SELECT
    p.job_id AS job_id,
    p.action AS action,
    p.reason AS reason,
    p.shot_at_risk AS shot_at_risk,
    p.agent AS agent,
    p.mode AS mode,
    p.executed AS executed,
    p.created_at AS created_at,
    -- A LEFT JOIN miss on a String column yields '', not NULL, so coalesce
    -- would never fire. Test for empty explicitly.
    if(empty(d.last_decision), 'pending', d.last_decision) AS decision,
    d.last_decided_by AS decided_by,
    d.last_decided_at AS decided_at,
    d.last_note AS note
-- Explicit ON over a concatenated key rather than USING (job_id, action):
-- the join keys are LowCardinality(String) on one side and plain String out of
-- the aggregate on the other, and matching them positionally has proved
-- unreliable on SharedMergeTree -- a proposal with no decision yet could drop
-- out of the view entirely, so a freshly filed proposal was invisible.
FROM remediation_proposals AS p
LEFT JOIN
(
    SELECT
        concat(job_id, '|', toString(action)) AS decision_key,
        argMax(decision, decided_at) AS last_decision,
        argMax(decided_by, decided_at) AS last_decided_by,
        argMax(note, decided_at) AS last_note,
        max(decided_at) AS last_decided_at
    FROM proposal_decisions
    GROUP BY decision_key
) AS d
ON concat(p.job_id, '|', toString(p.action)) = d.decision_key;
