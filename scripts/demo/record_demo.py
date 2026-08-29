#!/usr/bin/env python3
"""Record the hosted CineTrace supervisor against docs/demo/shot-list.md.

System python (Playwright). Reset proposals with the worktree venv, not this
interpreter:

    .venv/bin/python -m cinetrace.clickhouse.reset_proposals
    /usr/bin/python3 scripts/demo/record_demo.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from narration import Beat, beats_to_srt, build_beats, parse_usd

HOST = "https://cinetrace-781071502822.us-central1.run.app"
RECALL_QUERY = "we ran out of graphics memory halfway through"
VIEWPORT = {"width": 1600, "height": 900}
PICK_APPROVE = """
async () => {
  const props = await (await fetch("/api/proposals")).json();
  const jobs = await (await fetch("/api/jobs")).json();
  const list = props.proposals || props || [];
  const jobList = jobs.jobs || jobs || [];
  const byId = Object.fromEntries(jobList.map((j) => [j.job_id, j]));
  const open = list.filter((p) => p.decision === "pending" && byId[p.job_id]?.is_open);
  open.sort((a, b) => (Number(byId[b.job_id]?.waste_usd) || 0) - (Number(byId[a.job_id]?.waste_usd) || 0));
  return open.length ? {job_id: open[0].job_id, waste_usd: byId[open[0].job_id].waste_usd} : null;
}
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def synthesize(beats: list[Beat], audio_dir: Path, edge_tts_bin: str | None) -> list[Path]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, beat in enumerate(beats):
        wav = audio_dir / f"{i:02d}-{beat.key}.wav"
        if edge_tts_bin:
            mp3 = audio_dir / f"{i:02d}-{beat.key}.mp3"
            run(
                [
                    edge_tts_bin,
                    "--voice",
                    "en-US-GuyNeural",
                    "--rate=-5%",
                    "--text",
                    beat.text,
                    "--write-media",
                    str(mp3),
                ]
            )
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(mp3),
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    str(wav),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            run(
                [
                    "espeak-ng",
                    "-v",
                    "en-us",
                    "-s",
                    "138",
                    "-p",
                    "40",
                    "-w",
                    str(wav),
                    beat.text,
                ]
            )
        paths.append(wav)
    return paths


def concat_audio(wavs: list[Path], dest: Path) -> None:
    listing = dest.with_suffix(".txt")
    listing.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs))
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cut_and_mux(
    raw_video: Path,
    wavs: list[Path],
    markers: dict[str, float],
    beats: list[Beat],
    hq: Path,
    preview: Path,
    work: Path,
) -> float:
    work = work / "edit"
    work.mkdir(parents=True, exist_ok=True)
    raw_len = ffprobe_duration(raw_video)
    clips: list[Path] = []
    for i, beat in enumerate(beats):
        duration = ffprobe_duration(wavs[i])
        start = max(0.0, markers[beat.key])
        if start + duration > raw_len:
            start = max(0.0, raw_len - duration - 0.05)
        clip = work / f"{i:02d}-{beat.key}.mp4"
        run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(raw_video),
                "-t",
                f"{duration:.3f}",
                "-vf",
                "scale=1600:900:force_original_aspect_ratio=decrease,pad=1600:900:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-an",
                str(clip),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        clips.append(clip)
    listing = work / "clips.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    silent = work / "picture.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(silent),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    voice = work / "voice.wav"
    concat_audio(wavs, voice)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent),
            "-i",
            str(voice),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(hq),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Keep the Paperclip attach under ~1 MB.
    for scale, crf, fps in (
        ("1280:-2", 34, 24),
        ("960:-2", 36, 24),
        ("854:-2", 42, 18),
        ("720:-2", 44, 16),
    ):
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(hq),
                "-vf",
                f"scale={scale},fps={fps}",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                str(crf),
                "-c:a",
                "aac",
                "-b:a",
                "48k",
                "-ac",
                "1",
                "-movflags",
                "+faststart",
                str(preview),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"preview try scale={scale} crf={crf} -> {preview.stat().st_size} bytes", flush=True)
        if preview.stat().st_size <= 1_000_000:
            break
    return ffprobe_duration(hq)


def read_live(page) -> dict[str, str]:
    page.wait_for_function(
        "() => document.getElementById('shots-at-risk')?.textContent && "
        "document.getElementById('shots-at-risk').textContent !== '—'",
        timeout=30_000,
    )
    page.wait_for_function(
        "() => document.getElementById('scale-samples')?.textContent && "
        "document.getElementById('scale-samples').textContent !== '—'",
        timeout=30_000,
    )
    page.wait_for_selector("#asof-rows tr", timeout=30_000)
    return page.evaluate(
        """() => {
          const text = (id) => (document.getElementById(id)?.innerText || "").trim();
          const row = document.querySelector("#asof-rows tr");
          return {
            shots_at_risk: text("shots-at-risk"),
            shots_recoverable: text("shots-recoverable"),
            slots_stuck: text("slots-stuck"),
            scale_samples: text("scale-samples"),
            scale_jobs: text("scale-jobs"),
            scale_hosts: text("scale-hosts"),
            asof_stats: text("asof-stats"),
            asof_row: row ? row.innerText : "",
            impact_open: text("impact-open"),
            cost_meter: text("cost-meter"),
          };
        }"""
    )


