-- Retention. The live ticker appends telemetry continuously, so the fact table
-- needs a ceiling or it grows without bound for as long as the demo is up.
-- 100 days keeps the full 90-day history plus headroom, and ClickHouse drops
-- expired parts during normal merges rather than in a separate delete pass.
ALTER TABLE frame_samples
    MODIFY TTL toDateTime(ts) + INTERVAL 100 DAY;
