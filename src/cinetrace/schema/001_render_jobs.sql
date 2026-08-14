CREATE TABLE IF NOT EXISTS render_jobs
(
    job_id String,
    show String,
    shot String,
    renderer LowCardinality(String),
    host String,
    status LowCardinality(String),
    started_at DateTime64(3, 'UTC'),
    ended_at Nullable(DateTime64(3, 'UTC')),
    cpu_hours Float64,
    gpu_hours Float64,
    queue_wait_seconds UInt32,
    retry_count UInt8,
    error_class LowCardinality(String),
    frames_total UInt32,
    frames_done UInt32
)
ENGINE = MergeTree
ORDER BY (show, shot, started_at, job_id);
