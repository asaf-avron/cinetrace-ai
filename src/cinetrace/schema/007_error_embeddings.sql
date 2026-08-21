-- Institutional memory for render failures.
--
-- A render wrangler's real advantage over a dashboard is having seen the
-- failure before. This table is that memory: historical incidents, what fixed
-- them, and a Vertex AI embedding of the error text so the Sentinel can ask
-- "have we seen this?" semantically rather than by string match.
--
-- Search is brute-force cosineDistance over a few hundred rows, which is
-- sub-millisecond and exact. An ANN index would be the right call at millions
-- of vectors and the wrong call here.
CREATE TABLE IF NOT EXISTS error_embeddings
(
    fingerprint String,
    error_class LowCardinality(String),
    renderer    LowCardinality(String),
    error_text  String,
    resolution  String,
    occurrences UInt32,
    last_seen   DateTime('UTC'),
    embedding   Array(Float32)
)
ENGINE = MergeTree
ORDER BY (error_class, fingerprint);
