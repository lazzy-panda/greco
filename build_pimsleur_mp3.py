#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pimsleur_mp3.py — JSON → единый MP3/WAV для юнитов по алгоритму Пимслера.

Особенности:
- Поддержка TTS: edge-tts (рекоменд.), gTTS, pyttsx3 (офлайн).
- Учитывает абсолютные метки времени event["time"] ("95s", "1:35", "00:01:35") → вставляет тишину до этой отметки.
- Уникальные temp-файлы для каждого куска (фикс «тихих» сегментов).
- --voice-map перекрывает JSON/voices; безопасный запуск edge-tts c asyncio.run().
- --pad-to-target дополняет тишину до lesson.target_duration_sec (если задан).

Установка:
    pip install pydub
    pip install edge-tts     # или gTTS / pyttsx3 по желанию
    # + ffmpeg в системе

Примеры:
    python build_pimsleur_mp3.py unit-001.json -o unit-001.mp3 \
      --backend edge-tts \
      --voice-map '{"Narrator":"ru-RU-SvetlanaNeural","A":"el-GR-AthinaNeural","B":"el-GR-NestorasNeural","C":"el-GR-AthinaNeural"}' \
      --rate "+0%" --log
"""
import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from pydub import AudioSegment

OUTPUT_DIR = Path("output")
DEFAULT_TIMELINE_PATH = OUTPUT_DIR / "lesson_timeline.json"
DEFAULT_AUDIO_PATH = OUTPUT_DIR / "lesson.mp3"

GREEK_ROLES = {"A", "B"}
GREEK_PRONUN_FIXES = {
    "Όχι": "όχι",
    "Οχι": "όχι",
    "ΟΧΙ": "όχι",
    "οχι": "όχι",
}
UPPER_TONOS_TO_LOWER = {
    "Ά": "ά",
    "Έ": "έ",
    "Ή": "ή",
    "Ί": "ί",
    "Ό": "ό",
    "Ύ": "ύ",
    "Ώ": "ώ",
    "Ϊ": "ϊ",
    "Ϋ": "ϋ",
}

# ----------------- Utils -----------------
def parse_timecode(val: str) -> float:
    """'95s' | '95' | 'M:SS' | 'H:MM:SS' -> seconds float"""
    s = val.strip()
    if re.fullmatch(r"\d+(\.\d+)?s", s):
        return float(s[:-1])
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s):
        parts = [float(x) for x in s.split(":")]
        if len(parts) == 2:  # M:SS
            m, sec = parts
            return m * 60 + sec
        if len(parts) == 3:  # H:MM:SS
            h, m, sec = parts
            return h * 3600 + m * 60 + sec
    raise ValueError(f"Bad time format: {val!r}")

def parse_secs(x: Any) -> float:
    if x is None: return 0.0
    if isinstance(x, (int, float)): return float(x)
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*$", str(x))
    if m: return float(m.group(1))
    raise ValueError(f"Expected seconds, got: {x!r}")

def silence(seconds: float) -> AudioSegment:
    ms = max(0, int(seconds * 1000))
    return AudioSegment.silent(duration=ms)

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_voice_map(val: Optional[str]) -> Dict[str, str]:
    if not val:
        return {}
    if os.path.exists(val) and os.path.isfile(val):
        with open(val, "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        return json.loads(val)
    except Exception:
        print("WARN: --voice-map is not valid JSON; ignored.", file=sys.stderr)
        return {}

def is_greek(text: str) -> bool:
    return bool(re.search(r"[Α-Ωα-ωάέίόήύώϊΐϋΰ]", text))


def lowercase_initial_tonos(text: str) -> str:
    if not text:
        return text
    result: List[str] = []
    prev_is_letter = False
    for ch in text:
        is_letter = ch.isalpha()
        if is_letter and not prev_is_letter and ch in UPPER_TONOS_TO_LOWER:
            result.append(UPPER_TONOS_TO_LOWER[ch])
        else:
            result.append(ch)
        prev_is_letter = is_letter
        if not is_letter:
            prev_is_letter = False
    return "".join(result)


def apply_greek_pronunciation_fixes(text: str) -> str:
    if not text:
        return text
    fixed = lowercase_initial_tonos(text)
    for src, dst in GREEK_PRONUN_FIXES.items():
        fixed = fixed.replace(src, dst)
    return fixed

# -------------- TTS backends --------------
class TTSBase:
    def __init__(self, rate=None):
        self.rate = rate  # string or int depending on backend

    def synth(self, text: str, voice_hint: Optional[str], tmpdir: str) -> AudioSegment:
        raise NotImplementedError

class TTS_Edge(TTSBase):
    """edge-tts: лучшие голоса, безопасный asyncio.run()."""
    def __init__(self, rate=None):
        super().__init__(rate)
        try:
            import edge_tts  # noqa: F401
        except Exception as e:
            raise RuntimeError("edge-tts not installed. pip install edge-tts") from e
        self.edge_tts = __import__("edge_tts")
        import asyncio
        self.asyncio = asyncio

    def _default_voice(self, text: str) -> str:
        # разумные дефолты
        return "el-GR-AthinaNeural" if is_greek(text) else "ru-RU-SvetlanaNeural"

    async def _synth_async(self, text: str, voice: str, out_path: str):
        communicate = self.edge_tts.Communicate(text, voice, rate=self.rate or "+0%")
        await communicate.save(out_path)

    def synth(self, text: str, voice_hint: Optional[str], tmpdir: str) -> AudioSegment:
        if not text.strip():
            return silence(0.0)
        out_path = os.path.join(tmpdir, f"chunk-{uuid.uuid4().hex}.mp3")
        voice = voice_hint or self._default_voice(text)
        # Пытаемся озвучить c указанным голосом; на ошибке — откатываемся к дефолту
        try:
            self.asyncio.run(self._synth_async(text, voice, out_path))
        except Exception:
            fallback = self._default_voice(text)
            self.asyncio.run(self._synth_async(text, fallback, out_path))
        return AudioSegment.from_file(out_path)

class TTS_gTTS(TTSBase):
    def __init__(self, rate=None):
        super().__init__(rate)
        try:
            from gtts import gTTS  # noqa: F401
        except Exception as e:
            raise RuntimeError("gTTS not installed. pip install gTTS") from e
        self._gTTS_cls = __import__("gtts").gtts.gTTS

    def synth(self, text: str, voice_hint: Optional[str], tmpdir: str) -> AudioSegment:
        if not text.strip():
            return silence(0.0)
        lang = "el" if is_greek(text) else "ru"
        out_path = os.path.join(tmpdir, f"chunk-{uuid.uuid4().hex}.mp3")
        self._gTTS_cls(text=text, lang=lang).save(out_path)
        return AudioSegment.from_file(out_path)

class TTS_pyttsx3(TTSBase):
    def __init__(self, rate=None):
        super().__init__(rate)
        try:
            import pyttsx3  # noqa: F401
        except Exception as e:
            raise RuntimeError("pyttsx3 not installed. pip install pyttsx3") from e
        self.pyttsx3 = __import__("pyttsx3")
        self.engine = self.pyttsx3.init()
        if rate is not None:
            try:
                self.engine.setProperty("rate", int(rate))
            except Exception:
                pass
        self.voices = self.engine.getProperty("voices")

    def _pick_voice(self, hint: Optional[str]) -> Optional[str]:
        if not hint:
            return None
        hl = hint.lower()
        for v in self.voices:
            if hl in f"{v.name}|{getattr(v,'id','')}".lower():
                return v.id
        if any(k in hl for k in ("female", "жен", "f")):
            for v in self.voices:
                if "female" in f"{v.name}|{getattr(v,'id','')}".lower():
                    return v.id
        if any(k in hl for k in ("male", "муж", "m")):
            for v in self.voices:
                if "male" in f"{v.name}|{getattr(v,'id','')}".lower():
                    return v.id
        return None

    def synth(self, text: str, voice_hint: Optional[str], tmpdir: str) -> AudioSegment:
        if not text.strip():
            return silence(0.0)
        wav_path = os.path.join(tmpdir, f"chunk-{uuid.uuid4().hex}.wav")
        vid = self._pick_voice(voice_hint)
        if vid:
            try:
                self.engine.setProperty("voice", vid)
            except Exception:
                pass
        self.engine.save_to_file(text, wav_path)
        self.engine.runAndWait()
        return AudioSegment.from_file(wav_path)

def get_tts(backend: str, rate=None) -> TTSBase:
    if backend == "edge-tts": return TTS_Edge(rate)
    if backend == "gtts":     return TTS_gTTS(rate)
    if backend == "pyttsx3":  return TTS_pyttsx3(rate)
    raise ValueError(backend)

# -------------- Builder --------------
def pick_voice(role: str, voices_decl: Dict[str, str], vmap: Dict[str, str]) -> Optional[str]:
    # приоритет у --voice-map, потом у JSON/voices, иначе None → дефолт для бэкенда
    return vmap.get(role) or voices_decl.get(role)

def normalize_text_for_role(role: Optional[str], text: str) -> str:
    if role in GREEK_ROLES and text:
        text = apply_greek_pronunciation_fixes(text)
    return text

def speak(tts: TTSBase, text: str, voice_hint: Optional[str],
          gain_db: float, gap_sec: float, tmpdir: str) -> AudioSegment:
    seg = tts.synth(text, voice_hint, tmpdir)
    if gain_db:
        seg = seg.apply_gain(gain_db)
    if gap_sec > 0:
        seg = seg + silence(gap_sec)
    return seg

def handle_play_dialogue(ev: Dict[str, Any], data: Dict[str, Any], tts: TTSBase,
                         voices_decl: Dict[str, str], vmap: Dict[str, str],
                         gain_db: float, gap_sec: float, tmpdir: str) -> AudioSegment:
    cnt = int(ev.get("count") or ev.get("times") or 1)
    dialogue = data.get("dialogue_seed", {}) or data.get("dialogue", {})
    lines: List[Dict[str, Any]] = dialogue.get("lines", [])
    out = AudioSegment.silent(0)
    for _ in range(cnt):
        for line in lines:
            role = line.get("role", "Narrator")
            text = normalize_text_for_role(role, line.get("text", ""))
            out += speak(tts, text, pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
    return out

def handle_drill_numbers(ev: Dict[str, Any], data: Dict[str, Any], tts: TTSBase,
                         voices_decl: Dict[str, str], vmap: Dict[str, str],
                         gain_db: float, gap_sec: float, tmpdir: str) -> AudioSegment:
    items = data.get("items", [])
    nums = [it for it in items if it.get("id", "").startswith("n")]
    out = AudioSegment.silent(0)
    cycle = ["A", "B"]; i = 0
    if nums:
        for it in nums:
            role = cycle[i % len(cycle)]; i += 1
            text = normalize_text_for_role(role, it.get("text", ""))
            out += speak(tts, text, pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
    else:
        rng = ev.get("range", "0-10")
        a, b = [int(x) for x in rng.split("-")]
        for n in range(a, b + 1):
            role = cycle[i % len(cycle)]; i += 1
            out += speak(tts, str(n), pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
    return out

def build_song(data: Dict[str, Any], tts: TTSBase, vmap: Dict[str, str],
               gain_db: float, gap_sec: float, respect_time: bool,
               narration_prefix: Optional[str], log: bool) -> AudioSegment:
    voices_decl = data.get("voices", {}) or {}
    timeline = data.get("timeline", []) or []
    song = AudioSegment.silent(0)
    current_ms = 0

    def align_to(target_sec: float):
        nonlocal current_ms, song
        target_ms = int(target_sec * 1000)
        if target_ms > current_ms:
            song += silence((target_ms - current_ms) / 1000.0)
            current_ms = target_ms

    with tempfile.TemporaryDirectory() as tmpdir:
        for ev in timeline:
            # абсолютная синхронизация
            if respect_time and "time" in ev:
                try:
                    align_to(parse_timecode(str(ev["time"])))
                except Exception:
                    pass

            # явная пауза
            if "pause" in ev:
                dur = parse_secs(ev["pause"])
                seg = silence(dur); song += seg; current_ms += len(seg)
                if log: print(f"[pause] +{dur:.2f}s  t={current_ms/1000:.2f}s")
                continue

            # реплики
            if "role" in ev and "text" in ev:
                role, text = ev["role"], ev["text"]
                if role == "Narrator" and narration_prefix:
                    text = f"{narration_prefix} {text}"
                text = normalize_text_for_role(role, text)
                seg = speak(tts, text, pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
                song += seg; current_ms += len(seg)
                if log:
                    short = text.replace("\n", " ")[:60]
                    print(f"[{role}] \"{short}\" +{len(seg)/1000:.2f}s  t={current_ms/1000:.2f}s")
                continue

            # спец-типы
            typ = ev.get("type")
            if typ == "play_dialogue":
                seg = handle_play_dialogue(ev, data, tts, voices_decl, vmap, gain_db, gap_sec, tmpdir)
                song += seg; current_ms += len(seg)
                if log: print(f"[play_dialogue] +{len(seg)/1000:.2f}s  t={current_ms/1000:.2f}s")
                continue
            if typ == "drill_numbers":
                seg = handle_drill_numbers(ev, data, tts, voices_decl, vmap, gain_db, gap_sec, tmpdir)
                song += seg; current_ms += len(seg)
                if log: print(f"[drill_numbers] +{len(seg)/1000:.2f}s  t={current_ms/1000:.2f}s")
                continue
            # прочее — игнор
    return song

def fallback_song(data: Dict[str, Any], tts: TTSBase, vmap: Dict[str, str],
                  gain_db: float, gap_sec: float, narration_prefix: Optional[str]) -> AudioSegment:
    # На случай JSON без timeline — простенький «эхо»-режим
    voices_decl = data.get("voices", {}) or {}
    song = AudioSegment.silent(0)
    with tempfile.TemporaryDirectory() as tmpdir:
        dlg = data.get("dialogue_seed", {}) or {}
        n = int(dlg.get("play_count_intro", 1))
        lines = dlg.get("lines", []) or []
        for _ in range(n):
            for ln in lines:
                role, text = ln.get("role", "Narrator"), ln.get("text", "")
                text = normalize_text_for_role(role, text)
                song += speak(tts, text, pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
        items = data.get("items", []) or []
        nar = pick_voice("Narrator", voices_decl, vmap)
        for it in items:
            song += speak(tts, "Повторите.", nar, gain_db, gap_sec, tmpdir)
            for role in ("A", "B"):
                text = normalize_text_for_role(role, it.get("text", ""))
                song += speak(tts, text, pick_voice(role, voices_decl, vmap), gain_db, gap_sec, tmpdir)
                song += silence(2.0)
    return song

# ----------------- CLI -----------------
def parse_txt_to_timeline(txt_path: str) -> List[Dict[str, Any]]:
    """Парсит OUTPUT.txt и создает timeline для build_pimsleur_mp3.py"""
    import re
    
    with open(txt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    timeline = []
    
    greek_line_index = 0
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        
        if not line:
            continue
            
        # Обрабатываем паузы
        pause_match = re.match(r'\[PAUSE:\s*([\d.]+)s\]', line)
        if pause_match:
            pause_duration = float(pause_match.group(1))
            timeline.append({
                "type": "pause",
                "pause": pause_duration
            })
            continue
        
        # Определяем роль по языку
        if re.search(r"[Α-Ωα-ωάέήίόύώϊΐϋΰ]", line):
            greek_line_index += 1
            role = "A" if greek_line_index % 2 == 1 else "B"
        else:
            role = "Narrator"
        
        # Добавляем реплику в timeline
        timeline.append({
            "role": role,
            "text": line
        })
    
    return timeline

def main():
    ap = argparse.ArgumentParser(description="Build MP3/WAV from a Pimsleur-style JSON lesson or TXT file.")
    ap.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_TIMELINE_PATH),
        help=f"Input JSON file or TXT file (default: {DEFAULT_TIMELINE_PATH})"
    )
    ap.add_argument("-o", "--output", default=str(DEFAULT_AUDIO_PATH), help=f"Output file (mp3 or wav). Default: {DEFAULT_AUDIO_PATH}")
    ap.add_argument("--backend", choices=["edge-tts", "gtts", "pyttsx3"], default="edge-tts")
    ap.add_argument("--voice-map", default=None, help="JSON string or path: map roles to voices (overrides JSON voices)")
    ap.add_argument("--rate", default=None, help="Edge: '+0%', '+10%'; pyttsx3: '175'")
    ap.add_argument("--volume", type=float, default=0.0, help="Gain (dB) per chunk, e.g. 0, +6")
    ap.add_argument("--gap", type=float, default=0.25, help="Silence between chunks (seconds)")
    ap.add_argument("--respect-time", type=str, default="true", help="Respect event['time'] (true/false)")
    ap.add_argument("--pad-to-target", type=str, default="true", help="Pad to lesson.target_duration_sec (true/false)")
    ap.add_argument("--narration-prefix", default=None, help="Prefix for Narrator lines")
    ap.add_argument("--log", action="store_true", default=True, help="Enable verbose logging (default: on)")
    ap.add_argument("--no-log", dest="log", action="store_false", help="Disable verbose logging")
    args = ap.parse_args()

    # Проверяем тип входного файла
    if args.input_path.endswith('.txt'):
        # Обрабатываем TXT файл
        timeline = parse_txt_to_timeline(args.input_path)
        data = {
            "lesson": {
                "id": "greco-pimsleur-lesson",
                "title": "Greek Language Learning - Pimsleur Method",
                "description": "Generated from OUTPUT.txt with full repetitions and pauses"
            },
            "voices": {
                "Narrator": "en-US-AriaNeural",
                "A": "el-GR-AthinaNeural",
                "B": "el-GR-NestorasNeural"
            },
            "timeline": timeline,
            "export": {
                "filename": "greco-pimsleur-lesson.mp3"
            }
        }
    else:
        # Обрабатываем JSON файл
        data = load_json(args.input_path)
    vmap = load_voice_map(args.voice_map)
    out_path = args.output or data.get("export", {}).get("filename") \
               or f"lesson_{(data.get('lesson') or {}).get('id', Path(args.input_path).stem)}.mp3"

    tts = get_tts(args.backend, rate=args.rate)
    respect_time = args.respect_time.lower() in ("1", "true", "yes", "y", "on")
    pad_to_target = args.pad_to_target.lower() in ("1", "true", "yes", "y", "on")

    if data.get("timeline"):
        song = build_song(data, tts, vmap, args.volume, args.gap, respect_time, args.narration_prefix, args.log)
    else:
        song = fallback_song(data, tts, vmap, args.volume, args.gap, args.narration_prefix)

    # Дотягивание до target_duration_sec, если задан и включено
    tgt = (data.get("lesson") or {}).get("target_duration_sec")
    if pad_to_target and isinstance(tgt, (int, float)) and tgt > 0:
        cur = len(song) / 1000.0
        if cur < tgt:
            song += silence(tgt - cur)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fmt = "mp3" if out_path.lower().endswith(".mp3") else "wav"
    if fmt == "mp3":
        song.export(out_path, format="mp3", bitrate="192k")
    else:
        song.export(out_path, format="wav")
    if args.log:
        print(f"[DONE] saved {out_path}")

if __name__ == "__main__":
    main()
