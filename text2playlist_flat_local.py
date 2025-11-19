#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
import argostranslate.package
import argostranslate.translate
import time

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")

SENTENCE_SPLIT_RE = re.compile(r'[^.!?…]+[.!?…]+|[^.!?…]+$')
FEMALE_ROLE = "A"
MALE_ROLE = "B"


# Явные подстановки: греческий текст -> желаемый английский эквивалент
TRANSLATION_OVERRIDES = {
    "«Στον δρόμο»": "On the street",
    "Στον δρόμο": "On the street",
    "Στον δρόμο.": "On the street.",
    "Στο δρόμο": "On the street",
    "«Στη γραμματεία»": "At the registrar's office",
    "Στη γραμματεία": "At the registrar's office",
    "«Στο μάθημα»": "In class",
    "Στο μάθημα": "In class",
    "Γεια σου, Παναγιώτη!": "Hello, Panagiotis!",
    "Παναγιώτη!": "Panagiotis!",
    "Τι κάνεις;": "What are you doing?",
    "Τι κάνετε;": "What are you doing?",
    "Πού είναι;": "Where is it?",
    "Καλημέρα, παιδιά.": "Good morning, everyone.",
    "Έχετε κι ένα e-mail;": "Do you have an email?",
    "Έχετε κι ένα e‑mail;": "Do you have an email?",
    "Δεν έχω e-mail.": "I don't have an email.",
    "Δεν έχω e‑mail.": "I don't have an email.",
    "Ναι, το τηλέφωνό σας είναι αυτό.": "Yes, that's your phone number.",
    "Το τηλέφωνό σας το σημειώνω.": "I'm writing down your phone number.",
    "Μένω στην Αθήνα, στην Κυψέλη.": "I live in Kypseli, Athens.",
    "Μένω στην Ελλάδα, στην Αθήνα, στην Κυψέλη.": "I live in Kypseli, Athens, Greece.",
    "Εμείς μένουμε στην Κυψέλη.": "We live in Kypseli.",
    "Τα παιδιά μένουν στην Κίνα τώρα.": "The children live in China now.",
    "Ο Φου και ο Παναγιώτης δε μένουν κοντά.": "Fu and Panagiotis don't live close by.",
}

# Регулярные шаблоны: позволяют подставлять параметры (например, номера телефонов)
PATTERN_OVERRIDES = [
    (
        re.compile(r"^Ναι, το σταθερό μου είναι (?P<landline>[\d\s]+) και το κινητό μου (?P<mobile>[\d\s]+)\.?$"),
        lambda m: f"Yes, my landline is {m.group('landline').strip()} and my mobile phone is {m.group('mobile').strip()}.",
    ),
    (
        re.compile(r"^Δεν έχω σταθερό, έχω μόνο κινητό[: ]*(?P<mobile>[\d\s]+)\.?$"),
        lambda m: f"I don't have a landline; I only have a mobile phone: {m.group('mobile').strip()}.",
    ),
]


def postprocess_translation(source: str, translated: str) -> str:
    """Корректирует известные ошибки движка перевода"""
    # Простые глобальные замены
    replacements = {
        "e - mail": "email",
        "e-mail": "email",
        "E-mail": "Email",
    }
    for wrong, right in replacements.items():
        translated = translated.replace(wrong, right)

    if "Παναγιώ" in source:
        translated = translated.replace("Holy shit", "Panagiotis")
        translated = translated.replace("Holy shit!", "Panagiotis!")
        translated = translated.replace("Panagioti", "Panagiotis")

    if "Κυψέλη" in source:
        translated = re.sub(r"\b[Kk]ipseli\b", "Kypseli", translated)
        translated = re.sub(r"\b[Hh]ive\b", "Kypseli", translated)

    if "δε μένουν" in source:
        translated = translated.replace("don't stay", "don't live")

    if "Τα παιδιά" in source:
        translated = translated.replace("Kids", "The children")
        translated = translated.replace("kids", "children")

    return translated


def tokenize(text: str) -> list:
    """Разбивает текст на слова с сохранением знаков препинания"""
    # Регулярное выражение для поиска слов с возможными знаками препинания после них
    WORD_RE = re.compile(
        r"[0-9A-Za-zΑ-Ωα-ωάέήίόύώϊΐϋΰЁёА-Яа-я]+(?:[''][0-9A-Za-zΑ-Ωα-ωάέήίόύώϊΐϋΰЁёА-Яа-я]+)?[.,;:!?…()—\"'«»]*",
        re.UNICODE,
    )
    return WORD_RE.findall(text)

