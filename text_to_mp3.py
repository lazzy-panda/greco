#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end utility: dialogue text → structured JSON → timeline → MP3.

This script reuses the generation heuristics from ``text2playlist_flat_local`` to
produce the nested repetition metadata entirely in memory. It then converts that
structure into the timeline expected by ``build_pimsleur_mp3`` and optionally
synthesises audio with the configured TTS backend.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from text2playlist_flat_local import (
    add_repeat_instruction,
    calculate_speech_time,
    prepare_lines,
    setup_translator,
    tokenize,
    translate_text,
)
import build_pimsleur_mp3 as audio_builder

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
DEFAULT_INPUT_TEXT = INPUT_DIR / "TEXT.txt"
DEFAULT_JSON_PATH = OUTPUT_DIR / "lesson.json"
DEFAULT_TIMELINE_PATH = OUTPUT_DIR / "lesson_timeline.json"
DEFAULT_OUTPUT_AUDIO = OUTPUT_DIR / "lesson.mp3"

try:
    from argostranslate import translate as argos_translate
except Exception:  # pragma: no cover - optional dependency check
    argos_translate = None

try:
    from edge_tts import exceptions as edge_exceptions  # type: ignore
except Exception:  # pragma: no cover - optional dependency check
    edge_exceptions = None

FEMALE_ROLE = "A"
MALE_ROLE = "B"
ENGLISH_ROLE = "Narrator"
ROLE_HINTS = {
    "a": FEMALE_ROLE,
    "α": FEMALE_ROLE,
    "f": FEMALE_ROLE,
    "female": FEMALE_ROLE,
    "ж": FEMALE_ROLE,
    "b": MALE_ROLE,
    "β": MALE_ROLE,
    "m": MALE_ROLE,
    "male": MALE_ROLE,
    "м": MALE_ROLE,
}
ROLE_PREFIX_RE = re.compile(r"^(?P<label>[A-Za-zΑ-Ωα-ω]{1,10})[:：]\s*(?P<body>.+)$")
COMPARE_STRIP_CHARS = " .,!?:;…()[]{}\"'«»“”’—–-·"
GREEK_ARTICLE_BASE_FORMS = {
    "ο",
    "η",
    "το",
    "οι",
    "τα",
    "του",
    "της",
    "των",
    "τον",
    "την",
    "στο",
    "στον",
    "στη",
    "στην",
    "στις",
    "στους",
    "στα",
    "σε",
    "ενας",
    "εναν",
    "ενα",
    "μια",
    "μιαν",
    "μιας",
}


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", value or "") if unicodedata.category(ch) != "Mn")


