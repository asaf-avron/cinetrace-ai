"""Generate farm-scale render telemetry directly inside ClickHouse.

Everything here is ``INSERT INTO ... SELECT ... FROM numbers_mt(...)`` or an
``ARRAY JOIN`` fan-out over ``render_jobs``. No rows travel over the wire from
Python, so a 250M-row farm builds in minutes instead of hours.

Shape:

- ``render_jobs`` — the dimension table. ~200k jobs over 90 days.
  Everything older than ``LIVE_WINDOW_SECONDS`` is terminal (completed / failed),
  because a job that has been "running" for six weeks is not telemetry, it is a
  bug in the generator. The live cohort in the last 48h carries the running,
  queued, zombie and idle-queue states the Sentinel detects.
- ``frame_samples`` — the fact table. One sample per job every
  ``SAMPLE_SECONDS`` of wall time, fanned out with ``ARRAY JOIN range(...)``.
- ``shots`` — the delivery schedule that turns wasted hours into missed dailies.

Randomness is ``cityHash64(number, salt)``, so a regenerated farm is identical.
That matters: the demo script, the video, and the tests all quote real numbers.

Waste is planted deliberately, not sprinkled:

- **failed** ~2.5% of history, with ``oom`` failures preceded by a VRAM ramp so
  the ASOF JOIN root-cause query has a real signal to find.
- **overrun** ~1.5%, priced as hours-per-frame 3-6x their (show, renderer)
  cohort, which is what the tDigest baselines in ``006_cohort_baselines.sql``
  are built to catch.
- **zombie** / **idle_queue** only in the live window, where they are plausible.

The six named archetypes from the original seed survive as demo anchors
(``job-fail-oom``, ``job-zombie``, ...). They are now needles in a 200k-job
haystack rather than 6 of 62 rows.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from cinetrace.clickhouse.client import get_client

DAYS = 90
JOBS_PER_DAY = 2200
SAMPLE_SECONDS = 10
LIVE_WINDOW_SECONDS = 48 * 3600

SHOWS = ["NEBULA", "AURORA", "ORBIT", "DRIFT", "VESPER", "HALCYON"]
RENDERERS = ["karma", "arnold", "redshift", "houdini", "vray"]
ERROR_CLASSES = ["oom", "license", "crash", "timeout", "disk"]

# Hours per finished frame, before show complexity and per-job noise.
# arnold is the CPU path (no GPU); redshift and karma are GPU-heavy.
GPU_PER_FRAME = [0.080, 0.000, 0.120, 0.100, 0.060]
CPU_PER_FRAME = [0.150, 0.550, 0.050, 0.400, 0.300]
SHOW_COMPLEXITY = [1.00, 1.25, 0.80, 1.45, 0.70, 1.10]

_SHOWS_SQL = "[" + ", ".join(f"'{s}'" for s in SHOWS) + "]"
_RENDERERS_SQL = "[" + ", ".join(f"'{r}'" for r in RENDERERS) + "]"
_ERRORS_SQL = "[" + ", ".join(f"'{e}'" for e in ERROR_CLASSES) + "]"
_GPU_PF_SQL = "[" + ", ".join(str(v) for v in GPU_PER_FRAME) + "]"
_CPU_PF_SQL = "[" + ", ".join(str(v) for v in CPU_PER_FRAME) + "]"
_SHOW_MULT_SQL = "[" + ", ".join(str(v) for v in SHOW_COMPLEXITY) + "]"

# rnd-a01 .. rnd-h30 == 240 render hosts.
_HOST_SQL = """concat(
    'rnd-',
    arrayElement(['a','b','c','d','e','f','g','h'], toInt32(h_host % 8) + 1),
    leftPad(toString(toInt32(intDiv(h_host, 8) % 30) + 1), 2, '0')
)"""

JOB_COLUMNS = """job_id, show, shot, renderer, host, status,
    started_at, ended_at, cpu_hours, gpu_hours,
    queue_wait_seconds, retry_count, error_class,
    frames_total, frames_done"""

# Shared derived columns for both the history and live-cohort inserts. `offset`
# keeps job ids unique across the two passes.
_COMMON_WITH = f"""
    number + {{offset}} AS n,
    cityHash64(n, 101) AS h_show,
    cityHash64(n, 102) AS h_rend,
    cityHash64(n, 103) AS h_host,
    cityHash64(n, 104) AS h_frames,
    cityHash64(n, 105) AS h_age,
    cityHash64(n, 106) AS h_class,
    cityHash64(n, 107) AS h_noise,
    cityHash64(n, 108) AS h_wall,
    cityHash64(n, 109) AS h_queue,
    cityHash64(n, 110) AS h_err,
    arrayElement({_SHOWS_SQL}, toInt32(h_show % 6) + 1) AS show_name,
    arrayElement({_RENDERERS_SQL}, toInt32(h_rend % 5) + 1) AS renderer_name,
    {_HOST_SQL} AS host_name,
    arrayElement({_GPU_PF_SQL}, toInt32(h_rend % 5) + 1) AS gpu_pf,
    arrayElement({_CPU_PF_SQL}, toInt32(h_rend % 5) + 1) AS cpu_pf,
    arrayElement({_SHOW_MULT_SQL}, toInt32(h_show % 6) + 1) AS show_mult,
    0.75 + (h_noise % 500) / 1000.0 AS noise,
    toUInt32(40 + h_frames % 361) AS frames_n,
    toUInt32(40 + h_wall % 51) AS wall_per_frame
