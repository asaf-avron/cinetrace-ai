"""Impact calculator math against the committed seed rows. No ClickHouse required."""

from cinetrace.clickhouse.impact import (
    AFTER_LABEL_OPEN,
    AFTER_LABEL_RECOVERED,
    CPU_HOUR_USD,
    GPU_HOUR_USD,
    healthy_baseline,
    hours_to_usd,
    summarize_impact,
)

# Mirrors src/cinetrace/schema/seed.sql. waste_class matches the live SQL predicates.
SEED_JOBS = [
    {
        "job_id": "job-ok-001",
        "show": "NEBULA",
        "shot": "sh010",
        "status": "completed",
        "retry_count": 0,
        "cpu_hours": 12.4,
        "gpu_hours": 6.1,
        "queue_wait_seconds": 90,
        "frames_done": 120,
        "waste_class": "healthy",
    },
    {
        "job_id": "job-ok-002",
        "show": "NEBULA",
        "shot": "sh020",
        "status": "completed",
        "retry_count": 1,
        "cpu_hours": 18.0,
        "gpu_hours": 0,
        "queue_wait_seconds": 120,
        "frames_done": 80,
        "waste_class": "healthy",
    },
    {
        "job_id": "job-fail-oom",
        "show": "NEBULA",
        "shot": "sh040",
        "status": "failed",
        "retry_count": 4,
        "cpu_hours": 2.1,
        "gpu_hours": 1.8,
        "queue_wait_seconds": 45,
        "frames_done": 12,
        "waste_class": "failed",
    },
    {
        "job_id": "job-fail-lic",
        "show": "AURORA",
        "shot": "sh015",
        "status": "failed",
        "retry_count": 6,
        "cpu_hours": 0.2,
        "gpu_hours": 0.2,
        "queue_wait_seconds": 30,
        "frames_done": 0,
        "waste_class": "failed",
    },
    {
        "job_id": "job-retry-loop",
        "show": "AURORA",
        "shot": "sh030",
        "status": "failed",
        "retry_count": 8,
        "cpu_hours": 41.0,
        "gpu_hours": 0,
        "queue_wait_seconds": 600,
        "frames_done": 40,
        "waste_class": "failed",
    },
    {
        "job_id": "job-idle-queue",
        "show": "ORBIT",
        "shot": "sh050",
        "status": "queued",
        "retry_count": 0,
        "cpu_hours": 0,
        "gpu_hours": 0,
        "queue_wait_seconds": 28800,
        "frames_done": 0,
        "waste_class": "idle_queue",
    },
    {
        "job_id": "job-zombie",
        "show": "ORBIT",
        "shot": "sh080",
        "status": "running",
        "retry_count": 2,
        "cpu_hours": 96.0,
        "gpu_hours": 48.0,
        "queue_wait_seconds": 20,
        "frames_done": 18,
        "waste_class": "zombie",
    },
    {
        "job_id": "job-overrun",
        "show": "NEBULA",
        "shot": "sh090",
        "status": "completed",
        "retry_count": 0,
        "cpu_hours": 220.0,
        "gpu_hours": 110.0,
        "queue_wait_seconds": 180,
        "frames_done": 48,
        "waste_class": "overrun",
    },
]


def test_healthy_baseline_from_seed() -> None:
    base = healthy_baseline(SEED_JOBS)
    assert base["cpu_per_frame"] == 30.4 / 200
    assert base["gpu_per_frame"] == 6.1 / 200


def test_seed_waste_dollars() -> None:
    impact = summarize_impact(SEED_JOBS, set())
    assert impact["job_count"] == 8
    assert impact["waste_job_count"] == 6
    assert impact["before_usd"] == 625.12
    assert impact["after_usd"] == 625.12
    assert impact["recovered_usd"] == 0
    assert impact["recovery_state"] == "none"
    assert impact["open_usd"] == 625.12
    assert impact["after_label"] == AFTER_LABEL_OPEN
    assert impact["waste_gpu_hours"] == 166.536
    assert impact["assumptions"]["gpu_hour_usd"] == GPU_HOUR_USD
    assert impact["assumptions"]["cpu_hour_usd"] == CPU_HOUR_USD

    by_cat = {row["category"]: row for row in impact["categories"]}
    assert by_cat["failed"]["job_count"] == 3
    assert by_cat["failed"]["waste_usd"] == 12.20
    assert by_cat["retry_loops"]["job_count"] == 3
    assert by_cat["idle_queue"]["waste_usd"] == 28.00
    assert by_cat["zombies"]["waste_usd"] == 179.52
    assert by_cat["overruns"]["waste_usd"] == 405.40


def test_before_after_when_proposals_applied() -> None:
    proposed = {"job-zombie", "job-idle-queue", "job-fail-lic"}
    impact = summarize_impact(SEED_JOBS, proposed)
    assert impact["recovered_usd"] == 208.24
    assert impact["after_usd"] == 416.88
    assert impact["before_usd"] == 625.12
    assert impact["proposed_job_count"] == 3
    assert impact["recovery_state"] == "partial"
    assert impact["open_usd"] == 416.88
    assert impact["after_label"] == AFTER_LABEL_OPEN


def test_full_recovery_is_not_a_healthy_farm() -> None:
    waste_ids = {job["job_id"] for job in SEED_JOBS if job["waste_class"] != "healthy"}
    impact = summarize_impact(SEED_JOBS, waste_ids)
    assert waste_ids == {
        "job-fail-oom",
        "job-fail-lic",
        "job-retry-loop",
        "job-idle-queue",
        "job-zombie",
        "job-overrun",
    }
    assert impact["waste_job_count"] == 6
    assert impact["proposed_job_count"] == 6
    assert impact["after_usd"] == 0
    assert impact["recovered_usd"] == impact["before_usd"] == 625.12
    assert impact["recovery_state"] == "full"
    assert impact["open_usd"] == 0
    assert impact["after_label"] == AFTER_LABEL_RECOVERED


def test_hours_to_usd_uses_documented_rates() -> None:
    assert hours_to_usd(1, 1) == CPU_HOUR_USD + GPU_HOUR_USD