def normalize_repeat_key(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.strip()
    normalized = normalized.strip(COMPARE_STRIP_CHARS)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def is_article_key(key: str) -> bool:
    if not key:
        return False
    plain = strip_accents(key)
    return plain in GREEK_ARTICLE_BASE_FORMS


def extract_role_hint(text: str) -> tuple[Optional[str], str]:
    if not text:
        return None, text
    match = ROLE_PREFIX_RE.match(text)
    if not match:
        return None, text
    label = match.group("label").strip().casefold()
    role = ROLE_HINTS.get(label)
    if role is None:
        return None, text
    return role, match.group("body").strip()


def normalise_lines(text: str) -> List[str]:
    """Возвращает нормализованный список предложений с учётом точек."""
    return prepare_lines(text)


def build_drill_structure(lines: Iterable[str]) -> Dict[str, object]:
    """Replicate the TEXT.json structure produced by text2playlist_flat_local."""
    sentences_data: List[Dict[str, object]] = []
    used_repeats: set[str] = set()
    used_sentences: set[str] = set()

    for idx, line in enumerate(lines):
        sentence_body = line.lstrip('— ').strip()
        explicit_role, cleaned_sentence = extract_role_hint(sentence_body)
        sentence = cleaned_sentence or sentence_body
        if not sentence:
            continue
        greek_role = explicit_role or (FEMALE_ROLE if (idx % 2 == 0) else MALE_ROLE)
        words_raw = tokenize(sentence)

        words_block = []
        for word in words_raw:
            word_key = normalize_repeat_key(word)
            word_translation = translate_text(word)
            is_first = bool(word_key) and word_key not in used_repeats
            greek_count = 1 if is_article_key(word_key) else (3 if is_first else 1)
            entry = {
                "english": {
                    "text": add_repeat_instruction(word_translation),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(word_translation)),
                },
                "greek": {
                    "text": word,
                    "count": greek_count,
                    "pause": calculate_speech_time(word),
                    "repeat": is_first,
                },
            }
            entry['role'] = greek_role
            words_block.append(entry)
            if word_key:
                used_repeats.add(word_key)

        phrases_block = []
        for phrase_len in range(2, len(words_block) + 1):
            greek_words = [word["greek"]["text"] for word in words_block[:phrase_len]]
            phrase = " ".join(greek_words)
            phrase_key = normalize_repeat_key(phrase)
            phrase_translation = translate_text(phrase)
            is_phrase_first = bool(phrase_key) and phrase_key not in used_repeats
            greek_phrase_count = 3 if is_phrase_first else 1
            entry = {
                "english": {
                    "text": add_repeat_instruction(phrase_translation),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(phrase_translation)),
                },
                "greek": {
                    "text": phrase,
                    "count": greek_phrase_count,
                    "pause": calculate_speech_time(phrase),
                    "repeat": is_phrase_first,
                },
            }
            entry['role'] = greek_role
            phrases_block.append(entry)
            if phrase_key:
                used_repeats.add(phrase_key)

        english_sentence = translate_text(sentence)
        sentence_key = normalize_repeat_key(sentence)
        is_sentence_first = bool(sentence_key) and sentence_key not in used_sentences
        greek_sentence_count = 3 if is_sentence_first else 1
        sentence_entry = {
            "sentence": {
                "english": {
                    "text": add_repeat_instruction(english_sentence),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(english_sentence)),
                },
                "greek": {
                    "text": sentence,
                    "count": greek_sentence_count,
                    "pause": calculate_speech_time(sentence),
                    "repeat": is_sentence_first,
                },
            },
            "words": words_block,
            "phrases": phrases_block,
        }
        sentence_entry['role'] = greek_role
        sentences_data.append(sentence_entry)
        if sentence_key:
            used_sentences.add(sentence_key)
            used_repeats.add(sentence_key)

    combined_sentences: List[Dict[str, object]] = []
    accumulated_sentence = ""
    for sentence_data in sentences_data:
        greek_sentence = sentence_data["sentence"]["greek"]["text"]
        greek_role = sentence_data.get('role', FEMALE_ROLE)
        accumulated_sentence = greek_sentence if not accumulated_sentence else f"{accumulated_sentence} {greek_sentence}"
        combo_key = normalize_repeat_key(accumulated_sentence)
        english_translation = translate_text(accumulated_sentence)
        is_new_combo = bool(combo_key) and combo_key not in used_repeats
        greek_count = 3 if is_new_combo else 1
        combined_entry = {
            "english": {
                "text": add_repeat_instruction(english_translation),
                "count": 1,
                "pause": calculate_speech_time(add_repeat_instruction(english_translation)),
            },
            "greek": {
                "text": accumulated_sentence,
                "count": greek_count,
                "pause": calculate_speech_time(accumulated_sentence),
                "repeat": is_new_combo,
            },
        }
        combined_entry['role'] = greek_role
        combined_sentences.append(combined_entry)
        if combo_key:
            used_repeats.add(combo_key)

    return {
        "data": sentences_data,
        "sentences": combined_sentences,
    }


def add_timeline_entries(
    timeline: List[Dict[str, object]], role: str, text: str, count: int, pause: float
) -> None:
    if not text or count <= 0:
        return
    for idx in range(count):
        timeline.append({"role": role, "text": text})
        if idx < count - 1 and pause > 0:
            timeline.append({"type": "pause", "pause": pause})