def calculate_speech_time(text: str) -> float:
    """Рассчитывает время звучания текста в секундах"""
    # Убираем знаки препинания для подсчета слов
    clean_text = re.sub(r'[.,;:!?…()—"\'«»]', '', text)
    words = clean_text.split()
    
    # Средняя скорость речи: 150-160 слов в минуту (2.5-2.67 слова в секунду)
    # Используем 2.5 слова в секунду для более медленной, понятной речи
    words_per_second = 2.5
    
    # Добавляем время на паузы между словами (0.1 секунды на слово)
    pause_time = len(words) * 0.1
    
    # Общее время = время произношения + паузы
    total_time = (len(words) / words_per_second) + pause_time
    
    # Минимальное время 0.5 секунды для коротких слов
    return max(0.5, round(total_time, 2))

def translate_text(text: str) -> str:
    """Переводит греческий текст на английский"""
    try:
        stripped = text.strip()

        # Cначала проверяем явные подстановки
        override = TRANSLATION_OVERRIDES.get(stripped)
        if override is not None:
            return override

        # Затем регулярные шаблоны с числами
        for pattern, builder in PATTERN_OVERRIDES:
            match = pattern.match(stripped)
            if match:
                return builder(match)

        # Устанавливаем языки перевода
        from_code = "el"
        to_code = "en"

        translated = argostranslate.translate.translate(text, from_code, to_code)
        return postprocess_translation(stripped, translated)
    except Exception as e:
        print(f"Ошибка перевода: {e}")
        return f"[Translation error: {text}]"

def add_repeat_instruction(text: str) -> str:
    """Возвращает текст без изменений (инструкция убрана)"""
    return text

def split_into_sentences(line: str) -> list:
    """Разделяет диалоговую строку на предложения, сохраняя пунктуацию."""
    if not line:
        return []
    stripped = line.strip()
    if not stripped:
        return []
    prefix = ''
    if stripped.startswith('—'):
        stripped = stripped.lstrip('—').strip()
        prefix = '— '
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.findall(stripped)]
    sentences = []
    first = True
    for part in parts:
        if not part:
            continue
        if first and prefix:
            sentences.append(f"{prefix}{part}")
            first = False
        else:
            sentences.append(part)
    return sentences

def prepare_lines(text: str) -> list:
    """Готовит список предложений из исходного текста диалога."""
    sentences = []
    for raw_line in text.split('\n'):
        stripped = raw_line.strip()
        if not stripped:
            continue
        sentences.extend(split_into_sentences(stripped))
    return [s.strip() for s in sentences if s.strip()]

def setup_translator():
    """Настраивает переводчик"""
    try:
        # Устанавливаем языки перевода
        from_code = "el"  # греческий
        to_code = "en"    # английский
        
        # Проверяем доступные пакеты
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            filter(
                lambda x: x.from_code == from_code and x.to_code == to_code, available_packages
            )
        )
        
        # Устанавливаем пакет если нужно
        argostranslate.package.install_from_path(package_to_install.download())
        print(f"✅ Переводчик настроен: {from_code} -> {to_code}")
        return True
    except Exception as e:
        print(f"❌ Ошибка настройки переводчика: {e}")
        return False

