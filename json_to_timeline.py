#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert structured drill data (TEXT.json) into a Pimsleur-style timeline JSON.

The output mirrors the event ordering used by text2playlist_flat_local.py when
building OUTPUT.txt: sentence-level lines first, then per-word drills, then
phrases. Repetition counts and pauses are preserved so downstream audio
renderers can honour the same speaking cadence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

OUTPUT_DIR = Path("output")
DEFAULT_JSON_INPUT = OUTPUT_DIR / "lesson.json"
DEFAULT_TIMELINE_OUTPUT = OUTPUT_DIR / "lesson_timeline.json"

FEMALE_ROLE = "A"
MALE_ROLE = "B"
ENGLISH_ROLE = "Narrator"


def add_timeline_entries(
    timeline: List[Dict[str, object]],
    role: str,
    text: str,
    count: int,
    pause: float,
) -> None:
    """Append repeated text events and interleaving pauses to the timeline."""
    if not text:
        return
    for repeat_idx in range(count):
        timeline.append({"role": role, "text": text})
        if repeat_idx < count - 1 and pause > 0:
            timeline.append({"type": "pause", "pause": pause})


def process_component(
    timeline: List[Dict[str, object]],
    component: Dict[str, Dict[str, object]],
    fallback_role: str,
) -> None:
    """Emit english then greek entries for a sentence/word/phrase object."""
    english = component.get("english") or {}
    greek = component.get("greek") or {}
    role = component.get("role") or fallback_role or FEMALE_ROLE
    add_timeline_entries(
        timeline,
        ENGLISH_ROLE,
        str(english.get("text", "")),
        int(english.get("count", 0) or 0),
        float(english.get("pause", 0) or 0.0),
    )
    add_timeline_entries(
        timeline,
        role,
        str(greek.get("text", "")),
        int(greek.get("count", 0) or 0),
        float(greek.get("pause", 0) or 0.0),
    )


def build_timeline(data: Dict[str, object]) -> List[Dict[str, object]]:
    timeline: List[Dict[str, object]] = []
    sentence_counter = 0
    for sentence_data in data.get("data", []):
        sentence_counter += 1
        sentence_role = sentence_data.get("role")
        if not sentence_role:
            sentence_role = FEMALE_ROLE if sentence_counter % 2 == 1 else MALE_ROLE
        sentence = sentence_data.get("sentence") or {}
        process_component(timeline, sentence, sentence_role)

        for word_obj in sentence_data.get("words", []) or []:
            process_component(timeline, word_obj, sentence_role)

        for phrase_obj in sentence_data.get("phrases", []) or []:
            process_component(timeline, phrase_obj, sentence_role)

    # Optionally append combined sentences if present
    for combined_obj in data.get("sentences", []) or []:
        role = combined_obj.get("role") or FEMALE_ROLE
        process_component(
            timeline,
            {"english": combined_obj.get("english", {}), "greek": combined_obj.get("greek", {}), "role": role},
            role,
        )

    return timeline


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Convert TEXT.json into timeline JSON")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_JSON_INPUT),
        help=f"Path to the structured drill JSON file (default: {DEFAULT_JSON_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_TIMELINE_OUTPUT),
        help=f"Where to write the timeline JSON (default: {DEFAULT_TIMELINE_OUTPUT})",
    )
    parser.add_argument(
        "--lesson-id",
        default="lesson-001",
        help="Identifier to embed in the lesson metadata",
    )
    parser.add_argument(
        "--lesson-title",
        default="Greek Drill Lesson",
        help="Human-readable title for the lesson",
    )
    parser.add_argument(
        "--voice-en",
        default="en-US-AriaNeural",
        help="Narrator voice identifier",
    )
    parser.add_argument(
        "--voice-gr",
        default="el-GR-AthinaNeural",
        help="Female Greek voice identifier (odd sentences)",
    )
    parser.add_argument(
        "--voice-gr-male",
        default="el-GR-NestorasNeural",
        help="Male Greek voice identifier (even sentences)",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file {input_path} not found")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    timeline = build_timeline(data)

    lesson = {
        "lesson": {
            "id": args.lesson_id,
            "title": args.lesson_title,
            "description": "Auto-generated from TEXT.json",
        },
        "voices": {
            ENGLISH_ROLE: args.voice_en,
            FEMALE_ROLE: args.voice_gr,
            MALE_ROLE: args.voice_gr_male,
        },
        "timeline": timeline,
        "export": {
            "filename": f"{args.lesson_id}.mp3",
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(lesson, f, ensure_ascii=False, indent=2)

    print(f"Timeline with {len(timeline)} events saved to {output_path}")


if __name__ == "__main__":
    main()
