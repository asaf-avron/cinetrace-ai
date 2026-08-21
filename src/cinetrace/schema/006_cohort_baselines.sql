-- Statistical baselines, so "overrun" stops being a magic number.
--
-- The old rule was `cpu_hours >= 100 OR gpu_hours >= 50`, which is meaningless
-- across a farm where an arnold CPU job legitimately burns 10x the hours of a
-- redshift GPU job for the same shot. Instead: bucket by (show, renderer) and
-- ask whether a job is abnormal *for its own cohort*.
--
-- The threshold is a robust upper fence, p50 + 3 * (p95 - p50). p50 and p95 are
-- unaffected by a 1.5% tail of genuine overruns, so the fence does not drift up
-- to absorb the very jobs it is meant to catch.
CREATE OR REPLACE VIEW cohort_baselines AS
SELECT
    show,
    renderer,
    count() AS cohort_jobs,
    quantileTDigest(0.50)(hours_per_frame) AS p50,
    quantileTDigest(0.95)(hours_per_frame) AS p95,
    quantileTDigest(0.995)(hours_per_frame) AS p995,
    p50 + 3 * (p95 - p50) AS overrun_fence,
    quantileTDigest(0.50)(cpu_per_frame) AS cpu_p50,
    quantileTDigest(0.50)(gpu_per_frame) AS gpu_p50
FROM
(
    SELECT
        show,
        renderer,
        (cpu_hours + gpu_hours) / frames_done AS hours_per_frame,
        cpu_hours / frames_done AS cpu_per_frame,
        gpu_hours / frames_done AS gpu_per_frame
    FROM render_jobs
    WHERE status = 'completed' AND frames_done > 0
)
GROUP BY show, renderer;

-- One primary waste class per job, so the dollar headline is not double-counted.
-- retry_loop is a tag that overlaps `failed`; it is counted in the category card
-- but never added to the total a second time.
--
-- is_open separates "burning right now, an agent can still act" from the 90-day
-- historical total. Both numbers are real; only one of them is actionable.
CREATE OR REPLACE VIEW job_waste AS
SELECT
    j.job_id,
    j.show,
    j.shot,
    j.renderer,
    j.host,
    j.status,
    j.started_at,
    j.ended_at,
    j.cpu_hours,
    j.gpu_hours,
    j.queue_wait_seconds,
    j.retry_count,
    j.error_class,
    j.frames_total,
    j.frames_done,
    b.p50 AS cohort_p50,
    b.overrun_fence AS cohort_fence,
    if(j.frames_done > 0, (j.cpu_hours + j.gpu_hours) / j.frames_done, 0) AS hours_per_frame,
    j.retry_count >= 4 AS retry_loop,
    multiIf(
        j.status = 'running' AND j.started_at < now('UTC') - INTERVAL 6 HOUR, 'zombie',
        j.status = 'failed', 'failed',
        j.status = 'queued' AND j.queue_wait_seconds >= 3600, 'idle_queue',
        j.status = 'completed' AND j.frames_done > 0 AND b.overrun_fence > 0
            AND (j.cpu_hours + j.gpu_hours) / j.frames_done > b.overrun_fence, 'overrun',
        'healthy'
    ) AS waste_class,
    multiIf(
        waste_class IN ('zombie', 'failed'), j.cpu_hours,
        waste_class = 'overrun', greatest(j.cpu_hours - b.cpu_p50 * j.frames_done, 0),
        0
    ) AS waste_cpu_hours,
    multiIf(
        waste_class IN ('zombie', 'failed'), j.gpu_hours,
        waste_class = 'idle_queue', j.queue_wait_seconds / 3600,
        waste_class = 'overrun', greatest(j.gpu_hours - b.gpu_p50 * j.frames_done, 0),
        0
    ) AS waste_gpu_hours,
    -- "Open" means an agent can still change the outcome: the job is holding
    -- capacity right now, or it failed recently and will be resubmitted into
    -- the same wall. A completed overrun is neither -- the hours are spent and
    -- no action reclaims them -- so overruns are reported in the 90-day
    -- history and never in the actionable total.
    multiIf(
        waste_class IN ('zombie', 'idle_queue'), true,
        waste_class = 'failed'
            AND coalesce(j.ended_at, j.started_at) >= now('UTC') - INTERVAL 48 HOUR, true,
        false
    ) AS is_open
FROM render_jobs AS j
LEFT JOIN cohort_baselines AS b USING (show, renderer);
