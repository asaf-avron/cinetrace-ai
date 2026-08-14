TRUNCATE TABLE IF EXISTS render_jobs;

INSERT INTO render_jobs (
    job_id, show, shot, renderer, host, status,
    started_at, ended_at, cpu_hours, gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done
) VALUES
    ('job-ok-001', 'NEBULA', 'sh010', 'karma', 'rnd-a01', 'completed',
     '2026-08-13 08:00:00.000', '2026-08-13 08:42:00.000', 12.4, 6.1,
     90, 0, '', 120, 120),
    ('job-ok-002', 'NEBULA', 'sh020', 'arnold', 'rnd-a02', 'completed',
     '2026-08-13 09:10:00.000', '2026-08-13 09:55:00.000', 18.0, 0,
     120, 1, '', 80, 80),
    ('job-fail-oom', 'NEBULA', 'sh040', 'karma', 'rnd-b04', 'failed',
     '2026-08-13 11:00:00.000', '2026-08-13 11:08:00.000', 2.1, 1.8,
     45, 4, 'oom', 240, 12),
    ('job-fail-lic', 'AURORA', 'sh015', 'redshift', 'rnd-c02', 'failed',
     '2026-08-13 12:00:00.000', '2026-08-13 12:02:00.000', 0.2, 0.2,
     30, 6, 'license', 60, 0),
    ('job-retry-loop', 'AURORA', 'sh030', 'arnold', 'rnd-c07', 'failed',
     '2026-08-13 13:15:00.000', '2026-08-13 16:40:00.000', 41.0, 0,
     600, 8, 'crash', 200, 40),
    ('job-idle-queue', 'ORBIT', 'sh050', 'karma', 'queue', 'queued',
     '2026-08-13 06:00:00.000', NULL, 0, 0,
     28800, 0, '', 160, 0),
    ('job-zombie', 'ORBIT', 'sh080', 'houdini', 'rnd-d11', 'running',
     '2026-08-12 18:00:00.000', NULL, 96.0, 48.0,
     20, 2, '', 400, 18),
    ('job-overrun', 'NEBULA', 'sh090', 'karma', 'rnd-a09', 'completed',
     '2026-08-12 20:00:00.000', '2026-08-13 10:30:00.000', 220.0, 110.0,
     180, 0, '', 48, 48);
