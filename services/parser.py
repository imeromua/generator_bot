import re
from datetime import datetime
import config

def parse_dtek_message(text):
    """
    Аналізує текст повідомлення і шукає графік для групи (наприклад 3.2).
    Повертає список кортежів: [('08:00', '12:00'), ('16:00', '20:00')]
    """
    text = text.lower()
    
    # 1. Фільтр: чи це про нас?
    # Можна додати інші ключові слова в config, якщо треба
    if "3.2" not in text and "групи 3" not in text:
        return []
    
    ranges = []
    
    # 2. Шукаємо пари часу: "HH:MM - HH:MM" або "з HH:MM до HH:MM"
    # Регулярка ловить: 08:00, 8:00, 8.00
    pattern_range = r'(\d{1,2}[:.]\d{2})\s*(?:-|до|–)\s*(\d{1,2}[:.]\d{2})'
    matches = re.findall(pattern_range, text)
    
    for start, end in matches:
        # Нормалізуємо крапки на двокрапки (08.00 -> 08:00)
        ranges.append((start.replace('.', ':'), end.replace('.', ':')))
    
    # 3. Шукаємо одинарний час: "до HH:MM" (значить початок - зараз)
    if not ranges and "до" in text:
        pattern_until = r'до\s*(\d{1,2}[:.]\d{2})'
        singles = re.findall(pattern_until, text)
        for end in singles:
            # Поточний час як початок
            start_now = datetime.now(config.KYIV).strftime("%H:%M")
            ranges.append((start_now, end.replace('.', ':')))
            
    return ranges