"""

HISTORY_SQL = f"""
INSERT INTO render_jobs ({JOB_COLUMNS})
WITH{_COMMON_WITH},
    toUInt32({LIVE_WINDOW_SECONDS} + h_age % ({{days}} * 86400 - {LIVE_WINDOW_SECONDS})) AS age_s,
    multiIf(h_class % 10000 < 250, 'failed',
            h_class % 10000 < 400, 'overrun',
            'completed') AS waste_kind,
    multiIf(waste_kind = 'failed', (h_err % 40) / 100.0, 1.0) AS done_frac,
    greatest(toUInt32(round(frames_n * done_frac)), 1) AS frames_done_n,
    multiIf(waste_kind = 'overrun', 3.0 + (h_noise % 300) / 100.0, 1.0) AS overrun_mult,
    least(
        toUInt32(frames_done_n * wall_per_frame * if(waste_kind = 'overrun', 2, 1)),
        age_s - 300
    ) AS wall_s
SELECT
    concat('job-', leftPad(toString(n), 6, '0')) AS job_id,
    show_name AS show,
    concat('sh', leftPad(toString(toInt32(h_frames % 400) + 100), 4, '0')) AS shot,
    renderer_name AS renderer,
    host_name AS host,
    if(waste_kind = 'failed', 'failed', 'completed') AS status,
    now64(3, 'UTC') - toIntervalSecond(age_s) AS started_at,
    now64(3, 'UTC') - toIntervalSecond(age_s) + toIntervalSecond(wall_s) AS ended_at,
    round(cpu_pf * show_mult * noise * overrun_mult * frames_done_n, 3) AS cpu_hours,
    round(gpu_pf * show_mult * noise * overrun_mult * frames_done_n, 3) AS gpu_hours,
    toUInt32(h_queue % 900) AS queue_wait_seconds,
    if(waste_kind = 'failed',
       toUInt8(if(h_err % 10 < 3, 4 + h_err % 5, 1 + h_err % 3)),
       toUInt8(h_err % 2)) AS retry_count,
    if(waste_kind = 'failed',
       arrayElement({_ERRORS_SQL}, toInt32(h_err % 5) + 1),
       '') AS error_class,
    frames_n AS frames_total,
    frames_done_n AS frames_done