def scroll_to(page, selector: str) -> None:
    page.locator(selector).first.scroll_into_view_if_needed()
    page.wait_for_timeout(450)


def hold(page, seconds: float, pin: str | None = None) -> None:
    remaining = max(0.2, seconds)
    while remaining > 0:
        if pin:
            page.locator(pin).first.scroll_into_view_if_needed()
        step = min(2.0, remaining)
        page.wait_for_timeout(int(step * 1000))
        remaining -= step


def new_page(playwright, video_dir: Path | None):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
    )
    kwargs = {
        "viewport": VIEWPORT,
        "device_scale_factor": 2,
        "color_scheme": "dark",
        "locale": "en-US",
    }
    if video_dir:
        video_dir.mkdir(parents=True, exist_ok=True)
        kwargs["record_video_dir"] = str(video_dir)
        kwargs["record_video_size"] = VIEWPORT
    context = browser.new_context(**kwargs)
    page = context.new_page()
    clock0 = time.monotonic()
    page.goto(HOST, wait_until="load", timeout=60_000)
    page.wait_for_selector("#shots-at-risk", timeout=30_000)
    page.wait_for_function(
        "() => document.getElementById('shots-at-risk')?.textContent !== '—'",
        timeout=45_000,
    )
    page.wait_for_timeout(800)
    return browser, context, page, clock0


def record_take(page, smoke: bool, clock0: float) -> tuple[dict[str, float], dict[str, str]]:
    markers: dict[str, float] = {}

    def mark(key: str) -> None:
        markers[key] = time.monotonic() - clock0
        print(f"mark {key:12s} t={markers[key]:6.1f}s", flush=True)

    live = read_live(page)
    opening = dict(live)
    scroll_to(page, "#dailies")
    mark("hero")
    if not smoke:
        page.click("#run")
        page.wait_for_timeout(250)
        scroll_to(page, "#dailies")
    hold(page, 24, pin="#dailies")

    mark("scale")
    scroll_to(page, "#scale-strip")
    page.locator("#live-pill").hover()
    hold(page, 20, pin="#scale-strip")

    mark("agents")
    scroll_to(page, "#agents")
    if not smoke:
        try:
            page.wait_for_selector("#mcp-calls li", timeout=40_000)
        except Exception:
            print("warn: no MCP row yet; holding on agents anyway", flush=True)
    hold(page, 20, pin="#agents")
    # Keep the SQL list in frame while the run is still writing.
    if page.locator("#mcp-calls li").count() > 0:
        scroll_to(page, "#mcp-evidence")
        hold(page, 16, pin="#mcp-evidence")
    else:
        hold(page, 16, pin="#agents")

    mark("root_cause")
    scroll_to(page, "#root-cause")
    drawer = page.locator("#root-cause details.sql-drop summary")
    if drawer.count():
        drawer.first.click()
    hold(page, 30, pin="#root-cause")

    mark("recall")
    scroll_to(page, "#recall")
    page.fill("#recall-input", "")
    page.type("#recall-input", RECALL_QUERY, delay=35)
    page.click("#recall-form button[type=submit]")
    page.wait_for_selector("#recall-results li.recall-item", timeout=45_000)
    hold(page, 20, pin="#recall")

    if not smoke:
        print("waiting for supervisor run…", flush=True)
        page.wait_for_function(
            """() => {
              const meter = document.getElementById("cost-meter");
              const approve = document.querySelector("button.approve");
              return (meter && !meter.hidden && meter.innerText.trim()) || !!approve;
            }""",
            timeout=180_000,
        )
        # Cost lands at the end of the stream; give the DOM one paint.
        page.wait_for_timeout(800)

    mark("decision")
    scroll_to(page, "#agents")
    decide = page.locator(".timeline-step").filter(has_text="Decide")
    if decide.count():
        decide.last.scroll_into_view_if_needed()
        hold(page, 14, pin="#agents")
    scroll_to(page, "#proposals-section")
    hold(page, 22, pin="#proposals-section")

    mark("approve")
    if not smoke:
        picked = page.evaluate(PICK_APPROVE)
        print(f"approve {picked}", flush=True)
        if not picked:
            raise RuntimeError("no open pending proposal to approve")
        btn = page.locator(f'button.approve[data-job="{picked["job_id"]}"]')
        btn.first.scroll_into_view_if_needed()
        hold(page, 2)
        btn.first.click()
        page.wait_for_function(
            "() => document.getElementById('impact-approved')?.textContent "
            "&& document.getElementById('impact-approved').textContent !== '$0.00'",
            timeout=20_000,
        )
    scroll_to(page, "#impact-row")
    hold(page, 22, pin="#impact-row")

    closing = read_live(page)
    cost_text = page.evaluate("() => (document.getElementById('cost-meter')?.innerText || '')")
    parsed = parse_usd(cost_text)
    # Hero / scale / ASOF must match the opening frame. Approve rewrites those
    # numbers, so only the close beat reads the post-run meters.
    live = opening
    live["cost_meter"] = cost_text
    if parsed is not None:
        live["cost_usd"] = f"{parsed}"
    live["impact_open"] = closing.get("impact_open") or page.evaluate(
        "() => (document.getElementById('impact-open')?.innerText || '').trim()"
    )

    mark("close")
    scroll_to(page, "#run-toolbar")
    hold(page, 10, pin="#run-toolbar")
    scroll_to(page, "#top")
    hold(page, 10, pin="#top")
    return markers, live


