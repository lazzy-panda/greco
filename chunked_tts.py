#!/usr/bin/env python3
"""Convert a text file into chunked MP3 narration using Edge TTS."""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from typing import Iterable, List

import edge_tts

SENTENCES_PER_CHUNK = 50
VOICE = "en-US-AriaNeural"
RATE = "+0%"
VOLUME = "+0%"
OUTPUT_DIR = Path("output")


def split_sentences(text: str) -> List[str]:
    """Split text into sentences using simple punctuation heuristics."""
    normalized = text.replace("\n", " ").strip()
    if not normalized:
        return []
    pieces = re.split(r"(?<=[.!?…])\s+", normalized)
    return [piece.strip() for piece in pieces if piece.strip()]


def chunk(items: Iterable[str], chunk_size: int) -> List[List[str]]:
    """Group items into lists with at most chunk_size elements."""
    block: List[str] = []
    chunks: List[List[str]] = []
    for item in items:
        block.append(item)
        if len(block) == chunk_size:
            chunks.append(block)
            block = []
    if block:
        chunks.append(block)
    return chunks


async def synthesize_mp3(text: str, mp3_path: Path) -> None:
    communicate = edge_tts.Communicate(text=text, voice=VOICE, rate=RATE, volume=VOLUME)
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    with mp3_path.open("wb") as output_file:
        async for message in communicate.stream():
            if message["type"] == "audio":
                output_file.write(message["data"])


async def process_chunks(sentences: List[str]) -> None:
    batches = chunk(sentences, SENTENCES_PER_CHUNK)
    if not batches:
        raise ValueError("Input text does not contain any sentences after parsing.")

    for index, batch in enumerate(batches, start=1):
        joined_text = " ".join(batch)
        mp3_path = OUTPUT_DIR / f"chunk_{index:02d}.mp3"
        print(f"Генерируется {mp3_path}...")
        await synthesize_mp3(joined_text, mp3_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk text into 50-sentence MP3 files.")
    parser.add_argument("text_file", type=Path, help="Путь к исходному текстовому файлу")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    text_content = args.text_file.read_text(encoding="utf-8")
    sentences = split_sentences(text_content)
    await process_chunks(sentences)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