FROM numbers_mt({{total}})
"""

# The live window is where running / queued / zombie / idle_queue are credible.
#
# Two constraints the first version got wrong. First, concurrency: a job holds a
# host, so the number of jobs simultaneously 'running' cannot exceed the 240
# hosts in the pool. Second, shape: zombies do not arrive uniformly at random
# across six shows. A real bad night is one sequence hitting one bad pool, so
# the stuck jobs concentrate on ORBIT and NEBULA. That concentration is what
# makes "free these slots and the show makes its review" a true statement rather
# than a rounding error spread across the whole farm.
LIVE_SQL = f"""
INSERT INTO render_jobs ({JOB_COLUMNS})
WITH{_COMMON_WITH},
    toUInt32(h_age % {LIVE_WINDOW_SECONDS}) AS age_s,
    multiIf(h_class % 10000 < 800,  'failed',
            h_class % 10000 < 860,  'zombie',
            h_class % 10000 < 900,  'idle_queue',
            h_class % 10000 < 1260, 'queued',
            h_class % 10000 < 1690, 'running',
            'completed') AS waste_kind,
    -- Stuck work clusters on two shows; healthy work spreads normally.
    if(waste_kind IN ('zombie', 'idle_queue') AND h_noise % 10 < 7,
       arrayElement(['ORBIT', 'NEBULA'], toInt32(h_noise % 2) + 1),
       show_name) AS live_show,
    multiIf(waste_kind = 'failed', (h_err % 40) / 100.0,
            waste_kind IN ('running', 'zombie'), 0.15 + (h_err % 45) / 100.0,
            waste_kind IN ('queued', 'idle_queue'), 0.0,
            1.0) AS done_frac,
    greatest(toUInt32(round(frames_n * done_frac)), 1) AS frames_done_n,
    -- Zombies have been pinned to a host for a long time with nothing to show.
    multiIf(waste_kind = 'zombie', toUInt32(6 * 3600 + h_age % (34 * 3600)),
            waste_kind = 'running', toUInt32(h_age % (5 * 3600)),
            age_s) AS eff_age_s,
    least(
        toUInt32(frames_done_n * wall_per_frame),
        greatest(eff_age_s - 120, 60)
    ) AS wall_s
SELECT
    -- Width 6, not 5. `n` here starts at offset 900_000, so toString(n) is
    -- already six characters, and ClickHouse's leftPad truncates a string that
    -- is longer than the target rather than leaving it alone: leftPad('900240',
    -- 5, '0') is '90024'. At width 5 the whole live cohort collapsed onto 440
    -- ids, ten unrelated jobs each -- different show, shot, host and status,
    -- one identifier. That makes a proposal unexecutable and double-counts any
    -- aggregate that joins on job_id.
    concat('job-live-', leftPad(toString(n), 6, '0')) AS job_id,
    live_show AS show,
    concat('sh', leftPad(toString(toInt32(h_frames % 400) + 100), 4, '0')) AS shot,
    renderer_name AS renderer,
    host_name AS host,
    multiIf(waste_kind = 'failed', 'failed',
            waste_kind IN ('zombie', 'running'), 'running',
            waste_kind IN ('queued', 'idle_queue'), 'queued',
            'completed') AS status,
    now64(3, 'UTC') - toIntervalSecond(eff_age_s) AS started_at,
    if(status IN ('running', 'queued'),
       NULL,
       now64(3, 'UTC') - toIntervalSecond(eff_age_s) + toIntervalSecond(wall_s)) AS ended_at,
    if(status = 'queued', 0, round(cpu_pf * show_mult * noise * frames_done_n, 3)) AS cpu_hours,
    if(status = 'queued', 0, round(gpu_pf * show_mult * noise * frames_done_n, 3)) AS gpu_hours,
    multiIf(waste_kind = 'idle_queue', toUInt32(3600 + h_queue % (9 * 3600)),
            waste_kind = 'queued', toUInt32(h_queue % 3000),
            toUInt32(h_queue % 900)) AS queue_wait_seconds,
    if(waste_kind = 'failed',
       toUInt8(if(h_err % 10 < 3, 4 + h_err % 5, 1 + h_err % 3)),
       toUInt8(h_err % 2)) AS retry_count,
    if(waste_kind = 'failed',
       arrayElement({_ERRORS_SQL}, toInt32(h_err % 5) + 1),
       '') AS error_class,
    frames_n AS frames_total,
    frames_done_n AS frames_done
