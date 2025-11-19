import whisper
import os

# === НАСТРОЙКИ ===
AUDIO_FILE = "audio.mp3"  # имя файла в той же папке
MODEL_SIZE = "medium"     # можно: tiny, base, small, medium, large

# === ЗАГРУЗКА МОДЕЛИ ===
print(f"Загружаю модель Whisper ({MODEL_SIZE})...")
model = whisper.load_model(MODEL_SIZE)

# === ТРАНСКРИПЦИЯ ===
print(f"Обрабатываю файл: {AUDIO_FILE}")
result = model.transcribe(AUDIO_FILE)

# === СОХРАНЕНИЕ ПОЛНОГО ТЕКСТА ===
with open("transcript.txt", "w", encoding="utf-8") as f:
    f.write(result["text"])
print("✔️ Сохранено: transcript.txt")

# === СОХРАНЕНИЕ В SRT-ФОРМАТ ===
def format_timestamp(seconds: float) -> str:
    # Преобразует секунды в формат SRT
    millis = int(seconds * 1000)
    hours = millis // 3600000
    minutes = (millis % 3600000) // 60000
    seconds = (millis % 60000) // 1000
    milliseconds = millis % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

with open("subtitles.srt", "w", encoding="utf-8") as f:
    for i, segment in enumerate(result["segments"], start=1):
        start = format_timestamp(segment["start"])
        end = format_timestamp(segment["end"])
        text = segment["text"].strip()

        f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

print("✔️ Сохранено: subtitles.srt")