def build_timeline(drill_data: Dict[str, object]) -> List[Dict[str, object]]:
    timeline: List[Dict[str, object]] = []
    for sentence_block in drill_data.get("data", []):
        sentence = sentence_block.get("sentence", {})
        greek_role_sentence = sentence_block.get('role', FEMALE_ROLE)
        english = sentence.get("english", {})
        greek = sentence.get("greek", {})
        add_timeline_entries(
            timeline,
            ENGLISH_ROLE,
            str(english.get("text", "")),
            int(english.get("count", 0) or 0),
            float(english.get("pause", 0) or 0.0),
        )
        add_timeline_entries(
            timeline,
            greek_role_sentence,
            str(greek.get("text", "")),
            int(greek.get("count", 0) or 0),
            float(greek.get("pause", 0) or 0.0),
        )

        for word in sentence_block.get("words", []) or []:
            word_role = word.get('role', greek_role_sentence)
            english_word = word.get("english", {})
            greek_word = word.get("greek", {})
            add_timeline_entries(
                timeline,
                ENGLISH_ROLE,
                str(english_word.get("text", "")),
                int(english_word.get("count", 0) or 0),
                float(english_word.get("pause", 0) or 0.0),
            )
            add_timeline_entries(
                timeline,
                word_role,
                str(greek_word.get("text", "")),
                int(greek_word.get("count", 0) or 0),
                float(greek_word.get("pause", 0) or 0.0),
            )

        for phrase in sentence_block.get("phrases", []) or []:
            phrase_role = phrase.get('role', greek_role_sentence)
            english_phrase = phrase.get("english", {})
            greek_phrase = phrase.get("greek", {})
            add_timeline_entries(
                timeline,
                ENGLISH_ROLE,
                str(english_phrase.get("text", "")),
                int(english_phrase.get("count", 0) or 0),
                float(english_phrase.get("pause", 0) or 0.0),
            )
            add_timeline_entries(
                timeline,
                phrase_role,
                str(greek_phrase.get("text", "")),
                int(greek_phrase.get("count", 0) or 0),
                float(greek_phrase.get("pause", 0) or 0.0),
            )

    for combined in drill_data.get("sentences", []) or []:
        combined_role = combined.get('role', FEMALE_ROLE)
        add_timeline_entries(
            timeline,
            ENGLISH_ROLE,
            str(combined.get("english", {}).get("text", "")),
            int(combined.get("english", {}).get("count", 0) or 0),
            float(combined.get("english", {}).get("pause", 0) or 0.0),
        )
        add_timeline_entries(
            timeline,
            combined_role,
            str(combined.get("greek", {}).get("text", "")),
            int(combined.get("greek", {}).get("count", 0) or 0),
            float(combined.get("greek", {}).get("pause", 0) or 0.0),
        )

    return timeline