FROM numbers_mt({{total}})
"""

# Six named archetypes, one per waste story, anchored to now() so the Sentinel
# predicates stay true whenever the farm is regenerated. Hosts are real members
# of the rnd-a01..rnd-h30 pool so the ASOF root-cause join resolves.
ARCHETYPES_SQL = f"""
INSERT INTO render_jobs ({JOB_COLUMNS}) VALUES
    ('job-fail-oom', 'NEBULA', 'sh0040', 'karma', 'rnd-b04', 'failed',
     now64(3, 'UTC') - INTERVAL 7 HOUR,
     now64(3, 'UTC') - INTERVAL 7 HOUR + INTERVAL 52 MINUTE,
     34.8, 22.4, 45, 6, 'oom', 240, 41),
    ('job-fail-lic', 'AURORA', 'sh0015', 'redshift', 'rnd-c02', 'failed',
     now64(3, 'UTC') - INTERVAL 6 HOUR,
     now64(3, 'UTC') - INTERVAL 6 HOUR + INTERVAL 4 MINUTE,
     1.4, 3.2, 30, 7, 'license', 180, 3),
    ('job-retry-loop', 'AURORA', 'sh0030', 'arnold', 'rnd-c07', 'failed',
     now64(3, 'UTC') - INTERVAL 11 HOUR,
     now64(3, 'UTC') - INTERVAL 6 HOUR,
     128.5, 0, 600, 9, 'crash', 200, 44),
    ('job-idle-queue', 'ORBIT', 'sh0050', 'karma', 'rnd-e12', 'queued',
     now64(3, 'UTC') - INTERVAL 9 HOUR, NULL,
     0, 0, 32400, 0, '', 160, 0),
    ('job-zombie', 'ORBIT', 'sh0080', 'houdini', 'rnd-d11', 'running',
     now64(3, 'UTC') - INTERVAL 31 HOUR, NULL,
     286.0, 71.5, 20, 2, '', 400, 23),
    ('job-overrun', 'NEBULA', 'sh0090', 'karma', 'rnd-a09', 'completed',
     now64(3, 'UTC') - INTERVAL 38 HOUR,
     now64(3, 'UTC') - INTERVAL 12 HOUR,
     412.0, 233.0, 180, 0, '', 96, 96)
"""

# One sample per SAMPLE_SECONDS of wall time, fanned out from render_jobs.
# The OOM ramp is the whole point of the by_host projection: VRAM climbs toward
# the card limit right up to ended_at, so ASOF JOIN lands on a saturated sample.
FRAME_SAMPLES_SQL = f"""
INSERT INTO frame_samples
    (ts, job_id, show, host, frame, gpu_util, vram_used_mb, vram_total_mb,
     cpu_util, rss_mb, state)
WITH
    dateDiff('second', started_at, coalesce(ended_at, now64(3, 'UTC'))) AS wall_s,
    greatest(toUInt32(intDiv(wall_s, {{sample_seconds}})), 1) AS n_samples,
    arrayElement([24576, 49152, 81920], toInt32(cityHash64(host) % 3) + 1) AS vram_cap,
    renderer IN ('karma', 'redshift', 'houdini', 'vray') AS uses_gpu
SELECT
    started_at + toIntervalSecond(s * {{sample_seconds}}) AS ts,
    job_id,
    show,
    host,
    toUInt32(1 + intDiv(s * frames_total, n_samples)) AS frame,
    if(uses_gpu,
       toUInt8(62 + cityHash64(job_id, s, 7) % 38),
       toUInt8(cityHash64(job_id, s, 7) % 6)) AS gpu_util,
    toUInt32(if(
        error_class = 'oom',
        vram_cap * (0.34 + 0.63 * (s / greatest(n_samples - 1, 1))),
        vram_cap * (0.38 + (cityHash64(job_id, s, 8) % 260) / 1000.0)
    )) AS vram_used_mb,
    toUInt32(vram_cap) AS vram_total_mb,
    if(uses_gpu,
       toUInt8(18 + cityHash64(job_id, s, 9) % 30),
       toUInt8(70 + cityHash64(job_id, s, 9) % 30)) AS cpu_util,
    toUInt32(8192 + cityHash64(job_id, s, 10) % 57344) AS rss_mb,
    multiIf(s = 0, 'load',
            s + 1 >= n_samples, 'save',
            'render') AS state