def capture(out_dir: Path, smoke: bool) -> tuple[Path, dict[str, float], dict[str, str]]:
    from playwright.sync_api import sync_playwright

    video_dir = out_dir / "raw"
    if video_dir.exists():
        shutil.rmtree(video_dir)
    with sync_playwright() as playwright:
        browser, context, page, clock0 = new_page(playwright, video_dir)
        try:
            markers, live = record_take(page, smoke=smoke, clock0=clock0)
        finally:
            page.close()
            context.close()
            browser.close()
    videos = list(video_dir.glob("*.webm"))
    if not videos:
        raise RuntimeError(f"Playwright wrote no webm under {video_dir}")
    raw = out_dir / "raw-capture.webm"
    shutil.copy2(videos[0], raw)
    return raw, markers, live


def find_edge_tts() -> str | None:
    extra = []
    env_bin = Path(__file__).resolve().parent
    for candidate in (
        Path(sys.executable).resolve().parent / "edge-tts",
        Path("/usr/bin/edge-tts"),
        *[Path(p) / "edge-tts" for p in __import__("os").environ.get("PATH", "").split(":")],
    ):
        extra.append(candidate)
    for candidate in extra:
        if candidate.exists():
            return str(candidate)
    return shutil.which("edge-tts")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="No supervisor run, no approve")
    parser.add_argument("--assemble", action="store_true", help="Mux an existing raw capture")
    parser.add_argument("--work", default="", help="Scratch directory")
    args = parser.parse_args()

    root = repo_root()
    work = Path(args.work) if args.work else root / ".scratch" / "demo-record"
    work.mkdir(parents=True, exist_ok=True)
    hq = root / "docs" / "demo" / "cinetrace-ai-demo.mp4"
    preview = work / "cinetrace-ai-demo-1mb.mp4"
    srt_path = root / "docs" / "demo" / "cinetrace-ai-demo.srt"

    raw = work / "raw-capture.webm"
    capture_meta = work / "capture.json"
    if args.assemble:
        meta = json.loads(capture_meta.read_text())
        markers = meta["markers"]
        live = meta["live"]
        if not raw.exists():
            raise SystemExit(f"missing {raw}")
        print(f"assembling {raw}", flush=True)
    else:
        print(f"capturing {HOST} smoke={args.smoke}", flush=True)
        raw, markers, live = capture(work, smoke=args.smoke)
        capture_meta.write_text(json.dumps({"markers": markers, "live": live}, indent=2) + "\n")
    print("live", json.dumps(live, indent=2), flush=True)
    print("markers", json.dumps(markers, indent=2), flush=True)

    beats = build_beats(live)
    edge = find_edge_tts()
    print(f"tts={'edge-tts' if edge else 'espeak-ng'}", flush=True)
    wavs = synthesize(beats, work / "vo", edge)
    duration = cut_and_mux(raw, wavs, markers, beats, hq, preview, work)
    starts = [0.0]
    for wav in wavs[:-1]:
        starts.append(starts[-1] + ffprobe_duration(wav))
    srt_path.write_text(beats_to_srt(beats, starts))
    (work / "take.json").write_text(
        json.dumps(
            {
                "host": HOST,
                "smoke": args.smoke,
                "duration_s": duration,
                "hq": str(hq),
                "preview": str(preview),
                "preview_bytes": preview.stat().st_size,
                "live": live,
                "markers": markers,
                "beats": [{"key": b.key, "text": b.text, "audio_s": ffprobe_duration(w)} for b, w in zip(beats, wavs)],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"hq {hq} ({hq.stat().st_size} bytes, {duration:.1f}s)", flush=True)
    print(f"preview {preview} ({preview.stat().st_size} bytes)", flush=True)
    print(f"srt {srt_path}", flush=True)
    if duration > 180.5:
        print(f"WARN: cut is {duration:.1f}s; acceptance is ≤180s", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
