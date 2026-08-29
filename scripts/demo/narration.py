"""Build the CIN-7 demo voiceover from live supervisor numbers.

The shot list tells a person to read four beats off the screen. A pre-rendered
TTS track cannot do that, so this module turns the rendered text of those
elements into spoken English that cannot disagree with the frame.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

# Comfortable caption reading is ~15–20 characters/sec. Anything denser is split.
MAX_CUE_CHARS_PER_SEC = 20.0
MAX_CUE_CHARS = 90
SRT_TS = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
CLAUSE_SPLIT = re.compile(r"(?<=[,;:—–])\s+")


@dataclass(frozen=True)
class Beat:
    key: str
    title: str
    text: str
    target_s: float
    cue_lines: list[str] = field(default_factory=list)

    def sentences(self) -> list[str]:
        if self.cue_lines:
            return list(self.cue_lines)
        parts = re.split(r"(?<=[.!?])\s+", self.text.strip())
        return [p.strip() for p in parts if p.strip()]


def say_int(value: int) -> str:
    n = int(value)
    if n < 0:
        return f"negative {say_int(-n)}"
    if n < 20:
        return ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return TENS[tens] if ones == 0 else f"{TENS[tens]}-{ONES[ones]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = f"{ONES[hundreds]} hundred"
        return head if rest == 0 else f"{head} {say_int(rest)}"
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = f"{say_int(thousands)} thousand"
        return head if rest == 0 else f"{head} {say_int(rest)}"
    if n < 1_000_000_000:
        millions, rest = divmod(n, 1_000_000)
        head = f"{say_int(millions)} million"
        return head if rest == 0 else f"{head} {say_int(rest)}"
    billions, rest = divmod(n, 1_000_000_000)
    head = f"{say_int(billions)} billion"
    return head if rest == 0 else f"{head} {say_int(rest)}"


def say_compact(text: str) -> str:
    raw = (text or "").strip().replace(",", "")
    if not raw or raw == "—":
        return "unknown"
    match = re.fullmatch(r"(-?[\d.]+)\s*([kKmMbB])", raw)
    if match:
        number = match.group(1)
        suffix = match.group(2).lower()
        unit = {"k": "thousand", "m": "million", "b": "billion"}[suffix]
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        return f"{number} {unit}"
    if re.fullmatch(r"-?[\d.]+", raw):
        if "." in raw:
            return raw.rstrip("0").rstrip(".")
        return f"{int(raw):,}"
    return raw


def say_money(text: str) -> str:
    raw = (text or "").strip()
    match = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kKmMbB])?", raw)
    if not match:
        return raw or "the open waste"
    amount = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    if suffix == "m":
        amount *= 1_000_000
    elif suffix == "k":
        amount *= 1_000
    elif suffix == "b":
        amount *= 1_000_000_000
    whole = int(round(amount))
    if whole >= 1000:
        return f"{say_int(whole)} dollars"
    return f"{say_int(whole)} dollars"


def say_cents(usd: float) -> str:
    cents = int(round(float(usd) * 100))
    if cents <= 0:
        return "less than a cent"
    if cents == 1:
        return "about one cent"
    return f"about {say_int(cents)} cents"


def parse_usd(text: str) -> float | None:
    match = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", text or "")
    if not match:
        return None
    return float(match.group(1))


def parse_asof_gap(row_text: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?\s+before death", row_text or "", re.I)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*s\b", row_text or "")
    if not match:
        return "a few seconds"
    seconds = float(match.group(1))
    whole = int(round(seconds))
    if whole == 1:
        return "one second"
    return f"{say_int(whole)} seconds"


def parse_vram(row_text: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", row_text or "")
    if not match:
        return "peak VRAM"
    value = match.group(1).rstrip("0").rstrip(".") if "." in match.group(1) else match.group(1)
    return f"{value}% VRAM"


def parse_rows_scanned(stats_text: str) -> str:
    match = re.search(r"scanned\s+([0-9.]+[kKmMbB]?)\s+rows", stats_text or "", re.I)
    if not match:
        return "millions of rows"
    spoken = say_compact(match.group(1))
    return f"{spoken} rows"


def parse_count(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits or "0")


class HeroNotRecordable(RuntimeError):
    """Refuse a take whose opening line concedes the product does not recover reviews."""


def hero_is_recordable(live: dict[str, str]) -> bool:
    """The hero is only filmable when freeing slots would save at least one shot."""
    return parse_count(live.get("shots_recoverable", "")) > 0


def require_recordable_hero(live: dict[str, str]) -> None:
    recoverable = parse_count(live.get("shots_recoverable", ""))
    at_risk = parse_count(live.get("shots_at_risk", ""))
    if recoverable <= 0:
        raise HeroNotRecordable(
            f"shots-recoverable is {recoverable} (at-risk {at_risk}); "
            "do not roll until freeing slots would save at least one review"
        )


def build_beats(live: dict[str, str]) -> list[Beat]:
    at_risk = say_int(int(re.sub(r"[^\d]", "", live["shots_at_risk"]) or "0"))
    recoverable = say_int(int(re.sub(r"[^\d]", "", live["shots_recoverable"]) or "0"))
    slots = say_int(int(re.sub(r"[^\d]", "", live["slots_stuck"]) or "0"))
    samples = say_compact(live["scale_samples"])
    jobs = say_compact(live["scale_jobs"])
    hosts = say_compact(live["scale_hosts"])
    gap = parse_asof_gap(live.get("asof_row", ""))
    vram = parse_vram(live.get("asof_row", ""))
    rows = parse_rows_scanned(live.get("asof_stats", ""))
    cost = live.get("cost_usd")
    cents = say_cents(float(cost)) if cost not in (None, "") else "a few cents"
    impact = say_money(live.get("impact_open", ""))

    return [
        Beat(
            "hero",
            "The problem, stated as delivery",
            (
                "A render farm is the most expensive machine in a studio, "
                "and nobody watches it in real time. "
                "When a job hangs overnight on eight GPUs, the cost isn't the compute. "
                f"It's the {at_risk} shots that miss the 9am review — "
                f"{recoverable} recoverable by freeing slots, "
                f"{slots} GPU slots held by zombie and idle-queue jobs."
            ),
            20,
        ),
        Beat(
            "scale",
            "The scale, briefly",
            (
                f"This is {samples} rows of frame-level telemetry in ClickHouse. "
                f"{jobs} jobs, {hosts} hosts, and it's still being written to while we watch."
            ),
            15,
        ),
        Beat(
            "agents",
            "The agents, and the SQL they write live",
            (
                "Three Gemini agents on Google Cloud ADK. "
                "The Sentinel isn't given queries — it's given the schema and a goal, "
                "and it writes its own SQL through the official ClickHouse MCP server. "
                f"You're watching it compose those against {samples} rows, live. "
                "None of them are in our repo."
            ),
            30,
        ),
        Beat(
            "root_cause",
            "Root cause",
            (
                "When it finds an out-of-memory failure it runs an ASOF join — "
                "the last telemetry sample before the job died. "
                f"This one died {gap} after the host hit {vram}. "
                f"{rows} touched, and the panel tells you exactly what it cost. "
                "Almost nothing else lets you ask a database for the row just before "
                "a moment in a single join — anywhere else that's a window function "
                "or a correlated subquery."
            ),
            25,
        ),
        Beat(
            "recall",
            "Institutional memory",
            (
                "Error text is embedded with Vertex AI and searched by cosine "
                "distance in ClickHouse. It matches meaning, not keywords — "
                "so it finds the ticket from March and the fix that closed it."
            ),
            20,
        ),
        Beat(
            "decision",
            "The decision, tied to a deadline",
            (
                "The Orchestrator weighs findings against the dailies schedule. "
                "A zombie on a show with a review in five hours beats a bigger overrun due tomorrow. "
                "And when a proposal claims it protects a shot, that claim is checked "
                "against the delivery board before the row is written — a shot that's "
                "actually on track gets the claim dropped, not recorded. "
                "The agent doesn't get to mark its own homework."
            ),
            30,
        ),
        Beat(
            "approve",
            "Approval is the product",
            (
                "Nothing has touched a render host. A proposal is a record, and the number "
                "only moves when a human approves it — because an agent finding waste "
                "doesn't reduce your bill. A supervisor approving the fix does."
            ),
            25,
        ),
        Beat(
            "close",
            "Close",
            (
                "Gemini, Google Cloud ADK, ClickHouse through MCP. "
                f"This run cost {cents} and found {impact} of capacity that's burning "
                "right now — and the reviews it was about to cost."
            ),
            15,
        ),
    ]


def srt_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _hms_to_seconds(match: re.Match[str], offset: int) -> float:
    hours = int(match.group(offset))
    minutes = int(match.group(offset + 1))
    seconds = int(match.group(offset + 2))
    millis = int(match.group(offset + 3))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def parse_srt_cues(text: str) -> list[tuple[float, float, str]]:
    """Parse SRT or SRT-shaped VTT from edge-tts `--write-subtitles`."""
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\n\s*\n", (text or "").strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() and ln.strip() != "WEBVTT"]
        if not lines:
            continue
        stamp = next((ln for ln in lines if SRT_TS.search(ln)), "")
        match = SRT_TS.search(stamp)
        if not match:
            continue
        t0 = _hms_to_seconds(match, 1)
        t1 = _hms_to_seconds(match, 5)
        content_lines = []
        seen_stamp = False
        for ln in lines:
            if not seen_stamp:
                if SRT_TS.search(ln):
                    seen_stamp = True
                continue
            content_lines.append(ln.strip())
        content = " ".join(content_lines).strip()
        if content:
            cues.append((t0, t1, content))
    return cues


def speech_units(text: str, max_chars: int = MAX_CUE_CHARS) -> list[str]:
    """Split narration into speakable cues before TTS, so timings stay real."""
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    units: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            units.append(sentence)
            continue
        clauses = [c.strip() for c in CLAUSE_SPLIT.split(sentence) if c.strip()]
        if len(clauses) == 1:
            words = sentence.split()
            buf: list[str] = []
            for word in words:
                trial = (" ".join(buf + [word])).strip()
                if buf and len(trial) > max_chars:
                    units.append(" ".join(buf))
                    buf = [word]
                else:
                    buf.append(word)
            if buf:
                units.append(" ".join(buf))
            continue
        buf_text = ""
        for clause in clauses:
            trial = f"{buf_text} {clause}".strip() if buf_text else clause
            if buf_text and len(trial) > max_chars:
                units.append(buf_text)
                buf_text = clause
            else:
                buf_text = trial
        if buf_text:
            units.append(buf_text)
    return units


def _pack_sequential(parts: list[str], n: int) -> list[str]:
    if n <= 1 or len(parts) <= 1:
        return [" ".join(parts)] if parts else []
    total = sum(len(part) for part in parts) or 1
    target = total / n
    groups: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for i, part in enumerate(parts):
        trial_len = buf_len + len(part) + (1 if buf else 0)
        groups_left = n - len(groups)
        parts_after = len(parts) - i - 1
        if (
            buf
            and trial_len > target
            and groups_left > 1
            and parts_after >= groups_left - 2
        ):
            groups.append(" ".join(buf))
            buf = [part]
            buf_len = len(part)
        else:
            buf.append(part)
            buf_len = trial_len
    if buf:
        groups.append(" ".join(buf))
    return groups


def split_dense_text(
    text: str, duration_s: float, max_cps: float = MAX_CUE_CHARS_PER_SEC
) -> list[str]:
    """Split a wall-of-text cue so each caption is shorter.

    Proportional time keeps the same characters/sec — this is about not
    putting 185 characters on screen at once. Per-sentence TTS is what
    actually lands a comfortable reading rate.
    """
    text = (text or "").strip()
    if not text:
        return []
    if duration_s <= 0 or len(text) / duration_s <= max_cps:
        return [text]
    needed = max(2, int(math.ceil(len(text) / (max_cps * duration_s))))
    clauses = [c.strip() for c in CLAUSE_SPLIT.split(text) if c.strip()]
    parts = clauses if len(clauses) >= 2 else text.split()
    if len(parts) < 2:
        return [text]
    groups = _pack_sequential(parts, min(needed, len(parts)))
    return groups if len(groups) >= 2 else [text]


def cues_from_measured(
    sentences: list[str],
    durations: list[float],
    start: float = 0.0,
    max_cps: float = MAX_CUE_CHARS_PER_SEC,
) -> list[tuple[float, float, str]]:
    """Build cues from measured clip durations, splitting anything over max_cps."""
    cues: list[tuple[float, float, str]] = []
    cursor = start
    for sentence, duration in zip(sentences, durations, strict=True):
        parts = split_dense_text(sentence, duration, max_cps)
        if not parts:
            cursor += max(duration, 0.0)
            continue
        total_chars = sum(len(part) for part in parts) or 1
        inner = cursor
        for part in parts:
            slice_len = max(duration, 0.0) * (len(part) / total_chars)
            cues.append((inner, inner + slice_len, part))
            inner += slice_len
        cursor += max(duration, 0.0)
    return cues


def format_srt(cues: list[tuple[float, float, str]]) -> str:
    lines: list[str] = []
    for index, (t0, t1, text) in enumerate(cues, start=1):
        if t1 <= t0:
            t1 = t0 + 0.4
        lines.append(f"{index}\n{srt_timestamp(t0)} --> {srt_timestamp(t1)}\n{text}\n")
    return "\n".join(lines).rstrip() + "\n"


def beats_to_srt(
    beats: list[Beat],
    starts: list[float],
    sentence_durations: list[list[float]] | None = None,
    spoken_cues: list[list[tuple[float, float, str]]] | None = None,
    max_cps: float = MAX_CUE_CHARS_PER_SEC,
) -> str:
    """Build captions from speech timings, not even slices of a beat span.

    Preferred: ``spoken_cues`` from edge-tts ``--write-subtitles`` (already
    relative to each beat start). Next: ``sentence_durations`` measured from
    per-sentence audio. Last resort: the beat target length.
    """
    cues: list[tuple[float, float, str]] = []
    for i, (beat, start) in enumerate(zip(beats, starts, strict=True)):
        if spoken_cues is not None:
            for t0, t1, text in spoken_cues[i]:
                cues.extend(
                    cues_from_measured([text], [max(t1 - t0, 0.4)], start + t0, max_cps)
                )
            continue
        sentences = speech_units(beat.text) if not beat.cue_lines else list(beat.cue_lines)
        if not sentences:
            continue
        if sentence_durations is not None:
            cues.extend(cues_from_measured(sentences, sentence_durations[i], start, max_cps))
            continue
        next_starts = starts[i + 1 :]
        end = next_starts[0] if next_starts else start + beat.target_s
        span = max(end - start, 0.8)
        # No measured audio: still refuse even slices when a sentence is dense.
        # Weight by character count so a long closer is not the same width as
        # a short opener.
        total_chars = sum(len(s) for s in sentences) or 1
        cursor = start
        for sentence in sentences:
            slice_len = span * (len(sentence) / total_chars)
            cues.extend(cues_from_measured([sentence], [slice_len], cursor, max_cps))
            cursor += slice_len
    return format_srt(cues)