FROM render_jobs
ARRAY JOIN range(n_samples) AS s
WHERE started_at >= {{start}} AND started_at < {{end}}
SETTINGS max_block_size = 512, max_insert_threads = 4
"""

# Deadlines for the shots the live cohort is working on. Roughly one shot in
# eight is generated behind schedule so "at risk" is a real signal, not a
# constant-zero panel.
# The delivery board, not the whole show bible. A supervisor tracks the dozen or
# so shots in flight for the next dailies session, and dailies are a session:
# every shot for a show is reviewed at the same time, with stragglers rolling
# into the following one. Deadlines therefore cluster per show rather than
# scattering uniformly, which is what makes "this session is at risk" a sentence
# anyone in a studio would recognise.
SHOTS_PER_SHOW = 14

# Dailies run on a published schedule, so the sessions are fixed per show rather
# than random. NEBULA and ORBIT sit earliest because they are the shows the
# stuck slots concentrate on -- the whole point is a supervisor seeing that the
# show in trouble is also the show with a review in five hours.
SESSION_HOURS = {"NEBULA": 5, "AURORA": 9, "ORBIT": 6, "DRIFT": 12, "VESPER": 16, "HALCYON": 20}
_SESSION_SQL = "[" + ", ".join(str(SESSION_HOURS[s]) for s in SHOWS) + "]"

# How far out a given shot's review sits, derived from the show's published
# session and a stable per-shot hash so a quarter of the board slips to the
# following session. Hashed rather than row-numbered because the ticker and the
# re-anchor both need the same answer for a shot they see in isolation.
_DUE_HOURS_SQL = f"""
    toUInt32(arrayElement({_SESSION_SQL}, indexOf({_SHOWS_SQL}, show))) AS session_hours,
    if(cityHash64(show, shot, 205) % 4 = 0, session_hours + 14, session_hours) AS due_hours
"""

# How much of a shot is already delivered, at generation and on every roll.
# This is the dial that decides whether the delivery board has a story on it.
# Too high and every shot has a handful of frames left, the farm clears the
# queue in minutes, and nothing can ever miss its review; too low and the whole
# board is red, which is just as uninformative.
#
# At 0.72 the tail of NEBULA's five-hour session -- the show the stuck slots sit
# on -- starts just past its deadline and comes back when those slots are freed.
# The count climbs through a session rather than draining, because the deadline
# closes faster than the farm clears the queue: measured 5 at risk at the top of
# the session, 8 halfway, and it resets when the shots roll.
PROGRESS_FLOOR = 0.72
PROGRESS_SPREAD = 15
_PROGRESS_SQL = f"{PROGRESS_FLOOR} + ({{h}} % {PROGRESS_SPREAD}) / 100.0"

SHOTS_SQL = f"""
INSERT INTO shots (show, shot, sequence, review_at, frames_required, frames_delivered, priority)
WITH
    cityHash64(show, shot, 202) AS h_req,
    cityHash64(show, shot, 203) AS h_prog,
    cityHash64(show, shot, 204) AS h_pri,
    toUInt32(140 + h_req % 260) AS required,
    {_DUE_HOURS_SQL.strip()},
    {_PROGRESS_SQL.format(h="h_prog")} AS progress
SELECT
    show,
    shot,
    concat(substring(show, 1, 3), '_', substring(shot, 3, 2)) AS sequence,
    toDateTime(now('UTC') + toIntervalHour(due_hours), 'UTC') AS review_at,
    required AS frames_required,
    least(toUInt32(round(required * progress)), required - 1) AS frames_delivered,
    arrayElement(['hero', 'standard', 'standard', 'bg'], toInt32(h_pri % 4) + 1) AS priority
FROM
(
    SELECT
        show,
        shot,
        row_number() OVER (PARTITION BY show ORDER BY cityHash64(show, shot)) AS rn
    FROM
    (
        SELECT DISTINCT show, shot
        FROM render_jobs
        WHERE started_at >= now64(3, 'UTC') - INTERVAL 48 HOUR
    )
)
WHERE rn <= {SHOTS_PER_SHOW}
"""


# --------------------------------------------------------------------------
# Keeping the farm alive
# --------------------------------------------------------------------------
#
# The 90-day history is static: it is history, and history does not move. The
# last 48 hours cannot be, because every predicate the Sentinel uses is relative
# to now(). Left alone for a week, every "running" job drifts past the 6-hour
# zombie threshold and the farm reads as one enormous outage.
#
# So the live cohort is disposable. It carries a `job-live-` prefix and the six
# archetypes have fixed ids, which makes both cheap to delete and rebuild
# against a fresh now(). This is what lets the demo survive a judging window
# that runs for two weeks after the submission deadline.

ARCHETYPE_IDS = (
    "job-fail-oom",
    "job-fail-lic",
    "job-retry-loop",
    "job-idle-queue",
    "job-zombie",
    "job-overrun",
)

# One telemetry sample per in-flight job. Cheap (hundreds of rows), and it is
# what keeps the farm_minute materialized view producing fresh minutes.
TICK_SAMPLES_SQL = """
INSERT INTO frame_samples
    (ts, job_id, show, host, frame, gpu_util, vram_used_mb, vram_total_mb,
     cpu_util, rss_mb, state)
