"""Build the CIN-7 demo voiceover from live supervisor numbers.

The shot list tells a person to read four beats off the screen. A pre-rendered
TTS track cannot do that, so this module turns the rendered text of those
elements into spoken English that cannot disagree with the frame.
"""

from __future__ import annotations

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


def beats_to_srt(beats: list[Beat], starts: list[float]) -> str:
    cues: list[str] = []
    index = 1
    for beat, start in zip(beats, starts, strict=True):
        sentences = beat.sentences()
        if not sentences:
            continue
        # Spread cues across the beat using the measured audio duration when
        # the next start is known; otherwise use the target length.
        next_starts = starts[starts.index(start) + 1 :] if start in starts else []
        end = next_starts[0] if next_starts else start + beat.target_s
        span = max(end - start, 0.8)
        slice_len = span / len(sentences)
        for i, sentence in enumerate(sentences):
            t0 = start + i * slice_len
            t1 = start + (i + 1) * slice_len
            cues.append(
                f"{index}\n{srt_timestamp(t0)} --> {srt_timestamp(t1)}\n{sentence}\n"
            )
            index += 1
    return "\n".join(cues).rstrip() + "\n"
