-- Continuous per-minute farm rollup.
--
-- The dashboard and the Sentinel's first-pass question ("which show/minute is
-- abnormal?") must not scan 250M frame samples every time. This is incremental
-- aggregation: the MV fires on insert, so the rollup is already computed by the
-- time anyone asks. Keyed on (show, minute) rather than including host, which
-- keeps the target at ~800k rows instead of ~31M.
--
-- Columns are aggregate *states*, not finished numbers, so they still merge
-- correctly as new parts arrive. Readers must use the -Merge combinators.
CREATE TABLE IF NOT EXISTS farm_minute
(
    minute       DateTime('UTC'),
    show         LowCardinality(String),
    samples      AggregateFunction(count),
    active_jobs  AggregateFunction(uniq, String),
    active_hosts AggregateFunction(uniq, String),
    gpu_util_q   AggregateFunction(quantilesTDigest(0.5, 0.95, 0.995), UInt8),
    cpu_util_q   AggregateFunction(quantilesTDigest(0.5, 0.95, 0.995), UInt8),
    vram_peak    AggregateFunction(max, UInt32)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(minute)
ORDER BY (show, minute);

CREATE MATERIALIZED VIEW IF NOT EXISTS farm_minute_mv TO farm_minute AS
SELECT
    toStartOfMinute(ts) AS minute,
    show,
    countState() AS samples,
    uniqState(job_id) AS active_jobs,
    uniqState(toString(host)) AS active_hosts,
    quantilesTDigestState(0.5, 0.95, 0.995)(gpu_util) AS gpu_util_q,
    quantilesTDigestState(0.5, 0.95, 0.995)(cpu_util) AS cpu_util_q,
    maxState(vram_used_mb) AS vram_peak
FROM frame_samples
GROUP BY minute, show;
