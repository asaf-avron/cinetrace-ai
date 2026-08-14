CREATE TABLE IF NOT EXISTS remediation_proposals
(
    job_id String,
    action LowCardinality(String),
    reason String,
    mode LowCardinality(String) DEFAULT 'dry_run',
    created_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree
ORDER BY (created_at, job_id);
