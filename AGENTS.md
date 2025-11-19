# Repository Guidelines
Отвечай всегда по-русски

## Project Structure & Module Organization
The repository contains Python utilities for producing Greek learning materials. Root-level scripts form a linear flow: `transcribe.py` runs Whisper on `audio.mp3`, `text2playlist_flat_local.py` converts curated `TEXT.txt` prompts into `TEXT.json` plus a flattened narration script, and `build_pimsleur_mp3.py` turns lesson JSON into timed MP3 output through a TTS backend. Supporting spreadsheet helpers and sample subtitle assets live in `result/`; place experimental CSV/XLSX files there to keep the root clean. Generated audio, Whisper model weights, and Argos translation packages should remain local-only and excluded from version control.

## Build, Test, and Development Commands
Work in Python 3.10+ virtual environments so native dependencies stay isolated. Typical workflow:
- `python3 -m venv .venv && source .venv/bin/activate`
- `pip install argostranslate pydub edge-tts openai-whisper pandas openpyxl`
- `python text2playlist_flat_local.py` regenerates `TEXT.json` and an updated narration TXT.
- `python build_pimsleur_mp3.py lesson.json -o lesson.mp3 --backend edge-tts` synthesizes audio (requires `ffmpeg`).
- `python transcribe.py` expects `audio.mp3` beside the script and writes `transcript.txt` plus `subtitles.srt`.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation, snake_case function names, and PascalCase for TTS backend classes. Keep modules import-safe by wrapping script entrypoints in `if __name__ == "__main__":` when adding new tools. Inline comments should explain non-obvious heuristics such as repeat counts or pause calculations, while docstrings state intent concisely.

## Testing Guidelines
No automated suite exists; validate changes by re-running the relevant script and reviewing outputs. For playlist generation, diff the regenerated `TEXT.json` against prior revisions and spot-check the timing metadata. Spreadsheet utilities should be exercised against copies of the sample SRT/CSV files in `result/`, keeping originals untouched. Document any manual verification steps or sample commands in your pull request so reviewers can reproduce them quickly.

## Commit & Pull Request Guidelines
Repository history uses short, lower-case summaries (e.g., `first commit`), so continue with concise, imperative messages under 72 characters and optionally prefix the touched tool (`update text2playlist pipeline`). Pull requests should describe the motivation, list new commands or flags, and include representative before/after file paths. When new dependencies or voice packs are introduced, call them out explicitly and note installation hints for reviewers.

## Audio & Configuration Hygiene
Do not check in MP3 renders, Whisper checkpoints, or Argos language downloads; reference their locations in documentation instead. Confirm `ffmpeg -version` before running audio synthesis, and keep API keys or service tokens in local environment variables rather than source files.
