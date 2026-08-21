TRUNCATE TABLE IF EXISTS render_jobs;

-- Six named waste archetypes. Times are now()-relative so zombies stay
-- zombies on judging day (ZOMBIES uses started_at < now('UTC') - 6 hours).
INSERT INTO render_jobs (
    job_id, show, shot, renderer, host, status,
    started_at, ended_at, cpu_hours, gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done
) VALUES
    ('job-ok-001', 'NEBULA', 'sh010', 'karma', 'rnd-a01', 'completed',
     now64(3, 'UTC') - INTERVAL 6 HOUR, now64(3, 'UTC') - INTERVAL 5 HOUR, 12.4, 6.1,
     90, 0, '', 120, 120),
    ('job-ok-002', 'NEBULA', 'sh020', 'arnold', 'rnd-a02', 'completed',
     now64(3, 'UTC') - INTERVAL 5 HOUR, now64(3, 'UTC') - INTERVAL 4 HOUR, 18.0, 0,
     120, 1, '', 80, 80),
    ('job-fail-oom', 'NEBULA', 'sh040', 'karma', 'rnd-b04', 'failed',
     now64(3, 'UTC') - INTERVAL 7 HOUR, now64(3, 'UTC') - INTERVAL 7 HOUR + INTERVAL 8 MINUTE, 2.1, 1.8,
     45, 4, 'oom', 240, 12),
    ('job-fail-lic', 'AURORA', 'sh015', 'redshift', 'rnd-c02', 'failed',
     now64(3, 'UTC') - INTERVAL 6 HOUR, now64(3, 'UTC') - INTERVAL 6 HOUR + INTERVAL 2 MINUTE, 0.2, 0.2,
     30, 6, 'license', 60, 0),
    ('job-retry-loop', 'AURORA', 'sh030', 'arnold', 'rnd-c07', 'failed',
     now64(3, 'UTC') - INTERVAL 10 HOUR, now64(3, 'UTC') - INTERVAL 6 HOUR, 41.0, 0,
     600, 8, 'crash', 200, 40),
    ('job-idle-queue', 'ORBIT', 'sh050', 'karma', 'queue', 'queued',
     now64(3, 'UTC') - INTERVAL 8 HOUR, NULL, 0, 0,
     28800, 0, '', 160, 0),
    ('job-zombie', 'ORBIT', 'sh080', 'houdini', 'rnd-d11', 'running',
     now64(3, 'UTC') - INTERVAL 2 DAY, NULL, 96.0, 48.0,
     20, 2, '', 400, 18),
    ('job-overrun', 'NEBULA', 'sh090', 'karma', 'rnd-a09', 'completed',
     now64(3, 'UTC') - INTERVAL 36 HOUR, now64(3, 'UTC') - INTERVAL 12 HOUR, 220.0, 110.0,
     180, 0, '', 48, 48);

-- Healthy completed farm traffic (no waste predicates).
INSERT INTO render_jobs (
    job_id, show, shot, renderer, host, status,
    started_at, ended_at, cpu_hours, gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done
)
SELECT
    concat('job-farm-', leftPad(toString(number + 1), 3, '0')),
    arrayElement(['NEBULA', 'AURORA', 'ORBIT', 'DRIFT'], (number % 4) + 1),
    concat('sh', leftPad(toString(110 + number), 3, '0')),
    arrayElement(['karma', 'arnold', 'redshift'], (number % 3) + 1),
    concat('rnd-', leftPad(toString(number % 14), 2, '0')),
    'completed',
    now64(3, 'UTC') - toIntervalHour(4 + (number % 60)),
    now64(3, 'UTC') - toIntervalHour(3 + (number % 60)),
    6 + (number % 18),
    1 + (number % 7),
    20 + (number % 240),
    0,
    '',
    64 + (number % 48),
    64 + (number % 48)
FROM numbers(50);

-- In-progress jobs started recently so they are not zombies.
INSERT INTO render_jobs (
    job_id, show, shot, renderer, host, status,
    started_at, ended_at, cpu_hours, gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done
)
SELECT
    concat('job-live-', leftPad(toString(number + 1), 2, '0')),
    arrayElement(['NEBULA', 'AURORA'], (number % 2) + 1),
    concat('sh', leftPad(toString(200 + number), 3, '0')),
    'karma',
    concat('rnd-live-', toString(number)),
    'running',
    now64(3, 'UTC') - toIntervalMinute(20 + number * 8),
    NULL,
    1.2 + number,
    0.4 + (number * 0.2),
    15,
    0,
    '',
    96,
    20 + number * 5
FROM numbers(4);
