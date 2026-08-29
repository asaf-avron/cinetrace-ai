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
    for beat in beats[:-1]:
        starts.append(starts[-1] + beat.target_s)
    srt = n.beats_to_srt(beats, starts)
    assert srt.startswith("1\n00:00:00,000 -->")
    assert "eight shots" in srt
    last_end = srt.strip().split(" --> ")[-1].split("\n", 1)[0]
    assert last_end.startswith("00:03:00")
