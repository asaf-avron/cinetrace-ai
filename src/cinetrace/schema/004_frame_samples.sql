-- Frame-level render telemetry. This is the fact table: a real farm emits one
-- sample per frame per host every few seconds, so row count scales with farm
-- hours, not with job count. render_jobs is the dimension table beside it.
--
-- job_id is a plain String, not LowCardinality: ~200k distinct values is well
-- past the point where the dictionary stops paying for itself.
CREATE TABLE IF NOT EXISTS frame_samples
(
    ts            DateTime64(3, 'UTC'),
    job_id        String,
    show          LowCardinality(String),
    host          LowCardinality(String),
    frame         UInt32,
    gpu_util      UInt8,
    vram_used_mb  UInt32,
    vram_total_mb UInt32,
    cpu_util      UInt8,
    rss_mb        UInt32,
    state         LowCardinality(String),

    -- Skip indexes: the Sentinel writes its own drill-down SQL, so it filters on
    -- columns that are not in the sort key.
    INDEX idx_show show TYPE set(16) GRANULARITY 4,
    INDEX idx_vram vram_used_mb TYPE minmax GRANULARITY 4,

    -- Second physical ordering for the ASOF JOIN root-cause query, which seeks
    -- by (host, ts) while the primary key is (job_id, ts). Declared inline so
    -- every insert populates it; an ALTER would only cover new parts.
    PROJECTION by_host
    (
        SELECT host, ts, job_id, frame, gpu_util, vram_used_mb, vram_total_mb, rss_mb
        ORDER BY host, ts
    )
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (job_id, ts);