def main():
    # Настраиваем переводчик
    print("🔧 Настройка переводчика...")
    if not setup_translator():
        print("❌ Не удалось настроить переводчик. Продолжаем без перевода.")
        return
    
    # Читаем файл TEXT.txt
    input_file = INPUT_DIR / "TEXT.txt"
    if not input_file.exists():
        print(f"❌ Файл {input_file} не найден!")
        return
    
    print(f"📁 Читаем файл: {input_file}")
    
    # Читаем текст и разбиваем по строкам
    with open(input_file, 'r', encoding='utf-8') as f:
        text = f.read().strip()
    
    # Подготавливаем предложения, учитывая точки внутри строки
    lines = prepare_lines(text)
    print(f"📄 Найдено {len(lines)} предложений")
    
    sentences_data = []
    
    # Создаем словарь для отслеживания уже использованных слов с count=3
    used_words_with_count_3 = set()
    used_sentences_with_count_3 = set()  # Отдельный трекер для предложений
    
    for i, line in enumerate(lines):
        # Убираем тире в начале строки если есть
        greek_role = FEMALE_ROLE if (i % 2 == 0) else MALE_ROLE
        sentence = line.lstrip('— ')
        
        # Разбиваем предложение на слова
        words_raw = tokenize(sentence)
        
        # Создаем массив слов с переводами
        words = []
        for word in words_raw:
            # Переводим слово
            word_translation = translate_text(word)
            
            # Проверяем, было ли слово уже с count=3
            is_repeat = word not in used_words_with_count_3
            greek_count = 3 if is_repeat else 1
            
            words.append({
                "role": greek_role,
                "english": {
                    "text": add_repeat_instruction(word_translation),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(word_translation))
                },
                "greek": {
                    "text": word,
                    "count": greek_count,
                    "pause": calculate_speech_time(word),
                    "repeat": is_repeat
                }
            })
            
            # Добавляем слово в список использованных с count=3 (после создания объекта)
            used_words_with_count_3.add(word)
        
        # Создаем нарастающие словосочетания (от 2 слов до всего предложения)
        phrases = []
        for phrase_len in range(2, len(words) + 1):
            # Собираем греческие слова для словосочетания
            greek_words = [word["greek"]["text"] for word in words[:phrase_len]]
            phrase = " ".join(greek_words)
            # Переводим словосочетание
            phrase_translation = translate_text(phrase)
            
            # Проверяем, было ли словосочетание уже с count=3
            is_phrase_repeat = phrase not in used_words_with_count_3
            greek_phrase_count = 3 if is_phrase_repeat else 1
            
            phrases.append({
                "role": greek_role,
                "english": {
                    "text": add_repeat_instruction(phrase_translation),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(phrase_translation))
                },
                "greek": {
                    "text": phrase,
                    "count": greek_phrase_count,
                    "pause": calculate_speech_time(phrase),
                    "repeat": is_phrase_repeat
                }
            })
            
            # Добавляем словосочетание в список использованных с count=3 (после создания объекта)
            used_words_with_count_3.add(phrase)
        
        # Переводим предложение
        print(f"  🔄 Переводим: '{sentence[:30]}{'...' if len(sentence) > 30 else ''}'")
        english_translation = translate_text(sentence)
        
        # Проверяем, было ли предложение уже с count=3
        is_sentence_repeat = sentence not in used_sentences_with_count_3
        greek_sentence_count = 3 if is_sentence_repeat else 1
        
        # Создаем объект для предложения
        sentence_obj = {
            "sentence": {
                "english": {
                    "text": add_repeat_instruction(english_translation),
                    "count": 1,
                    "pause": calculate_speech_time(add_repeat_instruction(english_translation))
                },
                "greek": {
                    "text": sentence,
                    "count": greek_sentence_count,
                    "pause": calculate_speech_time(sentence),
                    "repeat": is_sentence_repeat
                }
            },
            "words": words,
            "phrases": phrases
        }
        
        sentence_obj['role'] = greek_role
        sentences_data.append(sentence_obj)
        
        # Добавляем предложение в список использованных с count=3 (после создания объекта)
        used_sentences_with_count_3.add(sentence)
        
        print(f"  📝 Строка {i+1}: '{sentence[:50]}{'...' if len(sentence) > 50 else ''}' -> {len(words)} слов, {len(phrases)} словосочетаний")
    
    # Создаем нарастающие объединения предложений
    print("\n🔄 Переводим объединенные предложения...")
    combined_sentences = []
    accumulated_sentence = ""
    
    for i, sentence_obj in enumerate(sentences_data):
        greek_role = sentence_obj.get('role', FEMALE_ROLE)
        if i == 0:
            accumulated_sentence = sentence_obj["sentence"]["greek"]["text"]
        else:
            accumulated_sentence += " " + sentence_obj["sentence"]["greek"]["text"]
        
        # Переводим объединенное предложение
        print(f"  🔄 Переводим объединение {i+1}: '{accumulated_sentence[:50]}{'...' if len(accumulated_sentence) > 50 else ''}'")
        english_translation = translate_text(accumulated_sentence)
        
        # Проверяем, было ли объединенное предложение уже с count=3
        is_combined_repeat = accumulated_sentence not in used_words_with_count_3
        greek_combined_count = 3 if is_combined_repeat else 1
        
        combined_entry = {
            "english": {
                "text": add_repeat_instruction(english_translation),
                "count": 1,
                "pause": calculate_speech_time(add_repeat_instruction(english_translation))
            },
            "greek": {
                "text": accumulated_sentence,
                "count": greek_combined_count,
                "pause": calculate_speech_time(accumulated_sentence),
                "repeat": is_combined_repeat
            }
        }
        combined_entry['role'] = greek_role
        combined_sentences.append(combined_entry)
        
        # Добавляем объединенное предложение в список использованных с count=3 (после создания объекта)
        used_words_with_count_3.add(accumulated_sentence)
    
    # Создаем финальную структуру данных
    final_data = {
        "data": sentences_data,
        "sentences": combined_sentences
    }
    
    # Сохраняем в JSON файл
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "TEXT.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 JSON файл сохранен: {output_file}")
    print(f"📊 Размер JSON: {output_file.stat().st_size} байт")
    
    # Теперь формируем TXT файл из JSON
    print(f"\n🔄 Формируем TXT файл из JSON...")
    
    # Получаем массив data
    sentences_data = final_data.get("data", [])
    print(f"📊 Найдено {len(sentences_data)} предложений в массиве data")
    
    # Формируем новый TXT файл
    output_lines = []
    
    # Обрабатываем все элементы массива data
    for sentence_idx, sentence_data in enumerate(sentences_data):
        print(f"\n📝 Обрабатываем предложение {sentence_idx + 1}")
        
        # Обрабатываем sentence объект
        sentence_obj = sentence_data.get("sentence", {})
        english_sentence_obj = sentence_obj.get("english", {})
        greek_sentence_obj = sentence_obj.get("greek", {})
        
        # Английское предложение
        english_text = english_sentence_obj.get("text", "")
        english_count = english_sentence_obj.get("count", 1)
        english_pause = english_sentence_obj.get("pause", 0)
        
        if english_text:
            # Записываем английское предложение count раз с паузами
            for repeat_idx in range(english_count):
                output_lines.append(english_text)
                print(f"  ✅ Английское предложение {repeat_idx+1}/{english_count}: '{english_text[:30]}{'...' if len(english_text) > 30 else ''}'")
                
                # Добавляем паузу между повторениями (кроме последнего)
                if repeat_idx < english_count - 1 and english_pause > 0:
                    output_lines.append(f"[PAUSE: {english_pause}s]")
                    print(f"  ⏸️  Пауза: {english_pause} секунд")
        
        # Греческое предложение
        greek_text = greek_sentence_obj.get("text", "")
        greek_count = greek_sentence_obj.get("count", 1)
        greek_pause = greek_sentence_obj.get("pause", 0)
        
        if greek_text:
            # Записываем греческое предложение count раз с паузами
            for repeat_idx in range(greek_count):
                output_lines.append(greek_text)
                print(f"  ✅ Греческое предложение {repeat_idx+1}/{greek_count}: '{greek_text[:30]}{'...' if len(greek_text) > 30 else ''}'")
                
                # Добавляем паузу между повторениями (кроме последнего)
                if repeat_idx < greek_count - 1 and greek_pause > 0:
                    output_lines.append(f"[PAUSE: {greek_pause}s]")
                    print(f"  ⏸️  Пауза: {greek_pause} секунд")
        
        # Пауза после предложения не добавляется - паузы только между повторениями
        
        # Обрабатываем массив words
        words_array = sentence_data.get("words", [])
        print(f"  📝 Обрабатываем {len(words_array)} слов")
        
        for word_idx, word_obj in enumerate(words_array):
            english_word_obj = word_obj.get("english", {})
            greek_word_obj = word_obj.get("greek", {})
            
            # Английское слово
            english_word_text = english_word_obj.get("text", "")
            english_word_count = english_word_obj.get("count", 1)
            english_word_pause = english_word_obj.get("pause", 0)
            
            if english_word_text:
                # Записываем английское слово count раз с паузами
                for repeat_idx in range(english_word_count):
                    output_lines.append(english_word_text)
                    print(f"    ✅ Английское слово {word_idx+1} {repeat_idx+1}/{english_word_count}: '{english_word_text[:20]}{'...' if len(english_word_text) > 20 else ''}'")
                    
                    # Добавляем паузу между повторениями (кроме последнего)
                    if repeat_idx < english_word_count - 1 and english_word_pause > 0:
                        output_lines.append(f"[PAUSE: {english_word_pause}s]")
                        print(f"    ⏸️  Пауза: {english_word_pause} секунд")
            
            # Греческое слово
            greek_word_text = greek_word_obj.get("text", "")
            greek_word_count = greek_word_obj.get("count", 1)
            greek_word_pause = greek_word_obj.get("pause", 0)
            
            if greek_word_text:
                # Записываем греческое слово count раз с паузами
                for repeat_idx in range(greek_word_count):
                    output_lines.append(greek_word_text)
                    print(f"    ✅ Греческое слово {word_idx+1} {repeat_idx+1}/{greek_word_count}: '{greek_word_text[:20]}{'...' if len(greek_word_text) > 20 else ''}'")
                    
                    # Добавляем паузу между повторениями (кроме последнего)
                    if repeat_idx < greek_word_count - 1 and greek_word_pause > 0:
                        output_lines.append(f"[PAUSE: {greek_word_pause}s]")
                        print(f"    ⏸️  Пауза: {greek_word_pause} секунд")
            
            # Пауза после слова не добавляется - паузы только между повторениями
        
        # Обрабатываем массив phrases
        phrases_array = sentence_data.get("phrases", [])
        print(f"  📝 Обрабатываем {len(phrases_array)} словосочетаний")
        
        for phrase_idx, phrase_obj in enumerate(phrases_array):
            english_phrase_obj = phrase_obj.get("english", {})
            greek_phrase_obj = phrase_obj.get("greek", {})
            
            # Английское словосочетание
            english_phrase_text = english_phrase_obj.get("text", "")
            english_phrase_count = english_phrase_obj.get("count", 1)
            english_phrase_pause = english_phrase_obj.get("pause", 0)
            
            if english_phrase_text:
                # Записываем английское словосочетание count раз с паузами
                for repeat_idx in range(english_phrase_count):
                    output_lines.append(english_phrase_text)
                    print(f"    ✅ Английское словосочетание {phrase_idx+1} {repeat_idx+1}/{english_phrase_count}: '{english_phrase_text[:25]}{'...' if len(english_phrase_text) > 25 else ''}'")
                    
                    # Добавляем паузу между повторениями (кроме последнего)
                    if repeat_idx < english_phrase_count - 1 and english_phrase_pause > 0:
                        output_lines.append(f"[PAUSE: {english_phrase_pause}s]")
                        print(f"    ⏸️  Пауза: {english_phrase_pause} секунд")
            
            # Греческое словосочетание
            greek_phrase_text = greek_phrase_obj.get("text", "")
            greek_phrase_count = greek_phrase_obj.get("count", 1)
            greek_phrase_pause = greek_phrase_obj.get("pause", 0)
            
            if greek_phrase_text:
                # Записываем греческое словосочетание count раз с паузами
                for repeat_idx in range(greek_phrase_count):
                    output_lines.append(greek_phrase_text)
                    print(f"    ✅ Греческое словосочетание {phrase_idx+1} {repeat_idx+1}/{greek_phrase_count}: '{greek_phrase_text[:25]}{'...' if len(greek_phrase_text) > 25 else ''}'")
                    
                    # Добавляем паузу между повторениями (кроме последнего)
                    if repeat_idx < greek_phrase_count - 1 and greek_phrase_pause > 0:
                        output_lines.append(f"[PAUSE: {greek_phrase_pause}s]")
                        print(f"    ⏸️  Пауза: {greek_phrase_pause} секунд")
            
            # Пауза после словосочетания не добавляется - паузы только между повторениями
    
    if not sentences_data:
        print("❌ Массив data пуст")
    
    # Сохраняем результат в TXT файл
    txt_output_file = OUTPUT_DIR / "OUTPUT.txt"
    with open(txt_output_file, 'w', encoding='utf-8') as f:
        for line in output_lines:
            f.write(line + '\n')
    
    print(f"💾 TXT файл сохранен: {txt_output_file}")
    print(f"📊 Записано строк: {len(output_lines)}")
    
    print(f"\n============================================================")
    print(f"🎉 ОБРАБОТКА ЗАВЕРШЕНА!")
    print(f"📁 Созданы файлы: {output_file} и {txt_output_file}")
    print(f"============================================================")

if __name__ == "__main__":
    main()