WITH
    arrayElement([24576, 49152, 81920], toInt32(cityHash64(host) % 3) + 1) AS vram_cap,
    renderer IN ('karma', 'redshift', 'houdini', 'vray') AS uses_gpu,
    toUInt64(toUnixTimestamp(now('UTC'))) AS tick
SELECT
    now64(3, 'UTC') AS ts,
    job_id,
    show,
    host,
    greatest(frames_done, 1) AS frame,
    if(uses_gpu,
       toUInt8(62 + cityHash64(job_id, tick, 7) % 38),
       toUInt8(cityHash64(job_id, tick, 7) % 6)) AS gpu_util,
    toUInt32(if(
        error_class = 'oom',
        vram_cap * 0.95,
        vram_cap * (0.38 + (cityHash64(job_id, tick, 8) % 260) / 1000.0)
    )) AS vram_used_mb,
    toUInt32(vram_cap) AS vram_total_mb,
    if(uses_gpu,
       toUInt8(18 + cityHash64(job_id, tick, 9) % 30),
       toUInt8(70 + cityHash64(job_id, tick, 9) % 30)) AS cpu_util,
    toUInt32(8192 + cityHash64(job_id, tick, 10) % 57344) AS rss_mb,
    'render' AS state
FROM render_jobs
WHERE status = 'running'
"""

# Delivery moves too. Shots whose review has passed roll to their show's next
# session with fresh progress, so there is always a next deadline to protect.
# The new deadline is measured from now(), not from the deadline it replaces:
# adding to the old value ratchets the whole board into the future.
# Delivery has to advance at roughly the rate the farm could actually render,
# or the board drains and "dailies at risk" is permanently zero. About 224 slots
# at ~0.46 hours per frame is ~480 frames an hour across all shows, so at a 30s
# tick that is ~4 frames total -- one frame on one shot in twenty-one, not two
# frames on every shot.
#
# A shot rolls to the next session when it is delivered or its review passes,
# which keeps the board populated instead of emptying over a judging window.
#
# FINAL matters: shots is a ReplacingMergeTree, and reading it without FINAL
# between merges returns both versions of a row, so the ticker would re-insert
# duplicates and the board would double on every beat.
#
# The derived columns live in a subquery rather than a WITH clause so that
# `review_at` on the way out does not shadow the `review_at` that `rolled`
# is computed from.
TICK_SHOTS_SQL = f"""
INSERT INTO shots (show, shot, sequence, review_at, frames_required, frames_delivered, priority)
SELECT
    show,
    shot,
    sequence,
    if(rolled,
       toDateTime(now('UTC') + toIntervalHour(due_hours), 'UTC'),
       review_at) AS next_review_at,
    if(rolled, toUInt32(140 + h % 260), frames_required) AS next_required,
    if(rolled,
       toUInt32(round((140 + h % 260) * ({_PROGRESS_SQL.format(h="h")}))),
       least(frames_delivered + if(h % 21 = 0, 1, 0), frames_required)) AS next_delivered,
    priority
