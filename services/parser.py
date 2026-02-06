import re
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)

def parse_dtek_message(text):
    """
    Аналізує текст повідомлення і шукає графік для групи (наприклад 3.2).
    Повертає список кортежів: [('08:00', '12:00'), ('16:00', '20:00')]
    """
    if not text:
        return []
    
    text = text.lower()
    
    # 1. Фільтр: чи це про нас?
    if "3.2" not in text and "групи 3" not in text and "група 3.2" not in text:
        return []
    
    logger.info("🔍 Знайдено згадку групи 3.2, аналізую графік...")
    
    ranges = []
    
    # 2. Шукаємо пари часу: "HH:MM - HH:MM" або "з HH:MM до HH:MM"
    # Регулярка ловить: 08:00, 8:00, 8.00
    pattern_range = r'(\d{1,2}[:.\s]*\d{2})\s*(?:-|до|–|—)\s*(\d{1,2}[:.\s]*\d{2})'
    matches = re.findall(pattern_range, text)
    
    for start, end in matches:
        # Нормалізуємо: прибираємо пробіли, крапки на двокрапки (08.00 -> 08:00)
        start_clean = start.replace('.', ':').replace(' ', '')
        end_clean = end.replace('.', ':').replace(' ', '')
        
        # Перевіряємо формат
        try:
            datetime.strptime(start_clean, "%H:%M")
            datetime.strptime(end_clean, "%H:%M")
            ranges.append((start_clean, end_clean))
            logger.info(f"✅ Знайдено діапазон: {start_clean} - {end_clean}")
        except ValueError:
            logger.warning(f"⚠️ Неправильний формат часу: {start} - {end}")
            continue
    
    # 3. Шукаємо одинарний час: "до HH:MM" (значить початок - зараз)
    if not ranges and "до" in text:
        pattern_until = r'до\s*(\d{1,2}[:.\s]*\d{2})'
        singles = re.findall(pattern_until, text)
        for end in singles:
            # Поточний час як початок
            start_now = datetime.now(config.KYIV).strftime("%H:%M")
            end_clean = end.replace('.', ':').replace(' ', '')
            
            try:
                datetime.strptime(end_clean, "%H:%M")
                ranges.append((start_now, end_clean))
                logger.info(f"✅ Знайдено діапазон (від зараз): {start_now} - {end_clean}")
            except ValueError:
                logger.warning(f"⚠️ Неправильний формат часу: {end}")
                continue
    
    if ranges:
        logger.info(f"📋 Всього знайдено діапазонів: {len(ranges)}")
    else:
        logger.info("ℹ️ Графік не розпізнано")
    
    return ranges
