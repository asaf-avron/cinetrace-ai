"""Semantic recall over past render failures: Vertex embeddings, ClickHouse search.

The Sentinel can already tell you a job died of OOM. What a senior wrangler adds
is "we saw this on the same card class in March, and the fix was capping
subdivision". That is a similarity question over unstructured text, not a
predicate, so it needs an embedding.

Google Cloud does the embedding (Vertex ``text-embedding-005``), ClickHouse does
the search (``cosineDistance`` over ``Array(Float32)``). Both halves of the
submission stack doing the part they are actually good at.

Corpus is ~500 synthetic-but-plausible incidents built from templates, each with
the resolution that closed it. Embedded once with ``populate()``; queried per
call with ``find_similar()``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from cinetrace.clickhouse.client import get_client
from cinetrace.env import load_env

EMBED_MODEL = "text-embedding-005"
EMBED_DIMS = 768
BATCH_SIZE = 20

HOSTS = [f"rnd-{letter}{n:02d}" for letter in "abcdefgh" for n in (3, 7, 11, 19, 24)]
SHOWS = ["NEBULA", "AURORA", "ORBIT", "DRIFT", "VESPER", "HALCYON"]
CARDS = ["A100 40GB", "A100 80GB", "L4 24GB", "RTX 6000 48GB"]

# (error_text template, resolution). Phrasing deliberately varies inside a class
# so retrieval has to work on meaning rather than shared keywords.
TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "oom": [
        (
            "CUDA out of memory on {host} ({card}) allocating {mb} MiB while "
            "rendering {show} {shot}; VRAM was already at {pct}% before the "
            "allocation",
            "Capped subdivision at level 2 and dropped bucket size to 128. "
            "Job completed on resubmit with peak VRAM at 71%.",
        ),
        (
            "Renderer aborted: device memory exhausted part way through frame "
            "{frame} of {show} {shot} on {host}",
            "Split the frame range across two hosts and enabled out-of-core "
            "textures. No further failures on that sequence.",
        ),
        (
            "{show} {shot} killed by the OOM reaper on {host}; resident set hit "
            "{mb} MiB against a {card} card",
            "Displacement cache was unbounded. Set a 6 GB cache ceiling in the "
            "renderer config and the shot rendered clean.",
        ),
        (
            "Out of GPU memory loading the volumetric grid for {show} {shot}; "
            "host {host} reported {pct}% VRAM in use at failure",
            "Downsampled the VDB to half resolution for beauty passes. "
            "Approved by the sequence supervisor.",
        ),
        (
            "Allocation of {mb} MiB failed on {host}. The scene exceeds what a "
            "{card} can hold with the current texture budget",
            "Moved the shot to the 80GB pool and added a pre-flight VRAM "
            "estimate to the submitter.",
        ),
        (
            "Frame {frame} on {show} {shot} died with a device-side allocation "
            "failure after climbing steadily for 40 minutes on {host}",
            "Memory leak in the custom shader. Patched the plugin; peak VRAM "
            "now flat across the frame range.",
        ),
    ],
    "license": [
        (
            "License checkout failed for {renderer} on {host}: all {seats} "
            "floating seats are checked out",
            "Staggered the submission window and reserved 4 seats for hero "
            "shots during crunch.",
        ),
        (
            "{show} {shot} could not start: the license server refused a "
            "{renderer} token and the job retried {retries} times before failing",
            "License server had stale checkouts from crashed jobs. Added a "
            "reaper that releases tokens after 10 minutes of no heartbeat.",
        ),
        (
            "RLM denied a {renderer} render token to {host}; the pool was "
            "saturated by a batch submission from another show",
            "Introduced per-show license quotas so one submission cannot drain "
            "the pool.",
        ),
        (
            "Job on {show} {shot} exited immediately: no {renderer} seats "
            "available, farm was at {seats}/{seats} in use",
            "Bought 8 additional seats for the delivery window. Queue drained "
            "within the hour.",
        ),
        (
            "Repeated license timeouts on {host} while other hosts acquired "
            "tokens normally",
            "The host had a stale license cache pointing at the retired server. "
            "Re-pointed and rebooted.",
        ),
    ],
    "crash": [
        (
            "{renderer} segfaulted evaluating displacement on {show} {shot}, "
            "frame {frame}, host {host}",
            "Corrupt displacement map in the published asset. Republished from "
            "source and the sequence rendered.",
        ),
        (
            "Renderer terminated with a signal 11 partway through {show} {shot} "
            "on {host}; no core dump was written",
            "Traced to a plugin ABI mismatch after the DCC upgrade. Rebuilt the "
            "plugin against the new SDK.",
        ),
        (
            "Unhandled exception in the shading network for {show} {shot}; the "
            "process died on {host} after {frame} frames",
            "A cyclic reference in the material graph. Fixed the network and "
            "added a validation step at publish.",
        ),
        (
            "Hard crash on {host} rendering {show} {shot}; the same scene "
            "completes on other nodes",
            "Faulty memory on the node. Drained it from the pool and replaced "
            "the DIMM.",
        ),
        (
            "{renderer} aborted with an assertion failure while building the "
            "acceleration structure for {show} {shot}",
            "Degenerate geometry with NaN vertices. Cleaned the mesh on "
            "ingest and added a NaN check.",
        ),
    ],
    "timeout": [
        (
            "Frame {frame} of {show} {shot} exceeded the {hours}h wall clock "
            "limit on {host} and was killed",
            "Raised samples adaptively instead of a flat high count. Frame time "
            "dropped from 7h to 90 minutes.",
        ),
        (
            "{show} {shot} still running after {hours} hours with frames "
            "advancing every 40 minutes; the scheduler reaped it",
            "Ray depth was set to 24 by mistake. Reset to 6 with no visible "
            "difference in the render.",
        ),
        (
            "Job on {host} passed the timeout threshold while the GPU sat at "
            "{pct}% utilisation, suggesting it was blocked rather than busy",
            "The job was stalled on an NFS read of a missing texture. Fixed the "
            "path and added a pre-flight asset check.",
        ),
        (
            "Wall clock limit hit on {show} {shot}: {frame} of the requested "
            "frames finished in {hours} hours",
            "Split the frame range into chunks of 20 so a slow frame no longer "
            "takes the whole job down.",
        ),
        (
            "Render on {host} made no measurable progress for two hours before "
            "the timeout fired",
            "Deadlock in the texture cache under concurrent access. Vendor "
            "patch applied farm-wide.",
        ),
    ],
    "disk": [
        (
            "Write to the frame cache failed on {host}: no space left on device "
            "while saving {show} {shot} frame {frame}",
            "Scratch volume filled with orphaned temp files. Added a nightly "
            "sweep and a 15% free-space alarm.",
        ),
        (
            "{show} {shot} could not flush its EXR output; the local scratch "
            "volume on {host} was full",
            "Increased scratch to 2 TB on the GPU pool and moved deep output "
            "straight to shared storage.",
        ),
        (
            "I/O error writing AOVs for {show} {shot}; the storage target "
            "reported a quota violation",
            "The show hit its project quota mid-delivery. Raised the quota and "
            "added a quota check to the submitter.",
        ),
        (
            "Disk write failure on {host} after {frame} frames; other jobs on "
            "the same volume also stalled",
            "A failing disk in the array degraded the volume. Replaced and "
            "rebuilt overnight.",
        ),
        (
            "Cache write rejected on {host}: the filesystem went read-only "
            "during the render of {show} {shot}",
            "Kernel remounted the volume read-only after an I/O error. Node "
            "drained and the controller firmware updated.",
        ),
    ],
}

RENDERERS = ["karma", "arnold", "redshift", "houdini", "vray"]


def build_corpus() -> list[dict[str, Any]]:
    """Expand the templates into a deterministic set of ~500 past incidents."""
    incidents: list[dict[str, Any]] = []
    counter = 0
    now = datetime.now(timezone.utc)
    for error_class, templates in TEMPLATES.items():
        for template_index, (text_template, resolution) in enumerate(templates):
            for variant in range(19):
                counter += 1
                host = HOSTS[counter % len(HOSTS)]
                show = SHOWS[counter % len(SHOWS)]
                renderer = RENDERERS[(counter + template_index) % len(RENDERERS)]
                text = text_template.format(
                    host=host,
                    show=show,
                    shot=f"sh{100 + (counter * 7) % 400:04d}",
                    renderer=renderer,
                    card=CARDS[counter % len(CARDS)],
                    mb=8192 + (counter * 613) % 65536,
                    pct=82 + counter % 17,
                    frame=1 + (counter * 11) % 400,
                    seats=8 + (counter % 5) * 8,
                    retries=2 + counter % 8,
                    hours=4 + counter % 8,
                )
                incidents.append(
                    {
                        "fingerprint": hashlib.sha1(
                            text.encode("utf-8")
                        ).hexdigest()[:16],
                        "error_class": error_class,
                        "renderer": renderer,
                        "error_text": text,
                        "resolution": resolution,
                        "occurrences": 1 + (counter * 3) % 24,
                        "last_seen": now - timedelta(hours=6 + (counter * 13) % 2000),
                    }
                )
    return incidents


def _genai_client():
    load_env()
    from google import genai

    return genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or None,
    )


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Embed with Vertex AI. task_type matters: documents and queries differ."""
    from google.genai import types

    client = _genai_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = client.models.embed_content(
            model=EMBED_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBED_DIMS,
            ),
        )
        vectors.extend([list(item.values) for item in response.embeddings])
    return vectors