FROM
(
    SELECT
        show, shot, sequence, review_at, frames_required, frames_delivered, priority,
        cityHash64(show, shot, toUnixTimestamp(now('UTC'))) AS h,
        {_DUE_HOURS_SQL.strip()},
        (review_at <= now('UTC')) OR (frames_delivered >= frames_required) AS rolled
    FROM shots FINAL
)
"""


# The ticker alone cannot repair a board that has already drifted, and drift is
# the default over a judging window: a shot that rolls early gets a new deadline,
# and if that deadline is measured from the old one rather than from now() the
# whole schedule ratchets forward. Three days of 30-second ticks moved the
# earliest session from 5 hours out to 42, at which point nothing on the board
# can ever be late and the headline reads zero.
#
# So the invariant is stated here and re-asserted on every refresh: a shot's
# review sits within its show's published session window, never beyond it.
REANCHOR_SHOTS_SQL = f"""
INSERT INTO shots (show, shot, sequence, review_at, frames_required, frames_delivered, priority)
SELECT
    show,
    shot,
    sequence,
    toDateTime(now('UTC') + toIntervalHour(due_hours), 'UTC') AS review_at,
    frames_required,
    frames_delivered,
    priority
FROM
(
    SELECT
        show, shot, sequence, review_at AS current_review_at,
        frames_required, frames_delivered, priority,
        {_DUE_HOURS_SQL.strip()}
    FROM shots FINAL
)
WHERE current_review_at > now('UTC') + toIntervalHour(due_hours)
"""


# A rebuilt live cohort has no telemetry of its own, and without it the ASOF
# root-cause join falls back to whatever older sample happens to sit on the same
# host -- which reads as "died 52 minutes after the host hit 97% VRAM" instead of
# 20 seconds, and the VRAM figure belongs to a different job.
#
# Backfilling every refreshed job would add ~176k rows every 15 minutes, so this
# covers only the jobs the evidence panels actually read: OOM failures and
# zombies, 40 samples each ending at the moment of death.
LIVE_BACKFILL_SQL = """
INSERT INTO frame_samples
    (ts, job_id, show, host, frame, gpu_util, vram_used_mb, vram_total_mb,
     cpu_util, rss_mb, state)
WITH
    40 AS n_samples,
    coalesce(ended_at, now64(3, 'UTC')) AS finish,
    greatest(dateDiff('second', started_at, finish), 120) AS wall_s,
    arrayElement([24576, 49152, 81920], toInt32(cityHash64(host) % 3) + 1) AS vram_cap,
    renderer IN ('karma', 'redshift', 'houdini', 'vray') AS uses_gpu
SELECT
    finish - toIntervalSecond(toUInt32(
        4 + cityHash64(job_id, 3) % 9
        + (n_samples - 1 - s) * intDiv(wall_s, n_samples)
    )) AS ts,
    job_id,
    show,
    host,
    toUInt32(1 + intDiv(s * greatest(frames_done, 1), n_samples)) AS frame,
    if(uses_gpu,
       toUInt8(62 + cityHash64(job_id, s, 7) % 38),
       toUInt8(cityHash64(job_id, s, 7) % 6)) AS gpu_util,
    toUInt32(if(
        error_class = 'oom',
        vram_cap * (0.34 + 0.63 * (s / (n_samples - 1))),
        vram_cap * (0.38 + (cityHash64(job_id, s, 8) % 260) / 1000.0)
    )) AS vram_used_mb,
    toUInt32(vram_cap) AS vram_total_mb,
    if(uses_gpu,
       toUInt8(18 + cityHash64(job_id, s, 9) % 30),
       toUInt8(70 + cityHash64(job_id, s, 9) % 30)) AS cpu_util,
    toUInt32(8192 + cityHash64(job_id, s, 10) % 57344) AS rss_mb,
    if(s + 1 >= n_samples, 'save', 'render') AS state
FROM render_jobs
ARRAY JOIN range(40) AS s
WHERE started_at >= now('UTC') - INTERVAL 48 HOUR
  AND (
      (status = 'failed' AND error_class = 'oom')
      OR (status = 'running' AND started_at < now('UTC') - INTERVAL 6 HOUR)
  )