def synthesise_audio(
    lesson_data: Dict[str, object],
    output_path: Path,
    backend: str,
    voice_map: Optional[str],
    rate: Optional[str],
    volume: float,
    gap: float,
    respect_time: bool,
    pad_to_target: bool,
    narration_prefix: Optional[str],
    log: bool,
) -> None:
    tts = audio_builder.get_tts(backend, rate=rate)
    vmap = audio_builder.load_voice_map(voice_map)

    if lesson_data.get("timeline"):
        song = audio_builder.build_song(
            lesson_data,
            tts,
            vmap,
            volume,
            gap,
            respect_time,
            narration_prefix,
            log,
        )
    else:
        song = audio_builder.fallback_song(
            lesson_data,
            tts,
            vmap,
            volume,
            gap,
            narration_prefix,
        )

    target = (lesson_data.get("lesson") or {}).get("target_duration_sec")
    if pad_to_target and isinstance(target, (int, float)) and target > 0:
        current = len(song) / 1000.0
        if current < target:
            song += audio_builder.silence(target - current)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "mp3" if output_path.suffix.lower() == ".mp3" else "wav"
    if fmt == "mp3":
        song.export(str(output_path), format="mp3", bitrate="192k")
    else:
        song.export(str(output_path), format="wav")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert dialogue text straight to MP3")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(INPUT_DIR),
        help=f"Путь к исходному TXT или директории (по умолчанию: {INPUT_DIR})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_AUDIO),
        help=f"Destination audio file (mp3 or wav). Default: {DEFAULT_OUTPUT_AUDIO}",
    )
    parser.add_argument(
        "--json-out",
        help=f"Path to write the generated JSON structure (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip writing the intermediate JSON file",
    )
    parser.add_argument("--lesson-id", default="lesson-001", help="Lesson identifier")
    parser.add_argument("--lesson-title", default="Greek Drill Lesson", help="Lesson title")
    parser.add_argument("--voice-en", default="en-US-AriaNeural", help="Narrator voice id")
    parser.add_argument("--voice-gr", default="el-GR-AthinaNeural", help="Female Greek voice id for нечётных реплик")
    parser.add_argument("--voice-gr-male", default="el-GR-NestorasNeural", help="Male Greek voice id for чётных реплик")
    parser.add_argument(
        "--backend",
        choices=["edge-tts", "gtts", "pyttsx3"],
        default="edge-tts",
        help="TTS backend for audio synthesis",
    )
    parser.add_argument("--voice-map", help="JSON string or path overriding role→voice mapping")
    parser.add_argument("--rate", help="Rate hint passed to the backend")
    parser.add_argument("--volume", type=float, default=0.0, help="Gain per chunk in dB")
    parser.add_argument("--gap", type=float, default=0.25, help="Silence between chunks (seconds)")
    parser.add_argument(
        "--respect-time",
        action="store_true",
        help="Respect absolute timestamps in the timeline if present",
    )
    parser.add_argument(
        "--no-respect-time",
        dest="respect_time",
        action="store_false",
        help="Ignore absolute timestamps (default)",
    )
    parser.set_defaults(respect_time=False)
    parser.add_argument(
        "--pad-to-target",
        action="store_true",
        help="Pad output to lesson.target_duration_sec if provided",
    )
    parser.add_argument(
        "--no-pad",
        dest="pad_to_target",
        action="store_false",
        help="Do not pad output audio (default)",
    )
    parser.set_defaults(pad_to_target=False)
    parser.add_argument("--narration-prefix", help="Prefix for narrator lines")
    parser.add_argument("--log", action="store_true", default=True, help="Print timeline build logs (default: on)")
    parser.add_argument("--no-log", dest="log", action="store_false", help="Disable timeline build logs")
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Generate JSON/timeline only without synthesising audio",
    )
    parser.add_argument(
        "--force-setup-translator",
        action="store_true",
        help="Always run Argos Translate package installation step",
    )
    return parser.parse_args(argv)


def ensure_translator_available(force: bool = False) -> Optional[bool]:
    """Проверяет наличие языковой пары el->en, при необходимости запускает установку."""
    if argos_translate is None:
        return None
    try:
        installed = argos_translate.get_installed_languages()
    except Exception:
        installed = []
    if not force:
        for lang in installed:
            if getattr(lang, "code", None) == "el":
                if any(getattr(t, "code", None) == "en" for t in getattr(lang, "translation_languages", [])):
                    return True
    if setup_translator():
        return True
    return False

def collect_input_files(base_path: Path) -> List[Path]:
    """Возвращает список входных TXT из файла или директории."""
    if base_path.is_file():
        if base_path.suffix.lower() != ".txt":
            raise SystemExit(f"Поддерживаются только TXT файлы, получен {base_path}")
        return [base_path]
    if base_path.is_dir():
        files = sorted(p for p in base_path.glob("*.txt") if p.is_file())
        if not files:
            raise SystemExit(f"В {base_path} не найдено TXT файлов")
        return files
    raise SystemExit(f"Файл или директория {base_path} не найдены")


def resolve_output_path(
    text_file: Path,
    args_output: Optional[str],
    multiple_inputs: bool,
) -> Path:
    """Определяет путь к выходному аудио, избегая перезаписи."""
    if not multiple_inputs:
        if args_output:
            return Path(args_output)
        return DEFAULT_OUTPUT_AUDIO

    # пакетный режим
    if args_output and args_output != str(DEFAULT_OUTPUT_AUDIO):
        base = Path(args_output)
        if base.suffix.lower() in {".mp3", ".wav"}:
            raise SystemExit("--output должно указывать на директорию при нескольких входных файлах")
        target_dir = base
    else:
        target_dir = OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{text_file.stem}.mp3"


def resolve_json_path(
    text_file: Path,
    args_json_out: Optional[str],
    skip_json: bool,
    multiple_inputs: bool,
) -> Optional[Path]:
    if skip_json:
        return None
    if not multiple_inputs:
        if args_json_out:
            return Path(args_json_out)
        return DEFAULT_JSON_PATH

    if args_json_out and args_json_out != str(DEFAULT_JSON_PATH):
        base = Path(args_json_out)
        if base.suffix.lower() == ".json":
            raise SystemExit("--json-out должно указывать на директорию в пакетном режиме")
        target_dir = base
    else:
        target_dir = OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{text_file.stem}.json"