SIMILAR = """
SELECT
    error_class,
    renderer,
    error_text,
    resolution,
    occurrences,
    last_seen,
    round(cosineDistance(embedding, {vec:Array(Float32)}), 4) AS distance,
    round(1 - cosineDistance(embedding, {vec:Array(Float32)}), 4) AS similarity
FROM error_embeddings
ORDER BY distance ASC
LIMIT {limit:UInt32}
"""


def find_similar(error_text: str, limit: int = 5) -> dict[str, Any]:
    """Nearest historical incidents to a free-text error description."""
    from cinetrace.clickhouse.queries import run_with_stats

    vector = embed_texts([error_text], task_type="RETRIEVAL_QUERY")[0]
    client = get_client()
    try:
        rows, _cols, stats = run_with_stats(
            client, SIMILAR, {"vec": vector, "limit": limit}
        )
    finally:
        client.close()
    return {
        "query": error_text,
        "model": EMBED_MODEL,
        "dims": EMBED_DIMS,
        "matches": rows,
        "sql": SIMILAR.strip(),
        "stats": stats,
    }


def populate() -> int:
    """Embed the corpus and load it. Idempotent: truncates first."""
    incidents = build_corpus()
    vectors = embed_texts([row["error_text"] for row in incidents])
    client = get_client()
    try:
        client.command("TRUNCATE TABLE IF EXISTS error_embeddings")
        client.insert(
            "error_embeddings",
            [
                [
                    row["fingerprint"],
                    row["error_class"],
                    row["renderer"],
                    row["error_text"],
                    row["resolution"],
                    row["occurrences"],
                    row["last_seen"].replace(tzinfo=None),
                    vector,
                ]
                for row, vector in zip(incidents, vectors)
            ],
            column_names=[
                "fingerprint",
                "error_class",
                "renderer",
                "error_text",
                "resolution",
                "occurrences",
                "last_seen",
                "embedding",
            ],
        )
    finally:
        client.close()
    return len(incidents)


def main() -> None:
    count = populate()
    print(f"Embedded and loaded {count} historical incidents with {EMBED_MODEL}.")


if __name__ == "__main__":
    main()
