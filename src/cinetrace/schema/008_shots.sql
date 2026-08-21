-- Delivery schedule. Waste only matters because it costs a slot on the wall:
-- frames that miss review_at become a missed dailies session.
--
-- ReplacingMergeTree so the live ticker can advance frames_delivered by
-- re-inserting the row instead of mutating it.
CREATE TABLE IF NOT EXISTS shots
(
    show             LowCardinality(String),
    shot             String,
    sequence         LowCardinality(String),
    review_at        DateTime('UTC'),
    frames_required  UInt32,
    frames_delivered UInt32,
    priority         LowCardinality(String),
    updated_at       DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (show, shot);
