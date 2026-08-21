"""Call the CineTrace agents where they are deployed: Vertex AI Agent Engine.

This is the difference between "we deployed to Agent Engine" and "the product
runs on Agent Engine". The Cloud Run container holds no agent logic on this
path; it authenticates with its service account, streams events back from the
managed runtime, and renders them.

Fails soft on purpose. Anything wrong -- unset id, missing ADC, quota, a cold
engine that exceeds the deadline -- returns no events and a reason, and the
caller runs the identical `root_agent` in process instead. A judge clicking Run
must never see a stack trace because of an IAM propagation delay.
"""

from __future__ import annotations

import asyncio
import os

from cinetrace.env import load_env

DEFAULT_TIMEOUT_S = 180
USER_ID = "supervisor"


def engine_resource_name() -> str:
    """Full reasoningEngines resource path, or empty when not configured."""
    load_env()
    configured = os.getenv("AGENT_ENGINE_ID", "").strip()
    if not configured:
        return ""
    if configured.startswith("projects/"):
        return configured
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
    if not project:
        return ""
    return (
        f"projects/{project}/locations/{location}/reasoningEngines/{configured}"
    )


def _collect_sync(resource_name: str, prompt: str) -> list[dict]:
    """Blocking stream_query. Runs in a worker thread; the SDK is not async."""
    import vertexai
    from vertexai import agent_engines

    vertexai.init(
        project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or None,
    )
    remote_app = agent_engines.get(resource_name)
    return list(remote_app.stream_query(message=prompt, user_id=USER_ID))


async def stream_agent_engine(
    prompt: str, timeout_s: int = DEFAULT_TIMEOUT_S
) -> tuple[list[dict], str]:
    """Return ``(events, reason)``. Empty events means the caller should fall back."""
    resource_name = engine_resource_name()
    if not resource_name:
        return [], "AGENT_ENGINE_ID not set; ran the same agents in process"

    try:
        events = await asyncio.wait_for(
            asyncio.to_thread(_collect_sync, resource_name, prompt),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return [], f"Agent Engine exceeded {timeout_s}s; ran in process instead"
    except Exception as exc:  # noqa: BLE001 - any remote failure must fall back
        return [], f"Agent Engine unavailable ({type(exc).__name__}); ran in process"

    if not events:
        return [], "Agent Engine returned no events; ran in process instead"
    return events, ""