def process_single_file(
    text_file: Path,
    args: argparse.Namespace,
    multiple_inputs: bool,
) -> None:
    raw_text = text_file.read_text(encoding="utf-8").strip()
    lines = normalise_lines(raw_text)
    if not lines:
        raise SystemExit(f"Файл {text_file} не содержит предложений для обработки")

    drill_data = build_drill_structure(lines)

    json_path = resolve_json_path(text_file, args.json_out, args.no_json, multiple_inputs)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(drill_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON сохранён в {json_path}")

    timeline = build_timeline(drill_data)
    lesson_id = args.lesson_id if not multiple_inputs else f"{args.lesson_id}-{text_file.stem}"
    lesson_title = args.lesson_title if not multiple_inputs else f"{args.lesson_title} ({text_file.stem})"
    lesson_data = {
        "lesson": {
            "id": lesson_id,
            "title": lesson_title,
            "description": "Generated via text_to_mp3",
        },
        "voices": {
            ENGLISH_ROLE: args.voice_en,
            FEMALE_ROLE: args.voice_gr,
            MALE_ROLE: args.voice_gr_male,
        },
        "timeline": timeline,
    }

    print(f"Подготовлено событий: {len(timeline)} для файла {text_file}")

    if args.skip_audio:
        return

    output_path = resolve_output_path(text_file, args.output, multiple_inputs)
    generate_with_fallback_backends(
        lesson_data,
        output_path,
        args,
    )


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)

    base_input = Path(args.input)
    input_files = collect_input_files(base_input)
    multiple_inputs = len(input_files) > 1

    translator_ready = ensure_translator_available(force=args.force_setup_translator)
    if translator_ready is False:
        print("⚠️  Переводчик недоступен. Будут использованы исходные тексты без перевода.")

    for text_file in input_files:
        process_single_file(text_file, args, multiple_inputs)


def backend_sequence(primary: str) -> List[str]:
    order = [primary]
    for candidate in ["edge-tts", "gtts", "pyttsx3"]:
        if candidate not in order:
            order.append(candidate)
    return order


def resolve_backend_rate(backend: str, configured_rate: Optional[str]) -> Optional[str]:
    if configured_rate:
        return configured_rate
    if backend == "edge-tts":
        return "-5%"
    if backend == "pyttsx3":
        return "170"
    return None


def is_install_error(exc: Exception) -> bool:
    msg = str(exc)
    return isinstance(exc, RuntimeError) and "not installed" in msg.lower()


def generate_with_fallback_backends(
    lesson_data: Dict[str, object],
    output_path: Path,
    args: argparse.Namespace,
) -> None:
    last_error: Optional[Exception] = None
    for idx, backend in enumerate(backend_sequence(args.backend)):
        if output_path.exists():
            output_path.unlink()
        try:
            print(f"🔊 Пытаемся озвучить с помощью {backend}...")
            synthesise_audio(
                lesson_data,
                output_path,
                backend=backend,
                voice_map=args.voice_map,
                rate=resolve_backend_rate(backend, args.rate),
                volume=args.volume,
                gap=args.gap,
                respect_time=args.respect_time,
                pad_to_target=args.pad_to_target,
                narration_prefix=args.narration_prefix,
                log=args.log,
            )
            if idx > 0:
                print(f"⚠️  Использован запасной TTS-бэкенд: {backend}")
            print(f"Аудио сохранено в {output_path}")
            return
        except Exception as exc:  # noqa: BLE001 - нам нужен доступ к типу
            last_error = exc
            if edge_exceptions and isinstance(exc, edge_exceptions.NoAudioReceived):
                print("⚠️  Edge TTS вернул пустой ответ. Пробуем другой бэкенд.")
                continue
            if is_install_error(exc):
                print(f"⚠️  Бэкенд {backend} недоступен: {exc}")
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Не удалось синтезировать аудио ни одним бэкендом")


if __name__ == "__main__":
    main()