SETTINGS max_block_size = 512
"""


def refresh_live_cohort(client: Any, jobs_per_day: int = JOBS_PER_DAY) -> None:
    """Rebuild the last 48 hours against a fresh now(). Leaves history untouched.

    mutations_sync is not optional here. A lightweight DELETE is an asynchronous
    mutation, so without it the delete can still be running when the reinsert
    lands and will happily remove the rows it was never meant to see -- the
    cohort silently comes back short, or empty.
    """
    ids = ", ".join(f"'{job_id}'" for job_id in ARCHETYPE_IDS)
    client.command(
        "DELETE FROM render_jobs WHERE startsWith(job_id, 'job-live-') "
        "SETTINGS mutations_sync = 1"
    )
    client.command(
        f"DELETE FROM render_jobs WHERE job_id IN ({ids}) SETTINGS mutations_sync = 1"
    )
    client.command(LIVE_SQL.format(days=DAYS, total=2 * jobs_per_day, offset=900_000))
    client.command(ARCHETYPES_SQL)
    client.command(LIVE_BACKFILL_SQL)
    client.command(REANCHOR_SHOTS_SQL)


def tick(client: Any) -> None:
    """One heartbeat of the live farm: fresh telemetry, advanced delivery."""
    client.command(TICK_SAMPLES_SQL)
    client.command(TICK_SHOTS_SQL)


def _log(message: str) -> None:
    print(message, flush=True)


def _truncate(client: Any) -> None:
    for table in ("frame_samples", "render_jobs", "shots"):
        client.command(f"TRUNCATE TABLE IF EXISTS {table}")
    _log("Truncated render_jobs, frame_samples, shots.")


def generate_jobs(client: Any, days: int, jobs_per_day: int) -> int:
    """Insert the history body, the live cohort, and the six named archetypes."""
    history_total = max(days - 2, 1) * jobs_per_day
    live_total = 2 * jobs_per_day

    started = time.time()
    client.command(HISTORY_SQL.format(days=days, total=history_total, offset=1))
    _log(f"  history: {history_total:,} jobs in {time.time() - started:.1f}s")

    started = time.time()
    client.command(LIVE_SQL.format(days=days, total=live_total, offset=900_000))
    _log(f"  live cohort: {live_total:,} jobs in {time.time() - started:.1f}s")

    client.command(ARCHETYPES_SQL)
    _log("  archetypes: 6 named demo jobs")

    return history_total + live_total + 6


def generate_frame_samples(client: Any, days: int, sample_seconds: int) -> int:
    """Fan render_jobs out into per-sample telemetry, one day-partition at a time.

    Chunking keeps the ARRAY JOIN working set small enough for a Cloud service;
    a single 250M-row statement would need many GB of memory for the range()
    arrays alone.
    """
    total = 0
    for day in range(days, -1, -1):
        start = f"now64(3, 'UTC') - INTERVAL {day + 1} DAY"
        end = f"now64(3, 'UTC') - INTERVAL {day} DAY"
        started = time.time()
        client.command(
            FRAME_SAMPLES_SQL.format(
                sample_seconds=sample_seconds, start=start, end=end
            )
        )
        rows = client.query(
            "SELECT count() FROM frame_samples"
        ).result_rows[0][0]
        added = rows - total
        total = rows
        _log(
            f"  day -{day:>2}: +{added:>10,} samples "
            f"({time.time() - started:5.1f}s, total {total:,})"
        )
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--jobs-per-day", type=int, default=JOBS_PER_DAY)
    parser.add_argument("--sample-seconds", type=int, default=SAMPLE_SECONDS)
    parser.add_argument(
        "--jobs-only",
        action="store_true",
        help="Regenerate render_jobs and shots without the frame_samples fan-out.",
    )
    parser.add_argument(
        "--refresh-live",
        action="store_true",
        help="Rebuild only the last 48h against a fresh now(). Keeps history.",
    )
    args = parser.parse_args()

    client = get_client()
    try:
        if args.refresh_live:
            refresh_live_cohort(client, args.jobs_per_day)
            _log("Refreshed the live cohort and the six archetypes.")
            return

        _truncate(client)

        _log(f"Generating render_jobs over {args.days} days...")
        jobs = generate_jobs(client, args.days, args.jobs_per_day)
        _log(f"render_jobs: {jobs:,}")

        client.command(SHOTS_SQL)
        shots = client.query("SELECT count() FROM shots").result_rows[0][0]
        _log(f"shots: {shots:,}")

        if args.jobs_only:
            _log("Skipping frame_samples (--jobs-only).")
            return

        _log(f"Generating frame_samples every {args.sample_seconds}s of wall time...")
        samples = generate_frame_samples(client, args.days, args.sample_seconds)
        _log(f"frame_samples: {samples:,}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
