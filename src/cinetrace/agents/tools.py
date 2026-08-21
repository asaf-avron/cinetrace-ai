"""Python function tools the agents call alongside MCP.

MCP `run_query` is the Sentinel's open-ended path into ClickHouse. These are the
narrow, deterministic reads: a fixed question with a fixed shape, where letting
a model compose the SQL would add latency and variance for no benefit.
"""

from __future__ import annotations

from typing import Any


def find_similar_failures(error_description: str) -> dict[str, Any]:
    """Find past render-farm incidents that resemble this failure, and how they were fixed.

    Matches on meaning, not keywords: the description is embedded with Vertex AI
    and compared against the incident archive in ClickHouse by cosine distance.
    Use it after identifying a failure to check whether the farm has seen this
    before and what closed it last time.

    Args:
        error_description: What went wrong, in plain language. Include the error
            class, renderer and any measurement you have, for example
            "karma job died of OOM on rnd-b04 with VRAM at 97 percent".
    """
    from cinetrace.clickhouse.embeddings import find_similar

    result = find_similar(error_description, limit=4)
    return {
        "query": result["query"],
        "embedding_model": result["model"],
        "matches": [
            {
                "similarity": row["similarity"],
                "error_class": row["error_class"],
                "renderer": row["renderer"],
                "past_incident": row["error_text"],
                "how_it_was_fixed": row["resolution"],
                "times_seen": row["occurrences"],
            }
            for row in result["matches"]
        ],
        "note": (
            "Historical incidents from the archive, ranked by semantic "
            "similarity. Cite the resolution only if the match is close."
        ),
    }


def shots_at_risk_brief() -> dict[str, Any]:
    """Which shots will miss their dailies review, and would freeing stuck GPUs save them.

    Returns the delivery picture the Studio Orchestrator prioritises against:
    each at-risk shot with its show, review time, frames remaining, the hours of
    work still queued ahead of it, and whether releasing the slots currently
    held by zombie and idle-queue jobs would bring it back inside its deadline.
    """
    from cinetrace.clickhouse.queries import fetch_shots_at_risk

    data = fetch_shots_at_risk()
    at_risk = [row for row in data["rows"] if row.get("at_risk")]
    return {
        "at_risk_count": data["at_risk_count"],
        "recoverable_count": data["recoverable_count"],
        "tracked_shots": data["tracked_count"],
        "shots": [
            {
                "show": row["show"],
                "shot": row["shot"],
                "priority": row["priority"],
                "review_at": str(row["review_at"]),
                "hours_to_review": row["hours_to_review"],
                "frames_remaining": row["frames_remaining"],
                "eta_hours_now": row["eta_hours_now"],
                "eta_hours_if_slots_freed": row["eta_hours_recovered"],
                "recoverable": bool(row["recoverable"]),
            }
            for row in at_risk[:12]
        ],
        "note": (
            "recoverable=true means the shot makes its review if the zombie and "
            "idle-queue slots on that show are released now."
        ),
    }
