"""Voiceover must read live supervisor numbers, not the August script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "demo" / "narration.py"


def load_narration():
    spec = importlib.util.spec_from_file_location("demo_narration", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


n = load_narration()


def test_say_int_covers_hero_counts() -> None:
    assert n.say_int(8) == "eight"
    assert n.say_int(4) == "four"
    assert n.say_int(42) == "forty-two"
    assert n.say_int(240) == "two hundred forty"


def test_say_compact_uses_on_screen_suffix() -> None:
    assert n.say_compact("243.8M") == "243.8 million"
    assert n.say_compact("198.0k") == "198 thousand"
    assert n.say_compact("240") == "240"


def test_asof_parsers_read_the_panel() -> None:
    row = "job-fail-oom NEBULA / sh0040 rnd-b04 97% 61523 / 63400 MB 5s before death 40"
    assert n.parse_asof_gap(row) == "five seconds"
    assert n.parse_vram(row) == "97% VRAM"
    assert n.parse_rows_scanned("scanned 2.1M rows in 137ms · 15.5M rows/s") == "2.1 million rows"


def test_cost_and_impact_close_beat() -> None:
    assert n.say_cents(0.0342) == "about three cents"
    assert n.say_cents(0.041) == "about four cents"
    assert "six thousand" in n.say_money("$6,029.26")
    assert n.parse_usd("This run: $0.0412 of gemini-2.5-flash") == pytest.approx(0.0412)


def test_live_numbers_replace_stale_script() -> None:
    beats = n.build_beats(
        {
            "shots_at_risk": "8",
            "shots_recoverable": "4",
            "slots_stuck": "42",
            "scale_samples": "243.8M",
            "scale_jobs": "198.0k",
            "scale_hosts": "240",
            "asof_stats": "scanned 2.1M rows in 137ms",
            "asof_row": "job-fail-oom NEBULA / sh0040 rnd-b04 97% 5s before death",
            "cost_usd": "0.037",
            "impact_open": "$6,029.26",
        }
    )
    keys = [b.key for b in beats]
    assert keys == [
        "hero",
        "scale",
        "agents",
        "root_cause",
        "recall",
        "decision",
        "approve",
        "close",
    ]
    hero = beats[0].text
    assert "eight shots" in hero
    assert "four recoverable" in hero
    assert "forty-two GPU slots" in hero
    assert "seven" not in hero
    assert "243.8 million" in beats[1].text
    assert "198 thousand" in beats[1].text
    assert "five seconds" in beats[3].text
    assert "97% VRAM" in beats[3].text
    assert "2.1 million rows" in beats[3].text
    assert "about four cents" in beats[-1].text
    assert "six thousand" in beats[-1].text


def test_zero_recoverable_is_not_recordable() -> None:
    live = {
        "shots_at_risk": "2",
        "shots_recoverable": "0",
        "slots_stuck": "42",
    }
    assert n.parse_count("0") == 0
    assert n.parse_count("—") == 0
    assert n.hero_is_recordable(live) is False
    with pytest.raises(n.HeroNotRecordable, match="shots-recoverable is 0"):
        n.require_recordable_hero(live)


def test_nonzero_recoverable_is_recordable() -> None:
    assert n.hero_is_recordable({"shots_recoverable": "4", "shots_at_risk": "8"}) is True
    n.require_recordable_hero({"shots_recoverable": "1", "shots_at_risk": "3"})


def test_srt_follows_measured_sentence_durations_not_even_slices() -> None:
    beat = n.Beat(
        "hero",
        "The problem",
        "Short opener. A much longer second sentence that must not share the first cue's width.",
        20,
    )
    srt = n.beats_to_srt([beat], [0.0], sentence_durations=[[3.2, 7.1]])
    assert "00:00:00,000 --> 00:00:03,200" in srt
    assert "00:00:03,200 --> 00:00:10,300" in srt
    assert "Short opener." in srt
    # Even-slice of the 20s target would have been 10.000 + 10.000.
    assert "00:00:10,000" not in srt


def test_srt_uses_edge_tts_spoken_cues() -> None:
    beat = n.Beat("scale", "scale", "This is two hundred million rows.", 15)
    spoken = [[(0.10, 4.40, "This is two hundred million rows.")]]
    srt = n.beats_to_srt([beat], [20.0], spoken_cues=spoken)
    assert "00:00:20,100 --> 00:00:24,400" in srt
    assert "two hundred million" in srt


def test_dense_cue_is_split_to_readable_rate() -> None:
    text = (
        "And when a proposal claims it protects a shot, that claim is checked "
        "against the delivery board before the row is written — a shot that's "
        "actually on track gets the claim dropped, not recorded."
    )
    assert len(text) / 5.83 > 20
    parts = n.split_dense_text(text, 5.83)
    assert len(parts) >= 2
    assert all(len(part) < len(text) for part in parts)
    cues = n.cues_from_measured([text], [5.83], 0.0)
    assert len(cues) >= 2
    assert max(len(part) for _, _, part in cues) < len(text)
    # Realistic TTS of the same line is ~15 chars/sec and stays one cue.
    comfortable = n.split_dense_text(text, len(text) / 15.0)
    assert comfortable == [text]


def test_parse_srt_cues_reads_edge_tts_output() -> None:
    raw = (
        "1\n"
        "00:00:00,100 --> 00:00:04,405\n"
        "A render farm is the most expensive machine in a studio.\n"
    )
    cues = n.parse_srt_cues(raw)
    assert cues == [
        (0.1, 4.405, "A render farm is the most expensive machine in a studio.")
    ]


def test_speech_units_break_long_sentences() -> None:
    units = n.speech_units(
        "And when a proposal claims it protects a shot, that claim is checked "
        "against the delivery board before the row is written — a shot that's "
        "actually on track gets the claim dropped, not recorded."
    )
    assert len(units) >= 2
    assert all(len(unit) <= n.MAX_CUE_CHARS or " " not in unit for unit in units)


def test_srt_timestamps_are_contiguous() -> None:
    beats = n.build_beats(
        {
            "shots_at_risk": "8",
            "shots_recoverable": "4",
            "slots_stuck": "42",
            "scale_samples": "243.8M",
            "scale_jobs": "198.0k",
            "scale_hosts": "240",
            "asof_stats": "scanned 2.1M rows in 137ms",
            "asof_row": "5s before death 97%",
            "cost_usd": "0.04",
            "impact_open": "$6029",
        }
    )
    starts = [0.0]
    durs: list[list[float]] = []
    for beat in beats:
        units = n.speech_units(beat.text)
        slice_durs = [max(len(unit) / 15.0, 0.8) for unit in units]
        durs.append(slice_durs)
        if beat is not beats[-1]:
            starts.append(starts[-1] + sum(slice_durs))
    srt = n.beats_to_srt(beats, starts, sentence_durations=durs)
    assert srt.startswith("1\n00:00:00,000 -->")
    assert "eight shots" in srt
    last_end = srt.strip().split(" --> ")[-1].split("\n", 1)[0]
    assert last_end.startswith("00:")
